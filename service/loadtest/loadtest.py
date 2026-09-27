#!/usr/bin/env python3
"""Нагрузочный тест сервиса. Только стандартная библиотека — ставить нечего.

Цифры из вывода идут прямо в README и в форму сдачи: это обязательное
требование ТЗ («В ОБЯЗАТЕЛЬНОМ ПОРЯДКЕ УКАЖИТЕ ДАННЫЕ О ПРОИЗВОДИТЕЛЬНОСТИ»).

Запуск:
    python loadtest.py                                  # 30 секунд, 32 потока
    python loadtest.py --duration 60 --threads 64
    python loadtest.py --url http://localhost:8000
"""

from __future__ import annotations

import argparse
import http.client
import statistics
import sys
import threading
import time
import urllib.parse
import urllib.request
from collections import Counter

# Сценарий: смесь типовых запросов дашборда
ENDPOINTS = [
    "/api/health",
    "/api/forecast?routes=17&horizon=day&date_from=2025-12-15&date_to=2025-12-15",
    "/api/forecast?horizon=month",
    "/api/forecast/routes",
    "/api/forecast/stops?route=17",
    "/api/routes",
    "/api/forecast?routes=11,12,17&horizon=month&k_weather=1.1"
    "&weather_from=2025-12-01&weather_to=2025-12-10",
]


def worker(base_url, deadline, latencies, statuses, cache_marks, lock,
           stop_event, cold, worker_id):
    local_lat = []
    local_status = Counter()
    local_cache = Counter()
    index = 0
    # Одно keep-alive соединение на поток, как у браузера. Новое TCP-
    # соединение на каждый запрос на Windows за полминуты исчерпывает
    # локальные порты (TIME_WAIT, WinError 10048) — и тест меряет клиента,
    # а не сервис.
    parsed = urllib.parse.urlsplit(base_url)
    host, port = parsed.hostname, parsed.port or 80
    conn = None
    while time.time() < deadline and not stop_event.is_set():
        path = ENDPOINTS[index % len(ENDPOINTS)]
        index += 1
        if cold:
            # Кеш ключуется полной строкой запроса, поэтому уникальный
            # параметр гарантирует MISS: считается весь путь запроса.
            path += ("&" if "?" in path else "?") + f"_nc={worker_id}-{index}"
        started = time.perf_counter()
        try:
            if conn is None:
                conn = http.client.HTTPConnection(host, port, timeout=10)
            conn.request("GET", path)
            response = conn.getresponse()
            response.read()
            code = response.status
            local_cache[response.getheader("X-Cache", "none")] += 1
        except Exception:  # noqa: BLE001 — таймауты и обрывы тоже считаем
            code = 0
            if conn is not None:
                conn.close()
            conn = None
        local_lat.append((time.perf_counter() - started) * 1000)
        local_status[code] += 1

    if conn is not None:
        conn.close()
    with lock:
        latencies.extend(local_lat)
        statuses.update(local_status)
        cache_marks.update(local_cache)


def percentile(values, share):
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(int(len(ordered) * share), len(ordered) - 1)
    return ordered[index]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--duration", type=int, default=30, help="секунд")
    parser.add_argument("--threads", type=int, default=32)
    parser.add_argument("--warmup", type=int, default=3, help="секунд прогрева")
    parser.add_argument(
        "--cold", action="store_true",
        help="каждый запрос уникален — кеш ответов не попадает ни разу",
    )
    args = parser.parse_args()
    if args.cold:
        args.warmup = 0

    base_url = args.url.rstrip("/")

    print(f"Проверяю доступность {base_url}/api/health …")
    try:
        with urllib.request.urlopen(base_url + "/api/health", timeout=5) as r:
            print(f"  {r.status} — сервис отвечает")
    except Exception as exc:  # noqa: BLE001
        sys.exit(f"  сервис недоступен: {exc}")

    if args.warmup:
        print(f"Прогрев {args.warmup} с …")
        end = time.time() + args.warmup
        while time.time() < end:
            for path in ENDPOINTS:
                try:
                    urllib.request.urlopen(base_url + path, timeout=5).read()
                except Exception:  # noqa: BLE001
                    pass
                if time.time() >= end:
                    break

    mode = "холодный кеш (--cold)" if args.cold else "прогретый кеш"
    print(f"Нагрузка: {args.threads} потоков, {args.duration} с, {mode}\n")
    latencies: list = []
    statuses: Counter = Counter()
    cache_marks: Counter = Counter()
    lock = threading.Lock()
    stop_event = threading.Event()
    deadline = time.time() + args.duration

    threads = [
        threading.Thread(
            target=worker,
            args=(base_url, deadline, latencies, statuses, cache_marks, lock,
                  stop_event, args.cold, n),
            daemon=True,
        )
        for n in range(args.threads)
    ]

    started = time.perf_counter()
    for thread in threads:
        thread.start()
    try:
        for thread in threads:
            thread.join()
    except KeyboardInterrupt:
        stop_event.set()
    elapsed = time.perf_counter() - started

    total = sum(statuses.values())
    ok = statuses.get(200, 0)
    print("=" * 62)
    print("РЕЗУЛЬТАТЫ НАГРУЗОЧНОГО ТЕСТА")
    print("=" * 62)
    print(f"  длительность:      {elapsed:.1f} с")
    print(f"  потоков:           {args.threads}")
    print(f"  запросов:          {total}")
    print(f"  успешных (200):    {ok} ({100 * ok / max(total, 1):.1f}%)")
    if len(statuses) > 1:
        print(f"  прочие коды:       {dict(statuses)}")
    print(f"  RPS:               {total / elapsed:.0f}")
    hits, misses = cache_marks.get("HIT", 0), cache_marks.get("MISS", 0)
    print(f"  режим:             {mode}")
    print(f"  X-Cache:           HIT {hits}, MISS {misses}, "
          f"без кеша {cache_marks.get('none', 0)} "
          f"(доля попаданий {100 * hits / max(hits + misses, 1):.1f}%)")
    print()
    print(f"  latency p50:       {percentile(latencies, 0.50):.1f} мс")
    print(f"  latency p95:       {percentile(latencies, 0.95):.1f} мс")
    print(f"  latency p99:       {percentile(latencies, 0.99):.1f} мс")
    print(f"  latency avg:       {statistics.fmean(latencies):.1f} мс")
    print(f"  latency max:       {max(latencies):.1f} мс")
    print()
    p95 = percentile(latencies, 0.95)
    rps = total / elapsed
    target_ok = p95 < 300 and rps >= 100
    print(f"  Требование ТЗ: сотни RPS при p95 < 200–300 мс")
    print(f"  Результат: {'ВЫПОЛНЕНО' if target_ok else 'НЕ ДОСТИГНУТО'}")
    print()
    print("  Скопируйте эти цифры в README и в форму сдачи.")
    print("  Укажите рядом конфигурацию: сколько vCPU и RAM было у контейнера.")


if __name__ == "__main__":
    main()
