import { useState } from 'react'
import type { Route } from '../api/types'
import { fmtDateTime } from '../lib/format'
import { RISK_COLOR, RISK_LABEL } from '../lib/risk'

interface Props {
  route: Route
  truckMiles: number | null
  selectedIndex: number | null
  onSelect: (index: number) => void
}

const H = 34

/**
 * Risk strip along the route: each checkpoint's covered stretch, colored by its
 * level and drawn taller for higher risk. Hover for details, click to focus it on the map.
 */
export default function RiskProfile({ route, truckMiles, selectedIndex, onSelect }: Props) {
  const [hover, setHover] = useState<number | null>(null)
  const total = route.distance_mi || 1
  const cps = route.checkpoints
  const x = (mi: number) => (mi / total) * 100
  const shown = hover ?? selectedIndex
  const cp = shown != null ? cps[shown] : null

  return (
    <div className="profile">
      <svg viewBox={`0 0 100 ${H}`} preserveAspectRatio="none" role="img" aria-label={`Risk profile of ${route.name}`} onMouseLeave={() => setHover(null)}>
        {cps.map((c, i) => {
          const lo = i === 0 ? 0 : (cps[i - 1].miles + c.miles) / 2
          const hi = i === cps.length - 1 ? total : (c.miles + cps[i + 1].miles) / 2
          const h = 8 + c.risk.score * 6.5
          return (
            <rect
              key={i}
              x={x(lo)}
              width={Math.max(x(hi) - x(lo), 0.15)}
              y={H - h}
              height={h}
              fill={RISK_COLOR[c.risk.level]}
              opacity={shown == null || shown === i ? 1 : 0.55}
              onMouseEnter={() => setHover(i)}
              onClick={() => onSelect(i)}
            />
          )
        })}
        {route.stops.map((s, i) => (
          <line key={`s${i}`} x1={x(s.miles)} x2={x(s.miles)} y1={0} y2={H} className="profile-stop" vectorEffect="non-scaling-stroke" />
        ))}
        {truckMiles != null && (
          <line x1={x(truckMiles)} x2={x(truckMiles)} y1={0} y2={H} className="profile-truck" vectorEffect="non-scaling-stroke" />
        )}
      </svg>
      <div className="profile-axis">
        <span>0</span>
        <span>{Math.round(total / 2).toLocaleString()}</span>
        <span>{Math.round(total).toLocaleString()} mi</span>
      </div>
      <div className="profile-readout" aria-live="polite">
        {cp ? (
          <>
            <strong>Mile {Math.round(cp.miles)}</strong> · {fmtDateTime(cp.eta)} ·{' '}
            <span style={{ color: RISK_COLOR[cp.risk.level], fontWeight: 600 }}>{RISK_LABEL[cp.risk.level]}</span>
            {cp.risk.drivers.length > 0 && <> ({cp.risk.drivers.join(', ')})</>} · wind {cp.weather.wind_mph.toFixed(0)} mph, rain{' '}
            {cp.weather.rain_in_hr.toFixed(2)}, snow {cp.weather.snow_in_hr.toFixed(2)} in/hr
          </>
        ) : (
          <span className="muted">Hover the strip to inspect checkpoints. Dark ticks mark HOS stops, the blue line is the truck at the slider time.</span>
        )}
      </div>
    </div>
  )
}
