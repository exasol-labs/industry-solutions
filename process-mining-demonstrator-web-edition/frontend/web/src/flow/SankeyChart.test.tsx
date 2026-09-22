/** SankeyChart — renders the flow model as SVG: one ribbon per condensation link, one
 *  node per (possibly collapsed) step, loop clusters marked ↺. */

import { describe, expect, it } from 'vitest'
import { fireEvent, render, screen, within } from '@testing-library/react'
import { SankeyChart } from './SankeyChart'
import type { ProcessGraph, StepInfo } from '../types'

const step = (belongsTo: string | null = null): StepInfo => ({
  step: 's', description: '', bgColor: 'blue', fgColor: 'white', score: null,
  shape: 'stadium', endOfProcess: false, belongsTo, eventTime: null,
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

describe('SankeyChart', () => {
  it('draws a ribbon per link and a labelled bar per node', () => {
    const { container } = render(
      <SankeyChart graph={graph(['A', 'B', 'C'], [['A', 'B', 10], ['B', 'C', 8]])} />,
    )
    expect(container.querySelectorAll('.sankey-link')).toHaveLength(2)
    expect(container.querySelectorAll('.sankey-node')).toHaveLength(3)
    expect(screen.getByText('A')).toBeInTheDocument()
    expect(screen.getByText('C')).toBeInTheDocument()
  })

  it('collapses a loop cluster into one ↺-marked node and notes it in the footer', () => {
    // S → A ⇄ B → T : A,B form a 2-node loop.
    const { container } = render(
      <SankeyChart
        graph={graph(['S', 'A', 'B', 'T'], [['S', 'A', 50], ['A', 'B', 30], ['B', 'A', 20], ['B', 'T', 40]])}
      />,
    )
    // 4 steps collapse to 3 nodes (A+B → one).
    expect(container.querySelectorAll('.sankey-node')).toHaveLength(3)
    // The cluster label is prefixed with the loop marker.
    expect(screen.getByText(/^↺/)).toBeInTheDocument()
    // Footer announces the collapse.
    expect(screen.getByText(/looping cluster.*collapsed/i)).toBeInTheDocument()
  })

  it('lists the grouped steps and highlights the group when a cluster is hovered', () => {
    const { container } = render(
      <SankeyChart
        graph={graph(['S', 'A', 'B', 'T'], [['S', 'A', 50], ['A', 'B', 30], ['B', 'A', 20], ['B', 'T', 40]])}
      />,
    )
    const cluster = container.querySelector('.sankey-node.cluster') as HTMLElement
    expect(cluster).toBeTruthy()

    fireEvent.mouseEnter(cluster)
    expect(cluster.classList.contains('focus')).toBe(true) // the group lights up

    fireEvent.mouseMove(cluster, { clientX: 20, clientY: 20 })
    const tip = container.querySelector('.sankey-tip') as HTMLElement
    expect(tip).toBeTruthy()
    expect(tip.textContent).toMatch(/Grouped steps that loop together \(2\)/)
    expect(within(tip).getByText('A')).toBeInTheDocument()
    expect(within(tip).getByText('B')).toBeInTheDocument()
  })

  it('drives the display by the selected metric (footer states which)', () => {
    render(<SankeyChart graph={graph(['A', 'B'], [['A', 'B', 10]])} metric="Avg Time" />)
    expect(screen.getByText(/Band width shows/)).toHaveTextContent('Avg Time')
  })

  it('shows an empty-state message for an empty graph', () => {
    render(<SankeyChart graph={graph([], [])} />)
    expect(screen.getByText(/no transitions/i)).toBeInTheDocument()
  })
})
