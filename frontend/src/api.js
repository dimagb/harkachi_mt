export const API = "/api";
export function query(params = {}) {
  return new URLSearchParams(
    Object.entries(params)
      .filter(([, v]) => v !== "" && v != null)
      .map(([k, v]) => [k, Array.isArray(v) ? v.join(",") : String(v)]),
  ).toString();
}
export async function request(path, params = {}, signal, options = {}) {
  const res = await fetch(
    `${API}${path}${Object.keys(params).length ? "?" + query(params) : ""}`,
    { signal, ...options },
  );
  if (!res.ok) {
    const e = await res.json().catch(() => ({}));
    throw new Error(
      typeof e.detail === "string" ? e.detail : e.message || `Ошибка API ${res.status}`,
    );
  }
  if (res.status === 204) return null;
  const type = res.headers.get("content-type") || "";
  if (!type.includes("json"))
    throw new Error("API недоступен: сервер вернул страницу вместо JSON.");
  return res.json();
}
export function period(horizon, date = "2025-12-15") {
  const [y, m] = date.split("-");
  if (horizon === "year")
    return { date_from: `${y}-01-01`, date_to: `${y}-12-31` };
  if (horizon === "month")
    return {
      date_from: `${y}-${m}-01`,
      date_to: `${y}-${m}-${new Date(Number(y), Number(m), 0).getDate()}`,
    };
  return { date_from: date, date_to: date };
}
export function forecastParams(filters, coefficients, scenario = true) {
  const p = {
    routes: filters.routes.join(","),
    date_from: filters.date_from,
    date_to: filters.date_to,
    hour_from: filters.hour_from,
    hour_to: filters.hour_to,
    horizon: filters.horizon,
    granularity: { day: "hour", month: "day", year: "month" }[filters.horizon],
    split_by_route: true,
    source: "forecast",
  };
  return scenario
    ? {
        ...p,
        k_global: coefficients.k_global,
        k_weather: coefficients.k_weather,
        k_event: coefficients.k_event,
        k_routes: coefficients.k_routes,
        weather_from: coefficients.weather_from,
        weather_to: coefficients.weather_to,
        event_from: coefficients.event_from,
        event_to: coefficients.event_to,
      }
    : p;
}
export function mergeYear(history, forecast) {
  const points = new Map(
    (history?.points || []).map((p) => [p.key, { ...p, source: "history" }]),
  );
  for (const p of forecast?.points || [])
    points.set(p.key, { ...p, source: "forecast" });
  return [...points.values()].sort((a, b) =>
    String(a.key).localeCompare(String(b.key)),
  );
}
export function mergeByRoute(history = {}, forecast = {}) {
  return Object.fromEntries(
    [...new Set([...Object.keys(history), ...Object.keys(forecast)])].map(
      (route) => {
        const points = (v) => (Array.isArray(v) ? v : v?.points || []);
        return [
          route,
          mergeYear(
            { points: points(history[route]) },
            { points: points(forecast[route]) },
          ),
        ];
      },
    ),
  );
}
export const asList = (data, key) =>
  Array.isArray(data) ? data : Array.isArray(data?.[key]) ? data[key] : [];
export const format = (n, d = 0) =>
  Number.isFinite(Number(n))
    ? Number(n).toLocaleString("ru-RU", { maximumFractionDigits: d })
    : "—";
