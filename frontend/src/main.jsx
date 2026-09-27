import React, { useEffect, useState, useRef } from "react";
import { createRoot } from "react-dom/client";
import { createPortal } from "react-dom";
import {
  BrowserRouter,
  Routes,
  Route,
  useNavigate,
  useLocation,
  Navigate,
} from "react-router-dom";
import {
  UserRound,
  LockKeyhole,
  Eye,
  EyeOff,
  ArrowRight,
  TramFront,
  CloudRain,
  UsersRound,
  Sigma,
  CalendarDays,
  Clock3,
  Download,
  Info,
  TriangleAlert,
  Bell,
  ChevronDown,
  ArrowLeftRight,
  TrendingUp,
  SlidersHorizontal,
  Star,
  Database,
  CheckCircle2,
  X,
  LogOut,
} from "lucide-react";
import {
  request,
  query,
  period,
  forecastParams,
  asList,
  format,
  mergeByRoute,
} from "./api";
import { demoData, demoPreview } from "./demo";
import { LineChart, Bars, Heatmap } from "./charts";
import TramMap from "./Map";
import "./styles.css";

const demo =
  new URLSearchParams(location.search).get("demo") === "1" ||
  sessionStorage.getItem("tram-demo") === "1";
if (demo) sessionStorage.setItem("tram-demo", "1");
const get = (path, p = {}, signal) =>
  demo ? Promise.resolve(demoData(path, p)) : request(path, p, signal);
function useResource(path, params = {}, revision = 0) {
  const [state, set] = useState({ data: null, loading: true, error: "" });
  const key = query(params);
  useEffect(() => {
    const controller = new AbortController();
    set((s) => ({ ...s, loading: true, error: "" }));
    get(path, params, controller.signal)
      .then((data) => {
        if (!controller.signal.aborted)
          set({ data, loading: false, error: "" });
      })
      .catch((e) => {
        if (e.name !== "AbortError" && !controller.signal.aborted)
          set({ data: null, loading: false, error: e.message });
      });
    return () => controller.abort();
  }, [path, key, revision]);
  return state;
}
function useScenario(body, revision = 0, enabled = true) {
  const [state, set] = useState({ data: null, loading: true, error: "" });
  const key = JSON.stringify(body);
  useEffect(() => {
    if (!enabled) {
      set({ data: null, loading: false, error: "" });
      return;
    }
    const controller = new AbortController();
    set({ data: null, loading: true, error: "" });
    (demo
      ? Promise.resolve().then(() => demoPreview(body))
      : request("/forecast/preview", {}, controller.signal, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: key,
        }))
      .then((data) => {
        if (!controller.signal.aborted) set({ data, loading: false, error: "" });
      })
      .catch((e) => {
        if (!controller.signal.aborted && e.name !== "AbortError")
          set({ data: null, loading: false, error: e.message });
      });
    return () => controller.abort();
  }, [key, revision, enabled]);
  return state;
}
function useDebounce(value) {
  const [v, set] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => set(value), 180);
    return () => clearTimeout(t);
  }, [JSON.stringify(value)]);
  return v;
}
const Icon = ({ as: Component, ...props }) => (
  <Component size={18} strokeWidth={1.6} {...props} />
);
function Logo() {
  return (
    <div className="brand" aria-label="Московский транспорт">
      <div className="brand-image" />
    </div>
  );
}
function InfoTip({ text }) {
  const [position, setPosition] = useState(null);
  const id = React.useId();
  const show = (event) => {
    const r = event.currentTarget.getBoundingClientRect();
    setPosition({left: Math.max(8, Math.min(r.left - 12, window.innerWidth - 288)), top: r.bottom + 9});
  };
  return <><button type="button" className="info" aria-label={text} aria-describedby={position ? id : undefined} onMouseEnter={show} onMouseLeave={() => setPosition(null)} onFocus={show} onBlur={() => setPosition(null)} onClick={e => position ? setPosition(null) : show(e)}><Info size={14}/></button>{position && createPortal(<div id={id} role="tooltip" className="info-tooltip" style={position}>{text}</div>, document.body)}</>;
}
function Panel({ title, children, className = "", actions, info }) {
  return (
    <section className={`panel ${className}`}>
      <div className="panel-heading">
        <h2>
          {title}
          {info && (
            <InfoTip text={info} />
          )}
        </h2>
        {actions}
      </div>
      {children}
    </section>
  );
}
function Tabs({ value, onChange }) {
  return (
    <div className="tabs horizon" role="tablist" aria-label="Горизонт прогноза">
      {[
        ["day", "День"],
        ["month", "Месяц"],
        ["year", "Год"],
      ].map(([v, l]) => (
        <button
          key={v}
          role="tab"
          aria-selected={value === v}
          className={value === v ? "active" : ""}
          onClick={() => onChange(v)}
        >
          {l}
        </button>
      ))}
    </div>
  );
}
function ResourceError({ resource }) {
  return resource.loading ? (
    <div className="resource-message">Загрузка данных…</div>
  ) : resource.error ? (
    <div className="resource-message error" role="alert">
      {resource.error}
    </div>
  ) : null;
}
function Login() {
  const nav = useNavigate(),
    [role, setRole] = useState("dispatcher"),
    [show, setShow] = useState(false);
  return (
    <div className="login-page">
      <header className="login-header">
        <Logo />
        <span>Единый диспетчерский центр · Авторизация</span>
      </header>
      <main className="login-stage">
        <form
          className="login-card"
          onSubmit={(e) => {
            e.preventDefault();
            sessionStorage.setItem("tram-role", role);
            nav("/dashboard");
          }}
        >
          <div className="login-intro">
            <div className="tram-symbol">
              <TramFront size={56} />
            </div>
            <div>
              <h1>Вход в систему</h1>
              <p>Трамвайная система Москвы</p>
            </div>
          </div>
          <label>
            Ваша роль в системе
            <div className="input-icon">
              <UserRound />
              <select
                aria-label="Ваша роль в системе"
                value={role}
                onChange={(e) => setRole(e.target.value)}
              >
                <option value="dispatcher">
                  Диспетчер трамвайного движения
                </option>
                <option value="admin">Администратор</option>
              </select>
              <ChevronDown className="select-arrow" />
            </div>
          </label>
          <label>
            Логин
            <div className="input-icon">
              <UserRound />
              <input
                autoComplete="username"
                placeholder="Введите логин"
                aria-label="Логин"
              />
            </div>
          </label>
          <label>
            Пароль
            <div className="input-icon">
              <LockKeyhole />
              <input
                type={show ? "text" : "password"}
                autoComplete="current-password"
                placeholder="Введите пароль"
                aria-label="Пароль"
              />
              <button
                type="button"
                className="password-eye"
                onClick={() => setShow(!show)}
                aria-label={show ? "Скрыть пароль" : "Показать пароль"}
              >
                {show ? <EyeOff /> : <Eye />}
              </button>
            </div>
          </label>
          <button className="primary login-submit" type="submit">
            Войти в систему <ArrowRight size={23} />
          </button>
        </form>
      </main>
    </div>
  );
}
function Header({ analytics, health, onAdmin }) {
  const nav = useNavigate(),
    [menu, setMenu] = useState(false),
    [now, setNow] = useState(new Date());
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);
  return (
    <header className={`app-header ${analytics ? "analytics-header" : ""}`}>
      <Logo />
      <div className="page-name">
        <h1>{analytics ? "Аналитика трамваев" : "Диспетчерская трамваев"}</h1>
        <p>
          {analytics
            ? "Глубокий анализ, факторы и качество прогноза"
            : "Москва"}
        </p>
      </div>
      <div className="header-time">
          <small>
            {now.toLocaleDateString("ru-RU", {
              day: "numeric",
              month: "long",
              year: "numeric",
            })}
          </small>
          <strong>{now.toLocaleTimeString("ru-RU")}</strong>
        </div>
      <nav className="tabs page-tabs">
        <button
          className={!analytics ? "active" : ""}
          onClick={() => nav("/dashboard")}
        >
          Управление движением
        </button>
        <button
          className={analytics ? "active" : ""}
          onClick={() => nav("/analytics")}
        >
          Аналитика
        </button>
      </nav>
      {!analytics && (
        <div className="weather">
          <CloudRain />
          <span>
            {demo ? "+12°C" : "—"}
            <small>{demo ? "Небольшой дождь" : "Нет погодных данных"}</small>
          </span>
        </div>
      )}
      <div className={`system-status ${health.error ? "offline" : ""}`}>
        <i />
        {demo
          ? "Демопросмотр"
          : health.loading
            ? "Подключение…"
            : health.error
              ? "API недоступен"
              : "Система работает"}
      </div>
      <div className="user-menu">
        <button onClick={() => setMenu(!menu)} aria-expanded={menu}>
          <UserRound size={18} />
          <span>
            {sessionStorage.getItem("tram-role") === "admin"
              ? "Администратор"
              : "Диспетчер"}
          </span>
          <ChevronDown size={14} />
        </button>
        {menu && (
          <div className="menu-popover">
            {sessionStorage.getItem("tram-role") === "admin" && (
              <button
                onClick={() => {
                  onAdmin();
                  setMenu(false);
                }}
              >
                Изменения сети
              </button>
            )}
            <button
              onClick={() => {
                sessionStorage.removeItem("tram-role");
                nav("/login");
              }}
            >
              <LogOut size={15} />
              Выйти
            </button>
          </div>
        )}
      </div>
    </header>
  );
}
function RoutePicker({ routes, selected, onChange }) {
  return (
    <details className="route-picker">
      <summary>
        <TramFront size={17} />
        <span>
          {selected.length ? "Маршрут " + selected.join(", ") : "Все маршруты"}
        </span>
        <ChevronDown size={14} />
      </summary>
      <div className="route-options">
        <label>
          <input
            type="checkbox"
            checked={!selected.length}
            onChange={() => onChange([])}
          />
          Все маршруты
        </label>
        {routes.map((r) => (
          <label key={r.route} title={r.note || ""}>
            <input
              type="checkbox"
              checked={selected.includes(String(r.route))}
              onChange={(e) =>
                onChange(
                  e.target.checked
                    ? [...selected, String(r.route)]
                    : selected.filter((x) => x !== String(r.route)),
                )
              }
            />
            Маршрут {r.route}
            {r.excluded ? " · исключён" : ""}
          </label>
        ))}
      </div>
    </details>
  );
}
function DateFilter({ filters, setFilters }) {
  return (
    <details className="date-picker">
      <summary>
        <CalendarDays size={17} />
        <span>
          {filters.date_from.split("-").reverse().join(".")}
          {filters.horizon !== "day"
            ? " — " + filters.date_to.split("-").reverse().join(".")
            : ""}
        </span>
        <ChevronDown size={13} />
      </summary>
      <div className="date-options">
        <label>
          С
          <input
            type="date"
            aria-label="Начало периода"
            value={filters.date_from}
            max={filters.date_to}
            onChange={(e) =>
              e.target.value &&
              setFilters((f) => ({ ...f, date_from: e.target.value }))
            }
          />
        </label>
        <label>
          По
          <input
            type="date"
            aria-label="Конец периода"
            min={filters.date_from}
            value={filters.date_to}
            onChange={(e) =>
              e.target.value &&
              setFilters((f) => ({ ...f, date_to: e.target.value }))
            }
          />
        </label>
      </div>
    </details>
  );
}
function HourFilter({ filters, setFilters }) {
  const hours = Array.from({length:24}, (_,i) => i);
  return <details className="date-picker hour-picker"><summary><Clock3 size={17}/><span>{String(filters.hour_from).padStart(2,"0")}:00 — {String(filters.hour_to).padStart(2,"0")}:59</span><ChevronDown size={13}/></summary><div className="date-options"><label>С часа<select aria-label="С часа" value={filters.hour_from} onChange={e => {const hour=Number(e.target.value); if(Number.isInteger(hour) && hour>=0 && hour<=23) setFilters(f=>({...f,hour_from:hour,hour_to:Math.max(hour,f.hour_to)}));}}>{hours.map(h=><option key={h} value={h}>{String(h).padStart(2,"0")}:00</option>)}</select></label><label>По час<select aria-label="По час" value={filters.hour_to} onChange={e=>{const hour=Number(e.target.value); if(Number.isInteger(hour) && hour>=0 && hour<=23) setFilters(f=>({...f,hour_to:hour,hour_from:Math.min(hour,f.hour_from)}));}}>{hours.map(h=><option key={h} value={h}>{String(h).padStart(2,"0")}:59</option>)}</select></label></div></details>;
}
function Export({ params, notify }) {
  return (
    <a
      className="primary export"
      href={`/api/export?${query({ ...params, format: "xlsx" })}`}
      download
      onClick={
        demo
          ? (e) => {
              e.preventDefault();
              notify(
                "Выгрузка XLSX будет доступна после подключения бекенда. Демоданные не выдаются за реальные.",
              );
            }
          : undefined
      }
    >
      <Download size={20} />
      Скачать XLSX
    </a>
  );
}
function DataStatus({ meta }) {
  const m = meta.data || {};
  return (
    <Panel title="Состояние данных" className="data-status">
      <ResourceError resource={meta} />
      {[
        [CalendarDays, "Данные по:", m.history_to || m.history?.date_to],
        [Clock3, "Обновлено:", m.updated_at],
        [CheckCircle2, "Покрытие:", m.coverage],
        [Database, "Версия модели:", m.model_version],
        [Database, "Агрегация:", m.aggregation],
      ].map(([I, l, v]) => (
        <div key={l}>
          <Icon as={I} />
          <span>{l}</span>
          <b className={l === "Покрытие:" ? "cyan" : ""}>
            {typeof v === "string" || typeof v === "number" ? v : "—"}
          </b>
        </div>
      ))}
      <small>
        Прогноз: {m.forecast_from || m.forecast?.date_from || "—"} —{" "}
        {m.forecast_to || m.forecast?.date_to || "—"}
      </small>
    </Panel>
  );
}
function Factors({ resource, onScope, horizon }) {
  const factors = asList(resource.data, "factors").filter(
    (f) => f.name && !/ЗАПОЛНИТЬ/.test(f.name),
  );
  return (
    <>
      <Panel
        title="Точность прогноза"
        info="Показывает, насколько прогноз близок к фактическому пассажиропотоку. Без данных для сравнения точность не рассчитывается."
        className="accuracy"
      >
        <div className="accuracy-body">
          <div className="accuracy-ring">
            <div />
          </div>
          <div>
            <strong>
              {demo ? { day: 93, month: 91, year: 89 }[horizon] + "%" : "—"}
            </strong>
            <p>Точность прогноза</p>
          </div>
        </div>
      </Panel>
      <Panel
        title="Внешние факторы и их эффект"
        className="factors"
        info="Влияние погоды, календаря и городских событий на ожидаемый пассажиропоток."
      >
        <ResourceError resource={resource} />
        {(factors.length
          ? factors
          : [
              { name: "Погода" },
              { name: "Календарь / сезонность" },
              { name: "Городские события" },
            ]
        ).map((f, i) => (
          <div className="factor" key={f.name}>
            <Icon
              as={[CloudRain, CalendarDays, Star][i % 3]}
              className={i === 1 ? "red-text" : i === 2 ? "yellow-text" : ""}
            />
            <span>{f.name}</span>
            <b className={Number(f.effect) < 0 ? "red-text" : "cyan"}>
              {f.effect == null
                ? "—"
                : `${Number(f.effect) > 0 ? "+" : ""}${f.effect}%`}
            </b>
          </div>
        ))}
        <button className="manual-factors" onClick={onScope}>
          <SlidersHorizontal size={19} />
          Ручные коэффициенты <small>индивидуально</small>
        </button>
      </Panel>
    </>
  );
}
function HistoricalBars({ filters }) {
  const [state, setState] = useState({ points: [], loading: true, error: "" });
  useEffect(() => {
    const c = new AbortController();
    setState({ points: [], loading: true, error: "" });
    const common = {
      routes: filters.routes.join(","),
      source: "history",
      hour_from: filters.hour_from,
      hour_to: filters.hour_to,
    };
    if (filters.horizon === "year") {
      if (demo) {
        setState({
          loading: false,
          error: "",
          points: [108, 132, 152, 158, 176].map((v, i) => ({
            key: String(2021 + i),
            label: String(2021 + i),
            value: v * 1e6,
          })),
        });
        return () => c.abort();
      }
      Promise.all(
        [2021, 2022, 2023, 2024, 2025].map(async (year) => {
          const r = await get(
            "/forecast",
            {
              ...common,
              horizon: "year",
              date_from: `${year}-01-01`,
              date_to: `${year}-12-31`,
            },
            c.signal,
          );
          return {
            key: String(year),
            label: String(year),
            value: r.summary?.total || 0,
          };
        }),
      )
        .then((points) => {
          if (!c.signal.aborted)
            setState({ points, loading: false, error: "" });
        })
        .catch((e) => {
          if (!c.signal.aborted)
            setState({ points: [], loading: false, error: e.message });
        });
    } else {
      get(
        "/forecast",
        {
          ...common,
          horizon: filters.horizon === "month" ? "year" : "day",
          ...(filters.horizon === "month"
            ? period("year", filters.date_from)
            : { date_from: filters.date_from, date_to: filters.date_to }),
        },
        c.signal,
      )
        .then((r) => {
          if (!c.signal.aborted)
            setState({ points: r.points || [], loading: false, error: "" });
        })
        .catch((e) => {
          if (!c.signal.aborted)
            setState({ points: [], loading: false, error: e.message });
        });
    }
    return () => c.abort();
  }, [JSON.stringify(filters)]);
  return (
    <>
      <ResourceError resource={state} />
      <Bars
        points={state.points}
        horizon={filters.horizon === "month" ? "year" : filters.horizon}
      />
    </>
  );
}
function Ranking({ resource, onRoute, horizon }) {
  return (
    <Panel
      title={`Рейтинг маршрутов по пассажиропотоку${horizon === "day" ? " (день)" : horizon === "year" ? " (год)" : ""}`}
      info="Маршруты по объёму пассажиропотока за выбранный период. Доля показывает вклад маршрута в общий поток."
      className="ranking"
    >
      <ResourceError resource={resource} />
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>#</th>
              <th>Маршрут</th>
              <th>Доля</th>
              <th>Всего пассажиров</th>
              <th>Изм. к прошл. периоду</th>
            </tr>
          </thead>
          <tbody>
            {asList(resource.data, "routes").map((r, i) => (
              <tr key={r.route} onClick={() => onRoute(String(r.route))}>
                <td>{i + 1}</td>
                <td>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      onRoute(String(r.route));
                    }}
                  >
                    {r.route}
                  </button>
                </td>
                <td>{format(r.share * 100, 1)}%</td>
                <td>{format(r.total)}</td>
                <td className="cyan">
                  {r.change_pct == null ? "—" : format(r.change_pct, 1) + "%"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!resource.loading &&
        !resource.error &&
        !asList(resource.data, "routes").length && (
          <div className="empty">Нет маршрутов за выбранный период</div>
        )}
    </Panel>
  );
}
function Coefficients({
  coeff,
  setCoeff,
  factors,
  preview,
  date,
}) {
  const month = Number(date.slice(5, 7));
  const season = (factors?.seasons?.warm || [4, 5, 6, 7, 8, 9]).includes(month)
    ? "warm" : "cold";
  const options = factors?.options || [];
  const scenarios = (factor) => options.filter((option) =>
    option.factor_code === factor &&
    (factor === "WEATHER" ? option.confirmed === true :
      option.confirmed === true || option.status === "manual_scenario" || option.source === "manual_scenario") &&
    (option.season === season || option.season === "all"));
  const baseline = preview.data?.base?.summary?.total;
  const total = preview.data?.scenario?.summary?.total;
  const update = (key, value) => setCoeff((current) => ({ ...current, [key]: value }));
  return (
    <Panel title="Корректирующие коэффициенты" className="coefficients">
      {[["weather", "Погода", "WEATHER", "NORMAL"],
        ["event", "Событие", "EVENT", "NONE"]].map(([key, label, factor, neutral]) => {
        const available = scenarios(factor);
        return <div className="scenario-factor" key={key}>
          <div className="scenario-factor-heading"><strong>{label}</strong></div>
            <select aria-label={`${label}: сценарий`} value={available.some((item) => item.option_code === coeff[`${key}Code`]) ? coeff[`${key}Code`] : neutral}
              onChange={(e) => update(`${key}Code`, e.target.value)} disabled={!available.length}>
              <option value={neutral}>{key === "weather" ? "Обычная погода" : "Нет события"}</option>
              {available.map((item) => <option key={item.option_code} value={item.option_code}>{item.label}{item.confirmed ? "" : " · ручная гипотеза"}</option>)}
            </select>
            {!available.length && <small className="scenario-note">{key === "weather" && season === "cold"
              ? "Для холодного сезона значимого эффекта в данных не обнаружено"
              : "Сценариев для выбранной даты нет"}</small>}
            {key === "event" && available.some((item) => item.option_code === coeff.eventCode && !item.confirmed) &&
              <small className="scenario-note">Ручная гипотеза, не измеренный эффект</small>}
        </div>;
      })}
      {[["seasonPct", "Сезонная поправка"], ["manualPct", "Ручная поправка"]].map(([key, label]) =>
        <div className="scenario-factor" key={key}>
          <div className="scenario-factor-heading"><strong>{label}</strong><output>{coeff[key] > 0 ? "+" : ""}{coeff[key]}%</output></div>
          <input type="range" min="-20" max="20" step="1" aria-label={label}
            value={coeff[key]} onChange={(e) => update(key, Number(e.target.value))} />
        </div>)}
      <div className="scenario-summary">
        <span>Базовый прогноз <b>{format(baseline)}</b></span>
        <span>Сценарный прогноз <b>{format(total)}</b></span>
        <span>Изменение <b className="cyan">{preview.data?.difference_pct == null ? "—" :
          `${preview.data.difference_pct > 0 ? "+" : ""}${format(preview.data.difference_pct, 1)}%`}</b></span>
      </div>
      {preview.error && <small className="scenario-error">{preview.error}</small>}
    </Panel>
  );
}
function Events({ events = [], onRoute }) {
  return (
    <Panel
      title="Лента событий"
      className="events"
      actions={<small>Все события</small>}
    >
      {events.length ? (
        events.map((e, i) => (
          <button
            className="event-item"
            key={e.id || i}
            onClick={() => onRoute(String(e.route))}
          >
            <span className="event-icon">
              <TriangleAlert size={17} />
            </span>
            <span>
              Маршрут {e.route}
              <strong>{e.title}</strong>
              <small>
                {e.valid_from} — {e.valid_to || "до отмены"}
              </small>
            </span>
            <ArrowRight size={13} />
          </button>
        ))
      ) : (
        <div className="empty">Активных событий сети нет</div>
      )}
    </Panel>
  );
}
function Recommendations({ ranking, forecast, onAction }) {
  const rs = ranking.slice(0, 2);
  return (
    <Panel
      title="Рекомендации ИИ"
      className="recommendations"
      actions={<span className="count">{rs.length}</span>}
    >
      {rs.length ? (
        rs.map((r, i) => (
          <div className={`recommendation rec-${i}`} key={r.route}>
            <div>
              <TriangleAlert size={17} />
              <span>Маршрут {r.route}</span>
              <small>{i === 0 ? "Высокий" : "Средний"} приоритет</small>
            </div>
            <h3>
              {i === 0
                ? "Добавить резервный вагон"
                : "Уточнить интервал движения"}
            </h3>
            <p>
              Прогноз: {format(r.total)} пассажиров за период.
              <br />
              Доля потока: {format(r.share * 100, 1)}%.
            </p>
            <span className="cyan">Рассмотрите дополнительный выпуск</span>
            <div className="recommendation-actions">
              <button
                className="primary"
                onClick={() =>
                  onAction(
                    `Рекомендация по маршруту ${r.route} выбрана. Контракт не содержит API управления вагонами; команда диспетчерской не отправлена.`,
                  )
                }
              >
                Рассмотреть
              </button>
              <button
                onClick={() =>
                  onAction(
                    `Маршрут ${r.route}: рекомендация отмечена как просмотренная в этой сессии.`,
                  )
                }
              >
                Отметить как обработано
              </button>
            </div>
          </div>
        ))
      ) : (
        <div className="empty">Недостаточно данных для рекомендаций</div>
      )}
    </Panel>
  );
}
function NetworkWarnings({ events = [] }) {
  return events.length ? (
    <div className="network-warnings">
      {events.map((e) => (
        <div key={e.id}>
          <TriangleAlert size={15} />
          <span>
            Маршрут {e.route}:{" "}
            {e.type === "FULL_CLOSURE" ? "временно не работает" : e.title} ·{" "}
            {e.valid_from} — {e.valid_to || "до отмены"}{" "}
            {/^https?:\/\//.test(e.source_url || "") && (
              <a href={e.source_url} target="_blank" rel="noreferrer">
                Источник
              </a>
            )}
          </span>
        </div>
      ))}
    </div>
  ) : null;
}
function Modal({ title, onClose, children }) {
  const dialog = useRef(null);
  useEffect(() => {
    const key = (e) => {
      if (e.key === "Escape") onClose();
      if (e.key === "Tab") {
        const controls = [...dialog.current.querySelectorAll('button, a[href], input, select, textarea, summary, [tabindex="0"]')].filter(el => !el.disabled && el.getClientRects().length);
        const first = controls[0], last = controls.at(-1);
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last?.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first?.focus(); }
      }
    };
    document.addEventListener("keydown", key);
    return () => document.removeEventListener("keydown", key);
  }, [onClose]);
  return (
    <div
      className="modal-backdrop"
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
        <section
          ref={dialog}
          role="dialog"
        aria-modal="true"
        aria-label={title}
        className="modal panel"
      >
        <div className="panel-heading">
          <h2>{title}</h2>
          <button autoFocus onClick={onClose} aria-label="Закрыть">
            <X />
          </button>
        </div>
        {children}
      </section>
    </div>
  );
}
function StopPanel({ route, params, onClose }) {
  const res = useResource("/forecast/stops", {
    ...params,
    routes: undefined,
    route,
  });
  return (
    <Modal title={`Маршрут ${route} · остановки`} onClose={onClose}>
      <ResourceError resource={res} />
      {res.data?.note && (
        <p className="stop-note">
          <Info size={17} />
          {res.data.note}
        </p>
      )}
      {res.data?.estimated && <span className="badge">Оценочная разбивка</span>}
      <div className="stop-list">
        {asList(res.data, "stops").map((s) => (
          <div key={s.stop_id}>
            <span>
              {s.is_hub ? "◉" : "○"} {s.name}
            </span>
            <span>
              {format(s.value)} · {format(s.share * 100, 1)}%
            </span>
          </div>
        ))}
      </div>
      {!res.loading && !res.error && !asList(res.data, "stops").length && (
        <div className="empty">
          Для этого маршрута остановки не предоставлены
        </div>
      )}
    </Modal>
  );
}
function Admin({ onClose, onSaved }) {
  const [form, set] = useState({
      route: 17,
      type: "FULL_CLOSURE",
      valid_from: "2025-12-15",
      valid_to: "",
      hour_from: "",
      hour_to: "",
      factor: "",
      title: "",
      source_url: "",
    }),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [rev, bump] = useState(0),
    events = useResource("/network-events", {}, rev);
  const change = (e) => set((f) => ({ ...f, [e.target.name]: e.target.value }));
  async function submit(e) {
    e.preventDefault();
    if (demo) {
      setError("Для создания событий подключите бекенд.");
      return;
    }
    setBusy(true);
    try {
      await request("/network-events", {}, undefined, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...form,
          route: Number(form.route),
          valid_to: form.valid_to || null,
          hour_from: form.hour_from === "" ? null : Number(form.hour_from),
          hour_to: form.hour_to === "" ? null : Number(form.hour_to),
          factor: form.type === "FULL_CLOSURE" ? null : Number(form.factor),
        }),
      });
      bump((x) => x + 1);
      onSaved();
      setError("");
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal title="Изменения сети" onClose={onClose}>
      <form className="admin-form" onSubmit={submit}>
        <label>
          Маршрут
          <input
            name="route"
            type="number"
            min="1"
            required
            value={form.route}
            onChange={change}
          />
        </label>
        <label>
          Тип
          <select name="type" value={form.type} onChange={change}>
            <option value="FULL_CLOSURE">Полное закрытие</option>
            <option value="SHORTENING">Укорочение</option>
            <option value="MANUAL_MULTIPLIER">Ручной множитель</option>
          </select>
        </label>
        <label>
          С
          <input
            type="date"
            name="valid_from"
            required
            value={form.valid_from}
            onChange={change}
          />
        </label>
        <label>
          До (пусто — до отмены)
          <input
            type="date"
            name="valid_to"
            min={form.valid_from}
            value={form.valid_to}
            onChange={change}
          />
        </label>
        <label>
          С часа
          <input
            type="number"
            name="hour_from"
            min="0"
            max="23"
            value={form.hour_from}
            onChange={change}
          />
        </label>
        <label>
          По час
          <input
            type="number"
            name="hour_to"
            min={form.hour_from || 0}
            max="23"
            value={form.hour_to}
            onChange={change}
          />
        </label>
        {form.type !== "FULL_CLOSURE" && (
          <label>
            Коэффициент
            <input
              type="number"
              name="factor"
              min="0.1"
              max="5"
              step="0.01"
              required
              value={form.factor}
              onChange={change}
            />
          </label>
        )}
        <label>
          Название
          <input name="title" required value={form.title} onChange={change} />
        </label>
        <label>
          Источник
          <input
            type="url"
            name="source_url"
            required
            value={form.source_url}
            onChange={change}
          />
        </label>
        <button disabled={busy} className="primary">
          {busy ? "Сохранение…" : "Добавить"}
        </button>
      </form>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      <ResourceError resource={events} />
      {asList(events.data, "network_events").map((e) => (
        <div className="admin-event" key={e.id}>
          {e.route} · {e.title}
          <button
            onClick={async () => {
              try {
                await request(`/network-events/${e.id}`, {}, undefined, {
                  method: "DELETE",
                });
                bump((x) => x + 1);
                onSaved();
              } catch (e) {
                setError(e.message);
              }
            }}
          >
            Снять
          </button>
        </div>
      ))}
    </Modal>
  );
}
function Workspace() {
  const location = useLocation(),
    analytics = location.pathname === "/analytics";
  const [filters, setFilters] = useState({
      horizon: "day",
      routes: [],
      ...period("day"),
      hour_from: 0,
      hour_to: 23,
    }),
    [coeff, setCoeff] = useState({
      weatherCode: "NORMAL", eventCode: "NONE",
      seasonPct: 0, manualPct: 0,
    }),
    [stopRoute, setStopRoute] = useState(null),
    [admin, setAdmin] = useState(false),
    [scopeOpen, setScopeOpen] = useState(false),
    [toast, setToast] = useState(""),
    [revision, setRevision] = useState(0),
    [selectedRoute, setSelectedRoute] = useState("17"),
    [statusFilter, setStatusFilter] = useState("all");
  const deferred = useDebounce(coeff),
    params = forecastParams(filters, {}, false),
    baseParams = forecastParams(filters, deferred, false),
    forecast = useResource("/forecast", params, revision),
    history = useResource(
      "/forecast",
      { ...baseParams, source: "history" },
      revision,
    ),
    compare = useResource("/forecast/compare", baseParams, revision),
    ranking = useResource("/forecast/routes", params, revision),
    routes = useResource("/routes"),
    geometry = useResource("/geometry"),
    stops = useResource(
      "/forecast/stops",
      { ...params, routes: undefined, route: selectedRoute },
      revision,
    ),
    meta = useResource("/meta"),
    health = useResource("/health"),
    factors = useResource("/factors"),
    scope = useResource("/scope");
  const warmMonths = factors.data?.seasons?.warm || [4, 5, 6, 7, 8, 9];
  const selectedSeason = warmMonths.includes(Number(filters.date_from.slice(5, 7))) ? "warm" : "cold";
  const validCode = (factor, code, neutral) =>
    factors.data?.options?.some((item) => item.factor_code === factor &&
      item.option_code === code && (item.confirmed === true ||
        (factor === "EVENT" && (item.status === "manual_scenario" || item.source === "manual_scenario"))) &&
      (item.season === selectedSeason || item.season === "all")) ? code : neutral;
  const scenarioBody = {
    routes: filters.routes.length ? filters.routes.map(Number) : null,
    from: filters.date_from,
    to: filters.date_to,
    weather: validCode("WEATHER", deferred.weatherCode, "NORMAL"),
    event: validCode("EVENT", deferred.eventCode, "NONE"),
    season_adjustment_pct: deferred.seasonPct,
    manual_adjustment_pct: deferred.manualPct,
  };
  const preview = useScenario(scenarioBody, revision, !analytics);
  const previewForView = (() => {
    if (!preview.data || analytics || filters.horizon !== "day" ||
        (filters.hour_from === 0 && filters.hour_to === 23)) return preview;
    const restrict = (series) => {
      const points = (series.points || []).filter((point) => {
        const hour = Number(String(point.key).match(/T(\d{2})/)?.[1] ??
          String(point.label).match(/^\d{1,2}/)?.[0]);
        return Number.isFinite(hour) && hour >= filters.hour_from && hour <= filters.hour_to;
      });
      return { ...series, points, summary: {
        ...series.summary,
        total: points.reduce((sum, point) => sum + Number(point.value || 0), 0),
        peak: points.reduce((peak, point) => !peak || point.value > peak.value ? point : peak, null),
      } };
    };
    const base = restrict(preview.data.base);
    const scenario = restrict(preview.data.scenario);
    return { ...preview, data: { ...preview.data, base, scenario,
      difference_pct: base.summary.total ?
        (scenario.summary.total / base.summary.total - 1) * 100 : null } };
  })();
  useEffect(() => {
    const selector = "details.route-picker, details.date-picker, details.coefficient-dates";
    const closeAll = (except = null) => {
      document.querySelectorAll(selector).forEach((details) => {
        if (details !== except) details.open = false;
      });
    };
    const onToggle = (event) => {
      const details = event.target;
      if (details instanceof HTMLDetailsElement && details.matches(selector) && details.open) {
        closeAll(details);
      }
    };
    const onPointerDown = (event) => {
      if (!event.target.closest(selector)) closeAll();
    };
    const onClick = (event) => {
      const details = event.target.closest(selector);
      if (details && event.target.closest("summary")) closeAll(details);
    };
    const onKeyDown = (event) => {
      if (event.key === "Escape") closeAll();
    };
    document.addEventListener("toggle", onToggle, true);
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("click", onClick, true);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("toggle", onToggle, true);
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("click", onClick, true);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, []);
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(""), 7000);
    return () => clearTimeout(t);
  }, [toast]);
  const changeHorizon = (h) =>
    setFilters((f) => ({ ...f, horizon: h, ...period(h, f.date_from) }));
  const routeList = asList(routes.data, "routes"),
    rank = asList(ranking.data, "routes"),
    dispatchForecast = previewForView.data?.scenario || forecast.data,
    events = dispatchForecast?.network_events || [],
    series = (analytics ? forecast.data : dispatchForecast)?.points || [],
    historyPoints = history.data?.points || [],
    compHistory =
      compare.data?.history?.points ||
      compare.data?.actual?.points ||
      historyPoints;
  const openRoute = (r) => {
    setSelectedRoute(r);
    setStopRoute(r);
  };
  useEffect(() => {
    if (filters.routes.length) setSelectedRoute(filters.routes[0]);
  }, [filters.routes.join(",")]);
  function reset() {
    setFilters({
      horizon: "day",
      routes: [],
      ...period("day"),
      hour_from: 0,
      hour_to: 23,
    });
    setCoeff({
      weatherCode: "NORMAL", eventCode: "NONE",
      seasonPct: 0, manualPct: 0,
    });
  }
  return (
    <div className={`app-shell ${analytics ? "is-analytics" : "is-dispatch"}`}>
      <Header
        analytics={analytics}
        health={health}
        onAdmin={() => setAdmin(true)}
      />
      <main
        className={
          analytics
            ? `analytics-layout horizon-${filters.horizon}`
            : "dispatch-layout"
        }
      >
        <aside className="left-sidebar">
          {analytics ? (
            <>
              <Panel
                title="Параметры анализа"
                actions={
                  <button className="text-button" onClick={reset}>
                    Сбросить
                  </button>
                }
                className="filters"
              >
                <label>Горизонт</label>
                <Tabs value={filters.horizon} onChange={changeHorizon} />
                <label>Маршруты</label>
                <RoutePicker
                  routes={routeList}
                  selected={filters.routes}
                  onChange={(routes) => setFilters((f) => ({ ...f, routes }))}
                />
                <label>{filters.horizon === "day" ? "Дата" : "Период"}</label>
                <DateFilter filters={filters} setFilters={setFilters} />
                <label>Время суток</label>
                <HourFilter filters={filters} setFilters={setFilters} />
                <Export params={params} notify={setToast} />
              </Panel>
              <DataStatus meta={meta} />
              <div
                className="tram-art"
                role="img"
                aria-label="Трамвай на фоне Москвы"
              />
            </>
          ) : (
            <>
              <Panel
                title="Ситуация"
                actions={
                  <button className="text-button" onClick={reset}>
                    Сбросить фильтры
                  </button>
                }
                className="filters"
              >
                <label>Маршрут</label>
                <RoutePicker
                  routes={routeList}
                  selected={filters.routes}
                  onChange={(routes) => setFilters((f) => ({ ...f, routes }))}
                />
                <label>Остановка</label>
                <select
                  aria-label="Остановка"
                  onChange={(e) => {
                    if (e.target.value) setStopRoute(selectedRoute);
                  }}
                >
                  <option value="">Выберите остановку…</option>
                  {asList(stops.data, "stops").map((s) => (
                    <option key={s.stop_id} value={s.stop_id}>
                      {s.name}
                    </option>
                  ))}
                </select>
                <label>Временной интервал</label>
                <HourFilter filters={filters} setFilters={setFilters} />
                <label>Статус</label>
                <select
                  aria-label="Статус"
                  value={statusFilter}
                  onChange={(e) => setStatusFilter(e.target.value)}
                >
                  <option value="all">Все статусы</option>
                  <option value="FULL_CLOSURE">Закрытие движения</option>
                  <option value="SHORTENING">Укорочение</option>
                </select>
              </Panel>
              <Events
                events={events.filter(
                  (e) => statusFilter === "all" || e.type === statusFilter,
                )}
                onRoute={openRoute}
              />
              <div className="sidebar-foot">
                <Export params={params} notify={setToast} />
                <small>
                  Данные до {meta.data?.history_to || "—"}
                  <br />
                  Прогноз {meta.data?.forecast_from || "—"} —{" "}
                  {meta.data?.forecast_to || "—"}
                </small>
              </div>
            </>
          )}
        </aside>
        {analytics ? (
          <div className="analytics-content">
            <div className="analytics-top">
              <Panel
                title="Прогноз и факт"
                info="Синяя линия — исторические данные, красная — прогноз с учётом выбранных коэффициентов и изменений движения."
                className="forecast-panel"
              >
                <ResourceError resource={forecast} />
                <NetworkWarnings events={events} />
                <LineChart
                  points={series}
                  history={
                    filters.horizon === "year" ? historyPoints : compHistory
                  }
                  horizon={filters.horizon}
                />
              </Panel>
              <aside className="analytics-factors">
                <Factors
                  resource={factors}
                  horizon={filters.horizon}
                  onScope={() => setScopeOpen(true)}
                />
              </aside>
            </div>
            <div className="analytics-bottom">
              <Panel
                title={
                  {
                    day: "Типичный суточный профиль (история)",
                    month: "Сезонность по месяцам (история)",
                    year: "Сезонность по годам (история)",
                  }[filters.horizon]
                }
                info="Показывает повторяющиеся пики и спады пассажиропотока по историческим данным."
                className="history-panel"
              >
                <HistoricalBars filters={filters} />
              </Panel>
              <Panel
                title={`Тепловая карта: маршрут × ${{ day: "час", month: "день месяца", year: "месяц" }[filters.horizon]}`}
                className="heat-panel"
                info="Каждая строка — маршрут, каждый столбец — временной интервал. Тёплые цвета обозначают больший пассажиропоток."
                actions={<small>10 маршрутов</small>}
              >
                <Heatmap
                  byRoute={
                    filters.horizon === "year"
                      ? mergeByRoute(
                          history.data?.by_route,
                          forecast.data?.by_route,
                        )
                      : forecast.data?.by_route
                  }
                  horizon={filters.horizon}
                />
              </Panel>
              <Ranking
                resource={ranking}
                onRoute={openRoute}
                horizon={filters.horizon}
              />
            </div>
          </div>
        ) : (
          <>
            <div className="dispatch-center">
              <TramMap
                geometry={geometry.data}
                stops={asList(stops.data, "stops")}
                ranking={rank}
                onRoute={openRoute}
                demo={demo}
              />
              {geometry.error && (
                <p className="error compact">{geometry.error}</p>
              )}
              <Panel
                title="Загруженность / Прогноз"
                className="dispatch-chart"
                actions={
                  <div className="chart-controls">
                    <DateFilter filters={filters} setFilters={setFilters} />
                  </div>
                }
              >
                <ResourceError resource={previewForView} />
                <NetworkWarnings events={events} />
                <LineChart
                  points={series}
                  history={historyPoints}
                  horizon={filters.horizon}
                  dispatch
                />
                <div className="stop-caption">
                  <button onClick={() => setStopRoute(selectedRoute)}>
                    Остановки · маршрут {selectedRoute}
                  </button>
                  <span>
                    {stops.data?.note ||
                      "Оговорка о разбивке по остановкам ожидается от API."}
                  </span>
                </div>
                {filters.routes.includes("5") && (
                  <small className="route-note">
                    Маршрут 5 запущен 16 декабря 2025; до запуска прогноз равен
                    нулю.
                  </small>
                )}
              </Panel>
            </div>
            <aside className="right-sidebar">
              <Coefficients
                coeff={coeff}
                setCoeff={setCoeff}
                factors={factors.data}
                preview={previewForView}
                date={filters.date_from}
              />
              <Recommendations
                ranking={rank}
                forecast={dispatchForecast}
                onAction={setToast}
              />
              <Panel
                title={`Действие по маршруту ${selectedRoute}`}
                className="action-panel"
              >
                <span>Прогноз пассажиропотока</span>
                <strong>
                  {format(dispatchForecast?.summary?.peak?.value)}{" "}
                  <small>в пиковый интервал</small>
                </strong>
                <button
                  className="primary"
                  onClick={() =>
                    setToast(
                      "Выбрано добавление резервного вагона. API управления движением в контракте отсутствует — команда не отправлена.",
                    )
                  }
                >
                  Добавить резервный вагон
                </button>
                <button
                  onClick={() =>
                    setToast(
                      "Предложение: увеличить частоту. Решение требует подтверждения диспетчером вне сервиса.",
                    )
                  }
                >
                  <TrendingUp size={18} />
                  Увеличить частоту
                </button>
                <button
                  onClick={() =>
                    setToast(
                      "Предложение: перераспределить состав. API для этой операции не предоставлен.",
                    )
                  }
                >
                  <ArrowLeftRight size={18} />
                  Перераспределить состав
                </button>
              </Panel>
            </aside>
          </>
        )}
      </main>
      {stopRoute && (
        <StopPanel
          route={stopRoute}
          params={params}
          onClose={() => setStopRoute(null)}
        />
      )}{" "}
      {admin && (
        <Admin
          onClose={() => setAdmin(false)}
          onSaved={() => setRevision((v) => v + 1)}
        />
      )}{" "}
      {scopeOpen && (
        <Modal
          title="Факторы и ограничения модели"
          onClose={() => setScopeOpen(false)}
        >
          <ResourceError resource={scope} />
          {scope.data && (
            <pre className="scope-text">
              {typeof scope.data === "string"
                ? scope.data
                : JSON.stringify(scope.data, null, 2)}
            </pre>
          )}
        </Modal>
      )}
      {toast && (
        <div className="toast" role="status">
          <Info size={18} />
          <span>{toast}</span>
          <button onClick={() => setToast("")} aria-label="Закрыть сообщение">
            <X size={16} />
          </button>
        </div>
      )}
    </div>
  );
}
function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/dashboard/*" element={<Workspace />} />
        <Route path="/analytics" element={<Workspace />} />
        <Route path="/" element={<Navigate to="/login" replace />} />
        <Route path="*" element={<Navigate to="/dashboard" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
createRoot(document.getElementById("root")).render(<App />);
