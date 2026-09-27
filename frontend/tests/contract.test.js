import test from "node:test";
import assert from "node:assert/strict";
import {
  forecastParams,
  period,
  query,
  mergeYear,
  mergeByRoute,
  request,
} from "../src/api.js";
test("annual heatmap combines ten historical months with two forecast months", () => {
  const points = Array.from({length:12}, (_,i) => ({key:`2025-${String(i+1).padStart(2,'0')}`,label:String(i+1),value:i}));
  const result = mergeByRoute({17:points.slice(0,10)}, {17:points.slice(10)});
  assert.equal(result[17].length, 12);
  assert.equal(result[17][11].source, 'forecast');
});
test("period boundaries and leap years", () => {
  assert.deepEqual(period("month", "2024-02-12"), {
    date_from: "2024-02-01",
    date_to: "2024-02-29",
  });
  assert.deepEqual(period("year", "2025-12-15"), {
    date_from: "2025-01-01",
    date_to: "2025-12-31",
  });
});
test("backend parameter names, route coefficients and validity dates are preserved", () => {
  const filters = {
    horizon: "month",
    routes: ["17", "50"],
    ...period("month"),
    hour_from: 3,
    hour_to: 22,
  };
  const c = {
    k_global: 1.2,
    k_weather: 0.9,
    k_event: 1,
    k_routes: "17:1.1,50:0.8",
    weather_from: "2025-12-01",
    weather_to: "2025-12-20",
    event_from: "2025-12-10",
    event_to: "2025-12-12",
  };
  const p = forecastParams(filters, c);
  assert.equal(p.routes, "17,50");
  assert.equal(p.granularity, "day");
  assert.equal(p.k_routes, c.k_routes);
  assert.equal(p.weather_to, c.weather_to);
  assert.equal(p.event_from, c.event_from);
  assert.equal(p.split_by_route, true);
  assert.equal(forecastParams(filters, c, false).k_weather, undefined);
  assert(!query(p).includes("stop_name"));
});
test("year keeps history and forecast distinct, forecast wins overlap without multiplication", () => {
  const history = {
    points: [
      { key: "2025-01", label: "Янв", value: 100 },
      { key: "2025-11", label: "Ноя", value: 150 },
    ],
  };
  const forecast = {
    points: [{ key: "2025-11", label: "Ноя", value: 0 }],
    network_events: [{ type: "FULL_CLOSURE", factor: 0.5 }],
  };
  assert.deepEqual(
    mergeYear(history, forecast).map((p) => [p.value, p.source]),
    [
      [100, "history"],
      [0, "forecast"],
    ],
  );
});
test("relative API requests preserve already adjusted values", async () => {
  const original = global.fetch;
  let called;
  global.fetch = async (url) => {
    called = url;
    return new Response(
      JSON.stringify({
        points: [{ key: "2025-12-15T08:00", label: "08", value: 80 }],
        network_events: [{ factor: 0.8 }],
      }),
      { headers: { "content-type": "application/json" } },
    );
  };
  try {
    const r = await request("/forecast", { routes: "17", k_weather: 0.8 });
    assert(called.startsWith("/api/forecast?"));
    assert.equal(r.points[0].value, 80);
  } finally {
    global.fetch = original;
  }
});
test("backend detail errors and wrong HTML responses are shown", async () => {
  const original = global.fetch;
  try {
    global.fetch = async () =>
      new Response(JSON.stringify({ detail: "Некорректный период" }), {
        status: 422,
        headers: { "content-type": "application/json" },
      });
    await assert.rejects(() => request("/forecast"), /Некорректный период/);
    global.fetch = async () =>
      new Response("<html/>", { headers: { "content-type": "text/html" } });
    await assert.rejects(() => request("/forecast"), /вместо JSON/);
  } finally {
    global.fetch = original;
  }
});
