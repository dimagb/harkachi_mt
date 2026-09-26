"""Корректирующие коэффициенты.

Позволяют диспетчеру подкрутить прогноз под условия, которых модель не знает:
похолодание, крупное мероприятие, закрытие участка на ремонт. Коэффициенты
применяются поверх готового прогноза, сама модель не переобучается — поэтому
пересчёт мгновенный и результат виден сразу.

Порядок применения (мультипликативно):

    итог = прогноз
           × коэффициент погоды           (если дата попадает в диапазон)
           × коэффициент события           (если дата попадает в диапазон)
           × коэффициент маршрута          (точечная поправка)
           × общий коэффициент             (масштаб всего прогноза)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass
class Adjustment:
    """Набор поправок, приходящий из интерфейса."""

    weather: float = 1.0
    weather_from: date | None = None
    weather_to: date | None = None

    event: float = 1.0
    event_from: date | None = None
    event_to: date | None = None

    global_factor: float = 1.0
    route_factors: dict = field(default_factory=dict)

    @property
    def is_identity(self) -> bool:
        return (
            self.weather == 1.0
            and self.event == 1.0
            and self.global_factor == 1.0
            and not self.route_factors
        )

    def factor(self, route: int, day: date) -> float:
        value = self.global_factor
        if self.weather != 1.0 and _in_range(day, self.weather_from, self.weather_to):
            value *= self.weather
        if self.event != 1.0 and _in_range(day, self.event_from, self.event_to):
            value *= self.event
        if self.route_factors:
            value *= self.route_factors.get(route, 1.0)
        return value

    def describe(self) -> list:
        """Человекочитаемое описание применённых поправок — уходит в ответ API,
        чтобы в интерфейсе было видно, из чего сложился результат."""
        parts = []
        if self.global_factor != 1.0:
            parts.append(
                {
                    "kind": "global",
                    "factor": self.global_factor,
                    "label": f"Общая поправка ×{self.global_factor:.2f}",
                }
            )
        if self.weather != 1.0:
            parts.append(
                {
                    "kind": "weather",
                    "factor": self.weather,
                    "from": str(self.weather_from) if self.weather_from else None,
                    "to": str(self.weather_to) if self.weather_to else None,
                    "label": f"Погодная поправка ×{self.weather:.2f}",
                }
            )
        if self.event != 1.0:
            parts.append(
                {
                    "kind": "event",
                    "factor": self.event,
                    "from": str(self.event_from) if self.event_from else None,
                    "to": str(self.event_to) if self.event_to else None,
                    "label": f"Поправка на событие ×{self.event:.2f}",
                }
            )
        for route, factor in sorted(self.route_factors.items()):
            parts.append(
                {
                    "kind": "route",
                    "route": route,
                    "factor": factor,
                    "label": f"Маршрут {route} ×{factor:.2f}",
                }
            )
        return parts


def _in_range(day: date, start: date | None, end: date | None) -> bool:
    if start and day < start:
        return False
    if end and day > end:
        return False
    return True


def parse_route_factors(raw: str | None) -> dict:
    """Разбирает строку вида "17:1.1,50:0.8" из query-параметра."""
    if not raw:
        return {}
    result = {}
    for chunk in raw.split(","):
        if ":" not in chunk:
            continue
        route_part, factor_part = chunk.split(":", 1)
        try:
            result[int(route_part.strip())] = float(factor_part.strip())
        except ValueError:
            continue
    return result
