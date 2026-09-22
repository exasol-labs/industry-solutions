import { describe, expect, it } from 'vitest'
import {
  collapseExcept,
  subgraphForMembers,
  subgraphWithNeighbours,
  type AggMembers,
} from './explode'
import type { ProcessGraph, ProcessTransition, StepInfo } from '../types'

const step = (): StepInfo => ({
  step: '',
  description: '',
  bgColor: 'blue',
  fgColor: 'white',
  score: null,
  shape: 'rectangle',
  endOfProcess: false,
  belongsTo: null,
  eventTime: null,
})
const tr = (fromStep: string, toStep: string, occurrences = 1): ProcessTransition => ({
  fromStep,
  toStep,
  occurrences,
  avgSecs: null,
  medianSecs: null,
  minSecs: null,
  maxSecs: null,
  stdDevSecs: null,
})
const g = (names: string[], transitions: ProcessTransition[]): ProcessGraph => ({
  steps: Object.fromEntries(names.map((n) => [n, step()])),
  transitions,
})
const edges = (graph: ProcessGraph) =>
  graph.transitions.map((t) => `${t.fromStep}->${t.toStep}`).sort()
const sigmaInfo = () => step()

describe('collapseExcept', () => {
  // Source (original): A → M1 → M2 → B, with aggregate Σ = {M1, M2}.
  const source = g(['A', 'M1', 'M2', 'B'], [tr('A', 'M1', 5), tr('M1', 'M2', 5), tr('M2', 'B', 5)])
  const aggs: AggMembers[] = [{ sigmaStep: 'Σ', members: ['M1', 'M2'] }]

  it('collapses to Σ when nothing is expanded (high-level view)', () => {
    const out = collapseExcept(source, aggs, new Set(), sigmaInfo)
    expect(Object.keys(out.steps).sort()).toEqual(['A', 'B', 'Σ'])
    expect(edges(out)).toEqual(['A->Σ', 'Σ->B']) // internal M1→M2 hidden
  })

  it('expands Σ in place with the ORIGINAL numbers', () => {
    const out = collapseExcept(source, aggs, new Set(['Σ']), sigmaInfo)
    expect(Object.keys(out.steps).sort()).toEqual(['A', 'B', 'M1', 'M2'])
    expect(edges(out)).toEqual(['A->M1', 'M1->M2', 'M2->B'])
    // The revealed internal edge keeps the source's real count (5), not a re-derived one.
    expect(out.transitions.find((t) => t.fromStep === 'M1' && t.toStep === 'M2')?.occurrences).toBe(5)
  })

  it('expands one aggregate while keeping the other collapsed', () => {
    // A → M1 → X → N1 → B ; Σ1={M1}, Σ2={N1}
    const src = g(['A', 'M1', 'X', 'N1', 'B'], [tr('A', 'M1'), tr('M1', 'X'), tr('X', 'N1'), tr('N1', 'B')])
    const two: AggMembers[] = [
      { sigmaStep: 'Σ1', members: ['M1'] },
      { sigmaStep: 'Σ2', members: ['N1'] },
    ]
    const out = collapseExcept(src, two, new Set(['Σ1']), sigmaInfo)
    expect(out.steps.M1).toBeDefined()
    expect(out.steps.Σ2).toBeDefined()
    expect(out.steps.N1).toBeUndefined()
    expect(edges(out)).toEqual(['A->M1', 'M1->X', 'X->Σ2', 'Σ2->B'])
  })

  it('subgraphForMembers keeps only member steps and their inter-edges (real numbers)', () => {
    const src = g(['A', 'M1', 'M2', 'B'], [tr('A', 'M1', 5), tr('M1', 'M2', 4), tr('M2', 'B', 5)])
    const sub = subgraphForMembers(src, ['M1', 'M2'])
    expect(Object.keys(sub.steps).sort()).toEqual(['M1', 'M2'])
    expect(edges(sub)).toEqual(['M1->M2'])
    expect(sub.transitions[0].occurrences).toBe(4) // the source's real count
  })

  it('subgraphWithNeighbours adds incoming/outgoing edges + external context nodes', () => {
    const src = g(['A', 'M1', 'M2', 'B'], [tr('A', 'M1', 5), tr('M1', 'M2', 4), tr('M2', 'B', 3)])
    const { graph: sub, contextNodes } = subgraphWithNeighbours(src, ['M1', 'M2'])
    expect(Object.keys(sub.steps).sort()).toEqual(['A', 'B', 'M1', 'M2'])
    expect(edges(sub)).toEqual(['A->M1', 'M1->M2', 'M2->B']) // incoming A→, internal, outgoing →B
    expect(contextNodes.sort()).toEqual(['A', 'B'])
    // Real numbers on the boundary edges.
    expect(sub.transitions.find((t) => t.fromStep === 'A')?.occurrences).toBe(5)
    expect(sub.transitions.find((t) => t.toStep === 'B')?.occurrences).toBe(3)
  })

  it('merges edges that collapse onto the same Σ', () => {
    // Two members of Σ both feed B → collapsed edges Σ→B merge (2+3=5).
    const src = g(['M1', 'M2', 'B'], [tr('M1', 'B', 2), tr('M2', 'B', 3)])
    const out = collapseExcept(src, [{ sigmaStep: 'Σ', members: ['M1', 'M2'] }], new Set(), sigmaInfo)
    expect(edges(out)).toEqual(['Σ->B'])
    expect(out.transitions[0].occurrences).toBe(5)
  })
})
