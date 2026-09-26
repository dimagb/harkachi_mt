"""Кеш ответов API.

Дашборд повторяет одни и те же запросы: пользователь переключается между
вкладками, возвращается к тому же маршруту, двигает ползунок туда-обратно.
Прогноз при этом не меняется — он пересчитывается пакетно, а не на запрос.
Поэтому ответы можно кешировать целиком по строке запроса.

Реализация намеренно простая: ограниченный по размеру словарь с вытеснением
самых старых записей. Redis не нужен — данные помещаются в память процесса,
а кеш сбрасывается при перезагрузке данных.
"""

from __future__ import annotations

import threading
from collections import OrderedDict


class ResponseCache:
    def __init__(self, max_entries: int = 512) -> None:
        self._store: OrderedDict = OrderedDict()
        self._lock = threading.Lock()
        self._max_entries = max_entries
        self.hits = 0
        self.misses = 0
        # Растёт при каждой инвалидации. Ответ, который начал считаться до
        # инвалидации, а закончил после, в кеш не попадает — иначе запрос,
        # стартовавший до POST /api/network-events, закешировал бы прогноз
        # без только что добавленного закрытия.
        self.generation = 0

    def get(self, key: str):
        with self._lock:
            if key in self._store:
                self._store.move_to_end(key)
                self.hits += 1
                return self._store[key]
            self.misses += 1
            return None

    def set(self, key: str, value, generation: int | None = None) -> None:
        with self._lock:
            if generation is not None and generation != self.generation:
                return
            self._store[key] = value
            self._store.move_to_end(key)
            while len(self._store) > self._max_entries:
                self._store.popitem(last=False)

    def invalidate(self) -> None:
        """Сбросить ответы, сохранив счётчики попаданий."""
        with self._lock:
            self._store.clear()
            self.generation += 1

    def clear(self) -> None:
        with self._lock:
            self._store.clear()
            self.generation += 1
            self.hits = 0
            self.misses = 0

    @property
    def stats(self) -> dict:
        total = self.hits + self.misses
        return {
            "entries": len(self._store),
            "max_entries": self._max_entries,
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": round(self.hits / total, 3) if total else 0.0,
        }


cache = ResponseCache()
