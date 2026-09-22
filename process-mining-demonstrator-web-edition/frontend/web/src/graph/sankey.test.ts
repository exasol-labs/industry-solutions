/** buildSankey — collapses loop clusters (SCCs) into single nodes so a cyclic DFG lays
 *  out as an acyclic left-to-right Sankey, and assigns columns by longest path. */

import { describe, expect, it } from 'vitest'
import { buildSankey } from './sankey'
import type { ProcessGraph, StepInfo } from '../types'

function step(belongsTo: string | null = null): StepInfo {
  return {
    step: 's', description: '', bgColor: 'blue', fgColor: 'white', score: null,
    shape: 'stadium', endOfProcess: false, belongsTo, eventTime: null,
  }
}

function graph(
  names: string[],
  edges: Array<[string, string, number]>,
  groups: Record<string, string | null> = {},
): ProcessGraph {
  const steps: Record<string, StepInfo> = {}
  for (const n of names) steps[n] = step(groups[n] ?? null)
  return {
    steps,
    transitions: edges.map(([fromStep, toStep, occurrences]) => ({
      fromStep, toStep, occurrences, avgSecs: null, medianSecs: null, minSecs: null, maxSecs: null, stdDevSecs: null,
    })),
  }
}

describe('buildSankey', () => {
  it('lays out an acyclic chain one node per column, no clusters', () => {
    const m = buildSankey(graph(['A', 'B', 'C'], [['A', 'B', 10], ['B', 'C', 8]]))
    expect(m.clustered).toBe(0)
    expect(m.nodes.map((n) => [n.id, n.column]).sort()).toEqual([['A', 0], ['B', 1], ['C', 2]])
    expect(m.columns).toBe(3)
    expect(m.links.map((l) => ({ source: l.source, target: l.target, value: l.value }))).toEqual([
      { source: 'A', target: 'B', value: 10 },
      { source: 'B', target: 'C', value: 8 },
    ])
  })

  it('collapses a loop cluster (A⇄B⇄C) into ONE node and absorbs the internal hops', () => {
    // S → A → B → C → A (the A,B,C cycle) and C → T.
    const m = buildSankey(
      graph(
        ['S', 'A', 'B', 'C', 'T'],
        [['S', 'A', 100], ['A', 'B', 60], ['B', 'C', 55], ['C', 'A', 40], ['C', 'T', 90]],
      ),
    )
    expect(m.clustered).toBe(1)
    const cluster = m.nodes.find((n) => n.isCluster)!
    expect(cluster.members.sort()).toEqual(['A', 'B', 'C'])
    // The three intra-cluster edges (A→B, B→C, C→A) become internal hops, not links.
    expect(cluster.internalHops).toBe(60 + 55 + 40)
    // Only the boundary flows survive as Sankey links: S→cluster and cluster→T.
    expect(m.links).toHaveLength(2)
    expect(m.links.some((l) => l.source === 'S' && l.target === cluster.id && l.value === 100)).toBe(true)
    expect(m.links.some((l) => l.source === cluster.id && l.target === 'T' && l.value === 90)).toBe(true)
    // Columns: S(0) → cluster(1) → T(2). The whole loop is one column.
    expect(m.nodes.find((n) => n.id === 'S')!.column).toBe(0)
    expect(cluster.column).toBe(1)
    expect(m.nodes.find((n) => n.id === 'T')!.column).toBe(2)
  })

  it('names a loop cluster after a shared step group when the members agree', () => {
    const m = buildSankey(
      graph(
        ['Duty Free', 'Dining', 'Lounge'],
        [['Duty Free', 'Dining', 5], ['Dining', 'Lounge', 4], ['Lounge', 'Duty Free', 3]],
        { 'Duty Free': 'Airside', Dining: 'Airside', Lounge: 'Airside' },
      ),
    )
    const cluster = m.nodes.find((n) => n.isCluster)!
    expect(cluster.label).toBe('Airside')
  })

  it('does not cluster a lone self-loop, but counts it as an internal hop', () => {
    const m = buildSankey(graph(['A', 'B'], [['A', 'A', 7], ['A', 'B', 10]]))
    expect(m.clustered).toBe(0)
    const a = m.nodes.find((n) => n.id === 'A')!
    expect(a.isCluster).toBe(false)
    expect(a.internalHops).toBe(7)
    expect(m.links.map((l) => ({ source: l.source, target: l.target, value: l.value }))).toEqual([
      { source: 'A', target: 'B', value: 10 },
    ])
  })

  it('sets node volume to max(inflow, outflow)', () => {
    // B receives 10+5 and emits 12.
    const m = buildSankey(
      graph(['A', 'X', 'B', 'C'], [['A', 'B', 10], ['X', 'B', 5], ['B', 'C', 12]]),
    )
    expect(m.nodes.find((n) => n.id === 'B')!.volume).toBe(15)
  })

  it('aggregates times (occurrence-weighted avg, min-of-mins, max-of-maxes) on merged links', () => {
    const t = (
      fromStep: string, toStep: string, occurrences: number,
      avgSecs: number, minSecs: number, maxSecs: number, stdDevSecs: number,
    ) => ({ fromStep, toStep, occurrences, avgSecs, medianSecs: null, minSecs, maxSecs, stdDevSecs })
    // S→A and S→B both feed the {A,B} loop cluster, so they merge into one boundary link.
    const g: ProcessGraph = {
      steps: { S: step(), A: step(), B: step() },
      transitions: [
        t('S', 'A', 10, 100, 50, 150, 10),
        t('S', 'B', 30, 200, 80, 260, 20),
        t('A', 'B', 5, 0, 0, 0, 0),
        t('B', 'A', 5, 0, 0, 0, 0),
      ],
    }
    const boundary = buildSankey(g).links.find((l) => l.source === 'S')!
    expect(boundary.value).toBe(40) // 10 + 30 occurrences
    expect(boundary.avgSecs).toBeCloseTo((100 * 10 + 200 * 30) / 40) // 175, weighted by occ
    expect(boundary.minSecs).toBe(50)
    expect(boundary.maxSecs).toBe(260)
  })
})
