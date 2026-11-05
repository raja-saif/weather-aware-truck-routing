import { useEffect, useRef, useState } from 'react'
import type { HeatMetric, HeatmapResponse } from '../api/types'
import { buildLut, frameToDataUrl } from '../lib/heatmap'
import { METRICS } from '../lib/risk'

const LUT = buildLut()

/**
 * Pre-renders every forecast hour of the selected metric to an image.
 *
 * Rendering happens in small chunks between animation frames so the UI never
 * stalls, and results are cached per metric so switching back is instant.
 */
export function useHeatFrames(heatmap: HeatmapResponse | null, metric: HeatMetric): string[] | null {
  const [frames, setFrames] = useState<string[] | null>(null)
  const cache = useRef<{ source: HeatmapResponse | null; byMetric: Partial<Record<HeatMetric, string[]>> }>({ source: null, byMetric: {} })

  useEffect(() => {
    if (cache.current.source !== heatmap) cache.current = { source: heatmap, byMetric: {} }
    if (!heatmap) {
      setFrames(null)
      return
    }
    const hit = cache.current.byMetric[metric]
    if (hit) {
      setFrames(hit)
      return
    }
    let cancelled = false
    const canvas = document.createElement('canvas')
    const values = heatmap.frames[metric]
    const out: string[] = []
    const step = () => {
      if (cancelled) return
      const until = performance.now() + 12 // keep each chunk under one frame budget
      while (out.length < values.length && performance.now() < until) {
        out.push(frameToDataUrl(heatmap, values[out.length], METRICS[metric], LUT, canvas))
      }
      if (out.length < values.length) {
        requestAnimationFrame(step)
      } else {
        cache.current.byMetric[metric] = out
        setFrames(out)
      }
    }
    requestAnimationFrame(step)
    return () => {
      cancelled = true
    }
  }, [heatmap, metric])

  return frames
}
