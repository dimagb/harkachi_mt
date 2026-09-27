export const LOAD_COLORS = {
  low: "#36c990",
  moderate: "#f4cf52",
  busy: "#ff913e",
  high: "#f04450",
  unknown: "#8aa5b5",
};

export function loadBand(ratio) {
  if (!Number.isFinite(ratio)) return "unknown";
  if (ratio < 0.25) return "low";
  if (ratio < 0.5) return "moderate";
  if (ratio < 0.75) return "busy";
  return "high";
}

// Сравниваем средний поток в выбранных часах с собственным пиковым часом
// маршрута за тот же период. Это относительная нагрузка, не заполненность
// вагона: вместимости и выпуска в данных API нет.
export function routeLoadByHour(byRoute, hourFrom, hourTo, scenarioFactor = 1) {
  const output = {};
  for (const [route, data] of Object.entries(byRoute || {})) {
    const points = Array.isArray(data) ? data : data?.points || [];
    const hourly = Array(24).fill(0);
    for (const point of points) {
      const match = String(point.key).match(/T(\d{2})(?::|$)/);
      if (!match) continue;
      const hour = Number(match[1]);
      if (hour < 0 || hour > 23) continue;
      const value = Number(point.value);
      if (Number.isFinite(value) && value > 0) hourly[hour] += value;
    }
    const peak = Math.max(...hourly);
    const selected = hourly.slice(hourFrom, hourTo + 1);
    const average = selected.reduce((sum, value) => sum + value, 0) /
      Math.max(selected.length, 1);
    const ratio = peak > 0 ? average * scenarioFactor / peak : NaN;
    output[String(route)] = { ratio, band: loadBand(ratio) };
  }
  return output;
}
