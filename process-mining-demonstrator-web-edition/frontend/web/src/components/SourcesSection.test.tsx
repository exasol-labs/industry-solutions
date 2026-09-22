/** SourcesSection — regenerating a sink's bearer token is guarded by a confirmation,
 *  because it invalidates the live token the moment it runs. */

import { afterEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import type { Source } from '../types'

const sink = {
  id: 's1', name: 'Agent sink', kind: 'ai-agent-logging-sink',
  config: { connectionId: 'c1', titleShort: 'AGENTLOG', port: 8120, tls: true },
} as unknown as Source

vi.mock('../api', () => ({
  api: {
    listSources: vi.fn(async () => [sink]),
    regenerateSinkToken: vi.fn(async () => ({ token: 'fresh-token-123' })),
  },
}))

import { api } from '../api'
import { SourcesSection } from './SourcesSection'
import { renderSettled } from '../test/renderSettled'

afterEach(() => vi.clearAllMocks())

describe('SourcesSection — regenerate token', () => {
  it('asks for confirmation before regenerating, and only then mints a new token', async () => {
    await renderSettled(<SourcesSection open onToggle={() => {}} />)
    await screen.findByText('Agent sink')

    // Click the 🔑 regenerate button — nothing should be minted yet.
    fireEvent.click(screen.getByRole('button', { name: 'Regenerate token' }))
    expect(api.regenerateSinkToken).not.toHaveBeenCalled()

    // A confirmation dialog appears, warning the old token stops working.
    expect(screen.getByText('Regenerate ingest token')).toBeTruthy()
    expect(screen.getByText(/current token stops working immediately/)).toBeTruthy()

    // Confirm (the dialog's button carries the text; the icon button only shows 🔑).
    fireEvent.click(screen.getByText('Regenerate token'))
    await waitFor(() => expect(api.regenerateSinkToken).toHaveBeenCalledWith('s1'))
    // The freshly minted token is shown once.
    expect(await screen.findByDisplayValue('fresh-token-123')).toBeTruthy()
  })

  it('does not regenerate when the confirmation is cancelled', async () => {
    await renderSettled(<SourcesSection open onToggle={() => {}} />)
    await screen.findByText('Agent sink')

    fireEvent.click(screen.getByRole('button', { name: 'Regenerate token' }))
    fireEvent.click(screen.getByRole('button', { name: /Cancel/i }))
    expect(api.regenerateSinkToken).not.toHaveBeenCalled()
  })
})
