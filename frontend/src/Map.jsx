import React, { useEffect, useRef, useState } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { Layers, LocateFixed } from "lucide-react";
import { LOAD_COLORS } from "./routeLoad";

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
    [showStops, setShowStops] = useState(true),
    [load, setLoad] = useState(true),
    [layers, setLayers] = useState(false);
  onClick.current = onRoute;
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
      m.on("click", "tram-lines", (e) =>
        onClick.current(String(e.features[0].properties.route)),
      );
      m.on(
        "mouseenter",
        "tram-lines",
        () => (m.getCanvas().style.cursor = "pointer"),
      );
      m.on("mouseleave", "tram-lines", () => (m.getCanvas().style.cursor = ""));
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
        .filter((f) => !selectedRoutes.length ||
          selectedRoutes.includes(String(f.properties?.route)))
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
        id: "tram-lines",
        type: "line",
        source: "trams",
        paint: {
          "line-color": loadColor,
          "line-width": 4,
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
    for (const name of ["tram-lines", "tram-glow"])
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
  }, [ready, geometry, stops, routeLoads, showRoutes, showStops, load, selectedRoutes.join(",")]);
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
      {layers && (
        <div className="map-layer-popover">
          OpenFreeMap · Москва
          <br />
          Маршруты и остановки: данные API
          <br />
          Цвет линии: нагрузка относительно пикового часа каждого маршрута
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
