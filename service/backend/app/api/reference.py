"""Справочные эндпойнты: маршруты, остановки, геометрия для карты."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app import config
from app.pipeline import geo as geo_module
from app.pipeline.ingest import get_dataset

router = APIRouter(tags=["справочники"])


@router.get("/routes", summary="Список маршрутов")
def routes() -> dict:
    dataset = get_dataset()
    geo = geo_module.get_geo()
    items = []
    for route in config.ROUTES:
        items.append(
            {
                "route": route,
                "in_data": route in dataset.routes,
                "has_geometry": geo.has_geometry(route),
                "stops_count": len(geo.stops(route)),
                "excluded": route in config.EXCLUDED_ROUTES,
                "starts_at": config.ROUTE_START_DATES.get(route),
                "note": (
                    f"Маршрут запущен {config.ROUTE_START_DATES[route]}: "
                    "истории нет, до этой даты прогноз нулевой"
                    if route in config.ROUTE_START_DATES
                    else None
                ),
            }
        )
    return {"routes": items, "total": len(items)}


@router.get("/stops", summary="Остановки маршрута с координатами")
def stops(route: int | None = Query(None, description="Номер маршрута")) -> dict:
    geo = geo_module.get_geo()
    if route is not None:
        if route not in config.ROUTES:
            raise HTTPException(
                status_code=404,
                detail=f"Маршрут {route} не входит в набор задачи",
            )
        items = [stop.as_dict() for stop in geo.stops(route)]
        return {
            "route": route,
            "stops": items,
            "has_geometry": bool(items),
            "note": (
                None
                if items
                else "Координаты для этого маршрута в справочниках отсутствуют"
            ),
        }
    return {
        "stops": [
            stop.as_dict()
            for route_stops in geo.stops_by_route.values()
            for stop in route_stops
        ]
    }


@router.get("/geometry", summary="Геометрия маршрутов в GeoJSON")
def geometry(route: int | None = Query(None)) -> dict:
    geo = geo_module.get_geo()
    targets = [route] if route is not None else geo.routes
    features = []
    for item in targets:
        features.extend(geo.route_geojson(item))
    return {
        "type": "FeatureCollection",
        "features": features,
        "routes_without_geometry": sorted(set(config.ROUTES) - set(geo.routes)),
    }
