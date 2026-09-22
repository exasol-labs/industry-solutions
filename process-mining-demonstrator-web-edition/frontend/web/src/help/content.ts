/**
 * In-app help content — ported from HelpView.swift.
 *
 * The block model mirrors the Swift `HelpBlock` enum so the same structured,
 * example-driven documentation renders here (paragraph / tip / warning /
 * bullets / definition / code). The Process Goodness, Process Similarity and
 * Simulation chapters are ported verbatim, including every worked example.
 */

export type HelpBlock =
  | { kind: 'paragraph'; text: string }
  | { kind: 'tip'; text: string }
  | { kind: 'warning'; text: string }
  | { kind: 'bullets'; items: string[] }
  | { kind: 'definition'; term: string; detail: string }
  | { kind: 'code'; text: string }
  | { kind: 'table'; headers: string[]; rows: string[][] }

export interface HelpSection {
  heading: string
  body: HelpBlock[]
}

export interface HelpTopic {
  id: string
  title: string
  subtitle: string
  icon: string
  sections: HelpSection[]
}

// Block constructors — keep the content below terse and readable.
const p = (text: string): HelpBlock => ({ kind: 'paragraph', text })
const tip = (text: string): HelpBlock => ({ kind: 'tip', text })
const warn = (text: string): HelpBlock => ({ kind: 'warning', text })
const ul = (...items: string[]): HelpBlock => ({ kind: 'bullets', items })
const def = (term: string, detail: string): HelpBlock => ({ kind: 'definition', term, detail })
const code = (text: string): HelpBlock => ({ kind: 'code', text })
const table = (headers: string[], rows: string[][]): HelpBlock => ({
  kind: 'table',
  headers,
  rows,
})

// ── Overview ──────────────────────────────────────────────────────────────────

const overview: HelpTopic = {
  id: 'overview',
  title: 'Overview',
  subtitle: 'What Process Mining Demonstrator does and key concepts',
  icon: '🏠',
  sections: [
    {
      heading: 'What is Process Mining Demonstrator?',
      body: [
        p('Process Mining Demonstrator is a process-mining tool that connects to an Exasol database and visualises how real cases flow through your business processes.'),
        p('It reads a JOURNEYS table and renders every possible path between process steps as an interactive flow chart, with rich filtering, side-by-side comparison, and individual journey inspection.'),
      ],
    },
    {
      heading: 'Workflow at a glance',
      body: [
        ul(
          'Sign in, then open the sidebar Connections section — it lists the database connections an administrator has assigned to you.',
          'Tap a connection to connect; the Projects section opens automatically.',
          'Select a project — the A-Chart loads for the last 30 days of data.',
          'Choose a chart view from the ☰ menu in the top-right corner of the main area.',
          'Adjust filters in the sidebar and tap Apply to refresh the map.',
          'Each chart view remembers its own filter settings independently.',
        ),
      ],
    },
    {
      heading: 'Data model',
      body: [
        def('Journey / Case', 'One end-to-end instance of a process, identified by EVENT_ID.'),
        def('Step / Event', 'A single activity within a journey, stored as a row in JOURNEYS.'),
        def('Transition', 'A chronologically consecutive pair of steps within the same journey.'),
        def('Meta attributes', 'Up to three free-text columns (META_1 – META_3) carrying case-level attributes such as department or customer segment.'),
      ],
    },
    {
      heading: 'The ten views',
      body: [
        p('Open the ☰ menu (top-right) to switch between: A-Chart, B-Chart, A/B Comparison, Individual Journey, AI supported Documentation, Statistics, Conformance Check, Happy Path, Notes and Simulation. A checkmark marks the active view, and the title capsule shows it on a second line so you always know your context.'),
        tip('Conformance Check, Happy Path and Simulation are advanced-analysis views shown only to Power users (and administrators). Plain users do not see them in the ☰ menu.'),
        tip('Press ⌘/ (or Ctrl+/) at any time to open or close this Help panel. It floats, and can be dragged by its title bar and resized from the bottom-right corner.'),
      ],
    },
  ],
}

// ── Database setup ────────────────────────────────────────────────────────────

const database: HelpTopic = {
  id: 'database',
  title: 'Database Setup',
  subtitle: 'Table schemas and required permissions',
  icon: '🗄',
  sections: [
    {
      heading: 'Required tables',
      body: [
        p('Process Mining Demonstrator reads from four tables — PROJECTS, JOURNEYS, STEPS and METAS. A NOTES table and the JOURNEYS.SAMPLE_SET column are created automatically on first use if the connecting user has the necessary rights. All table and column names are case-insensitive in Exasol.'),
        code(
          `CREATE TABLE PROJECTS (
  PROJECT_ID  VARCHAR(100) NOT NULL PRIMARY KEY,
  TITLE       VARCHAR(200) NOT NULL,
  DESCRIPTION VARCHAR(500)
);

CREATE TABLE JOURNEYS (
  PROJECT_ID  VARCHAR(100) NOT NULL,
  EVENT_ID    HASHTYPE(16 BYTE) NOT NULL, -- MD5 id; one journey = rows sharing an EVENT_ID
  STEP        VARCHAR(200) NOT NULL,   -- activity name → a node in the map
  STEP_ID     DECIMAL(18,0),           -- activity id of STEP (joins STEPS.STEP_ID)
  EVENT_TIME  TIMESTAMP    NOT NULL,   -- orders steps; drives date filters
  META_1      VARCHAR(500),
  META_2      VARCHAR(500),
  META_3      VARCHAR(500)
);

CREATE TABLE STEPS (
  PROJECT_ID     VARCHAR(100) NOT NULL,
  STEP           VARCHAR(200) NOT NULL,
  STEP_ID        DECIMAL(18,0),         -- stable activity id; JOURNEYS.STEP_ID matches it
  DESCRIPTION    VARCHAR(500),
  BG_COLOR       VARCHAR(50),          -- colour name or 6-digit hex (e.g. FF8000)
  FG_COLOR       VARCHAR(50),
  SCORE          DECIMAL(5,0),         -- −999…999, shown as a badge
  SHAPE          VARCHAR(20),          -- stadium | round | hex | circle
  END_OF_PROCESS DECIMAL(1,0) DEFAULT 0,
  BELONGS_TO     VARCHAR(200),         -- optional grouping label
  PRIMARY KEY (PROJECT_ID, STEP)
);

CREATE TABLE METAS (
  PROJECT_ID   VARCHAR(100) NOT NULL PRIMARY KEY,
  META_1_TITLE VARCHAR(200),
  META_2_TITLE VARCHAR(200),
  META_3_TITLE VARCHAR(200)
);`,
        ),
      ],
    },
    {
      heading: 'Permissions & performance',
      body: [
        ul(
          'SELECT on PROJECTS, JOURNEYS, STEPS, METAS — required for all read features.',
          'CREATE TABLE — needed once so the NOTES table can be auto-created (Notes feature only).',
          'ALTER TABLE + INSERT on JOURNEYS — needed for the Sampling feature (adds the SAMPLE_SET column and writes sample rows).',
          'UPDATE on STEPS — needed for the in-app Step Editor.',
        ),
        tip('For best performance, index JOURNEYS (PROJECT_ID, EVENT_TIME) and JOURNEYS (PROJECT_ID, EVENT_ID).'),
        p('No Exasol instance yet? The free Community Edition and the official Docker image both work. When using the Docker image or Exasol 7.x, set the connection’s minimum RSA key size to 1024 bits (legacy).'),
      ],
    },
  ],
}

// ── Connections ───────────────────────────────────────────────────────────────

const connecting: HelpTopic = {
  id: 'connecting',
  title: 'Connections',
  subtitle: 'Sign in, then pick a database connection assigned to you',
  icon: '⛁',
  sections: [
    {
      heading: 'Signing in',
      body: [
        p('Unless an administrator has turned sign-in off, the application asks you to sign in. Use the username and password you were given — depending on how your organisation is set up this may be a local account or a directory (LDAP / Active Directory) account.'),
        def('Passkeys', 'If your administrator has enabled passkeys for your account, you can sign in with Touch ID, Windows Hello, or a hardware security key instead of a password. First sign in with your password, then open 🔑 Passkeys next to Sign out and add a passkey for this device. After that, type your username on the login page and click “Sign with Passkey”. Your password always keeps working as a fallback, so you are never locked out.'),
        def('Passkeys need a hostname', 'Passkeys are tied to a domain name, so they only work when you reach the app by a hostname (or “localhost” on the same machine) over HTTPS — not by a bare IP address. If you open the app by IP (e.g. from a tablet on the same network), the passkey buttons are hidden and enrolment is blocked; use the server’s name instead, such as its “.local” name. Password sign-in works either way.'),
        def('Two-factor (authenticator app)', 'If your administrator has enabled two-factor for your account, it’s required: the first time you sign in, after your password you’ll be asked to set it up right away — scan the QR with an authenticator app (Google Authenticator, 1Password, Authy…), enter the 6-digit code, and save the recovery codes it shows (each signs you in once if you lose your phone). After that, every sign-in asks for the current code following your password. You can also review your setup any time from 🔒 Two-factor next to Sign out.'),
        tip('Your app sign-in is completely separate from any database credentials. You never type a database password into the app — those live only in the administrator’s configuration.'),
      ],
    },
    {
      heading: 'How connections work',
      body: [
        p('A connection bundles one Exasol database server with an optional OpenAI-compatible LLM server. Connections are defined by an administrator in the admin interface and assigned to individual users.'),
        p('The Connections section of the sidebar lists only the connections assigned to you, as read-only cards — you cannot change the host, credentials or TLS settings here; that is the administrator’s responsibility.'),
        ul(
          'Database — the Exasol host the connection points at, shown as “Database: host:port”.',
          'LLM — shown when a model server is attached; it enables the AI Documentation feature.',
        ),
        tip('Database passwords and LLM API keys are encrypted at rest and never sent to the browser — the app only receives host, port, schema and whether an LLM is attached.'),
      ],
    },
    {
      heading: 'Connecting',
      body: [
        p('Tap a connection card to connect; tap it again to disconnect. Only one connection is active at a time. Disconnecting clears all loaded data — project, map, KPIs and filters all reset.'),
        p('Up to two coloured dots appear on the active connection. The first is the database state: green when connected, orange while connecting or after a failure. The second appears only when an LLM server is attached: blue when the model server is reachable, orange when it is not.'),
        tip('Use the ↻ button in the Connections header to refresh the list after an administrator has just granted you a new connection.'),
        tip('The app resumes where you left off: after signing in again — including after an idle sign-out — it automatically reconnects to your last connection, reopens the last project and returns to the last view. Pressing Disconnect clears that memory, so a deliberate disconnect is never silently undone.'),
      ],
    },
    {
      heading: 'Power users: manage your own connections',
      body: [
        p('If an administrator has given your account the power role, a ＋ button appears in the Connections header. Use it to create a connection — Exasol host, credentials, optional TLS and an optional LLM server — right from the app, and to tick the users it should be assigned to.'),
        p('You manage only the connections you create: an ✎ button appears on those cards so you can edit or delete them and change who they are assigned to. Every new connection is automatically assigned to you, so you can connect to it immediately. Passwords and API keys you enter are encrypted at rest and, once saved, are never sent back to the browser — leave those fields blank when editing to keep the stored secret unchanged.'),
        p('The editor has two tabs. “Database / LLM Details” holds the connection fields; it can also create a fresh process-mining schema for you — enter a schema name and the database credentials, then use “Create schema & tables” to build the schema and the required tables (PROJECTS, JOURNEYS, STEPS, METAS, NOTES) if they don’t already exist.'),
        p('The “Demo Content” tab generates a ready-made dataset into the schema. Three are offered: a Retail dataset (📚 “Online Bookstore” — a synthetic order lifecycle with a returns flow and a flaky bank-transfer path), a Finance/Insurance dataset (💶 “Online Credit Application” — bank/affiliate intake, an application-check rework loop, credit assessment, and score- and sum-driven approval with agent-review loops, ending in payment or rejection), and a Transportation dataset (✈️ “Flight Booking & Management” — Star Alliance-style login → search → select → book → pay → confirm, where 50% of bookings are interline and query a partner airline, and 20% only manage an existing booking). For any of them, enter the schema and how many journeys, then Generate; it creates the schema and tables as needed and loads the journeys into that dataset’s own project (others are left untouched).'),
        warn('Creating a schema or generating demo data needs a database account with CREATE SCHEMA / CREATE TABLE (and, for demo data, INSERT) rights. Only your database administrator can grant those — the application cannot authorise you.'),
        tip('Use Test in the editor to check the database (and LLM, if set) before saving.'),
      ],
    },
    {
      heading: 'Demo event-ID format',
      body: [
        p('In every demo dataset the stored EVENT_ID — the case key that ties a journey’s rows together — is the MD5 hash of a simple synthetic reference: the dataset prefix plus a 1-based, zero-padded 6-digit sequence number. So the first journey uses ORD-000001 / CRA-000001 / FLT-000001, the second ORD-000002 / CRA-000002 / FLT-000002, and so on.'),
        code(
          'Online Bookstore (BOOKSTORE):       EVENT_ID = md5("ORD-000001"), md5("ORD-000002"), …\n' +
            'Online Credit Application (CREDIT):  EVENT_ID = md5("CRA-000001"), md5("CRA-000002"), …\n' +
            'Flight Booking & Management (FLIGHTS): EVENT_ID = md5("FLT-000001"), md5("FLT-000002"), …\n' +
            '\n' +
            '# reproduce a specific ID from a shell:\n' +
            "printf 'ORD-%06d' 1 | md5      # macOS  →  the stored 32-char hex EVENT_ID\n" +
            "printf 'FLT-%06d' 42 | md5sum  # Linux",
        ),
        tip('In the Individual Journey view you can type the friendly reference (e.g. ORD-000001) straight into the Event ID field — it is MD5-hashed for you — or paste a raw 32-character hash.'),
      ],
    },
    {
      heading: 'No connections listed?',
      body: [
        p('An empty Connections list means no connection has been assigned to your account yet. Ask an administrator to grant you access from the admin interface (Database Connections tab) — or, if you are a power user, create one with the ＋ button.'),
      ],
    },
  ],
}

// ── Users & permissions ──────────────────────────────────────────────────────

const roles: HelpTopic = {
  id: 'roles',
  title: 'Users & Permissions',
  subtitle: 'The three roles and what each one can do',
  icon: '🔑',
  sections: [
    {
      heading: 'The three roles',
      body: [
        p('Every signed-in account carries one of three permission levels. They build on each other: a Power user can do everything a Regular user can, plus more; an Administrator can do everything a Power user can, plus manage the whole installation. Roles are granted in the admin interface (Users tab); by default a new account is a Regular user.'),
        def('Regular user', 'Explores the process — views the maps and charts, applies filters and saved presets, reads and writes notes, and adjusts their own KPIs, layout and personal settings. They work with the database connections an administrator (or Power user) has assigned to them.'),
        def('Power user', 'A Regular user who can also create, manage and assign their own database connections from within the app (they manage only the connections they created), provision schemas, generate demo data, run journey sampling, and use the advanced-analysis views (Conformance Check, Happy Path, Simulation) — all without needing the separate admin interface.'),
        def('Administrator', 'Full control. Everything a Power user can do over every connection, plus the admin interface (:8090): managing all users and roles, TLS certificates, the LDAP directory, licensing, logging, backups and login customization.'),
        def('Developer (additional grant)', 'An extra permission (the Developer checkbox in the admin Users tab), independent of the level above. It admits the account to the Integration console — a separate surface on the admin port + 10 (http://…:8100) for configuring the application’s data sources. Only developers and administrators may enter it (power users may not); a Regular user with only the Developer grant may enter the console but has no other elevated powers in the main app.'),
        tip('The Integration console reuses the same sign-in (password, passkey, two-factor) and follows the same TLS mode as the app. An administrator can turn it off entirely under Admin → Integration.'),
        tip('Roles require a signed-in identity. If an administrator turns off “Require sign-in for the main application” (the login gate, in the admin Users tab), the app runs with no user identity — so every Power/Admin-only capability below is unavailable: the Sampling section and the advanced views (Conformance, Happy Path, Simulation) are hidden, and their APIs return 403. To use those features, keep Require sign-in on and sign in with a Power or Admin account. There is no way to have both no-login access and the power features at once.'),
      ],
    },
    {
      heading: 'Capability matrix',
      body: [
        table(
          ['Capability', 'Regular', 'Power', 'Admin'],
          [
            ['View process maps, charts & KPIs', '✓', '✓', '✓'],
            ['Filters, saved presets & date window', '✓', '✓', '✓'],
            ['Read & write notes and comments', '✓', '✓', '✓'],
            ['Personal settings, layout & backup of preferences', '✓', '✓', '✓'],
            ['Advanced views: Conformance, Happy Path, Simulation', '—', '✓', '✓'],
            ['Journey sampling (create / delete samples)', '—', '✓', '✓'],
            ['Create, manage & assign own DB connections', '—', '✓', '✓'],
            ['Provision schema & generate demo data', '—', '✓', '✓'],
            ['Integration console (data-source configuration)', 'Developer only', '✓', '✓'],
            ['Admin interface: all users, connections, TLS, LDAP, licensing, logging', '—', '—', '✓'],
          ],
        ),
        tip('Journey sampling rewrites the shared sample sets for everyone on the connection, which is why it sits with the Power/Admin capabilities rather than being a personal, per-user action.'),
      ],
    },
  ],
}

// ── Administration ──────────────────────────────────────────────────────────

// ── Administration (split into per-area chapters, grouped in the TOC) ─────────

const adminInterface: HelpTopic = {
  id: 'admin-interface',
  title: 'Admin Interface',
  subtitle: 'The separate administration interface for security and access',
  icon: '⚙︎',
  sections: [
    {
      heading: 'Overview',
      body: [
        p('A separate administration interface runs on its own port (8090 by default) and is where all security and access is configured. It has its own sign-in and admits administrators only.'),
        p('On first run it seeds a local administrator — Administrator / Administrator — and prompts you to change the password. Local admin accounts always work as a break-glass route, even if a directory is later misconfigured.'),
        tip('The admin interface is organised into tabs: App Control (restart the servers, manage the license), TLS / SSL, Users, Database Connections, Directory (LDAP), Logging, Backup and Customize.'),
      ],
    },
  ],
}

const adminTls: HelpTopic = {
  id: 'admin-tls',
  title: 'TLS / SSL',
  subtitle: 'HTTP/HTTPS mode and certificates',
  icon: '🔒',
  sections: [
    {
      heading: 'Modes & certificates',
      body: [
        p('Choose how connections are accepted: Off (HTTP only), Optional (HTTP and HTTPS together) or Required (HTTPS only). Generate a self-signed certificate or upload your own PEM certificate and key, then mark one active.'),
        p('The main app and the admin interface both follow this one mode and share the same active certificate — the app on ports 8080/8443, the admin on 8090/8453. Changes take effect when the servers restart: the ↻ Restart app server button in the App Control tab rebinds both in place. If a mode needs a certificate but none is active, each server falls back to HTTP so nothing (including the admin itself) is left unreachable.'),
        warn('Certificate private keys are encrypted at rest. Keep the active certificate valid — an expired certificate makes HTTPS clients refuse to connect.'),
      ],
    },
  ],
}

const adminUsers: HelpTopic = {
  id: 'admin-users',
  title: 'Users & Sign-in',
  subtitle: 'Accounts, roles and the login gate',
  icon: '👤',
  sections: [
    {
      heading: 'Accounts & roles',
      body: [
        p('The Users tab controls who may sign in to the main application: create local users, enable or disable access, grant or revoke the admin role, and reset local passwords. Only enabled users can sign in.'),
        p('The Require sign-in toggle turns the login gate on or off for the main app (on by default). With it off, the app is open to anyone who can reach it — and, since there is then no user identity, per-user settings and filter presets all fall back to one shared profile.'),
        def('Failed sign-in lockout', '“Disable an account after N failed sign-in attempts” automatically disables an account once N wrong passwords are entered (defaults to 3; set 0 to turn it off). A locked account shows a clear message on the login panel and carries a Locked badge in the Users tab, where you can unlock it. The built-in Administrator is exempt from auto-lockout — as the sole recovery account it must not be lockable by someone who merely knows its name; it is protected by the per-IP throttle instead. (If you ever need to clear all locks, restart the servers with PMW_RESET_LOCKOUTS=1.) Separately, the admin sign-in page throttles repeated failures from the same IP address with a short, self-clearing cooldown (HTTP 429), so password guessing is slowed even when the account lockout does not apply.'),
        def('Power role', 'Make power / Remove power grants the power badge. Power users can create and manage their own database connections from within the main app and assign them to other users — without needing access to this admin interface. They manage only the connections they create; admins still see and manage every connection. Power users (and admins) also get the advanced-analysis views — Conformance Check, Happy Path and Simulation — and journey sampling. See the Users & Permissions chapter for the full capability matrix.'),
        def('Source badge', 'Each user is tagged local or LDAP so you can tell built-in accounts from directory accounts at a glance; the All / Local / LDAP filter narrows the list.'),
      ],
    },
    {
      heading: 'Passkeys (WebAuthn)',
      body: [
        p('Passkeys let a user sign in with Touch ID, Windows Hello, or a hardware security key instead of typing a password. They are an alternative, never a replacement: the password (or directory sign-in) always remains as a fallback, so no one is locked out if a device is lost.'),
        def('Who may use a passkey', 'The Passkey column in the Users tab gates this per account — tick it to let that user enrol and sign in with a passkey. The header checkbox is a master toggle that turns passkeys on or off for everyone at once. Both local and directory (LDAP) users can be allowed; a directory user enrols a local passkey that signs them in without contacting the directory.'),
        def('Enrolling a device', 'Once allowed, a user adds a passkey from the main app (the 🔑 Passkeys button by Sign out) or, for administrators, from the App Control → Passkeys card here. Enrolment requires being signed in first, so only the real account owner can register a device. A passkey registered on this host works for both the main app and this admin interface — one passkey, both surfaces.'),
        def('Signing in', 'On the login page the user types their username and clicks “Sign with Passkey”. Turning off the Passkey permission blocks further passkey sign-ins immediately (existing passkeys stop working until re-enabled); deleting a user also removes their passkeys.'),
        warn('Passkeys need a secure context — HTTPS, or localhost for local testing. Off localhost, run the app with TLS set to Optional or Required. On a single host everything works out of the box; for split app/admin sub-domains, set PMW_PASSKEY_RP_ID to the shared parent domain and list the origins in PMW_PASSKEY_ORIGINS.'),
        warn('Passkeys also require a real hostname: WebAuthn rejects bare IP addresses (and single-label hosts) as the domain a passkey is bound to. If users reach the app by IP — e.g. a tablet connecting to a Mac on the LAN — passkey enrolment fails with “the effective domain is not a valid domain”. Give the host a name they can resolve (its “.local” Bonjour name, or a DNS entry) and issue the TLS certificate for that name. The app hides the passkey controls when it detects an IP so this is clear.'),
      ],
    },
    {
      heading: 'Two-factor authentication (TOTP)',
      body: [
        p('Two-factor adds a one-time code from an authenticator app (Google Authenticator, 1Password, Authy…) as a second step after the password. Like passkeys it is optional and additive — the password still signs the user in, the code is just an extra step — so it can’t lock anyone out.'),
        def('Who must use two-factor', 'The 2FA column in the Users tab enables it per account, with a master “Allow two-factor for all users” checkbox above the list. Enabling it makes 2FA MANDATORY for that user: if they haven’t configured it yet, their next sign-in stops after the password and forces them to set up an authenticator before they get in — they can’t bypass it by simply not enrolling. Both local and directory users qualify; for a directory user it’s a local second factor layered on their directory password. Turning the permission back off removes the requirement (they sign in with the password again).'),
        def('Setting it up', 'Once allowed, the user opens 🔒 Two-factor (next to Sign out), scans the QR with their authenticator app and confirms one code. They then get one-time recovery codes — shown once — to save for a lost phone. Administrators set up their own from App Control → Two-factor. The same secret protects both the app and the admin interface.'),
        def('Signing in', 'After the password, an enrolled user is asked for the current 6-digit code (or one recovery code). A passkey sign-in is already strong authentication, so it skips the code step. Recovery codes can be regenerated at any time, which invalidates the old set. Repeated wrong codes are rate-limited by source IP (a short cooldown) but never disable the account.'),
        def('Turning it off', 'A user turning two-factor off must enter their current code (or a recovery code) first, so a stolen session can’t silently remove it. If a user is locked out of their authenticator and their recovery codes, an administrator can’t read the secret — untick 2FA for them in the Users tab so they can sign in with their password and enrol again.'),
        tip('The secret is stored encrypted and recovery codes only as hashes; deleting a user removes both. If a user loses their authenticator and their recovery codes, an administrator can’t read the secret — turn 2FA off for them (untick the box or have them removed and re-added) so they can sign in with their password and enrol again.'),
      ],
    },
  ],
}

const adminConnections: HelpTopic = {
  id: 'admin-connections',
  title: 'Database Connections',
  subtitle: 'Define Exasol/LLM connections and assign them to users',
  icon: '🗄️',
  sections: [
    {
      heading: 'Defining connections',
      body: [
        p('Define each connection here — the Exasol host, port, user, password, schema and TLS options, plus an optional OpenAI-compatible LLM server — and assign it to one or more users. Each user then sees only the connections assigned to them.'),
        p('Use Test connection to verify the database (and LLM) before saving. Leaving a password or API-key field blank on an existing connection keeps the stored value. Secrets never leave the admin interface.'),
        p('“Create schema & tables” provisions a fresh process-mining schema — it creates the named schema and the required tables (PROJECTS, JOURNEYS, STEPS, METAS, NOTES) if they are missing, using the credentials entered.'),
        warn('This needs a database account with CREATE SCHEMA and CREATE TABLE privileges. Those can only be granted by the database administrator — the application cannot grant them.'),
      ],
    },
    {
      heading: 'Pre-materialized transitions (performance)',
      body: [
        p('Each connection can opt into reading the process map from a prebuilt TRANSITIONS_RAW table instead of computing the directly-follows pairs live on every request — a large speed-up for interactive filtering on big event logs. It is off by default and fails safe: until the table is built (or while a rebuild is in flight) the map falls back to the live query, so it never breaks.'),
        p('Tick “Use pre-materialized transitions” on the connection (it takes effect on the next chart reload — no reconnect needed), then rebuild the table after each load of JOURNEYS. Rebuild it three ways: the Rebuild now button here (shows the last-built time and pair count); a scheduler calling POST /api/connections/<id>/rebuild-transitions with an Authorization: Bearer token (generate the connection’s own token under “Rebuild from a script (API)”, which also shows a ready-to-copy curl example — the token is scoped to that connection, shown once, and stored only as a hash); or by ticking “Also build …” when you Create schema & tables.'),
        p('The active mode is shown as a pill on the process map: ⚡ Pre-materialized (reading the table), ↻ Live query (not enabled), or ⚠ Live (not built) — enabled but the table isn’t ready, so it is running live meanwhile; rebuild it. If a rebuild-enabled connection keeps showing “Live (not built)”, the admin Logging tab records the exact cause under the “materialize” operation.'),
        tip('Whether it pays off depends on how often JOURNEYS changes: ideal for batch loads that are then explored heavily, less so for continuously-updated data (the table is stale until the next rebuild).'),
      ],
    },
  ],
}

const adminApi: HelpTopic = {
  id: 'admin-api',
  title: 'Rebuild from a script (API)',
  subtitle: 'Trigger a per-connection rebuild from a scheduler',
  icon: '🔌',
  sections: [
    {
      heading: 'Per-connection rebuild token',
      body: [
        p('Each connection can issue its own bearer token so an external caller — a cron job or ETL step — can trigger that connection’s pre-materialized transitions rebuild without an admin login. Open the connection in Database Connections, expand “Rebuild from a script (API)”, and Generate / rotate or Revoke the token there. It is shown once, right after generation (copy it then); only its hash is stored, so it cannot be shown again, and rotating or revoking invalidates the previous token immediately.'),
        tip('The token is scoped to its own connection — it cannot rebuild any other connection.'),
      ],
    },
    {
      heading: 'Triggering the rebuild',
      body: [
        p('Call POST /api/connections/<id>/rebuild-transitions on the admin server with header Authorization: Bearer <token>. That section shows a ready-to-copy curl example (with a copy button), pre-filled with your real token while it is still visible, and using the -k flag to skip the TLS certificate check for the self-signed admin certificate. On success the response is {"ok": true, "rows": N, "built_at": …}; on failure, ok:false with an error string.'),
        p('Token-triggered rebuilds are rate-limited per connection, and a connection never runs two rebuilds at once, so a leaked token cannot hammer the database. An admin using the Rebuild now button is not throttled.'),
        tip('Run it right after each load of JOURNEYS so the materialized map reflects the new data. The connection must have “Use pre-materialized transitions” enabled to benefit.'),
      ],
    },
  ],
}

const adminDirectory: HelpTopic = {
  id: 'admin-directory',
  title: 'Directory (LDAP)',
  subtitle: 'Directory sign-in via search + bind',
  icon: '📇',
  sections: [
    {
      heading: 'Directory sign-in',
      body: [
        p('When enabled, the main-app login also accepts directory accounts via search + bind: a read-only service account searches the base DN for the login name, then the app re-binds as that user with the supplied password.'),
        ul(
          'Set the server URI (ldap:// or ldaps://, with optional StartTLS), the service-account bind DN and password, the base DN, and the user filter and attributes.',
          'Test server connection checks the server and service bind alone; Test a user login also resolves and signs in a directory account.',
          'On first successful sign-in a directory user is created locally as a plain, enabled account, so you can assign connections and, if you wish, the admin role.',
        ),
        p('While a directory is configured, the app’s sign-in panel shows a small status light — green when the directory server answers a connection test, red when it does not. The light is hidden entirely when no directory is configured, and you can also hide it while keeping directory sign-in on with the “Show the Authentication Server availability indicator on the login panels” switch in the banner — it governs both the app and admin login panels.'),
        p('By default the admin interface stays local-only. Tick “Also allow directory sign-in to this admin interface” to let directory accounts sign in here too — but only after one has been promoted to admin in the Users tab. Local administrators always work regardless, as a break-glass route.'),
        tip('Admin is never granted from the directory — a directory user stays a normal user until a local admin promotes them.'),
      ],
    },
  ],
}

const adminLogging: HelpTopic = {
  id: 'admin-logging',
  title: 'Logging',
  subtitle: 'The shared, structured application log',
  icon: '🧾',
  sections: [
    {
      heading: 'The application log',
      body: [
        p('The Logging tab is a shared, structured application log written by all three servers (main app, admin interface and compute backend). Each entry records a timestamp, severity, client IP, user, an operation, an optional tag and a message.'),
        p('Severity is a cumulative ladder — INFO, USAGE, WARN, ERROR, DEBUG. Pick the maximum level to record (the cheaper levels are always kept; DEBUG only when explicitly selected). Filter the view by severity, client IP, operation or tag, narrow it with a regular-expression search, page through the results, and Download the current log or Clear it.'),
        def('Tags', 'Where the operation says which code path wrote an entry, a tag is a coarser category that groups an entire activity across operations and severities. Four tags ship today. USER marks every deliberate user action — a successful state-changing request (create, update, delete, connect, run an import, change a setting…) made by a signed-in user, recorded at USAGE. Pick USER in the tag filter for an audit trail of what users did; reads and background polls are not actions and stay at DEBUG. SQL marks every entry that quotes an executed database statement — the per-statement DEBUG trace plus the error and timeout entries — so picking SQL in the tag filter gives you the database traffic on its own, at whatever severity it occurred. BACKUP/RESTORE marks every export, inspect and restore, scheduled or manual, including the failures — the whole custody trail of a backup file in one filter. DATA marks data imports — the start and the result of every import, whether triggered by hand in the integration console or by a file-source watchdog; an import therefore carries both USER (it is an action) and DATA. Pick DATA in the tag filter to see the complete import history: successful imports are recorded at USAGE, and a failure at WARN or ERROR with the reason.'),
        def('Audited actions', 'Security- and configuration-relevant actions are recorded with a dedicated operation tag so you can filter to them: sign-in and sign-out (login / logout), LDAP server and account tests and config changes (ldap), certificate generate / upload / activate / delete (tls), database-connection create / edit / assign / delete and connection and LLM-server tests (connection / llm-test), backup export / inspect / restore (backup), and login-page customization (customize). Deletions are recorded as warnings.'),
        tip('A fresh log file is started automatically once the live log passes the configured size (“New file after N MB”); rotated files are saved under data/logs/.'),
      ],
    },
  ],
}

const adminCustomize: HelpTopic = {
  id: 'admin-customize',
  title: 'Customize',
  subtitle: 'Appearance — the login-page background',
  icon: '🎨',
  sections: [
    {
      heading: 'Login page',
      body: [
        p('The Customize tab sets the login-page background for both sign-in pages — the main app and the admin interface. Keep the default theme colour (which follows light / dark mode), choose a solid colour, or upload a background image (PNG, JPEG, GIF, WebP or SVG, up to ~3 MB, scaled to cover). A live preview shows the result before you save.'),
        p('Over a background image the login panel turns semi-transparent so the image shows through, while the title, fields and buttons stay fully legible. The choice applies to new sign-ins immediately.'),
        tip('More appearance options will appear here over time; for now it covers the login page.'),
      ],
    },
  ],
}

const adminLicense: HelpTopic = {
  id: 'admin-license',
  title: 'License & Demo Mode',
  subtitle: 'Applying a license and the demo grace period',
  icon: '🔑',
  sections: [
    {
      heading: 'Licensing',
      body: [
        p('The application requires a valid license. Upload the license file you were issued in App Control → License; the panel shows who it is licensed to and when it expires, and lets you remove it again.'),
        p('With no valid license the app runs in Demo Mode for a one-time grace period — the sign-in panel shows “Demo Mode — remaining time”, or “No License installed” once that period is spent — after which the compute backend stops until a license is applied. Uploading a valid license during the grace period cancels the shutdown.'),
        tip('The demo period is granted once per installation; restarting does not renew it. The admin interface itself keeps working even when the backend has stopped, so you can always apply a license there.'),
      ],
    },
  ],
}

// ── Chart views ───────────────────────────────────────────────────────────────

const chartViews: HelpTopic = {
  id: 'chartviews',
  title: 'Chart Views',
  subtitle: 'Process map, A/B comparison, individual journey and statistics',
  icon: '📊',
  sections: [
    {
      heading: 'A-Chart',
      body: [
        p('The primary process map. Shows all journeys matching the current filter set as an aggregated directly-follows graph; arrow thickness reflects the selected transition metric. When a project is first selected, A-Chart loads automatically using the last N days of data — N defaults to 30 and is set in Configuration → Dates and Times → Default date window (0 shows the full range).'),
        tip('A date slider sits above the map, in the Date & Metrics card. In Range mode it has two independently draggable thumbs — drag either to move the window start or end; in Day mode a single thumb selects one calendar day. Both thumbs also respond to the arrow keys once focused. Switch modes with the Range / Day control at the right of the metric row, just below the slider.'),
      ],
    },
    {
      heading: 'B-Chart',
      body: [
        p('An independent second process map with its own filter set — use it to explore a different segment (date window, step selection, or meta value). B-Chart starts empty: apply filters and tap Apply, or use the Load button on its empty state.'),
      ],
    },
    {
      heading: 'A/B Comparison',
      body: [
        p('Splits the main area vertically: A-Chart on the left, B-Chart on the right, both visible at once. The sidebar filters operate on the active side — switch it by tapping a panel header or the A/B segmented control at the top of the Filters section. The active panel shows a pencil icon and an “editing” label.'),
        def('Valve (⇄ on the divider)', 'Open: both panels share one viewport, so pan, zoom, reset and node drags mirror instantly. Closed: each panel moves independently; closing snapshots A’s current view into B so they start aligned before diverging. A is always the master.'),
        def('Copy layout (⧉ in A’s header)', 'Transfers A’s complete viewport — zoom, pan and every node position — to B in one tap.'),
        p('A Process Similarity badge floats between the panels, showing the Q score coloured green/blue/red. It refreshes automatically whenever you apply filters or move a date slider in either panel. See the Process Similarity chapter.'),
      ],
    },
    {
      heading: 'Individual Journey',
      body: [
        p('Shows the complete step sequence for a single journey identified by EVENT_ID. The Filters section becomes an Event ID field: type a source identifier (e.g. ORD-000001) or a raw 32-character hash and press Return. Any input that is not already a hash is MD5-hashed automatically before querying, so you never compute a hash by hand.'),
        p('A switch floating over the canvas (top-centre) toggles between two layouts of the same journey:'),
        ul(
          'Flowchart — the directed-follows graph, where a revisited step is drawn as a loop back to the same node.',
          'Swimlane — the journey laid out strictly left-to-right, one column per event in time order, with a lane per node group (coloured by the group). A revisited step simply appears again further right, so there are no loops. A header row above the top lane shows each event’s date/time, and every edge shows the time taken from one node to the next. Below the lanes a cumulative-value line chart plots the running sum of the step scores from the start (a YTD-style total) — a green/red marker per step showing whether it added or subtracted value — so you can read the journey’s value develop from start to end. It pans and zooms as one, with a zoom cluster (out / in / fit / reset) in the lower-right corner like the flowchart.',
        ),
        tip('The swimlane is only for a single journey — it is never used for the aggregated views, where loops are meaningful.'),
        tip('A live suggestion dropdown appears as you type. Each EVENT_ID keeps its own saved node layout (flowchart).'),
        tip('In the flowchart, transitions are labelled with the average transition time. The sidebar metric picker is hidden in this view, since a single journey visits each step once — Count would carry no information.'),
      ],
    },
    {
      heading: 'Statistics',
      body: [
        p('Analyses all journey routes matching the current filters — which it always inherits from Chart A. A Routes / Analytics toggle switches between a searchable, sortable, paginated table of distinct journey variants (with a journeys-over-time chart) and a set of visualisations: the duration histogram, step traffic, and a transition heat map.'),
        tip('If you change a filter after loading, an orange “Filters changed since last load” banner appears with a one-tap Reload button. The journeys-over-time granularity is chosen automatically: ≤14 days → daily, ≤90 days → weekly, otherwise monthly.'),
      ],
    },
  ],
}

// ── Filters ───────────────────────────────────────────────────────────────────

const filters: HelpTopic = {
  id: 'filters',
  title: 'Filters',
  subtitle: 'Metrics, date range, steps, score and meta filters',
  icon: '⛃',
  sections: [
    {
      heading: 'Transition metrics',
      body: [
        p('The Metrics section controls which value drives the thickness, opacity, colour and label of each transition arrow.'),
        def('Count', 'Number of times this transition occurred. The default, always available.'),
        def('Percentage', 'The share of journeys leaving the source node that take this edge — the branching probability at each step. Every node’s outgoing edges add up to 100 %.'),
        def('Journey %', 'The share of all filtered journeys that traverse this edge (edge count ÷ total filtered journeys). Unlike Percentage, the denominator is the whole map, so it shows how common an edge is overall; a value can exceed 100 % for an edge a journey repeats.'),
        def('Avg Time', 'Average elapsed time between the two steps, shown as a readable duration (4m, 1.2h, 3.5d).'),
        def('Min / Max Time', 'Shortest / longest observed elapsed time for this transition.'),
        def('Std Dev', 'Standard deviation of elapsed times — higher values indicate inconsistent transition durations.'),
        tip('Each chart view stores its own metric selection. Each metric has its own colour scale — click the colour legend at the bottom-right of the map to configure them.'),
      ],
    },
    {
      heading: 'Journey-level filters',
      body: [
        p('Every filter works at journey (case) level, so a journey either qualifies in full or not at all.'),
        def('Date range', 'Journeys with at least one event inside the window. Adjustable from the slider above the map.'),
        def('Include Steps', 'Show only journeys that pass through any selected step.'),
        def('Exclude Steps', 'Remove every journey that passes through any selected step. A step chosen for Include is automatically disabled for Exclude, and vice versa.'),
        def('Num Steps', 'Keep journeys whose total step count is within the range.'),
        def('Journey Time', 'Keep journeys whose first-to-last span is within the range.'),
        def('Journey Score', 'Keep journeys whose summed step scores are within the range. Negative scores are supported — drag the right handle below zero to isolate problem paths.'),
        def('Meta 1–3', 'Case-level, case-insensitive contains search. Each is a searchable dropdown: focus the field (or tap the ▾) to see the distinct values from the database, then click one or type to narrow the list. The ⊗ clears the selection.'),
      ],
    },
    {
      heading: 'Applying, resetting and saving',
      body: [
        p('Filters are not applied automatically. Three buttons sit at the bottom of the section:'),
        def('Reset', 'Restores all filters to the project defaults.'),
        def('Save Preset…', 'Captures the current filter state as a named preset (see the Filter Presets chapter).'),
        def('Apply', 'Reloads the map with the current settings. In A/B Comparison only the active side reloads.'),
        p('Filtered Journeys shows matches for the active filters; Total Journeys always reflects the unfiltered project count.'),
      ],
    },
  ],
}

// ── Filter presets ────────────────────────────────────────────────────────────

const filterPresets: HelpTopic = {
  id: 'filterpresets',
  title: 'Filter Presets',
  subtitle: 'Save and reapply named filter configurations',
  icon: '🔖',
  sections: [
    {
      heading: 'What is a preset?',
      body: [
        p('A preset captures a complete snapshot of every filter dimension — date range, included/excluded steps, meta values, step-count, journey-time and score bounds — under a name of your choice. Presets are stored per project, persist between sessions, and are included in Backup & Restore.'),
      ],
    },
    {
      heading: 'Saving, applying, managing',
      body: [
        p('Configure the filters you want, then tap “Save Preset…” between the Reset and Apply buttons and give it a name. The state is captured at that moment — later filter changes do not update the preset.'),
        p('Every chart header shows a Presets picker. Choose a preset to restore all its settings instantly; the chart reloads and the date slider updates to the preset’s window. In A/B Comparison each panel has its own independent Presets picker, so you can apply different presets to A and B at once.'),
        tip('Rename and delete a preset from the small ✎ / 🗑 buttons next to it in the sidebar Presets list.'),
      ],
    },
  ],
}

// ── Process map ───────────────────────────────────────────────────────────────

const processMap: HelpTopic = {
  id: 'processmap',
  title: 'Process Map',
  subtitle: 'Navigation, nodes, groups and context actions',
  icon: '🗺',
  sections: [
    {
      heading: 'Reading the map',
      body: [
        p('Each node is a distinct process step. Arrows show transitions; thickness and opacity reflect the selected transition metric relative to the highest value on the map (for Percentage and Journey % the scale is a fixed 0–100 %). The label shows the value for the active metric — a plain number for Count, a percentage for Percentage / Journey %, or a readable duration for time-based metrics.'),
      ],
    },
    {
      heading: 'Connection colouring',
      body: [
        p('When “Colorise edges by weight” is on, each arrow is tinted using the colour scale configured for the active metric, from the low-end colour (few / short) to the high-end colour (many / long). Thickness always encodes the value independently of colour.'),
        def('Per-metric scales', 'Each metric has its own scale. Defaults: Count → green, Percentage → green, Journey % → green, Avg Time → orange, Min Time → blue, Max Time → red, Std Dev → purple.'),
        tip('Click the colour legend in the bottom-right corner of the map to open the wizard and pick a scale for each metric, with a live preview. “Reset to defaults” restores the built-in scales.'),
        tip('To read the exact figures behind the chart rather than compare edge widths, open the transition table: a ▦ Transitions button in the lower-right of the A-Chart, B-Chart and A/B panels lists every transition with all metrics at once (Count, % Outgoing, Journey %, Avg / Min / Max, Std Dev), searchable and sortable by any column, with a ⧉ Copy button that exports the rows as tab-separated values for a spreadsheet. The button is hidden until you enable it in Configuration → Layout → Transition-table button.'),
      ],
    },
    {
      heading: 'Start and end markers',
      body: [
        def('Green arrow (entry)', 'Appears above every start node — a step with no incoming transitions.'),
        def('Orange arrow (exit)', 'Appears below every end node — a step with no outgoing transitions.'),
        p('When a step belongs to a group, both markers are drawn outside the group’s dashed border so they stay visible.'),
      ],
    },
    {
      heading: 'Navigating & moving nodes',
      body: [
        ul(
          'Scroll / pinch to zoom, drag the background to pan, double-click to fit the graph to the window.',
          'Drag a node to reposition it — saved per project and per chart view; positions snap to a 20 pt grid.',
          'Drag a group box to move all its members at once.',
          '↺ discards custom positions and reverts to the automatic layout.',
          '⤢ fits the graph; the ± buttons zoom precisely.',
        ),
        tip('The quality of the automatic layout depends on the “Optimise layout” toggle in Configuration — when on, crossing minimisation produces a cleaner arrangement on complex graphs.'),
        tip('Inspecting one step in a dense map: hover a node and hold still for the dwell time (one second by default). The node and its incoming and outgoing transitions light up while everything else fades back, so you can trace exactly what leads into and out of it. Move the pointer away (or click, pan or drag) to clear it. Set the delay — 1 s / 2 s / 3 s, or Off — with the “Highlight Trigger” control in Configuration → Steps. This spotlight is available on every process map except the Individual Journey, whose single trace is already sequential.'),
        tip('A 🕸 Flowchart / 🌊 Sankey switch floats at the top of the A-Chart and B-Chart. The Sankey view shows the same data as a left-to-right flow — band width follows the currently selected transition metric (Count, %, Journey %, Avg/Min/Max Time, Std Dev), so switching the metric re-weights the flows. To keep it readable it collapses each cluster of steps that loop among one another into a single ↺ node (named after their shared step group when they have one); hover any band for exact counts, or hover a collapsed node to highlight it and see the full list of steps grouped inside plus their internal-loop total. Your choice of flowchart or Sankey is remembered per user.'),
      ],
    },
    {
      heading: 'Node context menu',
      body: [
        p('Click a node to open a small action card:'),
        def('Require in journeys', 'Adds the step to Include Steps and reloads.'),
        def('Exclude from journeys', 'Adds the step to Exclude Steps and reloads.'),
        def('Show Notes (n)', 'Opens the notes for this node — the count in parentheses is how many it already has. With none it opens the editor to create one; with one or more it opens the list, where you can read them and add another (a node or edge can hold several notes). See the Notes chapter.'),
        def('Show description', 'Displays the full DESCRIPTION text for the step, when it differs from the name.'),
      ],
    },
    {
      heading: 'Node appearance & groups',
      body: [
        p('Colours and shapes (stadium / round / hex / circle) come from the STEPS table and are editable in Configuration → Steps. An orange dot marks an end-of-process step; a score badge in the top-left is green for positive, red for negative, blue for zero. A yellow ✎ badge marks a node with a note.'),
        p('Steps sharing a BELONGS_TO value are wrapped in a dashed, coloured group box with a name pill. The box tint and border are tuned per theme so the group stays clearly visible in both light and dark mode. The +/− badge on the box collapses or expands it — collapsed groups sum connection counts and weight-average the times. “Groups start” in Configuration controls whether groups load Expanded, Collapsed, or in their last Persisted state.'),
      ],
    },
    {
      heading: 'Aggregates (developers)',
      body: [
        p('Developers can abstract sub-processes into Σ super-steps. Click “Σ Select steps to aggregate” (lower-left of the map) to enter pick mode, then click a set of interconnected steps. Use “＋ Add group” to bank that group and start another — banked steps are ringed and locked so a step belongs to only one aggregate. You can bank as many groups as you need.'),
        p('“Create map” opens a dialog with one row per group (a Σ name, a detail-project name, and its own target — same schema, a new schema, or a different connection). It builds ONE high-level project holding all the Σ nodes (each Σ’s black-box metrics computed by the normal engine), plus one detail project per group. The original project is untouched.'),
        p('To add more later, open the high-level map, enter pick mode again, select more original steps and choose “Add to map” — the map is rebuilt from its source with the new Σ step(s) added, and only the new detail project is written.'),
        tip('Each Σ node’s menu offers ⤵ Drill down to open its detail project. A Σ step inherits the group’s BELONGS_TO swimlane when its members share one.'),
        p('A Σ node’s menu offers two drill-downs, both using the original (un-aggregated) numbers — the aggregate is only a way to make the map readable, so the figures always match the real flowchart. “Drill down · new panel” opens the aggregate’s member steps as a sub-process in a panel. “Drill down · in place” expands the Σ node right inside the high-level map — its member sub-steps replace the Σ node, wired to the Σ’s neighbours, while the surrounding steps stay put (other Σ nodes can be expanded too). Collapse everything back with ⤴ Drill up (a node’s menu, or the button above the map).'),
        p('Aggregate projects (and connections holding them) are marked with a Σ in the sidebar. Under Configuration → Aggregations you can hide the aggregate detail projects and detail-only connections to declutter — the high-level map (and any connection holding it or the source) always stays visible, as does whatever you have open.'),
      ],
    },
  ],
}

// ── KPI panel ─────────────────────────────────────────────────────────────────

const kpi: HelpTopic = {
  id: 'kpi',
  title: 'KPI Panel',
  subtitle: 'Journey counts, durations and score tiles',
  icon: '📇',
  sections: [
    {
      heading: 'The tiles',
      body: [
        def('Total Journeys', 'Distinct journeys in the project with no filters applied. Does not change when you adjust filters.'),
        def('Filtered Journeys', 'Distinct journeys matching all current filters — the population the map visualises.'),
        def('Shortest / Avg / Longest Journey', 'Fastest, mean and slowest journey duration in the filtered set, first event to last.'),
        def('Std Dev', 'Standard deviation of journey durations. Low = most journeys take a similar time; high = durations vary widely.'),
        def('Graph Value', 'Sum of (step score × visit count) for every scored node on the map. Visit count is the larger of a node’s incoming and outgoing transition occurrences, so start and end nodes are handled correctly. A higher value means high-scoring steps are visited frequently.'),
        def('Process Goodness', 'A composite quality score for the whole process. Rewards paths where high-scoring steps are reached efficiently and penalises slow or low-scoring routes, with a coverage factor. See the Process Goodness chapter for the formula and worked examples.'),
        def('Process Similarity', 'A/B mode only — floats between the panels. Compares the two filtered processes; see the Process Similarity chapter.'),
      ],
    },
    {
      heading: 'Behaviour',
      body: [
        p('The strip and the date slider appear only once a chart has loaded data, and are hidden on launch, after disconnecting, and on any view not yet loaded. Tap the chevron handle to collapse the strip — the journey counts then appear inline in the handle bar.'),
        p('You can rearrange the strip in place: drag any tile onto another to reorder them, and hover a tile to reveal a × in its top-right corner that hides it. This is the same order and visibility as the Configuration → KPIs list — change it in either place and the other updates instantly. Both are stored per user, so your arrangement follows you between browsers and machines. A tile hidden with its × is switched back on from Configuration → KPIs.'),
        tip('In A/B Comparison, each panel has its own KPI strip. The Process Goodness tile is coloured green when this panel’s value beats the other, red when lower, blue when equal within 0.005.'),
      ],
    },
  ],
}

// ── Process Goodness (full fidelity) ──────────────────────────────────────────

const processGoodness: HelpTopic = {
  id: 'processgoodness',
  title: 'Process Goodness',
  subtitle: 'How the quality score is calculated',
  icon: '◔',
  sections: [
    {
      heading: 'What it measures',
      body: [
        p('Process Goodness is a single number that summarises how well your process is performing across all journeys matching the current filters. It combines three ideas into one score:'),
        ul(
          'Quality — do journeys pass through high-scoring steps?',
          'Efficiency — are journeys short, or do they take a long time?',
          'Coverage — how large a fraction of total journeys do the current filters capture?',
        ),
        p('Higher values are better. A positive score means the process delivers net value relative to its time cost. A negative score means slow, low-scoring routes are dragging overall quality down.'),
        tip('Process Goodness is only shown when at least one step has a SCORE value configured in the STEPS table. If no scores are set, the tile is hidden.'),
      ],
    },
    {
      heading: 'The formula',
      body: [
        p('The score is computed in two stages. First, a raw goodness is calculated across all distinct path patterns:'),
        code('raw = Σ (freq / total) × (sum_of_scores / √n − 0.01 × avg_duration)'),
        p('Where the sum runs over every distinct path pattern in the filtered set. Then a coverage factor is applied:'),
        code('Process Goodness = raw × (filtered_journeys / total_journeys)^0.5'),
        p('That is all. Everything else is just understanding what each symbol means — which the following sections explain one by one.'),
      ],
    },
    {
      heading: 'Inside the formula: each term explained',
      body: [
        def('freq / total', 'The relative frequency of this path pattern. A path taken by 80 out of 100 journeys has freq/total = 0.80. More common paths have a stronger influence on the final score — the formula is a weighted average, not a simple average.'),
        def('sum_of_scores', 'The sum of SCORE values (from the STEPS table) for every step in this path. If a step has no score it contributes zero. A path through high-value steps produces a large positive sum; a path through penalised steps (negative scores) can produce a negative sum.'),
        def('√n  (alpha = 0.5)', 'The square root of the number of steps in the path. Dividing by √n means longer paths must earn proportionally more total score to keep up with shorter paths — but the penalty grows slowly (as a square root, not linearly). A 4-step path divides by 2; a 9-step path divides by 3. This discourages unnecessary detours without harshly punishing genuinely complex processes.'),
        def('0.01 × avg_duration', 'A time penalty. avg_duration is the average total journey time in seconds for this path pattern. Multiplying by 0.01 means every 100 seconds of journey time costs 1.0 point. Fast paths are rewarded; slow paths are penalised. The constant 0.01 is chosen so that moderate durations (a few minutes) impose a small but noticeable penalty.'),
        def('(filtered / total)^0.5  (gamma = 0.5)', 'The coverage factor. If your current filters capture only half of all journeys, this term equals √0.5 ≈ 0.71 and reduces the score by about 29 %. A goodness score computed from a narrow slice of data should be taken with more caution than one computed from the full population. When no filters are active, coverage = 1.0 and the factor has no effect.'),
        tip('All fixed constants — alpha=0.5, time_penalty=0.01, gamma=0.5 — are embedded in the formula. They reflect a balanced default and are not adjustable in the current version.'),
      ],
    },
    {
      heading: 'Example 1 — two paths, short vs. long',
      body: [
        p('A digital checkout process has 100 orders. 85 take the direct path; 15 use a coupon step.'),
        code(
          `Path A  (85 journeys): Browse → Cart → Pay → Confirm
  Scores: 2 + 3 + 10 + 10 = 25    Steps: 4    Avg duration: 30 s

Path B  (15 journeys): Browse → Cart → Coupon → Pay → Confirm
  Scores: 2 + 3 + 1 + 10 + 10 = 26    Steps: 5    Avg duration: 60 s`,
        ),
        p('Calculation for Path A:'),
        code(
          `quality   = 25 / √4 = 25 / 2     = 12.50
time cost = 0.01 × 30            =  0.30
path score = 12.50 − 0.30        = 12.20
weighted   = 0.85 × 12.20        = 10.37`,
        ),
        p('Calculation for Path B:'),
        code(
          `quality   = 26 / √5 ≈ 26 / 2.24  = 11.61
time cost = 0.01 × 60            =  0.60
path score = 11.61 − 0.60        = 11.01
weighted   = 0.15 × 11.01        =  1.65`,
        ),
        p('Combined result (all 100 journeys in filter, 100 total):'),
        code(
          `raw = 10.37 + 1.65 = 12.02
coverage = 100 / 100 = 1.0    →  factor = √1.0 = 1.00

Process Goodness = 12.02 × 1.00 = +12.02`,
        ),
        tip('Notice that Path B contributes slightly less per journey (11.01 vs 12.20) even though it collects one extra score point. The longer path and slower duration partially offset the extra point — the formula captures this tradeoff automatically.'),
      ],
    },
    {
      heading: 'Example 2 — a failed-payment path with negative scores',
      body: [
        p('The same checkout process, but now 10 orders encounter a payment failure and are refunded. Step scores: Pay Failed = −10, Refund = −5.'),
        code(
          `Path A  (80 journeys): Browse → Cart → Pay → Confirm
  Scores: 25    Steps: 4    Avg duration: 30 s    (same as before)

Path B  (10 journeys): Browse → Cart → Coupon → Pay → Confirm
  Scores: 26    Steps: 5    Avg duration: 60 s    (same as before)

Path C  (10 journeys): Browse → Cart → Pay → Pay Failed → Refund
  Scores: 2 + 3 + 10 + (−10) + (−5) = 0    Steps: 5    Avg duration: 90 s`,
        ),
        p('Path C contributes:'),
        code(
          `quality   = 0 / √5 = 0
time cost = 0.01 × 90 = 0.90
path score = 0 − 0.90        = −0.90
weighted   = 0.10 × (−0.90)  = −0.09`,
        ),
        p('Combined result:'),
        code(
          `Path A weighted: 0.80 × 12.20 =  9.76
Path B weighted: 0.10 × 11.01 =  1.10
Path C weighted:              = −0.09

raw = 9.76 + 1.10 − 0.09 = 10.77
coverage = 1.0

Process Goodness = +10.77   (was +12.02 before failures appeared)`,
        ),
        p('The failed-payment path reduces the score from +12.02 to +10.77 — a drop of 1.25 points — even though it affects only 10 % of journeys. The combined effect of zero quality score and additional time makes it a net negative contributor.'),
        tip('Use this pattern to detect problem paths. When you notice a sudden drop in Process Goodness between two date periods, filter to isolate paths through specific problem steps — the score will confirm whether those paths are truly responsible for the decline.'),
      ],
    },
    {
      heading: 'Example 3 — the coverage penalty when filtering',
      body: [
        p('You apply a region filter — “Europe only” — and now only 40 of the 100 total orders match. Within those 40 orders there are no payment failures, so the raw goodness is the same clean +12.02.'),
        p('However, the coverage factor now kicks in:'),
        code(
          `coverage = 40 / 100 = 0.40
factor   = √0.40 ≈ 0.632

Process Goodness = 12.02 × 0.632 ≈ +7.60`,
        ),
        p('The filtered Europe result (+7.60) looks worse than the global result (+12.02), not because Europe performs worse, but because the filter captures a smaller proportion of the total population. The score reflects both quality and representativeness.'),
        tip('To compare two segments fairly, switch to A/B Comparison mode: set A to one segment and B to the other. The Process Goodness tile in each panel applies the same formula independently, so the scores are directly comparable even with different journey counts.'),
      ],
    },
    {
      heading: 'Requirements and limitations',
      body: [
        ul(
          'At least one step must have a non-zero SCORE value in the STEPS table. Without scores the tile is hidden.',
          'The query groups journeys by path pattern — on very large, heavily filtered datasets it may take several seconds. A 30-second timeout applies; if it expires the tile shows “—”.',
          'Average duration per path pattern is used as the time component. Individual journeys may differ from this average.',
          'Steps with no SCORE set contribute 0 to the quality sum — they neither help nor hurt.',
          'The score can be negative when slow, low-scoring paths dominate the filtered set.',
        ),
        warn('Process Goodness is a relative indicator, not an absolute benchmark. Use it to spot trends over time, compare segments in A/B mode, or monitor the impact of process changes — not as a standalone pass/fail threshold.'),
      ],
    },
  ],
}

// ── Process Similarity (full fidelity) ────────────────────────────────────────

const processSimilarity: HelpTopic = {
  id: 'processsimilarity',
  title: 'Process Similarity',
  subtitle: 'How Q(T₁, T₂) compares two filtered processes',
  icon: '⇄',
  sections: [
    {
      heading: 'What it measures',
      body: [
        p('Process Similarity Q(T₁, T₂) is a single number between 0 and 1 that answers: how behaviourally alike are the two process views loaded in A-Chart and B-Chart?'),
        p('A score of 1.0 means the two processes are identical — every variant is explained equally well by both graphs and the same scored steps are visited in the same proportion. A score of 0.0 means they share almost nothing. Values in between indicate partial overlap.'),
        p('Unlike Process Goodness, which measures how good a single process is, Process Similarity is a comparison metric. Use it to confirm that two filter segments really are behaving differently, or to verify that a process change has had a measurable effect.'),
        tip('Process Similarity only appears in A/B Comparison mode, as a floating badge between the two panels. It refreshes automatically whenever you apply filters or move a date slider in either panel.'),
      ],
    },
    {
      heading: 'The formula',
      body: [
        p('Q is a weighted average of three components, each between 0 and 1:'),
        code('Q(T₁, T₂) = 0.4 · Q_var  +  0.4 · Q_nodes  +  0.2 · Q_cov'),
        def('Q_var  (weight 40 %)', 'Variant alignment agreement. Measures how consistently both graphs explain the same journey variants. If both graphs handle a variant equally (both replay it perfectly, or both fail equally), Q_var is high. If one graph handles a variant much better than the other, Q_var is low.'),
        def('Q_nodes  (weight 40 %)', 'Node agreement weighted by importance. A Jaccard-style ratio comparing which scored steps are actually visited — under each graph — per variant. Steps with a higher absolute score value count more. If both graphs visit the same high-value steps in the same variants, Q_nodes approaches 1.'),
        def('Q_cov  (weight 20 %)', 'Joint coverage. The fraction of variant frequency that is explained perfectly (zero missing edges) by both graphs simultaneously. A high value means most journeys fit neatly into both process models.'),
        tip('The 40/40/20 weights reflect that structural similarity (Q_var) and scored-step agreement (Q_nodes) are equally important, while coverage is a useful but secondary signal.'),
      ],
    },
    {
      heading: 'Alignment cost — the key building block',
      body: [
        p('For each journey variant (a specific sequence of steps), the formula computes an alignment cost for each graph:'),
        code('cost_T(v) = missing_edges / total_edges_in_variant'),
        p('A “missing edge” is a consecutive step pair in the variant that does not appear as a transition in the graph. If all transitions exist, cost = 0 (perfect fit). If half are missing, cost = 0.5. A variant with only one step (no edges) is skipped.'),
        p('This is a practical approximation of formal process-mining alignment. It runs in linear time per variant and requires no external solver, making it fast enough to run automatically on every panel reload.'),
        p('One property follows directly: each side’s variants always replay perfectly on the graph mined from the same journeys (cost = 0 on their home side). Any misfit is therefore one-sided, which makes Q_var behave as a strict structural test — 1.0 when every variant’s edges exist in both graphs, 0.0 as soon as any variant uses an edge the other side lacks. The examples below show how Q_nodes and Q_cov then differentiate the score.'),
        tip('The variant set is capped at 500 per side (1 000 combined). When the cap is exceeded the badge is hidden rather than showing a misleading score computed from a biased sample. All example numbers below are verified outputs of the actual implementation.'),
      ],
    },
    {
      heading: 'Example 1 — shared core, one exclusive path',
      body: [
        p('A-Chart shows European orders; B-Chart shows North American orders. 90 % of all journeys take the shared main route; 10 % (EU only) redeem a coupon on the way.'),
        code(
          `Main route  (90 % of combined journeys, both sides):
  Browse → Cart → Pay → Confirm
  Edges exist in both graphs → cost_A = 0,  cost_B = 0

Coupon route  (10 %, EU only):
  Browse → Cart → Coupon → Pay → Confirm   (4 edges)
  All edges in A-graph → cost_A = 0
  Cart→Coupon and Coupon→Pay missing in B-graph
  cost_B = 2/4 = 0.50`,
        ),
        p('The only misfitting variant is one-sided (A explains it, B cannot), so Q_var collapses; the valuable steps and 90 % of the traffic still agree:'),
        code(
          `Q_var   = 0.00   (the coupon misfit is entirely one-sided)

Scored steps: Pay = +10, Confirm = +10 — present in BOTH variants
  main route:   visit_A = visit_B = 1.0        → min = max = 20
  coupon route: visit_A = 1.0, visit_B = 0.50  → min = 10, max = 20
Q_nodes = (0.90×20 + 0.10×10) / (1.00×20) = 0.95
Q_cov   = 0.90   (90 % of frequency fits both perfectly)

Q = 0.4×0.00 + 0.4×0.95 + 0.2×0.90 = 0.56  → blue`,
        ),
        tip('A blue mid-range score with healthy shared volume is the signature of “same core process, side-specific extras”. Q_var reacts decisively to the exclusive path, while Q_nodes and Q_cov keep the score well above red.'),
      ],
    },
    {
      heading: 'Example 2 — same period, different quality paths',
      body: [
        p('A-Chart shows successfully confirmed orders; B-Chart shows the same date range filtered to orders with a “Pay Failed” step — equally many journeys on each side. These are structurally different populations.'),
        code(
          `Variant A  (100 % of A-side, 50 % combined):
  Browse → Cart → Pay → Confirm   (3 edges)
  cost_A = 0;  Pay→Confirm missing from B-graph → cost_B = 1/3

Variant B  (100 % of B-side, 50 % combined):
  Browse → Cart → Pay → Pay Failed → Refund   (4 edges)
  cost_B = 0;  Pay→Pay Failed and Pay Failed→Refund missing
  from A-graph → cost_A = 2/4 = 0.50

Scored steps: Pay = +5, Confirm = +10, Pay Failed = −10, Refund = −5
(absolute values are used as weights)`,
        ),
        code(
          `Q_var   = 0.00   (each side fits only its own variant)

Q_nodes: variant A carries Pay+Confirm (weight 15),
         variant B carries Pay+Failed+Refund (weight 20):
  variant A: visit_A = 1.0, visit_B = 2/3  → min = 10,  max = 15
  variant B: visit_B = 1.0, visit_A = 0.5  → min = 10,  max = 20
  Q_nodes = (0.5×10 + 0.5×10) / (0.5×15 + 0.5×20) ≈ 0.57

Q_cov   = 0.00   (neither variant fits both graphs perfectly)

Q = 0.4×0.00 + 0.4×0.57 + 0.2×0.00 = 0.23  → red`,
        ),
        p('A score of 0.23 correctly signals strong divergence — the happy-path and failure-path populations are fundamentally different processes. Q_nodes stays moderate only because both share the journey up to Pay.'),
      ],
    },
    {
      heading: 'Example 3 — before and after a process change',
      body: [
        p('A-Chart shows January (before a redesign); B-Chart shows February (after). The redesign removed a Review step. 70 % of combined journeys take the new route (shared), 30 % the old Review route (January only).'),
        code(
          `New route (70 %): Browse → Submit → Approve → Complete
  Both graphs contain these edges → cost_A = 0, cost_B = 0

Old route (30 %, Jan only):
  Browse → Submit → Review → Approve → Complete   (4 edges)
  cost_A = 0  (all edges in the Jan graph)
  Submit→Review and Review→Approve missing from the Feb graph
  cost_B = 2/4 = 0.50

Scored steps: Approve = +8, Complete = +10 — in both variants`,
        ),
        code(
          `Q_var   = 0.00   (the old route is a one-sided misfit)

Q_nodes: new route: visit_A = visit_B = 1.0       → min = max = 18
         old route: visit_A = 1.0, visit_B = 0.5  → min = 9, max = 18
  Q_nodes = (0.70×18 + 0.30×9) / (1.00×18) = 0.85

Q_cov   = 0.70   (70 % of frequency fits both graphs perfectly)

Q = 0.4×0.00 + 0.4×0.85 + 0.2×0.70 = 0.48  → blue`,
        ),
        p('A blue 0.48 tells the true story: the redesign did change the structure (the old Review route no longer replays on February’s graph), while the scored steps and most of the traffic behave the same. As the old route’s share fades in later periods, Q_cov and Q_nodes rise and the score climbs toward green — reaching 1.0 once every remaining variant fits both graphs.'),
        tip('Use this pattern to validate process changes: Q = 1.0 means no structural difference at all; a mid-range blue confirms a real structural shift with a shared core; red means the two periods barely share behaviour.'),
      ],
    },
    {
      heading: 'Colour thresholds and limitations',
      body: [
        ul(
          'Green: Q ≥ 0.70 — the two processes are behaviourally similar.',
          'Blue: 0.30 < Q < 0.70 — moderate similarity; some paths are shared, others differ.',
          'Red: Q ≤ 0.30 — strong divergence; fundamentally different behaviour.',
        ),
        warn('Process Similarity is a relative indicator, not an absolute benchmark. It depends on which steps have SCORE values — if none do, Q_nodes defaults to 1.0 and only Q_var and Q_cov contribute. It is also sensitive to the route limit.'),
        ul(
          'The practical guard caps input at 500 variants per side (1 000 combined). When the cap is hit the badge is hidden.',
          'Alignment cost is an edge-coverage approximation, not a formal Petri-net alignment. It may slightly overestimate similarity for processes with loops or repeated steps.',
          'Q is symmetric: Q(A, B) = Q(B, A). The same value appears for both panels.',
        ),
      ],
    },
  ],
}

// ── Simulation (full fidelity) ────────────────────────────────────────────────

const simulation: HelpTopic = {
  id: 'simulation',
  title: 'Simulation',
  subtitle: 'Synthetic process data from a calibrated Markov model',
  icon: '🎲',
  sections: [
    {
      heading: 'What is simulation?',
      body: [
        p('The Simulation view generates synthetic event logs that statistically resemble your real process. It builds a first-order Markov chain from the currently loaded process graph, then walks that chain to produce journeys with the same three fields your database contains: a journey identifier, a step name, and a timestamp.'),
        p('Every synthetic journey follows the routing probabilities and timing distributions observed in your actual data. This makes the generated log useful for load-testing, what-if analysis, training-data generation, or simply exploring “what would 10 000 more journeys through this process look like?”'),
        tip('The simulation uses the process graph currently loaded in Chart A, including any date-range and step filters. Apply your desired filters before running to calibrate the model on a specific slice of your data.'),
      ],
    },
    {
      heading: 'How the model is calibrated',
      body: [
        p('The calibration algorithm reads three things from the displayed process graph:'),
        def('Transition probabilities', 'For every step with outgoing transitions, the occurrence counts are normalised to probabilities. A step with 600 transitions to “Approve” and 400 to “Reject” routes 60 % of simulated journeys to Approve and 40 % to Reject.'),
        def('Duration distributions', 'Each directed edge carries an average duration and a standard deviation from the real data. The simulator fits a lognormal distribution to these two numbers and samples from it to advance the clock on each transition. Lognormal is the correct shape for process durations: strictly positive and right-skewed, matching the long tail of slow cases seen in practice.'),
        def('Start steps', 'Steps whose incoming frequency is less than 20 % of their outgoing frequency are identified as likely entry points. Their relative frequency as first steps is used to sample the opening step of each journey.'),
        p('If an edge has timing data in only one direction (average without standard deviation, or vice versa), the simulator uses the available value only. If no timing data is present for an edge, a one-hour lognormal is used as a default. Start steps are always identified from the original graph before exclusions, so removing a step never creates a false entry point.'),
      ],
    },
    {
      heading: 'Arrival process',
      body: [
        p('New journeys are born according to a Poisson process: the gap between consecutive journey start times is drawn from an exponential distribution parameterised by “Average inter-arrival (hours)”. This is the standard model for arrivals in queueing theory and discrete-event simulation.'),
        p('A Poisson process is memoryless: knowing that no journey started in the last two hours tells you nothing about when the next will start. This correctly models processes where cases are independently initiated — order placements, patient admissions, support tickets, and so on.'),
        def('Average inter-arrival (hours)', 'The mean number of hours between consecutive journey start times. A value of 1.0 means one new journey starts every hour on average. It controls the spread of timestamps in the exported CSV, but does not affect routing or cycle times.'),
        tip('To estimate the correct rate, check the “Journeys over time” chart in the Statistics view: divide the journey count by the time span in hours.'),
      ],
    },
    {
      heading: 'Simulation parameters',
      body: [
        def('Journey Count', 'How many complete journeys to generate. Higher counts produce more stable variant distributions and smoother histograms but take longer. For a first run, 200–500 is usually enough to see the dominant process shape.'),
        def('Start Date', 'The date assigned to the first simulated journey’s opening event. Subsequent events are timestamped relative to this anchor using the inter-arrival times and step durations.'),
        def('Max Steps per Journey', 'Hard cap on the number of steps per journey — prevents rework loops from running forever. If a journey hits the cap it is included as-is, with a potentially incomplete path. The default (60) suits most real-world processes.'),
        tip('If you see many journeys with exactly 60 steps in the Variants table, the Max Steps cap is being hit. Increase it if your process genuinely contains long rework loops, or add the looping step to the Excluded Steps list.'),
      ],
    },
    {
      heading: 'Excluded and required steps',
      body: [
        def('Excluded steps', 'Removed from the Markov model entirely before simulation begins — all transitions to and from them are discarded. Use this to model a process improvement, e.g. removing a manual approval step to see the flow when it is automated away. Steps that become unreachable as a result are automatically excluded too, transitively.'),
        def('Required steps', 'A post-simulation filter: only journeys that visit every required step at least once are kept. The engine generates the full configured count and then discards those that do not qualify, so the reported total can be lower than the configured Journey Count if the required steps are rare.'),
        p('The two lists are mutually exclusive — a step chosen as excluded cannot also be required.'),
      ],
    },
    {
      heading: 'Worked example — a fork process',
      body: [
        p('Suppose the observed A-Chart graph is a simple fork: after Start, 70 % of cases go through the Fast branch and 30 % through the Slow branch, then both rejoin at End.'),
        code(
          `Observed transitions (calibration input):
  Start → Fast   occurrences 700   avg 2 min,  sd 30 s
  Start → Slow   occurrences 300   avg 2 min,  sd 30 s
  Fast  → End    occurrences 700   avg 5 min,  sd 1 min
  Slow  → End    occurrences 300   avg 40 min, sd 8 min`,
        ),
        p('The engine derives the Markov model:'),
        code(
          `Start step   : Start   (in/out ratio < 0.2 → entry point)
P(Fast | Start) = 700 / 1000 = 0.70
P(Slow | Start) = 300 / 1000 = 0.30
Fast → End, Slow → End are the only continuations (probability 1.0)

Edge durations → fitted lognormal(μ, σ) per edge, floor 60 s`,
        ),
        p('Running 1 000 journeys, each walk starts at Start, samples Fast or Slow by those probabilities, draws a duration from the fitted lognormal on each edge, and stops at End (an end-of-process step). The output converges to roughly:'),
        code(
          `Variant "Start → Fast → End"   ≈ 700 journeys (70 %)   avg ≈ 7 min
Variant "Start → Slow → End"   ≈ 300 journeys (30 %)   avg ≈ 42 min

Cycle-time histogram: a tall early peak (the Fast branch) and a
smaller, wider hump further right (the Slow branch) — bimodal,
exactly as the two-branch structure predicts.`,
        ),
        tip('Because sampling is random, your counts will vary slightly run to run — around 700/300, not exactly. Raise the Journey Count for a tighter match to the observed proportions. Set the RNG-free expectation by watching the percentages in the Variants tab converge as you increase the count.'),
      ],
    },
    {
      heading: 'What-if example — automating the slow branch',
      body: [
        p('Add “Slow” to the Excluded steps list and run again. The engine removes Start→Slow and Slow→End, then re-normalises: now 100 % of journeys take the Fast branch.'),
        code(
          `After excluding "Slow":
  P(Fast | Start) = 700 / 700 = 1.00

Result: one variant "Start → Fast → End", ~1000 journeys,
avg ≈ 7 min, and a single-peaked (unimodal) cycle-time histogram.`,
        ),
        p('Comparing the two runs quantifies the impact of the improvement: removing the slow branch collapses the bimodal distribution to a single fast peak and cuts the average cycle time dramatically — all without touching the database.'),
        tip('Store each run in a slot (Sim-A / Sim-B), then select them as the A and B data sources in the Sampling section to compare the two synthetic processes side-by-side in A/B Comparison — including a Process Similarity score between them.'),
      ],
    },
    {
      heading: 'Reading the results',
      body: [
        p('After a run, six KPI tiles summarise the output — Journeys, Avg cycle time, Shortest, Longest, Std dev, and Variants — above four tabs:'),
        def('Flow', 'The directly-follows graph of the simulated log, rendered with the same interactive flow chart used everywhere else. Because simulation is probabilistic, this graph resembles but is not identical to the real one — with a small Journey Count, rare edges may not be sampled at all.'),
        def('Variants', 'A ranked table of every distinct path, ordered by frequency, with count, share and average cycle time.'),
        def('Charts', 'A cycle-time distribution histogram and a top-variants bar chart. A unimodal, right-skewed histogram is typical of a well-behaved process; a bimodal shape often signals two fundamentally different paths — check the Variants tab for the split.'),
        def('Event log', 'The raw event rows (JOURNEY_ID, STEP, EVENT_TIME). Export the full log as CSV with the Export button.'),
      ],
    },
    {
      heading: 'Exporting the event log',
      body: [
        p('Export CSV saves the full event log — one row per event, three columns:'),
        code('JOURNEY_ID,STEP,EVENT_TIME'),
        p('The file is structurally identical to a JOURNEYS export from Exasol, so you can import it into another process-mining tool, load it into Excel or pandas, feed it back into an Exasol JOURNEYS table as a test sample set, or use it as labelled training data for ML models.'),
      ],
    },
    {
      heading: 'Limitations and assumptions',
      body: [
        p('The simulator is a first-order Markov model: each routing decision depends only on the current step, not on what came before. If your real process has strong history-dependent routing — for example, cases rejected once behaving very differently on retry — the model will not capture this.'),
        ul(
          'Long-range dependencies and case attributes (META_1–3) are not modelled — there is no concept of a customer segment or region that influences routing.',
          'Resource constraints and queues are not modelled. Cycle times are sampled independently per event; doubling volume does not increase waiting time.',
          'The model calibrates from the visible graph only. If the active filter excludes date ranges or step types, the model reflects only that subset.',
          'Very rare transitions may have unreliable duration estimates — a standard deviation estimated from two or three observations is noisy.',
        ),
        warn('Do not use simulation results as a substitute for real data analysis when making production decisions. The simulation reproduces the statistical structure of your process — but not individual journey behaviour, seasonal effects, or emergent properties from resource contention.'),
      ],
    },
  ],
}

// ── Conformance Check ─────────────────────────────────────────────────────────

const conformance: HelpTopic = {
  id: 'conformance',
  title: 'Conformance Check',
  subtitle: 'Compare the actual process against target norms',
  icon: '🛡️',
  sections: [
    {
      heading: 'What it does',
      body: [
        p('Conformance Check overlays target values (“norms”) on any transition metric and shows, edge by edge, whether the actual process meets them. Switch metrics with the chips at the top — norms are stored per project and per metric.'),
        def('For Count', 'Norms are percentages of the total traffic leaving the same source node. A norm of 50 % on A→B means “at most half of everything leaving A should go to B”.'),
        def('For time metrics', 'Norms are absolute values (seconds), compared directly against the edge’s Avg/Min/Max/Std-Dev time.'),
      ],
    },
    {
      heading: 'Setting and reading norms',
      body: [
        p('Click “Edit norms”, then click an edge and type its target. In view mode each edge turns green or red depending on whether the actual value meets the norm; the “Norm is a minimum” toggle flips the comparison so the actual must be ≥ the norm instead of ≤.'),
        tip('For the Count metric the editor shows a live “remaining %” as you type — how much is already assigned to the source node’s other outgoing edges and how much is left to reach 100 % — and warns in red if your value would push the node’s outgoing norms over 100 %.'),
        p('“Show gaps” opens the full gap-analysis table — from, to, actual, norm, delta and status — sorted with violations first. The gap analysis is also appended to the AI Documentation report.'),
        tip('Norms round-trip through Backup & Restore, so a target model built once can be shared or moved between installations.'),
      ],
    },
  ],
}

// ── Happy Path ────────────────────────────────────────────────────────────────

const happyPath: HelpTopic = {
  id: 'happypath',
  title: 'Happy Path',
  subtitle: 'Define ideal step sequences and measure real conformance',
  icon: '🪧',
  sections: [
    {
      heading: 'Defining an ideal path',
      body: [
        p('A Happy Path is the ideal sequence a process should follow. Create one, then add steps in order. The left panel shows the actual process map; the right panel is your ideal definition — toggle Edit mode to add (＋), reorder (▲ ▼) or remove (⊖) steps.'),
        def('⑂ Split', 'Add a split where the process may legitimately take one of several alternatives — each is a branch you fill with its own steps, so a process with legitimate variations is scored fairly. Give the split a name with its ✎ button.'),
        def('Rejoin & continue', 'A split’s branches reconverge: any steps you add after a split are the shared continuation that all branches lead into. When a split has a continuation you can name the rejoin point too (the ✎ Rejoin button on the split, shown as ⑃ in the diagram). If a split is the last thing on the path, its branches are simply alternative endings — there is no rejoin to name.'),
        def('Nesting', 'A branch can itself contain a split, so you can branch further inside an already-branched path — the editor and the diagram nest accordingly.'),
        tip('Drag the divider between the two panels to widen the ideal-path editor (handy for deeply nested splits); double-click it to reset. The width is remembered.'),
      ],
    },
    {
      heading: 'The conformance score',
      body: [
        p('The score is a journey-count-weighted average of edge coverage: for each real journey variant, the fraction of the ideal path’s transitions that the variant actually contains, weighted by how many journeys followed it.'),
        ul(
          '1.00 — every journey follows the ideal path perfectly.',
          '0.00 — no journey shares a single transition with the ideal sequence.',
        ),
        p('Every start-to-end route through the splits is considered, and each journey is scored against the route it matches best — so a case taking a legitimate alternative is not unfairly penalised.'),
        tip('Steps in your ideal path that are absent from the currently filtered process are shown dimmed, so you can immediately see which ideal steps never actually occur under the current filters.'),
      ],
    },
  ],
}

// ── Sampling ──────────────────────────────────────────────────────────────────

const sampling: HelpTopic = {
  id: 'sampling',
  title: 'Journey Sampling',
  subtitle: 'Representative subsets for fast, meaningful analysis',
  icon: '▤',
  sections: [
    {
      heading: 'Why sample?',
      body: [
        p('Because samples are shared by everyone on the connection, the Sampling section is available to Power users and administrators only — Regular users don’t see it (see Users & Permissions).'),
        p('On very large event logs, working with a representative subset keeps exploration interactive while preserving the process’s shape. Create up to three named sample sets from the original data; the A and B chart slots can each select their own sample independently.'),
        p('Samples are written to a SAMPLE_SET column on the JOURNEYS table (added automatically on first use). The original rows are never modified, and deleting a sample removes only its rows.'),
        p('Because sample sets live in the project database, they are shared by everyone connected to that project — unlike your personal settings and filter presets, which are stored per user. Creating or deleting a sample changes it for all users of the project.'),
      ],
    },
    {
      heading: 'The three strategies',
      body: [
        def('Random', 'Uniform random journey selection. The simplest baseline — fast and unbiased, but rare variants may be under-represented.'),
        def('Temporal Stratified', 'Proportional selection across equal calendar-month buckets, so the sample preserves the time distribution of the original — useful when volume varies seasonally.'),
        def('Path Diversity', 'Coverage-maximising selection across distinct journey variants, so rare paths are more likely to appear — useful when you care about the full variety of behaviour, not just the common cases.'),
      ],
    },
    {
      heading: 'Using samples & simulations as A/B sources',
      body: [
        p('In the Sampling section, each of the A and B slots has a picker that selects Original data, one of the three sample sets, or a stored Simulation result (Sim-A / Sim-B). This is how you feed simulated processes into A/B Comparison to compare them against real data — or against each other.'),
      ],
    },
  ],
}

// ── AI Documentation ──────────────────────────────────────────────────────────

const aiDocumentation: HelpTopic = {
  id: 'ai',
  title: 'AI supported Documentation',
  subtitle: 'AI-powered process analysis and a structured report',
  icon: '🧠',
  sections: [
    {
      heading: 'How it works',
      body: [
        p('The report is produced in two stages. First a language model does the analysis: it is sent ONLY the current A-Chart transition table and an instruction, and returns structured findings (title, executive summary, sections). Then the server assembles those findings — together with the process-flow Sankey and the locally-computed Happy Path and Conformance sections — into a polished, print-ready HTML report styled with your organisation’s accent and letterhead.'),
        p('The Happy Path and Conformance sections, the Sankey and your notes are computed on your own servers and are never sent to the model — only the aggregated transition table is.'),
        p('The report opens with a cover and executive summary, then a clickable table of contents; each topic (Analysis, Process flow, Conformance, Happy Path, Journey Paths, Notes) starts on its own page under a large title, and the links jump to it both on screen and in the exported PDF. The Notes chapter splits your project notes into Open and Resolved, each sorted by severity (most severe first).'),
        tip('The report is shown in its own frame; use ⎙ Save as PDF (browser print) to export it. Your administrator configures the report’s language model, accent/letterhead and the per-connection/project analysis prompt in the admin Reporting tab — separate from the interactive LLM on the connection.'),
      ],
    },
    {
      heading: 'Requirements',
      body: [
        ul(
          'A report language model — set in the admin Reporting tab; if none is set it falls back to the LLM attached to the active connection.',
          'Any OpenAI-compatible endpoint works: local servers (Ollama, llama.cpp, vLLM, LM Studio) or cloud APIs.',
          'Happy Path and Conformance sections appear only when a power user/administrator has defined the underlying paths and norms.',
        ),
        warn('AI models can produce results that are incorrect, incomplete or misleading. Independently verify every finding before acting on it.'),
      ],
    },
  ],
}

// ── Notes ─────────────────────────────────────────────────────────────────────

const notes: HelpTopic = {
  id: 'notes',
  title: 'Process Notes',
  subtitle: 'Annotate nodes and edges with sticky notes',
  icon: '🗒',
  sections: [
    {
      heading: 'Creating and finding notes',
      body: [
        p('Click a node or an edge and choose “Show Notes” to add an annotation. A yellow ✎ badge marks any node or edge that carries a note. The Notes view lists every note for the project — newest first — independent of the current filters.'),
        p('Each note records its author, who last contributed, and the complete filter context at the time it was created, so the observation stays interpretable later. The author is the signed-in application user — shown by real name (the directory “cn”) for LDAP accounts — not the shared database login.'),
        p('A note is a thread. Opening it shows all comments so far on top (read-only) and an “Add a comment” box below: anyone who can see the note — the author, and other users for a shared note — can add a comment, which is placed at the top of the thread and recorded with their name and the time. Give the note (when you create it) and each comment a short title; the most recent title is shown as the note’s heading, separately from the body, in both the list and the node’s note panel. Only the author can change the note’s importance or sharing, or delete the whole thread.'),
        p('Give each note an importance — NORMAL (the default), INFO, IMPORTANT or URGENT — shown as a coloured badge in the list. Mark a note as “shared” to make it visible to other users of the same database, and tick “resolved” once the issue it describes is closed — a green ✓ Resolved badge then appears in the list.'),
        p('The Notes view can be filtered by text search, type (node / edge), importance, status (unresolved / resolved), author, and time window (any time, or the last 7 / 30 / 90 days); the counter shows how many of the project’s notes match. It can be sorted by date (newest or oldest first) and optionally grouped by importance (on by default), and the list is paged — choose 5, 10 or 20 notes per page and step through with Prev / Next. A KPI strip across the top shows the note count for each importance level, least on the left through most urgent on the right, coloured to match the badges.'),
      ],
    },
    {
      heading: 'Storage',
      body: [
        p('Notes are stored in a NOTES table in your Exasol database, created automatically on first use if the connecting user has CREATE TABLE permission. This means notes travel with the data and are visible to every user of that database (subject to the shared flag), not just on the machine that wrote them.'),
      ],
    },
  ],
}

// ── Backup & Restore ──────────────────────────────────────────────────────────

const backup: HelpTopic = {
  id: 'backup',
  title: 'Backup & Restore',
  subtitle: 'Export and import your settings and annotations',
  icon: '💾',
  sections: [
    {
      heading: 'What is included',
      body: [
        p('A backup exports everything except the event data itself: connections and servers, filter presets, happy paths, target norms, saved node layouts, LLM prompt templates and app preferences — as a single JSON file. Passwords and API keys are included only if you tick the corresponding boxes.'),
        tip('The format is interchangeable with the macOS version of the app, so a backup taken there restores here and vice-versa.'),
      ],
    },
    {
      heading: 'Encryption',
      body: [
        p('Set an encryption password to protect the file with AES-256-GCM (PBKDF2-HMAC-SHA256, 100 000 iterations, a random 16-byte salt and 12-byte nonce). Restore inspects the file first and shows a summary — connection count, projects, whether layouts/norms/happy-paths/presets are present — before you commit, and lets you choose exactly which categories to restore.'),
        warn('If you include passwords or API keys without setting an encryption password, they are written in plain text in the JSON file. Set a password whenever the backup contains secrets.'),
      ],
    },
    {
      heading: 'Scheduled (automatic) backups',
      body: [
        p('The Backup tab can also write an encrypted backup automatically on a schedule, for as long as the admin server is running. Enable it, choose how often it runs and set an encryption password — the password is stored encrypted on the server so unattended backups can run, and is never shown again (leave it blank on a later save to keep it).'),
        p('The schedule is built like a crontab: pick a frequency (hourly, daily, weekly or monthly) and the time, or switch to Custom for a raw five-field cron expression (minute hour day-of-month month weekday). The panel shows the resulting cron string and a plain-English summary, and a “Run backup now” button lets you test the configuration immediately.'),
        def('Where they go', 'Scheduled backups are written on the server under data/backups/ as encrypted .json files, named by timestamp. “Keep newest N” prunes older files so the directory can’t grow without bound. The last run (success or failure) is shown under the controls.'),
        warn('Automatic backups need the encryption password stored to run unattended, so treat the server as a secret store. A scheduled backup can only be restored with that password — keep a copy somewhere safe. Enabling automatic backups requires a password to be set.'),
      ],
    },
  ],
}

// ── Configuration ─────────────────────────────────────────────────────────────

const configuration: HelpTopic = {
  id: 'configuration',
  title: 'Configuration',
  subtitle: 'Display options, KPIs, step colours, shapes, scores and groups',
  icon: '⚙️',
  sections: [
    {
      heading: 'Display options',
      body: [
        def('Show step groups', 'Toggles the dashed BELONGS_TO group boxes. When on, “Groups start” chooses whether groups load Expanded, Collapsed, or in their last Persisted state.'),
        def('Show node notes', 'Shows the shortened DESCRIPTION under the step name on each node, and the yellow note badges. It sits at the top of the Steps sub-section, next to the step editor whose notes it displays.'),
        def('Optimise layout', 'Enables barycenter crossing-minimisation for a cleaner arrangement on complex graphs.'),
        def('Colorise edges by weight', 'Turns on the per-metric colour scales (configure them from the map’s colour legend).'),
        def('Default date window', 'How many days back the map shows when a project first loads — the window ends at the latest event date and spans the last N days. Defaults to 30; set 0 to load the project’s full range. Takes effect on the next project load; it does not move the slider on the current map.'),
        def('Flowchart Font Sizes', 'Scale the process-map text — separate S / M / L / XL settings for Nodes, Edges and Group titles. A node’s box grows with its font, so the label always stays inside the node; the edge setting enlarges the transition labels, and the group-title setting sizes the pill on each step-group box.'),
        def('Date slider', 'Switches the map’s date control between Range (two thumbs) and Day (single day) mode.'),
      ],
    },
    {
      heading: 'KPIs, steps and preferences',
      body: [
        p('The KPIs sub-section lets you drag to reorder the KPI tiles and toggle each one on or off. The Steps sub-section is the in-app Step Editor: pick a step, then set its background/foreground colour, shape, score, group and description — changes are written straight to the STEPS table and the map redraws.'),
        p('The AI related sub-section holds the LLM Prompt editor — the report analysis instruction, stored per connection and project (the same mapping the admin Reporting tab manages). It is shown only to power users, developers and administrators; regular users do not see it. Theme (System / Light / Dark) is chosen from the bar at the bottom of the sidebar. (Sign-in is now managed centrally in the admin interface, so there is no per-client authentication toggle here.)'),
      ],
    },
  ],
}

// ── Troubleshooting ───────────────────────────────────────────────────────────

const troubleshooting: HelpTopic = {
  id: 'troubleshooting',
  title: 'Troubleshooting',
  subtitle: 'Common problems and their fixes',
  icon: '🛟',
  sections: [
    {
      heading: 'Common issues',
      body: [
        def('No connections listed', 'No connection has been assigned to your account. Ask an administrator to grant you one in the admin interface (Database Connections tab).'),
        def('Cannot connect to Exasol', 'Connection settings (host, port, credentials, TLS, RSA key size) are managed by an administrator. If a connection fails, ask them to check it with Test connection in the admin interface — for Exasol 7.x or the Docker image the minimum RSA key size must be 1024 bits, and the account needs SELECT on the required tables.'),
        def('Cannot sign in', 'Confirm your account is enabled (an administrator can check the Users tab). Directory (LDAP) accounts must exist in the directory and, for the admin interface, be tagged Admin locally.'),
        def('Statistics / goodness query times out', 'Narrow the date range or add filters — a 30-second limit applies. The affected tile shows “—”.'),
        def('Simulation returns no journeys', 'The graph needs at least one start step (in-degree / out-degree < 0.2); exclusions may have removed all entry points. Required steps that never occur also drop every journey.'),
        def('AI Documentation stays blank', 'Confirm the active connection has an LLM server attached and its status dot is blue (reachable); the LLM URL, model and API key are set by an administrator.'),
        def('Notes are not saved', 'The connecting user needs CREATE TABLE (first use) and INSERT / DELETE on NOTES.'),
        def('Sample cannot be created', 'The user needs ALTER TABLE and INSERT on JOURNEYS.'),
      ],
    },
  ],
}

// ── Integration console (developer) ────────────────────────────────────────────

const integrationConsole: HelpTopic = {
  id: 'integration-console',
  title: 'Integration Console',
  subtitle: 'Import event data into a connection from files',
  icon: '🧩',
  sections: [
    {
      heading: 'What it is',
      body: [
        p('The Integration Console is a separate surface for loading event data into a database connection. It runs on its own port (the admin port + 10 — 8100 for HTTP, 8463 for HTTPS by default) and reuses the same sign-in as the main app. It is reachable by developers and administrators only (power users may not enter it).'),
        p('At its heart is an abstraction layer: pluggable extractors read some source (today, a file) and push the parsed records into the schema of the connection you are connected to — creating the process-mining tables as needed. You define two things and then run an import.'),
        def('Source type', 'A reusable recipe for parsing one file format: an example record plus the selectors that pull out the timestamp, case id, step and up to three meta fields — regular expressions for Text, or JSON/XML paths for semi-structured files.'),
        def('Source', 'A concrete thing to import — a File (a path + encoding) linked to a source type, or an API Server - Event Receiver (see below).'),
      ],
    },
    {
      heading: 'API Server - Event Receiver',
      body: [
        p('Besides files, a source can be a live HTTP/HTTPS ingestion server that AI agents (or any client) POST journey entries to as JSON. Add one under Sources → + → API Server - Event Receiver: pick the destination connection, a project code (TITLE_SHORT — entries land in that project, created if new) and a free port from the pool. On save you are shown a bearer token once (only its hash is stored) — copy it then.'),
        p('Each sink runs on its own port from a fixed pool (the admin port + 30 onwards — 8120–8129 by default; under Docker the published host port is that + 10000). POST a JSON object or an array to /ingest with header Authorization: Bearer <token>. Each entry needs eventId (the case / correlation id) and step; eventTime (ISO-8601, defaults to now) and meta1–3 are optional. Any unknown step is created automatically.'),
        warn('The module is off by default — an administrator must enable “API Server - Event Receiver” in the admin interface (Event Receiver tab). While it is off, the ports stay open but return 503.'),
      ],
    },
    {
      heading: 'Getting there',
      body: [
        p('Open the console URL and sign in. The left panel holds three collapsible sections — Connections, Sources and Source types — plus the theme selector and your account footer, mirroring the main app. Clicking a connection connects to it, as in the main app, but an import does not depend on that: the Run dialog picks its own destination.'),
        p('If an administrator has set an idle timeout, the console signs you out after that long without activity and returns you to the login screen — the same as the main application. Because the console is always role-gated, this applies even when the global “require sign-in” setting is off.'),
        p('Connections can be created and edited here, so you do not have to switch to the main app to set up the database you are about to import into. Use ＋ on the Connections header for a new one, or ✎ on a connection you own to edit it — host, port, credentials, TLS, target schema, an optional LLM server, and which users it is assigned to.'),
        warn('✎ appears only on connections you own — the ones you created. A connection an administrator created and assigned to you can be used for imports but not edited; ask an administrator to change it.'),
      ],
    },
  ],
}

const integrationSources: HelpTopic = {
  id: 'integration-sources',
  title: 'Source Types & Sources',
  subtitle: 'Define how to parse a log, then import a file',
  icon: '🗂️',
  sections: [
    {
      heading: 'Building a source type',
      body: [
        p('Open the Source types section and click ＋. First give the type an example record. The quickest way is 📄 Choose a file…: it lists the files in the sandboxed sources directory, and when you pick one it auto-detects the file’s data format — Text, JSON or XML — shown as a badge. Pick one of the previewed records (drag it onto the box below, or click it) to use as the example; you can also paste one into the text box and choose the format yourself.'),
        p('How you map fields depends on the format, chosen with the Data format selector:'),
        ul(
          'Text — unstructured logs (.log, .txt). The file is read line by line and each field is captured with a regular expression. For text the picker also auto-detects the record delimiter — LF (Unix), CRLF (Windows), CR, FF, a blank line for multi-line records — with a dropdown you can override.',
          'JSON — a top-level array […] or JSONL/NDJSON (one object per line). Each field is located by a JSON path such as user.id or items[0].sku.',
          'XML — each record is a repeating element. Each field is located by an element/attribute path such as @id or payload/user@id; the record element (e.g. event) is shown at the top of the mapping step.',
        ),
        p('On the tabbed mapping step, pick a role tab (Timestamp · Step · Id · Metas), then map the field. For Text, highlight a piece of the line and press 🎯 Use selection to generate a regex, or press ＋ Add field and type the regex yourself. For JSON/XML, the record’s fields are listed as clickable paths — click one to map it to the active role, or type the path in the field row. Every field is defined manually, so the extraction is always exactly what you intend.'),
        ul(
          'EVENT_TIME — the timestamp. It is analysed and normalised to YEAR-MONTH-DAY HOUR:MINUTE:SECOND.',
          'EVENT_ID — the case/journey key. It is stored MD5-hashed, so a raw login or user id never lands in the clear.',
          'STEP — the activity name for the event.',
          'Metas — up to three extra attributes; give each a business name shown in the app.',
          'Helper — a value used only by compound-step rules. Extracted but written to no column.',
        ),
        p('For Text, a field’s regex should have exactly one capturing group — that group is the value. For JSON/XML the path resolves to a single value; each row shows live what it extracted from your sample, so a wrong pattern or path is obvious immediately.'),
        tip('Name your Metas and Helpers deliberately: the name is the label a compound rule uses to reference the field, and META names become the business titles shown in the app.'),
        p('A live “Example JOURNEYS record” shows the row your spec would produce from the sample (with the original id, labelled “stored as MD5”), so you can confirm the mapping before saving. Compound steps — which combine several fields into one STEP — work for every format: they match on the extracted field values, whether captured by regex (Text) or by a path (JSON/XML), and a helper field carries the matching selector accordingly.')
      ],
    },
    {
      heading: 'Adding a File source',
      body: [
        p('Open the Sources section and click ＋. Choose the File kind, enter the file path and encoding, preview the first few lines, and link the source type that parses it.'),
        warn('File reads are sandboxed: by default only files under the server’s integration files directory can be read. Paths that escape it (via “..” or symlinks) are rejected. An operator can opt out with PMW_INTEGRATION_ALLOW_ANY_PATH=1 for trusted deployments.'),
      ],
    },
    {
      heading: 'Running an import',
      body: [
        p('Press ▷ on a File source, pick the destination connection and the project. The extractor reads the file — line by line for Text/JSONL, or the whole document for a JSON array / XML file — applies the source type’s selectors, normalises the timestamp, MD5-hashes the id, and writes one JOURNEYS row per event into that connection’s schema. A progress bar counts the records as they load.'),
        p('Re-running tops up without duplicating: a Text or JSONL source imports only the lines appended since last time (a byte-offset delta upload). A JSON-array or XML file is whole-document, so it is import-once by content signature — re-running an unchanged file imports nothing; a changed file re-imports the whole document.'),
        tip('The connection dropdown lists every connection an administrator has assigned to you, and defaults to the one the main app is connected to. You do not have to connect to it first — the import opens the connection itself with its saved credentials, exactly as the watchdog does. The line under the dropdown shows the host and the schema the rows will land in.'),
        p('The project dropdown is filled from the projects already in that schema, so you pick an existing one instead of retyping its id. Choose ＋ New project… to start a new one and type its id — the PROJECTS row is created for you. Changing the connection reloads the list.'),
        tip('Both choices are remembered on the source: the next time you press ▷ the dialog reopens on the connection and project that source last imported into, so repeating an import is a single click. If the connection is no longer assigned to you it falls back to the one the main app is connected to, and a project deleted in the meantime is offered again as a new project id.'),
        p('Delta upload is on by default. A checkpoint records how far the file has been read, so pressing ▷ again imports only the lines added since — running the same source twice tops the project up instead of storing everything a second time. The panel shows the checkpoint: records imported, how far into the file it has read, and when it last ran. An empty log file, or one that has not grown, simply reports “nothing new” — it is not an error.'),
        p('Switch delta upload off to read the whole file from the top again, and use ↺ Reset checkpoint to forget the position so the next import starts over. Both are the same thing from the database\'s point of view: events are never de-duplicated, so a full re-read stores the file\'s events a second time. To genuinely reload a project, delete it first (Connections → Projects) and import again.'),
        warn('The checkpoint is shared with the watchdog — there is one per source. A manual delta import and a watchdog poll advance the same position, which is what keeps them from importing the same line twice between them. Resetting it therefore also makes the watchdog re-read the file from the start.'),
        p('It also creates anything missing: the PROJECTS row, a STEPS definition for every distinct step (a shape, a colour and a zero score), and the META business-name titles — existing rows are never overwritten.'),
      ],
    },
    {
      heading: 'Compound steps — build a step from several fields',
      body: [
        p('Sometimes the real activity is split across fields: the log records the action in one place and its outcome in another. In an Apache log, “POST /shop/login … 200” is a successful login and “… 500” a failed one — but the path alone yields “login” for both, so the process map cannot tell them apart.'),
        p('A compound rule fixes that. It names the step to produce and the conditions that must all hold. Take this line:'),
        code('10.185.248.71 - - [09/Jan/2015:19:12:06 +0000] 4213\n"POST /shop/login?userId=20253471 HTTP/1.1" 200 512 "-" "Mozilla/5.0 …"'),
        p('With step mapped to the path segment and the HTTP status mapped as a Helper, two rules split one activity into two:'),
        table(
          ['Rule', 'Conditions (all must hold)', 'STEP written'],
          [
            ['1', 'step is “login” · status is “200”', 'login successful'],
            ['2', 'step is “login” · status is “500”', 'login failed'],
          ],
        ),
        p('Anything the rules do not cover is untouched — a “basket” line still writes “basket”.'),
      ],
    },
    {
      heading: 'Writing the rules',
      body: [
        p('Compound steps live in the STEP tab of the mapping screen, under the step field — they only ever produce a STEP value, so that is where they belong.'),
        p('Each rule is a badge showing the step it produces and its conditions; three badges are visible and the list scrolls beyond that. A ✓ on a badge means that rule matches your sample line. Click ＋ Add rule, or click a badge, to open its panel:'),
        ul(
          'Step becomes — the name written to STEP, e.g. “login successful”.',
          'when / and — a field, a comparison, and a value. Add as many conditions as you need; every one must hold.',
          'Add a helper field — extract a new value on the spot without leaving the panel.',
        ),
        p('The panel shows what each referenced field captures from your sample (“= 200”) and whether the rule as a whole matches, so you can confirm a rule before closing it.'),
        table(
          ['Comparison', 'True when the captured value…'],
          [
            ['is', 'equals the value'],
            ['is not', 'differs from the value'],
            ['contains', 'contains the value anywhere'],
            ['starts with', 'begins with the value'],
            ['ends with', 'ends with the value'],
            ['matches regex', 'matches the pattern (case-sensitive, exact control)'],
          ],
        ),
        warn('All comparisons except “matches regex” ignore case and surrounding spaces — log casing is rarely dependable. Use “matches regex” when you need an exact pattern.'),
      ],
    },
    {
      heading: 'How rules are applied',
      body: [
        ul(
          'Rules are checked in the order they are listed — the badge number is that order — and the FIRST rule whose conditions all hold wins. Put specific rules above general ones.',
          'If no rule matches, the plain STEP field’s value is used unchanged. Compound steps are therefore purely additive: adding them to an existing source type cannot break it.',
          'A rule with no resulting step, or no conditions, is ignored rather than applied to every event — a half-built rule can never relabel your data.',
          'The same rules apply to a manual ▷ run and to a watchdog import, so a live feed is labelled identically.',
        ),
        p('Derived names are real step names: the import creates a STEPS definition — shape, colour, zero score — for “login successful” and “login failed” just as it would for any other step, so both appear as separate nodes in the process map with their own paths through it.'),
        def('Locked fields', 'A field referenced by a compound rule shows a 🔒 instead of its remove button, and the row names the rules using it. Deleting it would leave those rules pointing at a field that no longer exists — they would quietly stop matching — so remove it from the rules first, then delete it. Renaming needs no such care: the rules follow the new name automatically.'),
        warn('Changed rules only affect FUTURE imports; rows already written keep the step names they were given. Importing the same file again APPENDS its events rather than replacing them, so to re-apply changed rules to existing data, delete the project first — in the app’s connection editor, Projects tab — and then import again.'),
        tip('A misconfigured rule usually shows up as a surprise in the console’s “Events skipped” KPI or as unexpected nodes on the map. The Example JOURNEYS record in the wizard marks a compound-derived step with “compound”, so check it there before you import.'),
      ],
    },
    {
      heading: 'Helper fields',
      body: [
        p('A value you need only for matching — an HTTP status, a result code, a queue name — does not belong in META. Map it on the Helper tab, or add one directly from a rule panel.'),
        ul(
          'Helper fields are extracted from every line and are available to compound rules.',
          'They are written to NO database column, so all three META columns stay free for business attributes.',
          'They are named like Metas, and that name is what a rule references. Give each a distinct, meaningful name.',
        ),
        tip('Adding a helper from inside the rule panel also wires it into the rule’s first empty condition, so you go straight from “I need the status” to “status is 200” without switching tabs.'),
      ],
    },
    {
      heading: 'Transaction bracket',
      body: [
        p('Rows are inserted inside a real database transaction, committed in brackets: the import commits once the configured number of rows has been written, then a final commit for the remainder. Set the bracket per source in the wizard (Transaction bracket, default 5000 rows). It applies to both a manual run and the watchdog.'),
        ul(
          'A larger bracket is more atomic, but the database holds more of the import open at once.',
          'A smaller bracket commits steadily, so if the import fails part-way the brackets already committed stay in the database.',
          '0 means one single transaction for the whole import — all of it lands, or none of it.',
        ),
        tip('If a run fails, the bracket that was still open is rolled back; whatever was committed before it remains. The result message tells you how many events were written.'),
      ],
    },
    {
      heading: 'Watchdog — auto-import new lines',
      body: [
        p('A File source can run a watchdog (turn it on in the source wizard, under the file path). It picks a destination connection, a project id and a poll interval. A background job then watches the file and, whenever it grows, imports only the newly-appended lines — never the whole file again — so a continuously-written log streams into the database on its own.'),
        p('A checkpoint is kept per source file (how far it has been read, plus the imported record count), so nothing is imported twice — even across server restarts. If the file is truncated or replaced (rotated), the watchdog notices and re-reads it from the start.'),
        tip('The wizard shows the checkpoint status (records imported, last check, any error) and a Reset checkpoint button to force a full re-read. A source with the watchdog on is marked with a 👁 in the Sources list, and its imports appear in the live pipeline like any other run.'),
        warn('The watchdog runs headless (no signed-in session), so its destination is stored with the source rather than picked each time. It uses that connection’s saved credentials, so pick one you are assigned to and that points at the right schema — the assignment is re-checked on every poll, and revoking it stops the watchdog.'),
      ],
    },
  ],
}

const integrationMonitoring: HelpTopic = {
  id: 'integration-monitoring',
  title: 'Pipeline Monitoring',
  subtitle: 'The live import flowchart and run history',
  icon: '🔀',
  sections: [
    {
      heading: 'Ingestion KPIs',
      body: [
        p('The Abstraction layer card at the top summarises ingestion with the same KPI tiles the main app uses. They cover the whole recorded history, not just the last run:'),
        ul(
          'Manual imports — runs you started with ▷ Run.',
          'Watchdog imports — runs the background file watchdog started on its own.',
          'Last import — how long ago the most recent run finished (or “running…” while one is in flight).',
          'Events pushed — journey events written to the database.',
          'Events skipped — source lines that could not be parsed into an event.',
        ),
        warn('A non-zero “Events skipped” is highlighted in orange: it usually means the linked source type’s regexes do not fit that log. Edit the source type and test it against a real line.'),
        tip('The card also shows the target schema, the run state, and — behind the Run log button — the log lines of the most recent run. The counts reset when you clear the run history.'),
      ],
    },
    {
      heading: 'The flowchart',
      body: [
        p('Below the KPIs the imports are drawn as one flowchart: Source type → Source → Abstraction layer → Connection. Nodes are reused across runs — every distinct source type, source and destination is a single node, with the Abstraction layer as the hub in the middle. The Source and Destination nodes show the total number of rows imported, and each Source node also shows 🕒 with the date and time of its most recent import (in your local time), so you can see at a glance when each file was last loaded.'),
        p('Each stage is tinted in its own pastel colour (source types violet, sources blue, the layer by its state, destinations teal) so you can tell them apart at a glance; the stage currently running gets a deeper wash.'),
      ],
    },
    {
      heading: 'Live activity & colours',
      body: [
        p('While an import runs, a dot travels the active path node-to-node to show progress. Connections are coloured by their most recent run:'),
        ul('Blue — idle or completed.', 'Green — currently running.', 'Red — the last run on that path failed.'),
      ],
    },
    {
      heading: 'History & layout',
      body: [
        p('The console keeps a per-user history of every run and folds it into the one growing flowchart, so you can see the ingestion behaviour over time. It survives reloads and server restarts and is kept until you press ↺ Clear.'),
        p('You can drag the nodes to arrange them however you like, and drag the grip on the bottom edge of the canvas to make the working area taller. Both the arrangement and the canvas height are saved per user and restored automatically; ⤢ Reset layout returns to the automatic arrangement and the default size.'),
        tip('The run history, the manual layout and the canvas height are stored in your browser, so they are per-device.'),
      ],
    },
  ],
}

const actions: HelpTopic = {
  id: 'actions',
  title: 'Actions',
  subtitle: 'Business-readable queries on the process map',
  icon: '⚡',
  sections: [
    {
      heading: 'What actions are',
      body: [
        p('An action is a small, business-readable script attached to process-map nodes. From a node’s menu you can, for example, show the last log entries from that node, from the steps around it, or a transition table for everything that follows — all honouring the filters you currently have set on the chart.'),
        p('Actions are written and saved on the separate Actions site (developers and administrators only) and run from the app by anyone except a plain standard user. The whole feature is off until an administrator enables it in the admin panel’s Actions tab.'),
      ],
    },
    {
      heading: 'The script language',
      body: [
        p('Each action is a few clauses. Keywords are case-insensitive, and NODE/NODES and ENTRY/ENTRIES are interchangeable:'),
        ul(
          'AVAILABILITY — where the action appears: ALL NODES, or a comma-separated list of step names (e.g. LOGIN, LOGOUT, PAYMENT).',
          'SHOW — LAST [N] LOG ENTRIES (N defaults to 1); TRANSITION TABLE WITH one or more metrics: "COUNT", "%JOURNEY%", "%OUTGOING%", "AVG TIME", "MIN TIME", "MAX TIME", "STD DEV" (short forms like AVG/MIN/MAX/STDDEV/PERCENTAGE also work, or ALL METRICS for every metric); or FLOWCHART IN SEPARATE PANEL to open another project’s process map — optionally FOR one or more metrics (e.g. "FLOWCHART IN SEPARATE PANEL FOR Count, Avg Time", or FOR ALL METRICS) to let the panel switch the edge metric.',
          'FROM — for log entries / transition tables: NODE(…) relative to the clicked node — THIS, PREVIOUS, FOLLOWING, ALL FOLLOWING, ALL PREVIOUS (combine them, e.g. NODE(THIS, ALL FOLLOWING)). For a flowchart: a <connection>::<project> target.',
          'SORT — ASCENDING or DESCENDING (log entries by time; default most-recent-first).',
          'WHERE — an optional filter; this version supports EVENT_ID :: [id, id, …].',
        ),
        code('AVAILABILITY\n\tPAYMENT\nSHOW\n\tLAST 1 LOG ENTRY\nFROM\n\tNODE(THIS)\nSORT\n\tDESCENDING'),
        p('The builder validates the script live, restates it in plain English, and shows the exact SQL it will run. A Test panel runs it against a node of your choosing so you can see real rows before saving.'),
      ],
    },
    {
      heading: 'Running an action',
      body: [
        p('In the process map, click a node and pick the action from the Actions section of its menu — only actions whose AVAILABILITY matches that node are listed. The result (log entries or a transition table) opens over the map.'),
        tip('Actions always respect the chart’s current filters — date range, included/excluded steps, meta filters, ranges and the sample set — so the same action answers a different question as you narrow the view.'),
      ],
    },
  ],
}

export const HELP_TOPICS: HelpTopic[] = [
  overview,
  database,
  connecting,
  roles,
  // Administration chapters — grouped under one admin-only TOC sub-menu.
  adminInterface,
  adminTls,
  adminUsers,
  adminConnections,
  adminApi,
  adminDirectory,
  adminLogging,
  backup,
  adminCustomize,
  adminLicense,
  chartViews,
  filters,
  filterPresets,
  processMap,
  kpi,
  processGoodness,
  processSimilarity,
  simulation,
  conformance,
  happyPath,
  sampling,
  aiDocumentation,
  notes,
  actions,
  // Integration console chapters — grouped under one developer-only TOC sub-menu.
  integrationConsole,
  integrationSources,
  integrationMonitoring,
  configuration,
  troubleshooting,
]

/** Topic ids grouped under the developer-only "Integration console" TOC sub-menu. */
export const INTEGRATION_TOPIC_IDS = [
  'integration-console',
  'integration-sources',
  'integration-monitoring',
]

/** Topic ids grouped under the admin-only "Administration" TOC sub-menu. */
export const ADMIN_TOPIC_IDS = [
  'admin-interface',
  'admin-tls',
  'admin-users',
  'admin-connections',
  'admin-api',
  'admin-directory',
  'admin-logging',
  'backup',
  'admin-customize',
  'admin-license',
]
