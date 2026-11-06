import maplibregl, { type GeoJSONSource, type LngLatBoundsLike } from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { useEffect, useRef, useState } from 'react'
import type { Checkpoint, HeatmapResponse, PlanResponse, Route } from '../api/types'
import { fmtDateTime, fmtDuration, fmtMiles } from '../lib/format'
import { RISK_COLOR, RISK_LABEL, ROUTE_COLORS } from '../lib/risk'
import { truckAt } from '../lib/timeline'

const STYLE_URL = 'https://tiles.openfreemap.org/styles/positron'
const EMPTY: GeoJSON.FeatureCollection = { type: 'FeatureCollection', features: [] }

export interface CheckpointRef {
  routeId: string
  index: number
}

interface Props {
  plan: PlanResponse | null
  heatmap: HeatmapResponse | null
  frames: string[] | null
  /** Hours since heatmap start (fractional while animating). */
  hour: number
  heatOpacity: number
  heatVisible: boolean
  selectedRouteId: string | null
  onSelectRoute: (id: string) => void
  selectedCheckpoint: CheckpointRef | null
  onSelectCheckpoint: (ref: CheckpointRef | null) => void
}

export default function MapView(props: Props) {
  const container = useRef<HTMLDivElement>(null)
  const mapRef = useRef<maplibregl.Map | null>(null)
  const [ready, setReady] = useState(false)
  const hoverPopup = useRef<maplibregl.Popup | null>(null)
  const clickPopup = useRef<maplibregl.Popup | null>(null)
  const markers = useRef<maplibregl.Marker[]>([])
  const heatLayerCount = useRef(0)
  // keep latest callbacks/data for map event handlers registered once
  const latest = useRef(props)
  latest.current = props

  // ---- init -----------------------------------------------------------
  useEffect(() => {
    const map = new maplibregl.Map({
      container: container.current!,
      style: STYLE_URL,
      // continental US, framed for whatever size the map area is
      bounds: [[-124.8, 24.4], [-66.9, 49.4]],
      fitBoundsOptions: { padding: 24 },
      attributionControl: { compact: true },
      fadeDuration: 0,
    })
    mapRef.current = map
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right')
    map.addControl(new maplibregl.ScaleControl({ unit: 'imperial' }), 'bottom-right')

    map.on('load', () => {
      const firstSymbol = map.getStyle().layers.find((l) => l.type === 'symbol')?.id
      // invisible anchor that marks where heatmap frames are inserted (above roads, below labels)
      map.addSource('heat-anchor', { type: 'geojson', data: EMPTY })
      map.addLayer({ id: 'heat-anchor', type: 'circle', source: 'heat-anchor', paint: { 'circle-radius': 0 } }, firstSymbol)

      map.addSource('routes', { type: 'geojson', data: EMPTY })
      map.addLayer({
        id: 'route-casing',
        type: 'line',
        source: 'routes',
        layout: { 'line-cap': 'round', 'line-join': 'round', 'line-sort-key': ['get', 'sort'] },
        paint: {
          'line-color': '#ffffff',
          'line-width': ['case', ['get', 'selected'], 9, 6],
          'line-opacity': ['case', ['get', 'selected'], 1, 0.7],
        },
      })
      map.addLayer({
        id: 'route-line',
        type: 'line',
        source: 'routes',
        layout: { 'line-cap': 'round', 'line-join': 'round', 'line-sort-key': ['get', 'sort'] },
        paint: {
          'line-color': ['get', 'color'],
          'line-width': ['case', ['get', 'selected'], 5, 3],
          'line-opacity': ['case', ['get', 'selected'], 1, 0.55],
        },
      })
      map.addLayer({
        id: 'route-hit',
        type: 'line',
        source: 'routes',
        paint: { 'line-color': '#000', 'line-width': 18, 'line-opacity': 0 },
      })

      map.addSource('checkpoints', { type: 'geojson', data: EMPTY })
      map.addLayer({
        id: 'checkpoints',
        type: 'circle',
        source: 'checkpoints',
        layout: { 'circle-sort-key': ['get', 'sort'] },
        paint: {
          'circle-color': ['get', 'color'],
          'circle-radius': [
            'interpolate', ['linear'], ['zoom'],
            4, ['case', ['get', 'selected'], 3.5, 2],
            8, ['case', ['get', 'selected'], 6, 3.5],
            12, ['case', ['get', 'selected'], 8, 5],
          ],
          'circle-stroke-color': '#ffffff',
          'circle-stroke-width': ['case', ['get', 'selected'], 1.5, 0.75],
          'circle-opacity': ['case', ['get', 'selected'], 1, 0.75],
        },
      })
      map.addLayer({
        id: 'checkpoint-focus',
        type: 'circle',
        source: 'checkpoints',
        filter: ['==', ['get', 'focus'], true],
        paint: {
          'circle-radius': 13,
          'circle-color': 'rgba(0,0,0,0)',
          'circle-stroke-color': '#0b2733',
          'circle-stroke-width': 2.5,
        },
      })

      map.addSource('stops', { type: 'geojson', data: EMPTY })
      map.addLayer({
        id: 'stops',
        type: 'circle',
        source: 'stops',
        paint: {
          'circle-radius': ['case', ['==', ['get', 'kind'], 'rest'], 7, 5],
          'circle-color': '#0b2733',
          'circle-stroke-color': '#ffffff',
          'circle-stroke-width': 2,
        },
      })

      map.addSource('trucks', { type: 'geojson', data: EMPTY })
      map.addLayer({
        id: 'trucks',
        type: 'circle',
        source: 'trucks',
        paint: {
          'circle-radius': ['case', ['get', 'selected'], 12, 9],
          'circle-color': ['get', 'color'],
          'circle-stroke-color': '#ffffff',
          'circle-stroke-width': 2.5,
        },
      })
      map.addLayer({
        id: 'truck-labels',
        type: 'symbol',
        source: 'trucks',
        layout: {
          'text-field': ['get', 'id'],
          'text-font': ['Noto Sans Bold'],
          'text-size': ['case', ['get', 'selected'], 13, 11],
          'text-allow-overlap': true,
          'text-ignore-placement': true,
        },
        paint: { 'text-color': '#ffffff' },
      })

      // ---- interactions ----
      hoverPopup.current = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 10, className: 'hover-popup' })
      for (const layer of ['checkpoints', 'stops', 'route-hit', 'trucks']) {
        map.on('mouseenter', layer, () => (map.getCanvas().style.cursor = 'pointer'))
        map.on('mouseleave', layer, () => {
          map.getCanvas().style.cursor = ''
          hoverPopup.current?.remove()
        })
      }
      map.on('mousemove', 'checkpoints', (e) => {
        const f = e.features?.[0]
        const cp = f && findCheckpoint(latest.current.plan, f.properties.route, f.properties.index)
        if (!cp) return
        hoverPopup.current!.setLngLat([cp.lon, cp.lat]).setHTML(hoverHtml(f!.properties.route, cp)).addTo(map)
      })
      map.on('mousemove', 'stops', (e) => {
        const p = e.features?.[0]?.properties
        if (!p) return
        const dep = Date.parse(latest.current.plan!.request.departure)
        const text = p.kind === 'rest' ? '10-hour rest (HOS)' : '30-minute break (HOS)'
        hoverPopup.current!
          .setLngLat(e.lngLat)
          .setHTML(`<strong>Route ${esc(p.route)} · ${text}</strong><br>Mile ${Math.round(p.miles)} · from ${esc(fmtDateTime(dep + p.start * 1000))}`)
          .addTo(map)
      })
      map.on('click', (e) => {
        const hits = map.queryRenderedFeatures(e.point, { layers: ['checkpoints', 'route-hit'] })
        const cp = hits.find((h) => h.layer.id === 'checkpoints')
        if (cp) {
          latest.current.onSelectCheckpoint({ routeId: cp.properties.route, index: cp.properties.index })
          return
        }
        const route = hits.find((h) => h.layer.id === 'route-hit')
        if (route) latest.current.onSelectRoute(route.properties.id)
      })
      setReady(true)
    })

    return () => {
      map.remove()
      mapRef.current = null
    }
  }, [])

  const { plan, heatmap, frames, hour, heatOpacity, heatVisible, selectedRouteId, selectedCheckpoint, onSelectRoute } = props

  // ---- routes, checkpoints, stops, labels -------------------------------------
  useEffect(() => {
    const map = mapRef.current
    if (!ready || !map) return
    const routes = plan?.routes ?? []
    ;(map.getSource('routes') as GeoJSONSource).setData({
      type: 'FeatureCollection',
      features: routes.map((r) => ({
        type: 'Feature',
        properties: { id: r.id, color: ROUTE_COLORS[r.id], selected: r.id === selectedRouteId, sort: r.id === selectedRouteId ? 10 : r.recommended ? 5 : 0 },
        geometry: { type: 'LineString', coordinates: r.geometry.coords },
      })),
    })
    ;(map.getSource('checkpoints') as GeoJSONSource).setData({
      type: 'FeatureCollection',
      features: routes.flatMap((r) =>
        r.checkpoints.map((cp) => ({
          type: 'Feature' as const,
          properties: {
            route: r.id,
            index: cp.index,
            color: RISK_COLOR[cp.risk.level],
            selected: r.id === selectedRouteId,
            focus: selectedCheckpoint?.routeId === r.id && selectedCheckpoint.index === cp.index,
            // risky points draw on top; the selected route above the others
            sort: (r.id === selectedRouteId ? 10 : 0) + cp.risk.score,
          },
          geometry: { type: 'Point' as const, coordinates: [cp.lon, cp.lat] },
        })),
      ),
    })
    ;(map.getSource('stops') as GeoJSONSource).setData({
      type: 'FeatureCollection',
      features: routes
        .filter((r) => r.id === selectedRouteId)
        .flatMap((r) =>
          r.stops.map((s) => ({
            type: 'Feature' as const,
            properties: { route: r.id, kind: s.kind, miles: s.miles, start: s.start_offset_s },
            geometry: { type: 'Point' as const, coordinates: [s.lon, s.lat] },
          })),
        ),
    })
  }, [ready, plan, selectedRouteId, selectedCheckpoint])

  // ---- HTML markers: origin, destination, one summary chip per route ---------------
  useEffect(() => {
    const map = mapRef.current
    markers.current.forEach((m) => m.remove())
    markers.current = []
    if (!ready || !map || !plan) return
    const routes = plan.routes
    const { origin, destination } = plan.request
    markers.current.push(
      new maplibregl.Marker({ element: endpointEl('start', origin.label) }).setLngLat([origin.lon, origin.lat]).addTo(map),
      new maplibregl.Marker({ element: endpointEl('end', destination.label) }).setLngLat([destination.lon, destination.lat]).addTo(map),
    )
    const anchors = labelAnchors(routes)
    for (const r of routes) {
      const at = anchors[r.id]
      const el = chipEl(r, r.id === selectedRouteId)
      el.addEventListener('click', (ev) => {
        ev.stopPropagation()
        onSelectRoute(r.id)
      })
      markers.current.push(new maplibregl.Marker({ element: el, anchor: 'bottom', offset: [0, -10] }).setLngLat(at).addTo(map))
    }
  }, [ready, plan, selectedRouteId, onSelectRoute])

  // ---- fit to a new plan ------------------------------------------------------------
  useEffect(() => {
    const map = mapRef.current
    if (!ready || !map || !plan) return
    const b = new maplibregl.LngLatBounds()
    plan.routes.forEach((r) => r.geometry.coords.forEach((c) => b.extend(c)))
    map.fitBounds(b as LngLatBoundsLike, { padding: { top: 70, bottom: 170, left: 60, right: 60 }, duration: 900 })
  }, [ready, plan])

  // ---- checkpoint popup + fly-to --------------------------------------------------
  useEffect(() => {
    const map = mapRef.current
    clickPopup.current?.remove()
    if (!ready || !map || !plan || !selectedCheckpoint) return
    const cp = findCheckpoint(plan, selectedCheckpoint.routeId, selectedCheckpoint.index)
    if (!cp) return
    clickPopup.current = new maplibregl.Popup({ offset: 12, maxWidth: '300px', className: 'cp-popup' })
      .setLngLat([cp.lon, cp.lat])
      .setHTML(detailHtml(selectedCheckpoint.routeId, cp, plan.request.load_lb))
      .addTo(map)
    clickPopup.current.on('close', () => {
      const cur = latest.current.selectedCheckpoint
      if (cur && cur.routeId === selectedCheckpoint.routeId && cur.index === selectedCheckpoint.index) {
        latest.current.onSelectCheckpoint(null)
      }
    })
    if (!map.getBounds().contains([cp.lon, cp.lat])) map.easeTo({ center: [cp.lon, cp.lat], duration: 600 })
  }, [ready, plan, selectedCheckpoint])

  // ---- heatmap frames: one image layer per forecast hour -------------------------
  useEffect(() => {
    const map = mapRef.current
    if (!ready || !map) return
    for (let i = 0; i < heatLayerCount.current; i++) {
      if (map.getLayer(`heat-${i}`)) map.removeLayer(`heat-${i}`)
      if (map.getSource(`heat-${i}`)) map.removeSource(`heat-${i}`)
    }
    heatLayerCount.current = 0
    if (!heatmap || !frames) return
    const corners = heatmap.grid.corners as [[number, number], [number, number], [number, number], [number, number]]
    frames.forEach((url, i) => {
      map.addSource(`heat-${i}`, { type: 'image', url, coordinates: corners })
      map.addLayer(
        {
          id: `heat-${i}`,
          type: 'raster',
          source: `heat-${i}`,
          paint: { 'raster-opacity': 0, 'raster-resampling': 'linear', 'raster-fade-duration': 0, 'raster-opacity-transition': { duration: 0 } },
        },
        'heat-anchor',
      )
    })
    heatLayerCount.current = frames.length
    // geometry is identical across metrics, so this effect only re-runs when the frame set changes
  }, [ready, heatmap, frames])

  // Cross-fade between the two frames around the (possibly fractional) hour.
  useEffect(() => {
    const map = mapRef.current
    const n = heatLayerCount.current
    if (!ready || !map || !n) return
    const h = Math.min(Math.max(hour, 0), n - 1)
    const lo = Math.floor(h)
    const f = h - lo
    for (let i = 0; i < n; i++) {
      let o = 0
      if (heatVisible) {
        if (i === lo) o = heatOpacity * (1 - f)
        else if (i === lo + 1) o = heatOpacity * f
      }
      if (map.getPaintProperty(`heat-${i}`, 'raster-opacity') !== o) map.setPaintProperty(`heat-${i}`, 'raster-opacity', o)
    }
  }, [ready, hour, heatOpacity, heatVisible, frames])

  // ---- truck positions at the slider time ------------------------------------------
  useEffect(() => {
    const map = mapRef.current
    if (!ready || !map) return
    const src = map.getSource('trucks') as GeoJSONSource
    if (!plan || !heatmap) {
      src.setData(EMPTY)
      return
    }
    const offset = (Date.parse(heatmap.start) + hour * 3600_000 - Date.parse(plan.request.departure)) / 1000
    src.setData({
      type: 'FeatureCollection',
      features: plan.routes.map((r) => {
        const s = truckAt(r, offset)
        return {
          type: 'Feature',
          properties: { id: r.id, color: ROUTE_COLORS[r.id], selected: r.id === selectedRouteId },
          geometry: { type: 'Point', coordinates: [s.lon, s.lat] },
        }
      }),
    })
  }, [ready, plan, heatmap, hour, selectedRouteId])

  return <div ref={container} className="map" role="region" aria-label="Route map" />
}

// ---------------------------------------------------------------------------
function findCheckpoint(plan: PlanResponse | null, routeId: string, index: number): Checkpoint | undefined {
  return plan?.routes.find((r) => r.id === routeId)?.checkpoints[index]
}

function pointAtFraction(r: Route, frac: number): [number, number] {
  const { coords, mi } = r.geometry
  const target = mi[mi.length - 1] * frac
  let i = 0
  while (i < mi.length - 1 && mi[i + 1] < target) i++
  return coords[Math.min(i + 1, coords.length - 1)]
}

const LABEL_FRACTIONS = [0.35, 0.4, 0.45, 0.5, 0.55, 0.6, 0.65]
/** Preferred, staggered label positions so the three labels start apart. */
const LABEL_DEFAULT: Record<string, number> = { A: 0.5, B: 0.4, C: 0.6 }

/**
 * Where to pin each route's label. Each label stays near the middle of its route
 * (staggered so labels do not line up), but moves along its route when that spot is
 * on top of another route or too close to a label already placed. Distances are in
 * degrees, scaled for longitude, relative to the trip's size.
 */
function labelAnchors(routes: Route[]): Record<string, [number, number]> {
  const out: Record<string, [number, number]> = {}
  const placed: [number, number][] = []
  const all = routes.flatMap((r) => r.geometry.coords as [number, number][])
  const kx = Math.cos(((all[0]?.[1] ?? 40) * Math.PI) / 180)
  const lons = all.map((c) => c[0] * kx)
  const lats = all.map((c) => c[1])
  const span = Math.max(Math.max(...lons) - Math.min(...lons), Math.max(...lats) - Math.min(...lats), 1e-6)
  const clearLine = (span * 0.04) ** 2 // far enough from other routes
  const clearLabel = (span * 0.18) ** 2 // far enough from other labels
  const d2 = (a: [number, number], b: [number, number]) => ((a[0] - b[0]) * kx) ** 2 + (a[1] - b[1]) ** 2
  for (const r of routes) {
    const others = routes.filter((o) => o.id !== r.id).flatMap((o) => sample(o.geometry.coords as [number, number][], 400))
    const pref = LABEL_DEFAULT[r.id] ?? 0.5
    let best: [number, number] = pointAtFraction(r, pref)
    let bestScore = -Infinity
    for (const f of LABEL_FRACTIONS) {
      const p = pointAtFraction(r, f)
      let nearLine = Infinity
      for (const q of others) nearLine = Math.min(nearLine, d2(p, q))
      let nearLabel = Infinity
      for (const q of placed) nearLabel = Math.min(nearLabel, d2(p, q))
      // "good enough" is capped, so once a spot is clear the preferred position wins
      const score =
        Math.min(nearLine / clearLine, 1) + Math.min(nearLabel / clearLabel, 1) - Math.abs(f - pref) * 0.5
      if (score > bestScore) {
        bestScore = score
        best = p
      }
    }
    out[r.id] = best
    placed.push(best)
  }
  return out
}

function sample<T>(arr: T[], max: number): T[] {
  if (arr.length <= max) return arr
  const step = arr.length / max
  return Array.from({ length: max }, (_, i) => arr[Math.floor(i * step)])
}

function esc(s: unknown): string {
  return String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]!)
}

function levelBadge(level: Checkpoint['risk']['level']): string {
  return `<span class="badge" style="--c:${RISK_COLOR[level]}">${esc(RISK_LABEL[level])}</span>`
}

function hoverHtml(routeId: string, cp: Checkpoint): string {
  const drivers = cp.risk.drivers.length ? ` · ${cp.risk.drivers.join(', ')}` : ''
  return `<strong>Route ${esc(routeId)} · mile ${Math.round(cp.miles)}</strong><br>${esc(fmtDateTime(cp.eta))}<br>${levelBadge(cp.risk.level)}${esc(drivers)}`
}

function detailHtml(routeId: string, cp: Checkpoint, loadLb: number): string {
  const w = cp.weather
  const by = cp.risk.by_condition
  const row = (name: string, value: string, level: Checkpoint['risk']['level']) =>
    `<tr><th>${name}</th><td>${value}</td><td>${levelBadge(level)}</td></tr>`
  return `
    <div class="cp-detail">
      <div class="cp-head">Route ${esc(routeId)} · checkpoint ${cp.index + 1} · mile ${Math.round(cp.miles)}</div>
      <div class="cp-eta">ETA ${esc(fmtDateTime(cp.eta))}</div>
      <div class="cp-level">${levelBadge(cp.risk.level)}</div>
      <table>
        ${row('Wind', `${w.wind_mph.toFixed(1)} mph${w.gust_mph != null ? ` <span class="muted">(gust ${w.gust_mph.toFixed(0)})</span>` : ''}`, by.wind)}
        ${row('Rain', `${w.rain_in_hr.toFixed(2)} in/hr`, by.rain)}
        ${row('Snow', `${w.snow_in_hr.toFixed(2)} in/hr`, by.snow)}
      </table>
      ${cp.risk.load_rule ? `<div class="cp-rule">Load rule: ${esc(cp.risk.load_rule)} (load ${Math.round(loadLb).toLocaleString()} lb)</div>` : ''}
      ${crosswindHtml(cp)}
      ${w.temperature_f != null ? `<div class="muted">${w.temperature_f.toFixed(0)}°F · represents ${cp.coverage_mi.toFixed(1)} mi of road</div>` : ''}
    </div>`
}

const COMPASS = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW']
const compass = (deg: number) => COMPASS[Math.round((((deg % 360) + 360) % 360) / 45) % 8]

/** Extra feature: wind relative to the truck (informational, not part of the risk level). */
function crosswindHtml(cp: Checkpoint): string {
  const r = cp.wind_relative
  if (!r || cp.weather.wind_dir_deg == null) return ''
  const along =
    r.relation === 'crosswind' ? '' : ` · ${Math.abs(r.headwind_mph).toFixed(0)} mph ${r.relation}`
  return `
    <div class="cp-cross${r.strong ? ' strong' : ''}">
      <div class="cp-cross-head"><span>Crosswind</span><span class="extra-badge">Extra</span></div>
      <div><strong>${r.crosswind_mph.toFixed(0)} mph</strong> across the trailer (gusts ${r.gust_crosswind_mph.toFixed(0)})${esc(along)}</div>
      <div class="muted">Wind from ${compass(cp.weather.wind_dir_deg)}, truck heading ${compass(r.heading_deg)} · not used in the risk level</div>
    </div>`
}

function endpointEl(kind: 'start' | 'end', label: string): HTMLElement {
  const el = document.createElement('div')
  el.className = `endpoint endpoint-${kind}`
  el.title = `${kind === 'start' ? 'Origin' : 'Destination'}: ${label}`
  return el
}

function chipEl(r: Route, selected: boolean): HTMLElement {
  const el = document.createElement('button')
  el.type = 'button'
  el.className = `route-chip${selected ? ' selected' : ''}`
  el.style.setProperty('--route', ROUTE_COLORS[r.id])
  const s = r.summary
  const risk = s.no_travel_miles > 0 ? `${Math.round(s.no_travel_miles)} mi No Travel` : `${Math.round(s.severe_miles)} mi Severe`
  el.innerHTML = `<span class="chip-id">${esc(r.id)}</span>${r.recommended ? '<span class="chip-star" aria-label="Recommended">★</span>' : ''}<span>${esc(fmtMiles(r.distance_mi))} · ${esc(fmtDuration(r.trip_s))} · ${esc(risk)}</span>`
  el.setAttribute('aria-label', `Select route ${r.id}`)
  return el
}
