#!/usr/bin/env python3
"""Согласованность состояния между воркерами. Только стандартная библиотека.

Проверяет то, что показывается жюри вживую, против уже запущенного сервиса:

    python loadtest/consistency.py --url http://localhost:8000

  * добавили FULL_CLOSURE — каждый из следующих запросов показывает нули,
    10 итераций подряд;
  * сняли событие — значения вернулись, 10 итераций;
  * отправили батч валидаций — /api/meta и /api/ingest/aggregates видят его
    сразу, 10 батчей;
  * один батч в 20 потоков — засчитан ровно один раз;
  * одно событие в 10 потоков — одно 201, остальные 409;
  * POST /api/reload — ни одного ответа со старыми данными.

Каждый ответ помечен заголовком X-Worker (PID процесса). Скрипт считает,
сколько проверок пришлось на ДРУГОЙ воркер, чем тот, что принял изменение:
именно они доказывают согласованность. Если таких ноль — проверка ничего
не доказала, запустите ещё раз.

ВНИМАНИЕ: скрипт меняет состояние сервиса. События он снимает за собой,
а принятые батчи (маршрут 12, 25, дата 2025-10-31, batch_id с префиксом
consistency-) остаются в агрегатах приёма. Запускайте до демо или на
чистом томе: docker compose down -v && docker compose up.

Если хоть одна проверка FAIL — оставлять несколько воркеров нельзя,
верните --workers 1 в Dockerfile.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import Counter

FAILS: list = []


def make_call(base):
    def call(method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            base + path, data=data, method=method,
            headers={"Content-Type": "application/json", "Connection": "close"},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, json.loads(r.read() or b"{}"), r.headers.get("X-Worker")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}"), e.headers.get("X-Worker")
    return call


def check(name, cond, extra=""):
    print(("OK   " if cond else "FAIL ") + name + (f"  [{extra}]" if extra else ""), flush=True)
    if not cond:
        FAILS.append(name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://localhost:8000")
    args = parser.parse_args()
    call = make_call(args.url.rstrip("/"))
    run_id = str(int(time.time()))
    cross = Counter()

    seen = Counter(call("GET", "/api/health")[2] for _ in range(60))
    check(f"ответили воркеров: {len(seen)}", len(seen) >= 1, dict(seen))
    if len(seen) < 2:
        print("  Все запросы пришли в один процесс: либо воркер один, либо не повезло "
              "с балансировкой — межпроцессная часть проверена не будет.")

    F = "/api/forecast?routes=17&horizon=month&date_from=2025-11-01&date_to=2025-11-30"
    s, base, _ = call("GET", F)
    base_pts = {p["key"]: p["value"] for p in base["points"]}
    inside = [k for k in base_pts if "2025-11-10" <= k <= "2025-11-20"]
    for _ in range(20):
        call("GET", F)  # прогреть кеш во всех воркерах

    closure = {"route": 17, "type": "FULL_CLOSURE", "valid_from": "2025-11-10",
               "valid_to": "2025-11-20", "title": f"consistency-{run_id}"}
    ok_close = ok_open = 0
    for i in range(10):
        s, ev, w_post = call("POST", "/api/network-events", closure)
        if s != 201:
            check(f"итерация {i}: POST события", False, (s, ev))
            continue
        good = True
        for _ in range(4):
            s, r, w = call("GET", F)
            pts = {p["key"]: p["value"] for p in r["points"]}
            cross["closure"] += w != w_post
            good &= all(pts[k] == 0 for k in inside)
        ok_close += good
        s, _, w_del = call("DELETE", f"/api/network-events/{ev['id']}")
        good = True
        for _ in range(4):
            s, r, w = call("GET", F)
            pts = {p["key"]: p["value"] for p in r["points"]}
            cross["reopen"] += w != w_del
            good &= pts == base_pts
        ok_open += good
    check("закрытие видно сразу: итераций 10 из 10", ok_close == 10,
          f"{ok_close}/10; запросов в другой воркер {cross['closure']} из 40")
    check("снятие видно сразу: итераций 10 из 10", ok_open == 10,
          f"{ok_open}/10; запросов в другой воркер {cross['reopen']} из 40")

    s, m, _ = call("GET", "/api/meta")
    batches0 = m["ingest_batches"]
    s, a, _ = call("GET", "/api/ingest/aggregates?routes=12&date_from=2025-10-31&date_to=2025-10-31")
    base12 = sum(r["boardings"] for r in a["rows"])
    ok_ing = 0
    for i in range(10):
        s, r, w_post = call("POST", "/api/ingest/validations", {
            "batch_id": f"consistency-{run_id}-{i}",
            "records": [{"timestamp": "2025-10-31T08:00:00+03:00", "route": 12}] * (i + 1),
        })
        expected = base12 + sum(range(1, i + 2))
        good = s == 200
        for _ in range(3):
            s, m, w1 = call("GET", "/api/meta")
            s, a, w2 = call("GET", "/api/ingest/aggregates?routes=12&date_from=2025-10-31&date_to=2025-10-31")
            cross["ingest"] += (w1 != w_post) + (w2 != w_post)
            good &= m["ingest_batches"] == batches0 + i + 1
            good &= sum(r["boardings"] for r in a["rows"]) == expected
        ok_ing += good
    check("батч виден сразу в /api/meta и агрегатах: 10 из 10", ok_ing == 10,
          f"{ok_ing}/10; запросов в другой воркер {cross['ingest']} из 60")

    results = []
    race = {"batch_id": f"consistency-{run_id}-race",
            "records": [{"timestamp": "2025-10-31T09:00:00+03:00", "route": 25}] * 5}
    threads = [threading.Thread(target=lambda: results.append(call("POST", "/api/ingest/validations", race)))
               for _ in range(20)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    fresh = sum(1 for s, b, _ in results if s == 200 and b.get("already_processed") is False)
    check("один батч в 20 потоков: засчитан ровно один раз", fresh == 1,
          f"новых {fresh}, воркеров {len({w for *_, w in results})}")

    results = []
    dup = {"route": 26, "type": "MANUAL_MULTIPLIER", "valid_from": "2025-12-01",
           "factor": 0.9, "title": f"consistency-{run_id}"}
    threads = [threading.Thread(target=lambda: results.append(call("POST", "/api/network-events", dup)))
               for _ in range(10)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    codes = Counter(s for s, *_ in results)
    check("одно событие в 10 потоков: одно 201, девять 409", codes[201] == 1 and codes[409] == 9, dict(codes))
    for s, b, _ in results:
        if s == 201:
            call("DELETE", f"/api/network-events/{b['id']}")

    s, m, _ = call("GET", "/api/meta")
    before = m["data"]["loaded_at"]
    time.sleep(1.1)
    s, _, w_rel = call("POST", "/api/reload")
    answers = [call("GET", "/api/meta") for _ in range(40)]
    stale = sum(1 for _, m, _ in answers if not m["data"]["loaded_at"] > before)
    other = sum(1 for *_, w in answers if w != w_rel)
    check("POST /api/reload: ответов со старыми данными 0 из 40", stale == 0,
          f"устаревших {stale}; в другой воркер {other} из 40")

    total_cross = sum(cross.values()) + other
    print(f"\nПроверок, пришедших в другой воркер: {total_cross}")
    if total_cross == 0:
        print("  Межпроцессная согласованность НЕ проверена — запустите ещё раз.")
    print("ИТОГ:", "всё прошло" if not FAILS else f"провалено {len(FAILS)}: {FAILS}")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
