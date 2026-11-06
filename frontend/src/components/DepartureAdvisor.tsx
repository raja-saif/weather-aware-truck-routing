import { useState } from 'react'
import type { DepartureAdvice, DepartureOption } from '../api/types'
import { fmtDateTime } from '../lib/format'
import { RISK_COLOR } from '../lib/risk'
import { ExtraBadge, IconCalendar, IconCheck } from './Icons'

interface Props {
  advice: DepartureAdvice
  loading: boolean
  onApply: (departureIso: string) => void
}

const BAR_H = 54

/**
 * Extra feature: re-runs the same ranking for departures every 2 h over the next 24 h
 * and suggests the earliest one with the fewest No Travel, Severe and High miles.
 */
export default function DepartureAdvisor({ advice, loading, onApply }: Props) {
  const [hover, setHover] = useState<number | null>(null)
  const { options, suggestion } = advice
  const total = (o: DepartureOption) => o.no_travel_miles + o.severe_miles + o.high_miles
  const max = Math.max(1, ...options.map(total))
  const shown = hover != null ? options[hover] : null
  // nothing to compare when every departure is clear: a row of empty bars only adds noise
  const allClear = options.every((o) => total(o) === 0)

  return (
    <section className="card advisor" aria-labelledby="advisor-title">
      <div className="card-title">
        <IconCalendar />
        <h2 id="advisor-title">Best departure time</h2>
        <ExtraBadge />
      </div>

      {!allClear && (
      <div className="advisor-chart" role="img" aria-label="High, Severe and No Travel miles of the best route for each departure time">
        {options.map((o, i) => {
          const t = total(o)
          const isNow = o.shift_h === 0
          const isPick = suggestion?.shift_h === o.shift_h
          return (
            <div
              key={o.shift_h}
              className={`advisor-col${isPick ? ' pick' : ''}${isNow ? ' now' : ''}`}
              onMouseEnter={() => setHover(i)}
              onMouseLeave={() => setHover(null)}
            >
              <div className="advisor-bar" style={{ height: BAR_H }}>
                {t === 0 ? (
                  <span className="seg clear" style={{ height: 3 }} />
                ) : (
                  <>
                    <span className="seg" style={{ height: (o.high_miles / max) * BAR_H, background: RISK_COLOR.high }} />
                    <span className="seg" style={{ height: (o.severe_miles / max) * BAR_H, background: RISK_COLOR.severe }} />
                    <span className="seg" style={{ height: (o.no_travel_miles / max) * BAR_H, background: RISK_COLOR.no_travel }} />
                  </>
                )}
              </div>
              <span className="advisor-tick">{isNow ? 'now' : `+${o.shift_h}`}</span>
            </div>
          )
        })}
      </div>
      )}

      <div className="advisor-readout" aria-live="polite">
        {shown ? (
          <>
            <strong>{fmtDateTime(shown.departure)}</strong> · best is Route {shown.route_id}:{' '}
            {total(shown) === 0
              ? 'no High, Severe or No Travel miles'
              : `${Math.round(shown.no_travel_miles)} No Travel, ${Math.round(shown.severe_miles)} Severe, ${Math.round(shown.high_miles)} High mi`}
          </>
        ) : suggestion ? (
          <span className="advisor-suggestion">{suggestion.reason}</span>
        ) : (
          <span className="advisor-ok">
            <IconCheck size={14} />{' '}
            {allClear
              ? 'No High, Severe or No Travel miles for any departure in the next 24 hours. Leaving now is the safest choice.'
              : 'Leaving now is already the safest choice in the next 24 hours.'}
          </span>
        )}
      </div>

      {suggestion && (
        <button type="button" className="secondary" disabled={loading} onClick={() => onApply(suggestion.departure)}>
          Re-plan leaving {fmtDateTime(suggestion.departure)}
        </button>
      )}
      <p className="fineprint">Same rules and ranking, evaluated for later departures. Waiting counts as travel time.</p>
    </section>
  )
}
