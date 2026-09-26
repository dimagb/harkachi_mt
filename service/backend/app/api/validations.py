"""Приём потоковых валидаций: POST /api/ingest/validations и просмотр агрегатов.

Контракт: docs/stas-mvp-architecture.md, разделы 28–33. Путь как в контракте,
алиас /api/v1/... подключается в main.py к тем же обработчикам.

Обработчики — обычные def, не async def: внутри запись на диск, и в async
она заблокировала бы event loop, а с ним p95 всех запросов, не только
приёма. FastAPI уводит обычный def в пул потоков.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from typing import Any

from fastapi import APIRouter, Body, Query

from app import config
from app.api.deps import ApiError, parse_date_param, parse_routes_param
from app.pipeline import validations as v

router = APIRouter(prefix="/ingest", tags=["приём данных"])

INGEST_PATHS = ("/api/ingest/validations", "/api/v1/ingest/validations")


@router.post("/validations", summary="Принять батч успешных валидаций")
def ingest_validations(
    payload: Any = Body(
        ...,
        examples=[{
            "batch_id": "2025-10-31-001",
            "records": [{"timestamp": "2025-10-31T08:12:10+03:00", "route": 17}],
        }],
    ),
) -> dict:
    """Батч принимается целиком или отклоняется целиком (422 INVALID_BATCH).

    Повтор того же batch_id счётчики не удваивает: ответ already_processed.
    """
    repo = v.get_repository()

    # 1. batch_id — до разбора записей: повтор отвечает сразу и дёшево.
    try:
        batch_id = v.check_batch_id(payload.get("batch_id") if isinstance(payload, dict) else None)
    except v.BatchError as exc:
        raise ApiError(422, "INVALID_BATCH", str(exc)) from exc
    existing = repo.get_batch(batch_id)
    if existing is not None:
        return _already(existing, payload)

    # 2–4. схема, маршруты, время, группировка по МСК-часам.
    try:
        batch = v.parse_batch(payload, config.ROUTES)
    except v.BatchError as exc:
        raise ApiError(422, "INVALID_BATCH", str(exc)) from exc

    # 5–6. агрегаты и batch_id — атомарно под блокировкой репозитория.
    already, record = repo.apply(batch)
    if already:
        # Тот же batch_id пришёл параллельно и успел раньше.
        return _already(record, payload)

    result = {
        "status": "ok",
        "already_processed": False,
        "batch_id": record["batch_id"],
        "processed_at": record["processed_at"],
        "records_received": record["records_received"],
        "records_accepted": record["records_accepted"],
        "records_skipped_non_success": record["records_skipped_non_success"],
        "aggregates_touched": record["aggregates_touched"],
    }
    if getattr(repo, "persist_error", None):
        result["warning"] = (
            "Батч принят, но состояние не сохранено на диск и пропадёт "
            "после перезапуска сервиса"
        )
    return result


def _already(record: dict, payload) -> dict:
    result = {
        "status": "ok",
        "already_processed": True,
        "batch_id": record["batch_id"],
        "processed_at": record["processed_at"],
    }
    # Тот же batch_id с другим содержимым — скорее всего, ошибка источника.
    # Счётчики не трогаем, но говорим об этом прямо.
    records = payload.get("records") if isinstance(payload, dict) else None
    if isinstance(records, list):
        canonical = json.dumps(records, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        same = hashlib.sha256(canonical.encode("utf-8")).hexdigest() == record.get("content_hash")
        result["content_matches"] = same
        if not same:
            result["warning"] = (
                "batch_id уже обработан, но содержимое отличается от "
                "принятого. Счётчики не изменены"
            )
    return result


@router.get("/aggregates", summary="Накопленные почасовые агрегаты")
def aggregates(
    routes: str | None = Query(None, description="Маршруты через запятую"),
    date_from: str | None = Query(None, description="ГГГГ-ММ-ДД"),
    date_to: str | None = Query(None, description="ГГГГ-ММ-ДД"),
    granularity: str = Query("day", description="day — по маршруту и дате, hour — почасово"),
) -> dict:
    if granularity not in ("day", "hour"):
        raise ApiError(400, "INVALID_PARAMETER", "granularity принимает значения day или hour")
    repo = v.get_repository()
    rows = repo.aggregates(
        parse_routes_param(routes),
        parse_date_param(date_from, "date_from"),
        parse_date_param(date_to, "date_to"),
    )
    if granularity == "day":
        by_day: dict = defaultdict(lambda: {"boardings": 0, "hours": 0, "updated_at": None})
        for row in rows:
            item = by_day[(row["route"], row["date"])]
            item["boardings"] += row["boardings"]
            item["hours"] += 1
            if item["updated_at"] is None or row["updated_at"] > item["updated_at"]:
                item["updated_at"] = row["updated_at"]
        rows = [
            {"route": route, "date": day, **item}
            for (route, day), item in sorted(by_day.items())
        ]
    return {
        "granularity": granularity,
        "rows": rows,
        "total_boardings": sum(r["boardings"] for r in rows),
        "ingest": repo.stats(),
        "note": (
            "Агрегаты потока нужны пересборке прогноза "
            "(ml.build_release --runtime) и на выдачу /api/forecast не влияют"
        ),
    }


@router.get("/status", summary="Состояние приёма: счётчики и последние батчи")
def status(limit: int = Query(20, ge=1, le=200)) -> dict:
    repo = v.get_repository()
    recent = repo.recent_batches(limit) if hasattr(repo, "recent_batches") else []
    return {
        "ingest": repo.stats(),
        "limits": {
            "max_records_per_batch": v.MAX_RECORDS,
            "max_body_bytes": v.MAX_BODY_BYTES,
        },
        "recent_batches": recent,
    }
