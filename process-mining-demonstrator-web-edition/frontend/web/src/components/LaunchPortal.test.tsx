/** LaunchPortal — the end-user launch page: process tiles grouped by connection, and a
 *  click that hands the connection id + project up to open it. */

import { afterEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'

const portal = vi.fn()
const guides = vi.fn(async () => [] as { file: string; title: string; type: string }[])
vi.mock('../api', () => ({
  api: {
    portal: () => portal(),
    loginAppearance: vi.fn(async () => null),
    guides: () => guides(),
  },
}))

import { LaunchPortal } from './LaunchPortal'
import { renderSettled, resetStoreOutsideRender } from '../test/renderSettled'
import { useStore } from '../store'

afterEach(() =>
  resetStoreOutsideRender(() => useStore.setState({ authUser: null } as never)),
)

describe('LaunchPortal', () => {
  it('renders a group per connection and a tile per process, and opens on click', async () => {
    portal.mockResolvedValue({
      connections: [
        {
          id: 'c1', name: 'Prod DB', schema: 'MINING', error: null,
          projects: [
            { projectId: 1, title: 'Bookstore', titleShort: 'BOOK', journeys: 10, events: 40, lastEventAt: null },
            { projectId: 2, title: 'Credit', titleShort: 'CRED', journeys: 5, events: 22, lastEventAt: null },
          ],
        },
        { id: 'c2', name: 'Sandbox', schema: 'SBX', error: 'schema unreachable', projects: [] },
      ],
    })
    const onOpen = vi.fn()
    await renderSettled(<LaunchPortal onOpen={onOpen} onWorkbench={() => {}} />)

    // Group headers for both connections (the name sits next to a 🛢️ glyph).
    expect(await screen.findByText(/Prod DB/)).toBeTruthy()
    expect(screen.getByText(/Sandbox/)).toBeTruthy()
    // A tile per process, with its counts.
    expect(screen.getByText('Bookstore')).toBeTruthy()
    expect(screen.getByText(/40 events · 10 journeys/)).toBeTruthy()
    // The unreadable connection shows its error, not a crash.
    expect(screen.getByText(/schema unreachable/)).toBeTruthy()

    // Clicking a tile hands the connection id + the process up.
    fireEvent.click(screen.getByText('Bookstore'))
    await waitFor(() =>
      expect(onOpen).toHaveBeenCalledWith('c1', expect.objectContaining({ projectId: 1 })),
    )
  })

  it('shows an empty state when the user has no connections', async () => {
    portal.mockResolvedValue({ connections: [] })
    await renderSettled(<LaunchPortal onOpen={() => {}} onWorkbench={() => {}} />)
    expect(await screen.findByText(/No connections are assigned to you/)).toBeTruthy()
  })

  it('groups the docs by the leading-number decade into collapsible sections', async () => {
    portal.mockResolvedValue({ connections: [] })
    guides.mockResolvedValue([
      { file: '20-Administration-Quick-Start.html', title: 'Administration Quick-Start', type: 'html' },
      { file: '21-Users-and-Permissions.html', title: 'Users and Permissions', type: 'html' },
      { file: '30-Integration-Console.html', title: 'Integration Console', type: 'html' },
      { file: '31-Import-Unstructured-Logs.html', title: 'Import Unstructured Logs', type: 'html' },
      { file: 'Process-Mining-Demonstrator-Manual.pdf', title: 'Demonstrator Manual', type: 'pdf' },
    ])
    const { container } = await renderSettled(<LaunchPortal onOpen={() => {}} onWorkbench={() => {}} />)

    // Decade labels: 2x → Administration, 3x → Integration & Import, PDF → Full Manual.
    expect(await screen.findByText('Administration')).toBeTruthy()
    expect(screen.getByText('Integration & Import')).toBeTruthy()
    expect(screen.getByText('Full Manual')).toBeTruthy()
    // Each group is a collapsible <details>; the 2x group holds both 20- and 21- guides.
    const groups = container.querySelectorAll('details.pl-dgroup')
    expect(groups.length).toBe(3)
    const admin = screen.getByText('Administration').closest('details') as HTMLElement
    expect(admin.querySelectorAll('a.pl-guide').length).toBe(2)
    // Guides link to /guides/<file>.
    const link = screen.getByText('Integration Console').closest('a') as HTMLAnchorElement
    expect(link.getAttribute('href')).toBe('/guides/30-Integration-Console.html')
  })
})
