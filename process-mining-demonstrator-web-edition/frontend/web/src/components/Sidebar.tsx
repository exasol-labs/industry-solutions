/** Left panel — port of SidebarView.swift.
 *
 * Accordion sections (Connections · Projects · Metrics · Filters · Sampling ·
 * Configuration): opening one collapses the others, exactly like the Swift
 * `collapseAllSections()` behaviour. */

import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { KPI_DEFAULT_ORDER, KPI_META, TRANSITION_METRICS } from '../types'
import type {
  AssignedConnection,
  FilterGroup,
  GraphStartMode,
  ManagedConnection,
  TransitionMetric,
} from '../types'
import { formatSecs } from '../graph/format'
import { useSetting } from '../settings'
import { api } from '../api'
import { DEFAULT_LLM_PROMPT, useStore } from '../store'
import { AuthFooter } from './AuthFooter'
import { ConnectionEditor } from './ConnectionEditor'
import { Logo } from './Logo'
import { SamplingSection } from './SamplingSection'
import { StepEditor } from './StepEditor'
import { ThemeBar } from './ThemeBar'
import {
  AutocompleteField,
  Chevron,
  Divider,
  PromptSheet,
  RangeSlider,
  Segmented,
  Sheet,
  Spinner,
  Switch,
  ToggleRow,
} from './ui'

type SectionId =
  | 'connections'
  | 'projects'
  | 'metrics'
  | 'filters'
  | 'sampling'
  | 'config'

export function Sidebar({ onCollapse }: { onCollapse: () => void }) {
  const store = useStore()
  // The Projects header count must match the visible list, which hides aggregate
  // detail projects unless this setting is on.
  const [showAggDetailProjects] = useSetting<boolean>('aggregates.showProjects')
  const [openSection, setOpenSection] = useState<SectionId | null>('connections')
  const [showPromptEditor, setShowPromptEditor] = useState(false)
  const [showSavePreset, setShowSavePreset] = useState(false)
  // Power/admin only: the connection being created (null) or edited.
  const [connEditor, setConnEditor] = useState<
    { conn: ManagedConnection | null } | null
  >(null)
  const canManageConnections =
    store.authIsPower || store.authIsAdmin || store.authIsDeveloper
  // Journey sampling (creating/deleting representative subsets, choosing A/B
  // sources) is a power/admin capability, matching the advanced analysis views.
  const canSample = store.authIsPower || store.authIsAdmin
  // Individual Journey always renders with a fixed metric (Avg Time), so its
  // metric picker is hidden.
  const isIndividualJourney = store.activeChartMode === 'Individual Journey'

  const toggleSection = (id: SectionId) =>
    setOpenSection((current) => (current === id ? null : id))

  // Switching to Individual Journey opens the Filters section (its Event ID
  // field) so you can start typing immediately. Fires only on the mode change,
  // so you can still collapse it afterwards.
  useEffect(() => {
    if (store.activeChartMode === 'Individual Journey') setOpenSection('filters')
  }, [store.activeChartMode])

  return (
    <aside className="sidebar">
      <div className="sidebar-scroll">
        <BrandHeader />
        <Divider />

        <SectionHeader
          title="Connections"
          count={store.connections.length}
          open={openSection === 'connections'}
          onToggle={() => toggleSection('connections')}
          trailing={
            <>
              {canManageConnections && (
                <button
                  className="icon-btn"
                  title="New connection"
                  onClick={() => {
                    void store.refreshManageable()
                    setConnEditor({ conn: null })
                  }}
                >
                  ＋
                </button>
              )}
              <button
                className="icon-btn"
                title="Refresh connections"
                onClick={() => void store.refreshConnections()}
              >
                ↻
              </button>
            </>
          }
        />
        {openSection === 'connections' && (
          <ConnectionsList
            onConnected={() => setOpenSection('projects')}
            onEdit={
              canManageConnections ? (conn) => setConnEditor({ conn }) : undefined
            }
          />
        )}
        <Divider />

        <SectionHeader
          title="Projects"
          count={
            visibleProjects(
              store.projects,
              showAggDetailProjects,
              store.selectedProject?.projectId,
            ).length
          }
          open={openSection === 'projects'}
          onToggle={() => toggleSection('projects')}
          trailing={
            <button
              className="icon-btn"
              title="Reload projects"
              disabled={!store.connection.isConnected}
              onClick={() => void store.loadProjects()}
            >
              ↻
            </button>
          }
        />
        {openSection === 'projects' && (
          <ProjectsList onSelected={() => setOpenSection(null)} />
        )}
        <Divider />

        {!isIndividualJourney && (
          <>
            <SectionHeader
              title="Metrics"
              open={openSection === 'metrics'}
              onToggle={() => toggleSection('metrics')}
            />
            {openSection === 'metrics' && <MetricsSection />}
            <Divider />
          </>
        )}

        <SectionHeader
          title="Filters"
          open={openSection === 'filters'}
          onToggle={() => toggleSection('filters')}
        />
        {openSection === 'filters' && (
          <FiltersSection onSavePreset={() => setShowSavePreset(true)} />
        )}
        <Divider />

        {!isIndividualJourney && canSample && (
          <>
            <SectionHeader
              title="Sampling"
              open={openSection === 'sampling'}
              onToggle={() => toggleSection('sampling')}
            />
            {openSection === 'sampling' && <SamplingSection />}
            <Divider />
          </>
        )}

        <SectionHeader
          title="Configuration"
          open={openSection === 'config'}
          onToggle={() => toggleSection('config')}
        />
        {openSection === 'config' && (
          <ConfigSection onEditPrompt={() => setShowPromptEditor(true)} />
        )}
      </div>

      <AuthFooter />

      <Divider />
      <ThemeBar onCollapse={onCollapse} />

      {connEditor && (
        <ConnectionEditor
          connection={connEditor.conn}
          onClose={() => setConnEditor(null)}
        />
      )}
      {showPromptEditor && (
        <PromptEditorSheet onClose={() => setShowPromptEditor(false)} />
      )}
      {showSavePreset && (
        <PromptSheet
          title="Save Filter Preset"
          message="Saves the current filter settings as a named preset."
          onCancel={() => setShowSavePreset(false)}
          onConfirm={(name) => {
            store.createFilterGroup(name)
            setShowSavePreset(false)
          }}
        />
      )}
    </aside>
  )
}

// ── Branding ─────────────────────────────────────────────────────────────────

function BrandHeader() {
  return (
    <div className="brand-header">
      <div className="brand-logo" aria-hidden>
        <Logo />
      </div>
      <div className="col" style={{ gap: 2 }}>
        <span className="t-title3">Process Mining</span>
        <span className="t-caption fg-secondary">Demonstrator</span>
      </div>
    </div>
  )
}

// ── Section chrome ───────────────────────────────────────────────────────────

function SectionHeader({
  title,
  count,
  open,
  onToggle,
  trailing,
}: {
  title: string
  count?: number
  open: boolean
  onToggle: () => void
  trailing?: ReactNode
}) {
  return (
    <div className="section-header">
      <button className="section-toggle" onClick={onToggle}>
        <Chevron open={open} />
        <span className="section-title">{title}</span>
        {count != null && count > 0 && <span className="section-count">({count})</span>}
      </button>
      {trailing}
    </div>
  )
}

function SubHeader({
  title,
  open,
  onToggle,
  badge,
  onClear,
  icon,
}: {
  title: string
  open: boolean
  onToggle: () => void
  badge?: string
  onClear?: () => void
  icon?: string
}) {
  return (
    <div className="sub-header">
      <button onClick={onToggle}>
        <Chevron open={open} />
        {icon && (
          <span aria-hidden style={{ width: 16, textAlign: 'center' }}>
            {icon}
          </span>
        )}
        <span className="sub-title">{title}</span>
      </button>
      {badge && <span className="badge-pill">{badge}</span>}
      {onClear && (
        <button
          className="icon-btn"
          style={{ color: 'var(--secondary)', width: 20, height: 20 }}
          title={`Clear ${title}`}
          onClick={onClear}
        >
          ⊗
        </button>
      )}
    </div>
  )
}

// ── Connections ──────────────────────────────────────────────────────────────

function ConnectionsList({
  onConnected,
  onEdit,
}: {
  onConnected: () => void
  onEdit?: (conn: ManagedConnection) => void
}) {
  const store = useStore()
  // "Aggregate Connections" setting = visibility of connections that hold ONLY aggregate
  // detail data. Source / high-level connections are always visible, as is the active one.
  const [showAggConns] = useSetting<boolean>('aggregates.showConnections')
  const sorted = useMemo(() => {
    const all = [...store.connections].sort((a, b) => a.name.localeCompare(b.name))
    if (showAggConns) return all
    return all.filter(
      (c) => !c.aggregateDetailOnly || store.connection.activeProfileId === c.id,
    )
  }, [store.connections, showAggConns, store.connection.activeProfileId])
  // Connections this power user owns and may edit, keyed by id.
  const manageableById = useMemo(
    () => new Map(store.manageableConnections.map((c) => [c.id, c])),
    [store.manageableConnections],
  )

  const connectOrDisconnect = async (conn: AssignedConnection) => {
    const isActive = store.connection.activeProfileId === conn.id
    if (store.connection.isConnected && isActive) {
      await store.disconnect()
      return
    }
    if (store.connection.isConnected) await store.disconnect()
    const ok = await store.connectConnection(conn)
    if (ok) onConnected()
  }

  if (sorted.length === 0) {
    return (
      <div className="card-list">
        <span className="empty-hint">
          {onEdit
            ? 'No connections yet. Use ＋ above to create one and assign users.'
            : 'No connections assigned to you. Ask an administrator to grant access.'}
        </span>
        {store.connection.lastError && (
          <span className="t-caption fg-red">{store.connection.lastError}</span>
        )}
      </div>
    )
  }

  return (
    <div className="card-list" style={{ maxHeight: 300 }}>
      {sorted.map((conn) => {
        const isActive = store.connection.activeProfileId === conn.id
        const isConnected = store.connection.isConnected && isActive

        return (
          <div
            key={conn.id}
            className={`card${isActive ? ' selected' : ''}`}
            style={{ minHeight: 64 }}
            onClick={() => void connectOrDisconnect(conn)}
          >
            <span
              aria-hidden
              style={{ fontSize: 17, color: isConnected ? 'var(--green)' : 'var(--accent)' }}
            >
              ⛁
            </span>
            <div className="card-body">
              <span className="card-title">
                {conn.hasAggregates && (
                  <span className="agg-sigma-tag" title="Holds aggregate (Σ) projects">
                    Σ
                  </span>
                )}
                {conn.name || '(unnamed)'}
              </span>
              {conn.comment && <span className="card-sub">{conn.comment}</span>}
              <span className="card-sub">
                Database: {conn.host || '(no host)'}:{conn.port}
              </span>
              {conn.hasLLM && (
                <span className="card-sub">LLM: {conn.llmURL || '(configured)'}</span>
              )}
            </div>
            {onEdit && manageableById.has(conn.id) && (
              <button
                className="icon-btn"
                style={{ width: 22, height: 22, color: 'var(--secondary)' }}
                title="Edit connection"
                onClick={(e) => {
                  e.stopPropagation()
                  onEdit(manageableById.get(conn.id)!)
                }}
              >
                ✎
              </button>
            )}
            {isActive && (
              <div className="col" style={{ gap: 4, alignItems: 'center' }}>
                <span
                  className="status-dot"
                  style={{ background: isConnected ? 'var(--green)' : 'var(--orange)' }}
                  title={isConnected ? 'Connected' : 'Not connected'}
                />
                {conn.hasLLM && (
                  <span
                    className="status-dot"
                    style={{
                      background: store.connection.isLLMReachable
                        ? 'var(--blue)'
                        : 'var(--orange)',
                    }}
                    title={
                      store.connection.isLLMReachable
                        ? 'LLM reachable'
                        : 'LLM not reachable'
                    }
                  />
                )}
              </div>
            )}
          </div>
        )
      })}
      {store.connection.lastError && !store.connection.isConnected && (
        <span className="t-caption fg-red">{store.connection.lastError}</span>
      )}
    </div>
  )
}

// ── Projects ─────────────────────────────────────────────────────────────────

/** TITLE_SHORT marks an aggregate: 'Σ…' = a high-level Σ map, '#…' = a detail map. */
function aggregateKind(titleShort: string): 'high' | 'detail' | null {
  if ((titleShort || '').startsWith('#')) return 'detail'
  if ((titleShort || '').startsWith('Σ')) return 'high'
  return null
}

/** The projects shown in the sidebar list — aggregate DETAIL projects are hidden unless
 *  "Show aggregate detail projects" is on (the currently-open project is never hidden).
 *  The list AND the header count must use this so the badge matches the rows. */
export function visibleProjects<T extends { projectId: number; titleShort: string }>(
  projects: readonly T[],
  showAggDetails: boolean,
  selectedId: number | undefined,
): T[] {
  if (showAggDetails) return [...projects]
  return projects.filter(
    (p) => aggregateKind(p.titleShort) !== 'detail' || selectedId === p.projectId,
  )
}

function ProjectsList({ onSelected }: { onSelected: () => void }) {
  const store = useStore()
  // "Aggregate Projects" setting = visibility of aggregate DETAIL projects. High-level maps
  // (and normal projects) are always visible; the currently-open project is never hidden.
  const [showAggDetails] = useSetting<boolean>('aggregates.showProjects')
  const projects = useMemo(
    () => visibleProjects(store.projects, showAggDetails, store.selectedProject?.projectId),
    [store.projects, showAggDetails, store.selectedProject],
  )

  if (!store.connection.isConnected) {
    return (
      <div className="card-list">
        <span className="empty-hint">Connect to a database to load projects.</span>
      </div>
    )
  }
  if (store.isLoading && store.projects.length === 0) {
    return (
      <div className="card-list">
        <span className="row empty-hint">
          <Spinner /> Loading
        </span>
      </div>
    )
  }
  if (store.projects.length === 0) {
    return (
      <div className="card-list">
        <span className="empty-hint">No projects found.</span>
      </div>
    )
  }

  return (
    <div className="card-list" style={{ maxHeight: 240 }}>
      {projects.map((project) => {
        const selected = store.selectedProject?.projectId === project.projectId
        const agg = aggregateKind(project.titleShort)
        return (
          <button
            key={project.projectId}
            className={`card${selected ? ' selected' : ''}`}
            onClick={() => {
              void store.selectProject(project)
              onSelected()
            }}
          >
            <span aria-hidden className="fg-accent">
              📈
            </span>
            <div className="card-body">
              <span className="card-title">
                {agg && (
                  <span
                    className="agg-sigma-tag"
                    title={agg === 'high' ? 'High-level aggregate map' : 'Aggregate detail (drill-down)'}
                  >
                    Σ{agg === 'detail' ? '↳' : ''}
                  </span>
                )}
                {project.title}
              </span>
              {project.description && (
                <span className="card-sub">{project.description}</span>
              )}
            </div>
            {selected && <span className="fg-accent">✓</span>}
          </button>
        )
      })}
    </div>
  )
}

// ── Metrics ──────────────────────────────────────────────────────────────────

const METRIC_ICONS: Record<TransitionMetric, string> = {
  Count: '#',
  Percentage: '%',
  'Journey %': '%',
  'Avg Time': '⏱',
  'Median Time': '½',
  'Min Time': '⌄',
  'Max Time': '⌃',
  'Std Dev': '〰',
}

function MetricsSection() {
  const store = useStore()
  return (
    <div className="col" style={{ padding: '10px 20px', gap: 8 }}>
      <span className="t-caption fg-secondary" style={{ fontWeight: 600 }}>
        ƒ Transition metric
      </span>
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: '1fr 1fr',
          gap: 6,
        }}
      >
        {TRANSITION_METRICS.map((m) => (
          <button
            key={m}
            className={`chip${store.transitionMetric === m ? ' active' : ''}`}
            style={{ justifyContent: 'center', borderRadius: 7 }}
            disabled={!store.selectedProject}
            onClick={() => store.setTransitionMetric(m)}
          >
            <span aria-hidden>{METRIC_ICONS[m]}</span> {m}
          </button>
        ))}
      </div>
    </div>
  )
}

// ── Filters ──────────────────────────────────────────────────────────────────

function StepFilterList({
  steps,
  selected,
  disabledSteps,
  onToggle,
}: {
  steps: string[]
  selected: string[]
  disabledSteps: string[]
  onToggle: (step: string) => void
}) {
  const [search, setSearch] = useState('')
  const filtered = search
    ? steps.filter((s) => s.toLowerCase().includes(search.toLowerCase()))
    : steps

  return (
    <div className="step-filter">
      <div className="search-row">
        <span aria-hidden className="fg-secondary">
          🔍
        </span>
        <input
          value={search}
          placeholder="Search"
          onChange={(e) => setSearch(e.target.value)}
        />
        {search && (
          <button
            className="fg-secondary"
            onClick={() => setSearch('')}
            title="Clear search"
          >
            ⊗
          </button>
        )}
      </div>
      <div className="step-list">
        {steps.length === 0 ? (
          <span className="t-caption2 fg-tertiary" style={{ padding: '4px 8px' }}>
            No project selected
          </span>
        ) : filtered.length === 0 ? (
          <span className="t-caption2 fg-tertiary" style={{ padding: '4px 8px' }}>
            No matches
          </span>
        ) : (
          filtered.map((step) => {
            const isSelected = selected.includes(step)
            const isDisabled = disabledSteps.includes(step)
            return (
              <button
                key={step}
                className={`step-row${isSelected ? ' selected' : ''}${
                  isDisabled ? ' disabled' : ''
                }`}
                disabled={isDisabled}
                onClick={() => onToggle(step)}
              >
                <span className="mark">{isSelected ? '◉' : '○'}</span>
                <span className="truncate">{step}</span>
              </button>
            )
          })
        )}
      </div>
    </div>
  )
}

function FiltersSection({ onSavePreset }: { onSavePreset: () => void }) {
  const store = useStore()
  const [dateOpen, setDateOpen] = useSetting<boolean>('sidebar.filtersDateExpanded')
  const [includeOpen, setIncludeOpen] = useSetting<boolean>(
    'sidebar.filtersIncludeExpanded',
  )
  const [excludeOpen, setExcludeOpen] = useSetting<boolean>(
    'sidebar.filtersExcludeExpanded',
  )
  const [stepsOpen, setStepsOpen] = useSetting<boolean>('sidebar.filtersStepsExpanded')
  const [timeOpen, setTimeOpen] = useSetting<boolean>(
    'sidebar.filtersJourneyTimeExpanded',
  )
  const [scoreOpen, setScoreOpen] = useSetting<boolean>('sidebar.filtersScoreExpanded')
  const [metaOpen, setMetaOpen] = useSetting<boolean>('sidebar.filtersMetaExpanded')

  const disabled = !store.selectedProject
  const isStatistics = store.activeChartMode === 'Statistics'
  const apply = () =>
    isStatistics ? void store.loadStatistics() : void store.reloadGraph()

  // The Individual Journey and AI views use their own filter UI.
  if (store.activeChartMode === 'Individual Journey') {
    return <EventIdFilter />
  }
  if (store.activeChartMode === 'AI supported Documentation') {
    return (
      <div className="row" style={{ padding: '12px 20px', gap: 8, alignItems: 'flex-start' }}>
        <span aria-hidden className="fg-secondary">
          ⓘ
        </span>
        <span className="t-caption fg-secondary">
          AI supported Documentation uses the filter conditions from the A-Chart.
        </span>
      </div>
    )
  }

  const stepsActive =
    store.minStepsFilter > store.stepCountMin || store.maxStepsFilter < store.stepCountMax
  const timeActive =
    store.minJourneyTimeFilter > store.journeyTimeBoundsMin ||
    store.maxJourneyTimeFilter < store.journeyTimeBoundsMax
  const scoreActive =
    store.minScoreFilter > store.scoreBoundsMin || store.maxScoreFilter < store.scoreBoundsMax
  const metaCount =
    (store.meta1Title && store.meta1Filter ? 1 : 0) +
    (store.meta2Title && store.meta2Filter ? 1 : 0) +
    (store.meta3Title && store.meta3Filter ? 1 : 0)
  const hasMeta = !!(store.meta1Title || store.meta2Title || store.meta3Title)

  const maxSteps = Math.max(store.stepCountMin, store.stepCountMax)
  const maxTime = Math.max(store.journeyTimeBoundsMin + 1, store.journeyTimeBoundsMax)
  const maxScore = Math.max(store.scoreBoundsMin + 1, store.scoreBoundsMax)

  return (
    <div className="col" style={{ gap: 0 }}>
      {store.activeChartMode === 'A/B Comparison' && (
        <>
          <div className="row" style={{ padding: '8px 20px', gap: 10 }}>
            <span className="t-caption fg-secondary">Editing:</span>
            <Segmented
              options={[
                { value: 'a', label: 'A-Chart' },
                { value: 'b', label: 'B-Chart' },
              ]}
              value={store.abActiveSide}
              onChange={(side) => store.switchABSide(side)}
            />
          </div>
          <Divider />
        </>
      )}

      <SubHeader title="Date" open={dateOpen} onToggle={() => setDateOpen(!dateOpen)} />
      {dateOpen && (
        <div className="col" style={{ padding: '0 20px 10px', gap: 8 }}>
          <div className="row">
            <span className="t-footnote fg-secondary" style={{ width: 34 }}>
              From
            </span>
            <input
              className="text-input"
              type="date"
              value={store.fromDate}
              onChange={(e) => store.patch({ fromDate: e.target.value })}
            />
          </div>
          <div className="row">
            <span className="t-footnote fg-secondary" style={{ width: 34 }}>
              To
            </span>
            <input
              className="text-input"
              type="date"
              value={store.toDate}
              onChange={(e) => store.patch({ toDate: e.target.value })}
            />
          </div>
        </div>
      )}
      <Divider />

      <SubHeader
        title="Include Steps"
        open={includeOpen}
        onToggle={() => setIncludeOpen(!includeOpen)}
        badge={store.includedSteps.length ? String(store.includedSteps.length) : undefined}
        onClear={
          store.includedSteps.length ? () => store.patch({ includedSteps: [] }) : undefined
        }
      />
      {includeOpen && (
        <div style={{ padding: '0 20px 10px' }}>
          <StepFilterList
            steps={store.allSteps}
            selected={store.includedSteps}
            disabledSteps={store.excludedSteps}
            onToggle={(step) =>
              store.patch({
                includedSteps: store.includedSteps.includes(step)
                  ? store.includedSteps.filter((s) => s !== step)
                  : [...store.includedSteps, step],
              })
            }
          />
        </div>
      )}
      <Divider />

      <SubHeader
        title="Exclude Steps"
        open={excludeOpen}
        onToggle={() => setExcludeOpen(!excludeOpen)}
        badge={store.excludedSteps.length ? String(store.excludedSteps.length) : undefined}
        onClear={
          store.excludedSteps.length ? () => store.patch({ excludedSteps: [] }) : undefined
        }
      />
      {excludeOpen && (
        <div style={{ padding: '0 20px 10px' }}>
          <StepFilterList
            steps={store.allSteps}
            selected={store.excludedSteps}
            disabledSteps={store.includedSteps}
            onToggle={(step) =>
              store.patch({
                excludedSteps: store.excludedSteps.includes(step)
                  ? store.excludedSteps.filter((s) => s !== step)
                  : [...store.excludedSteps, step],
              })
            }
          />
        </div>
      )}
      <Divider />

      <SubHeader
        title="Num Steps"
        open={stepsOpen}
        onToggle={() => setStepsOpen(!stepsOpen)}
        badge={
          stepsActive ? `${store.minStepsFilter}–${store.maxStepsFilter}` : undefined
        }
        onClear={
          stepsActive
            ? () =>
                store.patch({
                  minStepsFilter: store.stepCountMin,
                  maxStepsFilter: store.stepCountMax,
                })
            : undefined
        }
      />
      {stepsOpen && (
        <div style={{ padding: '10px 20px' }}>
          <RangeSlider
            min={store.stepCountMin}
            max={maxSteps}
            low={store.minStepsFilter}
            high={Math.min(store.maxStepsFilter, maxSteps)}
            disabled={disabled || store.stepCountMin === store.stepCountMax}
            onChange={(low, high) =>
              store.patch({ minStepsFilter: low, maxStepsFilter: high })
            }
          />
        </div>
      )}
      <Divider />

      <SubHeader
        title="Journey Time"
        open={timeOpen}
        onToggle={() => setTimeOpen(!timeOpen)}
        badge={
          timeActive
            ? `${formatSecs(store.minJourneyTimeFilter)}–${formatSecs(
                Math.min(store.maxJourneyTimeFilter, maxTime),
              )}`
            : undefined
        }
        onClear={
          timeActive
            ? () =>
                store.patch({
                  minJourneyTimeFilter: store.journeyTimeBoundsMin,
                  maxJourneyTimeFilter: store.journeyTimeBoundsMax,
                })
            : undefined
        }
      />
      {timeOpen && (
        <div style={{ padding: '10px 20px' }}>
          <RangeSlider
            min={store.journeyTimeBoundsMin}
            max={maxTime}
            low={store.minJourneyTimeFilter}
            high={Math.min(store.maxJourneyTimeFilter, maxTime)}
            format={formatSecs}
            disabled={
              disabled || store.journeyTimeBoundsMax <= store.journeyTimeBoundsMin
            }
            onChange={(low, high) =>
              store.patch({ minJourneyTimeFilter: low, maxJourneyTimeFilter: high })
            }
          />
        </div>
      )}
      <Divider />

      <SubHeader
        title="Journey Score"
        open={scoreOpen}
        onToggle={() => setScoreOpen(!scoreOpen)}
        badge={
          scoreActive ? `${store.minScoreFilter}–${store.maxScoreFilter}` : undefined
        }
        onClear={
          scoreActive
            ? () =>
                store.patch({
                  minScoreFilter: store.scoreBoundsMin,
                  maxScoreFilter: store.scoreBoundsMax,
                })
            : undefined
        }
      />
      {scoreOpen && (
        <div style={{ padding: '10px 20px' }}>
          <RangeSlider
            min={store.scoreBoundsMin}
            max={maxScore}
            low={Math.max(store.minScoreFilter, store.scoreBoundsMin)}
            high={Math.min(store.maxScoreFilter, maxScore)}
            disabled={disabled || store.scoreBoundsMax <= store.scoreBoundsMin}
            onChange={(low, high) =>
              store.patch({ minScoreFilter: low, maxScoreFilter: high })
            }
          />
        </div>
      )}

      {hasMeta && (
        <>
          <Divider />
          <SubHeader
            title="Meta"
            open={metaOpen}
            onToggle={() => setMetaOpen(!metaOpen)}
            badge={metaCount > 0 ? String(metaCount) : undefined}
            onClear={
              metaCount > 0
                ? () =>
                    store.patch({ meta1Filter: '', meta2Filter: '', meta3Filter: '' })
                : undefined
            }
          />
          {metaOpen && (
            <div className="col" style={{ padding: '0 20px 10px', gap: 6 }}>
              <MetaField
                title={store.meta1Title}
                value={store.meta1Filter}
                suggestions={store.meta1Values}
                onChange={(v) => store.patch({ meta1Filter: v })}
              />
              <MetaField
                title={store.meta2Title}
                value={store.meta2Filter}
                suggestions={store.meta2Values}
                onChange={(v) => store.patch({ meta2Filter: v })}
              />
              <MetaField
                title={store.meta3Title}
                value={store.meta3Filter}
                suggestions={store.meta3Values}
                onChange={(v) => store.patch({ meta3Filter: v })}
              />
            </div>
          )}
        </>
      )}

      <div className="row" style={{ padding: '10px 20px', gap: 8 }}>
        <button
          className="btn small"
          disabled={disabled}
          onClick={() => {
            store.resetFilters()
            apply()
          }}
        >
          ↺ Reset
        </button>
        <span className="spacer" />
        <button className="btn small" disabled={disabled} onClick={onSavePreset}>
          🔖 Save Preset…
        </button>
        <button className="btn prominent small" disabled={disabled} onClick={apply}>
          Apply
        </button>
      </div>

      <PresetList />
    </div>
  )
}

function MetaField({
  title,
  value,
  suggestions,
  onChange,
}: {
  title: string | null
  value: string
  suggestions: string[]
  onChange: (value: string) => void
}) {
  if (!title) return null
  return (
    <AutocompleteField
      label={title}
      value={value}
      suggestions={suggestions}
      onChange={onChange}
    />
  )
}

function PresetList() {
  const store = useStore()
  const [renaming, setRenaming] = useState<FilterGroup | null>(null)

  if (store.filterGroups.length === 0) return null

  // Presets are listed alphabetically (A→Z), matching the chart header's picker.
  const groups = [...store.filterGroups].sort((a, b) => a.name.localeCompare(b.name))

  return (
    <>
      <Divider />
      <div className="col" style={{ padding: '8px 20px 12px', gap: 4 }}>
        <span className="sub-title">Presets</span>
        {/* At most four presets are shown at once; the rest scroll — same as the
            Connections and Projects lists. Four rows of 32px plus 4px gaps. */}
        <div
          className="col"
          style={{ gap: 4, maxHeight: 4 * 32 + 3 * 4, overflowY: 'auto' }}
        >
          {groups.map((group) => (
            <div
              key={group.id}
              className={`card${store.selectedFilterGroupId === group.id ? ' selected' : ''}`}
              style={{ minHeight: 32, flexShrink: 0, padding: '5px 10px' }}
            >
            <button
              className="card-body"
              style={{ textAlign: 'left' }}
              onClick={() => {
                store.applyFilterGroup(group)
                void store.reloadGraph()
              }}
            >
              <span className="card-title t-caption">{group.name}</span>
            </button>
            <button
              className="icon-btn"
              style={{ width: 20, height: 20, fontSize: 11, color: 'var(--secondary)' }}
              title="Rename preset"
              onClick={() => setRenaming(group)}
            >
              ✎
            </button>
            <button
              className="icon-btn"
              style={{ width: 20, height: 20, fontSize: 11, color: 'var(--red)' }}
              title="Delete preset"
              onClick={() => store.deleteFilterGroup(group.id)}
            >
              🗑
            </button>
            </div>
          ))}
        </div>
      </div>
      {renaming && (
        <PromptSheet
          title="Rename Filter Preset"
          initialValue={renaming.name}
          confirmLabel="Rename"
          onCancel={() => setRenaming(null)}
          onConfirm={(name) => {
            store.renameFilterGroup(renaming.id, name)
            setRenaming(null)
          }}
        />
      )}
    </>
  )
}

function EventIdFilter() {
  const store = useStore()
  const [focused, setFocused] = useState(false)

  return (
    <div className="col" style={{ padding: '8px 20px 10px', gap: 10 }}>
      <span className="t-caption fg-secondary" style={{ fontWeight: 600 }}>
        Event ID
      </span>
      <div style={{ position: 'relative' }}>
        <div className="row" style={{ gap: 6 }}>
          <input
            className="text-input"
            value={store.eventIdFilter}
            placeholder="Enter EVENT_ID"
            autoCorrect="off"
            autoCapitalize="none"
            spellCheck={false}
            onChange={(e) => {
              store.patch({ eventIdFilter: e.target.value })
              void store.fetchEventIdSuggestions()
              setFocused(true)
            }}
            onFocus={() => setFocused(true)}
            onBlur={() => setTimeout(() => setFocused(false), 180)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                setFocused(false)
                void store.loadIndividualJourney()
              }
            }}
          />
          {store.eventIdFilter && (
            <button
              className="icon-btn"
              style={{ width: 22, height: 22, color: 'var(--secondary)' }}
              onClick={() => store.patch({ eventIdFilter: '', eventIdSuggestions: [] })}
              title="Clear"
            >
              ⊗
            </button>
          )}
        </div>
        {focused && store.eventIdSuggestions.length > 0 && (
          <div
            className="suggestions"
            style={{ position: 'absolute', top: '100%', left: 0, right: 0, zIndex: 10 }}
          >
            {store.eventIdSuggestions.map((id) => (
              <button
                key={id}
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => {
                  store.patch({ eventIdFilter: id, eventIdSuggestions: [] })
                  setFocused(false)
                  void store.loadIndividualJourney()
                }}
              >
                {id}
              </button>
            ))}
          </div>
        )}
      </div>
      <button
        className="btn prominent small"
        style={{ alignSelf: 'flex-end' }}
        disabled={!store.eventIdFilter.trim() || !store.selectedProject}
        onClick={() => void store.loadIndividualJourney()}
      >
        Load Journey
      </button>
    </div>
  )
}

// ── Configuration ────────────────────────────────────────────────────────────

function ConfigSection({ onEditPrompt }: { onEditPrompt: () => void }) {
  const store = useStore()
  // The LLM/report prompt is a power/developer/admin capability (same bar as connection
  // management); regular users don't see it at all.
  const canEditPrompt =
    store.authIsPower || store.authIsAdmin || store.authIsDeveloper
  const [showGrouping, setShowGrouping] = useSetting<boolean>('processmap.showGrouping')
  const [startMode, setStartMode] = useSetting<GraphStartMode>('graph.startMode')
  const [showDescriptions, setShowDescriptions] = useSetting<boolean>(
    'processmap.showNodeDescriptions',
  )
  const [optimised, setOptimised] = useSetting<boolean>('graph.optimisedLayout')
  const [colorize, setColorize] = useSetting<boolean>('graph.edge.colorizeByWeight')
  const [tableButton, setTableButton] = useSetting<boolean>(
    'graph.showTransitionTableButton',
  )
  const [defaultWindowDays, setDefaultWindowDays] = useSetting<number>(
    'graph.defaultWindowDays',
  )
  const [nodeScale, setNodeScale] = useSetting<number>('graph.node.scale')
  const [edgeScale, setEdgeScale] = useSetting<number>('graph.edge.scale')
  const [groupScale, setGroupScale] = useSetting<number>('graph.group.scale')
  const [highlightMs, setHighlightMs] = useSetting<number>('graph.highlightTriggerMs')
  const [groupsOpen, setGroupsOpen] = useSetting<boolean>('sidebar.configGroupsExpanded')
  const [kpisOpen, setKpisOpen] = useSetting<boolean>('sidebar.configKpisExpanded')
  const [stepsOpen, setStepsOpen] = useSetting<boolean>('sidebar.configStepsExpanded')
  const [layoutOpen, setLayoutOpen] = useSetting<boolean>('sidebar.configLayoutExpanded')
  const [datesOpen, setDatesOpen] = useSetting<boolean>('sidebar.configDatesExpanded')
  const [aiOpen, setAiOpen] = useSetting<boolean>('sidebar.configAiExpanded')
  const [aggOpen, setAggOpen] = useSetting<boolean>('sidebar.configAggregationsExpanded')
  const [showAggProjects, setShowAggProjects] = useSetting<boolean>('aggregates.showProjects')
  const [showAggConnections, setShowAggConnections] = useSetting<boolean>(
    'aggregates.showConnections',
  )
  const [kpiOrder, setKpiOrder] = useSetting<string>('kpi.order')
  const [dragging, setDragging] = useState<string | null>(null)

  const orderedIds = useMemo(() => {
    const stored = kpiOrder.split(',').filter(Boolean)
    const all = KPI_DEFAULT_ORDER.split(',')
    return [...stored, ...all.filter((id) => !stored.includes(id))]
  }, [kpiOrder])

  const reorder = (dragId: string, targetId: string) => {
    if (dragId === targetId) return
    const arr = orderedIds.filter((id) => id !== dragId)
    const index = arr.indexOf(targetId)
    arr.splice(index < 0 ? arr.length : index, 0, dragId)
    setKpiOrder(arr.join(','))
  }

  // Node presets (M = 2.25 default); edge presets run a further +50% again
  // (M = 3.375 default) so transition labels read larger.
  const NODE_FONT_OPTIONS = [
    { value: '1.95', label: 'S' },
    { value: '2.25', label: 'M' },
    { value: '2.7', label: 'L' },
    { value: '3.15', label: 'XL' },
  ]
  const EDGE_FONT_OPTIONS = [
    { value: '2.925', label: 'S' },
    { value: '3.375', label: 'M' },
    { value: '4.05', label: 'L' },
    { value: '4.725', label: 'XL' },
  ]
  // Dwell delay before a hovered node's neighbourhood is spotlit; "Off" disables it.
  const HIGHLIGHT_OPTIONS = [
    { value: '0', label: 'Off' },
    { value: '1000', label: '1s' },
    { value: '2000', label: '2s' },
    { value: '3000', label: '3s' },
  ]

  return (
    <div className="col config-section" style={{ gap: 0 }}>
      {/* Collapsible sections first */}
      <SubHeader
        icon="🗂"
        title="Step Groups"
        open={groupsOpen}
        onToggle={() => setGroupsOpen(!groupsOpen)}
      />
      {groupsOpen && (
        <div className="config-subbody">
          <ToggleRow
            icon="⬚"
            label="Show step groups"
            checked={showGrouping}
            onChange={setShowGrouping}
          />
          {showGrouping && (
            <div className="col" style={{ padding: '6px 20px', gap: 5 }}>
              <span className="t-caption fg-secondary">▦ Groups start</span>
              <Segmented
                options={[
                  { value: 'expanded', label: 'Expanded' },
                  { value: 'collapsed', label: 'Collapsed' },
                  { value: 'persisted', label: 'Persisted' },
                ]}
                value={startMode}
                onChange={setStartMode}
              />
            </div>
          )}
        </div>
      )}

      <SubHeader
        icon="📊"
        title="KPIs"
        open={kpisOpen}
        onToggle={() => setKpisOpen(!kpisOpen)}
      />
      {kpisOpen && (
        <div className="config-subbody">
          <div className="col" style={{ padding: '0 14px 8px', gap: 0 }}>
            {orderedIds.map((id) => (
              <KpiToggleRow
                key={id}
                id={id}
                dragging={dragging === id}
                onDragStart={() => setDragging(id)}
                onDragEnd={() => setDragging(null)}
                onDropOn={() => {
                  if (dragging) reorder(dragging, id)
                }}
              />
            ))}
          </div>
        </div>
      )}

      <SubHeader
        icon="⬭"
        title="Steps"
        open={stepsOpen}
        onToggle={() => setStepsOpen(!stepsOpen)}
      />
      {stepsOpen && (
        <div className="config-subbody">
          <ToggleRow
            icon="🗒"
            label="Show node notes"
            checked={showDescriptions}
            onChange={setShowDescriptions}
          />
          <div className="col" style={{ padding: '6px 20px 8px', gap: 5 }}>
            <span className="t-caption fg-secondary">✨ Highlight Trigger</span>
            <Segmented
              options={HIGHLIGHT_OPTIONS}
              value={String(highlightMs ?? 1000)}
              onChange={(v) => setHighlightMs(Number(v))}
            />
            <span className="t-caption2 fg-tertiary">
              Rest on a node this long to spotlight it and its connections. Not used in
              Individual Journey.
            </span>
          </div>
          <div style={{ padding: '0 20px 14px' }}>
            <StepEditor />
          </div>
        </div>
      )}

      <SubHeader
        icon="✨"
        title="Layout"
        open={layoutOpen}
        onToggle={() => setLayoutOpen(!layoutOpen)}
      />
      {layoutOpen && (
        <div className="config-subbody">
          <ToggleRow
            icon="✨"
            label="Optimise layout"
            checked={optimised}
            onChange={setOptimised}
          />
          <ToggleRow
            icon="🎨"
            label="Colorise edges by weight"
            checked={colorize}
            onChange={setColorize}
          />
          <ToggleRow
            icon="▦"
            label="Transition-table button"
            checked={tableButton}
            onChange={setTableButton}
          />
          <div className="col" style={{ padding: '6px 20px 8px', gap: 8 }}>
            <span className="t-caption fg-secondary" style={{ fontWeight: 600 }}>
              🔠 Flowchart font sizes
            </span>
            <div className="col" style={{ gap: 4 }}>
              <span className="t-caption2 fg-secondary">Nodes</span>
              <Segmented
                options={NODE_FONT_OPTIONS}
                value={String(nodeScale ?? 2.25)}
                onChange={(v) => setNodeScale(Number(v))}
              />
            </div>
            <div className="col" style={{ gap: 4 }}>
              <span className="t-caption2 fg-secondary">Edges</span>
              <Segmented
                options={EDGE_FONT_OPTIONS}
                value={String(edgeScale ?? 3.375)}
                onChange={(v) => setEdgeScale(Number(v))}
              />
            </div>
            <div className="col" style={{ gap: 4 }}>
              <span className="t-caption2 fg-secondary">Group titles</span>
              <Segmented
                options={NODE_FONT_OPTIONS}
                value={String(groupScale ?? 2.25)}
                onChange={(v) => setGroupScale(Number(v))}
              />
            </div>
          </div>
        </div>
      )}

      <SubHeader
        icon="🗓"
        title="Dates and Times"
        open={datesOpen}
        onToggle={() => setDatesOpen(!datesOpen)}
      />
      {datesOpen && (
        <div className="config-subbody">
        <div className="col" style={{ padding: '8px 20px', gap: 4 }}>
          <div className="row" style={{ gap: 10 }}>
            <span aria-hidden className="fg-secondary">
              🗓
            </span>
            <span className="t-caption fg-secondary spacer">Default date window</span>
            <input
              className="text-input"
              type="number"
              min={0}
              step={1}
              aria-label="Default date window (days)"
              value={defaultWindowDays ?? 0}
              onChange={(e) =>
                setDefaultWindowDays(Math.max(0, Math.floor(Number(e.target.value) || 0)))
              }
              style={{ width: 64 }}
            />
            <span className="t-caption fg-secondary">days</span>
          </div>
          <span className="t-caption2 fg-tertiary" style={{ paddingLeft: 30 }}>
            On load, show the last N days. 0 = full range. Applies next project load.
          </span>
        </div>
        </div>
      )}

      {/* The report analysis prompt is editable by power users, developers and admins only
          (regular users never see it). It is stored per (connection, project). */}
      {canEditPrompt && (
        <>
          <SubHeader
            icon="✨"
            title="AI related"
            open={aiOpen}
            onToggle={() => setAiOpen(!aiOpen)}
          />
          {aiOpen && (
            <div className="config-subbody">
              <div className="row" style={{ padding: '8px 20px', gap: 10 }}>
                <span aria-hidden className="fg-secondary">
                  💬
                </span>
                <span className="t-caption fg-secondary spacer">LLM Prompt</span>
                <button
                  className="btn small"
                  disabled={!store.selectedProject || !store.connection.activeProfileId}
                  onClick={onEditPrompt}
                >
                  Edit
                </button>
              </div>
            </div>
          )}
        </>
      )}

      <SubHeader
        icon="Σ"
        title="Aggregations"
        open={aggOpen}
        onToggle={() => setAggOpen(!aggOpen)}
      />
      {aggOpen && (
        <div className="config-subbody">
          <ToggleRow
            icon="📈"
            label="Show aggregate detail projects"
            checked={showAggProjects}
            onChange={setShowAggProjects}
          />
          <ToggleRow
            icon="⛁"
            label="Show aggregate detail connections"
            checked={showAggConnections}
            onChange={setShowAggConnections}
          />
          <span className="t-caption2 fg-tertiary" style={{ padding: '4px 20px 8px' }}>
            A Σ node&rsquo;s menu offers both drill-downs, always with the original numbers:
            “new panel” shows the member steps as a sub-process in a panel; “in place” expands
            the Σ node inside the map (surrounding steps stay) — collapse with Drill up.
          </span>
        </div>
      )}
    </div>
  )
}

function KpiToggleRow({
  id,
  dragging,
  onDragStart,
  onDragEnd,
  onDropOn,
}: {
  id: string
  dragging: boolean
  onDragStart: () => void
  onDragEnd: () => void
  onDropOn: () => void
}) {
  const meta = KPI_META[id]
  const [visible, setVisible] = useSetting<boolean>(`kpi.show.${id}`, true)
  if (!meta) return null

  return (
    <div
      draggable
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
      onDragOver={(e) => e.preventDefault()}
      onDrop={onDropOn}
      className="row"
      style={{ gap: 6, opacity: dragging ? 0.4 : 1, cursor: 'grab' }}
    >
      <span className="fg-tertiary" style={{ width: 14, fontSize: 11 }} aria-hidden>
        ≡
      </span>
      <div className="toggle-row" style={{ flex: 1, padding: '6px 0' }}>
        <span aria-hidden style={{ width: 16 }}>
          {meta.icon}
        </span>
        <span className="toggle-label">{meta.label}</span>
        <Switch checked={visible} onChange={setVisible} />
      </div>
    </div>
  )
}

// Edits the report analysis prompt stored for the CURRENT (connection, project) — the same
// mapping the admin Reporting tab manages. Power/developer/admin only.
function PromptEditorSheet({ onClose }: { onClose: () => void }) {
  const store = useStore()
  const projectId = store.selectedProject?.projectId ?? 0
  const connectionId = store.connection.activeProfileId ?? ''
  const [text, setText] = useState('')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    if (!projectId || !connectionId) {
      setLoading(false)
      return
    }
    api
      .reportPrompt(projectId, connectionId)
      .then((r) => !cancelled && setText(r.prompt || ''))
      .catch((e) => !cancelled && setError(e instanceof Error ? e.message : String(e)))
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
  }, [projectId, connectionId])

  const save = async () => {
    if (!connectionId || !projectId) return
    setBusy(true)
    setError(null)
    try {
      await api.setReportPrompt(projectId, connectionId, text.trim())
      onClose()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setBusy(false)
    }
  }

  return (
    <Sheet
      title="Report Analysis Prompt"
      onClose={onClose}
      footer={
        <>
          <button className="btn" onClick={() => setText(DEFAULT_LLM_PROMPT)}>
            Use Default
          </button>
          <span className="spacer" />
          <button className="btn" onClick={onClose}>
            Cancel
          </button>
          <button
            className="btn prominent"
            disabled={busy || loading || !connectionId}
            onClick={() => void save()}
          >
            Save
          </button>
        </>
      }
    >
      <div className="t-caption fg-secondary">
        This instruction is sent to the report LLM together with the current transition
        table. It is stored for the current <b>connection</b> and <b>project</b>, so each
        process can carry its own analysis style. Leave it empty to use the built-in default.
      </div>
      {error && (
        <div className="t-caption" style={{ color: 'var(--red)' }}>
          {error}
        </div>
      )}
      <textarea
        className="text-input"
        style={{ minHeight: 220 }}
        value={loading ? 'Loading…' : text}
        disabled={loading}
        onChange={(e) => setText(e.target.value)}
      />
    </Sheet>
  )
}
