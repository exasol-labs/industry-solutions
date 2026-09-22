/** Model-helper tests — the TypeScript mirrors of ProcessTransition /
 *  ProcessGraph / SampleSet / NoteTarget behaviour. */

import { describe, expect, it } from 'vitest'
import {
  isPercentMetric,
  isTimeBased,
  journeyPercentage,
  maxMetricValue,
  metricValue,
  outgoingPercentage,
  noteTargetKey,
  noteTargetLabel,
  sampleLabel,
  sampleShortLabel,
  simulationFilterNotice,
  type ProcessGraph,
  type ProcessTransition,
} from './types'

const t: ProcessTransition = {
  fromStep: 'A',
  toStep: 'B',
  occurrences: 7,
  avgSecs: 1.0,
  medianSecs: 1.0,
  minSecs: 0.5,
  maxSecs: 3.0,
  stdDevSecs: 0.25,
}

describe('metricValue', () => {
  it('maps each metric to the right field', () => {
    expect(metricValue(t, 'Count')).toBe(7)
    expect(metricValue(t, 'Avg Time')).toBe(1.0)
    expect(metricValue(t, 'Min Time')).toBe(0.5)
    expect(metricValue(t, 'Max Time')).toBe(3.0)
    expect(metricValue(t, 'Std Dev')).toBe(0.25)
  })

  it('returns null for the percent metrics (they need a denominator)', () => {
    expect(metricValue(t, 'Percentage')).toBeNull()
    expect(metricValue(t, 'Journey %')).toBeNull()
  })
})

describe('outgoingPercentage (branching share)', () => {
  it('is the share of the source node total, so a node’s edges sum to 100%', () => {
    // Node A leaves 30 times total: 21 via this edge, 9 via another → 70% + 30% = 100%.
    expect(outgoingPercentage({ ...t, occurrences: 21 }, 30)).toBeCloseTo(70)
    expect(outgoingPercentage({ ...t, occurrences: 9 }, 30)).toBeCloseTo(30)
    expect(outgoingPercentage(t, 0)).toBe(0) // no outgoing → 0, never divide by zero
  })
})

describe('journeyPercentage (share of all filtered journeys)', () => {
  it('is occurrences over the total filtered journeys', () => {
    expect(journeyPercentage({ ...t, occurrences: 40 }, 200)).toBeCloseTo(20)
    // An edge a journey repeats can exceed 100% (occurrences > journey count).
    expect(journeyPercentage({ ...t, occurrences: 150 }, 100)).toBeCloseTo(150)
    expect(journeyPercentage(t, 0)).toBe(0)
  })
})

describe('isPercentMetric / isTimeBased', () => {
  it('percent metrics are the two shares, and neither is time-based', () => {
    expect(isPercentMetric('Percentage')).toBe(true)
    expect(isPercentMetric('Journey %')).toBe(true)
    expect(isPercentMetric('Count')).toBe(false)
    expect(isPercentMetric('Avg Time')).toBe(false)
    expect(isTimeBased('Count')).toBe(false)
    expect(isTimeBased('Percentage')).toBe(false)
    expect(isTimeBased('Journey %')).toBe(false)
    for (const m of ['Avg Time', 'Min Time', 'Max Time', 'Std Dev'] as const) {
      expect(isTimeBased(m)).toBe(true)
    }
  })
})

describe('maxMetricValue', () => {
  const graph: ProcessGraph = {
    steps: {},
    transitions: [
      { fromStep: 'A', toStep: 'B', occurrences: 3, avgSecs: 2, medianSecs: 2, minSecs: 1, maxSecs: 4, stdDevSecs: null },
      { fromStep: 'B', toStep: 'C', occurrences: 9, avgSecs: 5, medianSecs: 5, minSecs: 2, maxSecs: 8, stdDevSecs: null },
    ],
  }

  it('reports the maximum per metric', () => {
    expect(maxMetricValue(graph, 'Count')).toBe(9)
    expect(maxMetricValue(graph, 'Avg Time')).toBe(5)
    expect(maxMetricValue(graph, 'Max Time')).toBe(8)
  })

  it('uses a fixed 0–100 scale for the percent metrics', () => {
    expect(maxMetricValue(graph, 'Percentage')).toBe(100)
    expect(maxMetricValue(graph, 'Journey %')).toBe(100)
  })

  it('falls back to 1 for an empty graph', () => {
    expect(maxMetricValue({ steps: {}, transitions: [] }, 'Count')).toBe(1)
  })
})

describe('SampleSet labels', () => {
  it('formats long and short labels', () => {
    expect(sampleLabel('ORIGINAL')).toBe('Original Data')
    expect(sampleShortLabel('SAMPLE_2')).toBe('Sample 2')
  })
})

describe('simulationFilterNotice', () => {
  it('is null for a sample-set source', () => {
    expect(
      simulationFilterNotice({ kind: 'sampleSet', sampleSet: 'ORIGINAL' }),
    ).toBeNull()
  })

  it('warns (naming the slot) for a simulation source', () => {
    const notice = simulationFilterNotice({ kind: 'simulation', slot: 'Sim-B' })
    expect(notice).toContain('Sim-B')
    expect(notice).toMatch(/filtering/i)
  })
})

describe('NoteTarget helpers', () => {
  it('builds keys and labels for nodes and edges', () => {
    expect(noteTargetKey({ type: 'node', value: 'Checkout' })).toBe('node:Checkout')
    expect(noteTargetLabel({ type: 'node', value: 'Checkout' })).toBe('Checkout')
    expect(noteTargetKey({ type: 'edge', from: 'A', to: 'B' })).toBe('edge:A->B')
    expect(noteTargetLabel({ type: 'edge', from: 'A', to: 'B' })).toBe('A → B')
  })
})
