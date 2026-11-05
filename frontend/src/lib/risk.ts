import type { HeatMetric, RiskKey } from '../api/types'

export const RISK_LEVELS: { key: RiskKey; label: string; color: string }[] = [
  { key: 'low', label: 'Low', color: '#2f9e5b' },
  { key: 'moderate', label: 'Moderate', color: '#e2b822' },
  { key: 'high', label: 'High', color: '#f07c1b' },
  { key: 'severe', label: 'Severe', color: '#d42a1c' },
  { key: 'no_travel', label: 'No Travel', color: '#5a0b2e' },
]

export const RISK_COLOR: Record<RiskKey, string> = Object.fromEntries(
  RISK_LEVELS.map((l) => [l.key, l.color]),
) as Record<RiskKey, string>

export const RISK_LABEL: Record<RiskKey, string> = Object.fromEntries(
  RISK_LEVELS.map((l) => [l.key, l.label]),
) as Record<RiskKey, string>

export const ROUTE_COLORS: Record<string, string> = { A: '#2563eb', B: '#9333ea', C: '#0f8a8a' }

/**
 * Heatmap metrics. Raw conditions are mapped onto the same 0-4 "risk position"
 * scale as the risk table (piecewise-linear between the spec's thresholds), so
 * every metric shares one color ramp and the colors mean the same thing.
 */
export interface MetricDef {
  key: HeatMetric
  label: string
  unit: string
  /** values at risk positions 0..4 (Low start, Moderate, High, Severe, No Travel) */
  stops: [number, number, number, number, number]
  /** below this value nothing is drawn (keeps calm/dry areas clear) */
  floor: number
  legend: string[]
}

export const METRICS: Record<HeatMetric, MetricDef> = {
  risk: {
    key: 'risk',
    label: 'Risk',
    unit: '',
    stops: [0, 1, 2, 3, 4],
    floor: -1,
    legend: RISK_LEVELS.map((l) => l.label),
  },
  wind: {
    key: 'wind',
    label: 'Wind',
    unit: 'mph',
    stops: [12, 25, 35, 45, 55],
    floor: 12,
    legend: ['<25', '25', '35', '45', '55+'],
  },
  rain: {
    key: 'rain',
    label: 'Rain',
    unit: 'in/hr',
    stops: [0.01, 0.1, 0.25, 0.5, 1.0],
    floor: 0.005,
    legend: ['<0.10', '0.10', '0.25', '0.50', '>1.00'],
  },
  snow: {
    key: 'snow',
    label: 'Snow',
    unit: 'in/hr',
    stops: [0.02, 0.5, 1.0, 2.0, 3.0],
    floor: 0.01,
    legend: ['<0.5', '0.5', '1.0', '2.0', '>3.0'],
  },
}

/** Continuous 0..4 position of ``value`` on the metric's threshold scale, or NaN below the floor. */
export function riskPosition(metric: MetricDef, value: number): number {
  if (metric.key === 'risk') return value
  if (!(value >= metric.floor)) return Number.NaN
  const s = metric.stops
  if (value <= s[0]) return 0
  for (let i = 1; i < s.length; i++) {
    if (value < s[i]) return i - 1 + (value - s[i - 1]) / (s[i] - s[i - 1])
  }
  return 4
}

export function hexToRgb(hex: string): [number, number, number] {
  const n = parseInt(hex.slice(1), 16)
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}
