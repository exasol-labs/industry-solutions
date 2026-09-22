/**
 * Application state — the port of AppViewModel.swift.
 *
 * Keeps the same shape as the Swift view model: one flat "active chart" filter
 * state that the sidebar binds to, plus saved snapshots per chart mode that are
 * swapped in and out when the user switches views.
 */

import { create } from 'zustand'
import { api, ApiError, type AuthUser } from './api'
import {
  projectKeys,
  readJSON,
  readSetting,
  writeJSON,
  writeSetting,
} from './settings'
import {
  EMPTY_GRAPH,
  DETAIL_VIEW_MODES,
  INT_MAX,
  INT_MIN,
  type ABDataSource,
  type AssignedConnection,
  type ConnectionStatus,
  type DetailViewMode,
  type DocumentationResponse,
  type DurationStats,
  type FilterGroup,
  type FilterSnapshot,
  type FilterSpec,
  type HappyPath,
  type ConnectionProjectDeleteResult,
  type ConnectionProjectsResult,
  type JourneyEvent,
  type JourneyPath,
  type LegacyHappyPath,
  type ManagedConnection,
  type ProcessGraph,
  type ProcessNote,
  type Project,
  type SampleSet,
  type SamplingMethod,
  type SimSlot,
  type SimulationResult,
  type StatisticsResponse,
  type StepInfo,
  type TransitionMetric,
  type TransitionsMode,
} from './types'
import { addDays, fromISODate, toISODate } from './graph/format'
import { migrateHappyPath } from './graph/happyPath'
import { sankeySvg as sankeySvgString } from './flow/sankeySvg'
import { authenticateWithPasskey } from './passkey'
import type { SavedAction } from './actions/types'
import type { AggregateLink } from './aggregate/types'
import { collapseExcept, subgraphWithNeighbours, type AggMembers } from './aggregate/explode'

export type ABSide = 'a' | 'b'

export interface AppAlert {
  id: number
  title: string
  message: string
  primaryLabel: string
  onPrimary?: () => void
  secondaryLabel?: string
}

let alertSeq = 0

/** List-based META value include/exclude (from the node "Meta Infos" panel). Index 0 =
 *  Meta_1, exactly mirroring includedSteps/excludedSteps but per META column. */
export interface MetaListFilters {
  included: [string[], string[], string[]]
  excluded: [string[], string[], string[]]
}
export const emptyMetaFilters = (): MetaListFilters => ({
  included: [[], [], []],
  excluded: [[], [], []],
})
/** Defensive read: an older persisted snapshot (localStorage) has no metaFilters. */
export const metaFiltersOf = (mf: MetaListFilters | undefined): MetaListFilters =>
  mf ?? emptyMetaFilters()
/** Expand the structured metaFilters into the flat FilterSpec fields the API expects. */
export const metaFilterFields = (mf: MetaListFilters) => ({
  includedMeta1: mf.included[0], excludedMeta1: mf.excluded[0],
  includedMeta2: mf.included[1], excludedMeta2: mf.excluded[1],
  includedMeta3: mf.included[2], excludedMeta3: mf.excluded[2],
})
/** Rebuild the structured metaFilters from the flat fields (e.g. a saved preset). */
export const metaFiltersFromFields = (g: {
  includedMeta1?: string[]; excludedMeta1?: string[]
  includedMeta2?: string[]; excludedMeta2?: string[]
  includedMeta3?: string[]; excludedMeta3?: string[]
}): MetaListFilters => ({
  included: [g.includedMeta1 ?? [], g.includedMeta2 ?? [], g.includedMeta3 ?? []],
  excluded: [g.excludedMeta1 ?? [], g.excludedMeta2 ?? [], g.excludedMeta3 ?? []],
})

/** Mirror of Swift's `ChartFilterState`. */
export interface ChartFilterState {
  fromDate: string
  toDate: string
  includedSteps: string[]
  excludedSteps: string[]
  metaFilters: MetaListFilters
  meta1Filter: string
  meta2Filter: string
  meta3Filter: string
  eventIdFilter: string
  journeyDate: string | null
  journeyEndDate: string | null
  processGraph: ProcessGraph
  journeyCount: number | null
  transitionMetric: TransitionMetric
  durations: DurationStats
  minStepsFilter: number
  maxStepsFilter: number
  minJourneyTimeFilter: number
  maxJourneyTimeFilter: number
  minScoreFilter: number
  maxScoreFilter: number
  processGoodness: number | null
}

const EMPTY_DURATIONS: DurationStats = {
  minSecs: null,
  avgSecs: null,
  medianSecs: null,
  stdDevSecs: null,
  maxSecs: null,
}

function defaultChartState(
  from: string,
  to: string,
  bounds: Partial<ChartFilterState> = {},
): ChartFilterState {
  return {
    fromDate: from,
    toDate: to,
    includedSteps: [],
    excludedSteps: [],
    metaFilters: emptyMetaFilters(),
    meta1Filter: '',
    meta2Filter: '',
    meta3Filter: '',
    eventIdFilter: '',
    journeyDate: null,
    journeyEndDate: null,
    processGraph: EMPTY_GRAPH,
    journeyCount: null,
    transitionMetric: 'Journey %',
    durations: EMPTY_DURATIONS,
    minStepsFilter: 0,
    maxStepsFilter: INT_MAX,
    minJourneyTimeFilter: 0,
    maxJourneyTimeFilter: INT_MAX,
    minScoreFilter: INT_MIN,
    maxScoreFilter: INT_MAX,
    processGoodness: null,
    ...bounds,
  }
}

export interface AppState {
  // ── authentication (main-app sign-in) ─────────────────────────────────────
  authChecked: boolean
  authUser: string | null
  authDisplayName: string | null
  authIsAdmin: boolean
  authIsPower: boolean
  authIsDeveloper: boolean
  authPasskeyAllowed: boolean
  authMfaAllowed: boolean
  authMfaEnabled: boolean
  /** Username awaiting a TOTP code after a correct password (two-step sign-in). */
  mfaPending: string | null
  /** Username who must ENROL 2FA before signing in (it's required but not set up). */
  mfaSetupPending: string | null
  requireLogin: boolean
  idleTimeoutMins: number
  /** Whether the admin has enabled the Actions feature (gates the node-menu submenu). */
  actionsEnabled: boolean
  /** Saved actions for the open (connection, project), enabled-only — listed in node menus. */
  projectActions: SavedAction[]
  /** Aggregate links for the open project — a Σ step drills down into its detail project. */
  projectAggregates: AggregateLink[]
  /** When the current project was reached by drilling into a Σ step, the high-level map to
   *  return to (a "Return" button). Null when not viewing a drilled-into detail project. */
  drillReturn: { projectId: number; title: string } | null
  /** In-place drill-down: one or more Σ nodes expanded within the high-level map, using the
   *  ORIGINAL source graph so the revealed steps carry real, un-aggregated numbers. Null
   *  unless a drill is active; drill up clears it. */
  inPlaceDrill: {
    sigmaStep: string // the most recently expanded Σ (for labelling)
    expanded: string[] // every Σ currently expanded
    graph: ProcessGraph // the on-screen graph (source, collapsed except `expanded`)
    journeyCount: number | null
    source: { graph: ProcessGraph; journeyCount: number | null; aggregates: AggMembers[] }
  } | null
  /** "New panel" drill-down: the member sub-process shown in a modal, with real source
   *  numbers. Null unless the panel is open. */
  panelDrill: { sigmaStep: string; graph: ProcessGraph; journeyCount: number | null } | null
  /** Set when the last sign-out was due to inactivity, so the login screen can say so. */
  signedOutForInactivity: boolean

  // ── connection ──────────────────────────────────────────────────────────
  connections: AssignedConnection[]
  // Power users: connections they own & may edit, and the users they can assign.
  manageableConnections: ManagedConnection[]
  assignableUsers: string[]
  connection: ConnectionStatus

  // ── projects ────────────────────────────────────────────────────────────
  projects: Project[]
  selectedProject: Project | null
  isLoading: boolean
  // Bumped on every connect/disconnect. In-flight per-connection work (e.g. a
  // graph load) captures it and discards its result if it changed meanwhile — so a
  // request whose DB session was torn down by a concurrent connection switch is
  // superseded silently instead of surfacing a spurious "Not connected" error.
  connectionGen: number
  errorMessage: string | null
  pendingAlert: AppAlert | null

  allSteps: string[]
  allStepInfos: Record<string, StepInfo>
  meta1Title: string | null
  meta2Title: string | null
  meta3Title: string | null
  meta1Values: string[]
  meta2Values: string[]
  meta3Values: string[]
  totalJourneyCount: number | null
  initialFromDate: string
  initialToDate: string
  projectMinDate: string

  // ── active chart ────────────────────────────────────────────────────────
  activeChartMode: DetailViewMode
  savedChartStates: Partial<Record<DetailViewMode, ChartFilterState>>

  processGraph: ProcessGraph
  fromDate: string
  toDate: string
  includedSteps: string[]
  excludedSteps: string[]
  metaFilters: MetaListFilters
  meta1Filter: string
  meta2Filter: string
  meta3Filter: string
  /** Whether the node "Meta Infos" panel is open, and the node it was opened for. */
  metaInfoOpen: boolean
  metaInfoNode: string | null
  eventIdFilter: string
  eventIdSuggestions: string[]
  lastQueriedEventId: string
  journeyDate: string | null
  journeyEndDate: string | null
  journeyMeta1: string | null
  journeyMeta2: string | null
  journeyMeta3: string | null
  journeyCount: number | null
  // The loaded journey's raw ordered trace, for the sequential swimlane view.
  journeySequence: JourneyEvent[]
  // Individual-Journey canvas toggle: false = flowchart (default), true = swimlane.
  journeySwimlane: boolean
  durations: DurationStats
  transitionMetric: TransitionMetric
  processGoodnessScore: number | null
  /** How the active connection's transitions were computed on the last load. */
  transitionsMode: TransitionsMode | null
  /** Server-side query time (ms) of the last graph reload. */
  queryMs: number | null

  stepCountMin: number
  stepCountMax: number
  minStepsFilter: number
  maxStepsFilter: number
  journeyTimeBoundsMin: number
  journeyTimeBoundsMax: number
  minJourneyTimeFilter: number
  maxJourneyTimeFilter: number
  scoreBoundsMin: number
  scoreBoundsMax: number
  minScoreFilter: number
  maxScoreFilter: number

  // ── A/B comparison ──────────────────────────────────────────────────────
  abActiveSide: ABSide
  isLoadingA: boolean
  isLoadingB: boolean
  abGraphA: ProcessGraph
  abGraphB: ProcessGraph
  abJourneyCountA: number | null
  abJourneyCountB: number | null
  abDurationsA: DurationStats
  abDurationsB: DurationStats
  abMetricA: TransitionMetric
  abMetricB: TransitionMetric
  abGoodnessA: number | null
  abGoodnessB: number | null
  abVariantsA: JourneyPath[]
  abVariantsB: JourneyPath[]
  abSimilarityScore: number | null
  abDataSourceA: ABDataSource
  abDataSourceB: ABDataSource
  abFilterGroupIdA: string | null
  abFilterGroupIdB: string | null

  // ── statistics ──────────────────────────────────────────────────────────
  statistics: StatisticsResponse | null
  isLoadingStats: boolean
  statsErrorMessage: string | null
  statsRouteLimit: number
  statsLoadedSnapshot: FilterSnapshot | null

  // ── presets, happy paths, norms, notes ──────────────────────────────────
  filterGroups: FilterGroup[]
  selectedFilterGroupId: string | null
  happyPaths: HappyPath[]
  selectedHappyPathId: string | null
  happyPathScores: Record<string, number | null>
  targetNorms: Record<string, Record<string, number>>
  targetMetric: TransitionMetric
  projectNotes: ProcessNote[]

  // ── sampling ────────────────────────────────────────────────────────────
  sampleCounts: Record<string, number>
  sampleMethods: Record<string, SamplingMethod>
  isSampling: boolean
  samplingError: string | null
  samplingProgress: string | null

  // ── simulation ──────────────────────────────────────────────────────────
  simResultA: SimulationResult | null
  simResultB: SimulationResult | null
  isSimulating: boolean
  simulationError: string | null

  // ── AI documentation ────────────────────────────────────────────────────
  isLLMAnalyzing: boolean
  llmAnalysis: DocumentationResponse | null
  llmAnalysisError: string | null
  llmPromptTemplate: string
}

export interface AppActions {
  showAlert: (alert: Omit<AppAlert, 'id'>) => void
  dismissAlert: () => void

  checkSession: () => Promise<void>
  /** Returns an error message, or null. On null, check `mfaPending`: if set, a
   *  second factor is required; otherwise the user is signed in. */
  login: (username: string, password: string) => Promise<string | null>
  /** Step 2 of a two-factor sign-in — submit the TOTP or recovery code. */
  verifyMfa: (code: string) => Promise<string | null>
  /** Begin mandatory 2FA enrolment at sign-in — returns the secret + QR. */
  enrollMfaBegin: () => Promise<{ secret: string; otpauthUri: string; qrSvg: string }>
  /** Confirm enrolment with a code — signs the user in; returns recovery codes. */
  enrollMfaFinish: (code: string) => Promise<string[]>
  /** Dismiss the recovery-codes step and enter the app after enrolment. */
  finishMfaSetup: () => void
  cancelMfa: () => void
  loginWithPasskey: (username: string) => Promise<string | null>
  logout: (opts?: { inactivity?: boolean }) => Promise<void>

  refreshConnections: () => Promise<void>
  connectConnection: (connection: AssignedConnection) => Promise<boolean>
  disconnect: () => Promise<void>
  clearSession: () => void

  // Power-user connection management (create / edit / assign, from the app).
  refreshManageable: () => Promise<void>
  saveManagedConnection: (
    body: Record<string, unknown>,
  ) => Promise<{ ok: boolean; error: string | null }>
  deleteManagedConnection: (id: string) => Promise<boolean>
  testManagedConnection: (
    body: Record<string, unknown>,
  ) => Promise<{ dbError: string | null; llmError: string | null; llmModels: string[] }>
  provisionSchema: (
    body: Record<string, unknown>,
  ) => Promise<{ ok: boolean; error: string | null; created: string[] }>
  generateDemo: (
    body: Record<string, unknown>,
  ) => Promise<{
    ok: boolean
    error: string | null
    journeys: number
    project?: string
    message?: string
  }>
  listConnectionProjects: (id: string) => Promise<ConnectionProjectsResult>
  deleteConnectionProject: (
    id: string,
    projectId: number,
  ) => Promise<ConnectionProjectDeleteResult>


  loadProjects: () => Promise<void>
  selectProject: (project: Project) => Promise<void>
  /** After login/boot, reconnect to the last connection, reopen the last project and
   *  restore the last view — the per-user "resume where you left off" replay. */
  restoreLastSession: () => Promise<void>

  patch: (values: Partial<AppState>) => void
  setTransitionMetric: (metric: TransitionMetric) => void
  switchChartMode: (mode: DetailViewMode) => void
  switchABSide: (side: ABSide) => void
  setABMetric: (metric: TransitionMetric, side: ABSide) => void

  currentFilterSpec: () => FilterSpec
  currentFilterSnapshot: () => FilterSnapshot
  resetFilters: () => void
  loadProjectActions: () => Promise<void>
  loadProjectAggregates: () => Promise<void>
  /** Drill from a Σ step, dispatching to in-place or extra-panel per the current setting. */
  drillDown: (link: AggregateLink) => Promise<void>
  /** Drill from a Σ step into its detail project, remembering the high-level map to return to. */
  drillDownTo: (link: AggregateLink) => Promise<void>
  /** Go back to the high-level map remembered by the last drill-down. */
  returnFromDrill: () => Promise<void>
  /** Drill into a Σ step's detail IN-PLACE — load its graph into the current canvas. */
  drillDownInPlace: (link: AggregateLink) => Promise<void>
  /** Clear an in-place drill, restoring the high-level map in the canvas. */
  drillUp: () => void
  /** "New panel" drill-down: open the member sub-process (real source numbers) in a modal. */
  drillDownPanel: (link: AggregateLink) => Promise<void>
  closeDrillPanel: () => void
  /** Re-fetch an active in-place / panel drill under the current filter (called after the
   *  high-level map reloads, so the drilled numbers track the date window). */
  refreshDrill: () => Promise<void>
  reloadGraph: () => Promise<void>
  reloadGraphForDay: (day: string) => Promise<string | null>
  reloadABSide: (side: ABSide, from: string, to: string) => Promise<void>
  reloadABSideForDay: (side: ABSide, day: string) => Promise<string | null>
  refreshABSimilarity: () => Promise<void>

  loadStatistics: () => Promise<void>

  fetchEventIdSuggestions: () => Promise<void>
  loadIndividualJourney: () => Promise<void>
  setJourneySwimlane: (on: boolean) => void

  handleNodeAction: (node: string, action: 'include' | 'exclude') => void
  // Include/exclude a META value (col 0..2 = Meta_1..3) from the node "Meta Infos" panel.
  handleMetaAction: (col: number, value: string, action: 'include' | 'exclude') => void
  clearMetaFilters: () => void
  // The node "Meta Infos" panel — opened for a specific node, whose valid META values it
  // lists; the include/exclude filters it sets are still journey-level.
  openMetaInfo: (node: string) => void
  closeMetaInfo: () => void
  updateStep: (
    step: string,
    payload: {
      bgColor: string
      fgColor: string
      score: number | null
      shape: string
      belongsTo: string | null
      description: string | null
    },
  ) => Promise<void>

  // presets
  createFilterGroup: (name: string) => void
  deleteFilterGroup: (id: string) => void
  renameFilterGroup: (id: string, name: string) => void
  applyFilterGroup: (group: FilterGroup) => void

  // happy paths
  createHappyPath: (name: string) => void
  deleteHappyPath: (id: string) => void
  renameHappyPath: (id: string, name: string) => void
  updateHappyPath: (id: string, mutate: (path: HappyPath) => HappyPath) => void
  selectHappyPath: (id: string) => void
  refreshHappyPathConformance: () => Promise<void>

  // norms
  saveNorm: (edge: string, value: number | null) => void
  setTargetMetric: (metric: TransitionMetric) => void

  // notes
  loadNotes: () => Promise<void>
  saveNote: (note: ProcessNote) => Promise<void>
  updateNote: (
    noteId: string,
    body: {
      title?: string
      comment?: string
      resolved?: boolean
      importance?: string
      isShared?: boolean
    },
  ) => Promise<void>
  deleteNote: (note: ProcessNote) => Promise<void>

  // sampling
  refreshSampleCounts: () => Promise<void>
  createSample: (
    sampleSet: SampleSet,
    count: number,
    method: SamplingMethod,
  ) => Promise<void>
  deleteSample: (sampleSet: SampleSet) => Promise<void>
  switchSampleSet: (side: ABSide, set: SampleSet) => Promise<void>
  setABDataSource: (side: ABSide, source: ABDataSource) => Promise<void>

  // simulation
  runSimulation: (
    slot: SimSlot,
    config: {
      journeyCount: number
      startDate: string
      avgInterArrivalHours: number
      excludedSteps: string[]
      requiredSteps: string[]
      maxStepsPerJourney: number
    },
  ) => Promise<void>

  // AI documentation
  setLLMPromptTemplate: (template: string) => void
  runLLMAnalysis: () => Promise<void>
}

export type Store = AppState & AppActions

const today = toISODate(new Date())

/** Map a signed-in user payload (password / passkey / MFA) to the store's auth
 *  fields — the one place that shape is unpacked. */
function hydrateAuth(u: AuthUser) {
  return {
    authUser: u.username,
    authDisplayName: u.displayName || null,
    authIsAdmin: u.isAdmin,
    authIsPower: u.isPower,
    authIsDeveloper: u.isDeveloper,
    authPasskeyAllowed: u.passkeyAllowed,
    authMfaAllowed: u.mfaAllowed,
    authMfaEnabled: u.mfaEnabled,
  }
}

const INITIAL_STATE: AppState = {
  authChecked: false,
  authUser: null,
  authDisplayName: null,
  authIsAdmin: false,
  authIsPower: false,
  authIsDeveloper: false,
  authPasskeyAllowed: false,
  authMfaAllowed: false,
  authMfaEnabled: false,
  mfaPending: null,
  mfaSetupPending: null,
  requireLogin: true,
  idleTimeoutMins: 0,
  actionsEnabled: false,
  projectActions: [],
  projectAggregates: [],
  drillReturn: null,
  inPlaceDrill: null,
  panelDrill: null,
  signedOutForInactivity: false,

  connections: [],
  manageableConnections: [],
  assignableUsers: [],
  connection: {
    isConnected: false,
    isLLMReachable: false,
    activeProfileId: null,
    username: '',
    lastError: null,
  },

  projects: [],
  selectedProject: null,
  isLoading: false,
  connectionGen: 0,
  errorMessage: null,
  pendingAlert: null,

  allSteps: [],
  allStepInfos: {},
  meta1Title: null,
  meta2Title: null,
  meta3Title: null,
  meta1Values: [],
  meta2Values: [],
  meta3Values: [],
  totalJourneyCount: null,
  initialFromDate: today,
  initialToDate: today,
  projectMinDate: today,

  activeChartMode: 'A-Chart',
  savedChartStates: {},

  processGraph: EMPTY_GRAPH,
  fromDate: today,
  toDate: today,
  includedSteps: [],
  excludedSteps: [],
  metaFilters: emptyMetaFilters(),
  metaInfoOpen: false,
  metaInfoNode: null,
  meta1Filter: '',
  meta2Filter: '',
  meta3Filter: '',
  eventIdFilter: '',
  eventIdSuggestions: [],
  lastQueriedEventId: '',
  journeyDate: null,
  journeyEndDate: null,
  journeyMeta1: null,
  journeyMeta2: null,
  journeyMeta3: null,
  journeyCount: null,
  journeySequence: [],
  journeySwimlane: false,
  durations: EMPTY_DURATIONS,
  transitionMetric: 'Journey %',
  processGoodnessScore: null,
  transitionsMode: null,
  queryMs: null,

  stepCountMin: 1,
  stepCountMax: 100,
  minStepsFilter: 0,
  maxStepsFilter: INT_MAX,
  journeyTimeBoundsMin: 0,
  journeyTimeBoundsMax: 0,
  minJourneyTimeFilter: 0,
  maxJourneyTimeFilter: INT_MAX,
  scoreBoundsMin: 0,
  scoreBoundsMax: 0,
  minScoreFilter: INT_MIN,
  maxScoreFilter: INT_MAX,

  abActiveSide: 'a',
  isLoadingA: false,
  isLoadingB: false,
  abGraphA: EMPTY_GRAPH,
  abGraphB: EMPTY_GRAPH,
  abJourneyCountA: null,
  abJourneyCountB: null,
  abDurationsA: EMPTY_DURATIONS,
  abDurationsB: EMPTY_DURATIONS,
  abMetricA: 'Count',
  abMetricB: 'Count',
  abGoodnessA: null,
  abGoodnessB: null,
  abVariantsA: [],
  abVariantsB: [],
  abSimilarityScore: null,
  abDataSourceA: { kind: 'sampleSet', sampleSet: 'ORIGINAL' },
  abDataSourceB: { kind: 'sampleSet', sampleSet: 'ORIGINAL' },
  abFilterGroupIdA: null,
  abFilterGroupIdB: null,

  statistics: null,
  isLoadingStats: false,
  statsErrorMessage: null,
  statsRouteLimit: 500,
  statsLoadedSnapshot: null,

  filterGroups: [],
  selectedFilterGroupId: null,
  happyPaths: [],
  selectedHappyPathId: null,
  happyPathScores: {},
  targetNorms: {},
  targetMetric: 'Count',
  projectNotes: [],

  sampleCounts: {},
  sampleMethods: {},
  isSampling: false,
  samplingError: null,
  samplingProgress: null,

  simResultA: null,
  simResultB: null,
  isSimulating: false,
  simulationError: null,

  isLLMAnalyzing: false,
  llmAnalysis: null,
  llmAnalysisError: null,
  llmPromptTemplate:
    'Analyze the transitions table and identify outliers, min, max, avg values for transitions. Use project name as a title, make a decent layout.',
}

export const DEFAULT_LLM_PROMPT = INITIAL_STATE.llmPromptTemplate

/** Active sample set for a side, read from settings (persisted like @AppStorage). */
export function activeSampleSet(side: ABSide): SampleSet {
  return readSetting<SampleSet>(
    side === 'a' ? 'sampling.activeSampleSetA' : 'sampling.activeSampleSetB',
  )
}

function uuid(): string {
  return crypto.randomUUID().toUpperCase()
}

export const useStore = create<Store>((set, get) => {
  /** Filter payload for one chart's saved state (or the live one). */
  const specFrom = (
    state: {
      fromDate: string
      toDate: string
      includedSteps: string[]
      excludedSteps: string[]
      metaFilters?: MetaListFilters
      meta1Filter: string
      meta2Filter: string
      meta3Filter: string
      minStepsFilter: number
      maxStepsFilter: number
      minJourneyTimeFilter: number
      maxJourneyTimeFilter: number
      minScoreFilter: number
      maxScoreFilter: number
    },
    sampleSet: SampleSet,
  ): FilterSpec => ({
    fromDate: state.fromDate,
    toDate: state.toDate,
    includedSteps: state.includedSteps,
    excludedSteps: state.excludedSteps,
    ...metaFilterFields(metaFiltersOf(state.metaFilters)),
    meta1: state.meta1Filter,
    meta2: state.meta2Filter,
    meta3: state.meta3Filter,
    minSteps: state.minStepsFilter,
    maxSteps: state.maxStepsFilter,
    minJourneyTime: state.minJourneyTimeFilter,
    maxJourneyTime: state.maxJourneyTimeFilter,
    minScore: state.minScoreFilter,
    maxScore: state.maxScoreFilter,
    sampleSet,
  })

  const captureCurrentState = (): ChartFilterState => {
    const s = get()
    return {
      fromDate: s.fromDate,
      toDate: s.toDate,
      includedSteps: s.includedSteps,
      excludedSteps: s.excludedSteps,
      metaFilters: s.metaFilters,
      meta1Filter: s.meta1Filter,
      meta2Filter: s.meta2Filter,
      meta3Filter: s.meta3Filter,
      eventIdFilter: s.eventIdFilter,
      journeyDate: s.journeyDate,
      journeyEndDate: s.journeyEndDate,
      processGraph: s.processGraph,
      journeyCount: s.journeyCount,
      transitionMetric: s.transitionMetric,
      durations: s.durations,
      minStepsFilter: s.minStepsFilter,
      maxStepsFilter: s.maxStepsFilter,
      minJourneyTimeFilter: s.minJourneyTimeFilter,
      maxJourneyTimeFilter: s.maxJourneyTimeFilter,
      minScoreFilter: s.minScoreFilter,
      maxScoreFilter: s.maxScoreFilter,
      processGoodness: s.processGoodnessScore,
    }
  }

  const applyChartState = (state: ChartFilterState) => {
    set({
      fromDate: state.fromDate,
      toDate: state.toDate,
      includedSteps: state.includedSteps,
      excludedSteps: state.excludedSteps,
      metaFilters: metaFiltersOf(state.metaFilters),
      meta1Filter: state.meta1Filter,
      meta2Filter: state.meta2Filter,
      meta3Filter: state.meta3Filter,
      eventIdFilter: state.eventIdFilter,
      journeyDate: state.journeyDate,
      journeyEndDate: state.journeyEndDate,
      processGraph: state.processGraph,
      journeyCount: state.journeyCount,
      transitionMetric: state.transitionMetric,
      durations: state.durations,
      minStepsFilter: state.minStepsFilter,
      maxStepsFilter: state.maxStepsFilter,
      minJourneyTimeFilter: state.minJourneyTimeFilter,
      maxJourneyTimeFilter: state.maxJourneyTimeFilter,
      minScoreFilter: state.minScoreFilter,
      maxScoreFilter: state.maxScoreFilter,
      processGoodnessScore: state.processGoodness,
    })
  }

  const saveHappyPaths = () => {
    const { selectedProject, happyPaths } = get()
    if (!selectedProject) return
    writeJSON(projectKeys.happyPaths(selectedProject.projectId), happyPaths)
  }

  const saveFilterGroups = () => {
    const { selectedProject, filterGroups } = get()
    if (!selectedProject) return
    writeJSON(projectKeys.filterGroups(selectedProject.projectId), filterGroups)
  }

  const datesForABSide = (side: ABSide): [string, string] => {
    const s = get()
    const isActive = s.abActiveSide === side
    if (isActive) return [s.fromDate, s.toDate]
    const saved = s.savedChartStates[side === 'a' ? 'A-Chart' : 'B-Chart']
    return [saved?.fromDate ?? s.fromDate, saved?.toDate ?? s.toDate]
  }

  // Which A/B side the single-chart view currently shows: the A-Chart / B-Chart
  // standalone modes map to a/b directly; A/B Comparison follows the active side.
  const singleViewSide = (): ABSide | null => {
    const s = get()
    if (s.activeChartMode === 'A-Chart') return 'a'
    if (s.activeChartMode === 'B-Chart') return 'b'
    if (s.activeChartMode === 'A/B Comparison') return s.abActiveSide
    return null
  }

  const applySimulationToABSide = (side: ABSide) => {
    const s = get()
    const source = side === 'a' ? s.abDataSourceA : s.abDataSourceB
    if (source.kind !== 'simulation') return
    const result = source.slot === 'Sim-A' ? s.simResultA : s.simResultB
    if (!result) return

    const durations: DurationStats = {
      minSecs: result.minCycleTimeSecs,
      avgSecs: result.avgCycleTimeSecs,
      medianSecs: null, // a synthetic simulation has no median cycle time
      stdDevSecs: result.stdDevCycleTimeSecs,
      maxSecs: result.maxCycleTimeSecs,
    }
    if (side === 'a') {
      set({
        abGraphA: result.simProcessGraph,
        abJourneyCountA: result.totalJourneys,
        abDurationsA: durations,
        abGoodnessA: null,
        abVariantsA: [],
      })
      if (singleViewSide() === 'a') {
        set({
          processGraph: result.simProcessGraph,
          journeyCount: result.totalJourneys,
          processGoodnessScore: null,
        })
      }
    } else {
      set({
        abGraphB: result.simProcessGraph,
        abJourneyCountB: result.totalJourneys,
        abDurationsB: durations,
        abGoodnessB: null,
        abVariantsB: [],
      })
      if (singleViewSide() === 'b') {
        set({
          processGraph: result.simProcessGraph,
          journeyCount: result.totalJourneys,
          processGoodnessScore: null,
        })
      }
    }
    void get().refreshABSimilarity()
  }

  // Re-apply the in-memory simulation graph to any A/B side pointing at a
  // simulation. Callers that rebuild abGraphA/B from saved (observed) chart state
  // MUST run this afterward, or a sim-sourced side silently reverts to the observed
  // graph while its 'simulation' data source (and read-only notice) stay in place.
  const reapplySimSources = () => {
    const st = get()
    if (st.abDataSourceA.kind === 'simulation') applySimulationToABSide('a')
    if (st.abDataSourceB.kind === 'simulation') applySimulationToABSide('b')
  }

  return {
    ...INITIAL_STATE,

    patch: (values) => set(values as Partial<Store>),

    showAlert: (alert) => set({ pendingAlert: { ...alert, id: ++alertSeq } }),
    dismissAlert: () => set({ pendingAlert: null }),

    // ── connection ────────────────────────────────────────────────────────

    refreshConnections: async () => {
      const [connections, connection] = await Promise.all([
        api.listConnections(),
        api.connectionStatus(),
      ])
      set({ connections, connection })
    },

    connectConnection: async (conn) => {
      // Bump immediately: switching connections tears down the shared DB session
      // server-side, so any graph load already in flight must be superseded.
      set((st) => ({ isLoading: true, connectionGen: st.connectionGen + 1 }))
      try {
        const connection = await api.connectConnection(conn.id)
        set({ connection })
        if (connection.lastError) {
          get().showAlert({
            title: 'Connection Failed',
            message: connection.lastError,
            primaryLabel: 'Retry',
            onPrimary: () => void get().connectConnection(conn),
            secondaryLabel: 'Cancel',
          })
          return false
        }
        // Remember this connection so a later login can auto-reconnect to it.
        writeSetting('session.lastConnectionId', conn.id)
        await get().loadProjects()
        return true
      } catch (error) {
        const message = error instanceof ApiError ? error.message : String(error)
        set({ errorMessage: message })
        get().showAlert({
          title: 'Connection Failed',
          message,
          primaryLabel: 'OK',
        })
        return false
      } finally {
        set({ isLoading: false })
      }
    },

    disconnect: async () => {
      const connection = await api.disconnect()
      get().clearSession()
      set({ connection })
      // An explicit disconnect is a deliberate exit — forget the resume target so the
      // next login doesn't silently reconnect. (An inactivity logout does NOT come
      // through here, so its snapshot is preserved for the resume.)
      writeSetting('session.lastConnectionId', '')
      writeSetting('session.lastProjectId', '')
    },

    clearSession: () => {
      const s = get()
      set({
        ...INITIAL_STATE,
        // Supersede any in-flight per-connection work (INITIAL_STATE would reset this to 0).
        connectionGen: s.connectionGen + 1,
        // Disconnecting the database must not sign the user out of the app.
        authChecked: s.authChecked,
        authUser: s.authUser,
        authDisplayName: s.authDisplayName,
        authIsAdmin: s.authIsAdmin,
        authIsPower: s.authIsPower,
        authIsDeveloper: s.authIsDeveloper,
        requireLogin: s.requireLogin,
        idleTimeoutMins: s.idleTimeoutMins,
        actionsEnabled: s.actionsEnabled,
        connections: s.connections,
        manageableConnections: s.manageableConnections,
        assignableUsers: s.assignableUsers,
        connection: {
          ...s.connection,
          isConnected: false,
          isLLMReachable: false,
        },
      })
    },

    // ── power-user connection management ──────────────────────────────────

    refreshManageable: async () => {
      if (!(get().authIsPower || get().authIsAdmin || get().authIsDeveloper)) {
        set({ manageableConnections: [], assignableUsers: [] })
        return
      }
      try {
        const [manageableConnections, assignableUsers] = await Promise.all([
          api.listManageableConnections(),
          api.listAssignableUsers(),
        ])
        set({ manageableConnections, assignableUsers })
      } catch {
        /* leave prior lists in place if the probe fails */
      }
    },

    saveManagedConnection: async (body) => {
      try {
        await api.saveManagedConnection(body)
        await Promise.all([get().refreshManageable(), get().refreshConnections()])
        return { ok: true, error: null }
      } catch (error) {
        return {
          ok: false,
          error: error instanceof ApiError ? error.message : String(error),
        }
      }
    },

    deleteManagedConnection: async (id) => {
      try {
        await api.deleteManagedConnection(id)
        await Promise.all([get().refreshManageable(), get().refreshConnections()])
        return true
      } catch (error) {
        set({
          errorMessage: error instanceof ApiError ? error.message : String(error),
        })
        return false
      }
    },

    testManagedConnection: async (body) => {
      try {
        return await api.testManagedConnection(body)
      } catch (error) {
        const message = error instanceof ApiError ? error.message : String(error)
        return { dbError: message, llmError: null, llmModels: [] }
      }
    },

    provisionSchema: async (body) => {
      try {
        return await api.provisionManagedSchema(body)
      } catch (error) {
        const message = error instanceof ApiError ? error.message : String(error)
        return { ok: false, error: message, created: [] }
      }
    },

    generateDemo: async (body) => {
      try {
        return await api.generateDemoContent(body)
      } catch (error) {
        const message = error instanceof ApiError ? error.message : String(error)
        return { ok: false, error: message, journeys: 0 }
      }
    },

    listConnectionProjects: async (id) => {
      try {
        return await api.listConnectionProjects(id)
      } catch (error) {
        const message = error instanceof ApiError ? error.message : String(error)
        return { ok: false, error: message, projects: [] }
      }
    },

    deleteConnectionProject: async (id, projectId) => {
      try {
        return await api.deleteConnectionProject(id, projectId)
      } catch (error) {
        const message = error instanceof ApiError ? error.message : String(error)
        return { ok: false, error: message }
      }
    },

    checkSession: async () => {
      try {
        const s = await api.session()
        set({
          authChecked: true,
          authUser: s.authenticated ? s.username : null,
          authDisplayName: s.authenticated ? s.displayName : null,
          authIsAdmin: s.isAdmin,
          authIsPower: s.isPower,
          authIsDeveloper: s.isDeveloper,
          authPasskeyAllowed: s.authenticated ? s.passkeyAllowed : false,
          authMfaAllowed: s.authenticated ? s.mfaAllowed : false,
          authMfaEnabled: s.authenticated ? s.mfaEnabled : false,
          requireLogin: s.requireLogin,
          idleTimeoutMins: s.idleTimeoutMins ?? 0,
          actionsEnabled: s.actionsEnabled ?? false,
        })
        if (s.authenticated) void get().refreshManageable()
      } catch {
        // If the session probe fails, assume open access so the app still loads.
        set({ authChecked: true, authUser: null, requireLogin: false })
      }
    },

    login: async (username, password) => {
      try {
        const result = await api.login(username, password)
        if ('mfaRequired' in result) {
          // Password ok, but a second factor is needed — LoginView shows the code step.
          set({ mfaPending: result.username, mfaSetupPending: null, signedOutForInactivity: false })
          return null
        }
        if ('mfaSetupRequired' in result) {
          // 2FA is required but not configured — LoginView forces enrolment; no session.
          set({ mfaSetupPending: result.username, mfaPending: null, signedOutForInactivity: false })
          return null
        }
        set({
          ...hydrateAuth(result),
          mfaPending: null,
          mfaSetupPending: null,
          signedOutForInactivity: false,
        })
        void get().refreshManageable()
        return null
      } catch (error) {
        return error instanceof ApiError ? error.message : String(error)
      }
    },

    verifyMfa: async (code) => {
      try {
        const result = await api.verifyMfa(code)
        set({ ...hydrateAuth(result), mfaPending: null, signedOutForInactivity: false })
        void get().refreshManageable()
        return null
      } catch (error) {
        return error instanceof ApiError ? error.message : String(error)
      }
    },

    enrollMfaBegin: async () => {
      // Throws (ApiError) on failure — LoginView surfaces the message.
      return api.mfaEnrollBegin()
    },

    enrollMfaFinish: async (code) => {
      const result = await api.mfaEnrollFinish(code)
      // The server has issued the session; hydrate auth but keep `mfaSetupPending`
      // set so LoginView stays up to show the recovery codes once.
      set({ ...hydrateAuth(result), mfaPending: null, signedOutForInactivity: false })
      void get().refreshManageable()
      return result.recoveryCodes
    },

    finishMfaSetup: () => set({ mfaSetupPending: null }),

    cancelMfa: () => set({ mfaPending: null, mfaSetupPending: null }),

    loginWithPasskey: async (username) => {
      try {
        const result = await authenticateWithPasskey(username)
        set({
          ...hydrateAuth(result),
          mfaPending: null,
          signedOutForInactivity: false,
        })
        void get().refreshManageable()
        return null
      } catch (error) {
        // A user-cancelled ceremony (NotAllowedError / AbortError) is not an error.
        if (error instanceof DOMException && (error.name === 'NotAllowedError' || error.name === 'AbortError')) {
          return ''
        }
        return error instanceof Error ? error.message : String(error)
      }
    },

    logout: async (opts) => {
      try {
        await api.logout()
      } catch {
        /* clearing the cookie is best-effort */
      }
      set({
        authUser: null,
        authDisplayName: null,
        authIsAdmin: false,
        authIsPower: false,
        authIsDeveloper: false,
        authPasskeyAllowed: false,
        authMfaAllowed: false,
        authMfaEnabled: false,
        mfaPending: null,
        mfaSetupPending: null,
        manageableConnections: [],
        assignableUsers: [],
        signedOutForInactivity: opts?.inactivity ?? false,
        selectedProject: null,
        projects: [],
      })
    },

    // ── projects ──────────────────────────────────────────────────────────

    loadProjects: async () => {
      if (!get().connection.isConnected) return
      set({ isLoading: true, errorMessage: null })
      try {
        set({ projects: await api.listProjects() })
      } catch (error) {
        const message = error instanceof ApiError ? error.message : String(error)
        set({ errorMessage: message })
        get().showAlert({
          title: 'Failed to Load Projects',
          message,
          primaryLabel: 'Retry',
          onPrimary: () => void get().loadProjects(),
          secondaryLabel: 'Cancel',
        })
      } finally {
        set({ isLoading: false })
      }
    },

    selectProject: async (project) => {
      const projectId = project.projectId
      set({
        selectedProject: project,
        activeChartMode: 'A-Chart',
        savedChartStates: {},
        isLoading: true,
        errorMessage: null,
        // Any plain project switch leaves drill-down context; drillDownTo re-sets it after.
        drillReturn: null,
        inPlaceDrill: null,
        panelDrill: null,
        // reset active chart
        processGraph: EMPTY_GRAPH,
        includedSteps: [],
        excludedSteps: [],
        metaFilters: emptyMetaFilters(),
        meta1Filter: '',
        meta2Filter: '',
        meta3Filter: '',
        eventIdFilter: '',
        eventIdSuggestions: [],
        journeyDate: null,
        journeyEndDate: null,
        journeyCount: null,
        journeyMeta1: null,
        journeyMeta2: null,
        journeyMeta3: null,
        durations: EMPTY_DURATIONS,
        processGoodnessScore: null,
        // reset A/B
        abActiveSide: 'a',
        abGraphA: EMPTY_GRAPH,
        abGraphB: EMPTY_GRAPH,
        abJourneyCountA: null,
        abJourneyCountB: null,
        abDurationsA: EMPTY_DURATIONS,
        abDurationsB: EMPTY_DURATIONS,
        abGoodnessA: null,
        abGoodnessB: null,
        abVariantsA: [],
        abVariantsB: [],
        abSimilarityScore: null,
        abFilterGroupIdA: null,
        abFilterGroupIdB: null,
        abDataSourceA: { kind: 'sampleSet', sampleSet: 'ORIGINAL' },
        abDataSourceB: { kind: 'sampleSet', sampleSet: 'ORIGINAL' },
        simResultA: null,
        simResultB: null,
        // reset statistics + AI
        statistics: null,
        statsLoadedSnapshot: null,
        llmAnalysis: null,
        llmAnalysisError: null,
        happyPathScores: {},
      })

      // Remember the open project (and that we're back on A-Chart) for the resume.
      writeSetting('session.lastProjectId', projectId)
      writeSetting('session.lastChartMode', 'A-Chart')

      try {
        const boot = await api.bootstrap(projectId, activeSampleSet('a'))

        const toDate = boot.initialToDate
          ? toISODate(boot.initialToDate)
          : get().toDate
        let fromDate = boot.initialFromDate
          ? toISODate(boot.initialFromDate)
          : get().fromDate

        // Default window: show the last N days ending at the latest event date,
        // clamped to the project's earliest date so it never goes empty. N = 0
        // keeps the backend's full-range default.
        const windowDays = readSetting<number>('graph.defaultWindowDays')
        const toAnchor = fromISODate(toDate)
        if (windowDays && windowDays > 0 && toAnchor) {
          const minDate = boot.minDate ? toISODate(boot.minDate) : fromDate
          const windowStart = toISODate(addDays(toAnchor, -windowDays))
          fromDate = windowStart < minDate ? minDate : windowStart
        }

        // A previously selected sample may no longer exist in the database.
        for (const side of ['a', 'b'] as ABSide[]) {
          const set_ = activeSampleSet(side)
          if (set_ !== 'ORIGINAL' && boot.sampleCounts[set_] == null) {
            writeSetting(
              side === 'a' ? 'sampling.activeSampleSetA' : 'sampling.activeSampleSetB',
              'ORIGINAL',
            )
          }
        }

        const maxJourneyTime =
          boot.journeyTimeBoundsMax > 0 ? boot.journeyTimeBoundsMax : INT_MAX

        set({
          allSteps: boot.allSteps,
          allStepInfos: boot.allStepInfos,
          meta1Title: boot.meta1Title,
          meta2Title: boot.meta2Title,
          meta3Title: boot.meta3Title,
          meta1Values: boot.meta1Values,
          meta2Values: boot.meta2Values,
          meta3Values: boot.meta3Values,
          totalJourneyCount: boot.totalJourneyCount,
          fromDate,
          toDate,
          initialFromDate: fromDate,
          initialToDate: toDate,
          projectMinDate: boot.minDate ? toISODate(boot.minDate) : fromDate,
          stepCountMin: boot.stepCountMin,
          stepCountMax: boot.stepCountMax,
          minStepsFilter: boot.stepCountMin,
          maxStepsFilter: boot.stepCountMax,
          journeyTimeBoundsMin: boot.journeyTimeBoundsMin,
          journeyTimeBoundsMax: boot.journeyTimeBoundsMax,
          minJourneyTimeFilter: boot.journeyTimeBoundsMin,
          maxJourneyTimeFilter: maxJourneyTime,
          scoreBoundsMin: boot.scoreBoundsMin,
          scoreBoundsMax: boot.scoreBoundsMax,
          minScoreFilter: boot.scoreBoundsMin,
          maxScoreFilter: boot.scoreBoundsMax,
          sampleCounts: boot.sampleCounts,
          sampleMethods: boot.sampleMethods ?? {},
        })

        // Per-project persisted state
        set({
          filterGroups: readJSON<FilterGroup[]>(projectKeys.filterGroups(projectId), []),
          selectedFilterGroupId: null,
          targetNorms: readJSON<Record<string, Record<string, number>>>(
            projectKeys.norms(projectId),
            {},
          ),
          targetMetric: readJSON<TransitionMetric>(
            projectKeys.normsMetric(projectId),
            'Count',
          ),
          llmPromptTemplate: readJSON<string>(
            projectKeys.llmPrompt(projectId),
            DEFAULT_LLM_PROMPT,
          ),
        })
        const happyPaths = readJSON<LegacyHappyPath[]>(
          projectKeys.happyPaths(projectId),
          [],
        ).map(migrateHappyPath)
        set({
          happyPaths,
          selectedHappyPathId: happyPaths[0]?.id ?? null,
        })

        // Initial A-Chart load
        const result = await api.graph(projectId, get().currentFilterSpec(), {
          totalJourneyCount: boot.totalJourneyCount,
        })
        set({
          processGraph: result.processGraph,
          journeyCount: result.journeyCount,
          durations: result.durations,
          processGoodnessScore: result.processGoodness,
          transitionsMode: result.transitionsMode,
          queryMs: result.queryMs,
        })

        // Load this project's saved node-menu actions (no-op unless the feature is on).
        void get().loadProjectActions()
        // Load this project's aggregate links (for Σ drill-down).
        void get().loadProjectAggregates()

        // Seed the other chart modes with the same window and real bounds.
        const seed = defaultChartState(fromDate, toDate, {
          minStepsFilter: boot.stepCountMin,
          maxStepsFilter: boot.stepCountMax,
          minJourneyTimeFilter: boot.journeyTimeBoundsMin,
          maxJourneyTimeFilter: maxJourneyTime,
          minScoreFilter: boot.scoreBoundsMin,
          maxScoreFilter: boot.scoreBoundsMax,
        })
        const saved: Partial<Record<DetailViewMode, ChartFilterState>> = {}
        for (const mode of [
          'B-Chart',
          'A/B Comparison',
          'Individual Journey',
          'AI supported Documentation',
          'Statistics',
          'Conformance Check',
          'Happy Path',
          'Notes',
          'Simulation',
        ] as DetailViewMode[]) {
          saved[mode] = seed
        }
        set({ savedChartStates: saved })

        await get().loadNotes()
      } catch (error) {
        const message = error instanceof ApiError ? error.message : String(error)
        set({ errorMessage: message })
        get().showAlert({
          title: 'Failed to Load Project',
          message,
          primaryLabel: 'Retry',
          onPrimary: () => void get().selectProject(project),
          secondaryLabel: 'Cancel',
        })
      } finally {
        set({ isLoading: false })
      }
    },

    restoreLastSession: async () => {
      const connId = readSetting<string>('session.lastConnectionId', '')
      const projId = readSetting<number>('session.lastProjectId', 0)
      const mode = readSetting<string>('session.lastChartMode', '')

      // 1) Auto-reconnect to the last connection, unless we are already on it (e.g. the
      //    server session survived a plain reload). connectConnection loads the projects.
      //    This is the key "resume after a backend restart" path — the in-memory Exasol
      //    session is lost on any restart/redeploy, so on reload we transparently
      //    reconnect instead of leaving the user to reconnect + reselect by hand.
      const before = get()
      if (connId && before.connection.activeProfileId !== connId) {
        const match = before.connections.find((c) => c.id === connId)
        // A loaded list without this connection means it was revoked / unassigned —
        // nothing to resume. But an EMPTY list is a boot race (the assigned connections
        // haven't arrived yet); connectConnection only needs the id and the server
        // re-checks assignment, so attempt the resume with a bare {id} rather than
        // silently giving up and leaving the user to reconnect by hand.
        if (!match && before.connections.length > 0) return
        const ok = await get().connectConnection(match ?? ({ id: connId } as AssignedConnection))
        if (!ok) return // reconnect failed (its own alert already explains why)
      } else if (connId && before.connection.isConnected && before.projects.length === 0) {
        await get().loadProjects()
      }
      if (!connId || !get().connection.isConnected) return

      // 2) Reopen the last project (selectProject resets the view to A-Chart).
      if (!projId) return
      const project = get().projects.find((p) => p.projectId === projId)
      if (!project) return
      await get().selectProject(project)

      // 3) Restore the last view — must come AFTER selectProject, which forced A-Chart.
      if (mode && mode !== 'A-Chart' && (DETAIL_VIEW_MODES as readonly string[]).includes(mode)) {
        get().switchChartMode(mode as DetailViewMode)
      }
    },

    // ── chart mode switching ──────────────────────────────────────────────

    setTransitionMetric: (metric) => {
      const s = get()
      set({ transitionMetric: metric })
      if (s.activeChartMode === 'A/B Comparison') {
        get().setABMetric(metric, s.abActiveSide)
      }
    },

    switchChartMode: (mode) => {
      const s = get()
      if (mode === s.activeChartMode) return

      const current = captureCurrentState()
      const saved = { ...s.savedChartStates }

      if (s.activeChartMode === 'A/B Comparison') {
        if (s.abActiveSide === 'a') {
          saved['A-Chart'] = current
          set({
            abGraphA: s.processGraph,
            abJourneyCountA: s.journeyCount,
            abMetricA: s.transitionMetric,
            abGoodnessA: s.processGoodnessScore,
          })
        } else {
          saved['B-Chart'] = current
          set({
            abGraphB: s.processGraph,
            abJourneyCountB: s.journeyCount,
            abMetricB: s.transitionMetric,
            abGoodnessB: s.processGoodnessScore,
          })
        }
      } else {
        saved[s.activeChartMode] = current
      }

      set({ activeChartMode: mode, savedChartStates: saved })
      writeSetting('session.lastChartMode', mode)

      if (mode === 'A/B Comparison') {
        const a = saved['A-Chart']
        const b = saved['B-Chart']
        set({
          abActiveSide: 'a',
          abGraphA: a?.processGraph ?? EMPTY_GRAPH,
          abGraphB: b?.processGraph ?? EMPTY_GRAPH,
          abJourneyCountA: a?.journeyCount ?? null,
          abJourneyCountB: b?.journeyCount ?? null,
          abMetricA: a?.transitionMetric ?? 'Count',
          abMetricB: b?.transitionMetric ?? 'Count',
          abDurationsA: a?.durations ?? EMPTY_DURATIONS,
          abDurationsB: b?.durations ?? EMPTY_DURATIONS,
          abGoodnessA: a?.processGoodness ?? null,
          abGoodnessB: b?.processGoodness ?? null,
        })
        if (a) applyChartState(a)
        reapplySimSources()
        void get().refreshABSimilarity()
      } else if (mode === 'Statistics') {
        // Statistics always inherits Chart A's filter state.
        const a = saved['A-Chart']
        if (a) applyChartState(a)
      } else {
        const target = saved[mode]
        if (target) applyChartState(target)
        // A-Chart / B-Chart single views mirror the A/B sides — honour a simulation source.
        if (mode === 'A-Chart' || mode === 'B-Chart') reapplySimSources()
      }

      if (
        ['A-Chart', 'B-Chart', 'A/B Comparison', 'AI supported Documentation', 'Notes'].includes(
          mode,
        )
      ) {
        void get().loadNotes()
      }
    },

    switchABSide: (side) => {
      const s = get()
      if (side === s.abActiveSide) return
      const current = captureCurrentState()
      const saved = { ...s.savedChartStates }

      if (s.abActiveSide === 'a') {
        saved['A-Chart'] = current
        set({
          abGraphA: s.processGraph,
          abJourneyCountA: s.journeyCount,
          abMetricA: s.transitionMetric,
          abDurationsA: s.durations,
          abGoodnessA: s.processGoodnessScore,
        })
      } else {
        saved['B-Chart'] = current
        set({
          abGraphB: s.processGraph,
          abJourneyCountB: s.journeyCount,
          abMetricB: s.transitionMetric,
          abDurationsB: s.durations,
          abGoodnessB: s.processGoodnessScore,
        })
      }

      set({ abActiveSide: side, savedChartStates: saved })

      const target = saved[side === 'a' ? 'A-Chart' : 'B-Chart']
      if (target) {
        applyChartState(target)
      } else {
        set({
          processGraph: EMPTY_GRAPH,
          journeyCount: null,
          includedSteps: [],
          excludedSteps: [],
          metaFilters: emptyMetaFilters(),
          meta1Filter: '',
          meta2Filter: '',
          meta3Filter: '',
        })
      }

      const after = get()
      if (side === 'a') {
        set({
          abGraphA: after.processGraph,
          abJourneyCountA: after.journeyCount,
          abMetricA: after.transitionMetric,
          abDurationsA: after.durations,
          abGoodnessA: after.processGoodnessScore,
        })
      } else {
        set({
          abGraphB: after.processGraph,
          abJourneyCountB: after.journeyCount,
          abMetricB: after.transitionMetric,
          abDurationsB: after.durations,
          abGoodnessB: after.processGoodnessScore,
        })
      }
      // A sim-sourced side must keep its in-memory graph across the active-side switch.
      reapplySimSources()
    },

    setABMetric: (metric, side) => {
      const s = get()
      const saved = { ...s.savedChartStates }
      const mode: DetailViewMode = side === 'a' ? 'A-Chart' : 'B-Chart'
      if (saved[mode]) saved[mode] = { ...saved[mode], transitionMetric: metric }
      set({
        savedChartStates: saved,
        ...(side === 'a' ? { abMetricA: metric } : { abMetricB: metric }),
      })
      if (s.abActiveSide === side) set({ transitionMetric: metric })
    },

    // ── actions (node-menu) ───────────────────────────────────────────────

    loadProjectActions: async () => {
      const s = get()
      const connId = s.connection.activeProfileId
      const projectId = s.selectedProject?.projectId
      const runRole = s.authIsPower || s.authIsDeveloper || s.authIsAdmin
      if (!s.actionsEnabled || !runRole || !connId || !projectId) {
        set({ projectActions: [] })
        return
      }
      try {
        const r = await api.listActions(projectId, connId)
        set({ projectActions: r.actions.filter((a) => a.enabled) })
      } catch {
        set({ projectActions: [] }) // never block the chart on this
      }
    },

    loadProjectAggregates: async () => {
      const s = get()
      const connId = s.connection.activeProfileId
      const projectId = s.selectedProject?.projectId
      if (!connId || !projectId) {
        set({ projectAggregates: [] })
        return
      }
      try {
        const r = await api.listAggregates(projectId, connId)
        set({ projectAggregates: r.aggregates })
      } catch {
        set({ projectAggregates: [] }) // never block the chart on this
      }
    },

    drillDownTo: async (link) => {
      const s = get()
      if (link.detailConnectionId !== s.connection.activeProfileId) {
        s.showAlert({
          title: 'Detail on another connection',
          message: `This Σ step's detail lives on a different connection. Connect to it and open project “${link.detailProjectId}”.`,
          primaryLabel: 'OK',
        })
        return
      }
      const from = s.selectedProject // the high-level map we're leaving
      let project = s.projects.find((p) => p.projectId === link.detailProjectId)
      if (!project) {
        await get().loadProjects()
        project = get().projects.find((p) => p.projectId === link.detailProjectId)
      }
      if (!project) {
        s.showAlert({
          title: 'Detail project not found',
          message: `Project “${link.detailProjectId}” isn't listed here — it may live in a different schema.`,
          primaryLabel: 'OK',
        })
        return
      }
      await get().selectProject(project) // clears drillReturn
      if (from) set({ drillReturn: { projectId: from.projectId, title: from.title } })
    },

    returnFromDrill: async () => {
      const ret = get().drillReturn
      if (!ret) return
      let project = get().projects.find((p) => p.projectId === ret.projectId)
      if (!project) {
        await get().loadProjects()
        project = get().projects.find((p) => p.projectId === ret.projectId)
      }
      if (project) await get().selectProject(project) // clears drillReturn
    },

    drillDown: async (link) => {
      // Read the mode at click-time from the shared settings cache, so the choice can never
      // be stale relative to a component's captured render value.
      const mode = readSetting<string>('aggregates.drillMode', 'panel')
      if (mode === 'inplace') await get().drillDownInPlace(link)
      else await get().drillDownTo(link)
    },

    drillDownInPlace: async (link) => {
      const s = get()
      if (link.detailConnectionId !== s.connection.activeProfileId) {
        s.showAlert({
          title: 'Detail on another connection',
          message: `This Σ step's detail lives on a different connection. Connect to it and open project “${link.detailProjectId}”.`,
          primaryLabel: 'OK',
        })
        return
      }
      const connId = s.connection.activeProfileId
      const projectId = s.selectedProject?.projectId
      if (!connId || !projectId) return
      set({ isLoading: true, errorMessage: null })
      try {
        // Expand the Σ node IN PLACE using the ORIGINAL source graph, so the revealed steps
        // carry the same numbers as the non-aggregated flowchart. Cache the source graph so
        // expanding further Σ nodes needs no extra round trip.
        const current = get()
        let source = current.inPlaceDrill?.source
        if (!source) {
          // Same date window / META filters as the high-level view, so the numbers match.
          const r = await api.aggregateDrill(projectId, connId, get().currentFilterSpec())
          source = { graph: r.graph, journeyCount: r.journeyCount, aggregates: r.aggregates }
        }
        const expanded = new Set(current.inPlaceDrill?.expanded ?? [])
        expanded.add(link.sigmaStep)
        // Σ node presentation comes from the high-level map.
        const sigmaInfo = (sig: string) => current.processGraph.steps[sig]
        const graph = collapseExcept(source.graph, source.aggregates, expanded, sigmaInfo)
        set({
          isLoading: false,
          inPlaceDrill: {
            sigmaStep: link.sigmaStep,
            expanded: [...expanded],
            graph,
            journeyCount: source.journeyCount,
            source,
          },
        })
      } catch (e) {
        set({ isLoading: false })
        s.showAlert({
          title: 'Drill-down failed',
          message: String((e as Error).message ?? e),
          primaryLabel: 'OK',
        })
      }
    },

    drillUp: () => set({ inPlaceDrill: null }),

    drillDownPanel: async (link) => {
      const s = get()
      const connId = s.connection.activeProfileId
      const projectId = s.selectedProject?.projectId
      if (!connId || !projectId) return
      set({ isLoading: true, errorMessage: null })
      try {
        // Same source graph as the in-place drill; show just this Σ's members in isolation
        // with their real numbers, in a modal panel.
        const source =
          s.inPlaceDrill?.source ??
          (await api.aggregateDrill(projectId, connId, get().currentFilterSpec()))
        const agg = source.aggregates.find((a) => a.sigmaStep === link.sigmaStep)
        // Include the incoming/outgoing edges + neighbouring steps so the sub-process is
        // shown wired into the rest of the process (real, un-aggregated numbers).
        const { graph } = subgraphWithNeighbours(source.graph, agg?.members ?? [])
        set({
          isLoading: false,
          panelDrill: { sigmaStep: link.sigmaStep, graph, journeyCount: source.journeyCount },
        })
      } catch (e) {
        set({ isLoading: false })
        s.showAlert({
          title: 'Drill-down failed',
          message: String((e as Error).message ?? e),
          primaryLabel: 'OK',
        })
      }
    },

    closeDrillPanel: () => set({ panelDrill: null }),

    refreshDrill: async () => {
      const s = get()
      if (!s.inPlaceDrill && !s.panelDrill) return
      const connId = s.connection.activeProfileId
      const projectId = s.selectedProject?.projectId
      if (!connId || !projectId) return
      try {
        const r = await api.aggregateDrill(projectId, connId, get().currentFilterSpec())
        const source = { graph: r.graph, journeyCount: r.journeyCount, aggregates: r.aggregates }
        const cur = get()
        if (cur.inPlaceDrill) {
          const expanded = new Set(cur.inPlaceDrill.expanded)
          const sigmaInfo = (sig: string) => cur.processGraph.steps[sig]
          const graph = collapseExcept(source.graph, source.aggregates, expanded, sigmaInfo)
          set({ inPlaceDrill: { ...cur.inPlaceDrill, graph, journeyCount: source.journeyCount, source } })
        }
        if (cur.panelDrill) {
          const agg = source.aggregates.find((a) => a.sigmaStep === cur.panelDrill!.sigmaStep)
          const { graph } = subgraphWithNeighbours(source.graph, agg?.members ?? [])
          set({ panelDrill: { ...cur.panelDrill, graph, journeyCount: source.journeyCount } })
        }
      } catch {
        // Leave the current drill untouched if the refresh fails.
      }
    },

    // ── filters ───────────────────────────────────────────────────────────

    currentFilterSpec: () => {
      const s = get()
      const side: ABSide =
        s.activeChartMode === 'B-Chart' ||
        (s.activeChartMode === 'A/B Comparison' && s.abActiveSide === 'b')
          ? 'b'
          : 'a'
      return specFrom(s, activeSampleSet(side))
    },

    currentFilterSnapshot: () => {
      const s = get()
      return {
        fromDate: s.fromDate,
        toDate: s.toDate,
        includedSteps: s.includedSteps,
        excludedSteps: s.excludedSteps,
        ...metaFilterFields(metaFiltersOf(s.metaFilters)),
        meta1: s.meta1Filter,
        meta2: s.meta2Filter,
        meta3: s.meta3Filter,
        minSteps: s.minStepsFilter,
        maxSteps: s.maxStepsFilter,
        minJourneyTime: s.minJourneyTimeFilter,
        maxJourneyTime: s.maxJourneyTimeFilter,
        minScore: s.minScoreFilter,
        maxScore: s.maxScoreFilter,
      }
    },

    resetFilters: () => {
      const s = get()
      set({
        fromDate: s.initialFromDate,
        toDate: s.initialToDate,
        includedSteps: [],
        excludedSteps: [],
        metaFilters: emptyMetaFilters(),
        meta1Filter: '',
        meta2Filter: '',
        meta3Filter: '',
        minStepsFilter: s.stepCountMin,
        maxStepsFilter: s.stepCountMax,
        minJourneyTimeFilter: s.journeyTimeBoundsMin,
        maxJourneyTimeFilter: s.journeyTimeBoundsMax,
        minScoreFilter: s.scoreBoundsMin,
        maxScoreFilter: s.scoreBoundsMax,
      })
    },

    reloadGraph: async () => {
      const s = get()
      if (!s.selectedProject) return
      // Tie this load to the current connection. If a connect/disconnect happens
      // while the request is in flight (the shared DB session is torn down), the
      // response — or a "Not connected" error — belongs to a connection that is no
      // longer active, so it is discarded rather than shown or alerted.
      const gen = s.connectionGen
      set({ isLoading: true, errorMessage: null })
      try {
        const result = await api.graph(
          s.selectedProject.projectId,
          get().currentFilterSpec(),
          { totalJourneyCount: s.totalJourneyCount },
        )
        if (get().connectionGen !== gen) return  // superseded by a connection switch
        set({
          processGraph: result.processGraph,
          journeyCount: result.journeyCount,
          durations: result.durations,
          processGoodnessScore: result.processGoodness,
          transitionsMode: result.transitionsMode,
          queryMs: result.queryMs,
        })

        // Keep an active drill in step with the (new) filter, so its numbers track the map.
        void get().refreshDrill()

        if (get().activeChartMode === 'A/B Comparison') {
          const after = get()
          const saved = { ...after.savedChartStates }
          if (after.abActiveSide === 'a') {
            saved['A-Chart'] = captureCurrentState()
            set({
              abGraphA: result.processGraph,
              abJourneyCountA: result.journeyCount,
              abMetricA: after.transitionMetric,
              abDurationsA: result.durations,
              abGoodnessA: result.processGoodness,
              savedChartStates: saved,
            })
          } else {
            saved['B-Chart'] = captureCurrentState()
            set({
              abGraphB: result.processGraph,
              abJourneyCountB: result.journeyCount,
              abMetricB: after.transitionMetric,
              abDurationsB: result.durations,
              abGoodnessB: result.processGoodness,
              savedChartStates: saved,
            })
          }
          await get().refreshABSimilarity()
        }

        if (get().activeChartMode === 'Happy Path') {
          await get().refreshHappyPathConformance()
        }
      } catch (error) {
        // A load whose connection was swapped out mid-flight failed because the
        // session is gone, not because anything is wrong — swallow it; the newer
        // load owns the UI now.
        if (get().connectionGen !== gen) return
        const message = error instanceof ApiError ? error.message : String(error)
        set({ errorMessage: message })
        get().showAlert({
          title: 'Failed to Reload Chart',
          message,
          primaryLabel: 'Retry',
          onPrimary: () => void get().reloadGraph(),
          secondaryLabel: 'Cancel',
        })
      } finally {
        // Only clear the spinner if this load is still the current one; a superseded
        // load must not switch off the spinner a newer load turned on.
        if (get().connectionGen === gen) set({ isLoading: false })
      }
    },

    reloadGraphForDay: async (day) => {
      set({ fromDate: day, toDate: day })
      await get().reloadGraph()
      if (get().processGraph.transitions.length > 0) return day

      const project = get().selectedProject
      if (!project) return null
      try {
        const { date } = await api.nearestDay(
          project.projectId,
          day,
          activeSampleSet('a'),
        )
        if (!date) {
          get().showAlert({
            title: 'No Journey Data',
            message: 'No journeys exist for this date or any nearby dates.',
            primaryLabel: 'OK',
          })
          return null
        }
        const nearest = toISODate(date)
        set({ fromDate: nearest, toDate: nearest })
        await get().reloadGraph()
        get().showAlert({
          title: `No Journeys on ${day}`,
          message: `No journeys were found on ${day}. Jumped to the nearest date with data: ${nearest}.`,
          primaryLabel: 'OK',
        })
        return nearest
      } catch {
        return null
      }
    },

    reloadABSide: async (side, from, to) => {
      const s = get()
      const source = side === 'a' ? s.abDataSourceA : s.abDataSourceB
      if (source.kind === 'simulation') {
        applySimulationToABSide(side)
        return
      }
      const project = s.selectedProject
      if (!project) return

      const mode: DetailViewMode = side === 'a' ? 'A-Chart' : 'B-Chart'
      const saved = s.savedChartStates[mode]
      const base = saved ?? defaultChartState(from, to)

      set(side === 'a' ? { isLoadingA: true } : { isLoadingB: true })
      set({ errorMessage: null })
      try {
        const spec = {
          ...specFrom({ ...base, fromDate: from, toDate: to }, activeSampleSet(side)),
        }
        const result = await api.graph(project.projectId, spec, {
          totalJourneyCount: s.totalJourneyCount,
          includeVariants: true,
        })

        const nextSaved = { ...get().savedChartStates }
        nextSaved[mode] = {
          ...base,
          fromDate: from,
          toDate: to,
          processGraph: result.processGraph,
          journeyCount: result.journeyCount,
          durations: result.durations,
          processGoodness: result.processGoodness,
        }
        set({ savedChartStates: nextSaved })

        if (side === 'a') {
          set({
            abGraphA: result.processGraph,
            abJourneyCountA: result.journeyCount,
            abDurationsA: result.durations,
            abGoodnessA: result.processGoodness,
            abVariantsA: result.variants,
          })
        } else {
          set({
            abGraphB: result.processGraph,
            abJourneyCountB: result.journeyCount,
            abDurationsB: result.durations,
            abGoodnessB: result.processGoodness,
            abVariantsB: result.variants,
          })
        }

        if (get().abActiveSide === side) {
          set({
            processGraph: result.processGraph,
            journeyCount: result.journeyCount,
            durations: result.durations,
            processGoodnessScore: result.processGoodness,
            fromDate: from,
            toDate: to,
          })
        }
        await get().refreshABSimilarity()
      } catch (error) {
        const message = error instanceof ApiError ? error.message : String(error)
        set({ errorMessage: message })
        get().showAlert({
          title: 'Failed to Reload Chart',
          message,
          primaryLabel: 'Retry',
          onPrimary: () => void get().reloadABSide(side, from, to),
          secondaryLabel: 'Cancel',
        })
      } finally {
        set(side === 'a' ? { isLoadingA: false } : { isLoadingB: false })
      }
    },

    reloadABSideForDay: async (side, day) => {
      await get().reloadABSide(side, day, day)
      const graph = side === 'a' ? get().abGraphA : get().abGraphB
      if (graph.transitions.length > 0) return day

      const project = get().selectedProject
      if (!project) return null
      try {
        const { date } = await api.nearestDay(
          project.projectId,
          day,
          activeSampleSet(side),
        )
        if (!date) {
          get().showAlert({
            title: 'No Journey Data',
            message: 'No journeys exist for this date or any nearby dates.',
            primaryLabel: 'OK',
          })
          return null
        }
        const nearest = toISODate(date)
        await get().reloadABSide(side, nearest, nearest)
        get().showAlert({
          title: `No Journeys on ${day}`,
          message: `No journeys were found on ${day}. Jumped to the nearest date with data: ${nearest}.`,
          primaryLabel: 'OK',
        })
        return nearest
      } catch {
        return null
      }
    },

    refreshABSimilarity: async () => {
      const s = get()
      const project = s.selectedProject
      if (
        !project ||
        s.abGraphA.transitions.length === 0 ||
        s.abGraphB.transitions.length === 0
      ) {
        set({ abSimilarityScore: null })
        return
      }

      // Fetch each side's variants from its saved filter state when they are not
      // already cached (mirrors AppViewModel.refreshABSimilarity).
      const variantsFor = async (side: ABSide): Promise<JourneyPath[]> => {
        const cached = side === 'a' ? s.abVariantsA : s.abVariantsB
        if (cached.length > 0) return cached
        const saved = s.savedChartStates[side === 'a' ? 'A-Chart' : 'B-Chart']
        const spec = specFrom(saved ?? s, activeSampleSet(side))
        try {
          return await api.journeyPaths(project.projectId, spec, 500)
        } catch {
          return []
        }
      }

      const [variantsA, variantsB] = await Promise.all([
        variantsFor('a'),
        variantsFor('b'),
      ])
      set({ abVariantsA: variantsA, abVariantsB: variantsB })

      if (variantsA.length === 0 || variantsB.length === 0) {
        set({ abSimilarityScore: null })
        return
      }
      try {
        const { score } = await api.similarity({
          variantsA,
          variantsB,
          graphA: get().abGraphA,
          graphB: get().abGraphB,
        })
        set({ abSimilarityScore: score })
      } catch {
        set({ abSimilarityScore: null })
      }
    },

    // ── statistics ────────────────────────────────────────────────────────

    loadStatistics: async () => {
      const s = get()
      if (!s.selectedProject) return
      set({
        isLoadingStats: true,
        statsErrorMessage: null,
        statsLoadedSnapshot: get().currentFilterSnapshot(),
      })
      try {
        const stats = await api.statistics(
          s.selectedProject.projectId,
          get().currentFilterSpec(),
          s.statsRouteLimit,
          s.totalJourneyCount,
        )
        set({
          statistics: stats,
          journeyCount: stats.journeyCount,
          totalJourneyCount: stats.totalJourneyCount ?? s.totalJourneyCount,
          durations: stats.durations,
        })
      } catch (error) {
        const message = error instanceof ApiError ? error.message : String(error)
        set({ statsErrorMessage: message })
        get().showAlert({
          title: 'Statistics Error',
          message,
          primaryLabel: 'Retry',
          onPrimary: () => void get().loadStatistics(),
          secondaryLabel: 'Cancel',
        })
      } finally {
        set({ isLoadingStats: false })
      }
    },

    // ── individual journey ────────────────────────────────────────────────

    fetchEventIdSuggestions: async () => {
      const s = get()
      if (!s.selectedProject || s.eventIdFilter.length < 2) {
        set({ eventIdSuggestions: [] })
        return
      }
      try {
        set({
          eventIdSuggestions: await api.eventIds(
            s.selectedProject.projectId,
            s.eventIdFilter,
            activeSampleSet('a'),
          ),
        })
      } catch {
        set({ eventIdSuggestions: [] })
      }
    },

    loadIndividualJourney: async () => {
      const s = get()
      if (!s.selectedProject || !s.eventIdFilter.trim()) return
      set({
        isLoading: true,
        errorMessage: null,
        journeyMeta1: null,
        journeyMeta2: null,
        journeyMeta3: null,
      })
      try {
        const result = await api.journey(
          s.selectedProject.projectId,
          s.eventIdFilter.trim(),
          activeSampleSet('a'),
        )
        set({
          lastQueriedEventId: result.queriedEventId,
          processGraph: result.processGraph,
          journeySequence: result.sequence ?? [],
          journeyCount: result.journeyCount,
          journeyDate: result.startDate,
          journeyEndDate: result.endDate,
          journeyMeta1: result.meta1,
          journeyMeta2: result.meta2,
          journeyMeta3: result.meta3,
        })
      } catch (error) {
        set({
          errorMessage: error instanceof ApiError ? error.message : String(error),
        })
      } finally {
        set({ isLoading: false })
      }
    },

    setJourneySwimlane: (on: boolean) => set({ journeySwimlane: on }),

    // ── node actions & step editor ────────────────────────────────────────

    handleNodeAction: (node, action) => {
      const s = get()
      if (action === 'include') {
        set({
          includedSteps: Array.from(new Set([...s.includedSteps, node])),
          excludedSteps: s.excludedSteps.filter((x) => x !== node),
        })
      } else {
        set({
          excludedSteps: Array.from(new Set([...s.excludedSteps, node])),
          includedSteps: s.includedSteps.filter((x) => x !== node),
        })
      }
      void get().reloadGraph()
    },

    handleMetaAction: (col, value, action) => {
      if (col < 0 || col > 2) return
      const mf = metaFiltersOf(get().metaFilters)
      const included = mf.included.map((l) => [...l]) as [string[], string[], string[]]
      const excluded = mf.excluded.map((l) => [...l]) as [string[], string[], string[]]
      const already = (action === 'include' ? included : excluded)[col].includes(value)
      // Toggle: clicking the active side again clears it; otherwise set that side and
      // drop the value from the opposite side (a value is included OR excluded, not both).
      included[col] = included[col].filter((v) => v !== value)
      excluded[col] = excluded[col].filter((v) => v !== value)
      if (!already) (action === 'include' ? included : excluded)[col].push(value)
      set({ metaFilters: { included, excluded } })
      void get().reloadGraph()
    },

    clearMetaFilters: () => {
      set({ metaFilters: emptyMetaFilters() })
      void get().reloadGraph()
    },

    openMetaInfo: (node) => set({ metaInfoOpen: true, metaInfoNode: node }),
    closeMetaInfo: () => set({ metaInfoOpen: false }),

    updateStep: async (step, payload) => {
      const s = get()
      if (!s.selectedProject) return
      set({ errorMessage: null })
      try {
        const result = await api.updateStep(s.selectedProject.projectId, step, payload)
        set({
          allStepInfos: result.allStepInfos,
          scoreBoundsMin: result.scoreBoundsMin,
          scoreBoundsMax: result.scoreBoundsMax,
          minScoreFilter: result.scoreBoundsMin,
          maxScoreFilter: result.scoreBoundsMax,
        })
        await get().reloadGraph()
      } catch (error) {
        set({
          errorMessage: error instanceof ApiError ? error.message : String(error),
        })
      }
    },

    // ── filter presets ────────────────────────────────────────────────────

    createFilterGroup: (name) => {
      const s = get()
      const group: FilterGroup = {
        id: uuid(),
        name: name || `Preset ${s.filterGroups.length + 1}`,
        fromDate: s.fromDate,
        toDate: s.toDate,
        includedSteps: s.includedSteps,
        excludedSteps: s.excludedSteps,
        ...metaFilterFields(metaFiltersOf(s.metaFilters)),
        meta1: s.meta1Filter,
        meta2: s.meta2Filter,
        meta3: s.meta3Filter,
        minSteps: s.minStepsFilter,
        maxSteps: s.maxStepsFilter,
        minJourneyTime: s.minJourneyTimeFilter,
        maxJourneyTime: s.maxJourneyTimeFilter,
        minScore: s.minScoreFilter,
        maxScore: s.maxScoreFilter,
      }
      set({
        filterGroups: [...s.filterGroups, group],
        selectedFilterGroupId: group.id,
      })
      saveFilterGroups()
    },

    deleteFilterGroup: (id) => {
      const s = get()
      set({
        filterGroups: s.filterGroups.filter((g) => g.id !== id),
        selectedFilterGroupId:
          s.selectedFilterGroupId === id ? null : s.selectedFilterGroupId,
      })
      saveFilterGroups()
    },

    renameFilterGroup: (id, name) => {
      set({
        filterGroups: get().filterGroups.map((g) =>
          g.id === id ? { ...g, name } : g,
        ),
      })
      saveFilterGroups()
    },

    applyFilterGroup: (group) => {
      set({
        selectedFilterGroupId: group.id,
        fromDate: toISODate(group.fromDate),
        toDate: toISODate(group.toDate),
        includedSteps: group.includedSteps,
        excludedSteps: group.excludedSteps,
        // Restore the preset's META value include/exclude lists (empty for older presets).
        metaFilters: metaFiltersFromFields(group),
        meta1Filter: group.meta1,
        meta2Filter: group.meta2,
        meta3Filter: group.meta3,
        minStepsFilter: group.minSteps,
        maxStepsFilter: group.maxSteps,
        minJourneyTimeFilter: group.minJourneyTime,
        maxJourneyTimeFilter: group.maxJourneyTime,
        minScoreFilter: group.minScore,
        maxScoreFilter: group.maxScore,
      })
    },

    // ── happy paths ───────────────────────────────────────────────────────

    createHappyPath: (name) => {
      const s = get()
      const path: HappyPath = {
        id: uuid(),
        name: name || `Happy Path ${s.happyPaths.length + 1}`,
        nodes: [],
      }
      set({ happyPaths: [...s.happyPaths, path], selectedHappyPathId: path.id })
      saveHappyPaths()
    },

    deleteHappyPath: (id) => {
      const s = get()
      const remaining = s.happyPaths.filter((p) => p.id !== id)
      set({
        happyPaths: remaining,
        selectedHappyPathId:
          s.selectedHappyPathId === id ? (remaining[0]?.id ?? null) : s.selectedHappyPathId,
      })
      saveHappyPaths()
    },

    renameHappyPath: (id, name) => {
      set({
        happyPaths: get().happyPaths.map((p) => (p.id === id ? { ...p, name } : p)),
      })
      saveHappyPaths()
    },

    updateHappyPath: (id, mutate) => {
      set({
        happyPaths: get().happyPaths.map((p) => (p.id === id ? mutate(p) : p)),
      })
      saveHappyPaths()
    },

    selectHappyPath: (id) => set({ selectedHappyPathId: id }),

    refreshHappyPathConformance: async () => {
      const s = get()
      if (!s.selectedProject || s.happyPaths.length === 0) {
        set({ happyPathScores: {} })
        return
      }
      try {
        const scores = await api.conformance(
          s.selectedProject.projectId,
          get().currentFilterSpec(),
          s.happyPaths,
        )
        set({ happyPathScores: scores })
      } catch {
        set({ happyPathScores: {} })
      }
    },

    // ── target norms ──────────────────────────────────────────────────────

    saveNorm: (edge, value) => {
      const s = get()
      if (!s.selectedProject) return
      const key = s.targetMetric
      const metricNorms = { ...(s.targetNorms[key] ?? {}) }
      if (value == null) delete metricNorms[edge]
      else metricNorms[edge] = value

      const norms = { ...s.targetNorms }
      if (Object.keys(metricNorms).length === 0) delete norms[key]
      else norms[key] = metricNorms

      set({ targetNorms: norms })
      writeJSON(projectKeys.norms(s.selectedProject.projectId), norms)
    },

    setTargetMetric: (metric) => {
      const s = get()
      if (!s.selectedProject) return
      set({ targetMetric: metric })
      writeJSON(projectKeys.normsMetric(s.selectedProject.projectId), metric)
    },

    // ── notes ─────────────────────────────────────────────────────────────

    loadNotes: async () => {
      const s = get()
      if (!s.selectedProject || !s.connection.isConnected) return
      try {
        set({ projectNotes: await api.listNotes(s.selectedProject.projectId) })
      } catch {
        set({ projectNotes: [] })
      }
    },

    saveNote: async (note) => {
      const s = get()
      if (!s.selectedProject) return
      try {
        const saved = await api.saveNote(s.selectedProject.projectId, note)
        const existing = s.projectNotes.findIndex((n) => n.id === saved.id)
        const notes = [...s.projectNotes]
        if (existing >= 0) notes[existing] = saved
        else notes.push(saved)
        set({ projectNotes: notes })
      } catch (error) {
        const message = error instanceof ApiError ? error.message : String(error)
        get().showAlert({
          title: 'Note Not Synced',
          message: `Note could not be written to the database: ${message}`,
          primaryLabel: 'OK',
        })
      }
    },

    updateNote: async (noteId, body) => {
      const s = get()
      if (!s.selectedProject) return
      try {
        const saved = await api.updateNote(s.selectedProject.projectId, noteId, body)
        const notes = s.projectNotes.map((n) => (n.id === saved.id ? saved : n))
        set({ projectNotes: notes })
      } catch (error) {
        const message = error instanceof ApiError ? error.message : String(error)
        get().showAlert({
          title: 'Note Not Synced',
          message: `Note could not be updated: ${message}`,
          primaryLabel: 'OK',
        })
      }
    },

    deleteNote: async (note) => {
      const s = get()
      if (!s.selectedProject) return
      set({ projectNotes: s.projectNotes.filter((n) => n.id !== note.id) })
      try {
        await api.deleteNote(s.selectedProject.projectId, note.id)
      } catch {
        /* already removed locally; the list refreshes on the next view switch */
      }
    },

    // ── sampling ──────────────────────────────────────────────────────────

    refreshSampleCounts: async () => {
      const s = get()
      if (!s.selectedProject) {
        set({ sampleCounts: {}, sampleMethods: {} })
        return
      }
      try {
        const { counts, methods } = await api.sampleCounts(s.selectedProject.projectId)
        set({ sampleCounts: counts, sampleMethods: methods })
      } catch {
        set({ sampleCounts: {} })
      }
    },

    createSample: async (sampleSet, count, method) => {
      const s = get()
      if (!s.selectedProject) return
      set({ isSampling: true, samplingError: null, samplingProgress: 'Preparing…' })
      try {
        set({ samplingProgress: `Writing ${count} journeys…` })
        const { counts } = await api.createSample(
          s.selectedProject.projectId,
          sampleSet,
          count,
          method,
        )
        set({
          sampleCounts: counts,
          sampleMethods: { ...s.sampleMethods, [sampleSet]: method },
        })
      } catch (error) {
        set({
          samplingError: error instanceof ApiError ? error.message : String(error),
        })
      } finally {
        set({ isSampling: false, samplingProgress: null })
      }
    },

    deleteSample: async (sampleSet) => {
      const s = get()
      if (!s.selectedProject) return
      set({ isSampling: true, samplingError: null })
      try {
        const { counts } = await api.deleteSample(s.selectedProject.projectId, sampleSet)
        const methods = { ...s.sampleMethods }
        delete methods[sampleSet]
        set({ sampleCounts: counts, sampleMethods: methods })

        let reloaded = false
        for (const side of ['a', 'b'] as ABSide[]) {
          if (activeSampleSet(side) === sampleSet) {
            writeSetting(
              side === 'a' ? 'sampling.activeSampleSetA' : 'sampling.activeSampleSetB',
              'ORIGINAL',
            )
            reloaded = true
          }
        }
        if (reloaded) await get().reloadGraph()
      } catch (error) {
        set({
          samplingError: error instanceof ApiError ? error.message : String(error),
        })
      } finally {
        set({ isSampling: false })
      }
    },

    switchSampleSet: async (side, sampleSet) => {
      if (activeSampleSet(side) === sampleSet) return
      writeSetting(
        side === 'a' ? 'sampling.activeSampleSetA' : 'sampling.activeSampleSetB',
        sampleSet,
      )
      set(
        side === 'a'
          ? { abDataSourceA: { kind: 'sampleSet', sampleSet } }
          : { abDataSourceB: { kind: 'sampleSet', sampleSet } },
      )
      const s = get()
      if (!s.selectedProject) return

      if (s.activeChartMode === 'A/B Comparison') {
        const [from, to] = datesForABSide(side)
        await get().reloadABSide(side, from, to)
      } else if (
        (side === 'a' && s.activeChartMode !== 'B-Chart') ||
        (side === 'b' && s.activeChartMode === 'B-Chart')
      ) {
        await get().reloadGraph()
      }
    },

    setABDataSource: async (side, source) => {
      set(side === 'a' ? { abDataSourceA: source } : { abDataSourceB: source })
      if (source.kind === 'simulation') {
        applySimulationToABSide(side)
        return
      }
      await get().switchSampleSet(side, source.sampleSet)
    },

    // ── simulation ────────────────────────────────────────────────────────

    runSimulation: async (slot, config) => {
      const s = get()
      const baseGraph =
        s.savedChartStates['A-Chart']?.processGraph ?? s.processGraph
      if (baseGraph.transitions.length === 0) {
        set({ simulationError: 'Load the A-Chart first — simulation needs a process graph.' })
        return
      }
      set({ isSimulating: true, simulationError: null })
      try {
        const result = await api.simulate(baseGraph, s.allStepInfos, {
          journeyCount: config.journeyCount,
          startDate: config.startDate,
          avgInterArrivalHours: config.avgInterArrivalHours,
          excludedSteps: config.excludedSteps,
          requiredSteps: config.requiredSteps,
          maxStepsPerJourney: config.maxStepsPerJourney,
        })
        set(slot === 'Sim-A' ? { simResultA: result } : { simResultB: result })

        // Refresh any A/B side already displaying this slot.
        const after = get()
        if (
          after.abDataSourceA.kind === 'simulation' &&
          after.abDataSourceA.slot === slot
        ) {
          applySimulationToABSide('a')
        }
        if (
          after.abDataSourceB.kind === 'simulation' &&
          after.abDataSourceB.slot === slot
        ) {
          applySimulationToABSide('b')
        }
      } catch (error) {
        set({
          simulationError: error instanceof ApiError ? error.message : String(error),
        })
      } finally {
        set({ isSimulating: false })
      }
    },

    // ── AI documentation ──────────────────────────────────────────────────

    setLLMPromptTemplate: (template) => {
      const s = get()
      set({ llmPromptTemplate: template })
      if (s.selectedProject) {
        writeJSON(projectKeys.llmPrompt(s.selectedProject.projectId), template)
      }
    },

    runLLMAnalysis: async () => {
      const s = get()
      if (!s.selectedProject) return
      set({ isLLMAnalyzing: true, llmAnalysis: null, llmAnalysisError: null })
      try {
        // Pull the latest notes so the report's Notes chapter is current even if the
        // user never opened the Notes view this session.
        await get().loadNotes()
        // Analysis always uses A-Chart data as the reference dataset.
        const graph = s.savedChartStates['A-Chart']?.processGraph ?? s.processGraph
        // The process diagram embedded in the report is the same Sankey the app draws,
        // rendered to a standalone SVG (concrete colours) so it survives into the print doc.
        const sankeySvg = sankeySvgString(graph, s.transitionMetric, s.journeyCount ?? 0)
        const response = await api.documentation(s.selectedProject.projectId, {
          projectTitle: s.selectedProject.title,
          filter: get().currentFilterSpec(),
          graph,
          promptTemplate: s.llmPromptTemplate,
          targetNorms: s.targetNorms,
          targetMetric: s.targetMetric,
          // The report's gap analysis judges norms the same way the Conformance
          // view currently does (ceiling by default, floor when toggled).
          normIsMinimum: readSetting<boolean>('compliance.normIsMinimum'),
          happyPaths: s.happyPaths,
          notes: s.projectNotes,
          connectionId: s.connection.activeProfileId ?? '',
          sankeySvg,
          sankeyCaption: `Reconstructed process flow — band width shows ${s.transitionMetric}; looping steps are collapsed into single ↺ nodes.`,
          preparedFor: s.authDisplayName || s.authUser || '',
        })
        set({ llmAnalysis: response, llmAnalysisError: response.error })
      } catch (error) {
        set({
          llmAnalysisError: error instanceof ApiError ? error.message : String(error),
        })
      } finally {
        set({ isLLMAnalyzing: false })
      }
    },
  }
})

/** Single-line summary of the A-Chart window, journey count and active filters. */
export function aChartFilterSummary(state: AppState): string {
  const s = state.savedChartStates['A-Chart']
  if (!s) return `${state.fromDate} – ${state.toDate}`
  const parts = [`${s.fromDate} – ${s.toDate}`]
  if (s.journeyCount != null) parts.push(`${s.journeyCount.toLocaleString()} journeys`)
  if (s.includedSteps.length) parts.push(`include: ${[...s.includedSteps].sort().join(', ')}`)
  if (s.excludedSteps.length) parts.push(`exclude: ${[...s.excludedSteps].sort().join(', ')}`)
  for (const m of [s.meta1Filter, s.meta2Filter, s.meta3Filter]) if (m) parts.push(m)
  const mf = metaFiltersOf(s.metaFilters)
  for (let c = 0; c < 3; c++) {
    if (mf.included[c].length) parts.push(`M${c + 1} include: ${[...mf.included[c]].sort().join(', ')}`)
    if (mf.excluded[c].length) parts.push(`M${c + 1} exclude: ${[...mf.excluded[c]].sort().join(', ')}`)
  }
  return parts.join(' · ')
}

export { addDays }
