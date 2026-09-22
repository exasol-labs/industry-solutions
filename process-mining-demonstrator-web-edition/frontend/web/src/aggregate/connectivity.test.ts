import { describe, expect, it } from 'vitest'
import { validateAggregateSelection } from './connectivity'
import type { ProcessTransition } from '../types'

const edge = (fromStep: string, toStep: string): ProcessTransition => ({
  fromStep,
  toStep,
  occurrences: 1,
  avgSecs: null,
  medianSecs: null,
  minSecs: null,
  maxSecs: null,
  stdDevSecs: null,
})

// A -> B -> C -> D, plus an unrelated E -> F.
const g: ProcessTransition[] = [edge('A', 'B'), edge('B', 'C'), edge('C', 'D'), edge('E', 'F')]

describe('validateAggregateSelection', () => {
  it('accepts a connected chain', () => {
    const v = validateAggregateSelection(['A', 'B', 'C'], g)
    expect(v).toEqual({ isolated: [], components: 1, ok: true })
  })

  it('rejects a selection with an isolated step', () => {
    const v = validateAggregateSelection(['A', 'B', 'D'], g) // D not adjacent to A/B (C excluded)
    expect(v.isolated).toEqual(['D'])
    expect(v.ok).toBe(false)
  })

  it('rejects two disjoint groups (more than one component)', () => {
    const v = validateAggregateSelection(['A', 'B', 'E', 'F'], g)
    expect(v.components).toBe(2)
    expect(v.ok).toBe(false)
  })

  it('needs at least two steps', () => {
    expect(validateAggregateSelection(['A'], g).ok).toBe(false)
  })

  it('ignores self-loops when judging interconnection', () => {
    const withLoop = [...g, edge('A', 'A')]
    // A alone still isolated relative to a second selected step B? A-B edge exists.
    expect(validateAggregateSelection(['A', 'B'], withLoop).ok).toBe(true)
  })
})
