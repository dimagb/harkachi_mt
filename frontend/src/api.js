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
  // Закешированные ответы бекенда приходят без Content-Type, поэтому
  // отвергаем только явную HTML-страницу, а остальное разбираем как JSON.
  const type = res.headers.get("content-type") || "";
  const text = await res.text();
  if (type.includes("html") || /^\s*</.test(text))
    throw new Error("API недоступен: сервер вернул страницу вместо JSON.");
  try {
    return JSON.parse(text);
  } catch {
    throw new Error("API вернул ответ, который не удалось разобрать как JSON.");
  }
}
export function addDays(iso, n) {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}
const weekday = (iso) => new Date(`${iso}T00:00:00Z`).getUTCDay();
// Средний час по дням окна: points — почасовой ряд истории с ключами
// ГГГГ-ММ-ДДTЧЧ. Делим на число календарных дней окна, а не на число
// точек: часы без посадок в ряду отсутствуют и среднее бы завышали.
export function hourProfile(points, from, to, { sameWeekdayAs, keyDate } = {}) {
  const days = [];
  for (let d = from; d <= to; d = addDays(d, 1))
    if (!sameWeekdayAs || weekday(d) === weekday(sameWeekdayAs)) days.push(d);
  const wanted = new Set(days);
  const sums = new Map();
  for (const p of points) {
    const [d, h] = String(p.key).split("T");
    if (h == null || !wanted.has(d)) continue;
    sums.set(h, (sums.get(h) || 0) + (Number(p.value) || 0));
  }
  return [...sums.keys()].sort().map((h) => ({
    key: keyDate ? `${keyDate}T${h}` : h,
    label: `${h}:00`,
    value: Math.round((sums.get(h) / Math.max(days.length, 1)) * 10) / 10,
  }));
}
// Прогноз на период длиннее месяца preview отдаёт по дням; для горизонта
// «год» сворачиваем в месяцы, чтобы шаг совпадал с историей.
export function toMonths(points) {
  const months = new Map();
  for (const p of points) {
    const k = String(p.key).slice(0, 7);
    months.set(k, (months.get(k) || 0) + (Number(p.value) || 0));
  }
  return [...months].sort().map(([key, value]) => ({ key, label: key, value }));
}
// «Мост» между фактом и прогнозом на годовом графике: последний месяц
// истории с его фактическим значением ставится первой точкой ряда
// прогноза, чтобы линия прогноза начиналась там, где кончается факт.
// Значение не выдумывается — это та же точка истории. Только если оба
// ряда непусты и месяцы соседние.
export function withBridge(forecast = [], history = []) {
  if (!forecast.length || !history.length) return forecast;
  const last = [...history].sort((a, b) => String(a.key).localeCompare(String(b.key))).at(-1);
  const lastKey = String(last.key), firstKey = String(forecast[0].key);
  if (!/^\d{4}-\d{2}$/.test(lastKey) || !/^\d{4}-\d{2}$/.test(firstKey)) return forecast;
  const [y, m] = lastKey.split("-").map(Number);
  const next = m === 12 ? `${y + 1}-01` : `${y}-${String(m + 1).padStart(2, "0")}`;
  if (next !== firstKey) return forecast;
  return [{ ...last, bridge: true }, ...forecast];
}
export function scenarioFactor(explain = []) {
  return explain.reduce(
    (k, step) => (step.factor == null ? k : k * Number(step.factor)),
    1,
  );
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
