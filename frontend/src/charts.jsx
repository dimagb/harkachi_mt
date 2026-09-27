import React, { useId, useState } from "react";
import { format } from "./api";
const MONTHS = ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"];
// Подпись оси по ключу точки: полная подпись API («2025-12-15 00:00»)
// на 24 делениях накладывается, поэтому на оси — только час, день или месяц.
function axisLabel(key, horizon, label) {
  const k = String(key);
  if (horizon === "day" && /T\d{2}/.test(k)) return k.match(/T(\d{2})/)[1];
  if (/^\d{4}-\d{2}-\d{2}$/.test(k)) return `${k.slice(8)}.${k.slice(5, 7)}`;
  if (/^\d{4}-\d{2}$/.test(k)) return MONTHS[Number(k.slice(5)) - 1];
  return label;
}
export function LineChart({
  points = [],
  history = [],
  horizon = "day",
  dispatch = false,
  historyLabel = "Факт (история)",
}) {
  const id = useId().replaceAll(":", ""),
    [hover, setHover] = useState(null),
    all = [...points, ...history],
    max = Math.max(...all.map((p) => Number(p.value) || 0), 1) * 1.16;
  const keys = [...new Set(all.map((p) => p.key))].sort(),
    W = 900,
    H = dispatch ? 210 : 250,
    L = 55,
    R = 16,
    T = 25,
    B = 38,
    iw = W - L - R,
    ih = H - T - B;
  const x = (p) => horizon === "year"
      ? L + ((Number(String(p.key).slice(5, 7)) - 1) * iw) / 12
      : L + (keys.indexOf(p.key) * iw) / Math.max(keys.length - 1, 1),
    y = (p) => T + ih * (1 - Number(p.value) / max),
    path = (arr) =>
      arr.map((p, i) => `${i ? "L" : "M"}${x(p)},${y(p)}`).join(" ");
  if (!all.length)
    return <div className="empty">Нет данных за выбранный период</div>;
  const start = points[0];
  const lastHistory = history.at(-1);
  const adjacent = horizon === "year" && start && lastHistory &&
    new Date(`${lastHistory.key}-01T00:00:00Z`).getUTCMonth() + 1 ===
      new Date(`${start.key}-01T00:00:00Z`).getUTCMonth() &&
    x(start) > x(lastHistory);
  // Подписи месяцев стоят на их начале: красный ряд начинается строго на ноябре.
  const boundaryX = start && x(start);
  const historyPath = path(history);
  const forecastPath = points.length
    ? `${path(points)}${horizon === "year" ? ` L${W - R},${y(points.at(-1))}` : ""}`
    : "";
  const unit = max > 2e6 ? 1e6 : 1000;
  return (
    <div className="chart-wrap">
      <div className="legend">
        <span>
          <i className="blue" />
          {historyLabel}
        </span>
        <span>
          <i className="red" />
          Прогноз{dispatch ? " (с учётом коэффициентов)" : ""}
        </span>
      </div>
      <svg
        role="img"
        aria-label="График прогноза и истории пассажиропотока"
        viewBox={`0 0 ${W} ${H}`}
        onMouseLeave={() => setHover(null)}
      >
        <defs>
          <linearGradient id={`fill${id}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="#fd304f" stopOpacity=".22" />
            <stop offset="1" stopColor="#fd304f" stopOpacity="0" />
          </linearGradient>
          <filter id={`glow${id}`}>
            <feGaussianBlur stdDeviation="3" />
          </filter>
        </defs>
        {[0, 1, 2, 3, 4].map((i) => (
          <g key={i}>
            <line
              x1={L}
              x2={W - R}
              y1={T + (i * ih) / 4}
              y2={T + (i * ih) / 4}
              className="grid"
            />
            <text x={L - 10} y={T + (i * ih) / 4 + 4} textAnchor="end">
              {format((max * (1 - i / 4)) / unit)}
            </text>
          </g>
        ))}
        {keys.map((key, i) => (
          <g key={key}>
            <line
              x1={x({ key })}
              x2={x({ key })}
              y1={T}
              y2={H - B}
              className="grid"
            />
            {(keys.length <= 24 || i % Math.ceil(keys.length / 16) === 0) && (
              <text
                x={x({ key })}
                y={H - B + 20}
                textAnchor="middle"
              >
                {axisLabel(key, horizon, all.find((p) => p.key === key)?.label)}
              </text>
            )}
          </g>
        ))}
        {points.length > 0 && (
          <>
            <path
              d={`${forecastPath} L${horizon === "year" ? W - R : x(points.at(-1))},${H - B} L${boundaryX},${H - B} Z`}
              fill={`url(#fill${id})`}
            />
            <path
              d={forecastPath}
              stroke="#ef304c"
              strokeWidth="12"
              opacity=".15"
              fill="none"
              filter={`url(#glow${id})`}
            />
          </>
        )}
        {adjacent && (
          <path
            d={`M${x(lastHistory)},${y(lastHistory)} L${x(start)},${y(start)}`}
            fill="none"
            stroke="#8fa3ba"
            strokeWidth="2"
            strokeDasharray="4 4"
          />
        )}
        {[
          { arr: history, color: "#008dff", line: historyPath },
          { arr: points, color: "#ff3656", line: forecastPath },
        ].map(({ arr, color, line }) => (
          <g key={color}>
            <path
              d={line}
              fill="none"
              stroke={color}
              strokeWidth="2.6"
              strokeDasharray={
                dispatch && color === "#ff3656" ? "8 5" : undefined
              }
            />
            {arr.map((p) => (
              <circle
                key={p.key}
                cx={x(p)}
                cy={y(p)}
                r="4"
                fill={color}
                onMouseEnter={() => setHover(p)}
              >
                <title>
                  {p.label}: {format(p.value)} пассажиров
                </title>
              </circle>
            ))}
          </g>
        ))}
        {horizon === "year" && start && (
          <g>
            <line
              x1={boundaryX}
              x2={boundaryX}
              y1={T}
              y2={H - B}
              stroke="#8fa3ba"
              strokeDasharray="5 4"
            />
            <text x={Math.min(boundaryX + 7, W - 130)} y={T + 8}>
              Начало прогноза
            </text>
          </g>
        )}
        <text
          transform={`translate(13 ${H / 2}) rotate(-90)`}
          textAnchor="middle"
        >
          Пассажиры, {unit === 1e6 ? "млн" : "тыс."}
        </text>
        <text x={W / 2} y={H - 3} textAnchor="middle">
          {{ day: "Часы суток", month: "День месяца", year: "Месяц" }[horizon]}
        </text>
      </svg>
      {hover && (
        <div className="chart-tooltip">
          {hover.label} · {format(hover.value)} пассажиров
        </div>
      )}
    </div>
  );
}
export function Bars({ points = [], horizon }) {
  const id = useId().replaceAll(":", ""),
    max = Math.max(1, ...points.map((p) => p.value)) * 1.1;
  return points.length ? (
    <svg
      className="bars"
      role="img"
      aria-label="Исторический пассажиропоток"
      viewBox="0 0 480 180"
    >
      <defs>
        <linearGradient id={id} x2="0" y2="1">
          <stop stopColor="#64bbff" />
          <stop offset="1" stopColor="#1765a0" />
        </linearGradient>
      </defs>
      {[0, 1, 2, 3].map((i) => (
        <g key={i}>
          <line
            x1="44"
            x2="470"
            y1={12 + i * 43}
            y2={12 + i * 43}
            className="grid"
          />
          <text x="37" y={16 + i * 43} textAnchor="end">
            {format((max * (1 - i / 3)) / (horizon === "year" ? 1e6 : 1000))}
          </text>
        </g>
      ))}
      {points.map((p, i) => (
        <g key={p.key}>
          <rect
            x={48 + (i * 418) / points.length}
            y={141 - (p.value / max) * 129}
            width={Math.max(2, 418 / points.length - 5)}
            height={(p.value / max) * 129}
            fill={`url(#${id})`}
            rx="1"
          >
            <title>
              {p.label}: {format(p.value)}
            </title>
          </rect>
          {(points.length < 14 || i % 2 === 0) && (
            <text
              x={48 + ((i + 0.4) * 418) / points.length}
              y="160"
              textAnchor="middle"
            >
              {p.label}
            </text>
          )}
        </g>
      ))}
    </svg>
  ) : (
    <div className="empty">Нет исторических данных</div>
  );
}
export function Heatmap({ byRoute = {}, horizon }) {
  const rows = Object.entries(byRoute)
    .sort((a, b) => {
      const sum = (v) =>
        (Array.isArray(v) ? v : v?.points || []).reduce(
          (s, p) => s + Number(p.value || 0),
          0,
        );
      return sum(b[1]) - sum(a[1]);
    })
    .slice(0, 10)
    .map(([r, data]) => [r, Array.isArray(data) ? data : data?.points || []]);
  // Колонки — по ключу периода, а не по позиции: у маршрута 5 за год есть
  // только ноябрь и декабрь, и его клетки должны встать туда, а не в январь.
  const columns = [...new Set(rows.flatMap(([, ps]) => ps.map((p) => p.key)))].sort(),
    n = columns.length,
    max = Math.max(1, ...rows.flatMap(([, ps]) => ps.map((p) => p.value)));
  if (!n) return <div className="empty">Нет разбивки по маршрутам</div>;
  const colors = [
    "#006fc7",
    "#008cd3",
    "#1ca5bc",
    "#70b8a7",
    "#c7c375",
    "#ffd358",
    "#ff9843",
    "#ff314f",
  ];
  return (
    <div className="heatmap">
      <div
        className="heat-body"
        style={{ gridTemplateColumns: `28px repeat(${n}, minmax(0,1fr))` }}
      >
        {rows.map(([r, ps]) => (
          <React.Fragment key={r}>
            <span className="heat-route">{r}</span>
            {columns.map((key) => {
              const p = ps.find((x) => x.key === key);
              return p ? (
                <div
                  key={key}
                  title={`Маршрут ${r}, ${p.label || key}: ${format(p.value)}`}
                  style={{
                    background:
                      colors[Math.min(7, Math.floor((p.value / max) * 8))],
                  }}
                />
              ) : (
                <div key={key} title={`Маршрут ${r}: нет данных`} className="heat-empty" />
              );
            })}
          </React.Fragment>
        ))}
        <span />
        {columns.map((key, i) => (
          <span className="heat-label" key={key}>
            {n > 15 && i % 2 ? "" : axisLabel(key, horizon, key)}
          </span>
        ))}
      </div>
      <div className="heat-scale">
        <span>Низкая нагрузка</span>
        <i />
        <span>Высокая нагрузка</span>
      </div>
    </div>
  );
}
