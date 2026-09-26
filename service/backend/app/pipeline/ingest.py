"""Приём и нормализация данных.

Первое звено цепочки: читает прогноз, историю и справочники, приводит к
единому внутреннему представлению и держит в памяти. Объём данных небольшой
(прогноз 14 640 строк, история около 58 тысяч), поэтому всё грузится один раз
на старте — отсюда стабильные единицы миллисекунд на запрос.

Источник прогноза подменяется одним файлом: сюда можно положить как результат
статистического базлайна, так и выгрузку ML-модели — формат один и тот же.
"""

from __future__ import annotations

import csv
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from app import config

log = logging.getLogger(__name__)


def _parse_date(raw: str) -> date | None:
    raw = (raw or "").strip()[:10].replace("/", "-").replace(".", "-")
    parts = raw.split("-")
    if len(parts) != 3:
        return None
    try:
        if len(parts[0]) == 4:
            return date(int(parts[0]), int(parts[1]), int(parts[2]))
        return date(int(parts[2]), int(parts[1]), int(parts[0]))
    except ValueError:
        return None


def _sniff_delimiter(path: Path) -> str:
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        header = fh.readline()
    counts = {sep: header.count(sep) for sep in (";", ",", "\t", "|")}
    best = max(counts, key=counts.get)
    return best if counts[best] else ","


def _read_rows(path: Path) -> list[dict]:
    delimiter = _sniff_delimiter(path)
    for encoding in ("utf-8-sig", "cp1251"):
        try:
            with path.open("r", encoding=encoding, newline="") as fh:
                return list(csv.DictReader(fh, delimiter=delimiter))
        except UnicodeDecodeError:
            continue
    return []


def _column_map(columns) -> dict:
    """Распознаёт колонки независимо от точного написания заголовков."""
    mapping = {}
    for column in columns:
        name = (column or "").strip().lower()
        if name.startswith("route"):
            mapping["route"] = column
        elif name.startswith("date"):
            mapping["date"] = column
        elif name.startswith("hour"):
            mapping["hour"] = column
        elif name in ("prediction", "boardings", "target", "value", "count"):
            mapping["value"] = column
    return mapping


@dataclass
class Dataset:
    """Нормализованные данные в памяти."""

    forecast: dict = field(default_factory=dict)   # (route, date, hour) -> value
    history: dict = field(default_factory=dict)    # (route, date, hour) -> value
    routes: list = field(default_factory=list)
    forecast_dates: list = field(default_factory=list)
    history_dates: list = field(default_factory=list)
    loaded_at: datetime = field(default_factory=datetime.utcnow)
    source_files: dict = field(default_factory=dict)

    # --- производные срезы, считаются один раз на старте
    forecast_by_route_date: dict = field(default_factory=dict)
    history_by_route_date: dict = field(default_factory=dict)

    def build_indexes(self) -> None:
        by_rd = defaultdict(float)
        for (route, day, _hour), value in self.forecast.items():
            by_rd[(route, day)] += value
        self.forecast_by_route_date = dict(by_rd)

        by_rd = defaultdict(float)
        for (route, day, _hour), value in self.history.items():
            by_rd[(route, day)] += value
        self.history_by_route_date = dict(by_rd)

    @property
    def stats(self) -> dict:
        return {
            "forecast_rows": len(self.forecast),
            "history_rows": len(self.history),
            "routes": self.routes,
            "forecast_period": [
                str(min(self.forecast_dates)) if self.forecast_dates else None,
                str(max(self.forecast_dates)) if self.forecast_dates else None,
            ],
            "history_period": [
                str(min(self.history_dates)) if self.history_dates else None,
                str(max(self.history_dates)) if self.history_dates else None,
            ],
            "loaded_at": self.loaded_at.isoformat() + "Z",
            "source_files": self.source_files,
        }


def load_forecast(data_dir: Path, filename: str) -> tuple[dict, list]:
    """Прогноз в формате сдачи: route;date;hour;prediction."""
    path = data_dir / filename
    if not path.exists():
        candidates = sorted(data_dir.glob("submission*.csv"))
        if not candidates:
            log.warning("Файл прогноза не найден в %s", data_dir)
            return {}, []
        path = candidates[0]
        log.warning("Использую %s вместо %s", path.name, filename)

    rows = _read_rows(path)
    if not rows:
        return {}, []
    cols = _column_map(rows[0].keys())
    if len(cols) < 4:
        log.error("Не распознал колонки прогноза: %s", list(rows[0].keys()))
        return {}, []

    data: dict = {}
    for row in rows:
        day = _parse_date(row[cols["date"]])
        if day is None:
            continue
        try:
            route = int(float(row[cols["route"]]))
            hour = int(float(row[cols["hour"]]))
            value = float(row[cols["value"]] or 0)
        except (TypeError, ValueError):
            continue
        data[(route, day, hour)] = value
    return data, [path.name]


def load_history(data_dir: Path) -> tuple[dict, list]:
    """Фактические посадки из labels — используются для сравнения с прогнозом."""
    files = sorted(data_dir.rglob("labels_day_*.csv"))
    data: dict = {}
    names = []
    for path in files:
        rows = _read_rows(path)
        if not rows:
            continue
        cols = _column_map(rows[0].keys())
        if len(cols) < 4:
            continue
        for row in rows:
            day = _parse_date(row[cols["date"]])
            if day is None:
                continue
            try:
                route = int(float(row[cols["route"]]))
                hour = int(float(row[cols["hour"]]))
                value = float(row[cols["value"]] or 0)
            except (TypeError, ValueError):
                continue
            data[(route, day, hour)] = data.get((route, day, hour), 0.0) + value
        names.append(path.name)
    return data, names


def load() -> Dataset:
    """Собирает весь датасет. Вызывается один раз при старте приложения."""
    data_dir = config.DATA_DIR
    dataset = Dataset()

    dataset.forecast, forecast_files = load_forecast(
        data_dir, config.FORECAST_FILE
    )
    dataset.history, history_files = load_history(data_dir)

    dataset.routes = sorted(
        {route for route, _, _ in dataset.forecast}
        | {route for route, _, _ in dataset.history}
    )
    dataset.forecast_dates = sorted({day for _, day, _ in dataset.forecast})
    dataset.history_dates = sorted({day for _, day, _ in dataset.history})
    dataset.source_files = {
        "forecast": forecast_files,
        "history": history_files,
    }
    dataset.build_indexes()

    log.info(
        "Загружено: прогноз %d строк, история %d строк, маршрутов %d",
        len(dataset.forecast),
        len(dataset.history),
        len(dataset.routes),
    )
    return dataset


_dataset: Dataset | None = None


def get_dataset() -> Dataset:
    global _dataset
    if _dataset is None:
        _dataset = load()
    return _dataset


def reload_dataset() -> Dataset:
    """Перечитать данные без перезапуска сервиса — нужно, когда ML-команда
    подкладывает новый файл прогноза."""
    global _dataset
    _dataset = load()
    return _dataset
