import React, { useEffect, useRef, useState } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { Layers, LocateFixed } from "lucide-react";
import { LOAD_COLORS, routeMatchesLoad } from "./routeLoad";
import { stopSegments } from "./stopSegments";

const loadColor = [
  "match", ["get", "loadBand"],
  "low", LOAD_COLORS.low,
  "moderate", LOAD_COLORS.moderate,
  "busy", LOAD_COLORS.busy,
  "high", LOAD_COLORS.high,
  LOAD_COLORS.unknown,
];

export default function TramMap({
  geometry,
  stops = [],
  routeLoads = {},
  routeLoadsLoading = false,
  loadBandFilter = "all",
  onRoute,
  demo,
  selectedRoutes = [],
}) {
  const el = useRef(),
    map = useRef(),
    onClick = useRef(onRoute),
    [ready, setReady] = useState(false),
    [error, setError] = useState(""),
    [showRoutes, setShowRoutes] = useState(true),
    [showStops, setShowStops] = useState(false),
    [load, setLoad] = useState(true),
    [showStopSegments, setShowStopSegments] = useState(true),
    [layers, setLayers] = useState(false),
    [hoveredRoute, setHoveredRoute] = useState(null),
    [focusedRoute, setFocusedRoute] = useState(null);
  onClick.current = onRoute;
  useEffect(() => {
    if (loadBandFilter !== "all") setLoad(true);
  }, [loadBandFilter]);
  const matchesRoute = (route) =>
    routeMatchesLoad(route, selectedRoutes, loadBandFilter, routeLoads);
  useEffect(() => {
    let m;
    try {
      m = new maplibregl.Map({
        container: el.current,
        style: "https://tiles.openfreemap.org/styles/dark",
        center: [37.6173, 55.7558],
        zoom: 11,
        attributionControl: true,
      });
      map.current = m;
      m.addControl(
        new maplibregl.NavigationControl({ showCompass: false }),
        "bottom-right",
      );
      m.addControl(new maplibregl.ScaleControl({ unit: "metric" }));
      m.on("load", () => {
        for (const l of m.getStyle().layers) {
          try {
            if (l.type === "background")
              m.setPaintProperty(l.id, "background-color", "#031d2c");
            if (l.type === "fill" && /water/.test(l.id))
              m.setPaintProperty(l.id, "fill-color", "#073a50");
            if (l.type === "fill" && /park|landcover|landuse/.test(l.id))
              m.setPaintProperty(l.id, "fill-color", "#062936");
            if (l.type === "line" && /road|transportation/.test(l.id))
              m.setPaintProperty(
                l.id,
                "line-color",
                /major|primary|trunk|motorway/.test(l.id)
                  ? "#54604d"
                  : "#163c4a",
              );
            if (l.type === "symbol" && l.layout?.["text-field"]) {
              m.setLayoutProperty(l.id, "text-field", [
                "coalesce",
                ["get", "name:ru"],
                ["get", "name"],
              ]);
              m.setPaintProperty(l.id, "text-color", "#a8c2d3");
              m.setPaintProperty(l.id, "text-halo-color", "#052231");
            }
          } catch {}
        }
        setReady(true);
        setError("");
      });
      m.on("error", () =>
        setError(
          "Не удалось загрузить часть карты OpenFreeMap. Проверьте подключение к сети.",
        ),
      );
      const selectRoute = (e) => {
        const route = String(e.features[0].properties.route);
        setFocusedRoute(route);
        setShowStops(false);
        onClick.current(route);
      };
      const hoverRoute = (e) => {
        m.getCanvas().style.cursor = "pointer";
        setHoveredRoute(String(e.features[0].properties.route));
      };
      const leaveRoute = () => {
        m.getCanvas().style.cursor = "";
        setHoveredRoute(null);
      };
      for (const layer of ["tram-lines", "tram-segment-lines",
        "tram-route-badges", "tram-route-badge-text"]) {
        m.on("click", layer, selectRoute);
        m.on("mousemove", layer, hoverRoute);
        m.on("mouseleave", layer, leaveRoute);
      }
    } catch {
      setError("Браузер не поддерживает интерактивную карту WebGL.");
    }
    return () => {
      m?.remove();
      map.current = null;
    };
  }, []);
  useEffect(() => {
    const m = map.current;
    if (!ready || !m) return;
    const visibleRoutes = [...new Set((geometry?.features || [])
      .filter((f) => matchesRoute(f.properties?.route))
      .map((f) => Number(f.properties?.route)))]
      .filter(Number.isFinite).sort((a, b) => a - b);
    const alignedRoute = focusedRoute ||
      (showStops && stops[0] ? String(stops[0].route) : null);
    const data = {
      type: "FeatureCollection",
      // Пустой выбор — все маршруты. У маршрута две features (по одной на
      // направление), фильтр по properties.route оставляет обе.
      features: (geometry?.features || [])
        .filter((f) => matchesRoute(f.properties?.route))
        .map((f) => ({
        ...f,
        properties: {
          ...f.properties,
          loadBand: routeLoads[String(f.properties.route)]?.band || "unknown",
          laneOffset: alignedRoute === String(f.properties.route) ? 0 :
            (visibleRoutes.indexOf(Number(f.properties.route)) -
              (visibleRoutes.length - 1) / 2) * 6 *
              (Number(f.properties.direction) === 1 ? -1 : 1),
        },
      })),
    };
    if (m.getSource("trams")) m.getSource("trams").setData(data);
    else {
      m.addSource("trams", { type: "geojson", data });
      m.addLayer({
        id: "tram-glow",
        type: "line",
        source: "trams",
        paint: {
          "line-color": loadColor,
          "line-width": 9,
          "line-opacity": 0.12,
        },
      });
      m.addLayer({
        id: "tram-casing",
        type: "line",
        source: "trams",
        paint: {
          "line-color": "#00111d",
          "line-width": 8,
          "line-offset": ["get", "laneOffset"],
        },
      });
      m.addLayer({
        id: "tram-lines",
        type: "line",
        source: "trams",
        paint: {
          "line-color": loadColor,
          "line-width": 4,
          "line-offset": ["get", "laneOffset"],
        },
      });
      m.addLayer({
        id: "tram-focus-casing",
        type: "line",
        source: "trams",
        filter: ["==", ["get", "route"], -1],
        paint: {
          "line-color": "#00111d",
          "line-width": 12,
          "line-offset": ["get", "laneOffset"],
        },
      });
      m.addLayer({
        id: "tram-focus",
        type: "line",
        source: "trams",
        filter: ["==", ["get", "route"], -1],
        paint: {
          "line-color": loadColor,
          "line-width": 7,
          "line-offset": ["get", "laneOffset"],
        },
      });
    }
    const sd = {
      type: "FeatureCollection",
      features: stops
        .filter((s) => Number.isFinite(s.lat) && Number.isFinite(s.lon))
        .map((s) => ({
          type: "Feature",
          geometry: { type: "Point", coordinates: [s.lon, s.lat] },
          properties: { name: s.name, is_hub: s.is_hub, stop_id: s.stop_id },
        })),
    };
    if (m.getSource("stops")) m.getSource("stops").setData(sd);
    else {
      m.addSource("stops", { type: "geojson", data: sd });
      m.addLayer({
        id: "tram-stops",
        type: "circle",
        source: "stops",
        paint: {
          "circle-color": "#e5f8ff",
          "circle-radius": ["case", ["==", ["get", "is_hub"], true], 5, 3],
          "circle-stroke-color": "#37bba3",
          "circle-stroke-width": 1.5,
        },
      });
    }
    const segments = focusedRoute && showStopSegments
      ? data.features.flatMap((feature) =>
          String(feature.properties.route) === focusedRoute
            ? stopSegments(feature, stops) : [])
      : [];
    const segmentData = { type: "FeatureCollection", features: segments };
    if (m.getSource("tram-segments")) m.getSource("tram-segments").setData(segmentData);
    else {
      m.addSource("tram-segments", { type: "geojson", data: segmentData });
      m.addLayer({
        id: "tram-segment-casing", type: "line", source: "tram-segments",
        paint: { "line-color": "#00111d", "line-width": 11,
          "line-offset": ["get", "laneOffset"] },
      });
      m.addLayer({
        id: "tram-segment-lines", type: "line", source: "tram-segments",
        paint: { "line-color": loadColor, "line-width": 7,
          "line-offset": ["get", "laneOffset"] },
      });
    }
    const badgeData = {
      type: "FeatureCollection",
      features: data.features.filter((feature) => Number(feature.properties.direction) === 0)
        .map((feature, index) => {
          const coordinates = feature.geometry.coordinates;
          const position = [0.35, 0.55, 0.75][index % 3];
          return {
            type: "Feature",
            geometry: { type: "Point", coordinates: coordinates[Math.floor((coordinates.length - 1) * position)] },
            properties: { route: feature.properties.route, loadBand: feature.properties.loadBand },
          };
        }),
    };
    if (m.getSource("tram-route-labels")) m.getSource("tram-route-labels").setData(badgeData);
    else {
      m.addSource("tram-route-labels", { type: "geojson", data: badgeData });
      m.addLayer({
        id: "tram-route-badges", type: "circle", source: "tram-route-labels",
        paint: {
          "circle-radius": 17,
          "circle-color": "#001b2b",
          "circle-stroke-color": loadColor,
          "circle-stroke-width": 3,
        },
      });
      m.addLayer({
        id: "tram-route-badge-text", type: "symbol", source: "tram-route-labels",
        layout: { "text-field": ["to-string", ["get", "route"]],
          "text-size": 13, "text-allow-overlap": true },
        paint: { "text-color": "#f2f8fc" },
      });
    }
    for (const name of ["tram-lines", "tram-glow", "tram-casing",
      "tram-focus", "tram-focus-casing", "tram-route-badges", "tram-route-badge-text",
      "tram-segment-casing", "tram-segment-lines"])
      m.setLayoutProperty(name, "visibility", showRoutes ? "visible" : "none");
    m.setLayoutProperty(
      "tram-stops",
      "visibility",
      showStops ? "visible" : "none",
    );
    m.setPaintProperty(
      "tram-lines",
      "line-color",
      load
        ? loadColor
        : "#0095ff",
    );
    m.setPaintProperty("tram-glow", "line-color", load ? loadColor : "#0095ff");
    m.setPaintProperty("tram-focus", "line-color", load ? loadColor : "#0095ff");
    m.setPaintProperty("tram-route-badges", "circle-stroke-color", load ? loadColor : "#0095ff");
  }, [ready, geometry, stops, routeLoads, showRoutes, showStops, showStopSegments,
    focusedRoute, load, selectedRoutes.join(","), loadBandFilter]);
  useEffect(() => {
    if (focusedRoute && !matchesRoute(focusedRoute)) setFocusedRoute(null);
  }, [focusedRoute, loadBandFilter, routeLoads, selectedRoutes.join(",")]);
  useEffect(() => {
    const m = map.current;
    if (!ready || !m?.getLayer("tram-focus")) return;
    const active = hoveredRoute || focusedRoute;
    const filter = ["==", ["get", "route"], active ? Number(active) : -1];
    m.setFilter("tram-focus", filter);
    m.setFilter("tram-focus-casing", filter);
    m.setPaintProperty("tram-lines", "line-opacity", active ? 0.4 : 1);
    m.setPaintProperty("tram-casing", "line-opacity", active ? 0.5 : 1);
    m.setPaintProperty("tram-glow", "line-opacity", active ? 0.04 : 0.12);
  }, [ready, hoveredRoute, focusedRoute]);
  const routeNumbers = [...new Set((geometry?.features || [])
    .map((f) => Number(f.properties?.route)))]
    .filter(Number.isFinite).sort((a, b) => a - b)
    .filter(matchesRoute);
  const hasStopSegments = focusedRoute && (geometry?.features || []).some((feature) =>
    String(feature.properties?.route) === focusedRoute &&
    stopSegments(feature, stops).length > 0);
  return (
    <section className="map panel">
      <div ref={el} className="map-canvas" />
      <div className="map-toolbar">
        <div className="tabs">
          <button className="active">Карта</button>
        </div>
        <div className="map-toggles">
          <label>
            <input
              type="checkbox"
              checked={showRoutes}
              onChange={(e) => setShowRoutes(e.target.checked)}
            />
            Показать маршруты
          </label>
          <label>
            <input
              type="checkbox"
              checked={showStops}
              onChange={(e) => setShowStops(e.target.checked)}
            />
            Показать остановки
          </label>
          <label>
            <input type="checkbox" checked={showStopSegments}
              onChange={(e) => setShowStopSegments(e.target.checked)} />
            Оценка по остановкам
          </label>
          <label>
            <input
              type="checkbox"
              checked={load}
              onChange={(e) => setLoad(e.target.checked)}
            />
            Загрузка маршрутов
          </label>
          <button onClick={() => setLayers(!layers)}>
            <Layers size={15} />
            Слои
          </button>
        </div>
      </div>
      {showRoutes && routeNumbers.length > 0 && <div className="map-route-key" aria-label="Маршруты на карте">
        {routeNumbers.map((route) => <button key={route} type="button"
          aria-label={`Выделить маршрут ${route}`}
          aria-pressed={focusedRoute === String(route)}
          onClick={() => {
            setFocusedRoute((current) => current === String(route) ? null : String(route));
            setShowStops(false);
            onClick.current(String(route));
          }}
          onMouseEnter={() => setHoveredRoute(String(route))}
          onMouseLeave={() => setHoveredRoute(null)}
          style={{ borderColor: load ? LOAD_COLORS[routeLoads[String(route)]?.band || "unknown"] : "#0095ff" }}>
          {route}
        </button>)}
      </div>}
      {loadBandFilter !== "all" && !routeNumbers.length && geometry?.features?.length > 0 && (
        <div className="map-notice">{routeLoadsLoading
          ? "Расчёт загрузки маршрутов…"
          : "Нет маршрутов с выбранным уровнем загрузки"}</div>
      )}
      {layers && (
        <div className="map-layer-popover">
          OpenFreeMap · Москва
          <br />
          Маршруты и остановки: данные API
          <br />
          Цвет маршрута: поток относительно пикового часа.
          <br />
          Цвет участков выбранного маршрута: средняя оценочная доля посадок у соседних остановок.
        </div>
      )}
      {load && showRoutes && <div className="map-load-legend" aria-label="Уровни нагрузки маршрутов">
        <div className="map-load-legend-items">
          {[["low", "Почти пусто"], ["moderate", "Небольшая"],
            ["busy", "Средняя"], ["high", "Высокая"]].map(([band, label]) =>
            <span key={band}><i style={{ backgroundColor: LOAD_COLORS[band] }} />{label}</span>)}
        </div>
        <small>Относительно пика маршрута · без данных о вместимости вагонов</small>
      </div>}
      {showRoutes && showStopSegments && hasStopSegments && (
        <div className="map-stop-legend" aria-label="Оценочные посадки по остановкам">
          <b>Маршрут {focusedRoute} · оценочные посадки</b>
          <div className="map-load-legend-items">
            {[["low", "Низкие"], ["moderate", "Умеренные"],
              ["busy", "Повышенные"], ["high", "Высокие"]].map(([band, label]) =>
              <span key={band}><i style={{ backgroundColor: LOAD_COLORS[band] }} />{label}</span>)}
          </div>
          <small>Квартили внутри маршрута · средняя доля соседних остановок · не заполненность вагона</small>
        </div>
      )}
      {(error || demo) && (
        <div className="map-notice">
          {error ||
            "Демопросмотр · линии маршрутов появятся после подключения API"}
        </div>
      )}
      <button
        className="map-center"
        aria-label="Вернуться к Москве"
        onClick={() =>
          map.current?.flyTo({ center: [37.6173, 55.7558], zoom: 11 })
        }
      >
        <LocateFixed size={18} />
      </button>
      <div className="missing-geometry">
        Без координат:{" "}
        {(geometry?.routes_without_geometry || [])
          .map((r) => (typeof r === "object" ? r.route : r))
          .join(", ") || "—"}{" "}
        <span> · в справочниках организаторов</span>
      </div>
    </section>
  );
}
