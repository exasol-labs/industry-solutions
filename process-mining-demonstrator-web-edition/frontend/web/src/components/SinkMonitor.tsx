/** The API Server - Event Receivers as ONE live flowchart, the sink-side sibling of
 *  IntegrationPipeline. There is no run history here — sinks are pushed to by external
 *  agents and keep no stats — so each lane is assembled live from the monitor poll:
 *
 *      [🤖 AI agents] ──▶ [🔌 Sink :port] ──▶ [📊 Project] ──▶ [🛢️ Connection]
 *
 *  One shared "AI agents" source fans out to every sink. The sink node shows a liveness
 *  dot (its /health probe) and its live scheme/port; the project node shows the
 *  destination-DB event/journey counts and when the last event landed; the connection
 *  node (reused when sinks share one) shows the schema. A lane whose event count grew
 *  since the last poll lights up with the travelling dot — the "data arriving" signal. */

import {
  Background,
  BackgroundVariant,
  BaseEdge,
  getBezierPath,
  Handle,
  Position,
  ReactFlow,
  ReactFlowProvider,
  type Edge,
  type EdgeProps,
  type Node,
  type NodeProps,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { useMemo, type CSSProperties } from 'react'
import { flowKeyframes } from '../flow/MetricEdge'
import { relativeTime } from './IntegrationKpis'
import type { SinkMonitor as SinkMonitorData, SinkMonitorEntry } from '../types'

type Liveness = 'live' | 'down' | 'off'

interface SinkNodeData {
  icon: string
  kicker: string
  title: string
  subtitle?: string
  accent: string
  ports: Array<'l' | 'r'>
  dim?: boolean
  liveness?: Liveness // sink node only → a coloured status dot
  badges?: string[] // extra "▦ …" / "🕒 …" rows
  error?: string | null
  [key: string]: unknown
}

const DOT_COLOR: Record<Liveness, string> = {
  live: 'var(--green)',
  down: 'var(--red)',
  off: 'var(--secondary)',
}
const DOT_LABEL: Record<Liveness, string> = {
  live: 'Listener responding',
  down: 'Listener not responding',
  off: 'Module disabled',
}

function SinkNode({ data }: NodeProps) {
  const d = data as SinkNodeData
  return (
    <div
      className="ipipe-node done"
      style={{ ['--node-accent' as string]: d.accent, opacity: d.dim ? 0.72 : 1 } as CSSProperties}
    >
      {d.ports.includes('l') && <Handle type="target" position={Position.Left} id="l" className="ipipe-handle" />}
      <div className="ipipe-row">
        <span className="ipipe-icon" style={{ background: `color-mix(in srgb, transparent, ${d.accent} 20%)`, color: d.accent }}>
          {d.icon}
        </span>
        <div className="ipipe-text">
          <span className="ipipe-kicker">
            {d.liveness && (
              <span
                className="status-dot"
                title={DOT_LABEL[d.liveness]}
                style={{ background: DOT_COLOR[d.liveness], display: 'inline-block', marginRight: 5, verticalAlign: 'middle' }}
              />
            )}
            {d.kicker}
          </span>
          <span className="ipipe-title" title={d.title}>{d.title}</span>
          {d.subtitle && <span className="ipipe-sub" title={d.subtitle}>{d.subtitle}</span>}
        </div>
      </div>

      {d.badges?.map((b, i) => (
        <div className="ipipe-rows" key={i}>{b}</div>
      ))}

      {d.error && (
        <div className="ipipe-rows" style={{ color: 'var(--red)' }} title={d.error}>
          ⚠ {d.error}
        </div>
      )}

      {d.ports.includes('r') && <Handle type="source" position={Position.Right} id="r" className="ipipe-handle" />}
    </div>
  )
}

const nodeTypes = { sink: SinkNode }

const FLOW_SECS_PER_EDGE = 0.9

interface SinkEdgeData {
  flowing?: boolean
  flowIndex?: number
  stroke?: string
  width?: number
  [key: string]: unknown
}

/** Straight-through edge; while its lane is "flowing" (event count grew) a single dot
 *  travels agents→sink→project→connection in order, reusing the app's `flowKeyframes`. */
function SinkEdge({ id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, data }: EdgeProps) {
  const d = (data ?? {}) as SinkEdgeData
  const [path] = getBezierPath({ sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition })
  return (
    <>
      <BaseEdge id={id} path={path} style={{ stroke: d.stroke ?? 'var(--border)', strokeWidth: d.width ?? 2 }} />
      {d.flowing
        ? (() => {
            const FLOW_TOTAL = 3
            const total = FLOW_TOTAL * FLOW_SECS_PER_EDGE
            const kf = flowKeyframes(d.flowIndex ?? 0, FLOW_TOTAL)
            return (
              <circle r={5} fill="var(--accent)" stroke="#fff" strokeWidth={1.5} opacity={0}>
                <animateMotion dur={`${total}s`} repeatCount="indefinite" calcMode="linear" keyPoints={kf.keyPoints} keyTimes={kf.keyTimes} path={path} />
                <animate attributeName="opacity" dur={`${total}s`} repeatCount="indefinite" calcMode="discrete" keyTimes={kf.opacityTimes} values={kf.opacityValues} />
              </circle>
            )
          })()
        : null}
    </>
  )
}

const edgeTypes = { sink: SinkEdge }

// Layout: four fixed columns, one horizontal lane per sink.
const COL = { agents: 0, sink: 260, project: 540, conn: 830 }
const LANE_GAP = 132
const NODE_W = 210
const NODE_H = 96
const NODE_DIMS = {
  measured: { width: NODE_W, height: NODE_H },
  initialWidth: NODE_W,
  initialHeight: NODE_H,
}
const MIN_CANVAS_H = 320

export function SinkMonitor({ data, flowing }: { data: SinkMonitorData; flowing: Set<string> }) {
  const { nodes, edges, canvasH } = useMemo(() => {
    const sinks = data.sinks
    const n = Math.max(sinks.length, 1)
    const centerY = ((n - 1) * LANE_GAP) / 2
    const laneY = (i: number) => i * LANE_GAP

    const nodes: Node[] = []
    const edges: Edge[] = []

    // The one shared source: all agents push into all sinks.
    nodes.push({
      id: 'agents', type: 'sink', draggable: true, ...NODE_DIMS,
      position: { x: COL.agents, y: centerY },
      data: {
        icon: '🤖', kicker: 'Source', title: 'AI agents',
        subtitle: 'push journey events', accent: 'var(--purple, #9b59d0)', ports: ['r'],
        dim: !data.moduleEnabled,
      } satisfies SinkNodeData,
    })

    // Reuse a connection node when several sinks share one destination connection.
    const connY = new Map<string, number[]>()
    for (let i = 0; i < sinks.length; i++) {
      const s = sinks[i]
      const key = s.connectionId || `none:${s.id}`
      if (!connY.has(key)) connY.set(key, [])
      connY.get(key)!.push(laneY(i))
    }

    const liveness = (s: SinkMonitorEntry): Liveness =>
      !data.moduleEnabled ? 'off' : s.live ? 'live' : 'down'

    sinks.forEach((s, i) => {
      const y = laneY(i)
      const lane = flowing.has(s.id)
      const laneStroke = lane ? 'var(--green)' : s.error ? 'var(--red)' : 'var(--blue, #3b82f6)'
      const connKey = s.connectionId || `none:${s.id}`

      // Sink node.
      nodes.push({
        id: `sink:${s.id}`, type: 'sink', draggable: true, ...NODE_DIMS,
        position: { x: COL.sink, y },
        data: {
          icon: '🔌', kicker: 'Event Receiver', title: s.name,
          subtitle: s.port ? `${s.activeScheme} · port ${s.port}` : 'no port',
          accent: 'var(--accent)', ports: ['l', 'r'], liveness: liveness(s),
        } satisfies SinkNodeData,
      })

      // Project node (destination-DB counts).
      const counts =
        s.events == null
          ? []
          : [
              `▦ ${s.events.toLocaleString()} events · ${(s.journeys ?? 0).toLocaleString()} journeys`,
              `🕒 last event ${relativeTime(s.lastEventAt)}`,
            ]
      nodes.push({
        id: `proj:${s.id}`, type: 'sink', draggable: true, ...NODE_DIMS,
        position: { x: COL.project, y },
        data: {
          icon: '📊', kicker: 'Project', title: s.titleShort || '(no code)',
          subtitle: 'journeys table', accent: 'var(--orange, #e08a1e)', ports: ['l', 'r'],
          badges: counts, error: s.error,
        } satisfies SinkNodeData,
      })

      // Connection node — placed once, at the mean lane of the sinks that share it.
      const connNodeId = `conn:${connKey}`
      if (!nodes.some((nd) => nd.id === connNodeId)) {
        const ys = connY.get(connKey) ?? [y]
        const meanY = ys.reduce((a, b) => a + b, 0) / ys.length
        nodes.push({
          id: connNodeId, type: 'sink', draggable: true, ...NODE_DIMS,
          position: { x: COL.conn, y: meanY },
          data: {
            icon: '🛢️', kicker: 'Connection',
            title: s.connectionName || '(no connection)',
            subtitle: s.schema ? `schema ${s.schema}` : 'destination database',
            accent: 'var(--teal, #1a9e8f)', ports: ['l'],
          } satisfies SinkNodeData,
        })
      }

      // Lane edges: agents → sink → project → connection.
      const mk = (from: string, to: string, flowIndex: number): Edge => ({
        id: `${from}->${to}`, source: from, target: to, sourceHandle: 'r', targetHandle: 'l',
        type: 'sink',
        data: { flowing: lane, flowIndex, stroke: laneStroke, width: lane ? 2.6 : 2 } satisfies SinkEdgeData,
      })
      edges.push(mk('agents', `sink:${s.id}`, 0))
      edges.push(mk(`sink:${s.id}`, `proj:${s.id}`, 1))
      edges.push(mk(`proj:${s.id}`, connNodeId, 2))
    })

    const canvasH = Math.max(MIN_CANVAS_H, n * LANE_GAP + 80)
    return { nodes, edges, canvasH }
  }, [data, flowing])

  return (
    <div className="ipipe-canvas" style={{ height: canvasH }}>
      <ReactFlowProvider>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
          fitView
          fitViewOptions={{ padding: 0.16 }}
          nodesConnectable={false}
          nodesDraggable
          elementsSelectable={false}
          panOnDrag
          zoomOnScroll={false}
          proOptions={{ hideAttribution: true }}
          minZoom={0.3}
          maxZoom={1.5}
        >
          <Background variant={BackgroundVariant.Dots} gap={22} size={1} />
        </ReactFlow>
      </ReactFlowProvider>
    </div>
  )
}
