import { memo, useState } from 'react'
import type { PlanResponse, Route } from '../api/types'
import { fmtDateTime, fmtDuration, fmtMiles, fmtTime } from '../lib/format'
import { RISK_COLOR, RISK_LABEL, RISK_LEVELS, ROUTE_COLORS } from '../lib/risk'
import { IconAlert, IconCheck, IconClock, IconFlag, IconInfo, IconRoute } from './Icons'
import type { CheckpointRef } from './MapView'
import RiskProfile from './RiskProfile'

export type PanelTab = 'routes' | 'checkpoints'

interface Props {
  plan: PlanResponse
  tab: PanelTab
  onTab: (tab: PanelTab) => void
  selectedRouteId: string
  onSelectRoute: (id: string) => void
  selectedCheckpoint: CheckpointRef | null
  onSelectCheckpoint: (ref: CheckpointRef | null) => void
  truckMiles: Record<string, number | null>
}

export default function RoutePanel(props: Props) {
  const { plan, tab, onTab, selectedRouteId, onSelectRoute } = props
  const rec = plan.recommendation
  const best = plan.routes.find((r) => r.id === rec.route_id)!
  const ordered = rec.ranking.map((id) => plan.routes.find((r) => r.id === id)!)
  const selected = plan.routes.find((r) => r.id === selectedRouteId) ?? best
  const riskyCount = selected.checkpoints.filter((c) => c.risk.score > 0).length

  const tabs: { id: PanelTab; label: React.ReactNode }[] = [
    { id: 'routes', label: 'Routes' },
    {
      id: 'checkpoints',
      label: (
        <>
          Checkpoints
          <span className="tab-count" title={`Route ${selected.id}: checkpoints above Low`}>
            {riskyCount}
          </span>
        </>
      ),
    },
  ]

  return (
    <div className="results">
      <div className="tabs" role="tablist" aria-label="Trip results">
        {tabs.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            id={`tab-${t.id}`}
            aria-selected={tab === t.id}
            aria-controls="results-panel"
            className={tab === t.id ? 'on' : ''}
            onClick={() => onTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div className="tab-body" role="tabpanel" id="results-panel" aria-labelledby={`tab-${tab}`}>
        {tab === 'routes' && (
          <>
            <Recommendation plan={plan} />
            <div className="section-label">Route options</div>
            <div className="route-cards" role="list">
              {ordered.map((r) => (
                <RouteCard key={r.id} route={r} selected={r.id === selected.id} onSelect={onSelectRoute} />
              ))}
            </div>
            <button type="button" className="secondary view-cps" onClick={() => onTab('checkpoints')}>
              View checkpoints for Route {selected.id} →
            </button>
          </>
        )}

        {tab === 'checkpoints' && (
          <>
            <div className="route-switch" role="radiogroup" aria-label="Route">
              {ordered.map((r) => (
                <button
                  key={r.id}
                  type="button"
                  role="radio"
                  aria-checked={r.id === selected.id}
                  className={r.id === selected.id ? 'on' : ''}
                  style={{ ['--route' as string]: ROUTE_COLORS[r.id] }}
                  onClick={() => onSelectRoute(r.id)}
                >
                  <span className="route-id">{r.id}</span>
                  <span>
                    {r.recommended ? '★ ' : ''}
                    {fmtMiles(r.distance_mi)}
                  </span>
                </button>
              ))}
            </div>
            <RouteDetail {...props} route={selected} />
          </>
        )}

      </div>
    </div>
  )
}

function Recommendation({ plan }: { plan: PlanResponse }) {
  const rec = plan.recommendation
  const best = plan.routes.find((r) => r.id === rec.route_id)!
  return (
    <section className="card recommendation" style={{ ['--route' as string]: ROUTE_COLORS[best.id] }}>
      <div className="eyebrow">Recommended route</div>
      <div className="rec-head">
        <span className="route-id lg">{best.id}</span>
        <div>
          <div className="rec-name">{best.name}</div>
          <div className="rec-sub">
            {fmtMiles(best.distance_mi)} · {fmtDuration(best.trip_s)} · arrives {fmtDateTime(best.arrival)}
          </div>
        </div>
      </div>
      <ul className="rec-reasons">
        {rec.comparisons.map((c) => (
          <li key={c.route_id}>
            <IconCheck size={14} />
            <span>{c.reason}</span>
          </li>
        ))}
      </ul>
      {rec.warnings.map((w) => (
        <div key={w} className="warning" role="alert">
          <IconAlert size={15} />
          <span>{w}</span>
        </div>
      ))}
      {plan.notes.map((n) => (
        <div key={n} className="note">
          <IconInfo size={14} />
          <span>{n}</span>
        </div>
      ))}
      <details className="criteria">
        <summary>How routes are ranked</summary>
        <ol>
          <li>Fewest No Travel miles (stricter than Severe)</li>
          <li>Fewest Severe miles</li>
          <li>Fewest High miles</li>
          <li>Lowest average risk (ties within 0.05)</li>
          <li>Shortest travel time, including rest stops</li>
        </ol>
        <p>
          Each checkpoint stands for the road halfway to its neighbours, so a route's risk miles add up to its length.
          Weather is the forecast for the hour the truck reaches each checkpoint.
        </p>
      </details>
    </section>
  )
}

const RouteCard = memo(function RouteCard({ route: r, selected, onSelect }: { route: Route; selected: boolean; onSelect: (id: string) => void }) {
  const s = r.summary
  return (
    <button
      type="button"
      role="listitem"
      className={`card route-card${selected ? ' selected' : ''}`}
      style={{ ['--route' as string]: ROUTE_COLORS[r.id] }}
      onClick={() => onSelect(r.id)}
      aria-pressed={selected}
    >
      <div className="card-head">
        <span className="route-id">{r.id}</span>
        <span className="route-name">{r.name}</span>
        {r.recommended ? <span className="pill rec">★ Recommended</span> : <span className="pill">Rank {r.rank}</span>}
      </div>
      <div className="stats">
        <Stat icon={<IconRoute size={13} />} label="Distance" value={fmtMiles(r.distance_mi)} />
        <Stat icon={<IconClock size={13} />} label="Driving" value={fmtDuration(r.drive_s)} />
        <Stat icon={<IconClock size={13} />} label="Trip" value={fmtDuration(r.trip_s)} hint="Door to door, including HOS stops" />
        <Stat icon={<IconFlag size={13} />} label="Arrive" value={fmtDateTime(r.arrival)} />
      </div>
      <RiskBar route={r} />
      <div className="risk-figures">
        <Figure label="No Travel" value={s.no_travel_miles} level="no_travel" />
        <Figure label="Severe" value={s.severe_miles} level="severe" />
        <Figure label="High" value={s.high_miles} level="high" />
        <span className="avg">
          avg risk <strong>{s.avg_risk.toFixed(2)}</strong>
        </span>
      </div>
    </button>
  )
})

function Stat({ icon, label, value, hint }: { icon: React.ReactNode; label: string; value: string; hint?: string }) {
  return (
    <div className="stat" title={hint}>
      <span className="stat-label">
        {icon}
        {label}
      </span>
      <span className="stat-value">{value}</span>
    </div>
  )
}

function Figure({ label, value, level }: { label: string; value: number; level: keyof typeof RISK_COLOR }) {
  return (
    <span className={`figure${value > 0 ? ' nonzero' : ''}`} style={{ ['--c' as string]: RISK_COLOR[level] }}>
      <i /> {Math.round(value)} mi {label}
    </span>
  )
}

function RiskBar({ route }: { route: Route }) {
  const total = route.distance_mi || 1
  return (
    <div className="risk-bar" aria-label="Miles by risk level">
      {RISK_LEVELS.map((l) => {
        const mi = route.summary.miles_by_level[l.key]
        if (mi <= 0) return null
        return <span key={l.key} style={{ width: `${(mi / total) * 100}%`, background: l.color }} title={`${l.label}: ${Math.round(mi)} mi`} />
      })}
    </div>
  )
}

function RouteDetail({ route, selectedCheckpoint, onSelectCheckpoint, truckMiles, plan }: Props & { route: Route }) {
  const [showAll, setShowAll] = useState(false)
  const cps = route.checkpoints
  const risky = cps.filter((c) => c.risk.score > 0)
  const rows = showAll ? cps : risky
  const dep = Date.parse(plan.request.departure)
  return (
    <section className="card route-detail" style={{ ['--route' as string]: ROUTE_COLORS[route.id] }}>
      <div className="card-title">
        <span className="route-id">{route.id}</span>
        <h2>Risk along {route.name}</h2>
      </div>
      <RiskProfile
        route={route}
        truckMiles={truckMiles[route.id] ?? null}
        selectedIndex={selectedCheckpoint?.routeId === route.id ? selectedCheckpoint.index : null}
        onSelect={(index) => onSelectCheckpoint({ routeId: route.id, index })}
      />
      {route.stops.length > 0 && (
        <div className="stops">
          {route.stops.map((st, i) => (
            <span key={i} className="stop">
              {st.kind === 'rest' ? '10 h rest' : '30 min break'} · mile {Math.round(st.miles)} · {fmtDateTime(dep + st.start_offset_s * 1000)}
            </span>
          ))}
        </div>
      )}

      <div className="table-head">
        <span>
          {cps.length} checkpoints every {plan.request.interval_mi} mi · {risky.length} above Low
        </span>
        <button type="button" className="link" onClick={() => setShowAll((v) => !v)}>
          {showAll ? 'Show risky only' : 'Show all'}
        </button>
      </div>
      {rows.length === 0 ? (
        <p className="all-clear">
          <IconCheck size={14} /> All checkpoints are Low risk at their ETAs.
        </p>
      ) : (
        <div className="table-wrap">
          <table className="cp-table">
            <thead>
              <tr>
                <th>Mile</th>
                <th>ETA</th>
                <th>Risk</th>
                <th title="Sustained wind (mph)">Wind</th>
                <th title="Rain (in/hr)">Rain</th>
                <th title="Snow (in/hr)">Snow</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((c) => (
                <tr
                  key={c.index}
                  className={selectedCheckpoint?.routeId === route.id && selectedCheckpoint.index === c.index ? 'active' : ''}
                  onClick={() => onSelectCheckpoint({ routeId: route.id, index: c.index })}
                >
                  <td>{Math.round(c.miles)}</td>
                  <td title={fmtDateTime(c.eta)}>{fmtTime(c.eta)}</td>
                  <td>
                    <span className="badge" style={{ ['--c' as string]: RISK_COLOR[c.risk.level] }}>{RISK_LABEL[c.risk.level]}</span>
                  </td>
                  <td className={c.risk.by_condition.wind !== 'low' ? 'hot' : ''}>{c.weather.wind_mph.toFixed(0)}</td>
                  <td className={c.risk.by_condition.rain !== 'low' ? 'hot' : ''}>{c.weather.rain_in_hr.toFixed(2)}</td>
                  <td className={c.risk.by_condition.snow !== 'low' ? 'hot' : ''}>{c.weather.snow_in_hr.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
