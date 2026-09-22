/**
 * FlowChart render tests. jsdom can't lay out or drag ReactFlow, so these guard
 * the one thing that IS observable at render time: our nodes declare their size
 * (`measured` + `initialWidth`/`initialHeight`) so ReactFlow keeps them visible
 * even though the mocked ResizeObserver never measures them. Without those fields
 * the wrapper renders `visibility: hidden` — the same blank-out that made nodes
 * and their edges vanish during a drag (see reactflow-drag-hidden-nodes).
 */
import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { FlowChart } from './FlowChart'
import type { ProcessGraph, StepInfo } from '../types'

function step(name: string, belongsTo: string | null): StepInfo {
  return {
    step: name,
    description: '',
    bgColor: 'blue',
    fgColor: 'white',
    score: null,
    shape: 'stadium',
    endOfProcess: false,
    belongsTo,
    eventTime: null,
  }
}

function graphWithGroup(): ProcessGraph {
  const names: Array<[string, string | null]> = [
    ['Start', null],
    ['A', 'Intake'],
    ['B', 'Intake'],
    ['C', null],
  ]
  const steps: Record<string, StepInfo> = {}
  for (const [n, g] of names) steps[n] = step(n, g)
  return {
    steps,
    transitions: [
      { fromStep: 'Start', toStep: 'A', occurrences: 5, avgSecs: 60, medianSecs: 60, minSecs: null, maxSecs: null, stdDevSecs: null },
      { fromStep: 'A', toStep: 'B', occurrences: 4, avgSecs: 60, medianSecs: 60, minSecs: null, maxSecs: null, stdDevSecs: null },
      { fromStep: 'B', toStep: 'C', occurrences: 3, avgSecs: 60, medianSecs: 60, minSecs: null, maxSecs: null, stdDevSecs: null },
    ],
  }
}

function renderChart() {
  return render(
    <FlowChart graph={graphWithGroup()} projectId="test" chartMode="main" metric="Count" />,
  )
}

describe('FlowChart', () => {
  it('renders every step node plus the group box', () => {
    const { container } = renderChart()
    const ids = [...container.querySelectorAll('.react-flow__node')].map((n) =>
      n.getAttribute('data-id'),
    )
    for (const expected of ['Start', 'A', 'B', 'C', 'box:Intake']) {
      expect(ids).toContain(expected)
    }
  })

  it('draws the group box with its per-group colour variable for theme-aware tinting', () => {
    const { container } = renderChart()
    const box = container.querySelector<HTMLElement>('.group-box')
    expect(box).not.toBeNull()
    // The tint + dashed border derive from --gc in CSS (theme-aware opacity),
    // so the node must expose the per-group colour rather than an inline bg.
    expect(box!.style.getPropertyValue('--gc')).not.toBe('')
  })

  it('keeps nodes visible without measurement (declared dimensions)', () => {
    const { container } = renderChart()
    const nodes = [...container.querySelectorAll<HTMLElement>('.react-flow__node')]
    expect(nodes.length).toBeGreaterThan(0)
    // The ResizeObserver is a no-op, so the only reason these are not
    // `visibility: hidden` is the initialWidth/measured we set on every node.
    for (const n of nodes) {
      expect(n.style.visibility).not.toBe('hidden')
    }
  })
})
