import type { Checkpoint, Route } from '../api/types'

export type TruckStatus = 'not_departed' | 'driving' | 'break' | 'rest' | 'arrived'

export interface TruckState {
  lon: number
  lat: number
  miles: number
  status: TruckStatus
}

/** Largest index i with arr[i] <= x (arr ascending). */
export function upperIndex(arr: number[], x: number): number {
  let lo = 0
  let hi = arr.length - 1
  if (x < arr[0]) return -1
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1
    if (arr[mid] <= x) lo = mid
    else hi = mid - 1
  }
  return lo
}

/** Where the truck is ``offsetS`` seconds after departure. */
export function truckAt(route: Route, offsetS: number): TruckState {
  const { coords, t, mi } = route.geometry
  const last = coords.length - 1
  if (offsetS <= 0) return { lon: coords[0][0], lat: coords[0][1], miles: 0, status: offsetS < 0 ? 'not_departed' : 'driving' }
  if (offsetS >= t[last]) return { lon: coords[last][0], lat: coords[last][1], miles: mi[last], status: 'arrived' }
  const i = upperIndex(t, offsetS)
  const span = t[i + 1] - t[i]
  const f = span > 0 ? (offsetS - t[i]) / span : 0
  const stop = route.stops.find((s) => offsetS >= s.start_offset_s && offsetS < s.start_offset_s + s.duration_s)
  return {
    lon: coords[i][0] + (coords[i + 1][0] - coords[i][0]) * f,
    lat: coords[i][1] + (coords[i + 1][1] - coords[i][1]) * f,
    miles: mi[i] + (mi[i + 1] - mi[i]) * f,
    status: stop ? stop.kind : 'driving',
  }
}

/** Checkpoint whose coverage contains ``miles`` (nearest checkpoint). */
export function checkpointAtMiles(route: Route, miles: number): Checkpoint {
  const cps = route.checkpoints
  let best = cps[0]
  for (const cp of cps) {
    if (Math.abs(cp.miles - miles) < Math.abs(best.miles - miles)) best = cp
  }
  return best
}
