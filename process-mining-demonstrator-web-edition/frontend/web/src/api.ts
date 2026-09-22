/** Thin typed wrapper over the compute-backend REST API. */

import type {
  AssignedConnection,
  ConnectionProjectsResult,
  ConnectionProjectDeleteResult,
  ConnectionStatus,
  ManagedConnection,
  DocumentationResponse,
  FilterSpec,
  GraphResult,
  HappyPath,
  JourneyEvent,
  JourneyPath,
  MetaEntry,
  ProcessGraph,
  ProcessNote,
  Project,
  ProjectBootstrap,
  ExtractionField,
  ExtractorInfo,
  IntegrationFile,
  IntegrationStatus,
  RecordDetection,
  SampleSet,
  PortalConnection,
  SinkMonitor,
  Source,
  SourceCheckpoint,
  SourceInput,
  SourceType,
  SourceTypeInput,
  StructureDetection,
  SamplingMethod,
  SimulationConfig,
  SimulationResult,
  StatisticsResponse,
  StepInfo,
  TransitionMetric,
} from './types'
import type { LoginAppearance } from './loginAppearance'
import type { ActionRunResult, ActionSpec, SavedAction } from './actions/types'
import type {
  AddAggregatesBody,
  AggregateLink,
  AggregateSetResult,
  CreateAggregateBody,
  CreateAggregateResult,
  CreateAggregateSetBody,
} from './aggregate/types'

/** The signed-in user payload returned by password, passkey and MFA sign-in. */
export interface AuthUser {
  username: string
  isAdmin: boolean
  isPower: boolean
  isDeveloper: boolean
  displayName: string | null
  authSource: string | null
  passkeyAllowed: boolean
  mfaAllowed: boolean
  mfaEnabled: boolean
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(path, {
      ...init,
      headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
    })
  } catch {
    throw new ApiError('The server is not reachable.', 0)
  }
  if (!response.ok) {
    let detail = `HTTP ${response.status}`
    try {
      const body = await response.json()
      if (typeof body?.detail === 'string') detail = body.detail
    } catch {
      /* non-JSON error body — keep the status text */
    }
    throw new ApiError(detail, response.status)
  }
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

const get = <T>(path: string) => request<T>(path)
const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: 'POST', body: JSON.stringify(body ?? {}) })
const put = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: 'PUT', body: JSON.stringify(body ?? {}) })
const patch = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: 'PATCH', body: JSON.stringify(body ?? {}) })
const del = <T>(path: string) => request<T>(path, { method: 'DELETE' })

const enc = encodeURIComponent

export const api = {
  // ── authentication ─────────────────────────────────────────────────────────
  session: () =>
    get<{
      authenticated: boolean
      username: string | null
      isAdmin: boolean
      isPower: boolean
      isDeveloper: boolean
      displayName: string | null
      authSource: string | null
      requireLogin: boolean
      idleTimeoutMins: number
      actionsEnabled: boolean
      passkeyAllowed: boolean
      mfaAllowed: boolean
      mfaEnabled: boolean
    }>('/auth/session'),
  // A password login either signs the user in, asks for a second factor, or —
  // when 2FA is required but not yet set up — asks the user to enrol it first.
  login: (username: string, password: string) =>
    post<
      | AuthUser
      | { mfaRequired: true; username: string }
      | { mfaSetupRequired: true; username: string }
    >('/auth/login', { username, password }),
  // Step 2: submit the TOTP (or recovery) code after a password login that
  // returned mfaRequired.
  verifyMfa: (code: string) => post<AuthUser>('/auth/mfa/verify', { code }),
  // Mandatory enrolment when 2FA is required but not configured (pre-session).
  mfaEnrollBegin: () =>
    post<{ secret: string; otpauthUri: string; qrSvg: string }>('/auth/mfa/enroll/begin'),
  mfaEnrollFinish: (code: string) =>
    post<AuthUser & { recoveryCodes: string[] }>('/auth/mfa/enroll/finish', { code }),
  logout: () => post<{ ok: boolean }>('/auth/logout'),
  // Directory (LDAP) availability for the login panel; configured=false ⇒ show nothing.
  directoryStatus: () =>
    get<{ configured: boolean; available: boolean }>('/auth/directory-status'),
  // Demo-mode / license state for the login panel; demoMode=false ⇒ show nothing.
  licenseStatus: () =>
    get<{
      state: string
      demoMode: boolean
      remainingSeconds: number | null
    }>('/auth/license-status'),
  // Login-page background chosen in the admin Customize tab (pre-auth).
  loginAppearance: () => get<LoginAppearance>('/auth/login-appearance'),

  // ── connections ──────────────────────────────────────────────────────────
  // Admin-defined connections assigned to the signed-in user.
  listConnections: () => get<AssignedConnection[]>('/api/connections'),
  connectConnection: (id: string) =>
    post<ConnectionStatus>(`/api/connections/${enc(id)}/connect`),
  // End-user launch page: the user's processes grouped by connection.
  portal: () => get<{ connections: PortalConnection[] }>('/api/portal'),
  // The training-guide index (same list the suite launcher shows), for the launch page.
  guides: () => get<{ file: string; title: string; type: string }[]>('/guides/index.json'),

  // Power-user connection management (create / edit / assign, from the app).
  listManageableConnections: () =>
    get<ManagedConnection[]>('/api/connections/manageable'),
  listAssignableUsers: () => get<string[]>('/api/assignable-users'),
  saveManagedConnection: (body: Record<string, unknown>) =>
    post<ManagedConnection>('/api/connections', body),
  deleteManagedConnection: (id: string) =>
    del<{ ok: boolean }>(`/api/connections/${enc(id)}`),
  testManagedConnection: (body: Record<string, unknown>) =>
    post<{ dbError: string | null; llmError: string | null; llmModels: string[] }>(
      '/api/connections/test',
      body,
    ),
  // Create the process-mining schema + tables (needs elevated DB privileges).
  provisionManagedSchema: (body: Record<string, unknown>) =>
    post<{ ok: boolean; error: string | null; created: string[] }>(
      '/api/connections/provision-schema',
      body,
    ),
  // Generate the bookstore demo event log into a schema (needs elevated DB privileges).
  generateDemoContent: (body: Record<string, unknown>) =>
    post<{
      ok: boolean
      error: string | null
      journeys: number
      project?: string
      message?: string
    }>('/api/connections/generate-demo', body),
  // Projects stored in a manageable connection's schema (journey/event counts + delete).
  listConnectionProjects: (id: string) =>
    get<ConnectionProjectsResult>(`/api/connections/${enc(id)}/projects`),
  deleteConnectionProject: (id: string, projectId: number) =>
    post<ConnectionProjectDeleteResult>(`/api/connections/${enc(id)}/projects/delete`, {
      projectId,
    }),
  disconnect: () => post<ConnectionStatus>('/api/disconnect'),
  connectionStatus: () => get<ConnectionStatus>('/api/connection/status'),

  // ── integration abstraction layer ────────────────────────────────────────
  integrationStatus: () => get<IntegrationStatus>('/api/integration/status'),
  integrationExtractors: () => get<ExtractorInfo[]>('/api/integration/extractors'),
  listSourceTypes: () => get<SourceType[]>('/api/integration/source-types'),
  createSourceType: (body: SourceTypeInput) =>
    post<SourceType>('/api/integration/source-types', body),
  updateSourceType: (id: string, body: SourceTypeInput) =>
    put<SourceType>(`/api/integration/source-types/${enc(id)}`, body),
  deleteSourceType: (id: string) =>
    del<{ ok: boolean }>(`/api/integration/source-types/${enc(id)}`),
  parseDetect: (sample: string) =>
    post<{ fields: ExtractionField[] }>('/api/integration/parse/detect', { sample }),
  parseSegment: (sample: string, start: number, end: number) =>
    post<{ regex: string; value: string }>('/api/integration/parse/segment', { sample, start, end }),
  parseTimestamp: (value: string) =>
    post<{ format: string; normalized: string }>('/api/integration/parse/timestamp', { value }),
  listSources: () => get<Source[]>('/api/integration/sources'),
  // Creating an API Server - Event Receiver returns a one-time `token` (only its hash is stored).
  createSource: (body: SourceInput) =>
    post<Source & { token?: string }>('/api/integration/sources', body),
  updateSource: (id: string, body: SourceInput) =>
    put<Source>(`/api/integration/sources/${enc(id)}`, body),
  deleteSource: (id: string) => del<{ ok: boolean }>(`/api/integration/sources/${enc(id)}`),
  // The sink port pool + ports already taken (by port → sink name), for the wizard.
  listSinkPorts: () =>
    get<{ pool: number[]; https: Record<string, number>; used: Record<string, string> }>(
      '/api/integration/sink-ports',
    ),
  // Mint a fresh bearer token for a sink; the new plaintext is returned once.
  regenerateSinkToken: (id: string) =>
    post<{ token: string }>(`/api/integration/sources/${enc(id)}/regenerate-token`, {}),
  // Everything needed to build a sink's exact ingest request (scheme/port live under
  // the current TLS mode, + the console container ports for host-offset detection).
  sinkIngestInfo: (id: string) =>
    get<{
      method: string; path: string
      httpPort: number; httpsPort: number
      tlsMode: string; activeScheme: string; activeContainerPort: number
      consoleHttpPort: number; consoleHttpsPort: number; titleShort: string
      endpointUrl: string
    }>(`/api/integration/sources/${enc(id)}/ingest-info`),
  // Save (or clear, with "") a sink's public endpoint-URL override.
  setSinkEndpoint: (id: string, url: string) =>
    post<{ endpointUrl: string }>(`/api/integration/sources/${enc(id)}/sink-endpoint`, { url }),
  // The live sink monitor: per-sink liveness + destination-DB counts (one poll).
  sinkMonitor: () => get<SinkMonitor>('/api/integration/sinks/monitor'),
  previewSource: (path: string, limit: number) =>
    post<{ lines: string[]; truncated: boolean }>('/api/integration/sources/preview', { path, limit }),
  // Source-type wizard file picker: list the sandbox files, and detect a file's record
  // delimiter (or split on an explicit one), returning the first N records.
  listIntegrationFiles: () => get<IntegrationFile[]>('/api/integration/files'),
  detectRecords: (path: string, delimiter = '', limit = 5) =>
    post<RecordDetection>('/api/integration/files/records', { path, delimiter, limit }),
  // Detect a file's data format (text / JSON / XML) and return rendered sample records
  // plus suggested fields with their path selectors.
  detectStructure: (path: string, limit = 5) =>
    post<StructureDetection>('/api/integration/files/structure', { path, limit }),
  // Projects already in a destination connection's schema (gated on assignment, unlike
  // the manager-only /api/connections/{id}/projects).
  destinationProjects: (connectionId: string) =>
    get<ConnectionProjectsResult>(`/api/integration/connections/${enc(connectionId)}/projects`),
  runSource: (id: string, titleShort: string, connectionId: string, delta = true) =>
    post<{ records: number; detail: string }>(`/api/integration/sources/${enc(id)}/run`, {
      titleShort,
      connectionId,
      delta,
    }),
  sourceCheckpoint: (id: string) =>
    get<SourceCheckpoint>(`/api/integration/sources/${enc(id)}/checkpoint`),
  resetSourceCheckpoint: (id: string) =>
    post<{ ok: boolean }>(`/api/integration/sources/${enc(id)}/checkpoint/reset`),

  // ── project data ─────────────────────────────────────────────────────────
  listProjects: () => get<Project[]>('/api/projects'),
  bootstrap: (projectId: number, sampleSet: SampleSet) =>
    get<ProjectBootstrap>(
      `/api/projects/${projectId}/bootstrap?sampleSet=${sampleSet}`,
    ),
  // The META values that occur on ONE node's (step's) events, for its Meta Infos panel.
  // Each entry carries the value, the date/time it was last seen, and its occurrence count.
  nodeMetaValues: (projectId: number, step: string, sampleSet: SampleSet) =>
    post<{ meta1: MetaEntry[]; meta2: MetaEntry[]; meta3: MetaEntry[] }>(
      `/api/projects/${projectId}/node-metas`,
      { step, sampleSet },
    ),
  graph: (
    projectId: number,
    filter: FilterSpec,
    options: {
      totalJourneyCount?: number | null
      includeGoodness?: boolean
      includeVariants?: boolean
      variantLimit?: number
    } = {},
  ) =>
    post<GraphResult>(`/api/projects/${projectId}/graph`, {
      filter,
      totalJourneyCount: options.totalJourneyCount ?? null,
      includeGoodness: options.includeGoodness ?? true,
      includeVariants: options.includeVariants ?? false,
      variantLimit: options.variantLimit ?? 500,
    }),
  journeyPaths: (projectId: number, filter: FilterSpec, variantLimit = 500) =>
    post<JourneyPath[]>(`/api/projects/${projectId}/journey-paths`, {
      filter,
      variantLimit,
    }),
  statistics: (
    projectId: number,
    filter: FilterSpec,
    routeLimit: number,
    totalJourneyCount: number | null,
  ) =>
    post<StatisticsResponse>(`/api/projects/${projectId}/statistics`, {
      filter,
      routeLimit,
      totalJourneyCount,
    }),
  similarity: (payload: {
    variantsA: JourneyPath[]
    variantsB: JourneyPath[]
    graphA: ProcessGraph
    graphB: ProcessGraph
  }) => post<{ score: number | null }>('/api/similarity', payload),
  eventIds: (projectId: number, prefix: string, sampleSet: SampleSet) =>
    get<string[]>(
      `/api/projects/${projectId}/event-ids?prefix=${enc(prefix)}&sampleSet=${sampleSet}`,
    ),
  journey: (projectId: number, eventId: string, sampleSet: SampleSet) =>
    get<{
      queriedEventId: string
      processGraph: ProcessGraph
      // The raw ordered trace (loops unrolled) for the sequential swimlane view.
      sequence: JourneyEvent[]
      journeyCount: number
      startDate: string | null
      endDate: string | null
      meta1: string | null
      meta2: string | null
      meta3: string | null
    }>(
      `/api/projects/${projectId}/journey?eventId=${enc(eventId)}&sampleSet=${sampleSet}`,
    ),
  updateStep: (
    projectId: number,
    step: string,
    payload: {
      bgColor: string
      fgColor: string
      score: number | null
      shape: string
      belongsTo: string | null
      description: string | null
    },
  ) =>
    put<{
      scoreBoundsMin: number
      scoreBoundsMax: number
      allStepInfos: Record<string, StepInfo>
    }>(`/api/projects/${projectId}/steps/${enc(step)}`, payload),
  nearestDay: (projectId: number, day: string, sampleSet: SampleSet) =>
    post<{ date: string | null }>(`/api/projects/${projectId}/nearest-day`, {
      day,
      sampleSet,
    }),

  // ── notes ────────────────────────────────────────────────────────────────
  listNotes: (projectId: number) =>
    get<ProcessNote[]>(`/api/projects/${projectId}/notes`),
  saveNote: (projectId: number, note: ProcessNote) =>
    put<ProcessNote>(`/api/projects/${projectId}/notes`, note),
  // Append a comment to a note's thread and/or toggle resolved (any viewer);
  // importance/isShared are applied server-side only for the note's author.
  updateNote: (
    projectId: number,
    noteId: string,
    body: {
      title?: string
      comment?: string
      resolved?: boolean
      importance?: string
      isShared?: boolean
    },
  ) =>
    post<ProcessNote>(`/api/projects/${projectId}/notes/${enc(noteId)}`, body),
  deleteNote: (projectId: number, noteId: string) =>
    del<void>(`/api/projects/${projectId}/notes/${enc(noteId)}`),

  // ── sampling ─────────────────────────────────────────────────────────────
  sampleCounts: (projectId: number) =>
    get<{ counts: Record<string, number>; methods: Record<string, SamplingMethod> }>(
      `/api/projects/${projectId}/samples`,
    ),
  createSample: (
    projectId: number,
    sampleSet: SampleSet,
    count: number,
    method: SamplingMethod,
  ) =>
    post<{ counts: Record<string, number>; created: number }>(
      `/api/projects/${projectId}/samples`,
      { sampleSet, count, method },
    ),
  deleteSample: (projectId: number, sampleSet: SampleSet) =>
    del<{ counts: Record<string, number> }>(
      `/api/projects/${projectId}/samples/${sampleSet}`,
    ),

  // ── simulation & conformance ─────────────────────────────────────────────
  simulate: (
    graph: ProcessGraph,
    stepInfos: Record<string, StepInfo>,
    config: SimulationConfig,
  ) => post<SimulationResult>('/api/simulate', { graph, stepInfos, config }),
  conformance: (projectId: number, filter: FilterSpec, happyPaths: HappyPath[]) =>
    post<Record<string, number | null>>(`/api/projects/${projectId}/conformance`, {
      filter,
      happyPaths,
    }),

  // ── AI documentation ─────────────────────────────────────────────────────
  documentation: (
    projectId: number,
    payload: {
      projectTitle: string
      filter: FilterSpec
      graph: ProcessGraph
      promptTemplate: string
      targetNorms: Record<string, Record<string, number>>
      targetMetric: TransitionMetric
      normIsMinimum?: boolean
      happyPaths: HappyPath[]
      notes?: ProcessNote[]
      connectionId?: string
      sankeySvg?: string
      sankeyCaption?: string
      preparedFor?: string
    },
  ) =>
    post<DocumentationResponse>(`/api/projects/${projectId}/documentation`, payload),

  // The report analysis prompt for a (connection, project). Power/developer/admin only —
  // the same mapping the admin Reporting tab manages.
  reportPrompt: (projectId: number, connectionId: string) =>
    get<{ prompt: string }>(
      `/api/projects/${projectId}/report-prompt?connectionId=${enc(connectionId)}`,
    ),
  setReportPrompt: (projectId: number, connectionId: string, prompt: string) =>
    put<{ prompt: string }>(`/api/projects/${projectId}/report-prompt`, {
      connectionId,
      prompt,
    }),

  // ── actions (saved node-menu actions, per connection + project) ───────────
  listActions: (projectId: number, connectionId: string) =>
    get<{ actions: SavedAction[] }>(
      `/api/projects/${projectId}/actions?connectionId=${enc(connectionId)}`,
    ),
  createAction: (
    projectId: number,
    body: { connectionId: string; name: string; script: string; spec: ActionSpec; enabled: boolean },
  ) => post<SavedAction>(`/api/projects/${projectId}/actions`, body),
  updateAction: (
    projectId: number,
    actionId: string,
    body: { connectionId: string; name: string; script: string; spec: ActionSpec; enabled: boolean },
  ) => put<SavedAction>(`/api/projects/${projectId}/actions/${enc(actionId)}`, body),
  deleteAction: (projectId: number, actionId: string, connectionId: string) =>
    del<{ ok: boolean }>(
      `/api/projects/${projectId}/actions/${enc(actionId)}?connectionId=${enc(connectionId)}`,
    ),
  runAction: (
    projectId: number,
    actionId: string,
    body: { connectionId: string; filter: FilterSpec; contextNode: string; resolvedSteps: string[] },
  ) => post<ActionRunResult>(`/api/projects/${projectId}/actions/${enc(actionId)}/run`, body),
  previewRunAction: (
    projectId: number,
    body: {
      connectionId: string
      spec: ActionSpec
      filter: FilterSpec
      contextNode: string
      resolvedSteps: string[]
    },
  ) => post<ActionRunResult>(`/api/projects/${projectId}/actions/preview-run`, body),
  previewActionSql: (
    projectId: number,
    body: {
      connectionId: string
      spec: ActionSpec
      filter: FilterSpec
      contextNode: string
      resolvedSteps: string[]
    },
  ) => post<{ sql: string }>(`/api/projects/${projectId}/actions/preview-sql`, body),

  // ── aggregates (collapse connected steps into a Σ super-step) ─────────────
  createAggregate: (projectId: number, body: CreateAggregateBody) =>
    post<CreateAggregateResult>(`/api/projects/${projectId}/aggregate`, body),
  createAggregateSet: (projectId: number, body: CreateAggregateSetBody) =>
    post<AggregateSetResult>(`/api/projects/${projectId}/aggregate-set`, body),
  addAggregates: (highLevelProjectId: number, body: AddAggregatesBody) =>
    post<AggregateSetResult>(`/api/projects/${enc(highLevelProjectId)}/aggregate-set/add`, body),
  listAggregates: (projectId: number, connectionId: string) =>
    get<{ aggregates: AggregateLink[] }>(
      `/api/projects/${projectId}/aggregates?connectionId=${enc(connectionId)}`,
    ),
  /** The ORIGINAL source graph + each aggregate's members, for expanding a Σ node in place
   *  with real (un-aggregated) numbers. projectId = the high-level map. */
  aggregateDrill: (projectId: number, connectionId: string, filter: FilterSpec) =>
    post<{
      graph: ProcessGraph
      journeyCount: number | null
      aggregates: { sigmaStep: string; members: string[] }[]
    }>(`/api/projects/${projectId}/aggregate-drill`, { connectionId, filter }),

  // ── settings ─────────────────────────────────────────────────────────────
  settings: () => get<Record<string, unknown>>('/api/settings'),
  patchSettings: (values: Record<string, unknown>) =>
    patch<{ ok: boolean }>('/api/settings', { values }),
}
