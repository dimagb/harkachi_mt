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
import hashlib
import logging
import threading
from bisect import bisect_left, bisect_right
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from app import config
from app.pipeline.shared_state import reload_generation

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
class RowIndex:
    """Строки прогноза или истории с предрасчитанными ключами и индексом
    (маршрут, дата) → позиции строк.

    Запрос выбирает только нужные маршруты и даты, а не перебирает всё.
    Позиции возвращаются в исходном порядке строк, поэтому суммы
    складываются в той же последовательности, что и при полном переборе:
    сложение float неассоциативно, и другой порядок мог бы сдвинуть
    последний знак.
    """

    # (route, day, hour, value, ключ часа, ключ дня, ключ месяца)
    rows: list = field(default_factory=list)
    by_route_day: dict = field(default_factory=dict)
    dates: list = field(default_factory=list)
    routes: list = field(default_factory=list)

    KEY_POSITION = {"hour": 4, "day": 5, "month": 6}

    @classmethod
    def build(cls, store: dict) -> "RowIndex":
        rows = []
        by_route_day: dict = defaultdict(list)
        iso_cache: dict = {}
        for pos, ((route, day, hour), value) in enumerate(store.items()):
            iso = iso_cache.get(day)
            if iso is None:
                iso = iso_cache[day] = day.isoformat()
            rows.append((route, day, hour, value, f"{iso}T{hour:02d}", iso, iso[:7]))
            by_route_day[(route, day)].append(pos)
        return cls(
            rows=rows,
            by_route_day=dict(by_route_day),
            dates=sorted({day for _, day in by_route_day}),
            routes=sorted({route for route, _ in by_route_day}),
        )

    def positions(self, routes=None, start: date | None = None,
                  end: date | None = None) -> list:
        """Позиции строк по маршрутам и диапазону дат включительно."""
        lo = bisect_left(self.dates, start) if start is not None else 0
        hi = bisect_right(self.dates, end) if end is not None else len(self.dates)
        days = self.dates[lo:hi]
        wanted = sorted(set(routes)) if routes else self.routes
        get = self.by_route_day.get
        result: list = []
        for route in wanted:
            for day in days:
                found = get((route, day))
                if found:
                    result.extend(found)
        # Строки обычно уже упорядочены по маршруту и дате, тогда сортировка
        # линейная; в любом случае восстанавливает исходный порядок.
        result.sort()
        return result


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
    forecast_md5: str | None = None

    # --- производные срезы, считаются один раз на старте
    forecast_by_route_date: dict = field(default_factory=dict)
    history_by_route_date: dict = field(default_factory=dict)
    forecast_index: RowIndex = field(default_factory=RowIndex)
    history_index: RowIndex = field(default_factory=RowIndex)

    def build_indexes(self) -> None:
        self.forecast_index = RowIndex.build(self.forecast)
        self.history_index = RowIndex.build(self.history)

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
    # md5 байтов файла прогноза: по нему /api/meta решает, относится ли
    # score из configs/release.json к тому, что сервис реально отдаёт.
    if forecast_files:
        dataset.forecast_md5 = hashlib.md5(
            (data_dir / forecast_files[0]).read_bytes()
        ).hexdigest()
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
_dataset_generation: tuple | None = None
_dataset_lock = threading.Lock()


def get_dataset() -> Dataset:
    """Данные в памяти процесса. Если другой воркер выполнил POST /api/reload,
    метка перезагрузки изменилась — перечитать файлы здесь тоже (один stat
    на вызов)."""
    global _dataset, _dataset_generation
    generation = reload_generation()
    if _dataset is None or generation != _dataset_generation:
        with _dataset_lock:
            if _dataset is None or generation != _dataset_generation:
                _dataset = load()
                _dataset_generation = generation
    return _dataset


def reload_dataset() -> Dataset:
    """Перечитать данные без перезапуска сервиса — нужно, когда ML-команда
    подкладывает новый файл прогноза. Остальные воркеры перечитают по метке
    перезагрузки, которую ставит POST /api/reload."""
    global _dataset, _dataset_generation
    with _dataset_lock:
        _dataset = load()
        _dataset_generation = reload_generation()
    return _dataset
