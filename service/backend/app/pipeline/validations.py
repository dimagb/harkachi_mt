"""Приём потоковых валидаций: micro-batch → почасовые агрегаты.

Не путать с pipeline/ingest.py: тот читает файлы прогноза и истории на
старте. Здесь — входящий поток успешных валидаций, который копит
hourly_aggregates для пересборки прогноза (ml.build_release --runtime).

Контракт: docs/stas-mvp-architecture.md, разделы 28–33.

    1. проверить batch_id          уже обработан → already_processed
    2. проверить схему
    3. проверить маршрут и время
    4. сгруппировать по маршрут / дата / час (московское время)
    5. обновить hourly_aggregates
    6. записать batch_id
    7. вернуть ответ

Режим — только успешные валидации: каждая запись уже означает успех.
Если в записи есть поле result, учитывается только SUCCESS.

Агрегаты НЕ влияют на выдачу прогноза: /api/forecast читает релиз,
а не поток. Поток нужен пайплайну пересборки.

Хранилище спрятано за ValidationRepository. Сейчас это JSON-файл,
загружаемый в память на старте; замена на DuckDB трогает только
реализацию репозитория.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger(__name__)

# Москва живёт в UTC+3 без перехода на летнее время с 2014 года. Фиксированный
# сдвиг вместо zoneinfo: в slim-образе может не оказаться базы часовых поясов.
MSK = timezone(timedelta(hours=3))

MAX_RECORDS = 50_000                 # записей в одном батче
MAX_BODY_BYTES = 8 * 1024 * 1024     # проверяется до разбора JSON
MAX_FUTURE = timedelta(days=1)       # допуск на расхождение часов источника
BATCH_ID_RE = re.compile(r"^[A-Za-z0-9._:\-]{1,128}$")
MAX_ERRORS_SHOWN = 5


class BatchError(Exception):
    """Батч отклонён целиком: 422 INVALID_BATCH."""


@dataclass(frozen=True)
class ParsedBatch:
    batch_id: str
    counts: Counter              # (route, date, hour) → число успешных валидаций
    received: int
    accepted: int
    skipped_non_success: int
    content_hash: str


def parse_batch(payload, routes: list, now: datetime | None = None) -> ParsedBatch:
    """Проверка схемы, маршрутов и времени. Батч принимается целиком или
    отклоняется целиком — иначе повтор после частичной ошибки нельзя было бы
    сделать идемпотентным."""
    if not isinstance(payload, dict):
        raise BatchError("Тело запроса должно быть JSON-объектом с полями batch_id и records")

    batch_id = check_batch_id(payload.get("batch_id"))

    records = payload.get("records")
    if not isinstance(records, list):
        raise BatchError("Поле records обязательно и должно быть массивом")
    if not records:
        raise BatchError("Массив records пуст")
    if len(records) > MAX_RECORDS:
        raise BatchError(
            f"В батче {len(records)} записей, максимум {MAX_RECORDS}. "
            "Разбейте поток на батчи поменьше"
        )

    allowed = set(routes)
    now = now or datetime.now(timezone.utc)
    latest = now + MAX_FUTURE
    counts: Counter = Counter()
    errors: list = []
    skipped = 0

    truncated = False
    for i, record in enumerate(records):
        if len(errors) >= MAX_ERRORS_SHOWN:
            truncated = True
            break
        if not isinstance(record, dict):
            errors.append(f"records[{i}]: ожидается объект")
            continue

        result = record.get("result")
        if result is not None:
            if not isinstance(result, str):
                errors.append(f"records[{i}].result: ожидается строка")
                continue
            if result.strip().upper() != "SUCCESS":
                skipped += 1
                continue

        route = record.get("route")
        if isinstance(route, bool) or not isinstance(route, int):
            errors.append(f"records[{i}].route: ожидается целый номер маршрута, получено {route!r}")
            continue
        if route not in allowed:
            errors.append(f"records[{i}].route: маршрут {route} не поддерживается")
            continue

        raw = record.get("timestamp")
        if not isinstance(raw, str):
            errors.append(f"records[{i}].timestamp: ожидается строка ISO 8601 с часовым поясом")
            continue
        try:
            moment = datetime.fromisoformat(raw.strip())
        except ValueError:
            errors.append(f"records[{i}].timestamp: не разобрать {raw!r}")
            continue
        if moment.tzinfo is None:
            errors.append(
                f"records[{i}].timestamp: нет часового пояса в {raw!r}, "
                "нужен вид 2025-10-31T08:12:10+03:00"
            )
            continue
        if moment > latest:
            errors.append(f"records[{i}].timestamp: {raw} в будущем")
            continue

        local = moment.astimezone(MSK)
        counts[(route, local.date().isoformat(), local.hour)] += 1

    if errors:
        more = f" (показаны первые {len(errors)})" if truncated else ""
        raise BatchError("Батч отклонён целиком" + more + ": " + "; ".join(errors))

    canonical = json.dumps(records, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return ParsedBatch(
        batch_id=batch_id,
        counts=counts,
        received=len(records),
        accepted=sum(counts.values()),
        skipped_non_success=skipped,
        content_hash=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    )


def check_batch_id(batch_id) -> str:
    if not isinstance(batch_id, str) or not batch_id.strip():
        raise BatchError("Поле batch_id обязательно: непустая строка")
    if not BATCH_ID_RE.match(batch_id):
        raise BatchError(
            "batch_id — до 128 символов: латиница, цифры, точка, дефис, "
            f"подчёркивание, двоеточие. Получено: {batch_id!r}"
        )
    return batch_id


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class ValidationRepository:
    """Граница хранилища. Остальной код знает только эти методы."""

    def get_batch(self, batch_id: str) -> dict | None:
        raise NotImplementedError

    def apply(self, batch: ParsedBatch) -> tuple[bool, dict]:
        """Атомарно: если batch_id новый — прибавить счётчики и записать
        батч. Возвращает (уже_был, запись о батче)."""
        raise NotImplementedError

    def aggregates(self, routes=None, date_from: date | None = None,
                   date_to: date | None = None) -> list[dict]:
        raise NotImplementedError

    def stats(self) -> dict:
        raise NotImplementedError

    def reload(self) -> None:
        raise NotImplementedError


class JsonValidationRepository(ValidationRepository):
    """Состояние в JSON-файле, рабочая копия в памяти.

    Файл маленький: агрегаты ограничены сеткой маршрут × дата × час, батчи —
    одна строка на batch_id. Запись атомарная — через временный файл и
    os.replace. Если каталог только для чтения, состояние живёт в памяти до
    перезапуска, приём не падает.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._aggregates: dict = {}   # (route, date_iso, hour) → {boardings, updated_at}
        self._batches: dict = {}      # batch_id → запись о батче
        self.persist_error: str | None = None
        self.reload()

    def reload(self) -> None:
        aggregates: dict = {}
        batches: dict = {}
        if self.path.exists():
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8") or "{}")
                for row in raw.get("hourly_aggregates", []):
                    key = (int(row["route"]), str(row["date"]), int(row["hour"]))
                    aggregates[key] = {
                        "boardings": int(row["boardings"]),
                        "updated_at": row.get("updated_at"),
                    }
                for item in raw.get("batches", []):
                    batches[item["batch_id"]] = item
            except (OSError, ValueError, KeyError, TypeError) as exc:
                log.error("Приём валидаций: %s не прочитан (%s)", self.path, exc)
        with self._lock:
            self._aggregates = aggregates
            self._batches = batches
        log.info(
            "Приём валидаций: батчей %d, агрегатов %d", len(batches), len(aggregates)
        )

    def get_batch(self, batch_id: str) -> dict | None:
        return self._batches.get(batch_id)

    def apply(self, batch: ParsedBatch) -> tuple[bool, dict]:
        with self._lock:
            existing = self._batches.get(batch.batch_id)
            if existing is not None:
                return True, existing

            now = _utc_now()
            aggregates = dict(self._aggregates)
            for key, count in batch.counts.items():
                current = aggregates.get(key)
                boardings = (current["boardings"] if current else 0) + count
                aggregates[key] = {"boardings": boardings, "updated_at": now}

            record = {
                "batch_id": batch.batch_id,
                "processed_at": now,
                "records_received": batch.received,
                "records_accepted": batch.accepted,
                "records_skipped_non_success": batch.skipped_non_success,
                "aggregates_touched": len(batch.counts),
                "content_hash": batch.content_hash,
            }
            batches = dict(self._batches)
            batches[batch.batch_id] = record

            self._aggregates = aggregates
            self._batches = batches
            self._persist()
        return False, record

    def aggregates(self, routes=None, date_from: date | None = None,
                   date_to: date | None = None) -> list[dict]:
        wanted = set(routes) if routes else None
        start = date_from.isoformat() if date_from else None
        end = date_to.isoformat() if date_to else None
        rows = []
        for (route, day, hour), value in self._aggregates.items():
            if wanted is not None and route not in wanted:
                continue
            if start and day < start:
                continue
            if end and day > end:
                continue
            rows.append({
                "route": route,
                "date": day,
                "hour": hour,
                "boardings": value["boardings"],
                "updated_at": value["updated_at"],
            })
        rows.sort(key=lambda r: (r["route"], r["date"], r["hour"]))
        return rows

    def stats(self) -> dict:
        batches = self._batches
        last = max((b["processed_at"] for b in batches.values()), default=None)
        return {
            "last_ingest_at": last,
            "batches_processed": len(batches),
            "records_accepted": sum(b["records_accepted"] for b in batches.values()),
            "aggregate_rows": len(self._aggregates),
            "persist_error": self.persist_error,
        }

    def recent_batches(self, limit: int = 20) -> list[dict]:
        items = sorted(self._batches.values(), key=lambda b: b["processed_at"], reverse=True)
        return items[:limit]

    def _persist(self) -> None:
        """Под блокировкой: сохранить на диск."""
        payload = json.dumps(
            {
                "hourly_aggregates": [
                    {"route": r, "date": d, "hour": h, **v}
                    for (r, d, h), v in sorted(self._aggregates.items())
                ],
                "batches": sorted(self._batches.values(), key=lambda b: b["processed_at"]),
            },
            ensure_ascii=False,
            indent=1,
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
                "Приём валидаций: состояние не сохранено в %s (%s) — действует до перезапуска",
                self.path, exc,
            )


_repository: ValidationRepository | None = None


def get_repository() -> ValidationRepository:
    global _repository
    if _repository is None:
        from app import config

        _repository = JsonValidationRepository(config.VALIDATIONS_PATH)
    return _repository
