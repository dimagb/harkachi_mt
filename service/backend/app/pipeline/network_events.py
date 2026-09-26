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
import os
import threading
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timezone
from pathlib import Path

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
        # Маршруты с событиями: остальные hot path пропускает без вызова apply.
        self.routes = frozenset(by_route)
        # (маршрут, день) → события, покрывающие этот день, в исходном
        # порядке. Заполняется лениво; снимок неизменяемый, поэтому гонка
        # двух запросов безвредна — оба запишут одно и то же.
        self._by_route_day: dict = {}

    @property
    def is_empty(self) -> bool:
        return not self._by_route

    def apply(self, route: int, day: date, hour: int, value: float) -> float:
        events = self._by_route.get(route)
        if not events:
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
        return max(value * product, 0.0)

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
    """События в JSON-файле, рабочая копия в памяти.

    Снятое событие не удаляется, а получает active=false: остаётся след,
    что и когда было закрыто. Запись атомарная — через временный файл
    и os.replace, чтобы обрыв посреди записи не оставил битый JSON.
    Если каталог только для чтения, события живут в памяти до перезапуска,
    сервис при этом не падает.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._events: list[NetworkEvent] = []
        self._effect = NetworkEffect([])
        self.persist_error: str | None = None
        self.reload()

    def reload(self) -> None:
        events: list[NetworkEvent] = []
        if self.path.exists():
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8") or "[]")
                events = [NetworkEvent.from_dict(item) for item in raw]
            except (OSError, ValueError, KeyError, TypeError) as exc:
                log.error("События сети: %s не прочитан (%s)", self.path, exc)
        with self._lock:
            self._events = events
            self._effect = NetworkEffect(events)
        log.info(
            "События сети: загружено %d, активных %d",
            len(events), len(self._effect.events),
        )

    def list(self, include_inactive: bool = False) -> list[NetworkEvent]:
        events = self._events
        return list(events) if include_inactive else [e for e in events if e.active]

    def get(self, event_id: int) -> NetworkEvent | None:
        return next((e for e in self._events if e.id == event_id), None)

    def find_duplicate(self, candidate: NetworkEvent) -> NetworkEvent | None:
        key = candidate.identity()
        return next(
            (e for e in self._events if e.active and e.identity() == key), None
        )

    def add(self, fields: dict) -> NetworkEvent:
        with self._lock:
            next_id = max((e.id for e in self._events), default=0) + 1
            event = NetworkEvent(
                id=next_id,
                active=True,
                created_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                **fields,
            )
            self._commit(self._events + [event])
        return event

    def deactivate(self, event_id: int) -> NetworkEvent | None:
        with self._lock:
            current = next((e for e in self._events if e.id == event_id), None)
            if current is None:
                return None
            if not current.active:
                return current
            updated = replace(current, active=False)
            self._commit(
                [updated if e.id == event_id else e for e in self._events]
            )
        return updated

    def effect(self) -> NetworkEffect:
        return self._effect

    def _commit(self, events: list[NetworkEvent]) -> None:
        """Под блокировкой: сохранить на диск и подменить снимок."""
        self._events = events
        self._effect = NetworkEffect(events)
        payload = json.dumps(
            [e.as_dict() for e in events], ensure_ascii=False, indent=2
        )
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(payload, encoding="utf-8")
            os.replace(tmp, self.path)
            self.persist_error = None
        except OSError as exc:
            self.persist_error = str(exc)
            log.warning(
                "События сети не сохранены в %s (%s) — действуют до перезапуска",
                self.path, exc,
            )


_repository: NetworkEventRepository | None = None


def get_repository() -> NetworkEventRepository:
    global _repository
    if _repository is None:
        from app import config

        _repository = JsonNetworkEventRepository(config.NETWORK_EVENTS_PATH)
    return _repository
