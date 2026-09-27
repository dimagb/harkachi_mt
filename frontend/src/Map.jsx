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
  segmentStops = [],
  referenceStops = [],
  selectedStop = null,
  routeLoads = {},
  routeLoadsLoading = false,
  loadBandFilter = "all",
  onRoute,
  onStopSelect,
  demo,
  selectedRoutes = [],
}) {
  const el = useRef(),
    map = useRef(),
    onClick = useRef(onRoute),
    onStopClick = useRef(onStopSelect),
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
  onStopClick.current = onStopSelect;
  useEffect(() => {
    if (loadBandFilter !== "all") setLoad(true);
  }, [loadBandFilter]);
  const matchesRoute = (route) =>
    routeMatchesLoad(route, selectedRoutes, loadBandFilter, routeLoads);
  useEffect(() => {
    if (!ready || !selectedStop || !Number.isFinite(selectedStop.lon) ||
      !Number.isFinite(selectedStop.lat)) return;
    map.current?.flyTo({ center: [selectedStop.lon, selectedStop.lat],
      zoom: Math.max(map.current.getZoom(), 13) });
  }, [ready, selectedStop?.stop_id]);
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
        const stopLayers = m.getLayoutProperty("tram-stops", "visibility") === "visible"
          ? ["tram-stops", "selected-stop-marker"] : ["selected-stop-marker"];
        if (m.queryRenderedFeatures(e.point, { layers: stopLayers }).length)
          return;
        const route = String(e.features[0].properties.route);
        setFocusedRoute(route);
        setShowStops(true);
        onClick.current(route);
      };
      const selectStop = (e) => {
        const { stop_id: stopId, route } = e.features[0]?.properties || {};
        if (stopId && route != null) {
          setFocusedRoute(String(route));
          onStopClick.current(stopId, route);
        }
      };
      const hoverRoute = (e) => {
        m.getCanvas().style.cursor = "pointer";
        setHoveredRoute(String(e.features[0].properties.route));
      };
      const leaveRoute = () => {
        m.getCanvas().style.cursor = "";
        setHoveredRoute(null);
      };
      for (const layer of ["tram-lines", "tram-return-lines", "tram-segment-lines",
        "tram-route-badges", "tram-route-badge-text"]) {
        m.on("click", layer, selectRoute);
        m.on("mousemove", layer, hoverRoute);
        m.on("mouseleave", layer, leaveRoute);
      }
      for (const layer of ["tram-stops", "selected-stop-marker"]) {
        m.on("click", layer, selectStop);
        m.on("mouseenter", layer, () => { m.getCanvas().style.cursor = "pointer"; });
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
        },
      })),
    };
    if (m.getSource("trams")) m.getSource("trams").setData(data);
    else {
      m.addSource("trams", { type: "geojson", data });
      m.addLayer({
        id: "tram-casing",
        type: "line",
        source: "trams",
        filter: ["==", ["get", "direction"], 0],
        layout: { "line-cap": "round", "line-join": "round" },
        paint: {
          "line-color": "#00111d",
          "line-width": 7,
        },
      });
      m.addLayer({
        id: "tram-lines",
        type: "line",
        source: "trams",
        filter: ["==", ["get", "direction"], 0],
        layout: { "line-cap": "round", "line-join": "round" },
        paint: {
          "line-color": loadColor,
          "line-width": 4,
        },
      });
      m.addLayer({
        id: "tram-return-casing", type: "line", source: "trams", minzoom: 14,
        filter: ["==", ["get", "direction"], 1],
        layout: { "line-cap": "round", "line-join": "round" },
        paint: { "line-color": "#00111d", "line-width": 5 },
      });
      m.addLayer({
        id: "tram-return-lines", type: "line", source: "trams", minzoom: 14,
        filter: ["==", ["get", "direction"], 1],
        layout: { "line-cap": "round", "line-join": "round" },
        paint: { "line-color": loadColor, "line-width": 2.5 },
      });
    }
    const sd = {
      type: "FeatureCollection",
      features: stops
        .filter((s) => matchesRoute(s.route) &&
          Number.isFinite(s.lat) && Number.isFinite(s.lon))
        .map((s) => ({
          type: "Feature",
          geometry: { type: "Point", coordinates: [s.lon, s.lat] },
          properties: { name: s.name, is_hub: s.is_hub, stop_id: s.stop_id, route: s.route },
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
          "circle-radius": ["case", ["==", ["get", "is_hub"], true], 4, 3],
          "circle-stroke-color": "#37bba3",
          "circle-stroke-width": 1,
        },
      });
    }
    const selectedStopData = {
      type: "FeatureCollection",
      features: selectedStop && Number.isFinite(selectedStop.lat) && Number.isFinite(selectedStop.lon)
        ? [{ type: "Feature", geometry: { type: "Point",
          coordinates: [selectedStop.lon, selectedStop.lat] },
          properties: { name: selectedStop.name, stop_id: selectedStop.stop_id,
            route: selectedStop.route } }] : [],
    };
    if (m.getSource("selected-stop")) m.getSource("selected-stop").setData(selectedStopData);
    else {
      m.addSource("selected-stop", { type: "geojson", data: selectedStopData });
      m.addLayer({ id: "selected-stop-marker", type: "circle", source: "selected-stop",
        paint: { "circle-radius": 8, "circle-color": "#f2fbff",
          "circle-stroke-color": "#008dff", "circle-stroke-width": 4 } });
      m.addLayer({ id: "selected-stop-label", type: "symbol", source: "selected-stop",
        layout: { "text-field": ["get", "name"], "text-size": 13,
          "text-offset": [0, -1.8], "text-anchor": "bottom" },
        paint: { "text-color": "#ffffff", "text-halo-color": "#00111d",
          "text-halo-width": 3 } });
    }
    const segments = focusedRoute && showStopSegments
      ? data.features.flatMap((feature) =>
          String(feature.properties.route) === focusedRoute
            ? stopSegments(feature, segmentStops, referenceStops) : [])
      : [];
    const segmentData = { type: "FeatureCollection", features: segments };
    if (m.getSource("tram-segments")) m.getSource("tram-segments").setData(segmentData);
    else {
      m.addSource("tram-segments", { type: "geojson", data: segmentData });
      m.addLayer({
        id: "tram-segment-lines", type: "line", source: "tram-segments",
        layout: { "line-cap": "round", "line-join": "round" },
        paint: { "line-color": loadColor, "line-width": 5 },
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
          "circle-radius": 12,
          "circle-color": "#001b2b",
          "circle-stroke-color": loadColor,
          "circle-stroke-width": 2,
        },
      });
      m.addLayer({
        id: "tram-route-badge-text", type: "symbol", source: "tram-route-labels",
        layout: { "text-field": ["to-string", ["get", "route"]],
          "text-size": 11, "text-allow-overlap": true },
        paint: { "text-color": "#f2f8fc" },
      });
    }
    for (const name of ["tram-lines", "tram-casing", "tram-return-lines",
      "tram-return-casing", "tram-route-badges",
      "tram-route-badge-text", "tram-segment-lines"])
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
    m.setPaintProperty("tram-return-lines", "line-color", load ? loadColor : "#0095ff");
    m.setPaintProperty("tram-route-badges", "circle-stroke-color", load ? loadColor : "#0095ff");
    // Маркеры должны оставаться поверх раскрашенных отрезков.
    for (const name of ["tram-route-badges", "tram-route-badge-text",
      "tram-stops", "selected-stop-marker", "selected-stop-label"])
      m.moveLayer(name);
  }, [ready, geometry, stops, segmentStops, referenceStops, selectedStop,
    routeLoads, showRoutes, showStops, showStopSegments,
    focusedRoute, load, selectedRoutes.join(","), loadBandFilter]);
  useEffect(() => {
    if (focusedRoute && !matchesRoute(focusedRoute)) setFocusedRoute(null);
  }, [focusedRoute, loadBandFilter, routeLoads, selectedRoutes.join(",")]);
  useEffect(() => {
    const m = map.current;
    if (!ready || !m?.getLayer("tram-lines")) return;
    const active = focusedRoute || hoveredRoute;
    const opacity = active
      ? ["case", ["==", ["get", "route"], Number(active)], 1, 0.3] : 1;
    m.setPaintProperty("tram-lines", "line-opacity", opacity);
    m.setPaintProperty("tram-casing", "line-opacity", opacity);
    m.setPaintProperty("tram-return-lines", "line-opacity", opacity);
    m.setPaintProperty("tram-return-casing", "line-opacity", opacity);
  }, [ready, hoveredRoute, focusedRoute]);
  const routeNumbers = [...new Set((geometry?.features || [])
    .map((f) => Number(f.properties?.route)))]
    .filter(Number.isFinite).sort((a, b) => a - b)
    .filter(matchesRoute);
  const hasStopSegments = focusedRoute && (geometry?.features || []).some((feature) =>
    String(feature.properties?.route) === focusedRoute &&
    stopSegments(feature, segmentStops, referenceStops).length > 0);
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
            setFocusedRoute(String(route));
            setShowStops(true);
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
          Цвет участков выбранного маршрута: среднее оценочное число посадок у соседних остановок относительно базового прогноза.
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
          <small>Оценочные посадки у соседних остановок · цвет относительно базового прогноза маршрута, не заполненности вагона</small>
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
