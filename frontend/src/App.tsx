import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ApiError, fetchHeatmap, planTrip } from './api/client'
import type { HeatMetric, HeatmapResponse, PlanRequest, PlanResponse } from './api/types'
import { ExtraBadge, IconCalendar, IconTruck, IconWind } from './components/Icons'
import MapView, { type CheckpointRef } from './components/MapView'
import RoutePanel, { type PanelTab } from './components/RoutePanel'
import TimeControl from './components/TimeControl'
import TripForm from './components/TripForm'
import { useHeatFrames } from './hooks/useHeatFrames'
import { fmtDateTime } from './lib/format'
import { RISK_LEVELS } from './lib/risk'
import { truckAt } from './lib/timeline'

/** Forecast hours advanced per second of animation. */
const PLAY_SPEED_H_PER_S = 2

export default function App() {
  const [plan, setPlan] = useState<PlanResponse | null>(null)
  const [lastRequest, setLastRequest] = useState<PlanRequest | null>(null)
  const [planLoading, setPlanLoading] = useState(false)
  const [planError, setPlanError] = useState<string | null>(null)
  const [heatmap, setHeatmap] = useState<HeatmapResponse | null>(null)
  const [heatLoading, setHeatLoading] = useState(false)
  const [heatError, setHeatError] = useState<string | null>(null)
  const [selectedRouteId, setSelectedRouteId] = useState<string | null>(null)
  const [selectedCheckpoint, setSelectedCheckpoint] = useState<CheckpointRef | null>(null)
  const [hour, setHour] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [metric, setMetric] = useState<HeatMetric>('risk')
  const [heatOpacity, setHeatOpacity] = useState(0.85)
  const [heatVisible, setHeatVisible] = useState(true)
  const [formOpen, setFormOpen] = useState(true)
  const [tab, setTab] = useState<PanelTab>('routes')
  const planCtrl = useRef<AbortController | null>(null)
  const heatCtrl = useRef<AbortController | null>(null)

  const frames = useHeatFrames(heatmap, metric)

  const loadHeatmap = useCallback((p: PlanResponse) => {
    heatCtrl.current?.abort()
    const ctrl = new AbortController()
    heatCtrl.current = ctrl
    setHeatLoading(true)
    setHeatError(null)
    fetchHeatmap(p.request.departure, p.request.load_lb, p.routes, p.weather.storm, ctrl.signal)
      .then(setHeatmap)
      .catch((e) => {
        if (e.name !== 'AbortError') setHeatError(e instanceof ApiError ? e.message : 'Heatmap failed to load.')
      })
      .finally(() => {
        if (heatCtrl.current === ctrl) setHeatLoading(false)
      })
  }, [])

  const submit = useCallback(
    (req: PlanRequest) => {
      planCtrl.current?.abort()
      heatCtrl.current?.abort()
      const ctrl = new AbortController()
      planCtrl.current = ctrl
      setPlanLoading(true)
      setPlanError(null)
      setPlaying(false)
      planTrip(req, ctrl.signal)
        .then((p) => {
          setPlan(p)
          setLastRequest(req)
          setHeatmap(null)
          setSelectedRouteId(p.recommendation.route_id)
          setSelectedCheckpoint(null)
          setHour(0)
          setFormOpen(false)
          setTab('routes')
          loadHeatmap(p)
        })
        .catch((e) => {
          if (e.name !== 'AbortError') setPlanError(e instanceof ApiError ? e.message : 'Something went wrong. Please try again.')
        })
        .finally(() => {
          if (planCtrl.current === ctrl) setPlanLoading(false)
        })
    },
    [loadHeatmap],
  )

  const applyDeparture = useCallback(
    (iso: string) => {
      // keep the same demo storm so the suggestion and the re-plan see identical weather
      if (lastRequest) submit({ ...lastRequest, departure_time: iso, storm: plan?.weather.storm ?? null })
    },
    [lastRequest, plan, submit],
  )

  // Smooth playback: advance fractional hours every animation frame (frames cross-fade).
  const hourRef = useRef(hour)
  hourRef.current = hour
  useEffect(() => {
    if (!playing || !heatmap) return
    const maxHour = heatmap.hours - 1
    let h = hourRef.current
    let last = performance.now()
    let raf = 0
    const tick = (now: number) => {
      h = Math.min(maxHour, h + ((now - last) / 1000) * PLAY_SPEED_H_PER_S)
      last = now
      setHour(h)
      if (h >= maxHour) setPlaying(false)
      else raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [playing, heatmap])

  const selectRoute = useCallback((id: string) => {
    setSelectedRouteId(id)
    setSelectedCheckpoint((cp) => (cp && cp.routeId !== id ? null : cp))
  }, [])

  const selectCheckpoint = useCallback((ref: CheckpointRef | null) => {
    setSelectedCheckpoint(ref)
    if (ref) {
      setSelectedRouteId(ref.routeId)
      setTab('checkpoints')
    }
  }, [])

  const truckMiles = useMemo(() => {
    const out: Record<string, number | null> = {}
    if (!plan || !heatmap) return out
    const offset = (Date.parse(heatmap.start) + hour * 3600_000 - Date.parse(plan.request.departure)) / 1000
    for (const r of plan.routes) out[r.id] = truckAt(r, offset).miles
    return out
  }, [plan, heatmap, hour])

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <div className="logo" aria-hidden>
            <span />
            <span />
            <span />
          </div>
          <div className="brand-text">
            <h1>Weather-Aware Truck Routing</h1>
            <p>Safest route by forecast at every checkpoint's ETA</p>
          </div>
        </div>

        {plan && (
          <div className="trip-bar" aria-label="Current trip">
            <span className="trip-route" title={`${plan.request.origin.label} → ${plan.request.destination.label}`}>
              <span className="dot start" />
              <span className="place">{plan.request.origin.label}</span>
              <span className="arrow" aria-hidden>
                →
              </span>
              <span className="dot end" />
              <span className="place">{plan.request.destination.label}</span>
            </span>
            <span className="trip-chips">
              <span>{fmtDateTime(plan.request.departure)}</span>
              <span>{Math.round(plan.request.load_lb).toLocaleString()} lb</span>
              <span>every {plan.request.interval_mi} mi</span>
              {plan.request.hos && <span>HOS breaks</span>}
              {plan.weather.scenario === 'storm' && <span className="storm-chip">Demo storm</span>}
            </span>
          </div>
        )}

        {plan && !formOpen && (
          <button type="button" className="topbar-action" onClick={() => setFormOpen(true)}>
            Edit trip
          </button>
        )}
      </header>

      <aside className="panel">
        <div className="panel-body">
          {!(plan && !formOpen) && (
            <TripForm
              key={lastRequest ? lastRequest.departure_time : 'new'}
              loading={planLoading}
              onSubmit={submit}
              initial={lastRequest}
              onCancel={plan ? () => setFormOpen(false) : undefined}
            />
          )}

          {planError && (
            <div className="error" role="alert">
              {planError}
            </div>
          )}

          {planLoading && !plan && <LoadingHint />}

          {plan && selectedRouteId && !formOpen && (
            <RoutePanel
              tab={tab}
              onTab={setTab}
              plan={plan}
              selectedRouteId={selectedRouteId}
              onSelectRoute={selectRoute}
              selectedCheckpoint={selectedCheckpoint}
              onSelectCheckpoint={selectCheckpoint}
              truckMiles={truckMiles}
              onApplyDeparture={applyDeparture}
              planning={planLoading}
            />
          )}

          {!plan && !planLoading && <Intro />}

          <footer className="credits">
            Routing: Valhalla (truck) / OSRM · Weather: Open-Meteo / MET Norway · Places: Photon / Open-Meteo · Map: OpenFreeMap, © OpenStreetMap
            contributors
          </footer>
        </div>
      </aside>

      <main className="map-area">
        <MapView
          plan={plan}
          heatmap={heatmap}
          frames={frames}
          hour={hour}
          heatOpacity={heatOpacity}
          heatVisible={heatVisible}
          selectedRouteId={selectedRouteId}
          onSelectRoute={selectRoute}
          selectedCheckpoint={selectedCheckpoint}
          onSelectCheckpoint={selectCheckpoint}
        />
        {planLoading && (
          <div className="map-busy" role="status">
            <span className="spinner" /> Finding routes and sampling forecasts…
          </div>
        )}
        {plan && (
          <TimeControl
            plan={plan}
            heatmap={heatmap}
            heatLoading={heatLoading}
            heatError={heatError}
            framesReady={!!frames}
            hour={hour}
            onHour={setHour}
            playing={playing}
            onPlay={setPlaying}
            metric={metric}
            onMetric={setMetric}
            opacity={heatOpacity}
            onOpacity={setHeatOpacity}
            visible={heatVisible}
            onVisible={setHeatVisible}
            onRetry={() => loadHeatmap(plan)}
          />
        )}
      </main>
    </div>
  )
}

function LoadingHint() {
  return (
    <div className="loading-cards" aria-hidden>
      {[0, 1, 2].map((i) => (
        <div key={i} className="skeleton" />
      ))}
    </div>
  )
}

function Intro() {
  return (
    <section className="card intro">
      <div className="section-label">How it works</div>
      <ol className="steps">
        <li>
          <strong>Three truck routes</strong> are generated between your origin and destination.
        </li>
        <li>
          <strong>Every 10, 25 or 50 miles</strong>, weather is the forecast for the moment the truck arrives, including rest stops.
        </li>
        <li>
          <strong>Wind, rain and snow</strong> are classified with the risk table; wind is escalated for heavy loads.
        </li>
        <li>
          <strong>Routes are ranked</strong> by No Travel, Severe and High miles, then average risk, then travel time.
        </li>
      </ol>
      <div className="intro-legend">
        {RISK_LEVELS.map((l) => (
          <span key={l.key} style={{ ['--c' as string]: l.color }}>
            <i /> {l.label}
          </span>
        ))}
      </div>

      <div className="section-label extras-label">
        Extras <ExtraBadge />
      </div>
      <ul className="extras">
        <li>
          <IconCalendar size={15} />
          <span>
            <strong>Best departure time.</strong> The same ranking is re-run for departures over the next 24 hours, and a later
            start is suggested when it avoids No Travel, Severe or High miles.
          </span>
        </li>
        <li>
          <IconWind size={15} />
          <span>
            <strong>Crosswind.</strong> Wind across the trailer at each checkpoint, from the forecast wind direction and the
            truck's heading. Shown for information only.
          </span>
        </li>
        <li>
          <IconTruck size={15} />
          <span>
            <strong>Live trucks on the timeline.</strong> Each route's truck moves with the forecast slider, parked during
            rest stops.
          </span>
        </li>
      </ul>
      <p className="fineprint">Extras never change risk levels or the ranking defined by the brief.</p>
    </section>
  )
}
