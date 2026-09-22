/** Polls the API Server - Event Receiver monitor for the integration console. Slower than the
 *  file-status poll (5 s, not 1.5 s) because every tick reads the destination databases.
 *  Re-polls immediately when the active connection changes. On top of the raw payload it
 *  tracks the previous event count per sink so a lane whose count GREW since the last poll
 *  is flagged `flowing` — the "data is arriving" signal, since sinks keep no throughput
 *  counter of their own. */

import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import { useStore } from '../store'
import type { SinkMonitor } from '../types'

export function useSinkMonitor(pollMs = 5000) {
  const store = useStore()
  const [data, setData] = useState<SinkMonitor | null>(null)
  const [error, setError] = useState<string | null>(null)
  // Sink id → last seen event count, and the ids whose count just grew (→ "flowing").
  const prevEvents = useRef<Map<string, number>>(new Map())
  const [flowing, setFlowing] = useState<Set<string>>(new Set())

  useEffect(() => {
    let alive = true
    const tick = async () => {
      try {
        const next = await api.sinkMonitor()
        if (!alive) return
        const grew = new Set<string>()
        for (const s of next.sinks) {
          const before = prevEvents.current.get(s.id)
          if (typeof s.events === 'number') {
            if (before != null && s.events > before) grew.add(s.id)
            prevEvents.current.set(s.id, s.events)
          }
        }
        // Drop bookkeeping for sinks that no longer exist.
        const ids = new Set(next.sinks.map((s) => s.id))
        for (const id of [...prevEvents.current.keys()]) {
          if (!ids.has(id)) prevEvents.current.delete(id)
        }
        setData(next)
        setFlowing(grew)
        setError(null)
      } catch (err) {
        if (alive) setError(err instanceof Error ? err.message : String(err))
      }
    }
    void tick()
    const id = window.setInterval(tick, pollMs)
    return () => {
      alive = false
      window.clearInterval(id)
    }
  }, [store.connection.isConnected, store.connection.activeProfileId, pollMs])

  return { data, error, flowing }
}
