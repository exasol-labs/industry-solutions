/** useSinkMonitor — polls the monitor and flags a lane "flowing" when its event count
 *  grows between polls (the sink-side "data is arriving" signal). */

import { afterEach, describe, expect, it, vi } from 'vitest'
import { act, renderHook, waitFor } from '@testing-library/react'
import type { SinkMonitor } from '../types'

const payload = vi.fn<() => SinkMonitor>()
vi.mock('../api', () => ({
  api: { sinkMonitor: vi.fn(async () => payload()) },
}))

import { useSinkMonitor } from './useSinkMonitor'

function snapshot(events: number): SinkMonitor {
  return {
    moduleEnabled: true,
    supervisorRunning: true,
    sinks: [{
      id: 's1', name: 'Sink', port: 8120, activeScheme: 'http', titleShort: 'A',
      connectionId: 'c1', connectionName: 'DB', schema: 'M',
      live: true, events, journeys: 1, lastEventAt: null, error: null,
    }],
  }
}

afterEach(() => vi.clearAllMocks())

describe('useSinkMonitor', () => {
  it('never flags a lane whose event count holds steady', async () => {
    payload.mockReturnValue(snapshot(10)) // every poll: same count
    const { result } = renderHook(() => useSinkMonitor(20))

    await waitFor(() => expect(result.current.data?.sinks[0].events).toBe(10))
    // Give several more polls a chance to run; a steady count is never "flowing".
    await act(async () => {
      await new Promise((r) => setTimeout(r, 80))
    })
    expect(result.current.flowing.size).toBe(0)
  })

  it('flags a lane whose event count keeps growing between polls', async () => {
    // Each poll returns a higher count, so a fresh growth is seen on every tick and the
    // flowing flag stays set — observable without racing a one-tick transition.
    let n = 10
    payload.mockImplementation(() => snapshot((n += 5)))
    const { result } = renderHook(() => useSinkMonitor(20))

    await waitFor(() => expect(result.current.flowing.has('s1')).toBe(true))
  })
})
