/** sankeySvg — the standalone, self-contained SVG string embedded in the AI report. */

import { describe, expect, it } from 'vitest'
import { sankeySvg } from './sankeySvg'
import type { ProcessGraph, StepInfo } from '../types'

const step = (): StepInfo => ({
  step: 's', description: '', bgColor: 'blue', fgColor: 'white', score: null,
  shape: 'stadium', endOfProcess: false, belongsTo: null, eventTime: null,
})

function graph(names: string[], edges: Array<[string, string, number]>): ProcessGraph {
  const steps: Record<string, StepInfo> = {}
  for (const n of names) steps[n] = step()
  return {
    steps,
    transitions: edges.map(([fromStep, toStep, occurrences]) => ({
      fromStep, toStep, occurrences, avgSecs: null, medianSecs: null, minSecs: null, maxSecs: null, stdDevSecs: null,
    })),
  }
}

describe('sankeySvg', () => {
  it('produces a self-contained <svg> with bands, node labels and NO CSS variables', () => {
    const svg = sankeySvg(graph(['A', 'B', 'C'], [['A', 'B', 10], ['B', 'C', 8]]), 'Count', 100)
    expect(svg.startsWith('<svg')).toBe(true)
    expect(svg.trim().endsWith('</svg>')).toBe(true)
    expect(svg).toContain('xmlns="http://www.w3.org/2000/svg"')
    // Two ribbons (paths) and the node labels present.
    expect((svg.match(/<path /g) || []).length).toBe(2)
    expect(svg).toContain('>A<')
    expect(svg).toContain('>C<')
    // Colours are concrete (hex), never CSS vars — the report has no app tokens.
    expect(svg).not.toContain('var(--')
  })

  it('returns an empty string for an empty graph', () => {
    expect(sankeySvg(graph([], []), 'Count', 0)).toBe('')
  })
})
