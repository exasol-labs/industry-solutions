/** Root shell — port of ContentView.swift: split view, theme, alert host,
 *  legal gate and the floating help panel. */

import { useCallback, useEffect, useState } from 'react'
import { HelpPanel } from './components/HelpPanel'
import { LegalGate } from './components/Gates'
import { IdleLogout } from './components/IdleLogout'
import { LaunchPortal } from './components/LaunchPortal'
import { LoginView } from './components/LoginView'
import { MetaInfoModal } from './components/MetaInfoModal'
import { Sidebar } from './components/Sidebar'
import { Spinner } from './components/ui'
import { hydrateSettings, useSetting } from './settings'
import { useStore } from './store'
import type { AssignedConnection, PortalProcess } from './types'
import { DetailPane } from './views/DetailPane'

/** True on the end-user launch page route (/home), tolerant of a trailing slash. */
const isPortalPath = (path: string) => path.replace(/\/+$/, '') === '/home'

export function App() {
  const store = useStore()
  const [ready, setReady] = useState(false)
  const [sidebarHidden, setSidebarHidden] = useState(false)
  const [showHelp, setShowHelp] = useState(false)
  // Client-side route so /home renders the end-user launch page (LaunchPortal) after the
  // same sign-in, while / stays the Work-Bench. Kept in sync with the Back/Forward buttons.
  const [route, setRoute] = useState(() => window.location.pathname)
  useEffect(() => {
    const onPop = () => setRoute(window.location.pathname)
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])
  const navigate = useCallback((path: string) => {
    window.history.pushState({}, '', path)
    setRoute(path)
  }, [])
  const portal = isPortalPath(route)

  // The /home route (login gate + launcher) gets its own browser-tab title.
  useEffect(() => {
    if (!portal) return
    const previous = document.title
    document.title = 'Process Launcher'
    return () => {
      document.title = previous
    }
  }, [portal])

  // Open a process picked on the launch page in a NEW Work-Bench tab, keeping the launch
  // page open. The connection + project ride in the URL; the Work-Bench reads them on load
  // (openFromUrlParams below) to connect and open the map. Opened during the click's user
  // gesture so Safari doesn't swallow it; a blocked pop-up falls back to same-tab.
  const openProcess = useCallback((connId: string, p: PortalProcess) => {
    const target = `/?connect=${encodeURIComponent(connId)}&project=${encodeURIComponent(String(p.projectId))}`
    // No "noopener": with it window.open returns null even on success, which would trip
    // the fallback and also navigate this tab (a double-open).
    const w = window.open(target, '_blank')
    if (!w) window.location.assign(target)
  }, [])

  // Loads everything that needs an authenticated session (settings live in the
  // backend and its API is gated when sign-in is required).
  // A process opened in a new tab from the launch page arrives as /?connect=…&project=….
  // Connect to that connection and open that project instead of resuming the last session.
  const openFromUrlParams = useCallback(async (): Promise<boolean> => {
    const params = new URLSearchParams(window.location.search)
    const connectId = params.get('connect')
    const projectId = params.get('project')
    if (!connectId || !projectId) return false
    // Tidy the URL right away so a refresh is a plain Work-Bench, not a re-open.
    window.history.replaceState({}, '', '/')
    const conn =
      useStore.getState().connections.find((c) => c.id === connectId) ??
      ({ id: connectId } as AssignedConnection)
    const ok = await useStore.getState().connectConnection(conn)
    if (ok) {
      const project = useStore.getState().projects.find((pr) => pr.projectId === Number(projectId))
      if (project) await useStore.getState().selectProject(project)
    }
    return true
  }, [])

  const initAfterAuth = useCallback(async () => {
    await hydrateSettings()
    await store.refreshConnections()
    if (useStore.getState().connection.isConnected) {
      await useStore.getState().loadProjects()
    }
    // A launch-page tile opened this tab at a specific process → open it and skip the resume.
    if (await openFromUrlParams()) return
    // Resume where the user left off: reconnect to the last connection, reopen the last
    // project and restore the last view. Reads the per-user snapshot hydrated above, so
    // it works both on a cold boot with a live session and after an inactivity re-login.
    await useStore.getState().restoreLastSession()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [openFromUrlParams])

  useEffect(() => {
    void (async () => {
      await store.checkSession()
      const { requireLogin, authUser } = useStore.getState()
      if (!requireLogin || authUser) {
        await initAfterAuth()
      }
      setReady(true)
    })()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // ⌘/Ctrl + ? opens help, matching the Swift keyboard shortcut.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && (e.key === '/' || e.key === '?')) {
        e.preventDefault()
        setShowHelp((v) => !v)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  if (!ready) {
    return (
      <div className="center-fill" style={{ height: '100%' }}>
        <Spinner large />
        <span>Starting…</span>
      </div>
    )
  }

  // Sign-in gate: shown when the admin requires login and there is no session —
  // and kept up through the forced-2FA-enrolment recovery-codes step even once the
  // session has been issued, so those codes are shown before entering the app.
  if ((store.requireLogin && !store.authUser) || store.mfaSetupPending) {
    return (
      <>
        <ThemeSync />
        <LoginView
          subtitle={portal ? 'Process Launcher' : 'Work-Bench'}
          onSignedIn={() => {
            void initAfterAuth()
          }}
        />
        <AlertHost />
      </>
    )
  }

  // The end-user launch page: signed in (or sign-in not required), the launcher-styled
  // tiles of the user's processes grouped by connection.
  if (portal) {
    return (
      <>
        <ThemeSync />
        <LaunchPortal onOpen={openProcess} onWorkbench={() => navigate('/')} />
        <AlertHost />
        <IdleLogout />
      </>
    )
  }

  return (
    <>
      <ThemeSync />
      <LegalGateHost>
        <div className="app">
          {!sidebarHidden && <Sidebar onCollapse={() => setSidebarHidden(true)} />}
          <DetailPane
            sidebarHidden={sidebarHidden}
            onShowSidebar={() => setSidebarHidden(false)}
            onShowHelp={() => setShowHelp(true)}
          />
        </div>
      </LegalGateHost>

      {showHelp && <HelpPanel onClose={() => setShowHelp(false)} />}
      {store.metaInfoOpen && <MetaInfoModal onClose={() => store.closeMetaInfo()} />}
      <AlertHost />
      <IdleLogout />
    </>
  )
}

/** Applies the `app.theme` preference, following the OS when set to "system". */
function ThemeSync() {
  const [theme] = useSetting<string>('app.theme')

  useEffect(() => {
    const media = window.matchMedia('(prefers-color-scheme: dark)')
    const apply = () => {
      const resolved =
        theme === 'system' ? (media.matches ? 'dark' : 'light') : theme
      document.documentElement.dataset.theme = resolved
    }
    apply()
    media.addEventListener('change', apply)
    return () => media.removeEventListener('change', apply)
  }, [theme])

  return null
}

function LegalGateHost({ children }: { children: React.ReactNode }) {
  const [accepted, setAccepted] = useSetting<boolean>('legal.accepted')
  const store = useStore()
  if (!accepted)
    return (
      <LegalGate
        onAccept={() => setAccepted(true)}
        // Declining returns to the Login panel (signs the user out).
        onDecline={() => void store.logout()}
      />
    )
  return <>{children}</>
}

function AlertHost() {
  const store = useStore()
  const alert = store.pendingAlert
  if (!alert) return null

  return (
    <div className="scrim" onClick={store.dismissAlert}>
      <div className="alert-box" onClick={(e) => e.stopPropagation()} role="alertdialog">
        <div className="a-body">
          <div className="a-title">{alert.title}</div>
          <div className="a-message">{alert.message}</div>
        </div>
        <div className="a-actions">
          {alert.secondaryLabel && (
            <button onClick={store.dismissAlert}>{alert.secondaryLabel}</button>
          )}
          <button
            className="emphasis"
            onClick={() => {
              store.dismissAlert()
              alert.onPrimary?.()
            }}
          >
            {alert.primaryLabel}
          </button>
        </div>
      </div>
    </div>
  )
}
