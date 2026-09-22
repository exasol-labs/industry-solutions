/** TransitionTablePanel — the raw directly-follows table behind a process map: every
 *  transition with all its metrics at once, searchable and sortable. */

import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { TransitionTablePanel } from './TransitionTablePanel'
import type { ProcessGraph } from '../types'

const graph: ProcessGraph = {
  steps: {},
  transitions: [
    { fromStep: 'A', toStep: 'B', occurrences: 100, avgSecs: 60, medianSecs: 55, minSecs: 10, maxSecs: 120, stdDevSecs: 5 },
    { fromStep: 'A', toStep: 'C', occurrences: 40, avgSecs: null, medianSecs: null, minSecs: null, maxSecs: null, stdDevSecs: null },
    { fromStep: 'B', toStep: 'B', occurrences: 7, avgSecs: 30, medianSecs: 30, minSecs: 30, maxSecs: 30, stdDevSecs: 0 },
  ],
}

const bodyRows = () =>
  within(screen.getByRole('table').querySelector('tbody') as HTMLElement).getAllByRole('row')

describe('TransitionTablePanel', () => {
  it('lists every transition, titled by the chart, sorted by count desc by default', () => {
    render(
      <TransitionTablePanel graph={graph} journeyTotal={200} title="A-Chart" onClose={() => {}} />,
    )
    expect(screen.getByText('Transition table — A-Chart')).toBeInTheDocument()

    const rows = bodyRows()
    expect(rows).toHaveLength(3)
    // Default sort is Count descending: 100, 40, 7.
    expect(rows[0]).toHaveTextContent('A')
    expect(rows[0]).toHaveTextContent('B')
    expect(within(rows[0]).getByText('100')).toBeInTheDocument()
    expect(within(rows[2]).getByText('7')).toBeInTheDocument()
  })

  it('shows all metrics at once, with — for missing times and the outgoing share', () => {
    render(
      <TransitionTablePanel graph={graph} journeyTotal={200} title="A-Chart" onClose={() => {}} />,
    )
    // A→B outgoing share = 100 / (100+40) = 71% (rounded, ≥10).
    expect(screen.getByText('71%')).toBeInTheDocument()
    // A→C has no time stats → em dashes.
    const acRow = bodyRows().find((r) => r.textContent?.includes('C')) as HTMLElement
    expect(within(acRow).getAllByText('—').length).toBe(5) // avg/median/min/max/std
    // A→B journey share = 100 / 200 = 50%.
    expect(screen.getByText('50%')).toBeInTheDocument()
  })

  it('filters rows by step name', () => {
    render(
      <TransitionTablePanel graph={graph} journeyTotal={200} title="A-Chart" onClose={() => {}} />,
    )
    fireEvent.change(screen.getByPlaceholderText('Filter by step name'), {
      target: { value: 'C' },
    })
    const rows = bodyRows()
    expect(rows).toHaveLength(1)
    expect(rows[0]).toHaveTextContent('C')
  })

  it('copies the visible rows as TSV (header + raw values) to the clipboard', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.assign(navigator, { clipboard: { writeText } })

    render(
      <TransitionTablePanel graph={graph} journeyTotal={200} title="A-Chart" onClose={() => {}} />,
    )
    fireEvent.click(screen.getByText('⧉ Copy'))

    await waitFor(() => expect(writeText).toHaveBeenCalledTimes(1))
    const tsv = writeText.mock.calls[0][0] as string
    // A tab-separated header row …
    expect(tsv.split('\n')[0]).toBe(
      'From\tTo\tCount\t% Outgoing\tJourney %\tAvg (s)\tMedian (s)\tMin (s)\tMax (s)\tStd Dev (s)',
    )
    // … the top (Count-sorted) row with raw seconds …
    expect(tsv).toContain('A\tB\t100\t71.43\t50\t60\t55\t10\t120\t5')
    // … and blank cells where a time stat is missing (A→C).
    expect(tsv).toContain('A\tC\t40\t28.57\t20\t\t\t\t\t')
    // Button flips to a confirmation.
    expect(screen.getByText('✓ Copied')).toBeInTheDocument()
  })

  it('re-sorts when a column header is clicked', () => {
    render(
      <TransitionTablePanel graph={graph} journeyTotal={200} title="A-Chart" onClose={() => {}} />,
    )
    // Click "From" → ascending alphabetical; the two A-rows come before the B-row.
    fireEvent.click(screen.getByText('From'))
    const firstCellText = () =>
      bodyRows().map((r) => (r.querySelector('td') as HTMLElement).textContent)
    expect(firstCellText()).toEqual(['A', 'A', 'B'])
  })
})
