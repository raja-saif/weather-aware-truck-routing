import type { HeatMetric, HeatmapResponse, PlanResponse } from '../api/types'
import { fmtDateTime } from '../lib/format'
import { METRICS, RISK_LEVELS, ROUTE_COLORS } from '../lib/risk'
import { truckAt, type TruckStatus } from '../lib/timeline'

interface Props {
  plan: PlanResponse
  heatmap: HeatmapResponse | null
  heatLoading: boolean
  heatError: string | null
  framesReady: boolean
  hour: number
  onHour: (h: number) => void
  playing: boolean
  onPlay: (p: boolean) => void
  metric: HeatMetric
  onMetric: (m: HeatMetric) => void
  opacity: number
  onOpacity: (o: number) => void
  visible: boolean
  onVisible: (v: boolean) => void
  onRetry: () => void
}

const STATUS: Record<TruckStatus, string> = {
  not_departed: 'not departed',
  driving: 'driving',
  break: '30-min break',
  rest: '10-h rest',
  arrived: 'arrived',
}

export default function TimeControl(p: Props) {
  const maxHour = (p.heatmap?.hours ?? 49) - 1
  const startMs = p.heatmap ? Date.parse(p.heatmap.start) : Date.parse(p.plan.request.departure)
  const at = startMs + p.hour * 3600_000
  const offset = (at - Date.parse(p.plan.request.departure)) / 1000
  const metric = METRICS[p.metric]

  return (
    <div className="time-control" aria-label="Forecast time">
      <div className="tc-row">
        <button
          type="button"
          className="play"
          disabled={!p.framesReady}
          onClick={() => {
            if (!p.playing && p.hour >= maxHour) p.onHour(0)
            p.onPlay(!p.playing)
          }}
          aria-label={p.playing ? 'Pause forecast animation' : 'Play forecast animation'}
        >
          {p.playing ? '❚❚' : '▶'}
        </button>
        <div className="tc-slider">
          <div className="tc-time">
            <strong>+{Math.floor(p.hour)} h</strong> <span>{fmtDateTime(at)}</span>
            {p.heatLoading && <span className="muted"> · loading forecast…</span>}
            {!p.heatLoading && p.heatmap && !p.framesReady && <span className="muted"> · rendering…</span>}
            {p.heatError && (
              <span className="error-inline">
                {' '}· {p.heatError}{' '}
                <button type="button" className="link" onClick={p.onRetry}>Retry</button>
              </span>
            )}
          </div>
          <input
            type="range"
            min={0}
            max={maxHour}
            step={1}
            value={Math.floor(p.hour)}
            disabled={!p.heatmap}
            onChange={(e) => {
              p.onPlay(false)
              p.onHour(Number(e.target.value))
            }}
            aria-label="Hours after departure"
            aria-valuetext={`${Math.floor(p.hour)} hours after departure, ${fmtDateTime(at)}`}
          />
          <div className="ticks" aria-hidden>
            {[0, 12, 24, 36, 48].map((t) => (
              <span key={t} style={{ left: `${(t / maxHour) * 100}%` }}>{t}h</span>
            ))}
          </div>
        </div>
      </div>
      <div className="tc-row tc-options">
        <div className="segmented small" role="radiogroup" aria-label="Heatmap layer">
          {(Object.keys(METRICS) as HeatMetric[]).map((m) => (
            <button key={m} type="button" role="radio" aria-checked={p.metric === m} className={p.metric === m ? 'on' : ''} onClick={() => p.onMetric(m)}>
              {METRICS[m].label}
            </button>
          ))}
        </div>
        <label className="toggle small">
          <input type="checkbox" checked={p.visible} onChange={(e) => p.onVisible(e.target.checked)} />
          <span>Heatmap</span>
        </label>
        <input
          className="opacity"
          type="range"
          min={0.2}
          max={1}
          step={0.05}
          value={p.opacity}
          onChange={(e) => p.onOpacity(Number(e.target.value))}
          aria-label="Heatmap opacity"
          title="Heatmap opacity"
        />
        <div className="legend" aria-label={`${metric.label} legend`}>
          {RISK_LEVELS.map((l, i) => (
            <span key={l.key} style={{ ['--c' as string]: l.color }}>
              <i />
              {metric.legend[i]}
            </span>
          ))}
          {metric.unit && <span className="muted">{metric.unit}</span>}
        </div>
      </div>
      <div className="tc-row trucks">
        {p.plan.routes.map((r) => {
          const s = truckAt(r, offset)
          return (
            <span key={r.id} className="truck" style={{ ['--route' as string]: ROUTE_COLORS[r.id] }}>
              <i>{r.id}</i> {s.status === 'arrived' ? 'arrived' : `mile ${Math.round(s.miles)} · ${STATUS[s.status]}`}
            </span>
          )
        })}
      </div>
    </div>
  )
}
