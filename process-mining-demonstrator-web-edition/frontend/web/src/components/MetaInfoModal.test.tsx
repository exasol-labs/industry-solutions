/** MetaInfoModal — the node "Meta Infos" panel: tabs per META column, node-scoped
 *  searchable values (fetched for the clicked node), and include/exclude toggles. */

import { afterEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, cleanup } from '@testing-library/react'

const handleMetaAction = vi.fn()
const clearMetaFilters = vi.fn()
const nodeMetaValues = vi.fn(async () => ({
  meta1: [
    { value: 'Visa', time: '2026-09-17 13:54:02', count: 3 },
    { value: 'SEPA', time: '2026-09-16 09:10:00', count: 1 },
    { value: 'Apple Pay', time: '2026-09-15 08:00:00', count: 1 },
  ],
  meta2: [
    { value: 'Retail', time: '2026-09-17 13:54:02', count: 4 },
    { value: 'Business', time: '2026-09-14 11:00:00', count: 2 },
  ],
  meta3: [],
}))
const state = {
  meta1Title: 'Payment', meta2Title: 'Segment', meta3Title: 'Channel',
  metaInfoNode: 'Checkout',
  selectedProject: { projectId: 7 },
  metaFilters: { included: [['Visa'], [], []], excluded: [[], ['Business'], []] },
  handleMetaAction,
  clearMetaFilters,
}

vi.mock('../store', () => ({
  useStore: (sel: (s: typeof state) => unknown) => sel(state),
}))
vi.mock('../api', () => ({ api: { nodeMetaValues: (...a: unknown[]) => nodeMetaValues(...(a as [])) } }))

import { MetaInfoModal } from './MetaInfoModal'
import { renderSettled } from '../test/renderSettled'

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('MetaInfoModal', () => {
  it('fetches the node values and toggles include/exclude', async () => {
    await renderSettled(<MetaInfoModal onClose={() => {}} />)

    // Fetched the values for the clicked node.
    expect(nodeMetaValues).toHaveBeenCalledWith(7, 'Checkout', 'ORIGINAL')
    // Title names the node; tabs use the META titles.
    expect(screen.getByText(/Meta Infos — Checkout/)).toBeTruthy()
    expect(screen.getByRole('button', { name: /Payment/ })).toBeTruthy()

    // Meta_1 values listed; Include/Exclude call handleMetaAction(0, …).
    expect(await screen.findByText('SEPA')).toBeTruthy()
    // The second field shows each value's date/time (with a count when repeated).
    expect(screen.getByText('2026-09-16 09:10:00')).toBeTruthy()
    expect(screen.getByText(/2026-09-17 13:54:02 · ×3/)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Include SEPA' }))
    expect(handleMetaAction).toHaveBeenCalledWith(0, 'SEPA', 'include')
    fireEvent.click(screen.getByRole('button', { name: 'Exclude Visa' }))
    expect(handleMetaAction).toHaveBeenCalledWith(0, 'Visa', 'exclude')

    // Search narrows the list by value…
    fireEvent.change(screen.getByPlaceholderText(/Search Payment value or date/), { target: { value: 'app' } })
    expect(screen.getByText('Apple Pay')).toBeTruthy()
    expect(screen.queryByText('SEPA')).toBeNull()

    // …and by date/time.
    fireEvent.change(screen.getByPlaceholderText(/Search Payment value or date/), { target: { value: '09-16' } })
    expect(screen.getByText('SEPA')).toBeTruthy()
    expect(screen.queryByText('Apple Pay')).toBeNull()

    // Clear reflects the 2 active filters.
    fireEvent.click(screen.getByRole('button', { name: /Clear meta filters \(2\)/ }))
    expect(clearMetaFilters).toHaveBeenCalled()
  })

  it('shows a per-node empty note for a column the node never used', async () => {
    await renderSettled(<MetaInfoModal onClose={() => {}} />)
    fireEvent.click(screen.getByRole('button', { name: /Channel/ }))
    expect(screen.getByText(/This node has no values in this column/)).toBeTruthy()
  })
})
