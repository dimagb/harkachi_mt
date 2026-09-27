// Explicit demonstration fixtures. Never silently substitute for a failed API.
import { period } from "./api";
export const routes = [17, 12, 11, 1, 28, 26, 7, 50, 25, 5].map((route, i) => ({
  route,
  share: [0.236, 0.157, 0.15, 0.086, 0.047, 0.082, 0.109, 0.101, 0.033, 0][i],
  total: [168400, 112080, 88600, 79400, 70100, 63000, 58000, 55000, 32000, 0][
    i
  ],
  has_geometry: [1, 5, 7, 11, 12].includes(route),
  in_data: route !== 5,
  note:
    route === 5
      ? "Маршрут запущен 16 декабря 2025. До этой даты прогноз равен нулю."
      : "",
}));
const daily = [
  6, 4, 3.5, 3.8, 5, 8, 14, 31, 44, 35, 25, 21, 22, 23, 23, 25, 30, 39, 48, 40,
  22, 13, 8, 6,
];
export function demoForecast(p = {}) {
  const h = p.horizon || "day",
    n =
      h === "day"
        ? 24
        : h === "month"
          ? new Date(
              Number(p.date_to?.slice(0, 4) || 2025),
              Number(p.date_to?.slice(5, 7) || 12),
              0,
            ).getDate()
          : 12;
  const selected = p.routes
    ? String(p.routes).split(",")
    : routes.map((r) => String(r.route));
  const routeWeight =
    selected.reduce(
      (s, r) => s + (routes.find((x) => String(x.route) === r)?.share || 0),
      0,
    ) || (selected.includes("5") ? 0.02 : 1);
  const points = Array.from({ length: n }, (_, i) => {
    const label =
      h === "day"
        ? String(i).padStart(2, "0")
        : h === "month"
          ? String(i + 1)
          : [
              "Янв",
              "Фев",
              "Мар",
              "Апр",
              "Май",
              "Июн",
              "Июл",
              "Авг",
              "Сен",
              "Окт",
              "Ноя",
              "Дек",
            ][i];
    const key =
      h === "day"
        ? `${p.date_from || "2025-12-15"}T${label}:00`
        : h === "month"
          ? `${(p.date_from || "2025-12-01").slice(0, 7)}-${String(i + 1).padStart(2, "0")}`
          : `${(p.date_from || "2025").slice(0, 4)}-${String(i + 1).padStart(2, "0")}`;
    const date = key.slice(0, 10).padEnd(10, "1");
    const applies = (from, to) =>
      (!from || date >= from) && (!to || date <= to);
    let k =
      Number(p.k_global || 1) *
      (applies(p.weather_from, p.weather_to) ? Number(p.k_weather || 1) : 1) *
      (applies(p.event_from, p.event_to) ? Number(p.k_event || 1) : 1);
    const kr = Object.fromEntries(
      String(p.k_routes || "")
        .split(",")
        .filter(Boolean)
        .map((v) => v.split(":")),
    );
    k *=
      selected.reduce(
        (sum, r) =>
          sum +
          (routes.find((x) => String(x.route) === r)?.share || 0.02) *
            Number(kr[r] || 1),
        0,
      ) / routeWeight;
    let value =
      (h === "day"
        ? daily[i] * 1000
        : h === "month"
          ? (31 + 8 * Math.sin(i * 0.6) + 5 * Math.cos(i * 0.9)) * 1000
          : [
              9.8, 10.7, 11.8, 12.5, 13.3, 11.7, 9.6, 9.9, 10.5, 11.1, 10.7,
              11.6,
            ][i] * 1e6) *
      routeWeight *
      (p.source === "history" ? 0.82 : k);
    if (selected.length === 1 && selected[0] === "5" && date < "2025-12-16")
      value = 0;
    return { key, label, value: Math.round(value) };
  })
    .filter(
      (_, i) =>
        h !== "day" ||
        (i >= Number(p.hour_from || 0) && i <= Number(p.hour_to ?? 23)),
    )
    .filter(
      (_, i) => h !== "year" || (p.source === "history" ? i < 10 : i >= 10),
    );
  const peak = points.reduce((a, b) => (b.value > a.value ? b : a), {
    value: 0,
  });
  return {
    points,
    summary: {
      total: points.reduce((s, p) => s + p.value, 0),
      peak: { ...peak, route: selected[0], date: p.date_from, hour: 18 },
      buckets: points.length,
    },
    adjustments: ["k_global", "k_weather", "k_event", "k_routes"]
      .filter((k) => p[k] && String(p[k]) !== "1")
      .map((k) => ({
        label: `${{ k_global: "Общий масштаб", k_weather: "Погодная поправка", k_event: "Событие", k_routes: "Маршрут" }[k]} ×${p[k]}`,
      })),
    by_route: Object.fromEntries(
      selected.map((r) => [
        r,
        points.map((x) => ({
          ...x,
          value:
            (x.value *
              (routes.find((t) => String(t.route) === r)?.share || 0.02)) /
            routeWeight,
        })),
      ]),
    ),
    network_events: [],
  };
}
export function demoData(path, p) {
  if (path === "/forecast") return demoForecast(p);
  if (path === "/forecast/routes" || path === "/routes")
    return {
      routes: routes.filter(
        (r) =>
          !p.routes || String(p.routes).split(",").includes(String(r.route)),
      ),
    };
  if (path === "/geometry")
    return {
      type: "FeatureCollection",
      features: [],
      routes_without_geometry: [17, 25, 26, 28, 50],
    };
  if (path === "/forecast/stops" || path === "/stops")
    return {
      stops: [],
      estimated: true,
      note: "Разбивка по остановкам оценочная: в исходных данных нет привязки валидаций к остановкам. В деморежиме координаты не подменяются вымышленными.",
    };
  if (path === "/forecast/compare")
    return {
      history: demoForecast({ ...p, source: "history" }),
      forecast: demoForecast(p),
    };
  if (path === "/health") return { status: "demo" };
  if (path === "/meta")
    return {
      history_to: "2025-10-31",
      forecast_from: "2025-11-01",
      forecast_to: "2025-12-31",
      model_version: "v7",
      aggregation: "5 мин",
      updated_at: "12:34",
      coverage: "Полное",
    };
  if (path === "/factors")
    return {
      seasons: { warm: [4, 5, 6, 7, 8, 9], cold: [1, 2, 3, 10, 11, 12] },
      options: [
        ["WEATHER", "RAIN_LIGHT", "warm", "Небольшой дождь", 0.973, true],
        ["WEATHER", "RAIN", "warm", "Дождь", 0.946, true],
        ["WEATHER", "RAIN_HEAVY", "warm", "Сильный дождь", 0.897, true],
        ["WEATHER", "SNOW", "warm", "Снег", 0.958, true],
        ["WEATHER", "HEAT", "warm", "Жара", 0.964, true],
        ["EVENT", "MEDIUM", "all", "Среднее событие у линии", 1.05, false],
        ["EVENT", "MAJOR", "all", "Крупное событие у линии", 1.15, false],
      ].map(([factor_code, option_code, season, label, value, confirmed]) => ({
        factor_code, option_code, season, label, value, confirmed,
      })),
      factors: [
        { name: "Погода", effect: -6.3 },
        { name: "Календарь / сезонность", effect: 11.8 },
        { name: "Городские события", effect: 4.9 },
      ],
    };
  if (path === "/scope")
    return {
      note: "Демонстрационный режим. Область определения и ограничения модели будут получены из /api/scope после подключения бекенда.",
    };
  return [];
}

export function demoPreview(body) {
  const month = Number(body.from.slice(5, 7));
  const season = month >= 4 && month <= 9 ? "warm" : "cold";
  const options = demoData("/factors").options;
  const option = (factor, code) => options.find((item) =>
    item.factor_code === factor && item.option_code === code &&
    (item.season === season || item.season === "all") && item.confirmed);
  const weather = body.weather === "NORMAL" ? null : option("WEATHER", body.weather);
  const event = body.event === "NONE" ? null : option("EVENT", body.event);
  if (body.weather !== "NORMAL" && !weather) throw new Error("Для выбранной даты погодный сценарий недоступен");
  if (body.event !== "NONE" && !event) throw new Error("Для выбранной даты сценарий события недоступен");
  const params = { horizon: body.from === body.to ? "day" : "month", date_from: body.from, date_to: body.to,
    routes: body.routes?.join(",") || "" };
  const base = demoForecast(params);
  const multiplier = (weather?.value || 1) * (event?.value || 1) *
    (1 + body.season_adjustment_pct / 100) * (1 + body.manual_adjustment_pct / 100);
  const scenario = demoForecast({ ...params, k_global: multiplier });
  return { base, scenario, difference_pct: base.summary.total ?
    (scenario.summary.total / base.summary.total - 1) * 100 : null };
}
