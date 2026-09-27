// Цвет отражает оценочную долю посадок у соседних остановок, а не
// заполненность вагона на перегоне: данных о выходах пассажиров нет.
export function stopSegments(feature, stops) {
  if (!feature || !Array.isArray(stops)) return [];
  const route = String(feature.properties?.route);
  const direction = Number(feature.properties?.direction);
  const ordered = stops
    .filter((stop) => String(stop.route) === route && Number(stop.direction) === direction)
    .sort((a, b) => Number(a.sequence) - Number(b.sequence));
  const coordinates = feature.geometry?.coordinates || [];
  if (ordered.length < 2 || coordinates.length < 2) return [];
  const indices = ordered.map((stop) => coordinates.findIndex((point) =>
    Math.abs(point[0] - Number(stop.lon)) < 1e-5 &&
    Math.abs(point[1] - Number(stop.lat)) < 1e-5));
  if (indices.some((index) => index < 0)) return [];
  const weights = ordered.slice(0, -1).map((stop, index) =>
    (Number(stop.share) + Number(ordered[index + 1].share)) / 2);
  if (!weights.every(Number.isFinite) || !(Math.max(...weights) > 0)) return [];
  const ranked = [...weights].sort((a, b) => a - b);
  const quartile = (fraction) => ranked[Math.floor((ranked.length - 1) * fraction)];
  const [q1, q2, q3] = [quartile(0.25), quartile(0.5), quartile(0.75)];
  const band = (weight) => {
    if (ranked[0] === ranked.at(-1)) return "moderate";
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
