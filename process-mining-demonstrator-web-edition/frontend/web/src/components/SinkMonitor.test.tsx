/** SinkMonitor — the live sink flowchart. jsdom can't lay out ReactFlow, but node
 *  CONTENT renders, so we assert each lane shows its counts, last-event age, and a
 *  liveness dot, plus the empty and module-off states. */

import { describe, expect, it } from 'vitest'
import { screen } from '@testing-library/react'
import { SinkMonitor } from './SinkMonitor'
import { renderSettled } from '../test/renderSettled'
import type { SinkMonitor as SinkMonitorData, SinkMonitorEntry } from '../types'

function entry(over: Partial<SinkMonitorEntry> = {}): SinkMonitorEntry {
  return {
    id: 's1', name: 'Agent sink', port: 8120, activeScheme: 'http',
    titleShort: 'AGENTLOG', connectionId: 'c1', connectionName: 'Prod DB', schema: 'MINING',
    live: true, events: 12, journeys: 3, lastEventAt: new Date().toISOString(), error: null,
    ...over,
  }
}

function data(sinks: SinkMonitorEntry[], over: Partial<SinkMonitorData> = {}): SinkMonitorData {
  return { moduleEnabled: true, supervisorRunning: true, sinks, ...over }
}

describe('SinkMonitor', () => {
  it('renders a lane per sink with counts, last-event age and a green liveness dot', async () => {
    await renderSettled(<SinkMonitor data={data([entry()])} flowing={new Set()} />)

    // The destination-DB counts on the project node.
    expect(screen.getByText(/12 events · 3 journeys/)).toBeTruthy()
    // A recent lastEventAt renders as "just now".
    expect(screen.getByText(/last event just now/)).toBeTruthy()
    // The sink node's liveness dot is green (module on + /health responded).
    const sinkNode = screen.getByText('Agent sink').closest('.ipipe-node') as HTMLElement
    const dot = sinkNode.querySelector('.status-dot') as HTMLElement
    expect(dot.style.background).toContain('--green')
    // The connection node shows the schema.
    expect(screen.getByText(/schema MINING/)).toBeTruthy()
  })

  it('shows a red dot when a sink is not responding, grey when the module is off', async () => {
    const { rerender } = await renderSettled(
      <SinkMonitor data={data([entry({ live: false })])} flowing={new Set()} />,
    )
    let dot = (screen.getByText('Agent sink').closest('.ipipe-node') as HTMLElement)
      .querySelector('.status-dot') as HTMLElement
    expect(dot.style.background).toContain('--red')

    // Module disabled → grey, regardless of the probe result.
    rerender(<SinkMonitor data={data([entry({ live: true })], { moduleEnabled: false })} flowing={new Set()} />)
    dot = (screen.getByText('Agent sink').closest('.ipipe-node') as HTMLElement)
      .querySelector('.status-dot') as HTMLElement
    expect(dot.style.background).toContain('--secondary')
  })

  it('surfaces a per-sink error and omits counts when the DB could not be read', async () => {
    await renderSettled(
      <SinkMonitor
        data={data([entry({ events: null, journeys: null, lastEventAt: null, error: 'Connection refused' })])}
        flowing={new Set()}
      />,
    )
    expect(screen.getByText(/Connection refused/)).toBeTruthy()
    expect(screen.queryByText(/events ·/)).toBeNull()
  })

  it('renders one lane per sink and reuses a shared connection node', async () => {
    // Two sinks pointing at the SAME connection → one shared connection node.
    await renderSettled(
      <SinkMonitor
        data={data([
          entry({ id: 's1', name: 'Sink A', titleShort: 'AAA', events: 5, journeys: 1 }),
          entry({ id: 's2', name: 'Sink B', titleShort: 'BBB', events: 7, journeys: 2 }),
        ])}
        flowing={new Set()}
      />,
    )
    // Both sink lanes render …
    expect(screen.getByText('Sink A')).toBeTruthy()
    expect(screen.getByText('Sink B')).toBeTruthy()
    expect(screen.getByText(/5 events · 1 journeys/)).toBeTruthy()
    expect(screen.getByText(/7 events · 2 journeys/)).toBeTruthy()
    // … but the connection they share appears once (a single reused node).
    expect(screen.getAllByText('Prod DB').length).toBe(1)
  })
})
