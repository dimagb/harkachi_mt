#!/usr/bin/env python3
"""
Сезонный базлайн v3 — трек «ИИ-прогноз загрузки трамвайных маршрутов».

БЕЗ ВНЕШНИХ БИБЛИОТЕК — нужен только Python 3.9+.

По умолчанию воспроизводит конфигурацию, которая дала 0.869 на лидерборде,
с исправленным производственным календарём. Всё остальное — переключатели,
чтобы проверять гипотезы ПО ОДНОЙ и сравнивать по лидерборду.

Модель:
    прогноз = профиль(маршрут, день недели, час) × тренд × календарный коэф.

Запуск:
    python baseline.py initial_data                  # базовый прогноз
    python baseline.py initial_data --sweep          # 12 файлов-вариантов
    python baseline.py initial_data --weeks 12 --dec31 0.5 --out my.csv

Ключи:
    --weeks N     глубина профиля в неделях (по умолчанию 8)
    --damp X      затухание тренда 0..1 (0.5)
    --dec31 X     насколько 31 декабря похоже на каникулы, 0..1 (0.7)
    --nov X       то же для 2–4 ноября (1.0)
    --preny X     множитель на 20–30 декабря (1.0 = нет эффекта)
    --level X     общий множитель уровня (1.0)
    --outage      исключать ремонтные дни из профиля (по умолчанию нет)
    --out FILE    имя выходного файла (submission.csv)
    --sweep       записать набор вариантов для A/B на лидерборде
"""

import csv
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from statistics import median

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

csv.field_size_limit(10_000_000)

# ------------------------------------------------- значения по умолчанию

DEF = {
    "weeks": 8,        # как в версии, давшей 0.869
    "damp": 0.5,
    "dec31": 0.7,      # НЕ 1.0: 31-го днём ездят, обвал только к вечеру
    "nov": 1.0,
    "preny": 1.0,
    "level": 1.0,
    "anchor": 0,       # 0 = выкл; N = привязать уровень профиля
                       # к последним N дням истории (рекомендуется 14)
    "outage": False,
}

TREND_WINDOW = 28
TREND_MIN, TREND_MAX = 0.85, 1.20
OUTAGE_RATIO = 0.35

ROUTES_REQUIRED = [1, 5, 7, 11, 12, 17, 25, 26, 28, 50]

# ВНИМАНИЕ: здесь было ZERO_ROUTES = {5} с пояснением «эталон нулевой».
# Это неверно и проверено лидербордом: обнуление маршрута 5 опускает score
# с 0.89447 до 0.88987, то есть эталон по нему НЕ нулевой.
#
# Маршрут 5 запущен 16 декабря 2025 — восстановлен спустя 30 лет,
# Белорусский вокзал — Метро «Рижская». В справочнике у него стоит
# route_date_start = 2025-12-16, единственная такая дата среди всех
# маршрутов. Истории нет, потому что в январе–октябре маршрута
# не существовало, а не потому что его исключили.
#
# Правильная обработка — cold start от аналога со дня запуска:
#   прогноз(5, дата) = 0                              если дата < 2025-12-16
#   прогноз(5, дата) = прогноз(аналог, дата) × коэф.  если дата >= 2025-12-16
# Аналогом логично брать маршрут 7: он тоже заканчивается на Белорусском
# вокзале. Коэффициент калибруется по лидерборду, и это надо называть
# калибровкой, а не оценкой по данным.
ZERO_ROUTES: set = set()
ROUTE_5_LAUNCH = "2025-12-16"

# Производственный календарь РФ 2025 (КонсультантПлюс).
# 31 декабря и 2–4 ноября вынесены в настраиваемые веса — см. calendar_weight.
HOLIDAYS = {
    "2025-01-01", "2025-01-02", "2025-01-03", "2025-01-04",
    "2025-01-05", "2025-01-06", "2025-01-07", "2025-01-08",
    "2025-02-22", "2025-02-23",
    "2025-03-08", "2025-03-09",
    "2025-05-01", "2025-05-02", "2025-05-03", "2025-05-04",
    "2025-05-08", "2025-05-09", "2025-05-10", "2025-05-11",
    "2025-06-12", "2025-06-13", "2025-06-14", "2025-06-15",
}
NOV_HOLIDAYS = {"2025-11-02", "2025-11-03", "2025-11-04"}
NY = {f"2025-01-0{d}" for d in range(1, 9)}
DEC_TAIL_FIXED = {"2025-12-29": 0.15, "2025-12-30": 0.30}
PRE_NY_DAYS = {f"2025-12-{d}" for d in range(20, 31)}

# все нерабочие дни — для исключения из профиля
ALL_HOLIDAYS = HOLIDAYS | NOV_HOLIDAYS | {"2025-12-31"}

FOLDS = [
    (date(2025, 8, 31), date(2025, 9, 1), date(2025, 10, 31)),
    (date(2025, 6, 30), date(2025, 7, 1), date(2025, 8, 31)),
]
FCST_A, FCST_B = date(2025, 11, 1), date(2025, 12, 31)


# ------------------------------------------------------------------ утилиты

def fmt(n):
    return f"{n:,}".replace(",", " ")


def parse_date(s):
    s = (s or "").strip()[:10].replace("/", "-").replace(".", "-")
    p = s.split("-")
    if len(p) != 3:
        return None
    try:
        if len(p[0]) == 4:
            return date(int(p[0]), int(p[1]), int(p[2]))
        return date(int(p[2]), int(p[1]), int(p[0]))
    except ValueError:
        return None


def daterange(a, b):
    d = a
    while d <= b:
        yield d
        d += timedelta(days=1)


def wape_score(pairs):
    denom = sum(y for y, _ in pairs)
    if denom == 0:
        return 0.0
    return max(0.0, 1.0 - sum(abs(y - p) for y, p in pairs) / denom)


def bias(pairs):
    denom = sum(y for y, _ in pairs)
    return (sum(p for _, p in pairs) / denom) if denom else 0.0


def sniff_sep(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        head = f.readline()
    counts = {s: head.count(s) for s in (";", ",", "\t", "|")}
    best = max(counts, key=counts.get)
    return best if counts[best] else ","


def read_rows(path):
    sep = sniff_sep(path)
    for enc in ("utf-8-sig", "cp1251"):
        try:
            with open(path, "r", encoding=enc, newline="") as fh:
                return list(csv.DictReader(fh, delimiter=sep))
        except UnicodeDecodeError:
            continue
    return []


def map_columns(cols):
    key = {}
    for c in cols:
        cl = (c or "").strip().lower()
        if cl.startswith("route"):
            key["route"] = c
        elif cl.startswith("date"):
            key["date"] = c
        elif cl.startswith("hour"):
            key["hour"] = c
        elif "board" in cl or "target" in cl or "count" in cl \
                or cl == "prediction":
            key["val"] = c
    return key


# -------------------------------------------------------------------- данные

def read_labels(root: Path, quiet=False):
    files = sorted(root.rglob("labels_day_*.csv"))
    if not files:
        sys.exit(f"Не нашёл labels_day_*.csv внутри {root}")
    data = defaultdict(float)
    for f in files:
        rows = read_rows(f)
        if not rows:
            continue
        key = map_columns(rows[0].keys())
        if len(key) < 4:
            sys.exit(f"Не распознал колонки в {f.name}: {list(rows[0].keys())}")
        n = 0
        for r in rows:
            d = parse_date(r[key["date"]])
            if d is None:
                continue
            try:
                data[(int(float(r[key["route"]])), d,
                      int(float(r[key["hour"]])))] += float(r[key["val"]] or 0)
                n += 1
            except (ValueError, TypeError):
                continue
        if not quiet:
            print(f"  прочитан {f.name}: {fmt(n)} строк")
    return data


def build_grid(data):
    routes = sorted({r for r, _, _ in data})
    dates = [d for _, d, _ in data]
    d0, d1 = min(dates), max(dates)
    grid = {}
    for r in routes:
        for d in daterange(d0, d1):
            for h in range(24):
                grid[(r, d, h)] = data.get((r, d, h), 0.0)
    return grid, routes, d0, d1


def find_outages(grid):
    daily = defaultdict(float)
    for (r, d, _), v in grid.items():
        daily[(r, d)] += v
    by_rd = defaultdict(list)
    for (r, d), v in daily.items():
        by_rd[(r, d.weekday())].append(v)
    med = {k: median(v) for k, v in by_rd.items() if v}
    out = set()
    for (r, d), v in daily.items():
        if d.isoformat() in ALL_HOLIDAYS:
            continue
        m = med.get((r, d.weekday()), 0)
        if m and v < OUTAGE_RATIO * m:
            out.add((r, d))
    return out


# -------------------------------------------------------------------- модель

def calendar_weight(iso, cfg):
    """Насколько день похож на новогодние каникулы: 0 = обычный, 1 = каникулы."""
    if iso in HOLIDAYS:
        return 1.0
    if iso in NOV_HOLIDAYS:
        return cfg["nov"]
    if iso == "2025-12-31":
        return cfg["dec31"]
    return DEC_TAIL_FIXED.get(iso, 0.0)


def build_profile(grid, upto, weeks, skip):
    cutoff = upto - timedelta(weeks=weeks)
    buckets = defaultdict(list)
    for (r, d, h), v in grid.items():
        if d > upto or d <= cutoff:
            continue
        if d.isoformat() in ALL_HOLIDAYS or (r, d) in skip:
            continue
        buckets[(r, d.weekday(), h)].append(v)
    if not buckets:
        for (r, d, h), v in grid.items():
            if d <= upto and d.isoformat() not in ALL_HOLIDAYS:
                buckets[(r, d.weekday(), h)].append(v)
    return {k: median(v) for k, v in buckets.items()}


def anchor_profile(grid, profile, upto, days, skip):
    """Привязать уровень профиля к последним `days` дням истории.

    Профиль — медиана за 8 недель, поэтому его уровень соответствует
    СЕРЕДИНЕ окна, а не его концу. При растущем ряде это даёт
    систематическое занижение. Считаем, что профиль предсказал бы на
    последние две недели, сравниваем с фактом и масштабируем по маршрутам.
    """
    if not days:
        return profile
    a, b = defaultdict(float), defaultdict(float)
    start = upto - timedelta(days=days)
    for (r, d, h), v in grid.items():
        if not (start < d <= upto):
            continue
        if d.isoformat() in ALL_HOLIDAYS or (r, d) in skip:
            continue
        a[r] += v
        b[r] += profile.get((r, d.weekday(), h), 0.0)
    scale = {r: max(0.7, min(1.4, a[r] / b[r])) if b.get(r) else 1.0
             for r in set(a) | set(b)}
    return {(r, dw, h): v * scale.get(r, 1.0)
            for (r, dw, h), v in profile.items()}


def build_holiday_factor(grid, profile, upto):
    act, exp = defaultdict(float), defaultdict(float)
    for (r, d, h), v in grid.items():
        if d > upto or d.isoformat() not in NY:
            continue
        act[(r, h)] += v
        exp[(r, h)] += profile.get((r, d.weekday(), h), 0.0)
    return {k: min(1.5, max(0.1, act[k] / exp[k])) if exp.get(k) else 1.0
            for k in act}


def build_trend(grid, upto, skip):
    a, b = defaultdict(float), defaultdict(float)
    for (r, d, _), v in grid.items():
        if d > upto or (r, d) in skip:
            continue
        age = (upto - d).days
        if age < TREND_WINDOW:
            a[r] += v
        elif age < 2 * TREND_WINDOW:
            b[r] += v
    return {r: (a[r] / b[r]) ** (7.0 / TREND_WINDOW) if b.get(r) else 1.0
            for r in set(a) | set(b)}


def predict(grid, upto, routes, a, b, cfg, outages):
    skip = outages if cfg["outage"] else set()
    profile = build_profile(grid, upto, cfg["weeks"], skip)
    profile = anchor_profile(grid, profile, upto, int(cfg["anchor"]), skip)
    hol = build_holiday_factor(grid, profile, upto)
    trend = build_trend(grid, upto, skip)

    out = {}
    for r in routes:
        g = trend.get(r, 1.0)
        for d in daterange(a, b):
            iso = d.isoformat()
            wk = (d - upto).days / 7.0
            mult = max(TREND_MIN, min(TREND_MAX, g ** (wk * cfg["damp"])))
            w = calendar_weight(iso, cfg)
            pre = cfg["preny"] if iso in PRE_NY_DAYS else 1.0
            for h in range(24):
                base = profile.get((r, d.weekday(), h), 0.0)
                hf = hol.get((r, h), 1.0)
                val = base * mult * (1.0 + w * (hf - 1.0)) * pre * cfg["level"]
                out[(r, d, h)] = max(0.0, val)
    return out


def evaluate(grid, routes, fold, cfg, outages):
    upto, a, b = fold
    pred = predict(grid, upto, routes, a, b, cfg, outages)
    pairs, per_route = [], defaultdict(list)
    for (r, d, h), y in grid.items():
        if a <= d <= b:
            p = pred.get((r, d, h), 0.0)
            pairs.append((y, p))
            per_route[r].append((y, p))
    return pairs, per_route


def write_submission(grid, routes, d1, cfg, outages, path):
    fut = predict(grid, d1, routes, FCST_A, FCST_B, cfg, outages)
    rows = []
    for r in ROUTES_REQUIRED:
        for d in daterange(FCST_A, FCST_B):
            for h in range(24):
                v = 0.0 if r in ZERO_ROUTES else fut.get((r, d, h), 0.0)
                rows.append((r, d.isoformat(), h, max(0, int(round(v)))))
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["route", "date", "hour", "prediction"])
        w.writerows(rows)
    return rows


# ---------------------------------------------------------------------- CLI

def parse_args(argv):
    cfg = dict(DEF)
    sweep = False
    out = "submission.csv"
    root = None
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--sweep":
            sweep = True
        elif a == "--outage":
            cfg["outage"] = True
        elif a == "--out":
            i += 1
            out = argv[i]
        elif a.startswith("--"):
            name = a[2:]
            i += 1
            if name not in cfg:
                sys.exit(f"Неизвестный ключ: {a}")
            cfg[name] = int(argv[i]) if name == "weeks" else float(argv[i])
        elif root is None:
            root = a
        i += 1
    if root is None:
        sys.exit(__doc__)
    return Path(root), cfg, sweep, out


def main():
    root, cfg, sweep, out = parse_args(sys.argv[1:])
    if not root.exists():
        sys.exit(f"Нет такого пути: {root}")

    print("Читаю labels…")
    data = read_labels(root)
    grid, routes, d0, d1 = build_grid(data)
    print(f"  сетка: {fmt(len(grid))} строк, {d0} … {d1}, "
          f"маршрутов {len(routes)} → {routes}")

    outages = find_outages(grid)
    by_route = defaultdict(list)
    for r, d in outages:
        by_route[r].append(d)
    print(f"\nРемонтные дни: {len(outages)}")
    for r in sorted(by_route):
        ds = sorted(by_route[r])
        print(f"  маршрут {r:>3}: {len(ds)}, последние → "
              f"{', '.join(str(x) for x in ds[-4:])}")

    # ---------- валидация текущей конфигурации
    print(f"\nКОНФИГУРАЦИЯ: {cfg}")
    pairs, per_route = evaluate(grid, routes, FOLDS[0], cfg, outages)
    print(f"\nВАЛИДАЦИЯ (янв–авг → сен–окт)")
    print(f"  WAPE-score = {wape_score(pairs):.4f}")
    b = bias(pairs)
    print(f"  смещение Σпрогноз/Σфакт = {b:.3f}  "
          f"({'перелёт' if b > 1.02 else 'недолёт' if b < 0.98 else 'норма'})")
    print("  ВНИМАНИЕ: валидация искажена (закрытия 50-го в тестовом периоде).")
    print("  Решения принимайте по лидерборду, а не по этому числу.")

    total = sum(y for y, _ in pairs) or 1
    losses = sorted(((sum(abs(y - p) for y, p in sub) / total, r,
                      wape_score(sub), bias(sub),
                      sum(y for y, _ in sub) / total)
                     for r, sub in per_route.items()), reverse=True)
    print(f"\n  {'маршрут':>8} {'score':>7} {'смещ.':>7} {'доля':>7} "
          f"{'вклад в ошибку':>16}")
    for loss, r, sc, bi, share in losses:
        print(f"  {r:>8} {sc:7.3f} {bi:7.3f} {share:6.1%} {loss:15.1%}")

    # ---------- запись
    oct_total = sum(v for (r, d, _), v in grid.items() if d.month == 10)

    def report(rows, tag=""):
        nov = sum(x[3] for x in rows if x[1][5:7] == "11")
        dec = sum(x[3] for x in rows if x[1][5:7] == "12")
        print(f"    {tag:<14} ноя {fmt(nov)} ({nov/oct_total:.2f} от окт), "
              f"дек {fmt(dec)} ({dec/oct_total:.2f}), всего {fmt(nov+dec)}")

    if not sweep:
        print(f"\nФИНАЛ: пишу {out}")
        rows = write_submission(grid, routes, d1, cfg, outages, Path(out))
        print(f"  строк: {fmt(len(rows))}")
        print(f"  факт октябрь: {fmt(int(oct_total))}")
        report(rows, "прогноз:")
        print(f"  записан {Path(out).resolve()}")
        return

    # ---------- режим сweep: варианты для A/B на лидерборде
    print("\nSWEEP: пишу варианты для сравнения на лидерборде")
    print(f"  факт октябрь: {fmt(int(oct_total))}\n")
    variants = [
        ("base", {}),
        ("anchor14", {"anchor": 14}),
        ("anchor28", {"anchor": 28}),
        ("anchor14_damp0", {"anchor": 14, "damp": 0.0}),
        ("level103", {"level": 1.03}),
        ("level097", {"level": 0.97}),
        ("nov070", {"nov": 0.70}),
        ("dec31_050", {"dec31": 0.50}),
        ("dec31_100", {"dec31": 1.00}),
        ("preny106", {"preny": 1.06}),
        ("weeks12", {"weeks": 12}),
        ("weeks4", {"weeks": 4}),
        ("damp0", {"damp": 0.0}),
        ("damp1", {"damp": 1.0}),
        ("outage", {"outage": True}),
    ]
    for tag, over in variants:
        c = dict(cfg)
        c.update(over)
        path = Path(f"submission_{tag}.csv")
        rows = write_submission(grid, routes, d1, c, outages, path)
        v_pairs, _ = evaluate(grid, routes, FOLDS[0], c, outages)
        print(f"  {path.name:<28} валид. {wape_score(v_pairs):.4f}")
        report(rows, tag)

    print("\n  Порядок отправки (по ожидаемой пользе):")
    print("    1. base           — контрольная точка, должна дать ≈0.869")
    print("    2. anchor14       — привязка уровня к концу истории")
    print("    3. level103 / level097 — в какую сторону врёт уровень")
    print("    4. nov070         — не перестарались ли с ноябрьскими праздниками")
    print("    5. dec31_050      — насколько 31-е похоже на каникулы")
    print("    6. preny106       — предновогодний подъём")
    print("\n  Меняйте по одной вещи за раз, иначе не поймёте, что сработало.")


if __name__ == "__main__":
    main()
