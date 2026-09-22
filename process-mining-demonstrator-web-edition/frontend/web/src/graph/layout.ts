/**
 * Direct port of `GraphLayout.compute` from FlowChartView.swift.
 *
 * Sugiyama-style layered layout:
 *   1. greedy cycle-free DAG (edges added in descending occurrence order)
 *   2. Kahn longest-path layer assignment
 *   3. barycenter crossing minimisation, 3 alternating passes
 *   4. rows centred horizontally on the canvas
 *   5. BELONGS_TO group boxes pushed apart until they no longer overlap
 *
 * Coordinates are node *centres*, matching the Swift canvas. ReactFlow wants
 * top-left origins, so `FlowChart` subtracts half the node size when placing.
 */

import type { ProcessGraph } from '../types'

export const NODE_W = 198
export const NODE_H = 63
export const NODE_H_TIMED = 70 // nodes that carry an event timestamp are taller
// Gaps are sized so edge (transition) labels sit clearly in the space between nodes: the
// vertical gap must clear a metric label + arrowhead, the horizontal gap keeps a node's
// out-edge labels from colliding with its neighbour's.
export const H_GAP = 72
export const V_GAP = 116
export const PADDING = 48
export const GRID_SIZE = 20

export const GROUP_PAD = 20
export const GROUP_LABEL_PAD = 18
export const GROUP_MIN_GAP = 24

export interface Point {
  x: number
  y: number
}

export interface Rect {
  x: number
  y: number
  width: number
  height: number
}

export interface GraphLayout {
  nodePositions: Record<string, Point>
  canvasSize: { width: number; height: number }
}

export function defaultNodeHeight(graph: ProcessGraph): number {
  return Object.values(graph.steps).some((s) => s.eventTime) ? NODE_H_TIMED : NODE_H
}

export function computeLayout(
  graph: ProcessGraph,
  nodeHeight: number = NODE_H,
  optimised = true,
  nodeWidth: number = NODE_W,
  labelScale = 1,
  /** ≥1 — widens the between-layer gap so larger edge labels still fit clearly. */
  edgeLabelScale = 1,
  /** Lay the layers left-to-right (columns) instead of top-to-bottom (rows). */
  horizontal = false,
): GraphLayout {
  const nodes = Object.keys(graph.steps)
  if (nodes.length === 0) {
    return { nodePositions: {}, canvasSize: { width: 400, height: 300 } }
  }

  const allEdges = graph.transitions.filter((t) => t.fromStep !== t.toStep)

  // ── 1. Greedy cycle-free DAG. Back-edges (rare loops) are skipped for layout
  //       but still drawn.
  const dagSucc: Record<string, string[]> = {}
  for (const n of nodes) dagSucc[n] = []

  const wouldCreateCycle = (u: string, v: string): boolean => {
    const visited = new Set<string>()
    const stack = [v]
    while (stack.length) {
      const top = stack.pop() as string
      if (top === u) return true
      if (!visited.has(top)) {
        visited.add(top)
        for (const s of dagSucc[top] ?? []) stack.push(s)
      }
    }
    return false
  }

  // Sort by weight, then break ties on the step names so the greedy DAG (and
  // hence the whole layout) is independent of the order transitions arrive in.
  // The backend no longer sorts them, and equal-count ties were never ordered
  // by the database anyway.
  const byWeightThenName = [...allEdges].sort(
    (a, b) =>
      b.occurrences - a.occurrences ||
      a.fromStep.localeCompare(b.fromStep) ||
      a.toStep.localeCompare(b.toStep),
  )
  for (const edge of byWeightThenName) {
    if (!dagSucc[edge.fromStep] || !dagSucc[edge.toStep]) continue
    if (!wouldCreateCycle(edge.fromStep, edge.toStep)) {
      dagSucc[edge.fromStep].push(edge.toStep)
    }
  }

  // ── 2. Longest-path layer assignment via Kahn's topological sort.
  const inDeg: Record<string, number> = {}
  for (const n of nodes) inDeg[n] = 0
  for (const succs of Object.values(dagSucc)) {
    for (const v of succs) inDeg[v] = (inDeg[v] ?? 0) + 1
  }

  const layers: Record<string, number> = {}
  const queue = nodes.filter((n) => (inDeg[n] ?? 0) === 0).sort()
  for (const n of queue) layers[n] = 0

  for (let qi = 0; qi < queue.length; qi++) {
    const u = queue[qi]
    const ul = layers[u] ?? 0
    for (const v of dagSucc[u] ?? []) {
      const candidate = ul + 1
      if (candidate > (layers[v] ?? 0)) layers[v] = candidate
      inDeg[v] = (inDeg[v] ?? 0) - 1
      if (inDeg[v] === 0) queue.push(v)
    }
  }
  // Isolated nodes / unresolved sub-cycles land on layer 0.
  for (const n of nodes) if (layers[n] == null) layers[n] = 0

  // Alphabetical sort gives a stable, deterministic baseline within each layer.
  let layerGroups: Record<number, string[]> = {}
  for (const [node, layer] of Object.entries(layers)) {
    ;(layerGroups[layer] ??= []).push(node)
  }
  for (const key of Object.keys(layerGroups)) {
    layerGroups[Number(key)].sort()
  }

  const dagPred: Record<string, string[]> = {}
  for (const n of nodes) dagPred[n] = []
  for (const [u, succs] of Object.entries(dagSucc)) {
    for (const v of succs) (dagPred[v] ??= []).push(u)
  }

  // ── 3. Crossing minimisation.
  if (optimised) {
    layerGroups = applyCrossingMin(layerGroups, dagSucc, dagPred, layers)
  }

  const maxLayer = Math.max(...Object.values(layers))
  const maxCount = Math.max(...Object.values(layerGroups).map((g) => g.length), 1)

  // Scale the gaps/padding with the nodes so a larger node size just zooms the whole
  // layout uniformly — otherwise big nodes with fixed small gaps crowd and overlap.
  const s = nodeWidth / NODE_W
  const hGap = H_GAP * s
  const vGap = V_GAP * s * Math.max(1, edgeLabelScale)
  const pad = PADDING * s

  // Vertical: layers stack down the Y axis (rows), siblings spread across X.
  // Horizontal: layers march along the X axis (columns), siblings spread down Y — so the
  // between-layer gap (which must clear the edge labels) runs horizontally and the
  // within-layer gap runs vertically.
  const positions: Record<string, Point> = {}
  let canvasW: number
  let canvasH: number
  if (horizontal) {
    canvasW = (maxLayer + 1) * nodeWidth + maxLayer * vGap + 2 * pad
    canvasH = maxCount * nodeHeight + Math.max(maxCount - 1, 0) * hGap + 2 * pad
    for (const [layerKey, nodesInLayer] of Object.entries(layerGroups)) {
      const layer = Number(layerKey)
      const x = pad + layer * (nodeWidth + vGap) + nodeWidth / 2
      const groupH =
        nodesInLayer.length * nodeHeight + Math.max(nodesInLayer.length - 1, 0) * hGap
      const startY = (canvasH - groupH) / 2
      nodesInLayer.forEach((node, i) => {
        positions[node] = { x, y: startY + i * (nodeHeight + hGap) + nodeHeight / 2 }
      })
    }
  } else {
    canvasW = maxCount * nodeWidth + Math.max(maxCount - 1, 0) * hGap + 2 * pad
    canvasH = (maxLayer + 1) * nodeHeight + maxLayer * vGap + 2 * pad
    // ── 4. Position each node centred within its layer row.
    for (const [layerKey, nodesInLayer] of Object.entries(layerGroups)) {
      const layer = Number(layerKey)
      const y = pad + layer * (nodeHeight + vGap) + nodeHeight / 2
      const groupW =
        nodesInLayer.length * nodeWidth + Math.max(nodesInLayer.length - 1, 0) * hGap
      const startX = (canvasW - groupW) / 2
      nodesInLayer.forEach((node, i) => {
        positions[node] = { x: startX + i * (nodeWidth + hGap) + nodeWidth / 2, y }
      })
    }
  }

  // ── 5. Nudge overlapping group boxes apart.
  resolveGroupOverlaps(positions, graph, nodeHeight, nodeWidth, labelScale)

  const allX = Object.values(positions).map((p) => p.x)
  const allY = Object.values(positions).map((p) => p.y)
  const finalW = Math.max(canvasW, Math.max(...allX) + nodeWidth / 2 + pad)
  const finalH = Math.max(canvasH, Math.max(...allY) + nodeHeight / 2 + pad)

  return { nodePositions: positions, canvasSize: { width: finalW, height: finalH } }
}

/**
 * Barycenter heuristic — each node is sorted by the average normalised position
 * of its neighbours in the adjacent layer. Stable across equal barycenters, so
 * the previous order is preserved for ties and isolated nodes.
 */
function applyCrossingMin(
  layerGroups: Record<number, string[]>,
  dagSucc: Record<string, string[]>,
  dagPred: Record<string, string[]>,
  layers: Record<string, number>,
  passes = 3,
): Record<number, string[]> {
  const lg: Record<number, string[]> = {}
  for (const [k, v] of Object.entries(layerGroups)) lg[Number(k)] = [...v]

  const sortedKeys = Object.keys(lg)
    .map(Number)
    .sort((a, b) => a - b)
  if (sortedKeys.length <= 1) return lg

  const virtualPos = (node: string): number => {
    const l = layers[node] ?? 0
    const vs = lg[l]
    if (!vs || vs.length === 0) return 0.5
    const idx = Math.max(0, vs.indexOf(node))
    return vs.length > 1 ? idx / (vs.length - 1) : 0.5
  }

  const barycenter = (node: string, predecessors: boolean): number => {
    const nl = layers[node] ?? 0
    const nbrs = (predecessors ? dagPred[node] : dagSucc[node]) ?? []
    let sum = 0
    let count = 0
    for (const v of nbrs) {
      const vl = layers[v] ?? 0
      if (predecessors ? vl >= nl : vl <= nl) continue
      sum += virtualPos(v)
      count += 1
    }
    return count > 0 ? sum / count : virtualPos(node)
  }

  // A stable sort keyed on the barycenter, computed once per pass so the
  // comparator stays consistent (JS sort requires a total order).
  const sortLayer = (layer: number, predecessors: boolean) => {
    const nodes = lg[layer]
    if (!nodes) return
    const keyed = nodes.map((n, i) => ({ n, k: barycenter(n, predecessors), i }))
    keyed.sort((a, b) => a.k - b.k || a.i - b.i)
    lg[layer] = keyed.map((e) => e.n)
  }

  for (let pass = 0; pass < passes; pass++) {
    for (const l of sortedKeys.slice(1)) sortLayer(l, true) // top-down
    for (const l of [...sortedKeys.slice(0, -1)].reverse()) sortLayer(l, false) // bottom-up
  }
  return lg
}

/** Iteratively push overlapping BELONGS_TO group boxes apart. */
function resolveGroupOverlaps(
  positions: Record<string, Point>,
  graph: ProcessGraph,
  nodeHeight: number,
  nodeWidth: number = NODE_W,
  labelScale = 1,
): void {
  const groups: Record<string, string[]> = {}
  for (const [name, step] of Object.entries(graph.steps)) {
    const g = step.belongsTo
    if (!g) continue
    ;(groups[g] ??= []).push(name)
  }
  const groupNames = Object.keys(groups).sort()
  if (groupNames.length <= 1) return

  const s = nodeWidth / NODE_W
  const gPad = GROUP_PAD * s
  // The title pill scales with the independent group-title font setting, so its
  // reserved space must track that — not the node scale — or the box top desyncs
  // from the rendered pill and adjacent groups overlap.
  const gLabel = GROUP_LABEL_PAD * labelScale
  const gMinGap = GROUP_MIN_GAP * s

  const rectFor = (nodeList: string[]): Rect => {
    const xs = nodeList.map((n) => positions[n]?.x).filter((v): v is number => v != null)
    const ys = nodeList.map((n) => positions[n]?.y).filter((v): v is number => v != null)
    if (xs.length === 0) return { x: 0, y: 0, width: 0, height: 0 }
    const minX = Math.min(...xs) - nodeWidth / 2 - gPad
    const minY = Math.min(...ys) - nodeHeight / 2 - gPad - gLabel
    const maxX = Math.max(...xs) + nodeWidth / 2 + gPad
    const maxY = Math.max(...ys) + nodeHeight / 2 + gPad
    return { x: minX, y: minY, width: maxX - minX, height: maxY - minY }
  }

  const inset = (r: Rect, d: number): Rect => ({
    x: r.x - d,
    y: r.y - d,
    width: r.width + 2 * d,
    height: r.height + 2 * d,
  })
  const intersects = (a: Rect, b: Rect) =>
    a.x < b.x + b.width &&
    b.x < a.x + a.width &&
    a.y < b.y + b.height &&
    b.y < a.y + a.height

  for (let iteration = 0; iteration < 30; iteration++) {
    let anyOverlap = false
    for (let i = 0; i < groupNames.length; i++) {
      for (let j = i + 1; j < groupNames.length; j++) {
        const nodesA = groups[groupNames[i]]
        const nodesB = groups[groupNames[j]]
        const rA = rectFor(nodesA)
        const rB = rectFor(nodesB)
        if (!intersects(inset(rA, gMinGap / 2), inset(rB, gMinGap / 2))) {
          continue
        }
        anyOverlap = true

        const overlapX =
          Math.min(rA.x + rA.width, rB.x + rB.width) - Math.max(rA.x, rB.x) + gMinGap
        const overlapY =
          Math.min(rA.y + rA.height, rB.y + rB.height) - Math.max(rA.y, rB.y) + gMinGap

        if (overlapX <= overlapY) {
          const shift = overlapX / 2 + 1
          const aGoesLeft = rA.x + rA.width / 2 <= rB.x + rB.width / 2
          for (const n of nodesA) positions[n].x += aGoesLeft ? -shift : shift
          for (const n of nodesB) positions[n].x += aGoesLeft ? shift : -shift
        } else {
          const shift = overlapY / 2 + 1
          const aGoesUp = rA.y + rA.height / 2 <= rB.y + rB.height / 2
          for (const n of nodesA) positions[n].y += aGoesUp ? -shift : shift
          for (const n of nodesB) positions[n].y += aGoesUp ? shift : -shift
        }
      }
    }
    if (!anyOverlap) break
  }
}

/** Bounding boxes of the visible BELONGS_TO groups, in canvas coordinates. */
export function groupRects(
  graph: ProcessGraph,
  positions: Record<string, Point>,
  collapsedGroups: Set<string>,
  nodeHeight: number,
  collapsedNodeId: (group: string) => string,
  nodeWidth: number = NODE_W,
  labelScale = 1,
): { name: string; rect: Rect }[] {
  const grouped: Record<string, Point[]> = {}

  for (const [name, step] of Object.entries(graph.steps)) {
    const group = step.belongsTo
    if (!group || collapsedGroups.has(group)) continue
    const pos = positions[name]
    if (!pos) continue
    ;(grouped[group] ??= []).push(pos)
  }
  for (const group of collapsedGroups) {
    const pos = positions[collapsedNodeId(group)]
    if (pos) grouped[group] = [pos]
  }

  const s = nodeWidth / NODE_W
  const gPad = GROUP_PAD * s
  const gLabel = GROUP_LABEL_PAD * labelScale
  return Object.keys(grouped)
    .sort()
    .map((name) => {
      const centers = grouped[name]
      const minX = Math.min(...centers.map((c) => c.x - nodeWidth / 2)) - gPad
      const minY =
        Math.min(...centers.map((c) => c.y - nodeHeight / 2)) - gPad - gLabel
      const maxX = Math.max(...centers.map((c) => c.x + nodeWidth / 2)) + gPad
      const maxY = Math.max(...centers.map((c) => c.y + nodeHeight / 2)) + gPad
      return { name, rect: { x: minX, y: minY, width: maxX - minX, height: maxY - minY } }
    })
}

export function snapToGrid(p: Point): Point {
  return {
    x: Math.round(p.x / GRID_SIZE) * GRID_SIZE,
    y: Math.round(p.y / GRID_SIZE) * GRID_SIZE,
  }
}
