// Сценарные оценочные посадки сравниваются с квартилями базового прогноза
// того же маршрута. Это не заполненность вагона: данных о выходах нет.
export function stopSegments(feature, stops, referenceStops = stops) {
  if (!feature || !Array.isArray(stops)) return [];
  const route = String(feature.properties?.route);
  const direction = Number(feature.properties?.direction);
  const ordered = stops
    .filter((stop) => String(stop.route) === route && Number(stop.direction) === direction)
    .sort((a, b) => Number(a.sequence) - Number(b.sequence));
  const referenceById = new Map(referenceStops.map((stop) => [stop.stop_id, stop]));
  const reference = ordered.map((stop) => referenceById.get(stop.stop_id));
  const coordinates = feature.geometry?.coordinates || [];
  if (ordered.length < 2 || coordinates.length < 2 || reference.some((stop) => !stop)) return [];
  const indices = ordered.map((stop) => coordinates.findIndex((point) =>
    Math.abs(point[0] - Number(stop.lon)) < 1e-5 &&
    Math.abs(point[1] - Number(stop.lat)) < 1e-5));
  if (indices.some((index) => index < 0)) return [];
  const segmentValues = (items) => items.slice(0, -1).map((stop, index) =>
    (Number(stop.value) + Number(items[index + 1].value)) / 2);
  const weights = segmentValues(ordered);
  const baseline = segmentValues(reference);
  if (!weights.every(Number.isFinite) || !baseline.every(Number.isFinite) ||
    !(Math.max(...baseline) > 0)) return [];
  const ranked = [...baseline].sort((a, b) => a - b);
  const quartile = (fraction) => ranked[Math.floor((ranked.length - 1) * fraction)];
  const [q1, q2, q3] = [quartile(0.25), quartile(0.5), quartile(0.75)];
  const band = (weight) => {
    if (ranked[0] === ranked.at(-1))
      return weight < ranked[0] ? "low" : weight > ranked[0] ? "high" : "moderate";
    if (weight <= q1) return "low";
    if (weight <= q2) return "moderate";
    if (weight <= q3) return "busy";
    return "high";
  };
  return weights.flatMap((weight, index) => {
    const from = indices[index], to = indices[index + 1];
    if (to <= from || !Number.isFinite(weight)) return [];
    return [{
      type: "Feature",
      geometry: { type: "LineString", coordinates: coordinates.slice(from, to + 1) },
      properties: {
        route: Number(route), direction,
        loadBand: band(weight),
        fromStop: ordered[index].name,
        toStop: ordered[index + 1].name,
      },
    }];
  });
}
