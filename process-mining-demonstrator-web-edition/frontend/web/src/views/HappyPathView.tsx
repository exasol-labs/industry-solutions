/** Happy Path — port of HappyPathView.swift.
 *
 * Left: the actual process map. Right: the ideal sequence. In view mode the
 * ideal path is drawn as a trunk of step cards → a Y-fork → named branch
 * columns, each card showing its coverage (max(incoming, outgoing) / journeys)
 * as a green percentage. Edit mode swaps in the step editor. */

import { useEffect, useMemo, useRef, useState } from 'react'
import { PromptSheet, Unavailable } from '../components/ui'
import { FlowChart } from '../flow/FlowChart'
import { useSetting } from '../settings'
import {
  isSplit,
  splitNode,
  stepNode,
  updateNode,
  usedSteps,
} from '../graph/happyPath'
import { useStore } from '../store'
import type { HappyPath, HappyPathNode } from '../types'
import { useNoteHandlers } from './useNoteHandlers'

export function HappyPathView() {
  const store = useStore()
  const notes = useNoteHandlers()
  const [editMode, setEditMode] = useState(false)
  const [newPathName, setNewPathName] = useState<string | null>(null)
  const [renaming, setRenaming] = useState<HappyPath | null>(null)
  const [renamingSplit, setRenamingSplit] = useState<{
    pathId: string
    splitId: string
    field: 'label' | 'rejoinLabel'
    value: string
  } | null>(null)

  // Drag-resizable right (ideal-path) pane. The persisted width is the source of
  // truth; during a drag we track a live width and commit it on release so we
  // don't write to storage on every mouse move.
  const [savedWidth, setSavedWidth] = useSetting<number>('happyPath.editorWidth', 460)
  const [dragWidth, setDragWidth] = useState<number | null>(null)
  // `lastW` on the ref holds the live width so commit-on-release doesn't depend on
  // a possibly-stale render closure.
  const dragRef = useRef<{ startX: number; startW: number; lastW: number } | null>(null)
  const rawWidth = dragWidth ?? savedWidth
  const editorWidth = Number.isFinite(rawWidth)
    ? Math.min(Math.max(rawWidth, 300), 1000)
    : 460

  const onResizeDown = (e: React.PointerEvent) => {
    dragRef.current = { startX: e.clientX, startW: editorWidth, lastW: editorWidth }
    e.currentTarget.setPointerCapture?.(e.pointerId)
    e.preventDefault()
  }
  const onResizeMove = (e: React.PointerEvent) => {
    const d = dragRef.current
    if (!d) return
    // Dragging the handle left widens the right pane.
    const w = d.startW + (d.startX - e.clientX)
    if (Number.isFinite(w)) {
      d.lastW = Math.min(Math.max(w, 300), 1000)
      setDragWidth(d.lastW)
    }
  }
  const onResizeUp = (e: React.PointerEvent) => {
    const d = dragRef.current
    if (d) {
      dragRef.current = null
      e.currentTarget.releasePointerCapture?.(e.pointerId)
      setSavedWidth(d.lastW)
      setDragWidth(null)
    }
  }

  const path = store.happyPaths.find((p) => p.id === store.selectedHappyPathId) ?? null
  const score = path ? store.happyPathScores[path.id] : null

  useEffect(() => {
    if (store.selectedProject && store.happyPaths.length > 0) {
      void store.refreshHappyPathConformance()
    }
    setEditMode(false)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [store.selectedProject?.projectId, store.happyPaths.length, store.selectedHappyPathId])

  // Coverage per step: max(incoming, outgoing) occurrences / total journeys.
  const coverage = useMemo<Record<string, number>>(() => {
    const total = store.journeyCount
    if (!total || total <= 0) return {}
    const incoming: Record<string, number> = {}
    const outgoing: Record<string, number> = {}
    for (const t of store.processGraph.transitions) {
      outgoing[t.fromStep] = (outgoing[t.fromStep] ?? 0) + t.occurrences
      incoming[t.toStep] = (incoming[t.toStep] ?? 0) + t.occurrences
    }
    const result: Record<string, number> = {}
    for (const step of Object.keys(store.processGraph.steps)) {
      const count = Math.max(incoming[step] ?? 0, outgoing[step] ?? 0)
      result[step] = Math.min(1, count / total)
    }
    return result
  }, [store.processGraph, store.journeyCount])

  const inGraph = useMemo(
    () => new Set(Object.keys(store.processGraph.steps)),
    [store.processGraph.steps],
  )

  if (!store.selectedProject) {
    return (
      <Unavailable
        glyph="🗺"
        title="No Project Selected"
        description="Select a project from the sidebar."
      />
    )
  }

  const scoreColor =
    score == null
      ? 'var(--secondary)'
      : score >= 0.7
        ? 'var(--green)'
        : score <= 0.3
          ? 'var(--red)'
          : 'var(--orange)'

  const available = path
    ? (() => {
        const used = usedSteps(path.nodes)
        return store.allSteps.filter((s) => !used.has(s))
      })()
    : []

  return (
    <div className="col" style={{ flex: 1, minHeight: 0, gap: 0 }}>
      {/* ── Top bar ─────────────────────────────────────────────────────── */}
      <div
        className="row"
        style={{
          padding: '8px 16px',
          gap: 10,
          background: 'var(--bg-tertiary-grouped)',
          borderBottom: '1px solid var(--separator-soft)',
        }}
      >
        <span aria-hidden>🪧</span>
        <select
          className="select-input"
          style={{ width: 'auto', minWidth: 160 }}
          value={store.selectedHappyPathId ?? ''}
          onChange={(e) => store.selectHappyPath(e.target.value)}
        >
          {store.happyPaths.length === 0 && <option value="">No happy paths yet</option>}
          {store.happyPaths.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
        <button className="btn small" onClick={() => setNewPathName('')}>
          ＋ New
        </button>
        {path && (
          <>
            <button className="btn small" onClick={() => setRenaming(path)}>
              ✎ Rename
            </button>
            <button
              className="btn small destructive"
              onClick={() => store.deleteHappyPath(path.id)}
            >
              🗑 Delete
            </button>
          </>
        )}

        {score != null && (
          <div
            className="row"
            style={{
              gap: 6,
              padding: '5px 10px',
              borderRadius: 10,
              background: 'var(--material)',
              border: `1.5px solid ${
                score >= 0.7
                  ? 'rgba(52,199,89,0.45)'
                  : score <= 0.3
                    ? 'rgba(255,59,48,0.45)'
                    : 'rgba(255,149,0,0.45)'
              }`,
            }}
            title="Journey-count-weighted edge coverage"
          >
            <span aria-hidden style={{ color: scoreColor }}>
              🪧
            </span>
            <span className="t-caption fg-secondary">Conformance</span>
            <span className="t-headline tnum" style={{ color: scoreColor }}>
              {score.toFixed(2)}
            </span>
          </div>
        )}

        <span className="spacer" />
        {path && (
          <button
            className={`btn small${editMode ? ' prominent' : ''}`}
            onClick={() => setEditMode(!editMode)}
          >
            {editMode ? '✓ Done' : '✎ Edit Path'}
          </button>
        )}
      </div>

      {/* ── Body: actual map (left) + happy path (right) ────────────────── */}
      <div className="row" style={{ flex: 1, minHeight: 0, alignItems: 'stretch', gap: 0 }}>
        <div className="col" style={{ flex: 1, minWidth: 0, gap: 0 }}>
          <div
            className="row"
            style={{
              padding: '6px 14px',
              gap: 6,
              background: 'var(--bg-secondary-grouped)',
              borderBottom: '1px solid var(--separator-soft)',
            }}
          >
            <span className="t-caption fg-secondary" style={{ fontWeight: 600 }}>
              Actual Process
            </span>
            <span className="spacer" />
            {store.journeyCount != null && (
              <span className="t-caption2 fg-secondary tnum">
                {store.journeyCount.toLocaleString()} journeys
              </span>
            )}
          </div>
          {store.processGraph.transitions.length === 0 ? (
            <Unavailable
              glyph="📊"
              title="No Process Data"
              description="Apply filters in the sidebar to load the process map."
              action={
                <button className="btn prominent" onClick={() => void store.reloadGraph()}>
                  Load
                </button>
              }
            />
          ) : (
            <FlowChart
              graph={store.processGraph}
              projectId={store.selectedProject.projectId}
              chartMode="HappyPath"
              // Force 'Journey %' so the actual-process edges read as a share of all
              // journeys — the same measure the ideal-path diagram shows on each step
              // card (coverage = journeys through the step) — instead of the global metric.
              metric="Journey %"
              journeyTotal={store.journeyCount ?? 0}
              isLoading={store.isLoading}
              onNodeAction={(node, action) => store.handleNodeAction(node, action)}
              onMetaInfo={(node) => store.openMetaInfo(node)}
              notes={store.projectNotes}
              onNodeNote={notes.openNodeNotes}
              onEdgeNote={notes.openEdgeNotes}
            />
          )}
        </div>

        {/* Drag handle: resize the ideal-path pane by dragging left/right. */}
        <div
          role="separator"
          aria-orientation="vertical"
          aria-label="Resize the ideal-path panel"
          title="Drag to resize"
          onPointerDown={onResizeDown}
          onPointerMove={onResizeMove}
          onPointerUp={onResizeUp}
          onDoubleClick={() => {
            setDragWidth(null)
            setSavedWidth(460)
          }}
          className="hp-resize-handle"
          style={{
            width: 6,
            flexShrink: 0,
            cursor: 'col-resize',
            background: 'var(--separator)',
            touchAction: 'none',
          }}
        />

        <div
          className="col"
          style={{
            width: editorWidth,
            flexShrink: 0,
            background: 'var(--bg-secondary-grouped)',
            gap: 0,
            minHeight: 0,
          }}
        >
          <div
            className="row"
            style={{
              padding: '6px 14px',
              gap: 6,
              borderBottom: '1px solid var(--separator-soft)',
            }}
          >
            <span className="t-caption fg-secondary" style={{ fontWeight: 600 }}>
              {path?.name ?? 'Happy Path'}
            </span>
            <span className="spacer" />
            {editMode && path && available.length > 0 && (
              <AddStepMenu
                label="＋"
                steps={available}
                onPick={(step) =>
                  store.updateHappyPath(path.id, (p) => ({
                    ...p,
                    nodes: [...p.nodes, stepNode(step)],
                  }))
                }
              />
            )}
          </div>

          {!path ? (
            <div style={{ padding: 20 }}>
              <span className="t-footnote fg-secondary">
                Define an ideal step sequence to measure how closely real journeys follow
                your intended design. Create one with “＋ New”.
              </span>
            </div>
          ) : path.nodes.length === 0 ? (
            <Unavailable
              glyph="🪧"
              title="No Steps Defined"
              description={
                editMode
                  ? 'Use ＋ to add the first step.'
                  : 'Enable Edit Path to define the happy path.'
              }
            />
          ) : editMode ? (
            <HappyPathEditor
              path={path}
              available={available}
              inGraph={inGraph}
              onRename={(splitId, field, value) =>
                setRenamingSplit({ pathId: path.id, splitId, field, value })
              }
            />
          ) : (
            <HappyPathVisualisation path={path} coverage={coverage} inGraph={inGraph} />
          )}
        </div>
      </div>

      {newPathName !== null && (
        <PromptSheet
          title="New Happy Path"
          message="Give the ideal step sequence a name."
          onCancel={() => setNewPathName(null)}
          onConfirm={(name) => {
            store.createHappyPath(name)
            setNewPathName(null)
            setEditMode(true)
          }}
        />
      )}
      {renaming && (
        <PromptSheet
          title="Rename Happy Path"
          initialValue={renaming.name}
          confirmLabel="Rename"
          onCancel={() => setRenaming(null)}
          onConfirm={(name) => {
            store.renameHappyPath(renaming.id, name)
            setRenaming(null)
          }}
        />
      )}
      {renamingSplit && (
        <PromptSheet
          title={renamingSplit.field === 'rejoinLabel' ? 'Name Rejoin' : 'Rename Split'}
          initialValue={renamingSplit.value}
          confirmLabel="Save"
          onCancel={() => setRenamingSplit(null)}
          onConfirm={(value) => {
            const field = renamingSplit.field
            store.updateHappyPath(renamingSplit.pathId, (p) => ({
              ...p,
              nodes: updateNode(p.nodes, renamingSplit.splitId, (n) => ({ ...n, [field]: value })),
            }))
            setRenamingSplit(null)
          }}
        />
      )}

      {notes.element}
    </div>
  )
}

// ── View mode: the trunk → fork → branches visualisation ──────────────────────

function StepVizCard({
  name,
  inGraph,
  coverage,
}: {
  name: string
  inGraph: boolean
  coverage?: number
}) {
  return (
    <div
      style={{
        display: 'grid',
        justifyItems: 'center',
        gap: 2,
        padding: '10px 12px',
        borderRadius: 8,
        background: inGraph ? 'rgba(52,199,89,0.12)' : 'rgba(120,120,128,0.08)',
        border: `1px solid ${inGraph ? 'rgba(52,199,89,0.5)' : 'var(--separator-soft)'}`,
        textAlign: 'center',
      }}
      title={inGraph ? name : `${name} — not present in the filtered process`}
    >
      <span
        className="t-caption"
        style={{ fontWeight: 500, color: inGraph ? 'var(--primary)' : 'var(--secondary)' }}
      >
        {name}
      </span>
      {inGraph && coverage != null && (
        <span
          className="t-caption2 tnum"
          style={{ color: 'rgba(52,199,89,0.85)', fontWeight: 600 }}
        >
          {Math.round(coverage * 100)}%
        </span>
      )}
    </div>
  )
}

function Chevron() {
  return (
    <div
      className="fg-secondary"
      style={{ textAlign: 'center', fontSize: 11, padding: '3px 0', lineHeight: 1 }}
      aria-hidden
    >
      ⌄
    </div>
  )
}

function ForkLine({ glyph, label }: { glyph: string; label: string }) {
  return (
    <div className="row" style={{ gap: 6, padding: '8px 24px 0', alignItems: 'center' }}>
      <div style={{ flex: 1, height: 1, background: 'rgba(120,120,128,0.25)' }} />
      <span className="fg-secondary t-caption2" aria-hidden>
        {glyph} {label}
      </span>
      <div style={{ flex: 1, height: 1, background: 'rgba(120,120,128,0.25)' }} />
    </div>
  )
}

/** Recursive view of a node list: step cards in sequence; a split renders a fork,
 *  side-by-side branch columns (each a recursive NodeListViz), and — when steps
 *  follow the split — a rejoin marker before the shared continuation. */
function NodeListViz({
  nodes,
  coverage,
  inGraph,
}: {
  nodes: HappyPathNode[]
  coverage: Record<string, number>
  inGraph: Set<string>
}) {
  return (
    <div className="col" style={{ gap: 0 }}>
      {nodes.map((node, i) => (
        <div key={node.id}>
          {isSplit(node) ? (
            <SplitViz
              node={node}
              coverage={coverage}
              inGraph={inGraph}
              showRejoin={i < nodes.length - 1}
            />
          ) : (
            <div style={{ padding: '0 24px' }}>
              <StepVizCard
                name={node.step}
                inGraph={inGraph.has(node.step)}
                coverage={coverage[node.step]}
              />
            </div>
          )}
          {i < nodes.length - 1 && <Chevron />}
        </div>
      ))}
    </div>
  )
}

function SplitViz({
  node,
  coverage,
  inGraph,
  showRejoin,
}: {
  node: HappyPathNode
  coverage: Record<string, number>
  inGraph: Set<string>
  showRejoin: boolean
}) {
  return (
    <div className="col" style={{ gap: 0 }}>
      <ForkLine glyph="⑂" label={node.label || 'Split'} />
      <div className="row" style={{ alignItems: 'flex-start', gap: 0 }}>
        {node.branches.map((branch, bi) => (
          <div key={bi} className="row" style={{ flex: 1, minWidth: 0, gap: 0 }}>
            {bi > 0 && (
              <div style={{ width: 1, alignSelf: 'stretch', background: 'var(--separator)' }} />
            )}
            <div className="col" style={{ flex: 1, minWidth: 0, gap: 0, padding: '10px 6px 12px' }}>
              <span
                className="t-caption2 fg-secondary"
                style={{ fontWeight: 600, textAlign: 'center', paddingBottom: 6 }}
              >
                Branch {bi + 1}
              </span>
              {branch.length === 0 ? (
                <span className="t-caption2 fg-tertiary" style={{ textAlign: 'center', padding: 12 }}>
                  No steps
                </span>
              ) : (
                <NodeListViz nodes={branch} coverage={coverage} inGraph={inGraph} />
              )}
            </div>
          </div>
        ))}
      </div>
      {showRejoin && <ForkLine glyph="⑃" label={node.rejoinLabel || 'rejoin'} />}
    </div>
  )
}

function HappyPathVisualisation({
  path,
  coverage,
  inGraph,
}: {
  path: HappyPath
  coverage: Record<string, number>
  inGraph: Set<string>
}) {
  return (
    <div className="scroll-view" style={{ gap: 0, padding: '16px 0 24px' }}>
      <NodeListViz nodes={path.nodes} coverage={coverage} inGraph={inGraph} />
    </div>
  )
}

// ── Edit mode ─────────────────────────────────────────────────────────────────

function AddStepMenu({
  label,
  steps,
  onPick,
}: {
  label: string
  steps: string[]
  onPick: (step: string) => void
}) {
  return (
    <select
      className="select-input"
      style={{ width: 'auto', maxWidth: 180 }}
      value=""
      onChange={(e) => {
        if (e.target.value) onPick(e.target.value)
      }}
      title="Add a step"
    >
      <option value="">{label} Add step…</option>
      {steps.map((s) => (
        <option key={s} value={s}>
          {s}
        </option>
      ))}
    </select>
  )
}

function EditStepRow({
  name,
  inGraph,
  canMoveUp,
  canMoveDown,
  onMove,
  onRemove,
}: {
  name: string
  inGraph: boolean
  canMoveUp: boolean
  canMoveDown: boolean
  onMove: (delta: number) => void
  onRemove: () => void
}) {
  return (
    <div className="row" style={{ gap: 6 }}>
      <div
        className="row spacer"
        style={{
          padding: '7px 12px',
          borderRadius: 8,
          background: inGraph ? 'rgba(52,199,89,0.12)' : 'rgba(120,120,128,0.08)',
          border: `1px solid ${inGraph ? 'rgba(52,199,89,0.5)' : 'var(--separator-soft)'}`,
          fontSize: 12,
          fontWeight: 500,
          minWidth: 0,
          color: inGraph ? 'var(--primary)' : 'var(--secondary)',
        }}
        title={inGraph ? name : `${name} — not present in the filtered process`}
      >
        <span className="truncate">{name}</span>
      </div>
      <button
        className="icon-btn"
        style={{ width: 20, height: 20, fontSize: 10 }}
        disabled={!canMoveUp}
        title="Move up"
        onClick={() => onMove(-1)}
      >
        ▲
      </button>
      <button
        className="icon-btn"
        style={{ width: 20, height: 20, fontSize: 10 }}
        disabled={!canMoveDown}
        title="Move down"
        onClick={() => onMove(1)}
      >
        ▼
      </button>
      <button
        className="icon-btn"
        style={{ width: 20, height: 20, fontSize: 12, color: 'var(--red)' }}
        title="Remove step"
        onClick={onRemove}
      >
        ⊖
      </button>
    </div>
  )
}

function HappyPathEditor({
  path,
  available,
  inGraph,
  onRename,
}: {
  path: HappyPath
  available: string[]
  inGraph: Set<string>
  onRename: (splitId: string, field: 'label' | 'rejoinLabel', value: string) => void
}) {
  const store = useStore()
  const setNodes = (nodes: HappyPathNode[]) =>
    store.updateHappyPath(path.id, (p) => ({ ...p, nodes }))

  return (
    <div className="scroll-view" style={{ gap: 14 }}>
      <NodeListEditor
        nodes={path.nodes}
        onChange={setNodes}
        available={available}
        inGraph={inGraph}
        onRename={onRename}
      />
      <span className="t-caption2 fg-tertiary">
        Add a ⑂ Split for alternatives that rejoin — steps after a split are the shared
        continuation, and a split can be added inside a branch. Each journey is scored
        against the route it matches best.
      </span>
      <button
        className="btn small"
        style={{ alignSelf: 'flex-start' }}
        onClick={() => void store.refreshHappyPathConformance()}
      >
        ↻ Recompute conformance
      </button>
    </div>
  )
}

/** Controlled recursive editor for a node list: step rows and split cards (each
 *  containing nested NodeListEditors), plus ＋ Step / ⑂ Split controls. */
function NodeListEditor({
  nodes,
  onChange,
  available,
  inGraph,
  onRename,
}: {
  nodes: HappyPathNode[]
  onChange: (nodes: HappyPathNode[]) => void
  available: string[]
  inGraph: Set<string>
  onRename: (splitId: string, field: 'label' | 'rejoinLabel', value: string) => void
}) {
  const move = (i: number, delta: number) => {
    const t = i + delta
    if (t < 0 || t >= nodes.length) return
    const next = [...nodes]
    ;[next[i], next[t]] = [next[t], next[i]]
    onChange(next)
  }
  const removeAt = (i: number) => onChange(nodes.filter((_, idx) => idx !== i))

  return (
    <div className="col" style={{ gap: 6 }}>
      {nodes.map((node, i) =>
        isSplit(node) ? (
          <SplitEditor
            key={node.id}
            node={node}
            onChange={(n) => onChange(nodes.map((x, idx) => (idx === i ? n : x)))}
            onRemove={() => removeAt(i)}
            canMoveUp={i > 0}
            canMoveDown={i < nodes.length - 1}
            onMove={(d) => move(i, d)}
            hasContinuation={i < nodes.length - 1}
            available={available}
            inGraph={inGraph}
            onRename={onRename}
          />
        ) : (
          <EditStepRow
            key={node.id}
            name={node.step}
            inGraph={inGraph.has(node.step)}
            canMoveUp={i > 0}
            canMoveDown={i < nodes.length - 1}
            onMove={(d) => move(i, d)}
            onRemove={() => removeAt(i)}
          />
        ),
      )}
      <div className="row" style={{ gap: 6 }}>
        {available.length > 0 && (
          <AddStepMenu
            label="＋"
            steps={available}
            onPick={(step) => onChange([...nodes, stepNode(step)])}
          />
        )}
        <button
          className="btn small"
          title="Add a split — alternatives that rejoin and continue"
          onClick={() => onChange([...nodes, splitNode()])}
        >
          ⑂ Split
        </button>
      </div>
    </div>
  )
}

function SplitEditor({
  node,
  onChange,
  onRemove,
  canMoveUp,
  canMoveDown,
  onMove,
  hasContinuation,
  available,
  inGraph,
  onRename,
}: {
  node: HappyPathNode
  onChange: (n: HappyPathNode) => void
  onRemove: () => void
  canMoveUp: boolean
  canMoveDown: boolean
  onMove: (delta: number) => void
  hasContinuation: boolean
  available: string[]
  inGraph: Set<string>
  onRename: (splitId: string, field: 'label' | 'rejoinLabel', value: string) => void
}) {
  const setBranch = (bi: number, branchNodes: HappyPathNode[]) =>
    onChange({ ...node, branches: node.branches.map((b, idx) => (idx === bi ? branchNodes : b)) })

  return (
    <div
      className="col"
      style={{
        gap: 8,
        padding: 8,
        borderRadius: 8,
        background: 'var(--bg-fill)',
        border: '1px solid var(--separator-soft)',
      }}
    >
      <div className="row" style={{ gap: 4, alignItems: 'center' }}>
        <span aria-hidden>⑂</span>
        <span className="t-caption spacer" style={{ fontWeight: 600 }}>
          {node.label || 'Split'}
        </span>
        <button
          className="icon-btn"
          style={{ width: 20, height: 20, fontSize: 11 }}
          title="Rename split"
          onClick={() => onRename(node.id, 'label', node.label)}
        >
          ✎
        </button>
        <button
          className="icon-btn"
          style={{ width: 20, height: 20, fontSize: 10 }}
          disabled={!canMoveUp}
          title="Move up"
          onClick={() => onMove(-1)}
        >
          ▲
        </button>
        <button
          className="icon-btn"
          style={{ width: 20, height: 20, fontSize: 10 }}
          disabled={!canMoveDown}
          title="Move down"
          onClick={() => onMove(1)}
        >
          ▼
        </button>
        <button
          className="icon-btn"
          style={{ width: 20, height: 20, fontSize: 11, color: 'var(--red)' }}
          title="Delete split"
          onClick={onRemove}
        >
          🗑
        </button>
      </div>

      <div className="row" style={{ gap: 8, alignItems: 'flex-start' }}>
        {node.branches.map((branch, bi) => (
          <div
            key={bi}
            className="col"
            style={{
              flex: 1,
              minWidth: 0,
              gap: 6,
              padding: 8,
              borderRadius: 6,
              background: 'var(--bg-secondary-grouped)',
            }}
          >
            <div className="row" style={{ alignItems: 'center' }}>
              <span className="t-caption2 fg-secondary spacer" style={{ fontWeight: 600 }}>
                Branch {bi + 1}
              </span>
              {node.branches.length > 2 && (
                <button
                  className="icon-btn"
                  style={{ width: 18, height: 18, fontSize: 10, color: 'var(--red)' }}
                  title="Delete branch"
                  onClick={() =>
                    onChange({ ...node, branches: node.branches.filter((_, idx) => idx !== bi) })
                  }
                >
                  🗑
                </button>
              )}
            </div>
            <NodeListEditor
              nodes={branch}
              onChange={(n) => setBranch(bi, n)}
              available={available}
              inGraph={inGraph}
              onRename={onRename}
            />
          </div>
        ))}
      </div>

      <div className="row" style={{ gap: 8, alignItems: 'center' }}>
        <button
          className="btn small"
          onClick={() => onChange({ ...node, branches: [...node.branches, []] })}
        >
          ＋ Branch
        </button>
        {hasContinuation && (
          <button
            className="btn small"
            title="Name the point where these branches rejoin"
            onClick={() => onRename(node.id, 'rejoinLabel', node.rejoinLabel || '')}
          >
            ✎ Rejoin: {node.rejoinLabel || 'rejoin'}
          </button>
        )}
      </div>
    </div>
  )
}
