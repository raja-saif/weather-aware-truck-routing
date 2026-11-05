export type RiskKey = 'low' | 'moderate' | 'high' | 'severe' | 'no_travel'
export type Condition = 'wind' | 'rain' | 'snow'

export interface PlaceInputValue {
  label: string
  lat?: number
  lon?: number
}

export interface Suggestion {
  label: string
  lat: number
  lon: number
  kind: string | null
}

export interface Weather {
  wind_mph: number
  gust_mph: number | null
  rain_in_hr: number
  snow_in_hr: number
  temperature_f: number | null
  weather_code: number | null
}

export interface Risk {
  level: RiskKey
  score: number
  label: string
  by_condition: Record<Condition, RiskKey>
  drivers: Condition[]
  load_rule: string | null
}

export interface Checkpoint {
  index: number
  miles: number
  lat: number
  lon: number
  offset_s: number
  eta: string
  coverage_mi: number
  weather: Weather
  risk: Risk
}

export interface Stop {
  kind: 'break' | 'rest'
  lat: number
  lon: number
  miles: number
  start_offset_s: number
  duration_s: number
}

export interface RouteGeometry {
  coords: [number, number][] // [lon, lat]
  t: number[] // seconds after departure at each vertex
  mi: number[]
}

export interface RouteSummary {
  miles_by_level: Record<RiskKey, number>
  no_travel_miles: number
  severe_miles: number
  high_miles: number
  avg_risk: number
  max_level: RiskKey
  worst_checkpoint: number
  checkpoint_count: number
}

export interface Route {
  id: string
  name: string
  provider: string
  distance_mi: number
  drive_s: number
  trip_s: number
  arrival: string
  rank: number
  recommended: boolean
  summary: RouteSummary
  geometry: RouteGeometry
  stops: Stop[]
  checkpoints: Checkpoint[]
}

export interface Recommendation {
  route_id: string
  ranking: string[]
  comparisons: { route_id: string; decided_by: string | null; reason: string }[]
  warnings: string[]
  criteria: string[]
}

export interface PlanResponse {
  request: {
    origin: { label: string; lat: number; lon: number }
    destination: { label: string; lat: number; lon: number }
    departure: string
    load_lb: number
    interval_mi: number
    hos: boolean
  }
  routes: Route[]
  recommendation: Recommendation
  notes: string[]
  weather: {
    source: string
    lattice_deg: number
    locations: number
    window_start: string
    window_end: string
  }
  timing_ms: { routing: number; weather: number; total: number }
}

export type HeatMetric = 'risk' | 'wind' | 'rain' | 'snow'

export interface HeatmapResponse {
  start: string
  step_s: number
  hours: number
  load_lb: number
  grid: {
    lats: number[]
    lons: number[]
    step_deg: number
    cells: [number, number][]
    corners: [number, number][]
  }
  frames: Record<HeatMetric, number[][]>
}

export interface PlanRequest {
  origin: PlaceInputValue
  destination: PlaceInputValue
  departure_time: string
  load_weight_lb: number
  interval_miles: 10 | 25 | 50
  hos_breaks: boolean
}
