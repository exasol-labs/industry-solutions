/** TypeScript mirrors of the backend pydantic models (which mirror Models.swift). */

export const INT_MAX = 9223372036854775807
export const INT_MIN = -9223372036854775808

export interface ConnectionStatus {
  isConnected: boolean
  isLLMReachable: boolean
  activeProfileId: string | null
  username: string
  lastError: string | null
}

/** A connection assigned to the signed-in user by an administrator. Read-only:
 * the definition (and all secrets) lives in the admin interface. Mirrors the
 * backend's `Connection.user_public()`. */
export interface AssignedConnection {
  id: string
  name: string
  comment: string
  host: string
  port: number
  schema: string
  hasLLM: boolean
  llmURL: string | null
  /** True when this connection's schema holds aggregate (Σ) projects (high-level or detail). */
  hasAggregates?: boolean
  /** True when it holds only aggregate DETAIL projects (not a source or high-level) — so it
   *  may be hidden by the "show aggregate connections" setting. */
  aggregateDetailOnly?: boolean
}

/** A connection a *power* user owns and may edit from the app (admin_public shape;
 * secrets are represented by the hasPassword / hasLLMKey flags, never values). */
export interface ManagedConnection {
  id: string
  name: string
  comment: string
  host: string
  port: number
  username: string
  schema: string
  useTLS: boolean
  certModeRaw: string
  fingerprint: string
  minRSAKeySizeBits: number
  hasPassword: boolean
  llmURL: string
  llmModel: string
  hasLLMKey: boolean
  assignments: string[]
  owner: string
}

/** One project stored in a connection's schema, with its journey/event counts. */
export interface ConnectionProject {
  projectId: number
  titleShort: string
  title: string
  journeys: number
  events: number
}

export interface ConnectionProjectsResult {
  ok: boolean
  error: string | null
  projects: ConnectionProject[]
}

export interface ConnectionProjectDeleteResult {
  ok: boolean
  error?: string | null
  events?: number
  journeys?: number
  tables?: string[]
}

export interface Project {
  projectId: number
  title: string
  description: string
  titleShort: string
}

export interface StepInfo {
  step: string
  description: string
  bgColor: string
  fgColor: string
  score: number | null
  shape: string
  endOfProcess: boolean
  belongsTo: string | null
  eventTime: string | null
}

export interface ProcessTransition {
  fromStep: string
  toStep: string
  occurrences: number
  avgSecs: number | null
  medianSecs: number | null
  minSecs: number | null
  maxSecs: number | null
  stdDevSecs: number | null
}

export interface ProcessGraph {
  steps: Record<string, StepInfo>
  transitions: ProcessTransition[]
}

export const EMPTY_GRAPH: ProcessGraph = { steps: {}, transitions: [] }

export interface JourneyPath {
  path: string
  journeyCount: number
  stepCount: number
  totalScore: number
}

/** One event of a single journey, in time order — the raw trace the swimlane view lays
 *  out sequentially (a revisited step appears again; loops are unrolled by construction). */
export interface JourneyEvent {
  step: string
  eventTime: string
}

/** One META value on a node's events (Meta Infos panel): the value, the date/time it was
 *  last seen (``YYYY-MM-DD HH:MM:SS``, empty when unknown), and its occurrence count. */
export interface MetaEntry {
  value: string
  time: string
  count: number
}

export interface DurationBucket {
  label: string
  count: number
}

export interface JourneyTimePoint {
  date: string
  count: number
}

export interface DurationStats {
  minSecs: number | null
  avgSecs: number | null
  medianSecs: number | null
  stdDevSecs: number | null
  maxSecs: number | null
}

export const TRANSITION_METRICS = [
  'Count',
  'Percentage',
  'Journey %',
  'Avg Time',
  'Median Time',
  'Min Time',
  'Max Time',
  'Std Dev',
] as const
export type TransitionMetric = (typeof TRANSITION_METRICS)[number]

/** The two share metrics: 'Percentage' is the branching share of a node's OUTGOING
 *  journeys (each node's out-edges sum to 100 %); 'Journey %' is the share of ALL filtered
 *  journeys that traverse the edge. Both are 0–100 (Journey % can exceed 100 for an edge a
 *  journey repeats). Neither is time-based, and neither reads off a single transition. */
export function isPercentMetric(metric: TransitionMetric): boolean {
  return metric === 'Percentage' || metric === 'Journey %'
}

export function isTimeBased(metric: TransitionMetric): boolean {
  return metric !== 'Count' && !isPercentMetric(metric)
}

/** 'Percentage' is the share of journeys leaving a node that take this edge — a value
 *  relative to the SOURCE node's total outgoing occurrences, so it can't be read from a
 *  single transition. Callers that render it (the edge, conformance) compute it from the
 *  source's outgoing total; here it is null so the plain single-transition path skips it. */
export function metricValue(
  t: ProcessTransition,
  metric: TransitionMetric,
): number | null {
  switch (metric) {
    case 'Count':
      return t.occurrences
    case 'Percentage':
    case 'Journey %':
      return null
    case 'Avg Time':
      return t.avgSecs
    case 'Median Time':
      return t.medianSecs
    case 'Min Time':
      return t.minSecs
    case 'Max Time':
      return t.maxSecs
    case 'Std Dev':
      return t.stdDevSecs
  }
}

export function maxMetricValue(
  graph: ProcessGraph,
  metric: TransitionMetric,
): number {
  // Percentages are drawn on a fixed 0–100 scale.
  if (isPercentMetric(metric)) return 100
  let max = -Infinity
  for (const t of graph.transitions) {
    const v = metricValue(t, metric)
    if (v != null && v > max) max = v
  }
  return max === -Infinity ? 1 : max
}

/** The share (0–100) of the source node's outgoing journeys that take this transition.
 *  ``outgoingTotal`` is the sum of occurrences of every edge leaving ``t.fromStep``. */
export function outgoingPercentage(t: ProcessTransition, outgoingTotal: number): number {
  return outgoingTotal > 0 ? (t.occurrences / outgoingTotal) * 100 : 0
}

/** The share of ALL filtered journeys that traverse this transition. ``journeyTotal`` is
 *  the filtered journey count; the result can exceed 100 % for an edge a journey repeats. */
export function journeyPercentage(t: ProcessTransition, journeyTotal: number): number {
  return journeyTotal > 0 ? (t.occurrences / journeyTotal) * 100 : 0
}

export const SAMPLE_SETS = ['ORIGINAL', 'SAMPLE_1', 'SAMPLE_2', 'SAMPLE_3'] as const
export type SampleSet = (typeof SAMPLE_SETS)[number]

export function sampleLabel(set: SampleSet): string {
  return {
    ORIGINAL: 'Original Data',
    SAMPLE_1: 'Sample Set 1',
    SAMPLE_2: 'Sample Set 2',
    SAMPLE_3: 'Sample Set 3',
  }[set]
}

export function sampleShortLabel(set: SampleSet): string {
  return {
    ORIGINAL: 'Original',
    SAMPLE_1: 'Sample 1',
    SAMPLE_2: 'Sample 2',
    SAMPLE_3: 'Sample 3',
  }[set]
}

export type SamplingMethod = 'random' | 'temporal' | 'pathDiverse'

export const SAMPLING_METHODS: {
  id: SamplingMethod
  label: string
  icon: string
  description: string
}[] = [
  {
    id: 'random',
    label: 'Random',
    icon: '🔀',
    description: 'Uniform random selection',
  },
  {
    id: 'temporal',
    label: 'Temporal Stratified',
    icon: '📅',
    description: 'Proportional across time periods',
  },
  {
    id: 'pathDiverse',
    label: 'Path Diversity',
    icon: '🌿',
    description: 'Coverage across journey variants',
  },
]

export const DETAIL_VIEW_MODES = [
  'A-Chart',
  'B-Chart',
  'A/B Comparison',
  'Individual Journey',
  'AI supported Documentation',
  'Statistics',
  'Conformance Check',
  'Happy Path',
  'Notes',
  'Simulation',
] as const
export type DetailViewMode = (typeof DETAIL_VIEW_MODES)[number]

export const VIEW_MODE_ICONS: Record<DetailViewMode, string> = {
  'A-Chart': '📈',
  'B-Chart': '📉',
  'A/B Comparison': '⇄',
  'Individual Journey': '🧍',
  'AI supported Documentation': '🧠',
  Statistics: '📊',
  'Conformance Check': '🛡️',
  'Happy Path': '🪧',
  Notes: '🗒️',
  Simulation: '🎲',
}

export type SliderMode = 'Range' | 'Day'
export type GraphStartMode = 'expanded' | 'collapsed' | 'persisted'

export interface FilterSpec {
  fromDate: string | null
  toDate: string | null
  includedSteps: string[]
  excludedSteps: string[]
  meta1: string
  meta2: string
  meta3: string
  // List-based META value include/exclude (optional; backend defaults to empty lists).
  includedMeta1?: string[]
  excludedMeta1?: string[]
  includedMeta2?: string[]
  excludedMeta2?: string[]
  includedMeta3?: string[]
  excludedMeta3?: string[]
  minSteps: number
  maxSteps: number
  minJourneyTime: number
  maxJourneyTime: number
  minScore: number
  maxScore: number
  sampleSet: SampleSet
}

export interface FilterGroup {
  id: string
  name: string
  fromDate: string
  toDate: string
  includedSteps: string[]
  excludedSteps: string[]
  meta1: string
  meta2: string
  meta3: string
  // List-based META value include/exclude (optional — older stored presets omit them).
  includedMeta1?: string[]
  excludedMeta1?: string[]
  includedMeta2?: string[]
  excludedMeta2?: string[]
  includedMeta3?: string[]
  excludedMeta3?: string[]
  minSteps: number
  maxSteps: number
  minJourneyTime: number
  maxJourneyTime: number
  minScore: number
  maxScore: number
}

/** One node in a Happy Path's series-parallel sequence. A node is a single STEP
 *  when `branches` is empty (and `step` is set), or a SPLIT when `branches` is
 *  non-empty — each inner list is one alternative sub-path (itself a node list,
 *  hence nesting). Steps following a split node in the same list are the shared
 *  "after-rejoin" continuation. */
export interface HappyPathNode {
  id: string
  step: string
  label: string
  /** Name of the point where a split's branches rejoin (splits only; optional). */
  rejoinLabel?: string
  branches: HappyPathNode[][]
}

export interface HappyPath {
  id: string
  name: string
  nodes: HappyPathNode[]
}

/** The legacy flat shape (trunk + one level of branches) for migration on load. */
export interface LegacyHappyPath {
  id: string
  name: string
  steps?: string[]
  branches?: { id?: string; label?: string; steps: string[] }[]
  nodes?: HappyPathNode[]
}

export interface FilterSnapshot {
  fromDate: string
  toDate: string
  includedSteps: string[]
  excludedSteps: string[]
  meta1: string
  meta2: string
  meta3: string
  minSteps: number
  maxSteps: number
  minJourneyTime: number
  maxJourneyTime: number
  minScore: number
  maxScore: number
}

export interface NoteTarget {
  type: 'node' | 'edge'
  value?: string | null
  from?: string | null
  to?: string | null
}

export interface ProcessNote {
  id: string
  title: string
  text: string
  createdAt: string
  editedAt: string | null
  target: NoteTarget
  filterSnapshot: FilterSnapshot
  username: string
  lastEditedBy: string
  isShared: boolean
  importance: NoteImportance
  resolved: boolean
  // Display labels resolved by the backend: an LDAP user's real name (cn),
  // otherwise the login username. May be absent on locally-constructed notes.
  authorName?: string
  lastEditedByName?: string
}

export type NoteImportance = 'NORMAL' | 'INFO' | 'IMPORTANT' | 'URGENT'

// Ordered lowest → highest; NORMAL is the default.
export const NOTE_IMPORTANCE_LEVELS: NoteImportance[] = [
  'NORMAL',
  'INFO',
  'IMPORTANT',
  'URGENT',
]

// Badge presentation per level. NORMAL is intentionally muted (no loud badge).
export const NOTE_IMPORTANCE_META: Record<
  NoteImportance,
  { label: string; glyph: string; color: string; bg: string }
> = {
  NORMAL: { label: 'Normal', glyph: '•', color: 'var(--tertiary)', bg: 'transparent' },
  INFO: { label: 'Info', glyph: 'ℹ', color: 'var(--blue)', bg: 'rgba(10,132,255,0.14)' },
  IMPORTANT: {
    label: 'Important',
    glyph: '★',
    color: 'var(--orange)',
    bg: 'rgba(255,159,10,0.16)',
  },
  URGENT: { label: 'Urgent', glyph: '⚠', color: 'var(--red)', bg: 'rgba(255,59,48,0.16)' },
}

export function normalizeImportance(value: unknown): NoteImportance {
  return NOTE_IMPORTANCE_LEVELS.includes(value as NoteImportance)
    ? (value as NoteImportance)
    : 'NORMAL'
}

export function noteTargetKey(target: NoteTarget): string {
  return target.type === 'edge'
    ? `edge:${target.from}->${target.to}`
    : `node:${target.value}`
}

export function noteTargetLabel(target: NoteTarget): string {
  return target.type === 'edge'
    ? `${target.from} → ${target.to}`
    : (target.value ?? '')
}

// 'materialized' = read from TRANSITIONS_RAW; 'live' = computed on the fly;
// 'fallback' = materialized is enabled but the table isn't built, so it's
// running live meanwhile (a rebuild is pending).
export type TransitionsMode = 'materialized' | 'live' | 'fallback'

export interface GraphResult {
  processGraph: ProcessGraph
  journeyCount: number | null
  durations: DurationStats
  processGoodness: number | null
  transitionsMode: TransitionsMode | null
  queryMs: number | null
  variants: JourneyPath[]
}

export interface ProjectBootstrap {
  project: Project
  allSteps: string[]
  allStepInfos: Record<string, StepInfo>
  meta1Title: string | null
  meta2Title: string | null
  meta3Title: string | null
  meta1Values: string[]
  meta2Values: string[]
  meta3Values: string[]
  totalJourneyCount: number | null
  minDate: string | null
  maxDate: string | null
  initialFromDate: string | null
  initialToDate: string | null
  stepCountMin: number
  stepCountMax: number
  journeyTimeBoundsMin: number
  journeyTimeBoundsMax: number
  scoreBoundsMin: number
  scoreBoundsMax: number
  sampleCounts: Record<string, number>
  sampleMethods: Record<string, SamplingMethod>
}

export interface StatisticsResponse {
  paths: JourneyPath[]
  durationBuckets: DurationBucket[]
  timeSeries: JourneyTimePoint[]
  timeGranularity: 'day' | 'week' | 'month'
  processGraph: ProcessGraph
  journeyCount: number | null
  totalJourneyCount: number | null
  durations: DurationStats
  isTruncated: boolean
}

export interface SimulationConfig {
  journeyCount: number
  startDate: string
  avgInterArrivalHours: number
  excludedSteps: string[]
  requiredSteps: string[]
  maxStepsPerJourney: number
}

export interface SimulatedEvent {
  journeyId: string
  step: string
  timestamp: string
}

export interface SimulationVariant {
  path: string
  count: number
  percentage: number
  avgCycleTimeSecs: number
}

export interface SimulationResult {
  runId: string
  events: SimulatedEvent[]
  variants: SimulationVariant[]
  cycleTimes: number[]
  simProcessGraph: ProcessGraph
  totalJourneys: number
  avgCycleTimeSecs: number
  minCycleTimeSecs: number
  maxCycleTimeSecs: number
  stdDevCycleTimeSecs: number
}

export type SimSlot = 'Sim-A' | 'Sim-B'

export type ABDataSource =
  | { kind: 'sampleSet'; sampleSet: SampleSet }
  | { kind: 'simulation'; slot: SimSlot }

export function abDataSourceLabel(source: ABDataSource): string {
  return source.kind === 'sampleSet'
    ? sampleShortLabel(source.sampleSet)
    : source.slot
}

/** Red canvas notice when a side shows simulation output — simulations are a
 *  read-only what-if result and cannot drive interactive filtering / drill-down. */
export function simulationFilterNotice(source: ABDataSource): string | null {
  return source.kind === 'simulation'
    ? `${source.slot}: simulation data is read-only — interactive filtering, drill-down and step editing are not available.`
    : null
}

export interface DocumentationResponse {
  /** The full, self-contained styled HTML report (Python-assembled). Null on LLM error. */
  reportHtml: string | null
  /** The structured findings the analysis LLM returned (for reference/debug). */
  findings: unknown | null
  error: string | null
  prompt: string
  model: string | null
  generatedAt: string
  // Retained while the client migrates off the old client-side stitching.
  journeyPathsSummary: string
  conformanceSummary: string
  happyPathSummary: string
}

export const KPI_DEFAULT_ORDER =
  'totalJourneys,filteredJourneys,shortestJourney,avgJourney,medianJourney,stdDev,longestJourney,graphValue,processGoodness,processSimilarity,activeSample'

export const KPI_META: Record<string, { label: string; icon: string }> = {
  totalJourneys: { label: 'Total Journeys', icon: '👥' },
  filteredJourneys: { label: 'Filtered Journeys', icon: '⛃' },
  shortestJourney: { label: 'Shortest Journey', icon: '🐇' },
  avgJourney: { label: 'Avg Journey', icon: '⏱️' },
  medianJourney: { label: 'Median Journey', icon: '◑' },
  stdDev: { label: 'Std Dev', icon: '〰️' },
  longestJourney: { label: 'Longest Journey', icon: '🐢' },
  graphValue: { label: 'Graph Value', icon: 'ƒ' },
  processGoodness: { label: 'Process Goodness', icon: '◔' },
  processSimilarity: { label: 'Process Similarity', icon: '⇄' },
  activeSample: { label: 'Active Sample', icon: '▤' },
}

// ── Integration abstraction layer ─────────────────────────────────────────────

export interface ExtractorInfo {
  id: string
  name: string
  version: string
  description: string
}

export interface IntegrationStatus {
  state: 'idle' | 'running' | 'completed' | 'failed'
  /** What started the run: a console ▷ Run, or the background file watchdog. */
  trigger: 'manual' | 'watchdog' | ''
  extractorId: string | null
  extractorName: string | null
  sourceName: string | null
  sourceTypeName: string | null
  connectionId: string | null
  connectionName: string | null
  schema: string | null
  recordsPushed: number
  /** Journey EVENTS produced vs. source items that could not be parsed (unlike
   *  recordsPushed, which also counts the project/step/meta rows). */
  eventsWritten: number
  eventsSkipped: number
  recordsDone: number
  recordsTotal: number
  tablesTouched: string[]
  startedAt: string | null
  finishedAt: string | null
  lastError: string | null
  messages: string[]
  registeredExtractors: number
  activeConnectionId: string | null
  activeSchema: string | null
  connected: boolean
  /** File sources with the watchdog switched on, out of all file sources. */
  watchdogsActive: number
  watchdogsTotal: number
  /** False when the whole watchdog loop is disabled for the deployment, in which case
   *  an "on" watchdog still never polls. */
  watchdogEnabled: boolean
}

/** One API Server - Event Receiver in the live monitor: its config, whether its listener
 *  answered a localhost /health probe, and the destination-DB counts for its project. */
export interface SinkMonitorEntry {
  id: string
  name: string
  port: number
  activeScheme: string
  titleShort: string
  connectionId: string
  connectionName: string | null
  schema: string | null
  /** The sink's /health answered 200 on its live listener (true per-port liveness). */
  live: boolean
  /** Destination-DB counts for the sink's project (null when the DB couldn't be read). */
  events: number | null
  journeys: number | null
  lastEventAt: string | null
  /** Per-sink problem (connection not assigned, DB unreachable, …); null when fine. */
  error: string | null
}

export interface SinkMonitor {
  /** The API Server - Event Receiver module is switched on in the admin interface. */
  moduleEnabled: boolean
  /** The sink supervisor process is running (its PID file exists). */
  supervisorRunning: boolean
  sinks: SinkMonitorEntry[]
}

/** One process (project) shown as a tile on the end-user launch page (/home). */
export interface PortalProcess {
  projectId: number
  title: string
  titleShort: string
  journeys: number
  events: number
  lastEventAt: string | null
}

/** The processes available to the user in one connection, for the launch page. */
export interface PortalConnection {
  id: string
  name: string
  schema: string | null
  /** Set when the connection's schema couldn't be read (its tile group shows the note). */
  error: string | null
  projects: PortalProcess[]
}

/** "aux" is a helper field: extracted like the others but written to no column — it
 *  exists so a compound-step rule can match on a value (an HTTP status, a result code)
 *  that doesn't belong in META. */
export type ExtractionRole = 'timestamp' | 'id' | 'step' | 'meta' | 'aux'

// A source type's data format: unstructured text (regex per line) or semi-structured
// JSON / XML (a path selector per field). Existing specs have no format → 'text'.
export type DataFormat = 'text' | 'json' | 'xml'

export interface ExtractionField {
  id?: string
  name: string
  role: ExtractionRole
  // Text sources capture with `regex`; JSON/XML sources locate with `path`.
  regex: string
  path?: string
  format?: string
  title?: string
}

/** One test in a compound-step rule: a named field compared against a value. */
export interface CompoundCondition {
  field: string
  op: CompoundOp
  value: string
}

export const COMPOUND_OPS = ['eq', 'ne', 'contains', 'startswith', 'endswith', 'regex'] as const
export type CompoundOp = (typeof COMPOUND_OPS)[number]

export const COMPOUND_OP_LABEL: Record<CompoundOp, string> = {
  eq: 'is',
  ne: 'is not',
  contains: 'contains',
  startswith: 'starts with',
  endswith: 'ends with',
  regex: 'matches regex',
}

/** Derive the final STEP from several fields at once. All conditions must hold; the
 *  first matching rule wins; if none match the plain step value is used. Optional. */
export interface CompoundRule {
  id?: string
  step: string
  when: CompoundCondition[]
}

export interface SourceType {
  id: string
  owner: string
  name: string
  sample: string
  format?: DataFormat
  recordPath?: string
  fields: ExtractionField[]
  compound?: CompoundRule[]
  createdAt: string
}

export interface SourceTypeInput {
  name: string
  sample: string
  format?: DataFormat
  recordPath?: string
  fields: ExtractionField[]
}

export interface Source {
  id: string
  owner: string
  name: string
  kind: string
  config: Record<string, unknown>
  createdAt: string
}

export interface SourceInput {
  name: string
  kind: string
  config: Record<string, unknown>
}

/** Optional watchdog on a File source: auto-import newly-appended lines when the file
 *  grows, into a stored connection + project (stored in the source's config.watchdog). */
export interface WatchdogConfig {
  enabled: boolean
  connectionId: string
  projectId: string
  intervalSecs: number
}

/** The watchdog's read checkpoint for a source file. */
export interface SourceCheckpoint {
  byteOffset: number
  size: number
  signature: string
  records: number
  updatedAt: string | null
  lastError: string | null
}

// A file in the sandboxed sources directory, for the source-type wizard's file picker.
export interface IntegrationFile {
  name: string // path relative to the sandbox root
  size: number
  modified: number // unix seconds
}

// A candidate record delimiter with how many times it separates records in the sample.
export interface DelimiterCandidate {
  id: string // crlf | lf | cr | ff | rs | nul | blank
  label: string
  count: number
}

// Result of detecting a file's record delimiter and splitting its head into records.
export interface RecordDetection {
  delimiter: string
  candidates: DelimiterCandidate[]
  records: string[]
  truncated: boolean
  encoding: string
}

// A field suggested by structure detection: its safe name, guessed role, path selector
// and the value that path resolved to in the first record.
export interface SuggestedField {
  name: string
  role: ExtractionRole
  path: string
  sample: string
  format?: string
}

// Result of detecting a file's data format (text / JSON / XML). For JSON/XML the records
// are rendered (pretty JSON / XML element) and `fields` carries path suggestions; for
// text it also carries the RecordDetection delimiter fields.
export interface StructureDetection {
  format: DataFormat
  shape?: 'array' | 'object' | 'jsonl'
  recordPath?: string
  records: string[]
  fields: SuggestedField[]
  truncated?: boolean
  encoding?: string
  // present only for text (delegates to RecordDetection)
  delimiter?: string
  candidates?: DelimiterCandidate[]
}
