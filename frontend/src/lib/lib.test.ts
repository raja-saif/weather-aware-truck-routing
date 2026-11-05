import { describe, expect, it } from 'vitest'
import type { HeatmapResponse, Route } from '../api/types'
import { buildLut, frameGrid, rasterize } from './heatmap'
import { METRICS, riskPosition } from './risk'
import { truckAt, upperIndex } from './timeline'
import { fmtDuration, nextQuarterHour } from './format'

describe('riskPosition', () => {
  it('maps raw values onto the threshold scale', () => {
    expect(riskPosition(METRICS.wind, 25)).toBe(1)
    expect(riskPosition(METRICS.wind, 40)).toBeCloseTo(2.5)
    expect(riskPosition(METRICS.wind, 70)).toBe(4)
    expect(riskPosition(METRICS.rain, 0.25)).toBe(2)
    expect(riskPosition(METRICS.snow, 3.0)).toBe(4)
  })
  it('hides calm/dry values below the floor', () => {
    expect(riskPosition(METRICS.rain, 0)).toBeNaN()
    expect(riskPosition(METRICS.wind, 5)).toBeNaN()
    expect(riskPosition(METRICS.risk, 0)).toBe(0)
  })
})

describe('heatmap rasterize', () => {
  const hm = {
    grid: { lats: [41, 40], lons: [-100, -99, -98], cells: [[0, 0], [0, 1], [1, 1]] },
  } as unknown as HeatmapResponse

  it('builds a dense grid with NaN outside the corridor', () => {
    const g = frameGrid(hm, [0, 4, 2], METRICS.risk)
    expect(Array.from(g.slice(0, 3))).toEqual([0, 4, NaN])
    expect(g[4]).toBe(2)
    expect(g[3]).toBeNaN()
  })

  it('produces an upsampled image, transparent outside and opaque at nodes', () => {
    const lut = buildLut()
    const img = rasterize(frameGrid(hm, [0, 4, 2], METRICS.risk), 2, 3, lut, 4)
    expect(img.width).toBe(12)
    expect(img.height).toBe(8)
    const alphaAt = (x: number, y: number) => img.data[(y * img.width + x) * 4 + 3]
    expect(alphaAt(11, 0)).toBe(0) // top-right cell is outside the corridor
    expect(alphaAt(5, 1)).toBeGreaterThan(150) // the No Travel node is strongly colored
    expect(alphaAt(1, 1)).toBeLessThan(alphaAt(5, 1)) // Low is lighter than No Travel
  })
})

function route(): Route {
  return {
    geometry: {
      coords: [[0, 0], [1, 0], [1, 0], [2, 0]],
      t: [0, 3600, 5400, 9000],
      mi: [0, 60, 60, 120],
    },
    stops: [{ kind: 'break', lat: 0, lon: 1, miles: 60, start_offset_s: 3600, duration_s: 1800 }],
  } as unknown as Route
}

describe('truckAt', () => {
  it('interpolates along the route', () => {
    const s = truckAt(route(), 1800)
    expect(s.lon).toBeCloseTo(0.5)
    expect(s.miles).toBeCloseTo(30)
    expect(s.status).toBe('driving')
  })
  it('stays parked during an HOS stop', () => {
    const s = truckAt(route(), 4500)
    expect(s.lon).toBe(1)
    expect(s.status).toBe('break')
  })
  it('handles before departure and after arrival', () => {
    expect(truckAt(route(), -10).status).toBe('not_departed')
    expect(truckAt(route(), 99999).status).toBe('arrived')
  })
  it('upperIndex is a correct binary search', () => {
    expect(upperIndex([0, 10, 10, 20], 10)).toBe(2)
    expect(upperIndex([0, 10, 20], 15)).toBe(1)
    expect(upperIndex([0, 10, 20], -1)).toBe(-1)
  })
})

describe('format', () => {
  it('formats durations', () => {
    expect(fmtDuration(45 * 60)).toBe('45m')
    expect(fmtDuration(17.5 * 3600)).toBe('17h 30m')
    expect(fmtDuration(28 * 3600 + 4 * 60)).toBe('1d 4h 04m')
  })
  it('rounds up to the next quarter hour', () => {
    const d = nextQuarterHour(new Date(2026, 0, 1, 10, 7, 30))
    expect([d.getHours(), d.getMinutes()]).toEqual([10, 15])
    const e = nextQuarterHour(new Date(2026, 0, 1, 10, 59))
    expect([e.getHours(), e.getMinutes()]).toEqual([11, 0])
  })
})
