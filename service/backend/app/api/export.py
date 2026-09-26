"""Выгрузка прогноза в CSV и XLSX — требование функциональности из ТЗ."""

from __future__ import annotations

import csv
import io
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.api.deps import adjustment_params, parse_date_param, parse_routes_param
from app.pipeline.adjust import Adjustment
from app.pipeline.ingest import get_dataset

router = APIRouter(prefix="/export", tags=["выгрузка"])

HEADER = ["route", "date", "hour", "prediction"]


def _collect(routes, date_from, date_to, hour_from, hour_to, adjustment):
    dataset = get_dataset()
    wanted = set(routes) if routes else None
    rows = []
    for (route, day, hour), value in dataset.forecast.items():
        if wanted is not None and route not in wanted:
            continue
        if date_from and day < date_from:
            continue
        if date_to and day > date_to:
            continue
        if hour < hour_from or hour > hour_to:
            continue
        if adjustment is not None and not adjustment.is_identity:
            value = value * adjustment.factor(route, day)
        rows.append((route, day.isoformat(), hour, round(value)))
    rows.sort(key=lambda item: (item[0], item[1], item[2]))
    return rows


def _filename(extension: str) -> str:
    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M")
    return f"forecast_{stamp}.{extension}"


@router.get("", summary="Выгрузка прогноза в CSV или XLSX")
def export(
    format: str = Query("csv", description="csv или xlsx"),
    routes: str | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    hour_from: int = Query(0, ge=0, le=23),
    hour_to: int = Query(23, ge=0, le=23),
    adjustment: Adjustment = Depends(adjustment_params),
):
    fmt = format.lower().strip()
    if fmt not in ("csv", "xlsx"):
        raise HTTPException(
            status_code=400, detail="format принимает значения csv или xlsx"
        )

    rows = _collect(
        parse_routes_param(routes),
        parse_date_param(date_from, "date_from"),
        parse_date_param(date_to, "date_to"),
        hour_from,
        hour_to,
        adjustment,
    )

    if fmt == "csv":
        buffer = io.StringIO()
        writer = csv.writer(buffer, delimiter=";", lineterminator="\n")
        writer.writerow(HEADER)
        writer.writerows(rows)
        content = buffer.getvalue().encode("utf-8-sig")
        return StreamingResponse(
            io.BytesIO(content),
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{_filename("csv")}"'
            },
        )

    try:
        from openpyxl import Workbook
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail="Выгрузка в XLSX недоступна: не установлен openpyxl",
        ) from exc

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Прогноз"
    sheet.append(HEADER)
    for row in rows:
        sheet.append(list(row))
    for column, width in zip("ABCD", (10, 14, 8, 14)):
        sheet.column_dimensions[column].width = width
    sheet.freeze_panes = "A2"

    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        headers={
            "Content-Disposition": f'attachment; filename="{_filename("xlsx")}"'
        },
    )


@router.get("/submission", summary="Выгрузка в формате сдачи на лидерборд")
def export_submission():
    """Полная сетка 10 маршрутов × 61 день × 24 часа без поправок."""
    rows = _collect(None, None, None, 0, 23, None)
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", lineterminator="\n")
    writer.writerow(HEADER)
    writer.writerows(rows)
    content = buffer.getvalue().encode("utf-8")
    return StreamingResponse(
        io.BytesIO(content),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="submission.csv"'},
    )
