import { useState } from 'react'
import type { PlaceInputValue, PlanRequest, Scenario } from '../api/types'
import { localTzName, nextQuarterHour, toLocalInput } from '../lib/format'
import PlaceInput from './PlaceInput'

interface Props {
  loading: boolean
  onSubmit: (req: PlanRequest) => void
  /** Previous request, so "Edit trip" reopens the form with the same values. */
  initial?: PlanRequest | null
  onCancel?: () => void
}

const LOAD_PRESETS = [
  { lb: 18_000, label: '18k' },
  { lb: 35_000, label: '35k' },
  { lb: 45_000, label: '45k' },
]

const EXAMPLES: { label: string; origin: PlaceInputValue; destination: PlaceInputValue }[] = [
  {
    label: 'Chicago → Denver',
    origin: { label: 'Chicago, Illinois', lat: 41.8756, lon: -87.6244 },
    destination: { label: 'Denver, Colorado', lat: 39.7392, lon: -104.9849 },
  },
  {
    label: 'Dallas → Atlanta',
    origin: { label: 'Dallas, Texas', lat: 32.7763, lon: -96.7969 },
    destination: { label: 'Atlanta, Georgia', lat: 33.749, lon: -84.3902 },
  },
  {
    label: 'Seattle → Salt Lake City',
    origin: { label: 'Seattle, Washington', lat: 47.6038, lon: -122.3301 },
    destination: { label: 'Salt Lake City, Utah', lat: 40.7596, lon: -111.8868 },
  },
]

function initialDeparture(initial?: PlanRequest | null): string {
  const d = initial ? new Date(initial.departure_time) : null
  return toLocalInput(d && d.getTime() > Date.now() ? d : nextQuarterHour())
}

export default function TripForm({ loading, onSubmit, initial, onCancel }: Props) {
  const [origin, setOrigin] = useState<PlaceInputValue>(initial?.origin ?? { label: '' })
  const [destination, setDestination] = useState<PlaceInputValue>(initial?.destination ?? { label: '' })
  const [departure, setDeparture] = useState(() => initialDeparture(initial))
  const [load, setLoad] = useState(String(initial?.load_weight_lb ?? 42000))
  const [interval, setIntervalMi] = useState<10 | 25 | 50>(initial?.interval_miles ?? 25)
  const [hos, setHos] = useState(initial?.hos_breaks ?? true)
  const [scenario, setScenario] = useState<Scenario>(initial?.scenario ?? 'live')
  const [error, setError] = useState<string | null>(null)

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    const loadLb = Number(load)
    if (!origin.label.trim() || !destination.label.trim()) return setError('Enter an origin and a destination.')
    if (!departure) return setError('Choose a departure date and time.')
    if (!Number.isFinite(loadLb) || loadLb < 0 || loadLb > 120_000) return setError('Load weight must be between 0 and 120,000 lb.')
    setError(null)
    onSubmit({
      origin,
      destination,
      departure_time: new Date(departure).toISOString(),
      load_weight_lb: loadLb,
      interval_miles: interval,
      hos_breaks: hos,
      scenario,
    })
  }

  return (
    <form className="card trip-form" onSubmit={submit} noValidate>
      <div className="card-title">
        <h2>Plan a trip</h2>
        {onCancel && (
          <button type="button" className="link" onClick={onCancel}>
            Cancel
          </button>
        )}
      </div>

      <div className="places">
        <PlaceInput label="Origin" placeholder="City, address or lat, lon" value={origin} onChange={setOrigin} marker="start" />
        <button
          type="button"
          className="swap"
          title="Swap origin and destination"
          aria-label="Swap origin and destination"
          onClick={() => {
            setOrigin(destination)
            setDestination(origin)
          }}
        >
          ⇅
        </button>
        <PlaceInput label="Destination" placeholder="City, address or lat, lon" value={destination} onChange={setDestination} marker="end" />
      </div>
      <div className="examples">
        <span>Try</span>
        {EXAMPLES.map((ex) => (
          <button
            key={ex.label}
            type="button"
            className="chip"
            onClick={() => {
              setOrigin(ex.origin)
              setDestination(ex.destination)
            }}
          >
            {ex.label}
          </button>
        ))}
      </div>

      <div className="field">
        <label htmlFor="departure">
          Departure <span className="muted">({localTzName})</span>
        </label>
        <input id="departure" type="datetime-local" value={departure} onChange={(e) => setDeparture(e.target.value)} />
      </div>

      <div className="row">
        <div className="field">
          <label htmlFor="load">Load weight</label>
          <div className="suffix-input">
            <input id="load" type="number" inputMode="numeric" min={0} max={120000} step={500} value={load} onChange={(e) => setLoad(e.target.value)} />
            <span>lb</span>
          </div>
          <div className="presets" aria-label="Load presets">
            {LOAD_PRESETS.map((p) => (
              <button key={p.lb} type="button" className={`preset${Number(load) === p.lb ? ' on' : ''}`} onClick={() => setLoad(String(p.lb))}>
                {p.label}
              </button>
            ))}
          </div>
        </div>
        <div className="field">
          <span className="label" id="interval-label">Weather every</span>
          <div className="segmented" role="radiogroup" aria-labelledby="interval-label">
            {([10, 25, 50] as const).map((v) => (
              <button key={v} type="button" role="radio" aria-checked={interval === v} className={interval === v ? 'on' : ''} onClick={() => setIntervalMi(v)}>
                {v} mi
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="row">
        <div className="field">
          <span className="label" id="scenario-label">Weather</span>
          <div className="segmented" role="radiogroup" aria-labelledby="scenario-label">
            <button type="button" role="radio" aria-checked={scenario === 'live'} className={scenario === 'live' ? 'on' : ''} onClick={() => setScenario('live')}>
              Live
            </button>
            <button
              type="button"
              role="radio"
              aria-checked={scenario === 'storm'}
              className={scenario === 'storm' ? 'on' : ''}
              onClick={() => setScenario('storm')}
              title="Overlay a synthetic storm on the live forecast to demonstrate the risk rules"
            >
              Demo storm
            </button>
          </div>
        </div>
        <div className="field">
          <span className="label">Driver rest</span>
          <label className="toggle" title="FMCSA hours of service: 30-min break after 8 h driving, 10-h rest after 11 h">
            <input type="checkbox" checked={hos} onChange={(e) => setHos(e.target.checked)} />
            <span>HOS breaks</span>
          </label>
        </div>
      </div>

      {error && (
        <div className="form-error" role="alert">
          {error}
        </div>
      )}
      <button className="primary" type="submit" disabled={loading}>
        {loading ? (
          <>
            <span className="spinner" aria-hidden /> Planning routes…
          </>
        ) : (
          'Find safest route'
        )}
      </button>
    </form>
  )
}
