/** The "Sources" section of the integration console's left panel: the user's data
 *  sources as badges (kind icon · name · a config summary), a '+' in the header to add
 *  one via the wizard, and per-badge delete. At most ~3 badges show; the list scrolls. */

import { useCallback, useEffect, useState } from 'react'
import { api } from '../api'
import { sourceKind } from '../integration/sourceKinds'
import type { Source } from '../types'
import { ConfirmDialog } from './ConfirmDialog'
import { RunSourceDialog } from './RunSourceDialog'
import { SectionHeader } from './SectionHeader'
import { SinkIngestModal } from './SinkIngestModal'
import { SourceWizard } from './SourceWizard'
import { Sheet } from './ui'

const SINK_KIND = 'ai-agent-logging-sink'

export function SourcesSection({ open, onToggle }: { open: boolean; onToggle: () => void }) {
  const [sources, setSources] = useState<Source[]>([])
  const [wizard, setWizard] = useState<'new' | Source | null>(null)
  const [running, setRunning] = useState<Source | null>(null)
  const [confirming, setConfirming] = useState<Source | null>(null)
  // Regenerating a token invalidates the live one immediately, so guard it behind a
  // confirmation — an accidental click would lock out every agent still using the old token.
  const [confirmRegen, setConfirmRegen] = useState<Source | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // A freshly regenerated sink token, shown once (only its hash is stored server-side).
  const [newToken, setNewToken] = useState<{ sourceId: string; token: string; name: string } | null>(null)
  // The "exact request" popup (URL + curl + SKILL.md); token present when just minted.
  const [details, setDetails] = useState<{ sourceId: string; token?: string; name: string } | null>(null)

  const regenerate = async (s: Source) => {
    try {
      const { token } = await api.regenerateSinkToken(s.id)
      setNewToken({ sourceId: s.id, token, name: s.name })
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  const refresh = useCallback(async () => {
    try {
      setSources(await api.listSources())
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const remove = async (s: Source) => {
    setBusy(true)
    try {
      await api.deleteSource(s.id)
      setConfirming(null)
      await refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <SectionHeader
        title="Sources"
        count={sources.length}
        open={open}
        onToggle={onToggle}
        trailing={
          <button
            className="icon-btn"
            title="Add a source"
            aria-label="Add a source"
            onClick={() => setWizard('new')}
          >
            ＋
          </button>
        }
      />

      {open && error && (
        <div className="t-caption fg-red" style={{ padding: '0 4px' }}>
          {error}
        </div>
      )}

      {open &&
        (sources.length === 0 ? (
          <span className="t-caption fg-tertiary" style={{ padding: '0 4px' }}>
            No sources yet. Use ＋ to add one.
          </span>
        ) : (
          <div className="card-list" style={{ maxHeight: 190 }}>
            {sources.map((s) => {
            const kind = sourceKind(s.kind)
            const watching = Boolean(
              (s.config?.watchdog as { enabled?: boolean } | undefined)?.enabled,
            )
            return (
              <div
                key={s.id}
                className="card"
                style={{ minHeight: 52, cursor: 'pointer' }}
                title="Edit source"
                onClick={() => setWizard(s)}
              >
                <span aria-hidden style={{ fontSize: 16 }}>{kind?.icon ?? '🗂️'}</span>
                <div className="card-body">
                  <span className="card-title">
                    {s.name}
                    {watching && (
                      <span title="Watchdog on — auto-imports new lines" style={{ marginLeft: 6 }}>👁</span>
                    )}
                  </span>
                  <span className="card-sub fg-tertiary">
                    {kind?.label ?? s.kind}
                    {kind ? ` · ${kind.summary(s.config)}` : ''}
                  </span>
                </div>
                {s.kind === SINK_KIND && (
                  <button
                    className="icon-btn"
                    style={{ width: 22, height: 22 }}
                    title="Show the exact ingest request (URL + curl)"
                    aria-label="Show ingest request"
                    onClick={(e) => {
                      e.stopPropagation()
                      setDetails({ sourceId: s.id, name: s.name })
                    }}
                  >
                    🔌
                  </button>
                )}
                {s.kind === SINK_KIND && (
                  <button
                    className="icon-btn"
                    style={{ width: 22, height: 22, color: 'var(--accent)' }}
                    title="Regenerate the ingest token (invalidates the old one)"
                    aria-label="Regenerate token"
                    onClick={(e) => {
                      e.stopPropagation()
                      setConfirmRegen(s)
                    }}
                  >
                    🔑
                  </button>
                )}
                {s.kind === 'file' && (
                  <button
                    className="icon-btn"
                    // Green ▷ while a watchdog is on this source: it is importing on its
                    // own, so the button reads "live" rather than just "you can run it".
                    style={{
                      width: 22,
                      height: 22,
                      color: watching ? 'var(--green)' : 'var(--accent)',
                    }}
                    title={
                      watching
                        ? 'Watchdog active — run an import now as well'
                        : 'Run extraction'
                    }
                    aria-label="Run extraction"
                    onClick={(e) => {
                      e.stopPropagation()
                      setRunning(s)
                    }}
                  >
                    ▷
                  </button>
                )}
                <button
                  className="icon-btn"
                  style={{ width: 22, height: 22, color: 'var(--secondary)' }}
                  title="Delete source"
                  aria-label="Delete source"
                  onClick={(e) => {
                    e.stopPropagation()
                    setConfirming(s)
                  }}
                >
                  ✕
                </button>
              </div>
            )
          })}
          </div>
        ))}

      {wizard && (
        <SourceWizard
          existing={wizard === 'new' ? undefined : wizard}
          onClose={() => setWizard(null)}
          onSaved={async () => {
            setWizard(null)
            await refresh()
          }}
        />
      )}

      {running && (
        <RunSourceDialog source={running} onClose={() => setRunning(null)} onDone={() => {}} />
      )}

      {confirming && (
        <ConfirmDialog
          title="Delete source"
          message={`Delete the source “${confirming.name}”? This can’t be undone.`}
          confirmLabel="Delete source"
          busy={busy}
          onConfirm={() => void remove(confirming)}
          onCancel={() => setConfirming(null)}
        />
      )}

      {confirmRegen && (
        <ConfirmDialog
          title="Regenerate ingest token"
          message={`Generate a new bearer token for “${confirmRegen.name}”? The current token stops working immediately — any agent still using it is rejected until you give it the new one.`}
          confirmLabel="Regenerate token"
          busy={busy}
          onConfirm={async () => {
            setBusy(true)
            const s = confirmRegen
            await regenerate(s)
            setBusy(false)
            setConfirmRegen(null)
          }}
          onCancel={() => setConfirmRegen(null)}
        />
      )}

      {newToken && (
        <Sheet
          title="New token"
          icon="🔑"
          onClose={() => setNewToken(null)}
          footer={
            <>
              <span className="spacer" />
              <button className="btn prominent" onClick={() => setNewToken(null)}>Done</button>
            </>
          }
        >
          <div className="col" style={{ gap: 8 }}>
            <div className="t-body">
              A new bearer token was generated. <strong>Copy it now</strong> — it is shown only
              once (only its hash is stored). The previous token stops working once the sink
              rebinds.
            </div>
            <input
              className="text-input"
              readOnly
              value={newToken.token}
              onFocus={(e) => e.currentTarget.select()}
              style={{ fontFamily: 'var(--mono, monospace)' }}
            />
            <div className="row" style={{ gap: 8 }}>
              <button
                className="btn small"
                onClick={() => void navigator.clipboard?.writeText(newToken.token)}
              >
                Copy token
              </button>
              <button
                className="btn small"
                onClick={() =>
                  setDetails({ sourceId: newToken.sourceId, token: newToken.token, name: newToken.name })
                }
              >
                🔌 Show the exact request
              </button>
            </div>
          </div>
        </Sheet>
      )}

      {details && (
        <SinkIngestModal
          sourceId={details.sourceId}
          token={details.token}
          name={details.name}
          onClose={() => setDetails(null)}
        />
      )}
    </>
  )
}
