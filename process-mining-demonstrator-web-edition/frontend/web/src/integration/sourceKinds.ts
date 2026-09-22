/** The generic registry of source *kinds* the "Add source" wizard is built from.
 *
 *  Each kind declares its config fields; the wizard renders the right form from the
 *  descriptor, and the backend stores `{kind, config}` opaquely — so adding a new kind
 *  (a database, a REST API, object storage, …) is a matter of adding an entry here (and
 *  allowing the kind id in `SOURCE_KINDS` on the backend). Only "file" is available for
 *  now; the rest are listed as `available: false` to show the intended structure. */

// 'sourceType' is a dynamic picker of the user's source types (stored as an id in the
// config); 'connection' picks one of the user's connections; 'sinkPort' picks a free
// port from the sink pool. The wizard populates these options at runtime.
export type SourceFieldType =
  | 'text' | 'password' | 'number' | 'select' | 'sourceType' | 'connection' | 'sinkPort'
  | 'checkbox'

export interface SourceFieldDef {
  key: string
  label: string
  type: SourceFieldType
  placeholder?: string
  help?: string
  required?: boolean
  options?: string[] // for `select`
  default?: string
  // Row layout hint: 'full' = own row (default), 'grow' = share a row & take the
  // slack, 'narrow' = share a row at a fixed width (e.g. an encoding select).
  layout?: 'full' | 'grow' | 'narrow'
}

export interface SourceKindDef {
  id: string
  label: string
  icon: string
  description: string
  available: boolean
  fields: SourceFieldDef[]
  /** One-line summary of a saved source's config, shown on its badge. */
  summary: (config: Record<string, unknown>) => string
}

export const SOURCE_KINDS: SourceKindDef[] = [
  {
    id: 'file',
    label: 'File',
    icon: '📄',
    description: 'A log or data file the extractor reads at run time.',
    available: true,
    fields: [
      {
        key: 'path',
        label: 'File path or glob',
        type: 'text',
        placeholder: '/data/app/access.log  ·  events.json  ·  export.xml',
        help: 'Path (or glob) the extractor reads when the source runs — a log/text, JSON or XML file.',
        required: true,
        layout: 'grow',
      },
      {
        key: 'encoding',
        label: 'Encoding',
        type: 'select',
        options: ['utf-8', 'latin-1', 'utf-16'],
        default: 'utf-8',
        layout: 'narrow',
      },
      {
        key: 'sourceTypeId',
        label: 'Source type',
        type: 'sourceType',
        help: 'The parser applied to each line when this source runs.',
      },
    ],
    summary: (c) => String(c.path ?? '(no path)'),
  },
  // ── Future kinds — structure only, not selectable yet ──────────────────────
  {
    id: 'ai-agent-logging-sink',
    label: 'API Server - Event Receiver',
    icon: '🤖',
    description:
      'An HTTP/HTTPS API that AI agents POST journey entries to as JSON. Each entry is ' +
      'written to the chosen connection’s JOURNEYS table; unknown steps are created.',
    available: true,
    fields: [
      {
        key: 'connectionId',
        label: 'Connection',
        type: 'connection',
        required: true,
        help: 'The database connection whose JOURNEYS table posted entries are written to.',
      },
      {
        key: 'titleShort',
        label: 'Project code',
        type: 'text',
        required: true,
        placeholder: 'e.g. AGENTLOG',
        help: 'Entries land in this project (TITLE_SHORT, ≤10 chars); it is created if new.',
        layout: 'grow',
      },
      {
        key: 'port',
        label: 'Port',
        type: 'sinkPort',
        required: true,
        help: 'A free slot from the sink pool; each shows its HTTP and HTTPS port.',
        layout: 'grow',
      },
      {
        key: 'tls',
        label: 'TLS (address agents over HTTPS)',
        type: 'checkbox',
        default: 'true',
        help: 'Which scheme agents should use — sets the HTTPS or HTTP endpoint shown in the request and SKILL.md.',
        layout: 'narrow',
      },
    ],
    summary: (c) =>
      `${c.tls === false ? 'HTTP' : 'HTTPS'} port ${c.port ?? '—'} · ${c.titleShort ?? ''}`,
  },
]

export const sourceKind = (id: string): SourceKindDef | undefined =>
  SOURCE_KINDS.find((k) => k.id === id)
