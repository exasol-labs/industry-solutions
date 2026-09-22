import { afterEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'

vi.mock('../api', () => ({
  api: {
    runSource: vi.fn(async () => ({ records: 12, detail: '12 events written, 1 skipped' })),
    integrationStatus: vi.fn(async () => ({ state: 'completed', recordsDone: 0, recordsTotal: 0 })),
    destinationProjects: vi.fn(async () => ({
      ok: true,
      error: null,
      projects: [{ projectId: 1, titleShort: 'RETAIL', title: 'Retail demo', journeys: 3, events: 40 }],
    })),
    sourceCheckpoint: vi.fn(async () => ({
      byteOffset: 0, size: 0, signature: '', records: 0, updatedAt: null, lastError: null,
    })),
    resetSourceCheckpoint: vi.fn(async () => ({ ok: true })),
  },
}))

import { api } from '../api'
import { useStore } from '../store'
import { RunSourceDialog } from './RunSourceDialog'
import type { Source } from '../types'
import { renderSettled, resetStoreOutsideRender } from '../test/renderSettled'

const SOURCE: Source = {
  id: 's1', owner: 'dev', name: 'Access log', kind: 'file',
  config: { path: '/x.log', sourceTypeId: 'st1' }, createdAt: '',
}

afterEach(() => {
  // Unmount before resetting the store: the dialog subscribes to it, and resetting while
  // mounted would re-render it outside act(). See resetStoreOutsideRender.
  resetStoreOutsideRender(() =>
    useStore.setState({ connections: [], connection: { isConnected: false, activeProfileId: null } as never }),
  )
  vi.clearAllMocks()
})

describe('RunSourceDialog', () => {
  it('defaults the destination to the active connection and runs a new project', async () => {
    useStore.setState({
      connections: [{ id: 'c1', name: 'Prod DB' }] as never,
      connection: { isConnected: true, activeProfileId: 'c1' } as never,
    })
    await renderSettled(<RunSourceDialog source={SOURCE} onClose={() => {}} onDone={() => {}} />)

    fireEvent.change(screen.getByPlaceholderText(/RETAIL/i), { target: { value: 'P1' } })
    fireEvent.click(screen.getByRole('button', { name: /Run extraction/i }))

    await waitFor(() => expect(api.runSource).toHaveBeenCalledWith('s1', 'P1', 'c1', true))
    await waitFor(() => expect(screen.getByText(/12 events written/)).toBeTruthy())
  })

  it('runs against a picked connection the app is not connected to', async () => {
    // The backend opens the chosen connection itself, so no live session is needed.
    useStore.setState({
      connections: [{ id: 'c1', name: 'Prod DB' }, { id: 'c2', name: 'Staging DB' }] as never,
      connection: { isConnected: false, activeProfileId: null } as never,
    })
    await renderSettled(<RunSourceDialog source={SOURCE} onClose={() => {}} onDone={() => {}} />)

    fireEvent.change(screen.getByLabelText(/Destination connection/i), { target: { value: 'c2' } })
    fireEvent.change(screen.getByPlaceholderText(/RETAIL/i), { target: { value: 'P1' } })
    fireEvent.click(screen.getByRole('button', { name: /Run extraction/i }))

    await waitFor(() => expect(api.runSource).toHaveBeenCalledWith('s1', 'P1', 'c2', true))
  })

  it('offers the projects already in the destination schema', async () => {
    useStore.setState({
      connections: [{ id: 'c1', name: 'Prod DB' }] as never,
      connection: { isConnected: true, activeProfileId: 'c1' } as never,
    })
    await renderSettled(<RunSourceDialog source={SOURCE} onClose={() => {}} onDone={() => {}} />)

    await waitFor(() => expect(api.destinationProjects).toHaveBeenCalledWith('c1'))
    const select = await screen.findByLabelText('Project')
    await waitFor(() => expect(screen.getByRole('option', { name: /RETAIL/ })).toBeTruthy())

    fireEvent.change(select, { target: { value: 'RETAIL' } })
    // Picking an existing project swaps the free-text input for the append warning.
    expect(screen.queryByPlaceholderText(/RETAIL/i)).toBeNull()
    expect(screen.getByText(/40 already stored/)).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: /Run extraction/i }))
    await waitFor(() => expect(api.runSource).toHaveBeenCalledWith('s1', 'RETAIL', 'c1', true))
  })

  it('still allows a new project id when the schema cannot be listed', async () => {
    vi.mocked(api.destinationProjects).mockRejectedValueOnce(new Error('connection refused'))
    useStore.setState({
      connections: [{ id: 'c1', name: 'Prod DB' }] as never,
      connection: { isConnected: true, activeProfileId: 'c1' } as never,
    })
    await renderSettled(<RunSourceDialog source={SOURCE} onClose={() => {}} onDone={() => {}} />)

    await waitFor(() => expect(screen.getByText(/connection refused/)).toBeTruthy())
    fireEvent.change(screen.getByPlaceholderText(/RETAIL/i), { target: { value: 'P1' } })
    fireEvent.click(screen.getByRole('button', { name: /Run extraction/i }))
    await waitFor(() => expect(api.runSource).toHaveBeenCalledWith('s1', 'P1', 'c1', true))
  })

  it('sends delta upload on by default and off when switched off', async () => {
    useStore.setState({
      connections: [{ id: 'c1', name: 'Prod DB' }] as never,
      connection: { isConnected: true, activeProfileId: 'c1' } as never,
    })
    await renderSettled(<RunSourceDialog source={SOURCE} onClose={() => {}} onDone={() => {}} />)

    const toggle = screen.getByRole('checkbox', { name: /Delta upload/i }) as HTMLInputElement
    expect(toggle.checked).toBe(true)

    fireEvent.click(toggle)
    fireEvent.change(screen.getByPlaceholderText(/RETAIL/i), { target: { value: 'P1' } })
    fireEvent.click(screen.getByRole('button', { name: /Run extraction/i }))

    await waitFor(() => expect(api.runSource).toHaveBeenCalledWith('s1', 'P1', 'c1', false))
  })

  it('shows the checkpoint and lets it be reset', async () => {
    vi.mocked(api.sourceCheckpoint).mockResolvedValue({
      byteOffset: 512, size: 512, signature: 'sig', records: 40,
      updatedAt: '2026-08-06T10:00:00Z', lastError: null,
    })
    useStore.setState({
      connections: [{ id: 'c1', name: 'Prod DB' }] as never,
      connection: { isConnected: true, activeProfileId: 'c1' } as never,
    })
    await renderSettled(<RunSourceDialog source={SOURCE} onClose={() => {}} onDone={() => {}} />)

    await waitFor(() => expect(screen.getByText(/40 records imported/)).toBeTruthy())
    fireEvent.click(screen.getByRole('button', { name: /Reset checkpoint/i }))
    await waitFor(() => expect(api.resetSourceCheckpoint).toHaveBeenCalledWith('s1'))
  })

  it('reports an empty delta run as "nothing new", not a broken regex', async () => {
    vi.mocked(api.runSource).mockResolvedValueOnce({
      records: 0, detail: 'Nothing new to import — the file has not grown since the last import.',
      linesRead: 0,
    } as never)
    useStore.setState({
      connections: [{ id: 'c1', name: 'Prod DB' }] as never,
      connection: { isConnected: true, activeProfileId: 'c1' } as never,
    })
    await renderSettled(<RunSourceDialog source={SOURCE} onClose={() => {}} onDone={() => {}} />)

    fireEvent.change(screen.getByPlaceholderText(/RETAIL/i), { target: { value: 'P1' } })
    fireEvent.click(screen.getByRole('button', { name: /Run extraction/i }))

    await waitFor(() => expect(screen.getByText(/Nothing new to import/)).toBeTruthy())
    expect(screen.queryByText(/No line matched/)).toBeNull()
  })

  it('reopens on the connection and project the source last imported into', async () => {
    const REMEMBERED: Source = {
      ...SOURCE,
      config: { ...SOURCE.config, lastRun: { connectionId: 'c2', titleShort: 'RETAIL' } },
    }
    useStore.setState({
      connections: [{ id: 'c1', name: 'Prod DB' }, { id: 'c2', name: 'Staging DB' }] as never,
      // The app is connected to c1, but the source last imported into c2 — the
      // remembered destination wins.
      connection: { isConnected: true, activeProfileId: 'c1' } as never,
    })
    await renderSettled(<RunSourceDialog source={REMEMBERED} onClose={() => {}} onDone={() => {}} />)

    await waitFor(() => expect(api.destinationProjects).toHaveBeenCalledWith('c2'))
    await waitFor(() =>
      expect((screen.getByLabelText('Project') as HTMLSelectElement).value).toBe('RETAIL'),
    )

    fireEvent.click(screen.getByRole('button', { name: /Run extraction/i }))
    await waitFor(() => expect(api.runSource).toHaveBeenCalledWith('s1', 'RETAIL', 'c2', true))
  })

  it('falls back when the remembered connection is no longer assigned', async () => {
    const REMEMBERED: Source = {
      ...SOURCE,
      config: { ...SOURCE.config, lastRun: { connectionId: 'gone', titleShort: 'RETAIL' } },
    }
    useStore.setState({
      connections: [{ id: 'c1', name: 'Prod DB' }] as never,
      connection: { isConnected: true, activeProfileId: 'c1' } as never,
    })
    await renderSettled(<RunSourceDialog source={REMEMBERED} onClose={() => {}} onDone={() => {}} />)

    await waitFor(() => expect(api.destinationProjects).toHaveBeenCalledWith('c1'))
    // The remembered project belongs to the revoked connection, so it is not restored.
    expect((screen.getByLabelText('Project') as HTMLSelectElement).value).toBe('')
  })

  it('keeps a remembered project that has since been deleted as a new-project id', async () => {
    vi.mocked(api.destinationProjects).mockResolvedValueOnce({
      ok: true, error: null, projects: [],
    } as never)
    const REMEMBERED: Source = {
      ...SOURCE,
      config: { ...SOURCE.config, lastRun: { connectionId: 'c1', titleShort: 'RETAIL' } },
    }
    useStore.setState({
      connections: [{ id: 'c1', name: 'Prod DB' }] as never,
      connection: { isConnected: true, activeProfileId: 'c1' } as never,
    })
    await renderSettled(<RunSourceDialog source={REMEMBERED} onClose={() => {}} onDone={() => {}} />)

    await waitFor(() =>
      expect((screen.getByPlaceholderText(/RETAIL/i) as HTMLInputElement).value).toBe('RETAIL'),
    )
  })

  it('blocks running when no connection is available', async () => {
    useStore.setState({
      connections: [] as never,
      connection: { isConnected: false, activeProfileId: null } as never,
    })
    await renderSettled(<RunSourceDialog source={SOURCE} onClose={() => {}} onDone={() => {}} />)
    expect(screen.getByText(/No connections are assigned to you/i)).toBeTruthy()
    expect((screen.getByRole('button', { name: /Run extraction/i }) as HTMLButtonElement).disabled).toBe(true)
  })
})
