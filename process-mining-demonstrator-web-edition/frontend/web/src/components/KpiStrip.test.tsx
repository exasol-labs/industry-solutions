/** KPI "Active Sample" tile — reflects the side's data source: a sample set, or a
 *  Sim-A/Sim-B simulation. */

import { afterEach, describe, expect, it } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { KpiStrip } from './KpiStrip'
import { useStore } from '../store'
import { replaceSettings } from '../settings'
import { resetStoreOutsideRender } from '../test/renderSettled'
import { EMPTY_GRAPH, KPI_META } from '../types'

const inputs = {
  graph: EMPTY_GRAPH,
  journeyCount: null,
  durations: { minSecs: null, avgSecs: null, medianSecs: null, stdDevSecs: null, maxSecs: null },
  goodness: null,
  side: 'a' as const,
  loading: false,
}

describe('KpiStrip Active Sample', () => {
  it('shows the sample-set label when the source is a sample set', () => {
    useStore.setState({
      abDataSourceA: { kind: 'sampleSet', sampleSet: 'SAMPLE_1' },
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      sampleCounts: { SAMPLE_1: 123 } as any,
    })
    render(<KpiStrip {...inputs} />)
    expect(screen.getByText('Sample 1')).toBeInTheDocument()
    expect(screen.getByText('123')).toBeInTheDocument()
  })

  it("reads side B's data source when side='b' (the standalone B-Chart)", () => {
    // Regression: the B-Chart strip must reflect side B's sample, not side A's — else
    // it showed A's sample and only refreshed when A's sample changed.
    useStore.setState({
      abDataSourceA: { kind: 'sampleSet', sampleSet: 'ORIGINAL' },
      abDataSourceB: { kind: 'sampleSet', sampleSet: 'SAMPLE_2' },
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      sampleCounts: { SAMPLE_2: 77 } as any,
    })
    render(<KpiStrip {...inputs} side="b" />)
    expect(screen.getByText('Sample 2')).toBeInTheDocument()
    expect(screen.getByText('77')).toBeInTheDocument()
  })

  it('shows Sim-A and its journey count when the source is a simulation', () => {
    useStore.setState({
      abDataSourceA: { kind: 'simulation', slot: 'Sim-A' },
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      simResultA: { totalJourneys: 4200 } as any,
    })
    render(<KpiStrip {...inputs} />)
    expect(screen.getByText('Sim-A')).toBeInTheDocument()
    expect(screen.getByText('4,200')).toBeInTheDocument()
  })
})

describe('KpiStrip Process Similarity gating', () => {
  afterEach(() => resetStoreOutsideRender(() => replaceSettings({})))

  it('shows Process Similarity in A/B Comparison when a score exists', () => {
    useStore.setState({ activeChartMode: 'A/B Comparison', abSimilarityScore: 0.82 })
    render(<KpiStrip {...inputs} />)
    expect(screen.getByText(KPI_META.processSimilarity.label)).toBeInTheDocument()
  })

  it('never shows Process Similarity outside A/B Comparison, even with a stale score', () => {
    // A lingering score from an earlier A/B run must not leak onto a single-process chart.
    useStore.setState({ activeChartMode: 'A-Chart', abSimilarityScore: 0.82 })
    render(<KpiStrip {...inputs} />)
    expect(screen.queryByText(KPI_META.processSimilarity.label)).toBeNull()
  })
})

describe('KpiStrip reorder & remove (in sync with the left panel via kpi settings)', () => {
  // Both settings the strip writes (`kpi.order`, `kpi.show.*`) are module-level cache,
  // so reset to defaults between cases. Unmount first so the reset's notify() can't
  // re-render a still-mounted strip outside act().
  afterEach(() => resetStoreOutsideRender(() => replaceSettings({})))

  const labelsInOrder = (container: HTMLElement) =>
    [...container.querySelectorAll('.kpi-tile .kpi-label .truncate')].map(
      (n) => n.textContent,
    )

  it('hides a KPI when its × is clicked, writing the same kpi.show.<id> the panel toggles', () => {
    const label = KPI_META.totalJourneys.label
    render(<KpiStrip {...inputs} />)
    expect(screen.getByText(label)).toBeInTheDocument()

    fireEvent.click(screen.getByLabelText(`Hide ${label}`))

    // Gone from the strip — and because it wrote kpi.show.totalJourneys=false, the
    // left panel's toggle for it now reads off too (shared setting).
    expect(screen.queryByText(label)).toBeNull()
  })

  it('reorders the tiles when one is dragged onto another (updates kpi.order)', () => {
    const { container } = render(<KpiStrip {...inputs} />)
    const before = labelsInOrder(container)
    expect(before.length).toBeGreaterThanOrEqual(2)

    const tiles = container.querySelectorAll<HTMLElement>('.kpi-tile')
    // Drag the 2nd tile onto the 1st — it should land in the first slot.
    fireEvent.dragStart(tiles[1])
    fireEvent.drop(tiles[0])

    const after = labelsInOrder(container)
    expect(after[0]).toBe(before[1])
  })
})
