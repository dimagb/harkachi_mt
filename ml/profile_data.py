#!/usr/bin/env python3
"""
Разведка датасета трека «ИИ-прогноз загрузки трамвайных маршрутов».

БЕЗ ВНЕШНИХ БИБЛИОТЕК — нужен только сам Python 3.9+.
Ничего ставить через pip не надо.

Проверяет ровно те ловушки, на которых легко потерять баллы:
  * полна ли сетка labels (есть ли строки на ночные часы)
  * нет ли провалов по маршрутам (ремонты, закрытия)
  * правильный ли часовой пояс (пики должны быть около 8 и 18 часов)
  * что лежит в сырых CSV и в test_submission.csv

Запуск:
    python profile_data.py initial_data > report.txt
"""

import csv
import sys
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path
from statistics import median

# на Windows консоль часто не в UTF-8; без этого при > report.txt падает
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

csv.field_size_limit(10_000_000)

RAW_PEEK_ROWS = 200_000
ROUTES_EXPECTED = [1, 5, 7, 11, 12, 17, 25, 26, 28, 50]


def line(ch="=", n=78):
    print(ch * n)


def section(title):
    print()
    line()
    print(title)
    line()


def fmt(n):
    return f"{n:,}".replace(",", " ")


def parse_date(s):
    s = s.strip()[:10].replace("/", "-").replace(".", "-")
    p = s.split("-")
    if len(p) != 3:
        return None
    try:
        if len(p[0]) == 4:
            return date(int(p[0]), int(p[1]), int(p[2]))
        return date(int(p[2]), int(p[1]), int(p[0]))
    except ValueError:
        return None


def sniff_sep(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        head = f.readline()
    counts = {s: head.count(s) for s in (";", ",", "\t", "|")}
    best = max(counts, key=counts.get)
    return best if counts[best] else ","


def read_csv_rows(path, limit=None):
    """Читает CSV как список словарей. Пробует utf-8, затем cp1251."""
    for enc in ("utf-8-sig", "cp1251"):
        try:
            sep = sniff_sep(path)
            out = []
            with open(path, "r", encoding=enc, newline="") as f:
                rd = csv.DictReader(f, delimiter=sep)
                for i, row in enumerate(rd):
                    if limit and i >= limit:
                        break
                    out.append(row)
            return out, sep
        except UnicodeDecodeError:
            continue
    return [], ";"


# ------------------------------------------------------------------ состав

def show_files(root: Path):
    section("СОСТАВ ДАТАСЕТА")
    files = sorted((p for p in root.rglob("*") if p.is_file()),
                   key=lambda p: -p.stat().st_size)
    for p in files:
        size = p.stat().st_size
        unit, div = (("ГБ", 1 << 30) if size >= 1 << 30 else
                     ("МБ", 1 << 20) if size >= 1 << 20 else ("КБ", 1 << 10))
        print(f"  {str(p.relative_to(root)):<52} {size/div:>8.1f} {unit}")
    return files


# ------------------------------------------------------------------ labels

def load_labels(root: Path):
    files = sorted(root.rglob("labels_day_*.csv"))
    if not files:
        print("\n!! labels_day_*.csv не найдены")
        return None
    recs = []
    for f in files:
        rows, sep = read_csv_rows(f)
        if not rows:
            print(f"  {f.name}: не удалось прочитать")
            continue
        cols = list(rows[0].keys())
        print(f"  {f.name}: {fmt(len(rows))} строк, разделитель {sep!r}, "
              f"колонки {cols}")
        key = {}
        for c in cols:
            cl = (c or "").strip().lower()
            if cl.startswith("route"):
                key["route"] = c
            elif cl.startswith("date"):
                key["date"] = c
            elif cl.startswith("hour"):
                key["hour"] = c
            elif "board" in cl or "target" in cl or "count" in cl:
                key["val"] = c
        if len(key) < 4:
            print(f"  !! не распознаны колонки в {f.name}: нашёл {key}")
            continue
        for r in rows:
            d = parse_date(r[key["date"]])
            if d is None:
                continue
            try:
                recs.append((int(float(r[key["route"]])),
                             d,
                             int(float(r[key["hour"]])),
                             float(r[key["val"]] or 0)))
            except (ValueError, TypeError):
                continue
    return recs


def check_labels(recs):
    section("LABELS — целевая величина")

    routes = sorted({r for r, _, _, _ in recs})
    dates = [d for _, d, _, _ in recs]
    d0, d1 = min(dates), max(dates)
    n_days = (d1 - d0).days + 1

    print(f"  период: {d0} … {d1}  ({n_days} дней)")
    print(f"  маршрутов: {len(routes)} → {routes}")
    missing = set(ROUTES_EXPECTED) - set(routes)
    if missing:
        print(f"  !! нет маршрутов: {sorted(missing)}")

    expected = len(routes) * n_days * 24
    print(f"\n  строк фактически:    {fmt(len(recs))}")
    print(f"  строк в полной сетке: {fmt(expected)}")
    gap = expected - len(recs)
    if gap > 0:
        print(f"  !! ПРОПУСКОВ: {fmt(gap)}")
        print("     Это часы, которых нет в файле. Перед обучением их надо")
        print("     дописать нулями, иначе модель не выучит ночной провал.")
    else:
        print("  сетка полная")

    zeros = sum(1 for *_, v in recs if v == 0)
    print(f"  строк с нулём: {fmt(zeros)} ({100*zeros/len(recs):.1f}%)")

    # ---- часовой профиль
    print("\n  СУММА ПОСАДОК ПО ЧАСАМ (проверка часового пояса)")
    by_hour = defaultdict(float)
    for _, _, h, v in recs:
        by_hour[h] += v
    mx = max(by_hour.values()) if by_hour else 1
    for h in range(24):
        v = by_hour.get(h, 0)
        bar = "#" * int(40 * v / mx)
        print(f"    {h:02d}  {bar:<40} {fmt(int(v)):>12}")
    peak = max(by_hour, key=by_hour.get)
    print(f"\n  максимум в {peak}:00")
    if peak < 6 or peak > 21:
        print("  !! пик в странное время — возможно, часы в UTC, а не в МСК")

    # ---- вес маршрутов
    print("\n  ДОЛЯ МАРШРУТА В ОБЩЕМ ОБЪЁМЕ (это его вес в WAPE)")
    by_route = defaultdict(float)
    for r, _, _, v in recs:
        by_route[r] += v
    total = sum(by_route.values()) or 1
    for r, v in sorted(by_route.items(), key=lambda kv: -kv[1]):
        print(f"    маршрут {r:>3}: {fmt(int(v)):>12}  {100*v/total:5.1f}%")

    # ---- провалы по дням
    print("\n  ПРОВАЛЫ В ИСТОРИИ (дни с объёмом < 30% медианы маршрута)")
    daily = defaultdict(float)
    for r, d, _, v in recs:
        daily[(r, d)] += v
    per_route = defaultdict(list)
    for (r, d), v in daily.items():
        per_route[r].append((d, v))
    found = False
    for r in sorted(per_route):
        vals = [v for _, v in per_route[r]]
        med = median(vals) if vals else 0
        bad = sorted(d for d, v in per_route[r] if med and v < 0.3 * med)
        if bad:
            found = True
            shown = ", ".join(str(d) for d in bad[:12])
            more = f" … ещё {len(bad)-12}" if len(bad) > 12 else ""
            print(f"    маршрут {r:>3}: {len(bad)} дней → {shown}{more}")
    if not found:
        print("    не найдено")
    else:
        print("    Пометьте эти дни: ремонты и закрытия искажают профили.")

    # ---- помесячно
    print("\n  СУММА ПО МЕСЯЦАМ (тренд и летний спад)")
    by_month = defaultdict(float)
    for _, d, _, v in recs:
        by_month[(d.year, d.month)] += v
    mx = max(by_month.values()) if by_month else 1
    for (y, m), v in sorted(by_month.items()):
        bar = "#" * int(40 * v / mx)
        print(f"    {y}-{m:02d}  {bar:<40} {fmt(int(v)):>12}")

    # ---- новогодние каникулы
    ny = [v for _, d, _, v in recs if date(2025, 1, 1) <= d <= date(2025, 1, 8)]
    nd = len({d for _, d, _, _ in recs
              if date(2025, 1, 1) <= d <= date(2025, 1, 8)})
    nm = [v for _, d, _, v in recs
          if date(2025, 1, 15) <= d <= date(2025, 2, 15)]
    md = len({d for _, d, _, _ in recs
              if date(2025, 1, 15) <= d <= date(2025, 2, 15)})
    if ny and nm and nd and md:
        a, b = sum(ny) / nd, sum(nm) / md
        print("\n  ПРАЗДНИЧНЫЙ РЕЖИМ (1–8 января против обычных дней)")
        print(f"    каникулы: {fmt(int(a))} посадок в день")
        print(f"    обычные:  {fmt(int(b))} посадок в день")
        print(f"    отношение: {a/b:.2f}  ← переносим на конец декабря")


# ------------------------------------------------------------- submission

def check_submission(root: Path):
    path = next(iter(root.rglob("test_submission.csv")), None)
    if path is None:
        return
    section("ШАБЛОН РЕШЕНИЯ — test_submission.csv")
    rows, sep = read_csv_rows(path)
    if not rows:
        print("  не удалось прочитать")
        return
    print(f"  строк: {fmt(len(rows))} (в вашей сдаче нужно 14 640)")
    print(f"  разделитель: {sep!r}")
    print(f"  колонки: {list(rows[0].keys())}")
    col = {c.strip().lower(): c for c in rows[0].keys()}
    if "date" in col:
        ds = sorted(r[col["date"]] for r in rows)
        print(f"  даты: {ds[0]} … {ds[-1]}")
    if "route" in col:
        rs = sorted({r[col["route"]] for r in rows}, key=lambda x: int(float(x)))
        print(f"  маршруты: {rs}")
    if "prediction" in col:
        vals = [float(r[col["prediction"]] or 0) for r in rows]
        print(f"  prediction: min {min(vals)}, max {max(vals)}, "
              f"сумма {fmt(int(sum(vals)))}")
    print("\n  ПЕРВЫЕ 3 СТРОКИ")
    for r in rows[:3]:
        print("   ", r)


# --------------------------------------------------------------- сырые CSV

def check_raw(root: Path):
    for name in ("train.csv", "test.csv"):
        path = next(iter(root.rglob(name)), None)
        if path is None:
            continue
        section(f"СЫРЬЁ — {name} (первые {fmt(RAW_PEEK_ROWS)} строк)")
        rows, sep = read_csv_rows(path, limit=RAW_PEEK_ROWS)
        if not rows:
            print("  не удалось прочитать")
            continue
        cols = list(rows[0].keys())
        print(f"  разделитель: {sep!r}")
        print(f"  колонок: {len(cols)}")
        for c in cols:
            vals = [r.get(c) for r in rows]
            empty = sum(1 for v in vals if v in (None, "", "NULL"))
            print(f"    {str(c):<22} пусто {empty:>7}  "
                  f"уник. {len(set(vals))}")

        for c in cols:
            cl = (c or "").strip().lower()
            if cl in ("validation_result", "tran_type_id", "good_type",
                      "ngpt_route", "place_id"):
                cnt = Counter(r.get(c) for r in rows).most_common(10)
                print(f"\n  {c} — топ значений:")
                for k, v in cnt:
                    print(f"    {str(k):<40} {fmt(v):>10}")

        tcol = next((c for c in cols
                     if (c or "").strip().lower() == "tran_date_time"), None)
        if tcol:
            ds = [parse_date(r[tcol] or "") for r in rows]
            ok = [d for d in ds if d]
            if ok:
                print(f"\n  tran_date_time: {min(ok)} … {max(ok)}, "
                      f"нераспознано {len(ds)-len(ok)}")

        print("\n  ПЕРВАЯ СТРОКА ЦЕЛИКОМ")
        for k, v in rows[0].items():
            print(f"    {str(k):<22} = {v}")


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    root = Path(sys.argv[1])
    if not root.exists():
        sys.exit(f"Нет такого пути: {root}")

    print("ОТЧЁТ О ДАННЫХ")
    print(f"источник: {root.resolve()}")

    show_files(root)

    section("ЧТЕНИЕ LABELS")
    recs = load_labels(root)
    if recs:
        check_labels(recs)

    check_submission(root)
    check_raw(root)

    print()
    line()
    print("Готово.")


if __name__ == "__main__":
    main()
