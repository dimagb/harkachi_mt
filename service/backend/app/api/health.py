"""Служебные эндпойнты: проверка живости и сведения о загруженных данных."""

from __future__ import annotations

import json

from fastapi import APIRouter

from app import config
from app.pipeline import geo as geo_module
from app.pipeline import network_events, validations
from app.pipeline.shared_state import bump_reload_marker
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


def release_fields(dataset) -> dict:
    """Метаданные ML-релиза для /api/meta (раздел 49 контракта).

    Нет configs/release.json или он битый — пусто, /api/meta работает как
    раньше. score отдаётся, только если md5 загруженного прогноза совпадает
    с тем, что получил этот score: подменили файл — score не показывается.
    """
    try:
        rel = json.loads(config.RELEASE_CONFIG_PATH.read_text(encoding="utf-8"))
        scored = rel.get("scored_forecast") or {}
        release_id, model_version = rel["release_id"], rel["model_version"]
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return {}
    matches = bool(dataset.forecast_md5) and dataset.forecast_md5 == scored.get("forecast_md5")
    fields = {
        "release_id": release_id,
        "model_version": model_version,
        "score": scored.get("score") if matches else None,
        "cutoff_date": dataset.history_dates[-1].isoformat() if dataset.history_dates else None,
        "forecast_from": dataset.forecast_dates[0].isoformat() if dataset.forecast_dates else None,
        "forecast_to": dataset.forecast_dates[-1].isoformat() if dataset.forecast_dates else None,
        # Коммит, из которого сборка воспроизвела ровно этот прогноз. Перенесён
        # из release_metadata в .duckdb в configs/release.json (DuckDB в образе
        # нет); относится к тем же значениям, что и score, — то же правило md5.
        "code_git_sha": scored.get("code_git_sha") if matches else None,
        "forecast_md5": dataset.forecast_md5,
    }
    notes = []
    if not matches:
        notes.append(
            "score и code_git_sha не показаны: md5 загруженного прогноза не "
            "совпадает с прогнозом, получившим score в configs/release.json"
        )
    if notes:
        fields["release_notes"] = notes
    return fields


@router.get("/meta", summary="Что загружено в сервис")
def meta() -> dict:
    dataset = get_dataset()
    geo = geo_module.get_geo()
    ingest = validations.get_repository().stats()
    return {
        **release_fields(dataset),
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
@router.post("/admin/reload-forecast", include_in_schema=False)
def reload_data() -> dict:
    """Нужен, когда ML-команда подкладывает новый файл прогноза.

    Сначала меняется метка перезагрузки: по ней остальные воркеры
    перечитают данные на своём следующем запросе, а ключи кеша сменятся
    во всех процессах сразу (подпись метки входит в ключ, main.py).
    """
    shared = bump_reload_marker()
    dataset = reload_dataset()
    network_events.get_repository().reload()
    validations.get_repository().reload()
    response_cache.clear()
    geo_module._geo = None  # noqa: SLF001 — намеренный сброс кэша
    geo_module.get_geo()
    result = {"status": "reloaded", "data": dataset.stats}
    if not shared:
        result["warning"] = (
            "Метку перезагрузки записать не удалось: остальные воркеры "
            "продолжают работать на старых данных"
        )
    return result
