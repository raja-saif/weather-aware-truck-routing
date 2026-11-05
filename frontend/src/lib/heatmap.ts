import type { HeatmapResponse } from '../api/types'
import { hexToRgb, RISK_LEVELS, riskPosition, type MetricDef } from './risk'

/** Pixels per grid cell in the rendered image (GPU linear filtering smooths the rest). */
export const UPSAMPLE = 6

/** Opacity at each risk position: calm areas stay light so the basemap shows through. */
const ALPHA_STOPS = [0.16, 0.42, 0.55, 0.66, 0.78]

/** 256-entry RGBA lookup table over risk positions 0..4. */
export function buildLut(): Uint8ClampedArray {
  const colors = RISK_LEVELS.map((l) => hexToRgb(l.color))
  const lut = new Uint8ClampedArray(256 * 4)
  for (let i = 0; i < 256; i++) {
    const pos = (i / 255) * 4
    const lo = Math.min(3, Math.floor(pos))
    const f = pos - lo
    for (let c = 0; c < 3; c++) lut[i * 4 + c] = colors[lo][c] + (colors[lo + 1][c] - colors[lo][c]) * f
    lut[i * 4 + 3] = 255 * (ALPHA_STOPS[lo] + (ALPHA_STOPS[lo + 1] - ALPHA_STOPS[lo]) * f)
  }
  return lut
}

/** Dense row-major grid of risk positions for one frame (NaN = inactive/no data). */
export function frameGrid(hm: HeatmapResponse, values: number[], metric: MetricDef): Float32Array {
  const rows = hm.grid.lats.length
  const cols = hm.grid.lons.length
  const grid = new Float32Array(rows * cols).fill(Number.NaN)
  const cells = hm.grid.cells
  for (let k = 0; k < cells.length; k++) {
    const pos = riskPosition(metric, values[k])
    // below-floor cells are "nothing to show" but still part of the corridor: 0 with no alpha
    grid[cells[k][0] * cols + cells[k][1]] = Number.isNaN(pos) ? -1 : pos
  }
  return grid
}

/**
 * Bilinear upsampling of a coarse grid into RGBA pixels.
 *
 * Pixel centres map back onto grid coordinates; NaN (outside the corridor)
 * neighbours are excluded and their weight fades the alpha, so the corridor
 * edge is soft instead of blocky. Values of -1 mean "inside the corridor but
 * below the metric floor": they blend towards transparent.
 */
export function rasterize(grid: Float32Array, rows: number, cols: number, lut: Uint8ClampedArray, up = UPSAMPLE): ImageData | { width: number; height: number; data: Uint8ClampedArray } {
  const width = cols * up
  const height = rows * up
  const data = new Uint8ClampedArray(width * height * 4)
  for (let y = 0; y < height; y++) {
    const gy = Math.min(Math.max((y + 0.5) / up - 0.5, 0), rows - 1)
    const r0 = Math.floor(gy)
    const r1 = Math.min(r0 + 1, rows - 1)
    const fy = gy - r0
    for (let x = 0; x < width; x++) {
      const gx = Math.min(Math.max((x + 0.5) / up - 0.5, 0), cols - 1)
      const c0 = Math.floor(gx)
      const c1 = Math.min(c0 + 1, cols - 1)
      const fx = gx - c0
      let wSum = 0
      let vSum = 0
      let shown = 0
      const sample = (r: number, c: number, w: number) => {
        const v = grid[r * cols + c]
        if (Number.isNaN(v) || w === 0) return
        wSum += w
        if (v >= 0) {
          vSum += v * w
          shown += w
        }
      }
      sample(r0, c0, (1 - fx) * (1 - fy))
      sample(r0, c1, fx * (1 - fy))
      sample(r1, c0, (1 - fx) * fy)
      sample(r1, c1, fx * fy)
      if (shown === 0) continue
      const pos = vSum / shown
      const idx = Math.max(0, Math.min(255, Math.round((pos / 4) * 255))) * 4
      const o = (y * width + x) * 4
      data[o] = lut[idx]
      data[o + 1] = lut[idx + 1]
      data[o + 2] = lut[idx + 2]
      // fade towards the corridor edge and towards below-floor neighbours
      data[o + 3] = lut[idx + 3] * shown * Math.min(1, wSum * 1.25)
    }
  }
  return { width, height, data }
}

/** Render one frame to a PNG data URL (browser only). */
export function frameToDataUrl(
  hm: HeatmapResponse,
  values: number[],
  metric: MetricDef,
  lut: Uint8ClampedArray,
  canvas: HTMLCanvasElement,
): string {
  const rows = hm.grid.lats.length
  const cols = hm.grid.lons.length
  const img = rasterize(frameGrid(hm, values, metric), rows, cols, lut)
  canvas.width = img.width
  canvas.height = img.height
  const ctx = canvas.getContext('2d')!
  ctx.putImageData(new ImageData(img.data, img.width, img.height), 0, 0)
  return canvas.toDataURL('image/png')
}
