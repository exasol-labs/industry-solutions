import { afterEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'

vi.mock('../api', () => ({
  api: {
    createSource: vi.fn(async () => ({})),
    updateSource: vi.fn(async () => ({})),
    listSourceTypes: vi.fn(async () => []),
    listConnections: vi.fn(async () => [{ id: 'c1', name: 'Prod DB' }]),
    listSinkPorts: vi.fn(async () => ({
      pool: [8120, 8121, 8122],
      https: { '8120': 8483, '8121': 8484, '8122': 8485 },
      used: {},
    })),
    sourceCheckpoint: vi.fn(async () => ({
      byteOffset: 0, size: 0, signature: '', records: 0, updatedAt: null, lastError: null,
    })),
    previewSource: vi.fn(async () => ({ lines: ['line one', 'line two'], truncated: true })),
  },
}))

import { api } from '../api'
import { SourceWizard } from './SourceWizard'
import { renderSettled } from '../test/renderSettled'

afterEach(() => vi.clearAllMocks())

describe('SourceWizard', () => {
  it('creates a File source with its config', async () => {
    const onSaved = vi.fn()
    await renderSettled(<SourceWizard onClose={() => {}} onSaved={onSaved} />)

    // Step 1: File is preselected → Next
    fireEvent.click(screen.getByRole('button', { name: /^Next$/ }))

    // Step 2: name + the file path field
    fireEvent.change(screen.getByPlaceholderText(/access log/i), {
      target: { value: 'Access log' },
    })
    fireEvent.change(screen.getByPlaceholderText(/export\.xml/i), {
      target: { value: '/data/logs/access.log' },
    })
    fireEvent.click(screen.getByRole('button', { name: /^Next$/ }))

    // Step 3: review → create
    fireEvent.click(screen.getByRole('button', { name: /Create source/i }))

    await waitFor(() => expect(api.createSource).toHaveBeenCalled())
    const body = (api.createSource as unknown as ReturnType<typeof vi.fn>).mock.calls[0][0]
    expect(body).toMatchObject({ name: 'Access log', kind: 'file' })
    expect(body.config.path).toBe('/data/logs/access.log')
    expect(onSaved).toHaveBeenCalled()
  })

  it('offers the API Server - Event Receiver kind with connection + port fields', async () => {
    await renderSettled(<SourceWizard onClose={() => {}} onSaved={() => {}} />)
    // Pick the sink kind (it is selectable, not a "coming soon" placeholder).
    fireEvent.click(screen.getByText('API Server - Event Receiver'))
    fireEvent.click(screen.getByRole('button', { name: /^Next$/ }))
    // Step 2 renders the sink's fields: a connection picker, a project code, a port.
    expect(await screen.findByText(/Project code/)).toBeTruthy()
    expect(screen.getByText(/Connection/)).toBeTruthy()
    expect(screen.getByText(/^Port/)).toBeTruthy()
    // The TLS (HTTPS) preference checkbox is offered.
    expect(screen.getByText(/TLS \(address agents over HTTPS\)/)).toBeTruthy()
    // Each port slot is offered showing BOTH its HTTP and HTTPS port (loaded async).
    expect(await screen.findByRole('option', { name: /HTTP 8120 · HTTPS 8483/ })).toBeTruthy()
  })

  it('creates a sink and shows its one-time token', async () => {
    ;(api.createSource as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      id: 's1', name: 'Agent sink', kind: 'ai-agent-logging-sink', token: 'secret-token-xyz',
    })
    const onSaved = vi.fn()
    await renderSettled(<SourceWizard onClose={() => {}} onSaved={onSaved} />)
    fireEvent.click(screen.getByText('API Server - Event Receiver'))
    fireEvent.click(screen.getByRole('button', { name: /^Next$/ }))
    fireEvent.change(screen.getByPlaceholderText(/access log/i), {
      target: { value: 'Agent sink' },
    })
    await screen.findByRole('option', { name: /HTTP 8120/ }) // ports loaded
    fireEvent.change(screen.getByDisplayValue('— pick a connection —'), { target: { value: 'c1' } })
    fireEvent.change(screen.getByPlaceholderText(/AGENTLOG/i), { target: { value: 'AGENTLOG' } })
    fireEvent.change(screen.getByDisplayValue('— pick a port —'), { target: { value: '8120' } })
    fireEvent.click(screen.getByRole('button', { name: /^Next$/ }))
    fireEvent.click(screen.getByRole('button', { name: /Create source/i }))
    expect(await screen.findByDisplayValue('secret-token-xyz')).toBeTruthy()
    expect(onSaved).toHaveBeenCalled()
  })
})
