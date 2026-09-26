"""События сети: закрытия, укорочения, ручные множители.

Реальное состояние сети, а не what-if: маршрут действительно закрыт на
ремонт, а не «что будет, если пойдёт дождь». Поэтому события хранятся
на сервере и видны всем пользователям, а не приходят параметрами запроса.

Порядок применения (контракт, docs/stas-mvp-architecture.md, раздел 26):

    1. активно FULL_CLOSURE     → prediction = 0, абсолютный приоритет:
                                  ни погода, ни ползунки не возвращают
                                  пассажиров на закрытый маршрут;
    2. иначе                    → prediction *= произведение factor
                                  активных SHORTENING и MANUAL_MULTIPLIER;
    3. в конце                  → prediction = max(prediction, 0).

`model_prediction` не меняется: эффект считается на запросе от базы
умножением, без обучения и без SQL.

Хранилище спрятано за NetworkEventRepository. Сейчас это JSON-файл,
загружаемый в память на старте; замена на DuckDB или PostgreSQL трогает
только реализацию репозитория (repository boundary из контракта).
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timezone
from pathlib import Path

from app.pipeline.shared_state import atomic_write, file_lock, signature

log = logging.getLogger(__name__)

FULL_CLOSURE = "FULL_CLOSURE"
SHORTENING = "SHORTENING"
MANUAL_MULTIPLIER = "MANUAL_MULTIPLIER"
EVENT_TYPES = (FULL_CLOSURE, SHORTENING, MANUAL_MULTIPLIER)


@dataclass(frozen=True)
class NetworkEvent:
    id: int
    route: int
    type: str
    valid_from: date
    valid_to: date | None      # None — «до отмены», авария с неизвестным концом
    hour_from: int | None      # None — все сутки
    hour_to: int | None
    factor: float | None       # None у FULL_CLOSURE
    title: str
    source_url: str | None
    active: bool
    created_at: str

    def covers_day(self, day: date) -> bool:
        if day < self.valid_from:
            return False
        return self.valid_to is None or day <= self.valid_to

    def covers_hour(self, hour: int) -> bool:
        start = 0 if self.hour_from is None else self.hour_from
        end = 23 if self.hour_to is None else self.hour_to
        if start <= end:
            return start <= hour <= end
        # Ночное окно через полночь, например 22–02.
        return hour >= start or hour <= end

    def overlaps(self, start: date | None, end: date | None) -> bool:
        if end is not None and self.valid_from > end:
            return False
        if start is not None and self.valid_to is not None and self.valid_to < start:
            return False
        return True

    def identity(self) -> tuple:
        """По этим полям два события считаются одним и тем же (409)."""
        return (
            self.route, self.type, self.valid_from, self.valid_to,
            self.hour_from, self.hour_to, self.factor,
        )

    def as_dict(self) -> dict:
        data = asdict(self)
        data["valid_from"] = self.valid_from.isoformat()
        data["valid_to"] = self.valid_to.isoformat() if self.valid_to else None
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "NetworkEvent":
        valid_to = data.get("valid_to")
        return cls(
            id=int(data["id"]),
            route=int(data["route"]),
            type=str(data["type"]),
            valid_from=date.fromisoformat(data["valid_from"]),
            valid_to=date.fromisoformat(valid_to) if valid_to else None,
            hour_from=data.get("hour_from"),
            hour_to=data.get("hour_to"),
            factor=data.get("factor"),
            title=data.get("title") or "",
            source_url=data.get("source_url"),
            active=bool(data.get("active", True)),
            created_at=data.get("created_at") or "",
        )


@dataclass(frozen=True)
class SecondaryRule:
    """Измеренный вторичный эффект: закрытие маршрута-источника меняет
    спрос на маршруте-цели. Только измеренные правила (раздел 23 контракта):
    ml/transfer_experiment.py, artifacts/transfer_experiment.md."""

    event_type: str
    source_route: int
    target_route: int
    factor: float
    evidence: str
    caveat: str

    def describe(self, closure: "NetworkEvent") -> dict:
        return {
            "kind": "secondary",
            "event_type": self.event_type,
            "source_route": self.source_route,
            "target_route": self.target_route,
            "factor": self.factor,
            "source_event_id": closure.id,
            "valid_from": closure.valid_from.isoformat(),
            "valid_to": closure.valid_to.isoformat() if closure.valid_to else None,
            "label": (
                f"Маршрут {self.target_route} ×{self.factor:.3f}: перетекание "
                f"пассажиров при закрытии маршрута {self.source_route}"
            ),
            "evidence": self.evidence,
            "caveat": self.caveat,
        }


SECONDARY_RULES = (
    SecondaryRule(
        event_type=FULL_CLOSURE,
        source_route=17,
        target_route=11,
        factor=1.1079,
        evidence=(
            "4 из 4 дней > 1 (1.028–1.143), шум 4.3%, placebo p < 0.0001, "
            "без любого одного дня 1.084–1.131"
        ),
        caveat=(
            "Измерено на 4 выходных днях апреля 2025; маршрут 17 тогда возил "
            "1–13% обычного объёма, а не ноль; перенос на будни — экстраполяция"
        ),
    ),
)


class NetworkEffect:
    """Неизменяемый снимок активных событий для hot path.

    Пересобирается целиком при каждом изменении и подменяется одной
    ссылкой, поэтому читающим запросам блокировки не нужны. Маршруты без
    событий проходят проверку одним поиском в словаре.
    """

    def __init__(self, events: list[NetworkEvent]) -> None:
        self.events = [e for e in events if e.active]
        by_route: dict = {}
        for event in self.events:
            by_route.setdefault(event.route, []).append(event)
        self._by_route = by_route

        # Вторичные эффекты: цель правила → (правило, закрытия маршрута-
        # источника). Правило включается, только если есть активное
        # FULL_CLOSURE на маршруте-источнике; без таких событий этого словаря
        # нет, и арифметика прогноза не меняется ни на бит.
        secondary: dict = {}
        for rule in SECONDARY_RULES:
            closures = tuple(
                e for e in by_route.get(rule.source_route, ())
                if e.type == rule.event_type
            )
            if closures:
                secondary.setdefault(rule.target_route, []).append((rule, closures))
        self._secondary = secondary

        # Маршруты с событиями или вторичным эффектом: остальные hot path
        # пропускает без вызова apply.
        self.routes = frozenset(by_route) | frozenset(secondary)
        # (маршрут, день) → события, покрывающие этот день, в исходном
        # порядке. Заполняется лениво; снимок неизменяемый, поэтому гонка
        # двух запросов безвредна — оба запишут одно и то же.
        self._by_route_day: dict = {}
        self._secondary_day: dict = {}

    @property
    def is_empty(self) -> bool:
        return not self._by_route

    def apply(self, route: int, day: date, hour: int, value: float) -> float:
        events = self._by_route.get(route, ())
        secondary = self._secondary.get(route)
        if not events and not secondary:
            return value
        todays = self._by_route_day.get((route, day))
        if todays is None:
            todays = tuple(e for e in events if e.covers_day(day))
            self._by_route_day[(route, day)] = todays
        product = 1.0
        for event in todays:
            if not event.covers_hour(hour):
                continue
            if event.type == FULL_CLOSURE:
                return 0.0
            product *= event.factor if event.factor is not None else 1.0
        # Вторичный эффект — после прямых, до max(…, 0). Включается только
        # в дни и часы, когда закрыт маршрут-источник.
        if secondary:
            for rule, closures in self._secondary_today(route, day, secondary):
                if any(c.covers_hour(hour) for c in closures):
                    product *= rule.factor
        return max(value * product, 0.0)

    def _secondary_today(self, route: int, day: date, secondary: list) -> tuple:
        key = (route, day)
        cached = self._secondary_day.get(key)
        if cached is None:
            cached = tuple(
                (rule, active)
                for rule, closures in secondary
                if (active := tuple(c for c in closures if c.covers_day(day)))
            )
            self._secondary_day[key] = cached
        return cached

    def secondary_effects(
        self,
        routes: list | None = None,
        start: date | None = None,
        end: date | None = None,
    ) -> list[dict]:
        """Вторичные эффекты, действующие на запрошенный период и маршруты.
        Отдельной записью в ответе — чтобы было видно, откуда изменение."""
        wanted = set(routes) if routes else None
        result = []
        for target, pairs in self._secondary.items():
            if wanted is not None and target not in wanted:
                continue
            for rule, closures in pairs:
                for closure in closures:
                    if closure.overlaps(start, end):
                        result.append(rule.describe(closure))
        return result

    def relevant(
        self,
        routes: list | None = None,
        start: date | None = None,
        end: date | None = None,
    ) -> list[dict]:
        """Активные события на запрошенный период — для плашки на графике."""
        wanted = set(routes) if routes else None
        return [
            event.as_dict()
            for event in self.events
            if (wanted is None or event.route in wanted)
            and event.overlaps(start, end)
        ]


class NetworkEventRepository:
    """Граница хранилища. Остальной код знает только эти методы."""

    def list(self, include_inactive: bool = False) -> list[NetworkEvent]:
        raise NotImplementedError

    def get(self, event_id: int) -> NetworkEvent | None:
        raise NotImplementedError

    def find_duplicate(self, candidate: NetworkEvent) -> NetworkEvent | None:
        raise NotImplementedError

    def add(self, fields: dict) -> NetworkEvent:
        """fields — всё, кроме id, active и created_at."""
        raise NotImplementedError

    def deactivate(self, event_id: int) -> NetworkEvent | None:
        raise NotImplementedError

    def effect(self) -> NetworkEffect:
        raise NotImplementedError

    def reload(self) -> None:
        raise NotImplementedError


class JsonNetworkEventRepository(NetworkEventRepository):
    """События в JSON-файле; файл — источник правды для всех воркеров.

    Рабочая копия в памяти перечитывается, как только меняется подпись
    файла (один stat на вызов) — так закрытие, добавленное через один
    воркер, следующий же запрос видит в любом другом. Запись — под
    межпроцессной блокировкой: прочитать свежее → изменить → записать
    атомарно (shared_state).

    Снятое событие не удаляется, а получает active=false: остаётся след,
    что и когда было закрыто. Если каталог только для чтения, события
    живут в памяти одного воркера до перезапуска — сервис не падает, но
    при нескольких воркерах это расхождение, поэтому RUNTIME_DIR обязан
    быть доступен на запись.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._events: list[NetworkEvent] = []
        self._effect = NetworkEffect([])
        self._signature: tuple | None = None
        self.persist_error: str | None = None
        self.reload()

    # --- чтение: файл — источник правды для всех воркеров

    def _read_file(self) -> list[NetworkEvent]:
        if not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8") or "[]")
            return [NetworkEvent.from_dict(item) for item in raw]
        except (OSError, ValueError, KeyError, TypeError) as exc:
            log.error("События сети: %s не прочитан (%s)", self.path, exc)
            return self._events

    def _install(self, events: list[NetworkEvent], sig: tuple | None) -> None:
        self._events = events
        self._effect = NetworkEffect(events)
        self._signature = sig

    def reload(self) -> None:
        with file_lock(self.path):
            sig = signature(self.path)
            events = self._read_file()
        with self._lock:
            self._install(events, sig)
        log.info(
            "События сети: загружено %d, активных %d",
            len(events), len(self._effect.events),
        )

    def _refresh(self) -> None:
        """Один stat на вызов: файл изменил другой воркер — перечитать."""
        if signature(self.path) != self._signature:
            self.reload()

    def list(self, include_inactive: bool = False) -> list[NetworkEvent]:
        self._refresh()
        events = self._events
        return list(events) if include_inactive else [e for e in events if e.active]

    def get(self, event_id: int) -> NetworkEvent | None:
        self._refresh()
        return next((e for e in self._events if e.id == event_id), None)

    def find_duplicate(self, candidate: NetworkEvent) -> NetworkEvent | None:
        self._refresh()
        key = candidate.identity()
        return next(
            (e for e in self._events if e.active and e.identity() == key), None
        )

    def effect(self) -> NetworkEffect:
        self._refresh()
        return self._effect

    # --- запись: прочитать свежее → изменить → записать, всё под блокировкой

    def add(self, fields: dict) -> NetworkEvent:
        """Добавить событие. Дубликат активного события — DuplicateEventError:
        проверка внутри блокировки, иначе два воркера добавили бы одно
        и то же событие одновременно."""
        with self._lock, file_lock(self.path):
            events = self._read_file()
            probe = NetworkEvent(id=0, active=True, created_at="", **fields)
            duplicate = next(
                (e for e in events if e.active and e.identity() == probe.identity()),
                None,
            )
            if duplicate is not None:
                self._install(events, signature(self.path))
                raise DuplicateEventError(duplicate)
            next_id = max((e.id for e in events), default=0) + 1
            event = NetworkEvent(
                id=next_id,
                active=True,
                created_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                **fields,
            )
            self._commit(events + [event])
        return event

    def deactivate(self, event_id: int) -> NetworkEvent | None:
        with self._lock, file_lock(self.path):
            events = self._read_file()
            current = next((e for e in events if e.id == event_id), None)
            if current is None or not current.active:
                self._install(events, signature(self.path))
                return current
            updated = replace(current, active=False)
            self._commit([updated if e.id == event_id else e for e in events])
        return updated

    def _commit(self, events: list[NetworkEvent]) -> None:
        """Под обеими блокировками: сохранить на диск и подменить снимок."""
        payload = json.dumps(
            [e.as_dict() for e in events], ensure_ascii=False, indent=2
        )
        try:
            atomic_write(self.path, payload)
            self.persist_error = None
        except OSError as exc:
            self.persist_error = str(exc)
            log.warning(
                "События сети не сохранены в %s (%s) — действуют до перезапуска "
                "и только в этом воркере",
                self.path, exc,
            )
        self._install(events, signature(self.path))


class DuplicateEventError(Exception):
    def __init__(self, existing: NetworkEvent) -> None:
        super().__init__(f"duplicate of {existing.id}")
        self.existing = existing


_repository: NetworkEventRepository | None = None


def get_repository() -> NetworkEventRepository:
    global _repository
    if _repository is None:
        from app import config

        _repository = JsonNetworkEventRepository(config.NETWORK_EVENTS_PATH)
    return _repository
