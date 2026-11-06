import type { HeatmapResponse, PlanRequest, PlanResponse, Route, Storm, Suggestion } from './types'

const BASE = import.meta.env.VITE_API_BASE ?? '/api'

export class ApiError extends Error {
  code: string
  fields?: Record<string, unknown>
  constructor(message: string, code: string, fields?: Record<string, unknown>) {
    super(message)
    this.code = code
    this.fields = fields
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let resp: Response
  try {
    resp = await fetch(`${BASE}${path}`, {
      ...init,
      headers: { 'Content-Type': 'application/json', ...(init.headers ?? {}) },
    })
  } catch (err) {
    if ((err as Error).name === 'AbortError') throw err
    throw new ApiError('Cannot reach the server. Check your connection and try again.', 'network')
  }
  const body = await resp.json().catch(() => null)
  if (!resp.ok) {
    const e = body?.error
    throw new ApiError(fieldMessage(e) ?? e?.message ?? `Request failed (${resp.status})`, e?.code ?? 'http', e?.fields)
  }
  return body as T
}

/** Turn DRF field errors into one readable sentence. */
function fieldMessage(e: { fields?: Record<string, unknown> } | undefined): string | null {
  if (!e?.fields) return null
  const names: Record<string, string> = {
    origin: 'Origin',
    destination: 'Destination',
    departure_time: 'Departure',
    load_weight_lb: 'Load weight',
    interval_miles: 'Sampling interval',
  }
  const parts = Object.entries(e.fields).map(([k, v]) => {
    const msg = flatten(v)[0] ?? 'is invalid'
    return `${names[k] ?? k}: ${msg}`
  })
  return parts.length ? parts.join(' ') : null
}

function flatten(v: unknown): string[] {
  if (typeof v === 'string') return [v]
  if (Array.isArray(v)) return v.flatMap(flatten)
  if (v && typeof v === 'object') return Object.values(v).flatMap(flatten)
  return []
}

export function searchPlaces(q: string, signal?: AbortSignal): Promise<{ results: Suggestion[] }> {
  return request(`/geocode?q=${encodeURIComponent(q)}&limit=6`, { signal })
}

export function planTrip(body: PlanRequest, signal?: AbortSignal): Promise<PlanResponse> {
  return request('/plan', { method: 'POST', body: JSON.stringify(body), signal })
}

export function fetchHeatmap(
  departure: string,
  loadLb: number,
  routes: Route[],
  storm: Storm | null,
  signal?: AbortSignal,
): Promise<HeatmapResponse> {
  return request('/heatmap', {
    method: 'POST',
    body: JSON.stringify({
      departure_time: departure,
      load_weight_lb: loadLb,
      routes: routes.map((r) => r.geometry.coords),
      storm,
    }),
    signal,
  })
}
