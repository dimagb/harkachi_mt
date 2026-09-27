import test from "node:test";
import assert from "node:assert/strict";
import { stopSegments } from "../src/stopSegments.js";

test("colors consecutive supplied stop segments without inventing the reverse direction", () => {
  const geometry = { properties: { route: 11, direction: 0 },
    geometry: { coordinates: [[1, 1], [2, 2], [3, 3]] } };
  const stops = [
    { route: 11, direction: 0, sequence: 1, lon: 1, lat: 1, share: 0.01, name: "A" },
    { route: 11, direction: 0, sequence: 2, lon: 2, lat: 2, share: 0.02, name: "B" },
    { route: 11, direction: 0, sequence: 3, lon: 3, lat: 3, share: 0.08, name: "C" },
  ];
  const segments = stopSegments(geometry, stops);
  assert.equal(segments.length, 2);
  assert.equal(segments[0].properties.loadBand, "low");
  assert.equal(segments[1].properties.loadBand, "high");
  assert.deepEqual(segments[0].geometry.coordinates, [[1, 1], [2, 2]]);
  assert.deepEqual(stopSegments({ ...geometry, properties: { route: 11, direction: 1 } }, stops), []);
  assert.deepEqual(stopSegments(geometry, [{ ...stops[0], lon: 9 }, stops[1]]), []);
});
