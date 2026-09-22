import {
  Background,
  BackgroundVariant,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  type Edge,
  type Node,
  type NodeChange,
  type Viewport,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
} from 'react'

import {
  EDGE_SCHEMA_GRADIENTS,
  groupColor as groupColorFor,
  interpolate,
  type EdgeColorSchema,
} from '../graph/colors'
import { EdgeColorWizard } from './EdgeColorWizard'
import { actionMatchesNode } from '../actions/describe'
import type { SavedAction } from '../actions/types'
import type { AggregateLink } from '../aggregate/types'
import { subgraphForMembers } from '../aggregate/explode'
import {
  boundsFromCenter,
  boundsFromRect,
  computeGuides,
  type HLine,
  type VLine,
} from './alignGuides'
import {
  GRID_SIZE,
  NODE_W,
  computeLayout,
  defaultNodeHeight,
  groupRects,
  type Point,
} from '../graph/layout'
import {
  edgeSchemaKey,
  projectKeys,
  readJSON,
  useSetting,
  writeJSON,
} from '../settings'
import {
  maxMetricValue,
  type GraphStartMode,
  type ProcessGraph,
  type ProcessNote,
  type ProcessTransition,
  type StepInfo,
  type TransitionMetric,
} from '../types'
import { AggregatePickContext } from './aggregatePickContext'
import { computeFocus, FlowFocusContext, type FlowFocus } from './focusContext'
import { GroupBoxNode, type GroupBoxData } from './GroupBoxNode'
import { MARKER_H, MARKER_W, MarkerNode } from './MarkerNode'
import { MetricEdge, type MetricEdgeData } from './MetricEdge'
import { StepNode, type StepNodeData } from './StepNode'
import { TransitionTablePanel } from './TransitionTablePanel'
import type { Node as RFNode } from '@xyflow/react'

const nodeTypes = { step: StepNode, groupBox: GroupBoxNode, marker: MarkerNode }
const edgeTypes = { metric: MetricEdge }

// How close (in SCREEN pixels, at any zoom) an edge must come to a neighbour's edge before
// an alignment guide appears and the node snaps to it.
const GUIDE_SCREEN_PX = 7

const GROUP_PREFIX = '__group__'
const collapsedNodeId = (group: string) => `${GROUP_PREFIX}${group}`
const virtualGroupOf = (id: string) =>
  id.startsWith(GROUP_PREFIX) ? id.slice(GROUP_PREFIX.length) : null

export type NodeAction = 'include' | 'exclude'

/** Shared viewport + node positions between the two A/B panels ("valve open"). */
export interface SyncState {
  viewport: Viewport | null
  nodeOverrides: Record<string, Point>
  version: number
}

export function createSyncState(): SyncState {
  return { viewport: null, nodeOverrides: {}, version: 0 }
}

export interface FlowChartProps {
  graph: ProcessGraph
  projectId: number | string
  /** Included in the persistence key, exactly like the Swift `chartMode`. */
  chartMode: string
  metric: TransitionMetric
  isLoading?: boolean
  /** When provided, viewport and node drags are mirrored to the other panel. */
  syncState?: SyncState | null
  onSyncChange?: () => void
  skipInitialFit?: boolean
  onNodeAction?: (node: string, action: NodeAction) => void
  notes?: ProcessNote[]
  onNodeNote?: (node: string) => void
  onEdgeNote?: (transition: ProcessTransition) => void
  /** Open the "Meta Infos" panel for a node (lists that node's valid META values). */
  onMetaInfo?: (node: string) => void
  /** Target-process / conformance overlay. */
  normValues?: Record<string, number> | null
  normMetric?: TransitionMetric
  showCompliance?: boolean
  normIsMinimum?: boolean
  onEdgeTap?: (transition: ProcessTransition, screen: { x: number; y: number }) => void
  /** Red note shown in the canvas's top-right corner (e.g. a simulation warning). */
  notice?: string | null
  /** Read-only source (a simulation): hide the interactive filter actions
   *  (Require / Exclude) from the node context menu. */
  readOnly?: boolean
  /** Total filtered journeys — the denominator for the 'Journey %' edge metric. */
  journeyTotal?: number
  /** Lay the flow left-to-right (columns) instead of the default top-to-bottom. */
  horizontal?: boolean
  /** Hover-dwell focus: resting on a node spotlights it and its edges and dims the rest,
   *  for inspecting a step's neighbourhood in a crowded map. Default on; the Individual
   *  Journey (a single, already-sparse trace) turns it off. The dwell delay is the user's
   *  "Highlight Trigger" setting (0 disables it entirely). */
  hoverFocus?: boolean
  /** Offer the ▦ button that opens the underlying transition table. Enabled on the
   *  A-Chart, B-Chart and A/B panels; the button itself is still hidden unless the user
   *  turns it on in Configuration → Layout. */
  allowTransitionTable?: boolean
  /** Saved node-menu actions available for this project (the caller passes only when the
   *  Actions feature is enabled and the user may run them). The node menu lists those
   *  whose AVAILABILITY matches the clicked node. */
  actionItems?: SavedAction[]
  onRunAction?: (action: SavedAction, node: string) => void
  /** When set, the map offers an aggregate "select steps" mode (developers only — the
   *  caller gates this). The user banks one or more connected groups of steps; on Create
   *  the banked groups (each a list of step names) are handed back to build the map. */
  onCreateAggregate?: (groups: string[][]) => void
  /** True when the current project is itself a high-level aggregate map — the action bar
   *  then reads "Add to map" (append) rather than "Create map". */
  isHighLevelMap?: boolean
  /** Σ drill-down: a node whose name matches a link's sigmaStep gets a "Drill down" item. */
  aggregateLinks?: AggregateLink[]
  onDrillDown?: (link: AggregateLink) => void
  /** Second drill-down option: load the detail into THIS canvas (in-place). */
  onDrillDownInPlace?: (link: AggregateLink) => void
  /** When set, the map is an in-place drill of a detail sub-process: every node's menu
   *  offers "⤴ Drill up" to return to the high-level map. */
  onDrillUp?: () => void
  /** Re-fit the view whenever the chart container is resized (for a resizable panel). */
  fitOnResize?: boolean
  /** In-place EXPLODE seeding: keep the high-level map's node positions stable and only
   *  lay out the revealed member steps in the Σ node's spot (pushing downstream nodes down
   *  to make room), so surrounding steps/groups don't move or re-layout. */
  explode?: {
    baseGraph: ProcessGraph
    baseProjectId: number | string
    baseChartMode: string
    aggregates: { sigmaStep: string; members: string[] }[]
    expanded: string[]
  }
}

interface MenuState {
  kind: 'node' | 'edge'
  node?: string
  transition?: ProcessTransition
  x: number
  y: number
}

function FlowChartInner(props: FlowChartProps) {
  const {
    graph,
    projectId,
    chartMode,
    metric,
    isLoading = false,
    syncState = null,
    onSyncChange,
    skipInitialFit = false,
    onNodeAction,
    notes,
    onNodeNote,
    onEdgeNote,
    onMetaInfo,
    normValues = null,
    normMetric = 'Count',
    showCompliance = false,
    normIsMinimum = false,
    onEdgeTap,
    journeyTotal = 0,
    hoverFocus = true,
    allowTransitionTable = false,
    horizontal = false,
  } = props

  const flow = useReactFlow()
  const wrapRef = useRef<HTMLDivElement>(null)

  const [showGrouping] = useSetting<boolean>('processmap.showGrouping')
  const [showNodeDescriptions] = useSetting<boolean>('processmap.showNodeDescriptions')
  const [nodeScale] = useSetting<number>('graph.node.scale')
  const [edgeScale] = useSetting<number>('graph.edge.scale')
  const [groupScale] = useSetting<number>('graph.group.scale')
  const [optimisedLayout] = useSetting<boolean>('graph.optimisedLayout')
  const [colorizeByWeight] = useSetting<boolean>('graph.edge.colorizeByWeight')
  const [highlightTriggerMs] = useSetting<number>('graph.highlightTriggerMs')
  const [showTableButton] = useSetting<boolean>('graph.showTransitionTableButton')
  const [graphStartMode] = useSetting<GraphStartMode>('graph.startMode')
  // The schema for the *displayed* metric is reactive so the legend and edges
  // update instantly when it is changed in the colour wizard.
  const [activeSchema] = useSetting<EdgeColorSchema>(edgeSchemaKey(metric))

  // Dragged/saved node positions are orientation-specific: the horizontal layout keeps its
  // own set (suffix ":h") so toggling orientation reflows instead of loading the other
  // orientation's coordinates. Vertical keeps the original key, so existing saved layouts
  // stay valid.
  const layoutKey = projectKeys.layout(projectId, horizontal ? `${chartMode}:h` : chartMode)
  const collapsedKey = projectKeys.collapsedGroups(projectId, chartMode)

  const [overrides, setOverrides] = useState<Record<string, Point>>(() =>
    readJSON<Record<string, Point>>(layoutKey, {}),
  )
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(new Set())
  const [menu, setMenu] = useState<MenuState | null>(null)
  // Alignment guides shown while dragging a step or group: the lines are kept in flow
  // coordinates and projected to screen space at render time with the live viewport.
  const [guides, setGuides] = useState<{
    vertical: VLine[]
    horizontal: HLine[]
    vp: Viewport
  } | null>(null)
  const [descriptionNode, setDescriptionNode] = useState<string | null>(null)
  // Aggregate "pick steps" mode. A self-contained selection we control (ReactFlow's own
  // multi-select proved unreliable here): a toggle turns the map into a picker, plain
  // clicks add/remove steps, and an action bar creates or cancels.
  const [aggregateMode, setAggregateMode] = useState(false)
  const [picked, setPicked] = useState<Set<string>>(new Set())
  // Groups already banked this session (each a list of step names). Their steps are locked
  // out of further picking so a step can belong to only one aggregate.
  const [bankedGroups, setBankedGroups] = useState<string[][]>([])
  const bankedSet = useMemo(() => new Set(bankedGroups.flat()), [bankedGroups])
  const pickValue = useMemo(
    () => ({ active: aggregateMode, picked, banked: bankedSet }),
    [aggregateMode, picked, bankedSet],
  )
  const togglePicked = useCallback(
    (id: string) => {
      if (bankedSet.has(id)) return // already banked into a group — locked
      setPicked((prev) => {
        const next = new Set(prev)
        if (next.has(id)) next.delete(id)
        else next.add(id)
        return next
      })
    },
    [bankedSet],
  )
  const bankGroup = useCallback(() => {
    setPicked((prev) => {
      if (prev.size >= 2) setBankedGroups((gs) => [...gs, [...prev]])
      return new Set()
    })
  }, [])
  const exitAggregateMode = useCallback(() => {
    setAggregateMode(false)
    setPicked(new Set())
    setBankedGroups([])
  }, [])
  const [zoom, setZoom] = useState(1)
  const [showColorWizard, setShowColorWizard] = useState(false)
  const [showTable, setShowTable] = useState(false)
  // Hover-dwell focus (null unless a node has been rested on long enough). Held as state so
  // only the leaf node/edge components that consume FlowFocusContext re-render when it
  // changes — the node arrays and their caches are untouched.
  const [focus, setFocus] = useState<FlowFocus | null>(null)
  const dwellTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const clearDwell = useCallback(() => {
    if (dwellTimer.current) {
      clearTimeout(dwellTimer.current)
      dwellTimer.current = null
    }
  }, [])

  const allGroupNames = useMemo(
    () =>
      new Set(
        Object.values(graph.steps)
          .map((s) => s.belongsTo)
          .filter((g): g is string => !!g),
      ),
    [graph.steps],
  )

  // ── Initial collapse state (per project, per graph.startMode) ────────────
  const appliedGroupProject = useRef<number | string>(-1)
  useEffect(() => {
    if (allGroupNames.size === 0) return
    if (appliedGroupProject.current === projectId) return
    appliedGroupProject.current = projectId

    if (graphStartMode === 'expanded') setCollapsedGroups(new Set())
    else if (graphStartMode === 'collapsed') setCollapsedGroups(new Set(allGroupNames))
    else {
      const stored = readJSON<string[]>(collapsedKey, [])
      setCollapsedGroups(new Set(stored.filter((g) => allGroupNames.has(g))))
    }
  }, [projectId, graphStartMode, allGroupNames, collapsedKey])

  const toggleGroup = useCallback(
    (group: string) => {
      setCollapsedGroups((prev) => {
        const next = new Set(prev)
        if (next.has(group)) next.delete(group)
        else next.add(group)
        if (graphStartMode === 'persisted') writeJSON(collapsedKey, [...next])
        return next
      })
    },
    [graphStartMode, collapsedKey],
  )

  // ── Collapse resolution (ports resolvedSteps / resolvedTransitions) ──────

  const nodesInGroup = useCallback(
    (group: string) =>
      Object.entries(graph.steps)
        .filter(([, step]) => step.belongsTo === group)
        .map(([name]) => name),
    [graph.steps],
  )

  const resolvedStep = useCallback(
    (step: string) => {
      for (const group of collapsedGroups) {
        if (graph.steps[step]?.belongsTo === group) return collapsedNodeId(group)
      }
      return step
    },
    [collapsedGroups, graph.steps],
  )

  const drawGraph = useMemo<ProcessGraph>(() => {
    if (collapsedGroups.size === 0) return graph

    // Counts summed, times weighted-averaged; intra-group edges dropped.
    const acc = new Map<
      string,
      { from: string; to: string; occ: number; wTime: number; wCount: number }
    >()
    for (const t of graph.transitions) {
      const from = resolvedStep(t.fromStep)
      const to = resolvedStep(t.toStep)
      if (from === to) continue
      const key = `${from}->${to}`
      const entry = acc.get(key) ?? { from, to, occ: 0, wTime: 0, wCount: 0 }
      entry.occ += t.occurrences
      if (t.avgSecs != null) {
        entry.wTime += t.avgSecs * t.occurrences
        entry.wCount += t.occurrences
      }
      acc.set(key, entry)
    }
    const transitions: ProcessTransition[] = [...acc.values()].map((e) => ({
      fromStep: e.from,
      toStep: e.to,
      occurrences: e.occ,
      avgSecs: e.wCount > 0 ? e.wTime / e.wCount : null,
      medianSecs: null, // not recoverable from merged per-edge sums
      minSecs: null,
      maxSecs: null,
      stdDevSecs: null,
    }))

    const steps: Record<string, StepInfo> = { ...graph.steps }
    for (const group of collapsedGroups) {
      for (const member of nodesInGroup(group)) delete steps[member]
      steps[collapsedNodeId(group)] = {
        step: group,
        description: '',
        bgColor: 'accentColor',
        fgColor: 'white',
        score: null,
        shape: 'stadium',
        endOfProcess: false,
        belongsTo: null,
        eventTime: null,
      }
    }
    return { steps, transitions }
  }, [graph, collapsedGroups, nodesInGroup, resolvedStep])

  // ── Hover-dwell focus ────────────────────────────────────────────────────
  //
  // Rest on a step node for DWELL_MS and it, its neighbours and its edges light up while
  // the rest of the map dims — for reading one step's connections in a crowded chart. Only
  // real step nodes trigger it (not group boxes or start/end markers).
  const onNodeMouseEnter = useCallback(
    (_: React.MouseEvent, node: RFNode) => {
      // A 0 ms trigger means the user has turned the spotlight off entirely.
      if (!hoverFocus || highlightTriggerMs <= 0 || node.type !== 'step') return
      clearDwell()
      const id = node.id
      dwellTimer.current = setTimeout(() => {
        setFocus(computeFocus(drawGraph.transitions, id))
      }, highlightTriggerMs)
    },
    [hoverFocus, highlightTriggerMs, clearDwell, drawGraph],
  )

  const endFocus = useCallback(() => {
    clearDwell()
    setFocus(null)
  }, [clearDwell])

  // Never leave a dangling timer if the chart unmounts mid-dwell.
  useEffect(() => clearDwell, [clearDwell])

  // Node scale grows the node box AND the font together, so text always stays
  // inside; the layout uses the scaled dimensions so nodes never overlap.
  const scale = nodeScale || 1
  const nodeW = Math.round(NODE_W * scale)
  const nodeH = Math.round(defaultNodeHeight(graph) * scale)

  const gLabelScale = groupScale || 1
  // Normalise the edge-font size against its "M" baseline so bigger edge labels get more
  // vertical room in the auto-layout (they sit between the layers).
  const edgeLabelScale = Math.max(1, (edgeScale || 3.375) / 3.375)
  const explode = props.explode
  const layout = useMemo(() => {
    if (!explode) {
      return computeLayout(graph, nodeH, optimisedLayout, nodeW, gLabelScale, edgeLabelScale, horizontal)
    }
    // Explode/in-place expansion seeds positions with a vertical "push-down" and is never
    // combined with the horizontal toggle (the caller only wires horizontal on the plain map).
    // Explode seeding — keep the high-level map's positions; only the revealed members move.
    const base = computeLayout(
      explode.baseGraph, nodeH, optimisedLayout, nodeW, gLabelScale, edgeLabelScale,
    )
    const baseKey = projectKeys.layout(explode.baseProjectId, explode.baseChartMode)
    const savedBase = readJSON<Record<string, Point>>(baseKey, {})
    const basePos: Record<string, Point> = { ...base.nodePositions, ...savedBase }

    // Members of each currently-expanded Σ, grouped by their Σ node.
    const expandedSet = new Set(explode.expanded)
    const bySigma: Record<string, string[]> = {}
    for (const a of explode.aggregates) {
      if (!expandedSet.has(a.sigmaStep)) continue
      bySigma[a.sigmaStep] = a.members.filter((m) => graph.steps[m])
    }

    const pos: Record<string, Point> = {}
    // Surrounding + still-collapsed Σ nodes keep exactly their high-level position.
    for (const node of Object.keys(graph.steps)) {
      if (basePos[node]) pos[node] = basePos[node]
    }
    // Place each expanded Σ's members as a compact sub-layout centred on the Σ's old spot,
    // then shove everything BELOW the Σ down so the expansion inserts vertical space
    // instead of overlapping the map underneath it.
    for (const [sigma, members] of Object.entries(bySigma)) {
      const at = basePos[sigma]
      if (!at || members.length === 0) continue
      const sub = computeLayout(
        subgraphForMembers(graph, members), nodeH, optimisedLayout, nodeW, gLabelScale, edgeLabelScale,
      )
      const mp = members.map((m) => sub.nodePositions[m]).filter((p): p is Point => !!p)
      if (mp.length === 0) continue
      const minY = Math.min(...mp.map((p) => p.y))
      const maxY = Math.max(...mp.map((p) => p.y))
      const cx = mp.reduce((a, p) => a + p.x, 0) / mp.length
      const height = maxY - minY + nodeH
      // Extra vertical space this expansion needs beyond the single Σ node it replaces.
      const extra = Math.max(0, height - nodeH)
      // Push down everything strictly below the Σ node's row.
      for (const node of Object.keys(pos)) {
        if (node !== sigma && pos[node].y > at.y + 1) pos[node] = { ...pos[node], y: pos[node].y + extra }
      }
      // Now drop the members in, top-aligned to where the Σ node's top was.
      const topY = at.y - nodeH / 2
      for (const m of members) {
        const p = sub.nodePositions[m]
        if (p) pos[m] = { x: at.x + (p.x - cx), y: topY + (p.y - minY) + nodeH / 2 }
      }
    }
    const xs = Object.values(pos).map((p) => p.x)
    const ys = Object.values(pos).map((p) => p.y)
    return {
      nodePositions: pos,
      canvasSize: {
        width: Math.max(400, (xs.length ? Math.max(...xs) : 0) + nodeW),
        height: Math.max(300, (ys.length ? Math.max(...ys) : 0) + nodeH),
      },
    }
  }, [explode, graph, nodeH, nodeW, optimisedLayout, gLabelScale, edgeLabelScale, horizontal])

  const effectiveOverrides = syncState ? syncState.nodeOverrides : overrides

  /** Auto-layout ∪ user drags, with collapsed groups folded into a centroid. */
  const positions = useMemo<Record<string, Point>>(() => {
    const base: Record<string, Point> = { ...layout.nodePositions, ...effectiveOverrides }
    if (collapsedGroups.size === 0) return base

    const result = { ...base }
    for (const group of collapsedGroups) {
      const members = nodesInGroup(group)
      const vid = collapsedNodeId(group)
      const hasOverride = result[vid] != null
      const points = members.map((m) => result[m]).filter(Boolean) as Point[]
      for (const m of members) delete result[m]
      if (!hasOverride && points.length > 0) {
        result[vid] = {
          x: points.reduce((s, p) => s + p.x, 0) / points.length,
          y: points.reduce((s, p) => s + p.y, 0) / points.length,
        }
      }
    }
    return result
  }, [layout.nodePositions, effectiveOverrides, collapsedGroups, nodesInGroup])

  // Which node names currently have a position. This set only changes when nodes
  // are added/removed (collapse, project switch) — NOT while dragging — so edges
  // that depend on it stay referentially stable during a drag. ReactFlow re-routes
  // the edges from the live node positions itself, so they still follow the drag.
  const positionedKey = Object.keys(positions).sort().join(' ')
  const positionedIds = useMemo(
    () => new Set(positionedKey ? positionedKey.split(' ') : []),
    [positionedKey],
  )

  // ── Start / end process markers ─────────────────────────────────────────

  const { startNodes, endNodes } = useMemo(() => {
    const real = drawGraph.transitions.filter((t) => t.fromStep !== t.toStep)
    const targets = new Set(real.map((t) => t.toStep))
    const sources = new Set(real.map((t) => t.fromStep))
    const names = Object.keys(drawGraph.steps)
    return {
      startNodes: names.filter((n) => !targets.has(n)),
      endNodes: names.filter((n) => !sources.has(n)),
    }
  }, [drawGraph])

  const boxes = useMemo(
    () =>
      showGrouping
        ? groupRects(graph, positions, collapsedGroups, nodeH, collapsedNodeId, nodeW, gLabelScale)
        : [],
    [showGrouping, graph, positions, collapsedGroups, nodeH, nodeW, gLabelScale],
  )

  // ── Note lookup ─────────────────────────────────────────────────────────

  const { noteNodes, noteEdges, noteCounts } = useMemo(() => {
    const nodesWithNotes = new Set<string>()
    const edgesWithNotes = new Set<string>()
    const counts = new Map<string, number>() // "node:<name>" / "edge:<from>-><to>" → count
    for (const note of notes ?? []) {
      let key: string | null = null
      if (note.target.type === 'edge') {
        const e = `${note.target.from}->${note.target.to}`
        edgesWithNotes.add(e)
        key = `edge:${e}`
      } else if (note.target.value) {
        nodesWithNotes.add(note.target.value)
        key = `node:${note.target.value}`
      }
      if (key) counts.set(key, (counts.get(key) ?? 0) + 1)
    }
    return { noteNodes: nodesWithNotes, noteEdges: edgesWithNotes, noteCounts: counts }
  }, [notes])

  // ── ReactFlow nodes ─────────────────────────────────────────────────────
  //
  // Node objects are memoised by a content signature: a node whose position and
  // data are unchanged keeps its exact object reference across re-derivations, so
  // ReactFlow (and the memoised node components) skip re-rendering it. Without
  // this, every re-derive minted all-new node objects and ReactFlow re-rendered
  // *all* nodes on every pointermove of a single-node drag.
  const nodeCache = useRef(new Map<string, { sig: string; node: Node }>())
  // Stable per-object id for StepInfo values, so the signature changes when the
  // underlying step object is replaced (a structural change) but not on a drag.
  const stepIds = useRef({ map: new WeakMap<object, number>(), seq: 0 })
  const stepIdOf = useCallback((s: object) => {
    const store = stepIds.current
    let id = store.map.get(s)
    if (id == null) {
      id = ++store.seq
      store.map.set(s, id)
    }
    return id
  }, [])

  const rfNodes = useMemo<Node[]>(() => {
    const cache = nodeCache.current
    const seen = new Set<string>()
    const result: Node[] = []
    const emit = (id: string, sig: string, build: () => Node) => {
      seen.add(id)
      const hit = cache.get(id)
      if (hit && hit.sig === sig) {
        result.push(hit.node)
        return
      }
      const node = build()
      cache.set(id, { sig, node })
      result.push(node)
    }

    for (const { name, rect } of boxes) {
      const id = `box:${name}`
      const color = groupColorFor(name)
      const collapsed = collapsedGroups.has(name)
      emit(
        id,
        `box|${rect.x}|${rect.y}|${rect.width}|${rect.height}|${color}|${collapsed ? 1 : 0}|${groupScale}`,
        () => ({
          id,
          type: 'groupBox',
          position: { x: rect.x, y: rect.y },
          // Declared size so ReactFlow keeps the node dimensioned AND keeps its
          // handle bounds when it rebuilds the internal node on a drag (new object
          // ref). `measured` makes adoptUserNodes/parseHandles preserve the existing
          // handleBounds; without it the box + members flip to visibility:hidden and
          // every connected edge drops out (isNodeInitialized → false) for the whole
          // drag, since a position-only change never re-fires the ResizeObserver.
          measured: { width: rect.width, height: rect.height },
          initialWidth: rect.width,
          initialHeight: rect.height,
          data: {
            group: name,
            width: rect.width,
            height: rect.height,
            color,
            collapsed,
            scale: groupScale || 1,
            onToggle: toggleGroup,
          } satisfies GroupBoxData,
          draggable: true,
          selectable: false,
          zIndex: 0,
        }),
      )
    }

    for (const [name, step] of Object.entries(drawGraph.steps)) {
      const pos = positions[name]
      if (!pos) continue
      const group = virtualGroupOf(name)
      const left = { x: pos.x - nodeW / 2, y: pos.y - nodeH / 2 }
      const memberCount = group ? nodesInGroup(group).length : 0
      const groupCol = group ? groupColorFor(group) : ''
      const hasNote = noteNodes.has(name)
      emit(
        name,
        `step|${left.x}|${left.y}|${nodeW}|${nodeH}|${scale}|${showNodeDescriptions ? 1 : 0}|${
          hasNote ? 1 : 0
        }|${group ?? ''}|${memberCount}|${groupCol}|${horizontal ? 'h' : 'v'}|${stepIdOf(step)}`,
        () => ({
          id: name,
          type: 'step',
          position: left,
          // Declared size — see the group box note above: keeps the node visible
          // and its edges attached when its object is rebuilt mid-drag.
          measured: { width: nodeW, height: nodeH },
          initialWidth: nodeW,
          initialHeight: nodeH,
          data: {
            name: group ?? name,
            step,
            nodeW,
            nodeH,
            scale,
            showDescription: showNodeDescriptions,
            groupProxy: group
              ? { group, memberCount, color: groupCol }
              : null,
            hasNote,
            horizontal,
          } satisfies StepNodeData,
          draggable: true,
          zIndex: 2,
        }),
      )
    }

    // Markers sit above / below the node, or clear of the group box when the
    // node belongs to one — matching the Swift `tipY` / `baseY` logic.
    const boxByName = new Map(boxes.map((b) => [b.name, b.rect]))
    const groupOf = (name: string) =>
      virtualGroupOf(name) ?? graph.steps[name]?.belongsTo ?? null

    // In the horizontal layout the arrow lies on its side, so its bounding box is
    // MARKER_H wide × MARKER_W tall; a start marker sits to the node's left (pointing in),
    // an end marker to its right (pointing away). Vertical keeps the above/below placement.
    const markW = horizontal ? MARKER_H : MARKER_W
    const markH = horizontal ? MARKER_W : MARKER_H
    for (const name of startNodes) {
      const pos = positions[name]
      if (!pos) continue
      const box = showGrouping ? boxByName.get(groupOf(name) ?? '') : undefined
      const p = horizontal
        ? { x: (box ? box.x - 16 : pos.x - nodeW / 2 - 6) - markW, y: pos.y - markH / 2 }
        : { x: pos.x - markW / 2, y: (box ? box.y - 16 : pos.y - nodeH / 2 - 6) - markH }
      emit(`start:${name}`, `start|${p.x}|${p.y}|${horizontal ? 'h' : 'v'}`, () => ({
        id: `start:${name}`,
        type: 'marker',
        position: p,
        measured: { width: markW, height: markH },
        initialWidth: markW,
        initialHeight: markH,
        data: { kind: 'start', horizontal },
        draggable: false,
        selectable: false,
        zIndex: 1,
      }))
    }
    for (const name of endNodes) {
      const pos = positions[name]
      if (!pos) continue
      const box = showGrouping ? boxByName.get(groupOf(name) ?? '') : undefined
      const p = horizontal
        ? { x: box ? box.x + box.width + 8 : pos.x + nodeW / 2 + 8, y: pos.y - markH / 2 }
        : { x: pos.x - markW / 2, y: box ? box.y + box.height + 8 : pos.y + nodeH / 2 + 8 }
      emit(`end:${name}`, `end|${p.x}|${p.y}|${horizontal ? 'h' : 'v'}`, () => ({
        id: `end:${name}`,
        type: 'marker',
        position: p,
        measured: { width: markW, height: markH },
        initialWidth: markW,
        initialHeight: markH,
        data: { kind: 'end', horizontal },
        draggable: false,
        selectable: false,
        zIndex: 1,
      }))
    }

    // Drop cache entries for nodes that no longer exist (collapse, project switch).
    for (const key of cache.keys()) if (!seen.has(key)) cache.delete(key)

    return result
  }, [
    boxes,
    collapsedGroups,
    drawGraph.steps,
    endNodes,
    graph.steps,
    groupScale,
    horizontal,
    nodeH,
    nodeW,
    scale,
    nodesInGroup,
    noteNodes,
    positions,
    showGrouping,
    showNodeDescriptions,
    startNodes,
    stepIdOf,
    toggleGroup,
  ])

  // ── ReactFlow edges ─────────────────────────────────────────────────────

  const rfEdges = useMemo<Edge[]>(() => {
    const showNorms = normValues != null
    const maxValue = showNorms
      ? maxMetricValue(drawGraph, normMetric)
      : maxMetricValue(drawGraph, metric)
    const schema = activeSchema

    const outgoing = new Map<string, number>()
    for (const t of drawGraph.transitions) {
      outgoing.set(t.fromStep, (outgoing.get(t.fromStep) ?? 0) + t.occurrences)
    }

    const visible = drawGraph.transitions.filter(
      (t) => positionedIds.has(t.fromStep) && positionedIds.has(t.toStep),
    )

    return visible.map((t) => {
      const id = `${t.fromStep}->${t.toStep}`
      return {
          id,
          source: t.fromStep,
          target: t.toStep,
          type: 'metric',
          zIndex: 1,
          data: {
            transition: t,
            metric,
            maxValue,
            colorize: colorizeByWeight,
            schema,
            normValue: normValues?.[id] ?? null,
            normMetric,
            showNorms,
            showCompliance,
            normIsMinimum,
            outgoingTotal: outgoing.get(t.fromStep) ?? 0,
            journeyTotal,
            hasNote: noteEdges.has(id),
            nodeH,
            horizontal,
            edgeScale: edgeScale || 1,
            onEdgeClick:
              onEdgeTap ??
              (onEdgeNote
                ? (transition, screen) =>
                    setMenu({
                      kind: 'edge',
                      transition,
                      x: screen.x,
                      y: screen.y,
                    })
                : undefined),
          } satisfies MetricEdgeData,
        } satisfies Edge
      })
  }, [
    activeSchema,
    colorizeByWeight,
    drawGraph,
    edgeScale,
    horizontal,
    journeyTotal,
    metric,
    nodeH,
    normIsMinimum,
    normMetric,
    normValues,
    noteEdges,
    onEdgeNote,
    onEdgeTap,
    positionedIds,
    showCompliance,
  ])

  // ── Dragging ────────────────────────────────────────────────────────────

  // Per-group drag snapshot: the box's start position plus each member's start
  // position, captured once when a group drag begins (see onNodesChange).
  const dragOrigins = useRef<
    Record<string, { box: Point; members: Record<string, Point> }>
  >({})

  const commitOverrides = useCallback(
    (next: Record<string, Point>, persist = true) => {
      if (syncState) {
        syncState.nodeOverrides = next
        syncState.version += 1
        onSyncChange?.()
      }
      setOverrides(next)
      if (persist) writeJSON(layoutKey, next)
    },
    [layoutKey, onSyncChange, syncState],
  )

  const onNodesChange = useCallback(
    (changes: NodeChange[]) => {
      let next: Record<string, Point> | null = null
      let dragEnded = false
      let dragging = false
      // The item being dragged this gesture, tracked so alignment guides can measure it
      // against everything else and snap it into line. Either one group box…
      let movingGroup: {
        name: string
        box: { x: number; y: number; width: number; height: number }
        members: Record<string, Point> // origin (pre-drag) centres
        dx: number
        dy: number
      } | null = null
      // …or one or more free step nodes (raw, pre-snap centres).
      const movingNodes: Record<string, Point> = {}

      for (const change of changes) {
        if (change.type !== 'position' || !change.position) continue
        // `dragging` is true for every intermediate move and false on the final
        // change of a gesture (and undefined for programmatic moves) — either way
        // that is when the result should be written through to storage.
        if (change.dragging !== true) dragEnded = true
        else dragging = true
        const id = change.id

        if (id.startsWith('box:')) {
          // Dragging the box moves every member (or the proxy when collapsed).
          // The member origins are snapshotted once at drag start; applying the
          // cumulative pointer delta to those fixed origins (never to the live,
          // already-moved positions) is what keeps the group from compounding
          // its own movement and flying off-screen.
          const group = id.slice(4)
          const box = boxes.find((b) => b.name === group)
          if (!box) continue
          let snapshot = dragOrigins.current[id]
          if (!snapshot) {
            const members = collapsedGroups.has(group)
              ? [collapsedNodeId(group)]
              : nodesInGroup(group)
            const memberOrigins: Record<string, Point> = {}
            for (const member of members) {
              const base = positions[member]
              if (base) memberOrigins[member] = base
            }
            snapshot = { box: { x: box.rect.x, y: box.rect.y }, members: memberOrigins }
            dragOrigins.current[id] = snapshot
          }
          const dx = change.position.x - snapshot.box.x
          const dy = change.position.y - snapshot.box.y
          next ??= { ...effectiveOverrides }
          for (const [member, base] of Object.entries(snapshot.members)) {
            next[member] = snap({ x: base.x + dx, y: base.y + dy })
          }
          movingGroup = { name: group, box: box.rect, members: snapshot.members, dx, dy }
          if (!change.dragging) delete dragOrigins.current[id]
          continue
        }

        if (id.startsWith('start:') || id.startsWith('end:')) continue

        const center = {
          x: change.position.x + nodeW / 2,
          y: change.position.y + nodeH / 2,
        }
        movingNodes[id] = center
        next ??= { ...effectiveOverrides }
        next[id] = snap(center)
      }

      // ── Alignment guides ──────────────────────────────────────────────
      // While a drag is live, measure the moving item's six edges (left / centre-x /
      // right, top / centre-y / bottom) against every other node and group box; draw a
      // guide where they line up and snap the item onto the nearest match.
      if (dragging && next && (movingGroup || Object.keys(movingNodes).length)) {
        const excluded = new Set<string>()
        let moving: ReturnType<typeof boundsFromCenter> | null = null
        if (movingGroup) {
          moving = boundsFromRect(
            movingGroup.box.x + movingGroup.dx,
            movingGroup.box.y + movingGroup.dy,
            movingGroup.box.width,
            movingGroup.box.height,
          )
          for (const m of Object.keys(movingGroup.members)) excluded.add(m)
          excluded.add(collapsedNodeId(movingGroup.name))
        } else {
          const ids = Object.keys(movingNodes)
          for (const id of ids) excluded.add(id)
          let l = Infinity
          let t = Infinity
          let r = -Infinity
          let b = -Infinity
          for (const id of ids) {
            const c = movingNodes[id]
            l = Math.min(l, c.x - nodeW / 2)
            r = Math.max(r, c.x + nodeW / 2)
            t = Math.min(t, c.y - nodeH / 2)
            b = Math.max(b, c.y + nodeH / 2)
          }
          moving = { left: l, cx: (l + r) / 2, right: r, top: t, cy: (t + b) / 2, bottom: b }
        }

        // Guide only against peers of the SAME kind: a dragged group aligns to other
        // groups, a dragged node aligns to other nodes. Mixing both at once is more lines
        // than the eye can use.
        const targets = []
        if (movingGroup) {
          for (const box of boxes) {
            if (box.name === movingGroup.name) continue
            targets.push(boundsFromRect(box.rect.x, box.rect.y, box.rect.width, box.rect.height))
          }
        } else {
          for (const name of positionedIds) {
            if (excluded.has(name)) continue
            const c = positions[name]
            if (c) targets.push(boundsFromCenter(c.x, c.y, nodeW, nodeH))
          }
        }

        // Detect alignment in a constant SCREEN band (≈7px) rather than a fixed number of
        // flow units — otherwise, zoomed out, the band shrinks to a sub-pixel sliver and the
        // guides almost never appear. Dividing by the live zoom keeps the feel identical at
        // every zoom level.
        const vp = flow.getViewport()
        const threshold = GUIDE_SCREEN_PX / (vp.zoom || 1)
        const g = computeGuides(moving, targets, threshold)
        if (g.snapDx || g.snapDy) {
          if (movingGroup) {
            for (const [member, base] of Object.entries(movingGroup.members)) {
              next[member] = {
                x: g.snapDx ? base.x + movingGroup.dx + g.snapDx : next[member].x,
                y: g.snapDy ? base.y + movingGroup.dy + g.snapDy : next[member].y,
              }
            }
          } else {
            for (const [id, raw] of Object.entries(movingNodes)) {
              next[id] = {
                x: g.snapDx ? raw.x + g.snapDx : next[id].x,
                y: g.snapDy ? raw.y + g.snapDy : next[id].y,
              }
            }
          }
        }
        setGuides(
          g.vertical.length || g.horizontal.length
            ? { vertical: g.vertical, horizontal: g.horizontal, vp }
            : null,
        )
      } else if (dragEnded) {
        setGuides(null)
      }

      // Persist to storage only when the gesture ends (change.dragging === false),
      // never on every intermediate move — the per-move localStorage write was the
      // main source of drag jank. In-memory overrides still update every move so
      // the node tracks the cursor smoothly.
      if (next) commitOverrides(next, dragEnded)
    },
    [
      boxes,
      collapsedGroups,
      commitOverrides,
      effectiveOverrides,
      flow,
      nodeH,
      nodeW,
      nodesInGroup,
      positionedIds,
      positions,
    ],
  )

  // ── Viewport: initial fit + optional A/B sync ───────────────────────────

  const fitted = useRef(false)
  useEffect(() => {
    if (fitted.current || rfNodes.length === 0) return
    fitted.current = true
    if (skipInitialFit && syncState?.viewport) {
      flow.setViewport(syncState.viewport)
    } else {
      window.requestAnimationFrame(() => {
        flow.fitView({ padding: 0.12, duration: 0 })
        setZoom(flow.getZoom())
      })
    }
  }, [flow, rfNodes.length, skipInitialFit, syncState])

  // Re-fit when a new project is opened.
  useEffect(() => {
    fitted.current = false
  }, [projectId])

  // Re-fit to the container when it is resized (opt-in, e.g. a resizable panel). Debounced
  // to the next frame so a drag-resize keeps the whole chart in view without jitter.
  useEffect(() => {
    const el = wrapRef.current
    if (!props.fitOnResize || !el) return
    let raf = 0
    let first = true
    const ro = new ResizeObserver(() => {
      if (first) {
        first = false // the observer fires once on attach — the initial fit already handled it
        return
      }
      cancelAnimationFrame(raf)
      raf = requestAnimationFrame(() => {
        flow.fitView({ padding: 0.12, duration: 150 })
        setZoom(flow.getZoom())
      })
    })
    ro.observe(el)
    return () => {
      cancelAnimationFrame(raf)
      ro.disconnect()
    }
  }, [props.fitOnResize, flow])

  // Re-run the auto-fit whenever the SET of nodes changes (a drill-down / drill-up, or a
  // reload that adds/removes steps) — but ONLY for a non-persisted chart. A saved or dragged
  // layout keeps its own framing (persisted positions have priority). The re-computed
  // auto-layout (which already reacts to `graph`) is what re-optimises the node placement;
  // this just re-frames the viewport so the fresh layout is centred and its labels readable.
  const nodeSig = useMemo(() => Object.keys(graph.steps).sort().join(' '), [graph.steps])
  const prevNodeSig = useRef(nodeSig)
  useEffect(() => {
    if (prevNodeSig.current === nodeSig) return
    prevNodeSig.current = nodeSig
    if (syncState || Object.keys(overrides).length > 0) return // persisted / synced layout wins
    window.requestAnimationFrame(() => {
      flow.fitView({ padding: 0.12, duration: 350 })
      setZoom(flow.getZoom())
    })
  }, [nodeSig, overrides, syncState, flow])

  const syncVersion = syncState?.version ?? 0
  useEffect(() => {
    if (!syncState?.viewport) return
    const current = flow.getViewport()
    const v = syncState.viewport
    if (
      Math.abs(current.x - v.x) < 0.5 &&
      Math.abs(current.y - v.y) < 0.5 &&
      Math.abs(current.zoom - v.zoom) < 0.001
    ) {
      return
    }
    flow.setViewport(v)
    setZoom(v.zoom)
  }, [flow, syncState, syncVersion])

  const onMove = useCallback(
    (_: unknown, viewport: Viewport) => {
      setZoom(viewport.zoom)
      if (syncState) {
        syncState.viewport = viewport
        syncState.version += 1
        onSyncChange?.()
      }
    },
    [onSyncChange, syncState],
  )

  const resetLayout = useCallback(() => {
    commitOverrides({})
    window.requestAnimationFrame(() => {
      flow.fitView({ padding: 0.12, duration: 350 })
      setZoom(flow.getZoom())
    })
  }, [commitOverrides, flow])

  const zoomBy = useCallback(
    (factor: number) => {
      const next = Math.max(0.15, Math.min(5, flow.getZoom() * factor))
      flow.zoomTo(next, { duration: 200 })
      setZoom(next)
    },
    [flow],
  )

  // ── Colour-scale legend ─────────────────────────────────────────────────

  const gradient = EDGE_SCHEMA_GRADIENTS[activeSchema]
  const scaleStyle: CSSProperties = gradient
    ? {
        background: `linear-gradient(90deg, ${gradient.low}, ${interpolate(
          gradient.low,
          gradient.high,
          0.5,
        )}, ${gradient.high})`,
      }
    : { background: 'rgba(120,120,128,0.25)' }

  const menuNodeStep = menu?.node ? graph.steps[menu.node] : undefined
  const menuDescription = menuNodeStep?.description ?? ''
  const menuHasDescription =
    showNodeDescriptions &&
    menuDescription.length > 0 &&
    menuDescription !== menu?.node

  return (
    <div className={`flow-wrap${focus ? ' has-focus' : ''}`} ref={wrapRef}>
      <FlowFocusContext.Provider value={focus}>
      <AggregatePickContext.Provider value={pickValue}>
      <ReactFlow
        nodes={rfNodes}
        edges={rfEdges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        onNodesChange={(changes) => {
          // A drag (or any position change) ends the dwell spotlight immediately.
          if (changes.some((c) => c.type === 'position')) endFocus()
          onNodesChange(changes)
        }}
        onMove={onMove}
        onNodeMouseEnter={onNodeMouseEnter}
        onNodeMouseLeave={endFocus}
        onNodeClick={(event, node) => {
          endFocus()
          if (node.id.startsWith('box:') || virtualGroupOf(node.id)) return
          // In aggregate pick mode a click toggles the step's membership — no menu.
          if (aggregateMode) {
            event.stopPropagation()
            togglePicked(node.id)
            return
          }
          // The menu opens for node actions, or (in an in-place drill) for "Drill up".
          if (!onNodeAction && !props.onDrillUp) return
          setMenu({ kind: 'node', node: node.id, x: event.clientX, y: event.clientY })
        }}
        onPaneClick={() => {
          endFocus()
          setMenu(null)
          setDescriptionNode(null)
        }}
        onDoubleClick={() => flow.fitView({ padding: 0.12, duration: 350 })}
        minZoom={0.15}
        maxZoom={5}
        snapToGrid
        snapGrid={[GRID_SIZE, GRID_SIZE]}
        nodesConnectable={false}
        elementsSelectable
        proOptions={{ hideAttribution: false }}
        defaultEdgeOptions={{ type: 'metric' }}
      >
        <Background variant={BackgroundVariant.Dots} gap={GRID_SIZE} size={1} />
      </ReactFlow>
      </AggregatePickContext.Provider>
      </FlowFocusContext.Provider>

      {guides && (
        <svg className="align-guides" aria-hidden>
          {guides.vertical.map((l, i) => (
            <line
              key={`v${i}`}
              x1={l.x * guides.vp.zoom + guides.vp.x}
              x2={l.x * guides.vp.zoom + guides.vp.x}
              y1={l.y1 * guides.vp.zoom + guides.vp.y}
              y2={l.y2 * guides.vp.zoom + guides.vp.y}
            />
          ))}
          {guides.horizontal.map((l, i) => (
            <line
              key={`h${i}`}
              x1={l.x1 * guides.vp.zoom + guides.vp.x}
              x2={l.x2 * guides.vp.zoom + guides.vp.x}
              y1={l.y * guides.vp.zoom + guides.vp.y}
              y2={l.y * guides.vp.zoom + guides.vp.y}
            />
          ))}
        </svg>
      )}

      {isLoading && (
        <div className="loading-pill row">
          <span className="spinner" /> Loading…
        </div>
      )}

      {props.notice && (
        <div className="flow-notice" role="status">
          {props.notice}
        </div>
      )}

      {props.onCreateAggregate && !aggregateMode && (
        <div
          style={{
            position: 'absolute',
            bottom: 12,
            left: 12,
            zIndex: 6,
          }}
        >
          <button
            className="btn"
            onClick={() => {
              setMenu(null)
              setAggregateMode(true)
            }}
            title="Select interconnected steps to collapse into one Σ super-step"
          >
            Σ Select steps to aggregate
          </button>
        </div>
      )}

      {props.onCreateAggregate && aggregateMode && (
        <div className="agg-actionbar" role="toolbar">
          <span className="agg-actionbar-title">Σ Aggregate</span>
          <span className="agg-actionbar-count">
            {bankedGroups.length > 0 &&
              `${bankedGroups.length} group${bankedGroups.length === 1 ? '' : 's'} banked · `}
            {picked.size === 0
              ? 'click connected steps'
              : `${picked.size} step${picked.size === 1 ? '' : 's'} selected`}
          </span>
          <button
            className="btn"
            disabled={picked.size < 2}
            onClick={bankGroup}
            title="Bank this connected group and start another (a step can be in only one aggregate)"
          >
            ＋ Add group
          </button>
          <button
            className="btn primary"
            disabled={bankedGroups.length === 0 && picked.size < 2}
            onClick={() => {
              const groups = picked.size >= 2 ? [...bankedGroups, [...picked]] : bankedGroups
              if (groups.length) {
                props.onCreateAggregate?.(groups)
                exitAggregateMode()
              }
            }}
            title={
              props.isHighLevelMap
                ? 'Add these aggregate(s) to this high-level map'
                : 'Build the high-level map from these aggregate group(s)'
            }
          >
            {props.isHighLevelMap ? 'Add to map' : 'Create map'}
            {(() => {
              const n = bankedGroups.length + (picked.size >= 2 ? 1 : 0)
              return n > 0 ? ` (${n})` : ''
            })()}
          </button>
          <button className="btn" onClick={exitAggregateMode}>
            Cancel
          </button>
        </div>
      )}

      {collapsedGroups.size > 0 && (
        <div
          style={{
            position: 'absolute',
            bottom: 12,
            left: '50%',
            transform: 'translateX(-50%)',
            fontSize: 11,
            color: 'var(--secondary)',
            pointerEvents: 'none',
          }}
        >
          Collapsed groups: connection counts summed · times weighted-averaged
        </div>
      )}

      <div className="flow-overlay">
        {colorizeByWeight && (
          <button
            className="color-scale color-scale-btn"
            onClick={() => setShowColorWizard(true)}
            title="Configure edge colour schema per metric"
            aria-label="Configure edge colour schema"
          >
            <div className="row t-caption2 fg-secondary" style={{ gap: 4 }}>
              {metric}
              <span style={{ marginLeft: 'auto', opacity: 0.6 }}>⚙</span>
            </div>
            <div className="bar" style={scaleStyle} />
            {gradient ? (
              <div className="ends">
                <span>Low</span>
                <span>High</span>
              </div>
            ) : (
              <div className="ends">
                <span>No color scale</span>
              </div>
            )}
          </button>
        )}

        {allowTransitionTable && showTableButton && (
          <button
            className="table-btn"
            onClick={() => setShowTable(true)}
            title="Show the transition table behind this chart"
            aria-label="Show transition table"
          >
            ▦ Transitions
          </button>
        )}

        <div className="zoom-controls">
          <button onClick={() => zoomBy(1 / 1.3)} title="Zoom out">
            −
          </button>
          <span className="zoom-value">{Math.round(zoom * 100)}%</span>
          <button onClick={() => zoomBy(1.3)} title="Zoom in">
            +
          </button>
          <button
            onClick={() => flow.fitView({ padding: 0.12, duration: 350 })}
            title="Fit to view"
          >
            ⤢
          </button>
          <span className="sep" />
          <button onClick={resetLayout} title="Reset node layout">
            ↺
          </button>
          {showGrouping && allGroupNames.size > 0 && (
            <>
              <span className="sep" />
              <button
                onClick={() =>
                  setCollapsedGroups((prev) =>
                    prev.size === allGroupNames.size ? new Set() : new Set(allGroupNames),
                  )
                }
                title={
                  collapsedGroups.size === allGroupNames.size
                    ? 'Expand all groups'
                    : 'Collapse all groups'
                }
              >
                {collapsedGroups.size === allGroupNames.size ? '⤢' : '⤡'}
              </button>
            </>
          )}
        </div>
      </div>

      {menu?.kind === 'node' && menu.node && (onNodeAction || props.onDrillUp) && (
        <>
          <div
            style={{ position: 'fixed', inset: 0, zIndex: 199 }}
            onClick={() => setMenu(null)}
          />
          <div
            className="popover"
            style={{ left: clampX(menu.x), top: clampY(menu.y + 12) }}
          >
            <div className="p-title">{menu.node}</div>
            {props.onDrillUp && (
              <button
                className="p-item"
                style={{ color: 'var(--accent)' }}
                onClick={() => {
                  props.onDrillUp?.()
                  setMenu(null)
                }}
              >
                ⤴ Drill up to high-level map
              </button>
            )}
            {!props.readOnly && onNodeAction && (
              <>
                <button
                  className="p-item"
                  onClick={() => {
                    onNodeAction(menu.node as string, 'include')
                    setMenu(null)
                  }}
                >
                  ✓ Require in journeys
                </button>
                <button
                  className="p-item fg-red"
                  onClick={() => {
                    onNodeAction(menu.node as string, 'exclude')
                    setMenu(null)
                  }}
                >
                  ⊖ Exclude from journeys
                </button>
              </>
            )}
            {onMetaInfo && (
              <button
                className="p-item"
                onClick={() => {
                  onMetaInfo(menu.node as string)
                  setMenu(null)
                }}
              >
                ▤ Meta Infos
              </button>
            )}
            {menuHasDescription && (
              <button
                className="p-item"
                onClick={() => {
                  setDescriptionNode(menu.node as string)
                  setMenu(null)
                }}
              >
                ≡ Show description
              </button>
            )}
            {onNodeNote && (
              <button
                className="p-item"
                style={{ color: 'var(--yellow)' }}
                onClick={() => {
                  onNodeNote(menu.node as string)
                  setMenu(null)
                }}
              >
                ✎ Show Notes ({noteCounts.get(`node:${menu.node}`) ?? 0})
              </button>
            )}
            {(() => {
              const link = (props.aggregateLinks ?? []).find((l) => l.sigmaStep === menu.node)
              if (!link || !(props.onDrillDown || props.onDrillDownInPlace)) return null
              return (
                <>
                  {props.onDrillDown && (
                    <button
                      className="p-item"
                      style={{ color: 'var(--accent)' }}
                      onClick={() => {
                        props.onDrillDown?.(link)
                        setMenu(null)
                      }}
                    >
                      ⤵ Drill down · new panel
                    </button>
                  )}
                  {props.onDrillDownInPlace && (
                    <button
                      className="p-item"
                      style={{ color: 'var(--accent)' }}
                      onClick={() => {
                        props.onDrillDownInPlace?.(link)
                        setMenu(null)
                      }}
                    >
                      ⤵ Drill down · in place
                    </button>
                  )}
                </>
              )
            })()}
            {(() => {
              const node = menu.node as string
              const matches = (props.actionItems ?? []).filter((a) =>
                actionMatchesNode(a.spec, node),
              )
              if (!matches.length || !props.onRunAction) return null
              return (
                <>
                  <div style={{ borderTop: '1px solid var(--border)', margin: '4px 0' }} />
                  <div
                    className="fg-secondary"
                    style={{ fontSize: 11, padding: '2px 10px', textTransform: 'uppercase', letterSpacing: 0.5 }}
                  >
                    Actions
                  </div>
                  {matches.map((a) => (
                    <button
                      key={a.id}
                      className="p-item"
                      onClick={() => {
                        props.onRunAction?.(a, node)
                        setMenu(null)
                      }}
                    >
                      ⚡ {a.name || '(unnamed)'}
                    </button>
                  ))}
                </>
              )
            })()}
          </div>
        </>
      )}

      {menu?.kind === 'edge' && menu.transition && onEdgeNote && (
        <>
          <div
            style={{ position: 'fixed', inset: 0, zIndex: 199 }}
            onClick={() => setMenu(null)}
          />
          <div
            className="popover"
            style={{ left: clampX(menu.x), top: clampY(menu.y + 12) }}
          >
            <div className="p-title">
              {menu.transition.fromStep} → {menu.transition.toStep}
            </div>
            <button
              className="p-item"
              style={{ color: 'var(--yellow)' }}
              onClick={() => {
                onEdgeNote(menu.transition as ProcessTransition)
                setMenu(null)
              }}
            >
              ✎ Show Notes (
              {noteCounts.get(
                `edge:${menu.transition.fromStep}->${menu.transition.toStep}`,
              ) ?? 0}
              )
            </button>
          </div>
        </>
      )}

      {descriptionNode && (
        <>
          <div
            style={{ position: 'fixed', inset: 0, zIndex: 199 }}
            onClick={() => setDescriptionNode(null)}
          />
          <div
            className="popover"
            style={{
              left: '50%',
              top: '50%',
              transform: 'translate(-50%, -50%)',
              width: 260,
              padding: 14,
            }}
          >
            <div className="t-caption fg-secondary" style={{ fontWeight: 600 }}>
              {descriptionNode}
            </div>
            <hr className="divider" style={{ margin: '8px 0' }} />
            <div className="t-callout" style={{ whiteSpace: 'pre-wrap' }}>
              {graph.steps[descriptionNode]?.description}
            </div>
            <div className="row" style={{ justifyContent: 'flex-end', marginTop: 10 }}>
              <button className="btn small" onClick={() => setDescriptionNode(null)}>
                Done
              </button>
            </div>
          </div>
        </>
      )}

      {showColorWizard && (
        <EdgeColorWizard onClose={() => setShowColorWizard(false)} />
      )}

      {showTable && (
        <TransitionTablePanel
          graph={graph}
          journeyTotal={journeyTotal}
          title={chartMode}
          onClose={() => setShowTable(false)}
        />
      )}
    </div>
  )
}

function snap(p: Point): Point {
  return {
    x: Math.round(p.x / GRID_SIZE) * GRID_SIZE,
    y: Math.round(p.y / GRID_SIZE) * GRID_SIZE,
  }
}

function clampX(x: number): number {
  return Math.max(120, Math.min(window.innerWidth - 230, x))
}

function clampY(y: number): number {
  return Math.max(60, Math.min(window.innerHeight - 200, y))
}

export function FlowChart(props: FlowChartProps) {
  return (
    <ReactFlowProvider>
      <FlowChartInner {...props} />
    </ReactFlowProvider>
  )
}
