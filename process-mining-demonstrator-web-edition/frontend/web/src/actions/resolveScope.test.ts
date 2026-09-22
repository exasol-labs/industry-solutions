import { describe, expect, it } from 'vitest'
import { resolveScope } from './resolveScope'
import { actionMatchesNode } from './describe'
import type { ProcessTransition } from '../types'
import type { ActionSpec } from './types'

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

// A -> B -> C -> D, with a self-loop on B and a back edge D -> B.
const graph: ProcessTransition[] = [
  edge('A', 'B'),
  edge('B', 'C'),
  edge('C', 'D'),
  edge('B', 'B'),
  edge('D', 'B'),
]

describe('resolveScope', () => {
  it('THIS is just the node', () => {
    expect(resolveScope(['THIS'], 'C', graph)).toEqual(['C'])
  })

  it('PREVIOUS = direct predecessors, FOLLOWING = direct successors', () => {
    expect(resolveScope(['PREVIOUS'], 'C', graph).sort()).toEqual(['B'])
    expect(resolveScope(['FOLLOWING'], 'B', graph).sort()).toEqual(['B', 'C']) // self-loop included
  })

  it('ALL_FOLLOWING traverses transitively (cycles safe)', () => {
    expect(resolveScope(['ALL_FOLLOWING'], 'A', graph).sort()).toEqual(['B', 'C', 'D'])
  })

  it('ALL_PREVIOUS traverses backwards transitively', () => {
    // Everything that can reach D: C, B, A (and D itself via the D->B->...->? no path back to D except cycle)
    expect(resolveScope(['ALL_PREVIOUS'], 'D', graph).sort()).toEqual(['A', 'B', 'C', 'D'])
  })

  it('combines selectors and de-duplicates', () => {
    expect(resolveScope(['THIS', 'PREVIOUS', 'FOLLOWING'], 'C', graph).sort()).toEqual(['B', 'C', 'D'])
  })
})

describe('actionMatchesNode', () => {
  const spec = (allNodes: boolean, steps: string[]): ActionSpec => ({
    availability: { allNodes, steps },
    show: { kind: 'logEntries', limit: 1, metrics: [], forLast: null },
    from: { selectors: ['THIS'] },
    target: null,
    sort: null,
    where: null,
  })

  it('ALL NODES matches any node', () => {
    expect(actionMatchesNode(spec(true, []), 'ANYTHING')).toBe(true)
  })

  it('a step list matches only listed nodes', () => {
    expect(actionMatchesNode(spec(false, ['PAYMENT']), 'PAYMENT')).toBe(true)
    expect(actionMatchesNode(spec(false, ['PAYMENT']), 'LOGIN')).toBe(false)
  })

  it('tolerates sigma glyph, case and whitespace on aggregate steps', () => {
    // Node is the Greek Σ (U+03A3); availability may use ∑ (U+2211), lower case, or spaces.
    expect(actionMatchesNode(spec(false, ['∑ Payment']), 'Σ Payment')).toBe(true)
    expect(actionMatchesNode(spec(false, ['σ payment']), 'Σ Payment')).toBe(true)
    expect(actionMatchesNode(spec(false, ['  Σ   Payment ']), 'Σ Payment')).toBe(true)
    // But a genuinely different step still does not match.
    expect(actionMatchesNode(spec(false, ['∑ Refund']), 'Σ Payment')).toBe(false)
  })
})
