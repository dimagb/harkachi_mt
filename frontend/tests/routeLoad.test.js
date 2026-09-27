import test from "node:test";
import assert from "node:assert/strict";
import { routeLoadByHour } from "../src/routeLoad.js";

const hourly = (route, values) => ({
  [route]: values.map((value, hour) => ({
    key: `2025-12-15T${String(hour).padStart(2, "0")}`,
    value,
  })),
});

test("route colour follows its selected hours rather than network share", () => {
  const profile = hourly(17, [0, 20, 40, 60, 100]);
  assert.equal(routeLoadByHour(profile, 0, 0)[17].band, "low");
  assert.equal(routeLoadByHour(profile, 2, 2)[17].band, "moderate");
  assert.equal(routeLoadByHour(profile, 3, 3)[17].band, "busy");
  assert.equal(routeLoadByHour(profile, 4, 4)[17].band, "high");
});

test("a higher scenario forecast can move a route into a higher colour band", () => {
  const profile = hourly(12, [40, 100]);
  assert.equal(routeLoadByHour(profile, 0, 0, 1)[12].band, "moderate");
  assert.equal(routeLoadByHour(profile, 0, 0, 2)[12].band, "high");
  assert.deepEqual(routeLoadByHour({}, 0, 23), {});
});
