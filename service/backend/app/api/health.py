"""Служебные эндпойнты: проверка живости и сведения о загруженных данных."""

from __future__ import annotations

from fastapi import APIRouter

from app import config
from app.pipeline import geo as geo_module
from app.pipeline import network_events, validations
from app.pipeline.cache import cache as response_cache
from app.pipeline.ingest import get_dataset, reload_dataset

router = APIRouter(tags=["служебные"])


@router.get("/health", summary="Проверка работоспособности")
def health() -> dict:
    dataset = get_dataset()
    ready = bool(dataset.forecast)
    return {
        "status": "ok" if ready else "degraded",
        "version": config.APP_VERSION,
        "forecast_rows": len(dataset.forecast),
        "history_rows": len(dataset.history),
        "cache": response_cache.stats,
    }


@router.get("/meta", summary="Что загружено в сервис")
def meta() -> dict:
    dataset = get_dataset()
    geo = geo_module.get_geo()
    ingest = validations.get_repository().stats()
    return {
        "app": {"title": config.APP_TITLE, "version": config.APP_VERSION},
        # Раздел 49 контракта: видно живьём, что поток доезжает.
        "last_ingest_at": ingest["last_ingest_at"],
        "ingest_batches": ingest["batches_processed"],
        "active_network_events": len(network_events.get_repository().effect().events),
        "ingest": ingest,
        "data": dataset.stats,
        "geo": {
            "routes_with_geometry": sorted(geo.stops_by_route),
            "source_files": geo.source_files,
            "warnings": geo.warnings,
        },
        "limits": {
            "excluded_routes": sorted(config.EXCLUDED_ROUTES),
            "forecast_period": [config.FORECAST_START, config.FORECAST_END],
        },
    }


@router.post("/reload", summary="Перечитать файлы данных без перезапуска")
def reload_data() -> dict:
    """Нужен, когда ML-команда подкладывает новый файл прогноза."""
    dataset = reload_dataset()
    network_events.get_repository().reload()
    validations.get_repository().reload()
    response_cache.clear()
    geo_module._geo = None  # noqa: SLF001 — намеренный сброс кэша
    geo_module.get_geo()
    return {"status": "reloaded", "data": dataset.stats}
