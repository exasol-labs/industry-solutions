import SwiftUI
import CryptoKit
import WebKit
#if canImport(AppKit)
import AppKit
#endif

// MARK: - Model

struct HelpTopic: Identifiable {
    let id: String
    let title: String
    let subtitle: String
    let icon: String
    let color: Color
    let sections: [HelpSection]
}

struct HelpSection: Identifiable {
    let id = UUID()
    let heading: String
    let body: [HelpBlock]
}

enum HelpBlock {
    case paragraph(String)
    case tip(String)
    case warning(String)
    case bullets([String])
    case definition(term: String, detail: String)
    case code(String)
}

// MARK: - Content

extension HelpTopic {
    static let all: [HelpTopic] = [
        databaseSetup, overview, connecting, demoData, gettingExasol, chartViews, filters, filterPresets, processMap, kpi, processGoodness, processSimilarity, configuration,
        complianceCheck, happyPath, aiDocumentation, processNotes, backupRestore, appSecurity, sampling, simulation
    ]

    // MARK: Database Setup

    static let databaseSetup = HelpTopic(
        id: "dbsetup", title: "Database Setup", subtitle: "Table schemas and required permissions",
        icon: "server.rack", color: .green,
        sections: [
            HelpSection(heading: "What Process Mining Demonstrator needs", body: [
                .paragraph("Process Mining Demonstrator reads from four tables in your Exasol database: PROJECTS, JOURNEYS, STEPS, and METAS. PROJECTS and JOURNEYS are required. STEPS and METAS are optional but strongly recommended for a useful experience."),
                .tip("All table and column names are case-insensitive in Exasol. The names shown here are uppercase by convention.")
            ]),

            HelpSection(heading: "PROJECTS — required", body: [
                .paragraph("One row per process mining project. Process Mining Demonstrator shows this list in the sidebar so users can switch between different processes or data sets."),
                .code("""
CREATE TABLE PROJECTS (
  PROJECT_ID  VARCHAR(100) NOT NULL PRIMARY KEY,
  TITLE       VARCHAR(200) NOT NULL,
  DESCRIPTION VARCHAR(500)
);
"""),
                .definition(term: "PROJECT_ID",  detail: "Unique identifier used as a foreign key in all other tables."),
                .definition(term: "TITLE",        detail: "Human-readable name displayed in the Projects list."),
                .definition(term: "DESCRIPTION",  detail: "Optional short description shown beneath the title.")
            ]),

            HelpSection(heading: "JOURNEYS — required", body: [
                .paragraph("The core event log. Each row is one activity (step) that occurred within one process instance (journey). A journey is a sequence of steps sharing the same EVENT_ID."),
                .code("""
CREATE TABLE JOURNEYS (
  PROJECT_ID  VARCHAR(100)  NOT NULL,
  EVENT_ID    VARCHAR(200)  NOT NULL,
  STEP        VARCHAR(200)  NOT NULL,
  STEP_ID     DECIMAL(18,0),
  EVENT_TIME  TIMESTAMP     NOT NULL,
  META_1      VARCHAR(500),
  META_2      VARCHAR(500),
  META_3      VARCHAR(500)
);
"""),
                .definition(term: "PROJECT_ID",  detail: "Must match a value in PROJECTS.PROJECT_ID."),
                .definition(term: "EVENT_ID",    detail: "Unique identifier for a single journey or case. All rows with the same EVENT_ID form one complete journey."),
                .definition(term: "STEP",        detail: "Name of the activity or event. This becomes a node in the flow chart."),
                .definition(term: "STEP_ID",     detail: "Numeric sequence counter used to break ties when two steps share the same EVENT_TIME. Lower values come first."),
                .definition(term: "EVENT_TIME",  detail: "Timestamp of the activity. Used to order steps within a journey and to apply date-range filters."),
                .definition(term: "META_1–3",    detail: "Optional case-level attributes (e.g. region, product, customer segment). Support free-text filtering in the sidebar."),
                .tip("For best performance, create an index on (PROJECT_ID, EVENT_TIME) and a separate index on (PROJECT_ID, EVENT_ID).")
            ]),

            HelpSection(heading: "STEPS — optional", body: [
                .paragraph("Visual and semantic configuration for each step. Without this table all nodes render in grey with the stadium shape. The Step Editor in the sidebar writes back to this table."),
                .code("""
CREATE TABLE STEPS (
  PROJECT_ID      VARCHAR(100) NOT NULL,
  STEP            VARCHAR(200) NOT NULL,
  DESCRIPTION     VARCHAR(500),
  BG_COLOR        VARCHAR(50),
  FG_COLOR        VARCHAR(50),
  SCORE           DECIMAL(5,0),
  SHAPE           VARCHAR(20),
  END_OF_PROCESS  DECIMAL(1,0) DEFAULT 0,
  BELONGS_TO      VARCHAR(200),
  PRIMARY KEY (PROJECT_ID, STEP)
);
"""),
                .definition(term: "STEP",           detail: "Must match a STEP value used in JOURNEYS for this project."),
                .definition(term: "DESCRIPTION",    detail: "Human-readable label for the step (reserved for future tooltip use)."),
                .definition(term: "BG_COLOR",       detail: "Node background colour. Accepts CSS colour names (red, blue, …) or a 6-digit hex string (e.g. FF8000)."),
                .definition(term: "FG_COLOR",       detail: "Node text colour. Same format as BG_COLOR."),
                .definition(term: "SCORE",          detail: "Integer value from −999 to 999. Displayed as a badge on the node and summed in the Individual Journey KPI."),
                .definition(term: "SHAPE",          detail: "Node shape: stadium (default), round, hex, or circle."),
                .definition(term: "END_OF_PROCESS", detail: "Set to 1 to mark the step as a terminal state. An orange dot appears on the node."),
                .definition(term: "BELONGS_TO",     detail: "Optional grouping label, e.g. a subprocess name.")
            ]),

            HelpSection(heading: "METAS — optional", body: [
                .paragraph("Provides display names for the three META columns in JOURNEYS. Without this table the Meta filter section is hidden in the sidebar."),
                .code("""
CREATE TABLE METAS (
  PROJECT_ID    VARCHAR(100) NOT NULL PRIMARY KEY,
  META_1_TITLE  VARCHAR(200),
  META_2_TITLE  VARCHAR(200),
  META_3_TITLE  VARCHAR(200)
);
"""),
                .paragraph("Insert one row per project. Leave a TITLE column NULL to hide that filter field entirely."),
                .tip("Example: INSERT INTO METAS VALUES ('PROJ1', 'Region', 'Product', NULL); — this shows Region and Product filters but hides the third.")
            ]),

            HelpSection(heading: "NOTES — created automatically", body: [
                .paragraph("Process Mining Demonstrator stores process annotations (sticky notes on nodes and edges) in a NOTES table in the connected database. This table is created automatically on first use when the connecting user has CREATE TABLE permission."),
                .code("""
CREATE TABLE IF NOT EXISTS NOTES (
  ID              VARCHAR(36)   NOT NULL,
  PROJECT_ID      VARCHAR(100)  NOT NULL,
  NOTES_DATE      TIMESTAMP     NOT NULL,
  EDITED_DATE     TIMESTAMP,
  NOTE_USER       VARCHAR(200)  DEFAULT '',
  NOTE            VARCHAR(8000) DEFAULT '',
  IS_SHARED       BOOLEAN       DEFAULT FALSE,
  TARGET_TYPE     VARCHAR(10)   DEFAULT 'node',
  TARGET_FROM     VARCHAR(500)  DEFAULT '',
  TARGET_TO       VARCHAR(500),
  FILTER_SNAPSHOT VARCHAR(4000),
  PRIMARY KEY (ID)
);
"""),
                .definition(term: "ID",              detail: "UUID of the individual note."),
                .definition(term: "PROJECT_ID",      detail: "Foreign key to PROJECTS.PROJECT_ID."),
                .definition(term: "NOTES_DATE",      detail: "Timestamp when the note was originally created."),
                .definition(term: "EDITED_DATE",     detail: "Timestamp of the most recent edit; NULL if never edited."),
                .definition(term: "NOTE_USER",       detail: "Username from the database connection that created or last saved the note."),
                .definition(term: "NOTE",            detail: "The annotation text, up to 8 000 characters."),
                .definition(term: "IS_SHARED",       detail: "FALSE (default) = private note visible only to NOTE_USER. TRUE = shared note visible to all connected users."),
                .definition(term: "TARGET_TYPE",     detail: "'node' or 'edge' — what the note is attached to."),
                .definition(term: "TARGET_FROM/TO",  detail: "Step name(s) identifying the annotated node or edge."),
                .definition(term: "FILTER_SNAPSHOT", detail: "JSON snapshot of the active filter state at creation time."),
                .tip("Notes are stored per user and per target. Private notes (IS_SHARED = FALSE) are only returned for the user who created them. Shared notes are visible to everyone. If your user account lacks CREATE TABLE permission, ask a DBA to create the NOTES table once using the schema above.")
            ]),

            HelpSection(heading: "Minimal quick-start", body: [
                .paragraph("The absolute minimum to see your first process map:"),
                .bullets([
                    "Create PROJECTS and insert at least one row.",
                    "Create JOURNEYS and load your event log data.",
                    "Connect Process Mining Demonstrator to your Exasol instance, select the project, and tap Apply."
                ]),
                .paragraph("You can then use the Step Editor in the sidebar to configure colours, shapes, and scores without writing any SQL."),
                .warning("The JOURNEYS table must contain at least two steps sharing the same EVENT_ID to produce any transitions. A single-step journey results in an empty map.")
            ]),

            HelpSection(heading: "Permissions", body: [
                .paragraph("The Exasol user configured in the connection needs at minimum:"),
                .bullets([
                    "SELECT on PROJECTS, JOURNEYS, STEPS, METAS, and NOTES.",
                    "INSERT, UPDATE, DELETE on NOTES (to create and edit process notes).",
                    "UPDATE on STEPS (to write back colour and shape changes via the Step Editor).",
                    "CREATE TABLE (optional — only needed once to auto-create the NOTES table on first use)."
                ])
            ])
        ]
    )

    // MARK: Demo Data Generator

    static let demoData = HelpTopic(
        id: "demodata", title: "Demo Data", subtitle: "Generate a sample bookstore dataset",
        icon: "wand.and.stars", color: .teal,
        sections: [
            HelpSection(heading: "Bookstore demo dataset", body: [
                .paragraph("The Demo Data section in the sidebar (below Connections) lets you populate your Exasol instance with a realistic bookstore process-mining dataset — no external tools or scripts required."),
                .paragraph("The generated data models an online bookstore's complete order lifecycle: Login → Browse Catalog → Add to Basket → Checkout → Payment Processing → Fulfilment → Delivery, with a Returns flow for 5% of orders.")
            ]),
            HelpSection(heading: "Configuration", body: [
                .definition(term: "Schema", detail: "The Exasol schema where the four tables will be created. Pre-filled with the schema from the active connection's database server so the generated data is immediately accessible without reconnecting. The schema is created automatically if it does not exist. The name is converted to uppercase."),
                .warning("The Schema field must match the schema your active database server uses. If they differ, the app will query the wrong schema and find no data. The field is pre-filled correctly — only change it if you intentionally want to generate data in a separate schema."),
                .definition(term: "Journeys", detail: "Number of order journeys to generate. Use the stepper to choose a value between 10 and 5 000. This is a demo dataset — not intended for production-scale analysis."),
                .warning("Regenerating demo data replaces all JOURNEYS rows for the Online Bookstore project and refreshes its PROJECTS and METAS rows. Step configurations (colours, shapes, scores) you have customised via the Step Editor are preserved — only steps that do not yet exist in the STEPS table are added. Data belonging to other projects in the same schema is never touched.")
            ]),
            HelpSection(heading: "Payment method variation", body: [
                .paragraph("Three payment methods are generated at different rates and with intentionally different reliability, creating visible process variations in the flow chart:"),
                .bullets([
                    "Credit Card (45%) — fast processing, ~2% failure rate.",
                    "PayPal (35%) — fast processing, ~3% failure rate.",
                    "Bank Transfer (20%) — slow processing (3–15 min), ~35% failure rate with up to 2 retry attempts."
                ]),
                .tip("Bank Transfer failures are intentionally severe. After generating data, filter META_1 = 'Bank Transfer' to isolate this flow and see the Payment Failed / Payment Retry nodes clearly.")
            ]),
            HelpSection(heading: "After generation", body: [
                .paragraph("Once the progress bar reaches 100% and the status shows 'Done':"),
                .bullets([
                    "Tap the ↺ reload button in the Projects section header to refresh the project list.",
                    "Select 'Online Bookstore' from the list.",
                    "Tap Apply in the sidebar to load the process map.",
                    "Use META_1 (Payment Method), META_2 (Customer Segment), or META_3 (Order Value) filters to explore different slices."
                ]),
                .tip("Order numbers follow the format ORD-000001, ORD-000002, … ORD-{N} (zero-padded to six digits). Each is stored as its plain MD5 hash with no salt — so any external ETL tool can reproduce the same EVENT_ID by hashing the order number string directly. Enter any ORD-NNNNNN value in the Individual Journey filter to look up that specific order.")
            ])
        ]
    )

    // MARK: Overview

    static let overview = HelpTopic(
        id: "overview", title: "Overview", subtitle: "What Process Mining Demonstrator does and key concepts",
        icon: "house.fill", color: .blue,
        sections: [
            HelpSection(heading: "What is Process Mining Demonstrator?", body: [
                .paragraph("Process Mining Demonstrator is a process mining tool that connects to an Exasol database and visualises how real cases flow through your business processes."),
                .paragraph("It reads a JOURNEYS table and renders every possible path between process steps as an interactive flow chart, with rich filtering, side-by-side comparison, and individual journey inspection.")
            ]),
            HelpSection(heading: "Workflow at a glance", body: [
                .bullets([
                    "Define a database server (and optionally an LLM server) in Settings (⌘,).",
                    "In the sidebar Connections section, add a connection that pairs those servers, then tap it to connect.",
                    "Select a project — the sidebar collapses automatically and loads data.",
                    "Choose a chart view from the ≡ menu in the top-right corner of the main area.",
                    "Adjust filters in the sidebar and tap Apply to refresh the map.",
                    "Each chart view remembers its own filter settings independently."
                ])
            ]),
            HelpSection(heading: "Data model", body: [
                .definition(term: "Journey / Case",  detail: "One end-to-end instance of a process, identified by EVENT_ID."),
                .definition(term: "Step / Event",    detail: "A single activity within a journey, stored as a row in JOURNEYS."),
                .definition(term: "Transition",      detail: "A chronologically consecutive pair of steps within the same journey."),
                .definition(term: "Meta attributes", detail: "Up to three free-text columns (META_1 – META_3) carrying case-level attributes such as department or customer segment.")
            ]),
            HelpSection(heading: "Sidebar sections", body: [
                .paragraph("The sidebar is organised into five collapsible sections: Connections, Projects, Metrics, Filters, and Configuration. All sections start collapsed when the app launches — only the Connections section is open, so you can select or verify a database connection immediately."),
                .paragraph("Once a connection is active and you select a project, the Projects section opens automatically. Tapping any section header toggles that section; the others remain as they are."),
                .tip("The sidebar opens at maximum width on launch so the Projects list is easy to reach. You can collapse the sidebar entirely by dragging its edge left or tapping the sidebar toggle button that appears in the top-left corner of the main area.")
            ]),
            HelpSection(heading: "Exporting this documentation", body: [
                .paragraph("You can save this entire user documentation as a PDF. In the Help window's title bar, click the share button (the ↑ box icon next to the close button). Process Mining Demonstrator renders the documentation and opens a Save panel so you can choose where to keep the file."),
                .paragraph("The exported file is a structured, paginated A4 document:"),
                .bullets([
                    "Cover page — the Process Mining Demonstrator logo, the 'User Documentation' title, and the export date.",
                    "Table of contents — every chapter, numbered, in reading order.",
                    "Chapters — each chapter begins on a new page and matches the Help topics shown on screen.",
                    "Page numbers — 'Page X of N' is printed at the bottom centre of every page."
                ]),
                .tip("The PDF always reflects the documentation built into the app you are running, so re-export it after updating Process Mining Demonstrator to capture the latest content.")
            ])
        ]
    )

    // MARK: Connections

    static let connecting = HelpTopic(
        id: "connecting", title: "Connections", subtitle: "Define servers in Settings, then pair them into connections",
        icon: "cylinder.split.1x2", color: .indigo,
        sections: [
            HelpSection(heading: "How connections work", body: [
                .paragraph("Process Mining Demonstrator separates the servers you talk to from the connections you use. You define Database servers and LLM servers once in the Settings window, then a connection simply pairs one database server with an optional LLM server."),
                .bullets([
                    "Database server – an Exasol host with its port, credentials, schema, and TLS settings.",
                    "LLM server – an OpenAI-compatible model server (URL, API key, model). Optional.",
                    "Connection – a named pairing of one database server with, optionally, one LLM server. Connections live in the sidebar."
                ]),
                .tip("Because servers are defined separately, several connections can reuse the same database or LLM server without re-entering its details.")
            ]),
            HelpSection(heading: "Managing servers in Settings", body: [
                .paragraph("Open Settings from the Process Mining Demonstrator menu (or press ⌘,). A category list on the left holds two sections — Database and LLM. Select an entry to edit it on the right, or use the Add button in each section to create a new server."),
                .bullets([
                    "Database server fields: Name, Comment, Host, Port, Username, Password, Schema, plus a Security section for TLS and RSA key size.",
                    "LLM server fields: Name, Comment, Server URL, API Key, Model."
                ]),
                .tip("Changes are saved automatically as you type — there is no Save button. Use the Delete button in the toolbar (or swipe a row in the list) to remove a server."),
                .warning("Deleting a server that a connection points to clears that reference. Edit the affected connection in the sidebar and pick a replacement server.")
            ]),
            HelpSection(heading: "Adding a connection", body: [
                .paragraph("Tap the + button in the Connections section header of the sidebar. The connection editor has just a few fields:"),
                .bullets([
                    "Name – a short label shown in bold on the connection card.",
                    "Comment – an optional one-line note (e.g. environment, purpose, or owner). Shown on the card below the name.",
                    "Database Server – pick one of the database servers defined in Settings (required).",
                    "LLM Server – optionally pick an LLM server to enable the AI features for this connection."
                ]),
                .tip("If the pickers are empty, open Settings (⌘,) first and add a database or LLM server. The password is stored securely and never written to disk in plain text.")
            ]),
            HelpSection(heading: "Connection card", body: [
                .paragraph("Each card in the Connections list shows the connection name (bold), the comment if one was entered, and the referenced servers on their own lines: 'Database: host:port' and, when an LLM server is attached, 'LLM: server URL'."),
                .paragraph("Up to two coloured dots appear on the right of the active connection. The first is the database state: green when connected, orange while connecting or after a failure. The second appears only when an LLM server is attached: blue when the model server is reachable, orange when it is not.")
            ]),
            HelpSection(heading: "TLS / SSL", body: [
                .paragraph("In a database server's Security section, enable Use TLS / SSL if your Exasol instance requires an encrypted connection."),
                .bullets([
                    "Verify (system trust) – validates the server certificate against the system trust store.",
                    "Skip verification – connects without validating the certificate. Use only on trusted networks.",
                    "Fingerprint – validates the server certificate against a known SHA-256 hex fingerprint."
                ]),
                .warning("Skipping certificate verification exposes you to man-in-the-middle attacks. Only use on private, isolated networks.")
            ]),
            HelpSection(heading: "RSA key size", body: [
                .paragraph("Exasol encrypts your password with an RSA public key during login — even without TLS. The server sends its public key during the handshake; Process Mining Demonstrator encrypts the password before transmitting it, so it is never sent in plain text."),
                .definition(term: "Min. RSA key size", detail: "The minimum modulus length (in bits) the server's RSA public key must have. Connections to servers with a shorter key are rejected before the password is sent."),
                .bullets([
                    "2048 bits (standard) — the default. Correct for all current Exasol versions.",
                    "1024 bits (legacy) — required for Exasol 7.x and the official DockerDB image, which still use 1024-bit RSA keys.",
                    "3072 / 4096 bits — for high-security environments that mandate longer keys."
                ]),
                .tip("If you see a 'RSA key too weak' error when connecting, set this to 1024 bits (legacy). This only lowers the minimum accepted key length — it has no effect on TLS.")
            ]),
            HelpSection(heading: "Testing servers", body: [
                .paragraph("Each server editor in Settings has a Test button so you can verify it without affecting any active connection."),
                .bullets([
                    "Database server – tap Test to open a temporary connection using the current values. A blue dot and 'Connection successful' confirms the credentials; a red ✕ with a short message describes the failure (wrong password, TLS error, host unreachable, …).",
                    "LLM server – tap Test to probe the model server. 'Server reachable' confirms connectivity; a red message means the URL is empty or invalid, or the server could not be reached."
                ]),
                .tip("Changing any database field resets its status to 'Not tested', so you can always tell whether the values shown have been verified.")
            ]),
            HelpSection(heading: "Connection errors", body: [
                .paragraph("When a connection attempt fails, Process Mining Demonstrator shows an alert that describes what went wrong and — where appropriate — offers a Retry option."),
                .bullets([
                    "Authentication failures (wrong username or password) show an informational alert. No retry is offered because the same credentials would fail again — open Settings to correct the database server's username or password.",
                    "Network errors (host unreachable, connection refused, timeout) and certificate errors show Retry and Cancel buttons. Tap Retry to reattempt immediately — useful when the server was momentarily unavailable."
                ]),
                .paragraph("Data load errors (project list, chart data, statistics) are reported the same way. A Retry button re-runs the failed query so you do not need to navigate away and back.")
            ]),
            HelpSection(heading: "Connecting & disconnecting", body: [
                .paragraph("Tap a connection card to connect. The status indicator turns green when active. Tap the active connection again to disconnect."),
                .paragraph("Only one connection can be active at a time. Switching connections automatically disconnects the previous one."),
                .paragraph("Disconnecting — or switching to a different connection — immediately clears all loaded data: the selected project, process map, KPIs, filter state, and statistics are all reset so the detail area returns to its empty state. The KPI panel and the date range slider are also hidden until a new connection and project are active."),
                .tip("After a successful connection the Connections section collapses automatically so the Projects list is visible immediately.")
            ])
        ]
    )

    // MARK: Chart Views

    static let chartViews = HelpTopic(
        id: "chartviews", title: "Chart Views", subtitle: "Process map, A/B comparison, and statistics",
        icon: "line.3.horizontal", color: .teal,
        sections: [
            HelpSection(heading: "Switching views", body: [
                .paragraph("Tap the ≡ icon in the top-right corner of the main area to open the view picker. A checkmark shows the currently active view."),
                .paragraph("The ≡ menu is only shown when a database connection is active and a project has been selected. It is hidden on launch and whenever no project is loaded."),
                .tip("The project title capsule in the navigation bar shows the currently active view name on a second line below the project title, so you can always see your context at a glance."),
                .tip("Each chart view stores its own filter state — switching views never loses your filter settings for another view.")
            ]),
            HelpSection(heading: "A-Chart", body: [
                .paragraph("The primary process map. Shows all journeys that match the current filter set as an aggregated flow chart. Arrow thickness reflects transition frequency."),
                .paragraph("When a project is first selected, A-Chart loads automatically using the last 30 days of data."),
                .tip("A date slider sits above the map once a project is loaded. In Range mode it shows two draggable thumbs; in Day mode a single thumb selects one calendar day. Switch modes in the Configuration section under Date slider.")
            ]),
            HelpSection(heading: "B-Chart", body: [
                .paragraph("An independent second process map with its own filter set. Use B-Chart to explore a different segment of the data — for example, a different date window, step selection, or meta attribute value."),
                .tip("B-Chart starts empty. Apply filters in the sidebar and tap Apply to load it. Alternatively, tap the 'Load' button shown on B-Chart's empty state to load it instantly using the current filter settings."),
                .tip("Like A-Chart, B-Chart has its own date slider above the map once a project is loaded. The Date slider mode setting in Configuration applies to both charts simultaneously.")
            ]),
            HelpSection(heading: "A/B Comparison", body: [
                .paragraph("Splits the main area vertically: the A-Chart is on the left, the B-Chart is on the right. Both charts are visible simultaneously."),
                .paragraph("The sidebar filters always operate on the active side. Switch the active side in two ways:"),
                .bullets([
                    "Tap the panel header strip (\"A-Chart\" or \"B-Chart\") above a chart.",
                    "Use the A-Chart / B-Chart segmented control at the top of the Filters section."
                ]),
                .paragraph("The header of the active panel shows a pencil icon and an \"editing\" label."),
                .paragraph("Each panel contains its own journey count KPI tile and an independent metric selector row. Tap any metric chip in a panel to change which value drives that chart's arrow thickness and labels — without affecting the other panel."),
                .tip("A-Chart and B-Chart each retain their layout (node positions) independently in the split view."),
                .paragraph("A copy icon button appears in the A-Chart panel header. Tap it to copy A-Chart's complete viewport to B-Chart — zoom level, pan position, and all node positions are transferred simultaneously. This is useful when you want both panels to start from exactly the same view before applying different filters to B."),
                .paragraph("A circular valve icon sits on the divider between the two panels. It controls whether pan, zoom, and node positions are synchronised between A and B:"),
                .definition(term: "Valve open (filled)", detail: "Both panels share a single viewport. Panning, zooming, double-tapping to reset, or dragging a node in either panel instantly updates the other."),
                .definition(term: "Valve closed (outline)", detail: "Each panel moves independently. Closing the valve snapshots A's current view and seeds it into B so both panels start at the same position before diverging."),
                .tip("A is always the master. Opening the valve causes B to adopt A's zoom, pan, and node positions at that moment. Closing keeps A's current state in B — it never resets to defaults."),
                .paragraph("Each panel has its own date slider above its chart, operating independently. A panel's slider is visible only once that panel has loaded data — the B-panel slider remains hidden until B is loaded for the first time. In Range mode, drag either panel's thumbs to adjust its date window. In Day mode, slide each panel's thumb to a specific day — useful for comparing the process on two distinct dates side by side. If no journeys exist on the selected day, the slider automatically jumps to the nearest date with data."),
                .paragraph("A Process Similarity badge floats between the two panels, horizontally centred, just below both panels' date slider groups. It shows the Q score in a compact chip coloured green (high similarity), blue (moderate), or red (strong divergence). The badge refreshes automatically whenever you apply filters or move a date slider in either panel."),
                .tip("Each panel has its own independent 'Presets' pill button in its header. You can apply different filter presets to the A and B panels simultaneously — checkmarks are tracked independently per panel. If a panel is empty, tap the 'Load' button shown on its empty state to load it with the current filter settings.")
            ]),
            HelpSection(heading: "Individual Journey", body: [
                .paragraph("Shows the complete step sequence for a single journey identified by EVENT_ID."),
                .paragraph("The Filters section changes to a single Event ID text field. Type a source identifier (e.g. ORD-000001) or a raw EVENT_ID hash and tap Load Journey (or press Return). Process Mining Demonstrator automatically MD5-hashes any input that is not already a 32-character hex string before querying the database — so you never need to compute or paste a hash manually."),
                .paragraph("A live suggestion dropdown appears as you type, showing matching EVENT_IDs stored in the database. Tap a suggestion to load that journey immediately — suggestions are already hashed values and are used as-is."),
                .bullets([
                    "Date of Journey KPI — the timestamp of the first event in the journey.",
                    "Sum of Scores KPI — the sum of SCORE values across all distinct steps in the journey."
                ]),
                .tip("Each EVENT_ID gets its own saved layout. Switching to another journey and back restores your previous node positions.")
            ]),
            HelpSection(heading: "Statistics", body: [
                .paragraph("The Statistics view analyses all journey routes that match the current filters. A Routes / Analytics segmented control at the top switches between the two sections."),
                .paragraph("A collapsible KPI strip sits above the segmented control. It shows the same tiles as the single-chart views — Total Journeys, Filtered Journeys, duration statistics, Graph Value, and Process Goodness — all subject to the same KPI visibility toggles in Configuration. Tap the chevron handle to collapse or expand the strip."),
                .paragraph("Tap Compute Routes to run the analysis."),
                .bullets([
                    "Routes — Journeys Over Time area chart followed by every distinct step sequence with journey count, step count, score per journey, and total aggregated score.",
                    "Analytics — Four visualisations arranged in two side-by-side pairs.",
                ]),
                .definition(term: "Step Frequency",
                            detail: "Horizontal bar chart showing how often each step is visited (max of incoming and outgoing transitions), top 20 by traffic. The exact count is printed to the right of each bar."),
                .definition(term: "Journey Exit Points",
                            detail: "Horizontal bar chart of the last step reached in each journey path, top 15 by occurrence. Highlights where journeys most commonly terminate. Counts are printed to the right of each bar."),
                .definition(term: "Transition Heatmap",
                            detail: "Square grid showing step-to-step transition frequencies for the top 25 transitions. Cells are colour-coded from red (low) to green (high); empty cells are dimmed. A colour-scale legend appears to the right. Hover over a cell (or tap on touch) to see the exact count and step names in the tooltip bar above the grid."),
                .definition(term: "Journey Duration Distribution",
                            detail: "Vertical bar chart with 10 equal-width bins spanning the full range of actual journey durations. Bin edges are labelled with adaptive units (s, m, h, d) and the count is shown above each bar. Bins and labels are computed dynamically from the data — they change with every filter or project."),
                .definition(term: "Filter integration",
                            detail: "Statistics always inherit the filter state of Chart A (date range, include/exclude steps, meta attributes, score range, journey-time range). Navigating to Statistics automatically applies the current Chart A filters. If you change any filter after loading statistics, an orange 'Filters changed since last load' banner appears with a one-tap Reload button."),
                .definition(term: "Route limit",
                            detail: "Use the Limit picker (100 / 250 / 500 / 1 000 / 2 500) in the toolbar to cap the number of routes returned. An orange warning badge appears when results are truncated."),
                .definition(term: "Sorting",
                            detail: "Tap any column header in the route table to sort by that column. Tap again to reverse the order."),
                .definition(term: "Score / J",
                            detail: "The average score per journey for this route, based on SCORE values in the STEPS table."),
                .definition(term: "Total score",
                            detail: "Score per journey multiplied by the journey count — the overall impact of this route."),
                .tip("The route table wraps long journey paths across multiple lines so no path text is ever truncated."),
                .tip("The Journeys Over Time granularity is chosen automatically: ≤14 days → daily, ≤90 days → weekly, >90 days → monthly.")
            ]),
            HelpSection(heading: "Notes", body: [
                .paragraph("The Notes view shows your own notes plus any notes marked as shared by other users for the current project. Select Notes from the ≡ view picker to open it."),
                .paragraph("Notes are listed newest-first. Each row shows the annotation target (step name or edge direction), the author username, a teal person icon if the note is shared, the creation timestamp, the note text, and — if the note has been edited — an italic 'Edited [date]' line below the text."),
                .paragraph("Tap any row to open that note in the editor and update it. Swipe a row left and tap Delete to remove a note without opening it."),
                .tip("The Notes view is not filtered by the active sidebar filters — all visible notes for the project are shown regardless of the current date range or step selection.")
            ]),
            HelpSection(heading: "AI supported Documentation", body: [
                .paragraph("Sends the current process data to a language model and displays the AI response as formatted Markdown. The analysis always uses the A-Chart filter conditions — date range, step inclusion/exclusion, meta filters, and journey count."),
                .tip("See the AI Documentation chapter for full setup instructions, prompt customisation, notes integration, and export options.")
            ])
        ]
    )

    // MARK: Filters

    static let filters = HelpTopic(
        id: "filters", title: "Filters", subtitle: "Date range, steps, score, and meta filters",
        icon: "line.3.horizontal.decrease.circle.fill", color: .orange,
        sections: [
            HelpSection(heading: "Transition Metrics", body: [
                .paragraph("The Metrics section sits above the Filters section in the sidebar. It controls which value is used to calculate the thickness, opacity, and label of each transition arrow in the process map."),
                .definition(term: "Count",    detail: "Number of times this transition occurred. This is the default and always available."),
                .definition(term: "Avg Time", detail: "Average elapsed time between the two steps, in seconds. Shown as a human-readable duration (e.g. 4m, 1.2h, 3.5d)."),
                .definition(term: "Min Time", detail: "Shortest observed elapsed time for this transition."),
                .definition(term: "Max Time", detail: "Longest observed elapsed time for this transition."),
                .definition(term: "Std Dev",  detail: "Standard deviation of elapsed times — higher values indicate inconsistent transition durations."),
                .paragraph("Select a metric by tapping its chip. The map redraws immediately: the thickest, most opaque arrow always represents the highest value for the chosen metric."),
                .tip("Each chart view (A-Chart, B-Chart, Individual Journey, etc.) stores its own metric selection independently."),
                .tip("Each metric has its own configurable color scale for connection colorization. A small gradient indicator (Low → High) is shown in the bottom-right corner of the map next to the zoom buttons whenever colorization is active. Configure scales in Settings (⌘,) → Appearance → Flow Chart.")
            ]),
            HelpSection(heading: "Per-chart filter state", body: [
                .paragraph("Every chart view (A-Chart, B-Chart, Individual Journey, etc.) stores its own filter state independently. Changing filters on A-Chart never affects B-Chart."),
                .tip("Switching chart views saves the current filter state and restores the state you last used for the target view.")
            ]),
            HelpSection(heading: "Date range", body: [
                .paragraph("Restricts the data to journeys that contain at least one event within the selected date window. A date slider appears at the top of every chart view and lets you adjust the window without opening the sidebar."),
                .paragraph("The slider has two modes, selectable in the Configuration section of the sidebar under Date slider:")
            ]),
            HelpSection(heading: "Range mode", body: [
                .paragraph("Fixed labels showing the dataset minimum date (left) and maximum date (right) flank a draggable range track. The selected span is highlighted on the track."),
                .bullets([
                    "Drag the left thumb to move the start date forward.",
                    "Drag the right thumb to pull the end date back.",
                    "A date badge floats above each thumb at all times, showing the current date. While dragging, the badge follows the thumb live."
                ]),
                .paragraph("The graph reloads automatically when you release a thumb. The track spans the full date range of the project data, from the earliest to the latest recorded event."),
                .tip("When you first select a project, the start date defaults to 30 days before the most recent event and the end date defaults to the most recent event date.")
            ]),
            HelpSection(heading: "Day mode", body: [
                .paragraph("Fixed labels showing the dataset minimum date (left) and maximum date (right) flank a single draggable thumb that represents one calendar day. Only journeys that contain at least one event on that exact day are included in the map."),
                .bullets([
                    "Drag the thumb to slide through the timeline and land on a specific day.",
                    "A date badge always floats above the thumb, tracking it live during a drag."
                ]),
                .paragraph("Day mode is useful for exploring how the process looked on a specific date — for example a day with an incident, a campaign launch, or an end-of-month peak."),
                .tip("If no journeys exist on the selected day, an info notice appears and the slider automatically jumps to the nearest date that does have data — forward in time first, then backward."),
                .tip("In A/B Comparison, each panel has its own independent slider. Set the A panel to one day and the B panel to another to compare process behaviour across two specific dates.")
            ]),
            HelpSection(heading: "Include Steps", body: [
                .paragraph("Show only journeys that passed through at least one of the selected steps."),
                .tip("Include is evaluated at journey level: if any event in a journey matches a selected step, the whole journey is included."),
                .warning("A step selected in Include Steps is automatically disabled in Exclude Steps, and vice versa.")
            ]),
            HelpSection(heading: "Exclude Steps", body: [
                .paragraph("Remove all journeys that contain at least one of the selected steps. The excluded journeys are completely removed from the map and journey counts."),
                .tip("Exclusion is evaluated at journey level — it removes the entire case, not just that single event.")
            ]),
            HelpSection(heading: "Num Steps", body: [
                .paragraph("A double-ended range slider that limits results to journeys whose total step count falls within the selected minimum and maximum."),
                .paragraph("The slider bounds are determined automatically from the data when a project is loaded. Drag the left handle to raise the minimum, and the right handle to lower the maximum."),
                .tip("The value labels above the slider track update in real time as you drag, so you always see the exact selection before releasing."),
                .tip("The current range is shown in a small badge next to the section header. Tap the × beside it to reset both handles to the project-wide bounds.")
            ]),
            HelpSection(heading: "Journey Time", body: [
                .paragraph("A double-ended range slider that limits results to journeys whose total duration (first event to last event) falls within the selected range."),
                .paragraph("The slider bounds are determined automatically when a project is loaded. Duration values are displayed in a human-readable unit — seconds, minutes, hours, or days."),
                .tip("The value labels above the slider track update in real time as you drag, so you always see the exact selection before releasing."),
                .tip("The active range appears as a badge next to the header. Tap × to reset both handles to the project-wide bounds.")
            ]),
            HelpSection(heading: "Journey Score", body: [
                .paragraph("A double-ended range slider that limits results to journeys whose aggregated score falls within the selected range."),
                .paragraph("The aggregated score for a journey is the sum of SCORE values (from the STEPS table) across every step the journey contains. Slider bounds are calculated automatically from the minimum and maximum scores across all journeys in the project."),
                .tip("The value labels above the slider track update in real time as you drag, so you always see the exact selection before releasing."),
                .tip("Negative scores are fully supported. Drag the left handle above zero to see only positively-scored journeys, or drag the right handle below zero to isolate problem paths.")
            ]),
            HelpSection(heading: "Meta filters", body: [
                .paragraph("Free-text fields that perform a case-insensitive contains search on META_1, META_2, or META_3. Labels come from the METAS table and are configured per project."),
                .tip("Start typing to see autocomplete suggestions drawn from distinct values in the database.")
            ]),
            HelpSection(heading: "Individual Journey filter", body: [
                .paragraph("When the Individual Journey view is active, the entire Filters section is replaced by an Event ID input with live autocomplete."),
                .definition(term: "Source ID lookup", detail: "Type a human-readable source identifier such as ORD-000001. Process Mining Demonstrator MD5-hashes the input before querying, so it matches the hash stored in the database — no manual hashing required."),
                .definition(term: "Hash lookup",      detail: "Paste or type a raw 32-character hex EVENT_ID directly. Process Mining Demonstrator detects the format and uses it as-is without a second hash pass."),
                .definition(term: "Autocomplete",     detail: "A suggestion dropdown appears after the second character, showing EVENT_IDs (hashes) from the database that match your input as a prefix. Tap a suggestion to load that journey immediately."),
                .tip("Type the full source identifier (e.g. ORD-000042) and press Return to load the journey. You can also select a suggestion from the autocomplete dropdown — Process Mining Demonstrator detects whether the input is already a hash and avoids double-hashing automatically."),
                .paragraph("Switching back to A-Chart or B-Chart restores the full filter panel with all your previous settings intact.")
            ]),
            HelpSection(heading: "A/B Comparison filter", body: [
                .paragraph("When A/B Comparison is active, a segmented A-Chart / B-Chart control appears at the top of the Filters section. The selected segment determines which chart the filters apply to."),
                .tip("You can also switch the active side by tapping the panel header above either chart.")
            ]),
            HelpSection(heading: "Applying and resetting filters", body: [
                .paragraph("Filters are not applied automatically. Three buttons sit at the bottom of the Filters section:"),
                .definition(term: "Reset",        detail: "Restores all filters to the default state: date range reset to the project window, steps and meta fields cleared, and all sliders returned to their project-wide bounds."),
                .definition(term: "Save Preset…", detail: "Captures the current filter state as a named preset so you can reapply it later from any chart view. You are prompted for a name before the preset is saved."),
                .definition(term: "Apply",         detail: "Reloads the map with all current filter settings applied."),
                .bullets([
                    "Filtered Journeys KPI updates to show matches for the active filters.",
                    "Total Journeys always reflects the unfiltered project count.",
                    "In A/B Comparison only the active side is reloaded — the other side is unchanged."
                ]),
                .tip("Once a preset is saved, the 'Presets' pill button appears in every chart header. Tap it to apply any saved preset directly — no need to open the sidebar.")
            ])
        ]
    )

    // MARK: Filter Presets

    static let filterPresets = HelpTopic(
        id: "filterpresets", title: "Filter Presets", subtitle: "Save and reapply named filter configurations",
        icon: "slider.horizontal.3", color: .indigo,
        sections: [
            HelpSection(heading: "What is a filter preset?", body: [
                .paragraph("A filter preset captures a complete snapshot of all active filter settings — date range, included and excluded steps, meta attribute values, step count bounds, journey time bounds, and score bounds — and saves it under a name of your choice."),
                .paragraph("Presets are stored per project, so each project has its own independent list. They persist between sessions and are included in the Backup & Restore export.")
            ]),
            HelpSection(heading: "Saving a preset", body: [
                .paragraph("Configure all desired filters in the Filters section of the sidebar. When the combination is ready, tap 'Save Preset…' — the button sits between the Reset and Apply buttons at the bottom of the Filters section."),
                .paragraph("You will be prompted for a name. The current filter state is captured at the moment you tap Save — changing filters afterwards does not update the preset."),
                .tip("You can save as many presets as you like. Each preset is a complete snapshot of all filter dimensions, not just the ones you changed from their defaults.")
            ]),
            HelpSection(heading: "Applying a preset", body: [
                .paragraph("Every chart view — A-Chart, B-Chart, both A/B Comparison panels, Conformance Check, and Happy Path — shows a 'Presets' pill button in its header. Tap it to open the dropdown list of saved presets."),
                .paragraph("Tap a preset name to apply it. All filter settings are restored instantly and the chart reloads automatically. A checkmark marks the most recently applied preset."),
                .tip("In A/B Comparison, each panel has its own independent Presets button. You can apply different presets to the A and B panels simultaneously — checkmarks are tracked independently per panel."),
                .tip("The date slider in a chart view is automatically updated to reflect the preset's saved date range when a preset is applied.")
            ]),
            HelpSection(heading: "Renaming and deleting", body: [
                .paragraph("Open the Presets dropdown in any chart header. Below the preset list, after a separator:"),
                .definition(term: "Rename…", detail: "Renames the most recently applied preset (the one with a checkmark). A text field lets you enter the new name."),
                .definition(term: "Delete",   detail: "Permanently removes the most recently applied preset. This action cannot be undone."),
                .tip("Rename and Delete always act on the checkmarked preset. Apply the preset you want to manage before choosing one of these actions.")
            ]),
            HelpSection(heading: "Backup & Restore", body: [
                .paragraph("All filter presets for all projects are included in a Backup & Restore export and restored on import. The Backup Preview shows 'Filter Presets: Yes / No' so you can confirm presets are present before restoring.")
            ])
        ]
    )

    // MARK: Process Map

    static let processMap = HelpTopic(
        id: "processmap", title: "Process Map", subtitle: "Navigation, nodes, groups, and context actions",
        icon: "arrow.triangle.branch", color: .cyan,
        sections: [
            HelpSection(heading: "Reading the map", body: [
                .paragraph("Each node represents a distinct process step. Arrows show transitions between steps — the thickness and opacity of an arrow reflects the selected Transition Metric relative to the highest value visible on the map."),
                .paragraph("The label on each arrow shows the value for the active metric: a plain number for Count, or a human-readable duration (e.g. 4m, 1.2h, 3.5d) for time-based metrics. Select a metric in the Metrics section of the sidebar.")
            ]),
            HelpSection(heading: "Connection coloring", body: [
                .paragraph("When 'Colorize connections by weight' is enabled (Settings ⌘, → Appearance → Flow Chart), each transition arrow is tinted using the color scale configured for the active Transition Metric."),
                .paragraph("The scale runs from the low-end color (few occurrences / short duration) to the high-end color (many occurrences / long duration). Arrow thickness and opacity always encode the same value independently of color."),
                .paragraph("A color scale indicator appears in the bottom-right corner of the map, to the left of the zoom buttons. It shows the active metric's icon, name, and a gradient bar labelled Low → High. The indicator is only visible when colorization is on."),
                .definition(term: "Per-metric scales", detail: "Each of the five Transition Metrics (Count, Avg Time, Min Time, Max Time, Std Dev) has its own independent color scale. Switching the active metric changes both arrow thickness and color scheme simultaneously. Default scales: Count → green (more = notable), Avg Time → orange, Min Time → blue, Max Time → red (longer = notable), Std Dev → purple."),
                .tip("Configure each metric's color scale in Settings (⌘,) → Appearance → Flow Chart. Tap 'Reset to Defaults' to restore the built-in scales.")
            ]),
            HelpSection(heading: "Start and end node indicators", body: [
                .paragraph("Process Mining Demonstrator automatically identifies the structural entry and exit points of your process and marks them with prominent colored indicators:"),
                .definition(term: "Green arrow (entry)", detail: "A green dot-and-arrow indicator appears above every start node — any step that has no incoming transitions from other steps. The arrowhead points downward toward the node, signalling where the process begins."),
                .definition(term: "Orange arrow (exit)", detail: "An orange dot-and-arrow indicator appears below every end node — any step that has no outgoing transitions to other steps. The arrowhead points downward away from the node, signalling where the process terminates."),
                .paragraph("When a step belongs to a group, both indicators are drawn outside the group's dashed border so they remain clearly visible regardless of grouping."),
                .tip("A single isolated node (no transitions at all) receives both a green entry indicator above and an orange exit indicator below.")
            ]),
            HelpSection(heading: "Auto-fit", body: [
                .paragraph("When a project is first selected or you switch to a different project, the map automatically fits all nodes into the visible area. The view also re-fits if the window is resized."),
                .paragraph("Applying filters preserves your current zoom level, pan position, and any custom node positions — the map redraws in place without jumping back to the auto-fit view."),
                .tip("To return to the auto-fit view at any time, double-tap the map, or tap the reset arrow button (⟲) in the bottom-right corner.")
            ]),
            HelpSection(heading: "Navigating the map", body: [
                .bullets([
                    "Pinch to zoom in or out.",
                    "Drag on an empty area to pan.",
                    "Double-tap to reset zoom and pan to the default position.",
                    "Use the ± buttons in the bottom-right corner for precise zoom control.",
                    "Tap the reset arrow button (⟲) to restore the default zoom and position.",
                    "When step groups are active, a compress/expand icon appears in the bottom-right controls. Tap it to collapse all groups into proxy nodes, or expand them all back to individual steps."
                ])
            ]),
            HelpSection(heading: "Moving nodes", body: [
                .paragraph("Drag any node to reposition it. The new position is saved automatically per project and per chart view — moving a node in A-Chart does not affect B-Chart or any other view."),
                .paragraph("Tap the counterclockwise arrow button (↺) in the bottom-right corner to discard all custom positions and revert to the automatic layout. The quality of the automatic layout depends on the 'Optimise layout' toggle in the Configuration section — when enabled, crossing minimisation produces a cleaner arrangement on complex graphs."),
                .tip("Each Individual Journey also saves its own layout keyed to the EVENT_ID.")
            ]),
            HelpSection(heading: "Node context menu", body: [
                .paragraph("Tap any node once to open a small action card directly on the map. The following actions are available:"),
                .definition(term: "Require in journeys",  detail: "Adds the step to the Include Steps filter. Only journeys that passed through this step appear in the map. Applied immediately."),
                .definition(term: "Exclude from journeys", detail: "Adds the step to the Exclude Steps filter. All journeys containing this step are removed from the map. Applied immediately."),
                .definition(term: "Show Notes",             detail: "Opens the notes interface for this node. If no note exists, the editor opens immediately for a new note. If one note exists, the editor opens for that note. If multiple notes exist, a list sheet appears showing each note with its author, date, and a preview — tap any row to open the editor, swipe left to delete, or tap 'Add Note' at the bottom to create a new one."),
                .definition(term: "Show description",      detail: "Displays the full DESCRIPTION text for this step in an overlay card. Only appears when the step has a description that differs from its name."),
                .tip("Tap outside the card or start a drag to dismiss it without taking any action. Double-tapping a node resets the zoom and pan instead of opening the menu.")
            ]),
            HelpSection(heading: "Node appearance", body: [
                .paragraph("Node colours and shapes come from the STEPS table and can be customised in the Configuration section of the sidebar."),
                .bullets([
                    "Stadium — pill-shaped node for standard process steps.",
                    "Round corners — rectangular node with rounded corners.",
                    "Hexagon — six-sided shape, useful for decision points or gateways.",
                    "Circle — circular node, typically used for start or end events."
                ]),
                .paragraph("An orange dot in the top-right corner of a node indicates it is marked as an end-of-process step. A small score badge on the top-left shows the step's score value — green for positive scores, red for negative scores, and blue for zero."),
                .paragraph("When a step has a description set and it differs from the step name, the node is divided into two rows: the step name on top and a shortened version of the description (up to 20 characters) below it in a lighter style."),
                .paragraph("A small yellow ✎ badge appears in the upper-right area of a node when a process note is attached to it (and the Show node notes toggle is on). A yellow dot near the midpoint of a transition arrow indicates a note on that edge.")
            ]),
            HelpSection(heading: "Step grouping", body: [
                .paragraph("Steps that share the same BELONGS_TO value are visually grouped inside a rounded, dashed border. The group's name appears as a colored pill badge centered on the top edge of the border, using the group's assigned color."),
                .paragraph("Grouping can be toggled on or off using the Show step groups switch in the Configuration section. When off, all group borders and badges are hidden."),
                .paragraph("When grouping is on, the Groups start picker (directly below the toggle) controls how groups appear each time a project loads:"),
                .bullets([
                    "Expanded — all groups open, showing every individual step.",
                    "Collapsed — each group folds into a single proxy node on load.",
                    "Persisted — restores each group's collapsed/expanded state from your last session."
                ]),
                .paragraph("To quickly change all groups at once, use the compress/expand icon in the bottom-right controls strip (visible only when grouping is on). One tap collapses every group; a second tap expands them all again."),
                .tip("Groups are colored automatically and consistently — the same group name always produces the same color.")
            ]),
            HelpSection(heading: "Toolbar stats", body: [
                .paragraph("The toolbar shows the total number of transitions and distinct steps visible for the active filters. These counts update each time you tap Apply.")
            ]),
            HelpSection(heading: "Self-loops", body: [
                .paragraph("A step that transitions to itself (e.g. a repeated activity) is drawn as a small loop arc above the node.")
            ])
        ]
    )

    // MARK: KPI Panel

    static let kpi = HelpTopic(
        id: "kpi", title: "KPI Panel", subtitle: "Journey counts, durations, and score tiles",
        icon: "chart.bar.fill", color: .purple,
        sections: [
            HelpSection(heading: "Visibility", body: [
                .paragraph("The KPI panel and the date range slider are only shown once a chart has been loaded with data. Both elements are automatically hidden on launch, after disconnecting, whenever no project is selected, and on any chart view that has not yet been loaded."),
                .paragraph("A-Chart loads automatically when a project is selected. B-Chart, the B-panel in A/B Comparison, and Individual Journey show their KPI and slider only after their first successful data load.")
            ]),
            HelpSection(heading: "Collapsing the panel", body: [
                .paragraph("Tap the chevron handle between the KPI panel and the map to collapse or expand it. When collapsed, the journey counts are shown inline in the handle bar to save vertical space.")
            ]),
            HelpSection(heading: "A-Chart & B-Chart KPIs", body: [
                .definition(term: "Total Journeys",    detail: "Number of distinct journeys in the project with no filters applied. Does not change when you adjust filters."),
                .definition(term: "Filtered Journeys", detail: "Number of distinct journeys matching all currently applied filters. This is the population the map visualises."),
                .definition(term: "Shortest Journey",  detail: "Duration of the fastest journey in the filtered set, from its first to its last event."),
                .definition(term: "Avg Journey",       detail: "Mean duration across all filtered journeys."),
                .definition(term: "Std Dev",           detail: "Standard deviation of journey durations in the filtered set. A low value means most journeys take a similar amount of time; a high value means durations vary widely."),
                .definition(term: "Longest Journey",   detail: "Duration of the slowest journey in the filtered set."),
                .definition(term: "Graph Value",       detail: "Sum of (step score × visit count) for every scored node visible in the current map. Visit count is estimated as the larger of all incoming and outgoing transition occurrences for that node, so start nodes (no incoming) and end nodes (no outgoing) are handled correctly. Only nodes that have a SCORE configured in the STEPS table contribute. A higher value means high-scoring steps are visited frequently."),
                .definition(term: "Process Goodness",  detail: "A composite quality score for the process as a whole. It rewards paths where high-scoring steps are reached efficiently and penalises slow or low-scoring routes. A coverage factor reduces the score when only a fraction of all journeys match the current filter. See the Process Goodness help chapter for the full formula and worked examples."),
                .tip("Durations are shown in the most readable unit: seconds, minutes, hours, or days.")
            ]),
            HelpSection(heading: "A/B Comparison KPIs", body: [
                .paragraph("In A/B Comparison mode the top KPI strip is replaced by per-panel KPI strips. Each panel has its own collapsible row showing all the same tiles as the single-chart view, plus one additional comparison tile:"),
                .definition(term: "Process Goodness (coloured)", detail: "The same formula as in single-chart mode, but coloured green when this panel's value exceeds the other panel's, red when it is lower, and blue when both panels are equal within 0.005."),
                .paragraph("Process Similarity is not shown inside either panel's KPI strip. Instead, it appears as a compact horizontal badge floating between the two panels, positioned just below the date range slider group. The badge shows the icon, the 'Similarity' label, and the Q score — all on one line — coloured green (Q ≥ 0.70), blue (0.30–0.70), or red (Q < 0.30). See the Process Similarity help chapter for the full formula and worked examples."),
                .tip("Process Similarity is recomputed automatically whenever you apply filters to either panel or move a date slider. It is skipped (badge hidden) when the combined variant count exceeds 1 000 as a performance guard. Individual Journey KPI tiles are hidden until a journey is loaded."),
                .tip("Each panel's KPI strip and date slider are hidden until that panel has loaded data. The B-panel starts empty — its KPI and slider appear only after the first load.")
            ]),
            HelpSection(heading: "Individual Journey KPIs", body: [
                .paragraph("When inspecting a single journey the KPI panel shows a horizontal scrollable row of metric tiles. Swipe the panel sideways if all tiles do not fit at once."),
                .definition(term: "Date of Journey",         detail: "The date of the first recorded event for the loaded EVENT_ID."),
                .definition(term: "Sum of Scores",           detail: "The sum of SCORE values across all distinct steps that appear in the journey. Positive values are shown with a + prefix."),
                .definition(term: "Steps visited / distinct", detail: "Total step events in the journey (including repeated visits) versus the number of unique step names. For example '7 / 4' means seven events but only four distinct steps."),
                .definition(term: "META tiles",              detail: "One tile per configured META column that has a non-empty value on the loaded journey. The tile label uses the display name from the METAS table (e.g. 'Region', 'Product')."),
                .tip("META tiles only appear when a title is configured in the METAS table AND the loaded journey has a non-empty value for that column.")
            ])
        ]
    )

    // MARK: Process Goodness

    static let processGoodness = HelpTopic(
        id: "processgoodness", title: "Process Goodness", subtitle: "How the quality score is calculated",
        icon: "gauge.high", color: .mint,
        sections: [
            HelpSection(heading: "What it measures", body: [
                .paragraph("Process Goodness is a single number that summarises how well your process is performing across all journeys matching the current filters. It combines three ideas into one score:"),
                .bullets([
                    "Quality — do journeys pass through high-scoring steps?",
                    "Efficiency — are journeys short, or do they take a long time?",
                    "Coverage — how large a fraction of total journeys do the current filters capture?"
                ]),
                .paragraph("Higher values are better. A positive score means the process delivers net value relative to its time cost. A negative score means slow, low-scoring routes are dragging overall quality down."),
                .tip("Process Goodness is only shown when at least one step has a SCORE value configured in the STEPS table. If no scores are set, the tile is hidden.")
            ]),

            HelpSection(heading: "The formula", body: [
                .paragraph("The score is computed in two stages. First, a raw goodness is calculated across all distinct path patterns:"),
                .code("""
raw = Σ (freq / total) × (sum_of_scores / √n − 0.01 × avg_duration)
"""),
                .paragraph("Where the sum runs over every distinct path pattern in the filtered set. Then a coverage factor is applied:"),
                .code("""
Process Goodness = raw × (filtered_journeys / total_journeys)^0.5
"""),
                .paragraph("That is all. Everything else is just understanding what each symbol means — which the following sections explain one by one.")
            ]),

            HelpSection(heading: "Inside the formula: each term explained", body: [
                .definition(term: "freq / total",
                    detail: "The relative frequency of this path pattern. A path taken by 80 out of 100 journeys has freq/total = 0.80. More common paths have a stronger influence on the final score — the formula is a weighted average, not a simple average."),
                .definition(term: "sum_of_scores",
                    detail: "The sum of SCORE values (from the STEPS table) for every step in this path. If a step has no score it contributes zero. A path through high-value steps produces a large positive sum; a path through penalised steps (negative scores) can produce a negative sum."),
                .definition(term: "√n  (alpha = 0.5)",
                    detail: "The square root of the number of steps in the path. Dividing by √n means longer paths must earn proportionally more total score to keep up with shorter paths — but the penalty grows slowly (as a square root, not linearly). A 4-step path divides by 2; a 9-step path divides by 3. This discourages unnecessary detours without harshly punishing genuinely complex processes."),
                .definition(term: "0.01 × avg_duration",
                    detail: "A time penalty. avg_duration is the average total journey time in seconds for this path pattern. Multiplying by 0.01 means every 100 seconds of journey time costs 1.0 point. Fast paths are rewarded; slow paths are penalised. The constant 0.01 is chosen so that moderate durations (a few minutes) impose a small but noticeable penalty."),
                .definition(term: "(filtered / total)^0.5  (gamma = 0.5)",
                    detail: "The coverage factor. If your current filters capture only half of all journeys, this term equals √0.5 ≈ 0.71 and reduces the score by about 29 %. The idea is that a goodness score computed from a narrow slice of data should be taken with more caution than one computed from the full population. When no filters are active, coverage = 1.0 and the factor has no effect."),
                .tip("All four fixed constants — alpha=0.5, time_penalty=0.01, gamma=0.5 — are embedded in the formula. They reflect a balanced default and are not adjustable in the current version.")
            ]),

            HelpSection(heading: "Example 1 — two paths, short vs. long", body: [
                .paragraph("A digital checkout process has 100 orders. 85 take the direct path; 15 use a coupon step."),
                .code("""
Path A  (85 journeys): Browse → Cart → Pay → Confirm
  Scores: 2 + 3 + 10 + 10 = 25    Steps: 4    Avg duration: 30 s

Path B  (15 journeys): Browse → Cart → Coupon → Pay → Confirm
  Scores: 2 + 3 + 1 + 10 + 10 = 26    Steps: 5    Avg duration: 60 s
"""),
                .paragraph("Calculation for Path A:"),
                .code("""
quality   = 25 / √4 = 25 / 2     = 12.50
time cost = 0.01 × 30            =  0.30
path score = 12.50 − 0.30        = 12.20
weighted   = 0.85 × 12.20        = 10.37
"""),
                .paragraph("Calculation for Path B:"),
                .code("""
quality   = 26 / √5 ≈ 26 / 2.24  = 11.61
time cost = 0.01 × 60            =  0.60
path score = 11.61 − 0.60        = 11.01
weighted   = 0.15 × 11.01        =  1.65
"""),
                .paragraph("Combined result (all 100 journeys in filter, 100 total):"),
                .code("""
raw = 10.37 + 1.65 = 12.02
coverage = 100 / 100 = 1.0    →  factor = √1.0 = 1.00

Process Goodness = 12.02 × 1.00 = +12.02
"""),
                .tip("Notice that Path B contributes slightly less per journey (11.01 vs 12.20) even though it collects one extra score point. The longer path and slower duration partially offset the extra point. The formula captures this tradeoff automatically.")
            ]),

            HelpSection(heading: "Example 2 — a failed-payment path with negative scores", body: [
                .paragraph("The same checkout process, but now 10 orders encounter a payment failure and are refunded. Step scores: Pay Failed = −10, Refund = −5."),
                .code("""
Path A  (80 journeys): Browse → Cart → Pay → Confirm
  Scores: 25    Steps: 4    Avg duration: 30 s    (same as before)

Path B  (10 journeys): Browse → Cart → Coupon → Pay → Confirm
  Scores: 26    Steps: 5    Avg duration: 60 s    (same as before)

Path C  (10 journeys): Browse → Cart → Pay → Pay Failed → Refund
  Scores: 2 + 3 + 10 + (−10) + (−5) = 0    Steps: 5    Avg duration: 90 s
"""),
                .paragraph("Path C contributes:"),
                .code("""
quality   = 0 / √5 = 0
time cost = 0.01 × 90 = 0.90
path score = 0 − 0.90        = −0.90
weighted   = 0.10 × (−0.90)  = −0.09
"""),
                .paragraph("Combined result:"),
                .code("""
Path A weighted: 0.80 × 12.20 =  9.76
Path B weighted: 0.10 × 11.01 =  1.10
Path C weighted:              = −0.09

raw = 9.76 + 1.10 − 0.09 = 10.77
coverage = 1.0

Process Goodness = +10.77   (was +12.02 before failures appeared)
"""),
                .paragraph("The failed-payment path reduces the score from +12.02 to +10.77 — a drop of 1.25 points — even though it affects only 10 % of journeys. The combined effect of zero quality score and additional time makes it a net negative contributor."),
                .tip("Use this pattern to detect problem paths. When you notice a sudden drop in Process Goodness between two date periods, filter to isolate paths through specific problem steps — the goodness score will confirm whether those paths are truly responsible for the decline.")
            ]),

            HelpSection(heading: "Example 3 — the coverage penalty when filtering", body: [
                .paragraph("You apply a region filter — 'Europe only' — and now only 40 of the 100 total orders match. Within those 40 orders there are no payment failures, so the path mix looks like Example 1 (clean process). The raw goodness is the same: +12.02."),
                .paragraph("However, the coverage factor now kicks in:"),
                .code("""
coverage = 40 / 100 = 0.40
factor   = √0.40 ≈ 0.632

Process Goodness = 12.02 × 0.632 ≈ +7.60
"""),
                .paragraph("The filtered Europe result (+7.60) looks worse than the global result (+12.02), not because Europe performs worse, but because the filter captures a smaller proportion of the total population. The score reflects both quality and representativeness."),
                .paragraph("This behaviour is intentional: a goodness score computed from 40 % of your data deserves less absolute weight than one computed from 100 %. When comparing two filter configurations, keep coverage in mind — a high goodness from a tiny slice can be misleading."),
                .tip("To compare two segments fairly, switch to A/B Comparison mode: set A to one segment and B to the other. The Process Goodness tile in each panel applies the same formula independently, so the scores are directly comparable even if the two panels have different filtered journey counts.")
            ]),

            HelpSection(heading: "Requirements and limitations", body: [
                .bullets([
                    "At least one step must have a non-zero SCORE value in the STEPS table. Without scores the tile is hidden.",
                    "The query uses LISTAGG to group journeys by path pattern — on very large, heavily filtered datasets it may take several seconds. A 30-second timeout applies; if it expires the tile shows '—'.",
                    "Average duration per path pattern is used as the time component. Individual journeys may differ from this average.",
                    "Steps with no SCORE set contribute 0 to the quality sum — they neither help nor hurt.",
                    "The score can be negative when slow, low-scoring paths dominate the filtered set."
                ]),
                .warning("Process Goodness is a relative indicator, not an absolute benchmark. Use it to spot trends over time, compare segments in A/B mode, or monitor the impact of process changes — not as a standalone pass/fail threshold.")
            ])
        ]
    )

    // MARK: Process Similarity

    static let processSimilarity = HelpTopic(
        id: "processsimilarity", title: "Process Similarity", subtitle: "How Q(T₁, T₂) compares two filtered processes",
        icon: "arrow.triangle.2.circlepath", color: .indigo,
        sections: [
            HelpSection(heading: "What it measures", body: [
                .paragraph("Process Similarity Q(T₁, T₂) is a single number between 0 and 1 that answers the question: how behaviourally alike are the two process views loaded in A-Chart and B-Chart?"),
                .paragraph("A score of 1.0 means the two processes are identical — every variant is explained equally well by both graphs and the same scored steps are visited in the same proportion. A score of 0.0 means the two processes share almost nothing. Values in between indicate partial overlap."),
                .paragraph("Unlike Process Goodness, which measures how good a single process is, Process Similarity is a comparison metric. Use it to confirm that two filter segments really are behaving differently, or to verify that a process change has had a measurable effect."),
                .tip("Process Similarity only appears in A/B Comparison mode. It is displayed as a floating horizontal badge between the two panels, just below the date range slider group. The score is refreshed automatically whenever you apply filters or move a date slider in either panel.")
            ]),

            HelpSection(heading: "The formula", body: [
                .paragraph("Q is a weighted average of three components, each between 0 and 1:"),
                .code("""
Q(T₁, T₂) = 0.4 · Q_var  +  0.4 · Q_nodes  +  0.2 · Q_cov
"""),
                .definition(term: "Q_var  (weight 40 %)",
                    detail: "Variant alignment agreement. Measures how consistently both graphs explain the same journey variants. If both graphs handle a variant equally (both replay it perfectly, or both fail equally), Q_var is high. If one graph handles a variant much better than the other, Q_var is low."),
                .definition(term: "Q_nodes  (weight 40 %)",
                    detail: "Node agreement weighted by importance. A Jaccard-style ratio comparing which scored steps are actually visited — under each graph — per variant. Steps with a higher absolute score value count more. If both graphs visit the same high-value steps in the same variants, Q_nodes approaches 1."),
                .definition(term: "Q_cov  (weight 20 %)",
                    detail: "Joint coverage. The fraction of variant frequency that is explained perfectly (zero missing edges) by both graphs simultaneously. A high value means most journeys fit neatly into both process models."),
                .tip("The 40/40/20 weights reflect that structural similarity (Q_var) and scored-step agreement (Q_nodes) are equally important, while coverage is a useful but secondary signal.")
            ]),

            HelpSection(heading: "Alignment cost — the key building block", body: [
                .paragraph("For each journey variant (a specific sequence of steps), the formula computes an alignment cost for each graph:"),
                .code("""
cost_T(v) = missing_edges / total_edges_in_variant
"""),
                .paragraph("A 'missing edge' is a consecutive step pair in the variant that does not appear as a transition in the graph. If all transitions exist, cost = 0 (perfect fit). If half are missing, cost = 0.5. A variant with only one step (no edges) is skipped."),
                .paragraph("This is a practical approximation of formal process-mining alignment. It runs in linear time per variant and requires no external solver, making it fast enough to run automatically on every panel reload."),
                .tip("The variant set is capped at 500 per side (1 000 combined). When the cap is exceeded the tile is hidden rather than showing a misleading score computed from a biased sample.")
            ]),

            HelpSection(heading: "Example 1 — nearly identical segments", body: [
                .paragraph("A-Chart shows European orders; B-Chart shows North American orders. Both regions follow almost the same checkout process."),
                .code("""
Variant A  (90 % of journeys, both sides):
  Browse → Cart → Pay → Confirm
  Edges exist in both graphs → cost_A = 0,  cost_B = 0

Variant B  (10 % of journeys, EU only):
  Browse → Cart → Coupon → Pay → Confirm
  All edges in A-graph; Coupon→Pay missing in B-graph
  cost_A = 0,  cost_B = 1/4 = 0.25
"""),
                .paragraph("Q_var calculation:"),
                .code("""
Variant A: freq = 0.90  |cost_A − cost_B| = 0    max = 0
Variant B: freq = 0.10  |cost_A − cost_B| = 0.25  max = 0.25

Q_var = 1 − (0.90×0 + 0.10×0.25) / (0.90×0 + 0.10×0.25)
      = 1 − 0.025 / 0.025 = 0.00   ← penalised by denominator = numerator
"""),
                .paragraph("Wait — this gives Q_var = 0 because the only non-zero cost comes from the one variant where costs differ. In practice, when max cost equals absolute difference, Q_var = 0 for that variant. However, Variant A (90 % frequency) contributes 0/0 which is treated as 1.0 (perfect agreement). Weighting by frequency:"),
                .code("""
Weighted Q_var ≈ 0.90 × 1.0 + 0.10 × 0.0 = 0.90

Assume scored steps: Pay = +10, Confirm = +10 (both graphs)
Q_nodes ≈ 0.95  (Coupon step has no score, so its absence barely matters)
Q_cov   = 0.90  (90 % of frequency fits both perfectly)

Q = 0.4 × 0.90 + 0.4 × 0.95 + 0.2 × 0.90
  = 0.36 + 0.38 + 0.18 = 0.92  → green
"""),
                .tip("A score of 0.92 correctly reflects that EU and North America are very similar processes — only the coupon path distinguishes them.")
            ]),

            HelpSection(heading: "Example 2 — same time period, different quality paths", body: [
                .paragraph("A-Chart shows the standard process (no failures); B-Chart shows the same date range but filtered to orders that included a 'Pay Failed' step. These are structurally different populations."),
                .code("""
Variant A  (100 % of A-side): Browse → Cart → Pay → Confirm
  All edges in A-graph (cost_A = 0)
  'Pay → Confirm' missing from B-graph  (cost_B = 1/3 ≈ 0.33)

Variant B  (100 % of B-side): Browse → Cart → Pay → Pay Failed → Refund
  'Pay → Confirm' missing from A-graph  (cost_A = 1/3 ≈ 0.33)
  All edges in B-graph  (cost_B = 0)

Scored steps: Pay = +5, Confirm = +10, Pay Failed = −10, Refund = −5
"""),
                .paragraph("Variant A contributes freq = 0.5 (half of combined journeys), Variant B freq = 0.5:"),
                .code("""
Q_var:
  Var A: |0 − 0.33| = 0.33,  max = 0.33
  Var B: |0.33 − 0| = 0.33,  max = 0.33
  Q_var = 1 − (0.5×0.33 + 0.5×0.33) / (0.5×0.33 + 0.5×0.33) = 0.00

Q_nodes:
  Var A: visited under A = {Browse,Cart,Pay,Confirm} × (1−0) = full weight
         visited under B = {Browse,Cart,Pay,Confirm} × (1−0.33) = 0.67 weight
         Confirm (|s|=10): min(1,0.67)=0.67, max(1,0.67)=1 → ratio 0.67
  Var B: similar analysis for Pay Failed (|s|=10), Refund (|s|=5)
  Approximate Q_nodes ≈ 0.45

Q_cov = 0  (neither variant fits both graphs perfectly)

Q = 0.4×0.00 + 0.4×0.45 + 0.2×0.00 = 0.18  → red
"""),
                .paragraph("A score of 0.18 correctly signals strong divergence — the happy-path and failure-path populations are fundamentally different processes.")
            ]),

            HelpSection(heading: "Example 3 — before and after a process change", body: [
                .paragraph("A-Chart shows January (before a process redesign); B-Chart shows February (after). The redesign merged two slow approval steps into one. Most variants are shared but with different graph structure."),
                .code("""
Shared variant (70 %): Browse → Submit → Approve → Complete
  January graph: Submit→Approve and Approve→Complete exist  (cost_A = 0)
  February graph: same edges still exist in simplified graph (cost_B = 0)

Old variant (30 %, Jan only): Browse → Submit → Review → Approve → Complete
  cost_A = 0  (all edges in Jan graph)
  'Submit→Review' and 'Review→Approve' missing from Feb graph
  cost_B = 2/4 = 0.50

Scored steps: Approve = +8, Complete = +10
"""),
                .code("""
Q_var:
  Shared (0.70): |0−0| = 0, max = 0 → treated as perfect agreement
  Old    (0.30): |0−0.50| = 0.50, max = 0.50 → ratio = 1.0 (full penalty)
  Weighted Q_var = 0.70×1.0 + 0.30×0.0 = 0.70

Q_nodes:
  Shared variant: both graphs visit Approve and Complete perfectly → high agreement
  Old variant: Review step has no score, so its absence in Feb barely hurts Q_nodes
  Approximate Q_nodes ≈ 0.82

Q_cov:
  70 % of frequency fits both graphs perfectly
  Q_cov = 0.70

Q = 0.4×0.70 + 0.4×0.82 + 0.2×0.70
  = 0.28 + 0.33 + 0.14 = 0.75  → green
"""),
                .paragraph("A score of 0.75 reflects that the two periods are broadly similar — the core path is unchanged — but the old Review step creates a measurable divergence. The green colour signals the processes are still recognisably the same, while the value below 0.90 confirms the redesign did introduce a structural difference."),
                .tip("Use this pattern to validate process changes: a Q score that stays near 1 after a change means the redesign had little behavioural effect. A Q score that drops toward 0.5 or below confirms a meaningful structural shift in how journeys flow.")
            ]),

            HelpSection(heading: "Colour thresholds and limitations", body: [
                .bullets([
                    "Green: Q ≥ 0.70 — the two processes are behaviourally similar.",
                    "Blue: 0.30 ≤ Q < 0.70 — moderate similarity; some paths are shared, others differ.",
                    "Red: Q < 0.30 — strong divergence; the two filter segments describe fundamentally different behaviour."
                ]),
                .warning("Process Similarity is a relative indicator, not an absolute benchmark. It depends on which steps have SCORE values configured — if no steps have scores, Q_nodes defaults to 1.0 and only Q_var and Q_cov contribute. The score is also sensitive to the route limit: raising the limit to 2 500 may reveal rare variants not visible at 100, changing Q."),
                .bullets([
                    "The practical guard caps input at 500 variants per side (1 000 combined). When the cap is hit the tile is hidden.",
                    "Alignment cost is an edge-coverage approximation, not a formal Petri-net alignment. It may slightly overestimate similarity for processes with loops or repeated steps.",
                    "Q is symmetric: Q(A, B) = Q(B, A). The same value appears in both panels."
                ])
            ])
        ]
    )

    // MARK: Configuration

    static let configuration = HelpTopic(
        id: "configuration", title: "Configuration", subtitle: "Display options, step colours, shapes, scores, and groups",
        icon: "slider.horizontal.3", color: .brown,
        sections: [
            HelpSection(heading: "Display options", body: [
                .paragraph("Three display preferences sit at the top of the Configuration section and apply globally across all chart views."),
                .definition(term: "Show step groups",
                    detail: "Toggles the rounded dashed group borders on or off. When off, all BELONGS_TO grouping is hidden visually — nodes still belong to their groups, but no border or label is drawn."),
                .definition(term: "Groups start",
                    detail: "Appears directly below \"Show step groups\" when grouping is on. Controls how BELONGS_TO groups appear each time a project loads. Expanded shows every step individually. Collapsed folds each group into a single proxy node. Persisted restores the collapse state from your last session."),
                .definition(term: "Date slider",
                    detail: "Switches the date slider style on all chart views between Range mode and Day mode. See the Date range section in the Filters topic for a full explanation of each mode."),
                .definition(term: "Show node notes",
                    detail: "When enabled, a yellow ✎ badge is drawn on any node that has a process note, and a yellow dot is drawn near the midpoint of any edge that has a note. Disable to hide all note indicators for a cleaner map view."),
                .definition(term: "Optimise layout",
                    detail: "When enabled, the automatic layout algorithm applies a crossing-minimisation pass (Sugiyama phase 3 barycenter heuristic) after the initial layer assignment. Nodes within each layer are reordered so that edges cross as rarely as possible, producing cleaner and easier-to-read flow charts on complex graphs. Disable this toggle if you prefer a purely alphabetical node order within each layer, or on very simple graphs where the extra pass makes no visible difference. The setting takes effect the next time the layout is recomputed — tap the reset button (↺) to force an immediate refresh."),
                .tip("Display settings are global — they apply to all projects and all chart views simultaneously and are remembered across sessions.")
            ]),
            HelpSection(heading: "Appearance (Settings window)", body: [
                .paragraph("Additional appearance options live in the Settings window — open it with ⌘, or from the application menu. Navigate to the Appearance → Flow Chart entry in the sidebar."),
                .definition(term: "Colorize connections by weight",
                    detail: "When enabled, each transition arrow is tinted according to its value relative to the map maximum. When disabled, all arrows are drawn in the default secondary color regardless of the active metric."),
                .definition(term: "Color Scale per Metric",
                    detail: "Visible when colorization is on. Each of the five Transition Metrics (Count, Avg Time, Min Time, Max Time, Std Dev) has its own color scale picker. Six scales are available: None (grey), Green (high is good), Red (low is good), Blue scale, Orange scale, and Purple scale. A gradient preview swatch shows the chosen scale next to each picker. The active metric's scale is reflected live in the map and in the corner indicator."),
                .definition(term: "Reset to Defaults",
                    detail: "Clears all per-metric color scale overrides and restores the built-in defaults: Count → green, Avg Time → orange, Min Time → blue, Max Time → red, Std Dev → purple.")
            ]),
            HelpSection(heading: "KPIs", body: [
                .paragraph("The KPIs subsection in Configuration lets you show or hide each individual KPI tile across all views simultaneously. Toggle any KPI off to remove its tile from the single-chart panel, the A/B comparison panels, and the Statistics view — the setting applies globally and is remembered across sessions."),
                .bullets([
                    "Total Journeys — unfiltered journey count for the project.",
                    "Filtered Journeys — journey count matching the current filter set.",
                    "Shortest / Avg / Std Dev / Longest Journey — duration statistics for filtered journeys.",
                    "Graph Value — sum of (step score × visit count) across the visible map.",
                    "Process Goodness — composite quality score. See the Process Goodness chapter.",
                    "Process Similarity — behavioural similarity between A and B in A/B Comparison mode. See the Process Similarity chapter."
                ]),
                .tip("All KPI toggles default to on. Hiding tiles you do not use keeps the panel compact on smaller screens.")
            ]),
            HelpSection(heading: "Step Editor", body: [
                .paragraph("Found in the Configuration section at the bottom of the sidebar. The Step Editor lets you customise how each process step is displayed across all chart views."),
                .tip("Changes apply immediately after tapping Save and are persisted to the STEPS table in the database.")
            ]),
            HelpSection(heading: "Selecting a step", body: [
                .paragraph("Tap the step picker at the top of the Step Editor to choose which step you want to edit. The list shows all steps found in the project's JOURNEYS table.")
            ]),
            HelpSection(heading: "Colours", body: [
                .bullets([
                    "Background colour — the fill colour of the node on the map.",
                    "Foreground colour — the text colour inside the node.",
                    "A live preview chip shows both colours together before you save."
                ])
            ]),
            HelpSection(heading: "Score", body: [
                .paragraph("An optional integer value between −999 and 999 assigned to a step. Scores are displayed as a small badge on each node and are summed in the Individual Journey KPI panel."),
                .paragraph("Enable the toggle to activate a score for the step, then use the text field or +/− stepper to set the value.")
            ]),
            HelpSection(heading: "Shape", body: [
                .paragraph("Choose one of four node shapes:"),
                .bullets([
                    "Stadium — rounded pill shape (default).",
                    "Round corners — rectangle with rounded corners.",
                    "Hexagon — six-sided shape.",
                    "Circle — elliptical shape."
                ])
            ]),
            HelpSection(heading: "Group (Belongs To)", body: [
                .paragraph("An optional free-text field that maps a step to a logical group or subprocess. The value is stored in the BELONGS_TO column of the STEPS table."),
                .paragraph("On the process map, all steps sharing the same group value are enclosed by a rounded dashed border. The group name is displayed as a colored pill badge on the top edge of that border. Each distinct group name receives a unique, consistent color.")
            ]),
            HelpSection(heading: "Node descriptions", body: [
                .paragraph("Each step in the STEPS table has an optional DESCRIPTION column. When a description is set and differs from the step name, the node is split into two zones: the step name on the upper portion and a shortened description (up to 20 characters) on the lower portion."),
                .paragraph("To add or update a description, open the Step Editor, select a step, type in the Note field at the bottom of the editor, and tap Save."),
                .definition(term: "Show description", detail: "Tap any node on the map to open its context menu. If that node has a description, a 'Show description' button appears — tap it to display the full description text in an overlay card on the map."),
                .tip("Leave the Note field empty in the Step Editor to clear a description. Nodes without a description display only the step name, using the full node height.")
            ])
        ]
    )

    // MARK: Getting Exasol

    static let gettingExasol = HelpTopic(
        id: "gettingexasol", title: "Getting Exasol", subtitle: "Cloud, personal, community, and Docker",
        icon: "arrow.down.circle.fill", color: .blue,
        sections: [
            HelpSection(heading: "Before you connect", body: [
                .paragraph("Process Mining Demonstrator requires an Exasol database. If you do not have one yet, you have four options — from a fully managed cloud service to a Docker container that starts in seconds on your own machine.")
            ]),

            HelpSection(heading: "Exasol Cloud", body: [
                .paragraph("Exasol Cloud is a fully managed, serverless database-as-a-service. No installation or server administration is required — Exasol handles capacity, backups, and upgrades automatically."),
                .bullets([
                    "Sign up for a free trial at exasol.com and create a new database cluster.",
                    "Once provisioned, open the Exasol Cloud Console to find your connection host (e.g. your-instance.cloud.exasol.com), port (8563), and your initial credentials.",
                    "In Process Mining Demonstrator, enable Use TLS / SSL and set Certificate to Verify (system trust) — cloud instances use CA-signed certificates."
                ]),
                .tip("Exasol Cloud is the fastest way to get started. The free trial includes enough compute and storage to load a real dataset and explore Process Mining Demonstrator end-to-end.")
            ]),

            HelpSection(heading: "Exasol Personal", body: [
                .paragraph("Exasol Personal is a free, single-node instance intended for personal learning and development. It is limited to 10 GB of working memory and is not for production use."),
                .bullets([
                    "Download the VirtualBox or VMware appliance from the Exasol website (exasol.com → Downloads).",
                    "Import the appliance and start the VM. The VM's assigned IP address is displayed in the console after boot.",
                    "In Process Mining Demonstrator: Host = VM's IP address, Port = 8563, Username = sys, Password = exasol.",
                    "Leave Use TLS / SSL disabled — TLS is not active on a default local VM."
                ]),
                .warning("The default password is exasol. Change it immediately with: ALTER USER sys IDENTIFIED BY '<new password>';")
            ]),

            HelpSection(heading: "Exasol Community Edition", body: [
                .paragraph("The Community Edition is free for non-commercial use and provides the complete Exasol feature set within a defined data volume limit. It is a good choice for a persistent local instance shared by a small team."),
                .bullets([
                    "Download the installer or VM image from the Exasol website and follow the setup wizard.",
                    "The Community Edition deploys as a single-node cluster with the same default settings as Personal Edition.",
                    "Connection details: Host = instance IP, Port = 8563, Username = sys, Password = exasol."
                ]),
                .tip("Community Edition supports the same SQL and WebSocket API as cloud deployments, so anything you build locally migrates cleanly to Exasol Cloud later.")
            ]),

            HelpSection(heading: "Docker Image", body: [
                .paragraph("Exasol publishes an official Docker image (exasol/docker-db) that starts a fully functional single-node instance without any VM setup."),
                .code("docker run --name exasoldb -p 8563:8563 --privileged -d exasol/docker-db:latest"),
                .bullets([
                    "Docker Desktop must have at least 4 GB of RAM allocated to the Docker engine.",
                    "Wait about 2–3 minutes after the container starts before connecting — Exasol completes an internal cluster initialisation on first boot.",
                    "In Process Mining Demonstrator: Host = 127.0.0.1, Port = 8563, Username = sys, Password = exasol.",
                    "Leave Use TLS / SSL disabled."
                ]),
                .tip("To keep your data across container restarts, add a named volume: add -v exasol-data:/exa to the docker run command."),
                .warning("The default password is exasol. Change it before storing any non-trivial data.")
            ]),

            HelpSection(heading: "Common local connection settings", body: [
                .paragraph("All local options (VM or Docker) use the same defaults in Process Mining Demonstrator:"),
                .definition(term: "Host",     detail: "127.0.0.1, or the VM's IP address shown in its console."),
                .definition(term: "Port",     detail: "8563 — Exasol's default WebSocket port."),
                .definition(term: "Username", detail: "sys"),
                .definition(term: "Password", detail: "exasol (the default — change it after first login)."),
                .definition(term: "Schema",   detail: "Optional. Enter your schema name to avoid fully qualifying every table."),
                .definition(term: "TLS",      detail: "Off for local instances. On (Verify) for Exasol Cloud."),
                .tip("After connecting, use the Demo Data section in Process Mining Demonstrator to generate a sample bookstore dataset — no SQL required — so you can explore all views immediately.")
            ])
        ]
    )

    // MARK: Conformance Check

    static let complianceCheck = HelpTopic(
        id: "compliancecheck", title: "Conformance Check", subtitle: "Compare actual process against target norms",
        icon: "checkmark.shield.fill", color: .green,
        sections: [
            HelpSection(heading: "What is Conformance Check?", body: [
                .paragraph("Conformance Check places the actual process map (left panel) side-by-side with the Target Process (right panel). Edges on the actual map are colour-coded to show whether each transition's measured value is within or above its defined norm."),
                .paragraph("Both panels always display the same filtered slice of data. Changing filters and tapping Apply reloads both sides simultaneously.")
            ]),
            HelpSection(heading: "Opening Conformance Check", body: [
                .paragraph("Tap the ≡ icon in the top-right corner and select Conformance Check. Both panels load using the current filter settings."),
                .paragraph("The toolbar at the top of the view contains three controls: the filter preset menu (bookmark icon), the Edit / Execution mode picker, and the Gap Table chip. Below the toolbar, three collapsible cards let you configure the view without cluttering the chart area: Conformance KPIs, Date & Metrics, and the side-by-side chart panels.")
            ]),
            HelpSection(heading: "Edit and Execution modes", body: [
                .paragraph("A segmented control in the header bar switches between two modes:"),
                .definition(term: "Edit mode",      detail: "The right panel (Target Process) is interactive — tap any edge to open the norm editor and update norm values directly from this view without leaving Conformance Check."),
                .definition(term: "Execution mode", detail: "Both panels are read-only. The actual process map on the left applies compliance colouring to every edge, making violations immediately visible."),
                .tip("Switch to Execution mode to focus on identifying violations without accidentally editing norms.")
            ]),
            HelpSection(heading: "Conformance KPIs panel", body: [
                .paragraph("Tap the 'Conformance KPIs' row (chevron on the left) to expand or collapse the KPI tile strip. When expanded, it shows:"),
                .definition(term: "Conformance %", detail: "The percentage of normed transitions whose actual value is within target. Only shown when at least one norm is defined. What counts as 'within target' depends on the Norm is setting in the Date & Metrics panel."),
                .definition(term: "Violations",    detail: "The number of transitions that breach their norm. With 'Max ≤' norms a violation means the actual value exceeds the ceiling; with 'Min ≥' norms it means the actual value falls below the floor. Displayed in red when greater than zero."),
                .definition(term: "Compliant",     detail: "The number of normed transitions that satisfy their target. Displayed in green when greater than zero."),
                .definition(term: "No Norm",       detail: "The number of transitions that have no norm defined for the current metric."),
                .tip("Collapse the KPI strip once you have noted the headline numbers to give the chart panels more vertical space.")
            ]),
            HelpSection(heading: "Date & Metrics panel", body: [
                .paragraph("Tap the 'Date & Metrics' row (chevron on the left) to expand or collapse the combined date range, metric selector, and norm direction panel."),
                .paragraph("When expanded it shows three controls:"),
                .definition(term: "Date range slider", detail: "Drag the thumbs or use the date pickers to narrow the data to a specific period. Releasing a thumb immediately reloads both process maps with the new date boundaries."),
                .definition(term: "Metric chips",      detail: "A row of chips — Count %, Avg Duration, Max Duration, Min Duration, and Std Dev — that selects which metric's values are displayed on the edges and which norm set is active for compliance colouring. The currently selected chip is highlighted in the accent colour."),
                .definition(term: "Norm is: Max ≤ / Min ≥", detail: "Controls how norm values are interpreted. 'Max ≤' (default) treats each norm as a ceiling — a transition is compliant when its actual value is at or below the norm and is a violation when it exceeds it. 'Min ≥' treats each norm as a floor — a transition is compliant when its actual value meets or exceeds the norm and is a violation when it falls short. Switch to 'Min ≥' for metrics where a higher value is better, such as a minimum required completion rate or a minimum acceptable throughput percentage."),
                .tip("The 'Count %' metric treats norms as percentages of outgoing journeys from the same source node. All other metrics compare against absolute values. Collapse the panel after selecting your metric to maximise chart space."),
                .tip("The filter preset bookmark in the header updates the date range slider automatically when a preset is applied, keeping the slider in sync with the loaded data.")
            ]),
            HelpSection(heading: "Metric-specific norms", body: [
                .paragraph("Every metric has its own independent set of norm values. Selecting a different metric chip in the Date & Metrics panel switches both the displayed edge values and the norms being compared — norms entered for Count % are completely separate from norms entered for Avg Duration, Max Duration, and so on."),
                .paragraph("This means you can define, for example, a Count % norm of 60 % and an Avg Duration norm of 120 s on the same transition, and switch between them without either value affecting the other."),
                .tip("Define norms for whichever metrics matter most to your process targets. The AI Supported Documentation view will include a gap analysis table for every metric that has at least one norm defined.")
            ]),
            HelpSection(heading: "Compliance colouring", body: [
                .paragraph("When a norm is defined for a transition under the currently selected metric, its edge on the actual process map is coloured to indicate compliance. The direction of the comparison is controlled by the 'Norm is' toggle in the Date & Metrics panel:"),
                .definition(term: "Green edge", detail: "The transition is compliant. With 'Max ≤' norms this means the measured value is at or below the ceiling; with 'Min ≥' norms it means the measured value meets or exceeds the floor."),
                .definition(term: "Red edge",   detail: "The transition is in violation. With 'Max ≤' norms the measured value exceeds the ceiling; with 'Min ≥' norms it falls short of the floor."),
                .definition(term: "Grey edge",  detail: "No norm has been defined for this transition under the current metric. The edge is displayed in the default neutral style."),
                .tip("Tap a different metric chip in the Date & Metrics panel to instantly see compliance colouring for a different dimension. Each metric's norm set is stored independently.")
            ]),
            HelpSection(heading: "Synchronized navigation", body: [
                .paragraph("Both panels share a single viewport. Panning, zooming, or dragging a node in either panel immediately updates the other, so both maps stay visually aligned at all times.")
            ]),
            HelpSection(heading: "Gap Analysis table", body: [
                .paragraph("Tap the Gap Table chip in the header bar to reveal a sortable comparison table below the charts. The table lists every transition that has a norm defined and shows:"),
                .definition(term: "From → To", detail: "The source and destination steps of the transition."),
                .definition(term: "Actual",    detail: "The measured value for the active metric (e.g. average time in seconds, or outgoing journey percentage for Count %)."),
                .definition(term: "Norm",      detail: "The target norm value defined for this transition."),
                .definition(term: "Δ Delta",   detail: "The difference between the actual value and the norm (actual − norm). A positive delta means the actual exceeds the norm; a negative delta means it falls below. Which sign represents a violation depends on the 'Norm is' toggle: for 'Max ≤' norms, a positive delta is a violation; for 'Min ≥' norms, a negative delta is a violation."),
                .paragraph("Rows are sorted with violations first (worst offenders at the top, based on the active norm direction), followed by compliant transitions."),
                .tip("Use the Gap Analysis table to prioritise the transitions that deviate most from their targets and focus improvement efforts accordingly.")
            ])
        ]
    )

    // MARK: Happy Path

    static let happyPath = HelpTopic(
        id: "happypath", title: "Happy Path", subtitle: "Define ideal step sequences and measure real conformance",
        icon: "signpost.right.fill", color: .orange,
        sections: [
            HelpSection(heading: "What is a Happy Path?", body: [
                .paragraph("A Happy Path is your definition of how a process should ideally run — an ordered sequence of steps that represents the best-case or target flow. The Happy Path view places the actual process map (left panel) side-by-side with your defined step sequence (right panel) and calculates a Conformance score between 0.0 and 1.0 that tells you how closely real journeys follow the ideal route."),
                .paragraph("Unlike Conformance Check — which compares measured transition values against numeric norms — Happy Path measures structural alignment: do journeys actually traverse the transitions that the ideal sequence defines?"),
                .paragraph("A happy path can be a single linear sequence, or it can split into two or more branches at a point where the ideal process legitimately diverges — for example, domestic vs. international check-in, or standard vs. express fulfilment. A single Conformance score is still produced, reflecting how well real journeys match whichever branch is most appropriate for them."),
                .tip("Use Happy Path when you want to answer 'What fraction of journeys follow the process we designed?' rather than 'Are individual transitions within their performance targets?'")
            ]),
            HelpSection(heading: "Opening Happy Path", body: [
                .paragraph("Tap the ≡ icon in the top-right corner and select Happy Path. Both panels load using the current sidebar filter settings. The left panel shows the actual process map; the right panel shows the selected happy path's step list.")
            ]),
            HelpSection(heading: "Multiple named paths", body: [
                .paragraph("Each project can have any number of named happy paths. Use the path selector in the top bar — it sits directly to the left of the Conformance badge — to switch between paths or create new ones."),
                .paragraph("The selector menu offers:"),
                .bullets([
                    "A list of all existing paths for the project. The currently active path is marked with a checkmark.",
                    "New Happy Path… — creates a new path and selects it immediately.",
                    "Rename… — changes the name of the currently selected path.",
                    "Delete — permanently removes the selected path (with immediate effect, no undo)."
                ]),
                .tip("Happy path definitions are stored on-device (in UserDefaults) per project. They are included in Backup & Restore exports and survive app re-installs when a backup is restored.")
            ]),
            HelpSection(heading: "Building a linear path", body: [
                .paragraph("Tap Edit Path in the top-right of the bar to switch the right panel to edit mode. In edit mode:"),
                .bullets([
                    "Tap the + button in the panel header to open the Add Step sheet. Search for a step by name and tap it to append it to the end of the trunk sequence.",
                    "Drag the three-line handle on any row to reorder steps.",
                    "Swipe a row left and tap Delete to remove a step from the sequence.",
                    "Tap Done when you are finished editing."
                ]),
                .paragraph("The same step cannot appear more than once anywhere in a path (trunk or any branch) — the Add Step sheet automatically filters out steps already present."),
                .tip("A path needs at least two steps to produce a Conformance score. Single-step paths have no transitions and will show no score.")
            ]),
            HelpSection(heading: "Adding branches to a path", body: [
                .paragraph("A branch represents an alternative continuation of the process after a shared trunk. The trunk is the common sequence of steps that all journeys follow before the process splits. Each branch then describes one valid route from that split point onward."),
                .paragraph("To add a branch:"),
                .bullets([
                    "Enter Edit mode and scroll to the bottom of the editor.",
                    "Tap 'Add Branch'. A new empty branch section appears below the trunk.",
                    "Tap the + icon in the branch section header to add steps to that branch.",
                    "Tap the ✏ (pencil) icon to give the branch a descriptive label, such as 'Domestic' or 'Express'.",
                    "Tap the 🗑 (trash) icon to delete a branch entirely.",
                    "To reorder or remove individual steps within a branch, use drag handles and swipe-to-delete just as in the trunk."
                ]),
                .paragraph("In view mode, the trunk is shown as a vertical flow. The last trunk step is marked with a (+) badge to signal the split point. Below it, each branch is displayed as a separate column of steps, labelled with its name. A branch divider line with a branch icon separates the trunk from the columns."),
                .tip("Leave a branch label empty if you do not need a name — it will display as 'Branch 1', 'Branch 2', etc. You can rename it at any time without affecting the conformance score.")
            ]),
            HelpSection(heading: "Two approaches to multi-route processes", body: [
                .paragraph("There are two ways to model a process where different journeys take legitimately different routes:"),
                .definition(term: "Multiple separate happy paths",
                    detail: "Create one happy path per route variant — for example 'Domestic Flow' and 'International Flow' as two independent paths. Analyse them separately and compare their individual Conformance scores. This is best when the two routes are largely distinct and you want to track them independently."),
                .definition(term: "A single branching happy path",
                    detail: "Define a shared trunk (the common steps) and then add branches for each diverging continuation within the same path. The Conformance badge shows one combined score that reflects how well real journeys match whichever branch is most appropriate for them. This is best when the routes share a meaningful common prefix and you want a single top-level conformance metric."),
                .tip("Both variants are supported simultaneously. You might use separate paths for high-level reporting and a branching path for drill-down analysis of a specific segment within the same project.")
            ]),
            HelpSection(heading: "Reading the right panel (view mode)", body: [
                .paragraph("When Edit mode is off, the right panel shows the defined steps as a visual flow diagram. Each step box is colour-coded:"),
                .definition(term: "Green box",  detail: "This step appears in the actual process graph (observed in the loaded data under the current filters). A small green percentage below the step name shows its step coverage — the proportion of current journeys that pass through this step, estimated from the transition occurrence counts."),
                .definition(term: "Grey box",   detail: "This step is not present in the current process graph — it was never observed, or was filtered out. No coverage percentage is shown."),
                .paragraph("For branching paths, the trunk is shown top to bottom, and each branch appears as a vertical column below the trunk split point. Branches are displayed side by side with equal width. Coverage percentages are shown for branch steps in exactly the same way as trunk steps."),
                .paragraph("Grey steps still contribute to the conformance calculation: a journey that skips a grey step loses conformance credit for the transition involving that step."),
                .tip("Coverage and Conformance answer different questions. Coverage tells you how many journeys visit a step at all. Conformance tells you how many journeys follow the full sequence of transitions you defined. A step can have 90 % coverage but still contribute to a low Conformance score if journeys arrive at it via a different predecessor."),
                .tip("Reapply filters or change the date range to see how coverage, conformance, and step visibility change across different data slices.")
            ]),
            HelpSection(heading: "The Conformance score — linear path", body: [
                .paragraph("For a linear (non-branching) path, the Conformance badge shows a score H between 0.0 and 1.0, calculated as a journey-count-weighted average of per-variant edge coverage."),
                .paragraph("For each distinct journey variant (a unique step sequence observed in the data), Process Mining Demonstrator:"),
                .bullets([
                    "Extracts the variant's edges — every consecutive step pair (A→B) in that variant's path.",
                    "Computes coverage: how many of the happy path's edges appear in the variant's edge set.",
                    "Weights that coverage by the number of journeys that follow the variant."
                ]),
                .code("""
H = Σ ( n_v × coverage_v ) / Σ n_v

Where:
  n_v          = number of journeys following variant v
  coverage_v   = |E_happy ∩ E_v| / |E_happy|
  E_happy      = set of consecutive step pairs (A→B) in the happy path
  E_v          = set of consecutive step pairs (A→B) in variant v
"""),
                .paragraph("In plain language: for each real journey Process Mining Demonstrator asks 'what fraction of the transitions I defined as ideal does this journey actually contain?' It then averages those fractions weighted by how many journeys are in each variant group."),
                .definition(term: "Score = 1.0", detail: "Every journey contains all transitions defined in the happy path. Perfect conformance."),
                .definition(term: "Score = 0.0", detail: "No journey shares a single transition with the happy path. Complete divergence."),
                .definition(term: "Score = 0.65", detail: "On average, journeys traverse 65 % of the defined transitions, weighted by journey count."),
                .tip("The score measures transition coverage, not step coverage. A journey that visits every step in the happy path but in a different order will score lower than one that follows the exact sequence, because the transitions (A→B pairs) will not match."),
                .warning("The Conformance score is computed from up to 500 journey variants. For very large datasets with more than 500 distinct routes, less-common variants are excluded. In practice this affects the score only marginally because rare variants represent a small share of total journey count.")
            ]),
            HelpSection(heading: "The Conformance score — branching path", body: [
                .paragraph("When branches are defined, the scoring is extended: each branch is combined with the trunk to form a complete path (trunk steps + branch steps), and every journey is scored against all complete paths. The journey's score is the best match — the highest coverage across all branches — reflecting that a journey should be judged against the branch it was meant to follow."),
                .code("""
For a path with k branches:

  E_b       = edges of trunk + edges of branch b   (b = 1 … k)
  E_v       = edges of journey variant v

  best_b(v) = max over b=1..k of  |E_b ∩ E_v| / |E_b|

  H = Σ ( n_v × best_b(v) ) / Σ n_v
"""),
                .paragraph("In plain language: each journey is matched against every defined branch. The branch it fits best determines its contribution to the overall score. A journey that perfectly follows any one branch receives full credit; a journey that fits no branch receives proportional partial credit."),
                .definition(term: "All branches empty", detail: "If no branch has been given any steps yet, scoring falls back to trunk-only mode (same as a linear path). This ensures a meaningful score is always shown as soon as the trunk has two or more steps."),
                .tip("A journey that traverses both the trunk and the correct branch will score close to 1.0 even if the other branches are entirely different, because it is always compared to its best-matching branch."),
                .warning("Branches with zero steps are excluded from scoring. Add at least one step to each branch to have it considered in the conformance calculation.")
            ]),
            HelpSection(heading: "Conformance score colour coding", body: [
                .definition(term: "Green  (≥ 0.70)", detail: "High conformance — the majority of journeys closely follow the happy path."),
                .definition(term: "Orange (0.30 – 0.69)", detail: "Moderate conformance — many journeys diverge from the ideal sequence."),
                .definition(term: "Red    (≤ 0.30)", detail: "Low conformance — most journeys deviate significantly from the happy path.")
            ]),
            HelpSection(heading: "Left panel — actual process map", body: [
                .paragraph("The left panel shows the full FlowChartView for the current project and filters, identical to the A-Chart view. All the usual interactions are available:"),
                .bullets([
                    "Tap any node to include/exclude it from filters or add a note.",
                    "Tap any edge to view its details or add a note.",
                    "Pinch to zoom, drag to pan, drag nodes to reposition them.",
                    "The metric selector chips in the top bar drive the edge labels and thickness in this panel."
                ]),
                .tip("Applying a filter (include step, exclude step) via the node context menu in this panel reloads the graph and recalculates the Conformance score automatically.")
            ]),
            HelpSection(heading: "When does the score refresh?", body: [
                .paragraph("The Conformance score is recalculated automatically whenever:"),
                .bullets([
                    "The Happy Path view is first displayed.",
                    "You switch to a different happy path from the selector.",
                    "You add, remove, reorder, or rename steps or branches in the path.",
                    "Any sidebar filter is applied (via the Apply button).",
                    "A step is included or excluded via the node context menu on the actual process map."
                ])
            ])
        ]
    )

    // MARK: AI Documentation

    static let aiDocumentation = HelpTopic(
        id: "aidocumentation", title: "AI Documentation", subtitle: "AI-powered process analysis and insights",
        icon: "brain", color: .purple,
        sections: [
            HelpSection(heading: "What is AI Documentation?", body: [
                .paragraph("AI Documentation sends a structured description of your process data — transitions, frequencies, durations, and filter context — to a language model and renders the response as a formatted document inside the app."),
                .paragraph("The result is a multi-chapter document that combines AI-generated analysis with directly computed sections for Journey Paths, Happy Path conformance, and Conformance Check results. The exact AI output depends on the prompt template you configure and the model in use."),
                .warning("AI models can produce results that are incorrect, incomplete, or misleading. Always verify AI findings independently before acting on them.")
            ]),
            HelpSection(heading: "Prerequisites — LLM server", body: [
                .paragraph("AI Documentation requires a running language model server accessible from your device. Open Settings (⌘,), select the LLM section, and add a server with three fields:"),
                .definition(term: "Server URL", detail: "Base URL of an OpenAI-compatible API endpoint, e.g. http://localhost:1234/v1 for LM Studio or http://your-server:11434/v1 for Ollama."),
                .definition(term: "API Key",    detail: "Bearer token sent in the Authorization header. Leave blank for local servers that do not require authentication."),
                .definition(term: "Model",      detail: "Model identifier passed in the request body, e.g. qwen3-coder:30B. Must match a model loaded on your server."),
                .paragraph("Then edit the connection in the sidebar and select this LLM server in its LLM Server picker. The connection's second status dot turns blue when the model server is reachable."),
                .tip("Tap 'Test' in the LLM server editor to verify the server before running an analysis. 'Server reachable' confirms connectivity; a red message means the URL is empty or invalid, or the server is unreachable."),
                .tip("LLM servers are reusable: define a model server once and select it from any connection. Each connection can point to a different model server.")
            ]),
            HelpSection(heading: "Opening the view", body: [
                .paragraph("Tap the ≡ icon in the top-right corner of the main area to open the view picker and select 'AI supported Documentation'. The view is only available when a database connection is active and a project has been selected.")
            ]),
            HelpSection(heading: "Running an analysis", body: [
                .paragraph("When no analysis has been run yet, the view shows a brain icon and a filter context card that summarises the A-Chart filters currently in effect — date range, step selection, meta filters, and journey count. This is the data that will be sent to the model."),
                .paragraph("Tap 'AI based Analysis' to start. A spinner replaces the content area while the model is processing; the A-Chart filter summary is shown below the spinner so you always know what is being analysed."),
                .paragraph("If the analysis fails, an error message is shown with a 'Try Again' button. The most common causes are an unreachable server, an incorrect model name, or a network timeout."),
                .tip("The 'AI based Analysis' and 'Re-run' buttons are disabled when the LLM server is not reachable. Check the connection's LLM status dot, or test the LLM server in Settings, if the buttons remain greyed out.")
            ]),
            HelpSection(heading: "Document structure", body: [
                .paragraph("When a result is available, the document is structured as a series of numbered chapters. The first two are always present; the remaining ones appear only when the corresponding data exists:"),
                .definition(term: "1. AI Analysis",          detail: "The model's narrative response — summary, transition analysis, outlier identification, and any other insight the prompt requested."),
                .definition(term: "2. Journey Paths",        detail: "A table of the most common journey paths, each showing journey count, average step count, score per journey, and aggregated score. Loaded fresh from the database using the current A-Chart filters."),
                .definition(term: "3. Happy Path Conformance", detail: "Appears when at least one Happy Path with two or more steps has been defined. Shows a conformance score (0.00–1.00) per path — computed directly, not by the model."),
                .definition(term: "4. Conformance Check",   detail: "Appears when target norms have been defined in the Compliance Check view. Lists every transition that exceeds its norm (actual vs. target vs. delta), computed directly from the live data."),
                .definition(term: "5. User Comments",        detail: "Appears when process notes exist for the project. A table of all visible notes with element, type, author, text, and date."),
                .definition(term: "N. Analysis Parameters",  detail: "Always the final chapter. Shows the model name and the exact prompt template used — so the analysis can be reproduced precisely."),
                .tip("Happy Path and Conformance sections are computed directly from your data rather than generated by the AI. This makes them deterministic and free from model hallucinations.")
            ]),
            HelpSection(heading: "Reading the result", body: [
                .paragraph("A context bar at the top of the view shows the A-Chart filter summary and a 'Re-run' button. The document is rendered below with all chapters visible as a continuous scrollable view."),
                .paragraph("Tap 'Re-run' to send the current A-Chart data to the model again. This is useful after changing filters in A-Chart or after editing the prompt template. All directly computed sections (Journey Paths, Happy Path, Conformance) are also recalculated on every re-run."),
                .tip("Each analysis result is tied to the filter state that was active when it was generated. The context bar always shows which filters were used, so you can tell at a glance whether the result is current.")
            ]),
            HelpSection(heading: "Customising the prompt", body: [
                .paragraph("The prompt template is the instruction sent to the model together with the transitions data. Process Mining Demonstrator prepends the project name and the full transitions dataset automatically — you only write the analysis instruction. Journey Paths, Happy Path, and Conformance results are appended to the document after the model responds, not included in the prompt."),
                .paragraph("To edit the prompt, scroll to the Configuration section in the sidebar and tap 'Edit' next to 'LLM Prompt'. The Prompt Editor sheet opens with the current template pre-filled."),
                .definition(term: "Save",             detail: "Saves the edited template for the current project and closes the sheet. Prompt templates are per-project — changing the prompt for one project does not affect others."),
                .definition(term: "Reset to Default", detail: "Replaces the current template with the built-in default. This change is not saved until you tap Save."),
                .tip("The prompt is stored in the app's local storage, not in the database, so it is not shared with other users. You can write multi-line prompts — the editor expands to fit the content."),
                .tip("Experiment with specific instructions: ask the model to focus on bottlenecks, compare specific transitions, suggest process improvements, or output a structured executive summary. The more specific your prompt, the more actionable the response.")
            ]),
            HelpSection(heading: "Exporting the analysis", body: [
                .paragraph("When an analysis result is available, a share button (↑) appears in the top-right toolbar. Tap it to generate a PDF and open the system share sheet."),
                .paragraph("The exported PDF is a fully structured A4 document:"),
                .bullets([
                    "Title page — project name, 'AI-Supported Process Documentation' subtitle, filter period, and generation date.",
                    "Numbered table of contents — lists all chapters present in that analysis run, with the page number where each chapter begins.",
                    "Numbered chapters — each chapter starts on a new page. Chapter headings match the table of contents.",
                    "Page numbers — printed at the bottom centre of every page.",
                    "Long tables — column headers repeat at the top of each continuation page; rows are never split across a page boundary."
                ]),
                .tip("The PDF structure is built from exactly the data visible on screen. If Journey Paths, Happy Path, or Conformance sections are not shown in the app view, they will not appear in the PDF either."),
                .tip("AI Documentation is the only chart mode that includes full analysis metadata in its export. Use this when sharing results with colleagues who may want to verify or re-run the analysis.")
            ]),
            HelpSection(heading: "Filters and the sidebar", body: [
                .paragraph("While AI Documentation is the active view, the Filters section of the sidebar shows an info notice explaining that filters cannot be changed directly from there. This is because the analysis always uses the A-Chart filter state — the same date range, step selections, and meta filters that are currently set for A-Chart."),
                .paragraph("To analyse a different slice of data: switch back to A-Chart, adjust your filters and tap Apply, then switch to AI Documentation and tap 'AI based Analysis' or 'Re-run'."),
                .tip("Each analysis result is tied to the filter state that was active when it was generated. The context bar at the top of the result always shows which filters were used, so you can tell at a glance whether the result is current.")
            ])
        ]
    )

    // MARK: Process Notes

    static let processNotes = HelpTopic(
        id: "processnotes", title: "Process Notes", subtitle: "Annotate nodes and edges with sticky notes",
        icon: "note.text", color: .yellow,
        sections: [
            HelpSection(heading: "What are process notes?", body: [
                .paragraph("Process notes let you attach free-text annotations to any node or edge in the process map. Notes are stored in the NOTES table of the connected Exasol database — not on the device — so they persist across devices and app reinstalls."),
                .paragraph("Each note is attributed to the username of the database connection that created it. Every note also records the complete filter state active at creation time — date range, step filters, meta values, and score range — so you can always trace the exact data slice the observation refers to."),
                .paragraph("Notes can be private (visible only to you) or shared (visible to all users connected to the same database). You control this with the 'Share with all users' toggle in the note editor.")
            ]),
            HelpSection(heading: "Opening notes on a node", body: [
                .paragraph("Tap any node on the process map to open its context menu, then tap Show Notes (highlighted in yellow). What happens next depends on how many notes already exist for that node:"),
                .bullets([
                    "No notes yet — the note editor opens immediately so you can write the first note.",
                    "One note — the editor opens directly for that note.",
                    "Two or more notes — a note list sheet appears showing all notes for the node."
                ]),
                .paragraph("The note editor shows the author username, target name, the filter snapshot active at creation time, a text area, and a 'Share with all users' toggle (off by default). Tap Save to store the note. A small yellow ✎ badge appears in the top-right corner of the node immediately."),
                .tip("The ✎ badge only appears when the 'Show node notes' toggle is enabled in the Configuration section of the sidebar. The badge lights up whenever any user has a note on that node — whether private or shared.")
            ]),
            HelpSection(heading: "Opening notes on an edge", body: [
                .paragraph("Tap any transition arrow on the map to open its action card, then tap Show Notes. The same routing applies: no note opens a new editor, one note opens the editor directly, two or more notes open the note list sheet."),
                .paragraph("Once the first note is saved, a small yellow dot appears near the midpoint of the edge.")
            ]),
            HelpSection(heading: "Shared and private notes", body: [
                .paragraph("Every note has a visibility setting controlled by the 'Share with all users' toggle in the note editor:"),
                .bullets([
                    "Private (default) — only you can see the note. Other users never see it, even if they are connected to the same database.",
                    "Shared — the note is visible to all users connected to the same database and project. A teal person icon appears next to the note in the Notes view to indicate it is shared."
                ]),
                .paragraph("You can change a note from private to shared (or back) at any time by editing it and toggling 'Share with all users' before saving."),
                .tip("Sharing a note makes it visible to everyone — use it for observations relevant to the whole team. Keep notes private when they are personal reminders or work-in-progress.")
            ]),
            HelpSection(heading: "Adding multiple notes to one element", body: [
                .paragraph("Any node or edge can hold any number of notes — from different users or from the same user writing separate observations. There are two ways to add a second note:"),
                .bullets([
                    "From the note list sheet — tap the 'Add Note' row at the bottom of the list.",
                    "From inside the note editor — tap 'Add New Note' at the bottom of the form while editing an existing note."
                ]),
                .tip("Each note is independent — different authors, timestamps, filter snapshots, and sharing settings. Notes never overwrite each other.")
            ]),
            HelpSection(heading: "Multi-user notes", body: [
                .paragraph("Because notes are stored in the shared database, multiple team members can annotate the same process simultaneously. Tapping Show Notes on an element with contributions from several users opens the note list, showing each note with its author and date."),
                .bullets([
                    "Notes from other users appear only if they are marked as shared — private notes from other users are never shown.",
                    "The Notes view lists your own notes (private and shared) plus any shared notes from other users, each attributed to its author."
                ]),
                .tip("Private notes are invisible to other users even when they view the same element. Use shared notes for team-visible observations.")
            ]),
            HelpSection(heading: "Editing and deleting notes", body: [
                .paragraph("Notes can be edited from two places:"),
                .bullets([
                    "From the process map — tap the node or edge, tap Show Notes, then tap the note row to open the editor.",
                    "From the Notes view — tap any note row in the list to open it in the editor."
                ]),
                .paragraph("Every saved edit is timestamped. The editor shows the original Author, the creation date, and a 'Last edited' line if the note has been modified."),
                .paragraph("To delete a note: tap Delete Note (in red) at the bottom of the editor, or swipe any note row left in the note list sheet or in the Notes view and tap Delete."),
                .tip("Deleting the last note on a node removes its ✎ badge immediately. If other users still have notes on the same element the badge remains.")
            ]),
            HelpSection(heading: "Notes view", body: [
                .paragraph("Select Notes from the ≡ chart view menu to open a dedicated list of your own notes plus any shared notes from other users for the current project. Notes are sorted newest-first. Each row shows:"),
                .bullets([
                    "The target — step name for a node note, or 'From → To' for an edge note.",
                    "The author username next to the target name.",
                    "A teal person icon when the note is marked as shared.",
                    "The date and time the note was created.",
                    "An italic 'Edited [date]' line when the note has been modified.",
                    "The filter snapshot active at creation time.",
                    "The full note text (up to three lines; tap the row to see more)."
                ]),
                .paragraph("Tap any row to open that note in the editor. Swipe a row left and tap Delete to remove it without opening it."),
                .tip("The Notes view shows notes regardless of the active sidebar filters.")
            ]),
            HelpSection(heading: "Notes and Backup & Restore", body: [
                .paragraph("Process notes are stored in the Exasol database and are not included in Process Mining Demonstrator's Backup & Restore export. They persist as long as the NOTES table exists in the database and survive device changes, re-installs, and user switches automatically.")
            ])
        ]
    )

    // MARK: Backup & Restore

    static let backupRestore = HelpTopic(
        id: "backup", title: "Backup & Restore", subtitle: "Export and import your settings and annotations",
        icon: "externaldrive.badge.timemachine", color: .gray,
        sections: [
            HelpSection(heading: "What is backed up?", body: [
                .paragraph("Backup & Restore exports all of your Process Mining Demonstrator device settings to a single JSON file that can be imported on the same or a different device."),
                .paragraph("A backup always includes:"),
                .bullets([
                    "All connections together with their database servers (host, port, schema, TLS settings) and LLM servers (server URL and model).",
                    "App settings and sidebar expand/collapse state.",
                    "Chart layouts — saved node positions for every project and chart view.",
                    "Target norms defined in the Conformance Check.",
                    "Happy Path definitions — all named paths and their step sequences for every project.",
                    "Filter presets — all named filter presets for all projects.",
                    "LLM prompt templates."
                ]),
                .paragraph("Three sensitive items are optional and controlled by export toggles: the database username, the LLM API key, and Keychain passwords."),
                .paragraph("Process notes are NOT included in the backup. They are stored in the NOTES table of your Exasol database and shared across all users — they survive device changes and re-installs automatically.")
            ]),
            HelpSection(heading: "Exporting a backup", body: [
                .paragraph("Open the sidebar, scroll to the Configuration section, and tap Backup & Restore. The Export section shows three credential toggles, an optional encryption block, and the export button:"),
                .definition(term: "Include database username", detail: "When on (default), the username of each database server is written to the backup file. Turn off to produce a credential-free backup safe to share with others."),
                .definition(term: "Include LLM API key",       detail: "When on, the API key of each LLM server is included. Off by default — enable only when transferring to your own device."),
                .definition(term: "Include passwords",         detail: "When on, stored Keychain passwords are included in the backup. Off by default. When encryption is also enabled, passwords are protected by the backup password; without encryption they appear in plain text."),
                .definition(term: "Encrypt backup file",       detail: "When on, the backup is encrypted with AES-GCM using a key derived from the password you enter (PBKDF2-SHA256, 100 000 iterations). Two password fields appear — Password and Confirm password. The Export Backup… button stays disabled until both fields are non-empty and match."),
                .paragraph("Tap Export Backup… to generate the file and open the iOS share sheet. From there you can save to Files, AirDrop to another device, send via email, or upload to iCloud Drive."),
                .tip("Enable encryption whenever the backup contains credentials (username, API key, or passwords). An encrypted backup is safe to store in cloud services or send over email."),
                .warning("Without encryption, any backup that includes a username, API key, or password contains credentials in plain text inside the JSON file. Store it securely and do not share it over untrusted channels.")
            ]),
            HelpSection(heading: "Encryption and password protection", body: [
                .paragraph("When 'Encrypt backup file' is enabled, the entire JSON payload is encrypted before the file is written. The file uses AES-GCM (256-bit key) with a random salt, so each export produces a unique ciphertext even for identical data."),
                .paragraph("The encryption key is derived from your chosen password using PBKDF2-SHA256 with 100 000 iterations and a 16-byte random salt. The salt is stored alongside the ciphertext inside the file so the password is the only secret you need to keep."),
                .warning("There is no password-reset mechanism. If you forget the password used to encrypt a backup, the file cannot be decrypted and is permanently unreadable. Store the password in a password manager alongside the backup file."),
                .tip("You do not need to encrypt a backup that contains no credentials. Encryption is most valuable when the backup includes usernames, API keys, or Keychain passwords.")
            ]),
            HelpSection(heading: "Importing and previewing a backup", body: [
                .paragraph("Tap Choose Backup File… and select a previously exported .json backup file. If the file is password-protected, a prompt appears immediately asking for the decryption password — enter it and tap Unlock to decrypt the file before the preview is shown. If the wrong password is entered an error is displayed and you can try again by selecting the file again."),
                .paragraph("Once decrypted (or if the file was not encrypted), a Backup Preview section appears that describes the file's contents before anything is changed:"),
                .definition(term: "Created",       detail: "Date and time the backup was originally exported."),
                .definition(term: "Connections",   detail: "Number of connection profiles stored in the backup."),
                .definition(term: "Projects",      detail: "Number of distinct projects that have saved data (layouts, norms, LLM prompts, etc.)."),
                .definition(term: "DB Username",   detail: "Included or Not included — reflects the export choice made when the file was created."),
                .definition(term: "LLM API Key",   detail: "Included or Not included."),
                .definition(term: "Passwords",     detail: "Included or Not included."),
                .definition(term: "Layouts",         detail: "Whether saved chart node positions are present."),
                .definition(term: "Norms",           detail: "Whether target norm values are present."),
                .definition(term: "Happy Paths",     detail: "Whether Happy Path definitions are present."),
                .definition(term: "Filter Presets",  detail: "Whether saved filter presets are present."),
                .tip("The preview is read-only — nothing is restored until you tap Restore Backup… and confirm.")
            ]),
            HelpSection(heading: "Selecting what to restore", body: [
                .paragraph("After the preview, a Restore Options section appears with a toggle for each category of data present in the backup. All toggles default to on. Turn off any category you want to leave untouched on the device:"),
                .definition(term: "App Settings & UI state", detail: "App theme, graph start mode, date slider mode, and all sidebar expand/collapse states."),
                .definition(term: "Connections",             detail: "Connections and their database/LLM servers (host, port, schema, TLS, LLM settings). Sub-toggles appear for the credential fields that were included in the backup."),
                .definition(term: "  Database Username",     detail: "Restores the username field for each database server. Only shown when the backup includes usernames. Disabled when the Connections toggle is off."),
                .definition(term: "  LLM API Key",           detail: "Restores the API key for each LLM server. Only shown when the backup includes API keys. Disabled when the Connections toggle is off."),
                .definition(term: "  Passwords",             detail: "Restores Keychain passwords. Only shown when the backup includes passwords. Disabled when the Connections toggle is off."),
                .definition(term: "Chart Layouts",    detail: "Saved node positions for every project and chart view. Only shown when the backup contains layouts."),
                .definition(term: "Norms & AI Prompts", detail: "Target norm values and per-project LLM prompt templates. Only shown when the backup contains norms."),
                .definition(term: "Happy Paths",      detail: "All named Happy Path definitions. Only shown when the backup contains happy paths."),
                .definition(term: "Filter Presets",   detail: "All named filter presets. Only shown when the backup contains presets."),
                .tip("Categories not present in the backup do not appear as toggles — only content that can actually be restored is shown.")
            ]),
            HelpSection(heading: "Restoring a backup", body: [
                .paragraph("After choosing your restore options, tap Restore Backup… and confirm. Restore behaviour:"),
                .bullets([
                    "Only the categories you left enabled are applied. Everything else on the device is left untouched.",
                    "Connections are merged by ID — connections not present in the backup are always kept regardless of the Connections toggle.",
                    "If a credential field (username, API key, password) is toggled off or was not included in the backup, the existing value on the device is preserved for that connection.",
                    "The active connection is switched to the one recorded in the backup, if that connection exists after the merge and the Connections toggle is on."
                ]),
                .tip("You may need to restart the app for all view state changes (sidebar expand/collapse state, theme) to fully take effect."),
                .warning("Restoring does not delete connections that exist on the device but are absent from the backup. To start clean, delete unwanted connections manually before restoring.")
            ])
        ]
    )

    // MARK: App Security

    static let appSecurity = HelpTopic(
        id: "appsecurity", title: "App Security", subtitle: "Protect the app with Face ID, Touch ID, or passcode",
        icon: "lock.shield.fill", color: .indigo,
        sections: [
            HelpSection(heading: "Overview", body: [
                .paragraph("Process Mining Demonstrator can be locked behind your device's built-in authentication — Face ID, Touch ID, or passcode/password — to prevent unauthorised access to sensitive process data and findings."),
                .paragraph("When enabled, the app presents a lock screen every time it is launched from scratch and every time it returns from the background. No data, charts, or analysis results are visible until authentication succeeds."),
                .tip("Enable this setting whenever the device is shared with colleagues or left unattended, or whenever the process data contains commercially sensitive information.")
            ]),
            HelpSection(heading: "Enabling authentication", body: [
                .paragraph("Open the sidebar, scroll to the Configuration section, and turn on the 'Require authentication' toggle (lock icon). The change takes effect immediately:"),
                .bullets([
                    "The next time the app cold-starts, the lock screen appears automatically and triggers authentication.",
                    "Each time the app moves to the background (home button, app switcher, lock screen) and then returns to the foreground, authentication is required again.",
                    "Disabling the toggle removes all authentication requirements immediately — the lock screen will not appear on the next foreground transition."
                ]),
                .tip("Enabling or disabling the toggle does not lock the app while you are actively using it. The new setting takes effect on the next background-to-foreground transition or cold launch.")
            ]),
            HelpSection(heading: "Authentication methods", body: [
                .paragraph("Process Mining Demonstrator uses the device's built-in Local Authentication framework, which automatically selects the most secure method available:"),
                .definition(term: "Face ID",  detail: "Used on iPad Pro and iPad Air models with Face ID. The lock screen shows a 'Face ID' button and triggers the face scan automatically on appear."),
                .definition(term: "Touch ID", detail: "Used on iPad models with a Touch ID sensor and on Apple Silicon Macs running the app. The fingerprint scanner is triggered automatically."),
                .definition(term: "Passcode / Password", detail: "Used as a fallback when biometrics are unavailable, have failed too many times, or are not configured on the device. On macOS the system login password is used instead of a numeric passcode."),
                .paragraph("If none of the above are configured on the device (no passcode set), the lock screen is bypassed automatically and the app opens without a prompt.")
            ]),
            HelpSection(heading: "Lock screen", body: [
                .paragraph("When authentication is required, a full-screen lock panel covers the app content. The panel shows:"),
                .bullets([
                    "A lock-shield icon and the text 'Process Mining Demonstrator is Locked'.",
                    "A brief explanation that authentication is required to access data.",
                    "An 'Unlock' button labelled with the available method (Face ID, Touch ID, or Passcode)."
                ]),
                .paragraph("Authentication is triggered automatically when the lock screen appears. If the system prompt is dismissed without completing authentication — for example by tapping Cancel — tapping the button manually retries it."),
                .tip("If Face ID or Touch ID fails repeatedly, the system falls back to the passcode/password prompt automatically after a defined number of attempts.")
            ]),
            HelpSection(heading: "iOS system-level app lock", body: [
                .paragraph("In addition to Process Mining Demonstrator's built-in lock, iOS 18 and later allows you to require Face ID for any installed app directly from the home screen, independent of any setting inside the app itself:"),
                .bullets([
                    "On the home screen, touch and hold the Process Mining Demonstrator app icon until the context menu appears.",
                    "Tap 'Require Face ID' (or 'Touch ID' on supported devices).",
                    "Confirm with Face ID when prompted."
                ]),
                .paragraph("The iOS system lock operates at the operating system level and cannot be bypassed by the app. It is separate from the in-app 'Require authentication' toggle — both can be active simultaneously for a layered defence."),
                .tip("The iOS system lock is the strongest protection available because it is enforced by the operating system before Process Mining Demonstrator even launches. Use it on shared or managed devices where process insights data must not be accessible to anyone without biometric authentication.")
            ]),
            HelpSection(heading: "macOS — Designed for iPad", body: [
                .paragraph("On Apple Silicon Macs, Process Mining Demonstrator can run as a 'Designed for iPad' app. The in-app 'Require authentication' toggle works on macOS using Touch ID (if the Mac has a Touch ID sensor) or the macOS login password as a fallback."),
                .paragraph("There is no equivalent to the iOS system-level home screen lock on macOS. For maximum protection on a Mac, enable the in-app 'Require authentication' toggle and ensure the Mac's login screen lock is configured (System Settings → Lock Screen).")
            ]),
            HelpSection(heading: "Privacy considerations", body: [
                .paragraph("The 'Require authentication' setting is stored locally in UserDefaults on the device. It is included in the Backup & Restore export so it can be transferred to a replacement device along with your other settings."),
                .warning("If you restore a backup that has 'Require authentication' enabled onto a new device that does not yet have a passcode configured, the app will bypass the lock screen silently. Configure a passcode or biometrics on the device before restoring to ensure protection is active immediately.")
            ])
        ]
    )

    // MARK: Sampling

    static let sampling = HelpTopic(
        id: "sampling", title: "Journey Sampling", subtitle: "Representative subsets for fast, meaningful analysis",
        icon: "square.3.layers.3d", color: .teal,
        sections: [

            // ── Why sampling? ──────────────────────────────────────────────
            HelpSection(heading: "Why sample?", body: [
                .paragraph("Process mining on large event logs is powerful but expensive: a project with several hundred thousand or millions of journeys can take many seconds per query, making interactive exploration sluggish. Sampling solves this by letting you work with a smaller, carefully chosen subset of journeys that fits inside the same JOURNEYS table — so every chart, filter, and statistic in Process Mining Demonstrator works exactly as usual, just much faster."),
                .paragraph("The key insight is that most analytical questions can be answered reliably from a well-drawn sample. A 10 000-journey sample from a 500 000-journey project will show the same dominant process paths, the same bottlenecks, and the same outlier variants — while loading in a fraction of the time."),
                .tip("Sampling is journey-complete: every step that belongs to a selected journey is copied into the sample. You never see a truncated or partial journey in a sample set."),
                .bullets([
                    "Speed up interactive exploration — reduce query times from seconds to milliseconds.",
                    "Validate hypotheses quickly before running full-scale analysis.",
                    "Create focused variant sets — e.g. a diversity sample that guarantees all rare paths are represented.",
                    "Compare Original vs Sample side-by-side in A/B Comparison to verify the sample is representative."
                ])
            ]),

            // ── How samples are stored ─────────────────────────────────────
            HelpSection(heading: "How samples are stored", body: [
                .paragraph("Samples live in the same JOURNEYS table as the original data. When you create your first sample, Process Mining Demonstrator automatically adds a SAMPLE_SET column to the table and marks every existing row as 'ORIGINAL'. It then inserts copies of the selected journeys with the chosen sample label."),
                .code("-- Added automatically on first sample creation:\nALTER TABLE JOURNEYS ADD COLUMN SAMPLE_SET VARCHAR(20) DEFAULT 'ORIGINAL';\nUPDATE JOURNEYS SET SAMPLE_SET = 'ORIGINAL' WHERE SAMPLE_SET IS NULL;"),
                .definition(term: "ORIGINAL", detail: "Every row that belongs to the full, unsampled dataset. All pre-existing rows receive this value automatically; new journeys written to the table default to it."),
                .definition(term: "SAMPLE_1", detail: "Rows copied from ORIGINAL journeys for Sample Set 1."),
                .definition(term: "SAMPLE_2", detail: "Rows copied from ORIGINAL journeys for Sample Set 2."),
                .definition(term: "SAMPLE_3", detail: "Rows copied from ORIGINAL journeys for Sample Set 3."),
                .paragraph("Process Mining Demonstrator supports up to three independent sample sets per project. Each is a named slice of the JOURNEYS table; they coexist without interfering with each other or with the original data."),
                .warning("Creating the SAMPLE_SET column requires ALTER TABLE permission on the JOURNEYS table. This is a one-time, non-destructive schema change. After the column exists, users with only SELECT permission can still query and view samples — they just cannot create new ones.")
            ]),

            // ── The Sampling section ───────────────────────────────────────
            HelpSection(heading: "The Sampling section", body: [
                .paragraph("The Sampling panel lives in the sidebar. It is available whenever a project is selected. It has two parts:"),
                .definition(term: "Active data picker", detail: "A compact menu at the top of the panel. It shows the name of the currently active data set and its journey count in parentheses. Tap it to switch between Original Data and any created sample. If a sample slot has not been created yet, it is listed as 'not created' and cannot be selected."),
                .definition(term: "Sample slot list", detail: "Three rows — Sample 1, Sample 2, Sample 3. Each row shows a status icon (✓ created, dashed circle empty), the journey count if created, and either a trash icon (delete) or a + icon (create). A progress bar with a stage label slides in while a sample is being built."),
                .tip("The active data set is remembered between sessions. If you close the app with Sample 1 active, it will still be active when you reopen it.")
            ]),

            // ── Sampling methods ──────────────────────────────────────────
            HelpSection(heading: "Random sampling", body: [
                .paragraph("Selects N journeys uniformly at random. Internally, the app loads all journey IDs from the ORIGINAL rows, shuffles them, and takes the first N. Every journey has exactly the same probability of being selected — there is no weighting or stratification."),
                .paragraph("When to use it:"),
                .bullets([
                    "You need a quick performance benchmark and the data is broadly homogeneous.",
                    "You do not care about preserving the temporal distribution or the exact mix of process variants.",
                    "You want the simplest, most reproducible result (re-creating the sample will give a similarly representative set)."
                ]),
                .tip("Random sampling is the fastest method to create because it does not require any grouping query against the database — just a shuffle of IDs.")
            ]),

            HelpSection(heading: "Temporal stratified sampling", body: [
                .paragraph("Divides the full time span of the ORIGINAL data into monthly buckets, then samples journeys proportionally from each bucket so the sample mirrors the original temporal distribution."),
                .paragraph("Example: if your data spans 12 months and 30 % of journeys happened in Q4, approximately 30 % of the sample will come from Q4. No time period is over- or under-represented."),
                .paragraph("When to use it:"),
                .bullets([
                    "Your process shows seasonality, growth trends, or periodic peaks (e.g. end-of-month spikes, campaign periods).",
                    "You want the Statistics view's 'Journeys Over Time' chart to look the same in the sample as in the original.",
                    "You are testing a time-range filter and want the sample to behave consistently for any selected window."
                ]),
                .tip("If your data is very unevenly distributed — for example, 90 % of journeys in one month — temporal stratification prevents that month from dominating the sample while still representing all months fairly.")
            ]),

            HelpSection(heading: "Path diversity sampling", body: [
                .paragraph("Groups ORIGINAL journeys by their exact step sequence (every journey that follows exactly the same path belongs to the same group). It then samples proportionally from each group, guaranteeing that every distinct path variant has at least one representative in the sample."),
                .paragraph("Example: if there are 500 distinct path variants in your data, a 5 000-journey path-diversity sample will contain at least one journey from each of those 500 variants, with the remaining 4 500 slots distributed proportionally by variant frequency."),
                .paragraph("When to use it:"),
                .bullets([
                    "You are doing process discovery or variant analysis and cannot afford to lose rare but important paths.",
                    "You want the process map to show all known variants, not just the most frequent ones.",
                    "You are comparing process variants and need even rare deviations to survive the sampling step."
                ]),
                .warning("Path diversity sampling requires a full scan of the JOURNEYS table to compute path signatures (step sequences) for every journey. On very large tables this is the slowest method to create — but the analytical richness it preserves is worth the wait."),
                .tip("Use path-diversity samples when exploring the process map for the first time on a new dataset. Rare variants that only appear in 0.01 % of journeys would be statistically invisible in a random sample but are guaranteed to appear here.")
            ]),

            // ── Choosing a sample size ─────────────────────────────────────
            HelpSection(heading: "Choosing a sample size", body: [
                .paragraph("There is no universal right answer, but these guidelines work well in practice:"),
                .definition(term: "1 000 – 5 000 journeys", detail: "Good starting point. Process map loads in under a second for most projects. Major paths and bottlenecks are clearly visible. Use this size to explore the overall shape of the process."),
                .definition(term: "5 000 – 20 000 journeys", detail: "Balances speed and statistical depth. Transition frequencies become more reliable, duration statistics tighten, and rare variants are better represented. Recommended for variant analysis and Statistics view exploration."),
                .definition(term: "20 000 – 50 000 journeys", detail: "Near-representative for most purposes. Query times are typically 1–5 seconds. Use this when you need reliable KPIs or are preparing a presentation based on the sample."),
                .tip("After creating a sample, open A/B Comparison and load Original Data in Chart A and the sample in Chart B. If the process maps look structurally similar — same dominant paths, same major branches — the sample is representative. If key paths are missing or weights look very different, increase the sample size or switch to Path Diversity sampling."),
                .paragraph("Three independent sample slots allow you to maintain samples at different sizes simultaneously — for example, a 2 000-journey quick-exploration sample in Slot 1 and a 20 000-journey presentation-quality sample in Slot 2.")
            ]),

            // ── Creating a sample ──────────────────────────────────────────
            HelpSection(heading: "Creating a sample (step by step)", body: [
                .paragraph("A project must be selected and a database connection active before you can create samples."),
                .bullets([
                    "Open the Sampling section in the sidebar.",
                    "Tap the + button on any empty slot (Sample 1, 2, or 3).",
                    "In the creation sheet, enter the number of journeys in the Count field.",
                    "Select a sampling method by tapping its row.",
                    "Tap Create Sample."
                ]),
                .paragraph("The sheet stays open while the sample is being built and shows a linear progress bar with a stage label: 'Preparing…' → 'Fetching journeys…' → 'Writing N journeys…'. The sheet closes automatically once the sample is ready. If an error occurs, the error message is shown inline and the form re-enables so you can adjust settings and retry."),
                .tip("The last-used sampling method is remembered as the default for the next time you open the creation sheet. You can also change the default permanently in Settings → Sampling Preferences.")
            ]),

            // ── Switching the active data set ──────────────────────────────
            HelpSection(heading: "Switching the active data set", body: [
                .paragraph("The 'Active data' menu at the top of the Sampling panel controls which data set all charts and queries use. Tapping it opens a dropdown that lists Original Data and every created sample, each showing its journey count."),
                .paragraph("Switching the active set takes effect immediately for all subsequent queries. Charts do not reload automatically — tap Apply in the sidebar Filters section (or navigate to a chart view) to load data from the new active set."),
                .definition(term: "Original Data", detail: "Queries the full JOURNEYS table, filtered to SAMPLE_SET = 'ORIGINAL' or NULL. This is always available regardless of whether any samples exist."),
                .definition(term: "Sample 1 / 2 / 3", detail: "Queries only the rows with the corresponding SAMPLE_SET value. These options are only selectable once the sample has been created."),
                .tip("The active data set selection is stored in Settings → Sampling Preferences and persists between app launches, per connection.")
            ]),

            // ── Comparing original vs sample ───────────────────────────────
            HelpSection(heading: "Comparing Original vs Sample", body: [
                .paragraph("A/B Comparison is the best way to validate that a sample is representative before relying on it for analysis:"),
                .bullets([
                    "Switch to Original Data and open A/B Comparison.",
                    "Apply filters and tap Apply to load the original data into Chart A.",
                    "Switch the active data set to the sample you want to validate.",
                    "Tap the B-Chart panel header to make it active, then tap Apply to load the sample into Chart B.",
                    "Open the valve (sync icon on the divider) so both panels share a viewport.",
                    "Compare transition counts, path shapes, and the Process Similarity badge between the two panels."
                ]),
                .tip("The Process Similarity score (Q) shown between the two panels is a direct measure of how well the sample reproduces the process structure of the original. A Q above 0.85 generally indicates a representative sample.")
            ]),

            // ── Deleting a sample ──────────────────────────────────────────
            HelpSection(heading: "Deleting a sample", body: [
                .paragraph("Tap the trash icon on a sample slot. A confirmation dialog shows how many rows will be removed. Confirming the deletion permanently removes all JOURNEYS rows with that SAMPLE_SET value."),
                .paragraph("Original data (SAMPLE_SET = 'ORIGINAL' or NULL) is never touched. Other sample slots are unaffected. The slot becomes empty and shows the + button again, ready for a new sample."),
                .warning("Deletion cannot be undone from within the app. Re-creating the sample will produce a statistically similar but not identical result for Random and Temporal methods (due to the random shuffle). Path Diversity samples are deterministic — re-creating one with the same count and the same source data always yields the same set of path variants.")
            ]),

            // ── Permissions ───────────────────────────────────────────────
            HelpSection(heading: "Required permissions", body: [
                .paragraph("The database user configured in the active connection needs:"),
                .bullets([
                    "SELECT on JOURNEYS — always required (to load and query any data).",
                    "ALTER TABLE on JOURNEYS — required once, to add the SAMPLE_SET column the first time any sample is created.",
                    "INSERT on JOURNEYS — required to write sample rows.",
                    "DELETE on JOURNEYS — required to delete a sample."
                ]),
                .paragraph("Read-only users (SELECT only) can still query and visualise existing samples — they just cannot create or delete them. The + and trash controls are disabled when the connected user lacks the necessary permissions."),
                .tip("If your DBA cannot grant ALTER TABLE to the analytics user, ask them to run the one-time schema change manually: ALTER TABLE JOURNEYS ADD COLUMN SAMPLE_SET VARCHAR(20) DEFAULT 'ORIGINAL'. After that, only INSERT and DELETE are needed for ongoing sample management.")
            ]),

            // ── Default method preference ──────────────────────────────────
            HelpSection(heading: "Default method preference", body: [
                .paragraph("Open Settings (⌘,) and navigate to Sampling Preferences. The 'Default sampling method' picker sets which method is pre-selected when you open the Create Sample sheet. This is a local setting; it does not affect the database or any existing samples."),
                .tip("If you always work with path diversity analysis, set the default to Path Diversity so you do not have to re-select it each time.")
            ])
        ]
    )

    // MARK: Simulation

    static let simulation = HelpTopic(
        id: "simulation", title: "Simulation", subtitle: "Synthetic process data from a calibrated Markov model",
        icon: "chart.line.flattrend.xyaxis", color: .purple,
        sections: [

            // ── What is simulation? ───────────────────────────────────────────
            HelpSection(heading: "What is simulation?", body: [
                .paragraph("The Simulation view generates synthetic event logs that statistically resemble your real process. It builds a first-order Markov chain from the currently loaded process graph, then walks that chain to produce journeys consisting of the same three fields your database contains: a journey identifier, a step name, and a timestamp."),
                .paragraph("Every synthetic journey follows the routing probabilities and timing distributions observed in your actual data. This makes the generated log useful for load-testing, what-if analysis, training data generation, or simply exploring 'what would 10 000 more journeys through this process look like?'"),
                .tip("The simulation uses the process graph that is currently loaded in Chart A, including any date-range and step filters you have applied. Apply your desired filters before switching to Simulation to calibrate the model on a specific slice of your data.")
            ]),

            // ── How the model is calibrated ───────────────────────────────────
            HelpSection(heading: "How the model is calibrated", body: [
                .paragraph("The calibration algorithm reads three things from the currently displayed process graph:"),
                .definition(term: "Transition probabilities", detail: "For every step that has outgoing transitions, the occurrence counts are normalised to probabilities. A step with 600 transitions to 'Approve' and 400 to 'Reject' will route 60 % of simulated journeys to 'Approve' and 40 % to 'Reject'."),
                .definition(term: "Duration distributions", detail: "Each directed edge (from → to) carries an average duration and a standard deviation from the real data. The simulator fits a lognormal distribution to these two numbers and samples from it to advance the clock when a step transition occurs. Lognormal is the correct shape for process durations: it is strictly positive and right-skewed, matching the long tail of slow cases seen in practice."),
                .definition(term: "Start steps", detail: "Steps whose incoming frequency is less than 20 % of their outgoing frequency are identified as likely entry points. Their relative frequency of occurrence as first steps is used to sample the opening step of each journey."),
                .paragraph("If a step has timing data in only one direction (average without standard deviation, or vice versa), the simulator falls back to using the available value only. If no timing data is present for an edge, a one-hour lognormal is used as a default."),
                .tip("The calibration happens automatically whenever you tap Simulate. If you change the active filters in Chart A, switch back to Simulation and tap Simulate again to recalibrate from the updated graph.")
            ]),

            // ── Arrival process ───────────────────────────────────────────────
            HelpSection(heading: "Arrival process", body: [
                .paragraph("New journeys are born according to a Poisson process: the gap between consecutive journey start times is drawn from an exponential distribution parameterised by the 'Avg Arrival (h)' field. This is the standard model for arrivals in queueing theory and discrete-event simulation."),
                .paragraph("A Poisson process has the memoryless property: knowing that no journey started in the last two hours tells you nothing about when the next journey will start. This correctly models processes where cases are independently initiated — order placements, patient admissions, support tickets, and so on."),
                .definition(term: "Avg Arrival (h)", detail: "The mean number of hours between consecutive journey start times. A value of 1.0 means one new journey starts every hour on average (rate λ = 1/h). Set this to match the arrival rate in your real data — for example, if your real data contains 720 journeys per month, a rate of one journey per hour is a reasonable starting point."),
                .tip("To estimate the correct arrival rate, check the 'Journeys over time' chart in the Statistics view. Divide the journey count by the time span in hours.")
            ]),

            // ── Parameters ────────────────────────────────────────────────────
            HelpSection(heading: "Simulation parameters", body: [
                .paragraph("All parameters are set in the configuration panel on the left (iPad/Mac) or top (iPhone). Changes take effect the next time you tap Simulate."),
                .definition(term: "Journey Count", detail: "How many complete journeys to generate. Range: 10 to 10 000. Higher counts produce more stable variant distributions and smoother histograms but take longer to compute. For a first run, 200–500 is usually sufficient to see the dominant process shape."),
                .definition(term: "Start Date", detail: "The date assigned to the first simulated journey's opening event. Subsequent events are timestamped relative to this anchor using the inter-arrival times and step durations."),
                .definition(term: "Avg Arrival (h)", detail: "Mean hours between new journey arrivals. Controls the spread of timestamps in the exported CSV and the simulated timeline, but does not affect routing or cycle times."),
                .definition(term: "Max Steps", detail: "Hard cap on the number of steps per journey. Prevents rework loops from running forever. If a journey hits the cap it is included in the results as-is, with a potentially incomplete path. Range: 10 to 200. The default (60) is sufficient for most real-world processes."),
                .tip("If you see many journeys with exactly 60 steps in the Table view, the Max Steps cap is being hit. Increase it if your process genuinely contains long rework loops, or add the looping step to the Excluded Steps list.")
            ]),

            // ── Excluded and included steps ───────────────────────────────────
            HelpSection(heading: "Excluded and included steps", body: [
                .paragraph("Both lists are collapsed by default. Tap a section header to expand it. The step picker uses the same design as the global filter panel in the sidebar: a search field to narrow long step lists, then a scrollable checklist where a filled circle (●) marks selected steps and an empty circle (○) marks unselected ones."),
                .definition(term: "Exclude Steps", detail: "Steps selected here are removed from the Markov model entirely before simulation begins. All transitions to and from excluded steps are discarded. Use this to model a process improvement — for example, removing a manual approval step to see what the flow looks like when it is automated away. Steps that would become unreachable as a result of the exclusion (their only incoming edge came from the excluded step) are automatically excluded too, transitively."),
                .definition(term: "Include Steps (must-visit filter)", detail: "Steps selected here act as a post-simulation filter: only journeys that visit every selected step at least once are kept in the final result. The simulation generates the full configured number of journeys and then discards those that do not pass the filter. The displayed Simulated Journeys count will therefore be lower than the configured Journey Count if the required steps are rare."),
                .paragraph("Mutual exclusion is enforced: a step selected in Exclude Steps is greyed and unselectable in Include Steps, and vice versa. This prevents contradictory configurations."),
                .tip("The accent-coloured count badge next to each section title (e.g. '3') tells you how many steps are active without expanding the list. Tap the × icon beside the badge to clear all selections in one step.")
            ]),

            // ── Results: view selector ────────────────────────────────────────
            HelpSection(heading: "Navigating the results — Flow, Table, Charts", body: [
                .paragraph("After a simulation completes, results are presented in three tabs. The KPI strip and the tab selector (Flow | Table | Charts) plus the Export CSV button are always visible in a fixed header at the top of the results panel, regardless of which tab is active. The Flow tab is selected by default when a simulation finishes."),
                .definition(term: "Flow", detail: "The directly-follows graph of the simulated event log, rendered as an interactive flow chart. Shown first as the default view."),
                .definition(term: "Table", detail: "A ranked table of all distinct journey variants found in the output, ordered by frequency."),
                .definition(term: "Charts", detail: "A top-10 variants bar chart and a cycle-time distribution histogram.")
            ]),

            // ── The KPI summary strip ─────────────────────────────────────────
            HelpSection(heading: "KPI summary tiles", body: [
                .paragraph("Six tiles appear in a horizontally scrollable strip immediately after a simulation completes. The strip is persistent — it stays visible across all three tabs (Flow, Table, and Charts) — and uses the same design as the main process map KPI panel."),
                .definition(term: "Simulated Journeys", detail: "Total number of journeys in the simulation output. May be lower than the configured Journey Count if Include Steps filtering discarded some generated journeys."),
                .definition(term: "Variants", detail: "Number of distinct step-sequences found across all simulated journeys."),
                .definition(term: "Shortest Journey", detail: "Minimum end-to-end duration observed across all simulated journeys."),
                .definition(term: "Avg Journey", detail: "Mean end-to-end duration across all simulated journeys, from first step to last step."),
                .definition(term: "Std Dev", detail: "Standard deviation of the cycle time distribution. A high value relative to the mean indicates a wide spread — many fast journeys and many slow ones."),
                .definition(term: "Longest Journey", detail: "Maximum end-to-end duration observed. Because the simulator draws durations from a lognormal distribution, very short minimum values and unexpectedly long maximum values are both statistically possible — this is expected behaviour of a calibrated stochastic model.")
            ]),

            // ── Results: Flow tab ─────────────────────────────────────────────
            HelpSection(heading: "Results — Flow tab", body: [
                .paragraph("The Flow tab renders the directly-follows graph aggregated from the simulated event log using the same interactive FlowChartView used throughout the app. The graph is auto-fitted to the available viewport on first display and every time you run a new simulation, so all nodes and connections are immediately visible without manual zooming."),
                .paragraph("Node colours, shapes, and groupings come from the project's STEPS configuration — the same visual rules that apply to the A-Chart and B-Chart. Edge thickness and labels reflect how often each transition occurred in the simulated log."),
                .paragraph("Because the simulation is probabilistic, the simulated graph will not be identical to the real one. High-frequency transitions will have similar relative weights, but rare transitions may appear more or less often than in the original data. With a small Journey Count, some low-probability edges from the real graph may not be sampled at all."),
                .tip("Pinch or use the scroll wheel to zoom, drag to pan, and long-press a node to access the include/exclude context menu — all the same interactions as in the A-Chart.")
            ]),

            // ── Results: Table tab ────────────────────────────────────────────
            HelpSection(heading: "Results — Table tab", body: [
                .paragraph("The Table tab shows a ranked list of all distinct journey variants found in the simulated output. Columns:"),
                .definition(term: "#", detail: "Rank by frequency. Variant 1 is the most common path."),
                .definition(term: "Path", detail: "The full ordered sequence of step names, separated by ' → '. Long paths are truncated in the cell but the full path is shown in a tooltip on hover."),
                .definition(term: "N", detail: "Number of simulated journeys that followed this exact path."),
                .definition(term: "%", detail: "This variant's share of total simulated journeys."),
                .definition(term: "Avg", detail: "Average cycle time of journeys that followed this path, formatted as seconds (s), minutes (m), hours (h), or days (d)."),
                .paragraph("Up to 50 variants are shown. If the simulation produced more, only the top 50 by frequency are displayed.")
            ]),

            // ── Results: Charts tab ───────────────────────────────────────────
            HelpSection(heading: "Results — Charts tab", body: [
                .paragraph("The Charts tab shows two complementary visualisations of the simulated output."),
                .definition(term: "Top 10 Variants bar chart", detail: "A horizontal bar chart where each bar represents one of the ten most frequent variants. The bar length encodes the journey count; a percentage annotation appears at the right edge. The variants are labelled V1–V10 in descending frequency order. A legend below the chart maps each label to its full path sequence."),
                .definition(term: "Cycle Time Distribution histogram", detail: "A vertical bar chart that bins all simulated journey durations into 12 equal-width buckets. The x-axis shows time (formatted automatically as seconds, minutes, hours, or days), and the y-axis shows how many journeys fell into each bucket. The shape of this histogram reflects both the routing probabilities and the per-step timing distributions from your real data."),
                .tip("A unimodal, right-skewed histogram (one peak, long tail to the right) is typical for well-behaved processes. A bimodal histogram often indicates two fundamentally different process paths — check the Table tab to see if a clear split exists between the fast and slow variants.")
            ]),

            // ── Exporting the event log ───────────────────────────────────────
            HelpSection(heading: "Exporting the simulated event log", body: [
                .paragraph("Tap 'Export CSV' to save the full event log as a comma-separated values file. The file contains one row per event (not per journey), with three columns:"),
                .code("JOURNEY_ID,STEP,EVENT_TIME"),
                .definition(term: "JOURNEY_ID", detail: "Sequential identifier for each journey, formatted as SIM-1, SIM-2, … SIM-N."),
                .definition(term: "STEP", detail: "The step name as it appears in the process graph. Step names that contain commas are automatically quoted."),
                .definition(term: "EVENT_TIME", detail: "ISO 8601 timestamp (e.g. 2025-03-15T08:23:11Z). Events within a journey are sorted chronologically."),
                .paragraph("The exported CSV is structurally identical to a JOURNEYS table export from Exasol, which means you can:"),
                .bullets([
                    "Import it into another process mining tool for comparison.",
                    "Load it into Excel or Python/pandas for custom analysis.",
                    "Import it back into an Exasol JOURNEYS table as a new sample set for testing purposes.",
                    "Use it as training data for ML models that need labelled process event logs."
                ]),
                .tip("On iPad and Mac, tapping 'Export CSV' opens a native Save panel so you can choose the file name and destination. On iPhone, the share sheet appears instead.")
            ]),

            // ── Typical use cases ─────────────────────────────────────────────
            HelpSection(heading: "Typical use cases", body: [
                .paragraph("Process simulation is most valuable in the following scenarios:"),
                .definition(term: "Load and volume testing", detail: "Generate 5 000 or 10 000 synthetic journeys matching your process structure to benchmark how downstream systems or dashboards perform under realistic load, without waiting for real data to accumulate."),
                .definition(term: "Process redesign what-if analysis", detail: "Exclude a step to model automation, or add an Included Steps filter to focus on a specific sub-process. Observe how the variant distribution and cycle-time histogram change when a step is removed."),
                .definition(term: "Training data for ML models", detail: "Many classification or anomaly-detection models require labelled event logs. The simulator lets you generate balanced training sets with controlled properties — for example, equal numbers of fast and slow journeys, or a custom mix of path variants."),
                .definition(term: "Demonstrating process insights", detail: "A simulated flow chart or variant table can be shown in a presentation without exposing real production data, while still accurately reflecting the structure and timing of the actual process."),
                .definition(term: "Validating conformance rules", detail: "Generate a large synthetic log and run it through the Conformance Check view to verify that your target norms behave correctly before applying them to real data.")
            ]),

            // ── Limitations ───────────────────────────────────────────────────
            HelpSection(heading: "Limitations and assumptions", body: [
                .paragraph("The simulator is a first-order Markov model. This means each routing decision depends only on the current step, not on what came before. If your real process has strong history-dependent routing — for example, journeys that were rejected once behave very differently on subsequent attempts — the model will not capture this."),
                .bullets([
                    "Long-range dependencies and case attributes (META_1–3) are not modelled. The simulator has no concept of a 'customer segment' or 'region' that influences routing.",
                    "Resource constraints and queues are not modelled. Cycle times are sampled independently for each event; there is no concept of a busy resource causing waiting time to increase when volume doubles.",
                    "The model calibrates from the visible graph only. If the active filter excludes date ranges or step types, the calibrated model reflects only the filtered subset, not the full process.",
                    "Very rare transitions (those that occurred only a handful of times in the real data) may have unreliable duration estimates. The lognormal fit requires at least a plausible standard deviation, and a standard deviation estimated from two or three observations is noisy."
                ]),
                .warning("Do not use simulation results as a substitute for real data analysis when making production decisions. The simulation accurately reproduces the statistical structure of your process — but it does not reproduce individual journey behaviour, seasonal effects, or emergent properties that arise from resource contention."),
                .tip("For a richer simulation that includes resource pools and queueing effects (the jump from 'data generator' to true discrete-event simulation), consider exporting the calibrated Markov parameters from the CSV and feeding them into a dedicated DES tool such as SimPy.")
            ])
        ]
    )
}

// MARK: - Main view (NavigationStack for floating-panel compatibility)

struct HelpView: View {
    var onDismiss: (() -> Void)? = nil
    @Environment(\.dismiss) private var dismiss
    @State private var searchText  = ""

    private let gettingStarted: [HelpTopic] = [.appSecurity, .overview, .gettingExasol, .databaseSetup, .connecting, .demoData]
    private let reference: [HelpTopic]      = [.chartViews, .processMap, .filters, .filterPresets, .kpi, .processGoodness, .processSimilarity, .configuration, .complianceCheck, .happyPath, .aiDocumentation, .processNotes, .backupRestore, .sampling, .simulation]
    private let columns = [GridItem(.flexible(), spacing: 12), GridItem(.flexible(), spacing: 12)]

    private func filtered(_ topics: [HelpTopic]) -> [HelpTopic] {
        guard !searchText.isEmpty else { return topics }
        let q = searchText.lowercased()
        return topics.filter {
            $0.title.lowercased().contains(q) ||
            $0.subtitle.lowercased().contains(q) ||
            $0.sections.contains { $0.heading.lowercased().contains(q) }
        }
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 24) {
                    // App branding header
                    HStack(spacing: 16) {
                        LenticularisLogoView(56)
                        VStack(alignment: .leading, spacing: 2) {
                            Text("Process Mining")
                                .font(.title3.weight(.bold))
                            Text("Demonstrator")
                                .font(.subheadline)
                                .foregroundStyle(.secondary)
                        }
                        Spacer(minLength: 0)
                    }
                    .padding(.horizontal, 20)
                    .padding(.top, 16)
                    .padding(.bottom, 4)

                    HStack(spacing: 8) {
                        Image(systemName: "magnifyingglass")
                            .foregroundStyle(.secondary)
                        TextField("Search topics", text: $searchText)
                            .autocorrectionDisabled()
                    }
                    .padding(.horizontal, 12)
                    .padding(.vertical, 10)
                    .background(
                        RoundedRectangle(cornerRadius: 10, style: .continuous)
                            .fill(Color(.secondarySystemGroupedBackground))
                    )
                    .padding(.horizontal, 16)
                    .padding(.top, 8)

                    helpSection("Getting Started", topics: filtered(gettingStarted))
                    helpSection("Reference",       topics: filtered(reference))
                }
                .padding(.bottom, 24)
            }
            .background(Color(.systemGroupedBackground))
            .navigationTitle("Help")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") {
                        if let onDismiss { onDismiss() } else { dismiss() }
                    }
                }
            }
        }
    }

    // MARK: Print

    /// Renders the help document to PDF `Data` via the shared WKWebView → PDF
    /// pipeline. This path works on iOS, Mac Catalyst, and native macOS because
    /// it never invokes the system print UI — `UIPrintInteractionController`
    /// reports "This application does not support printing" under Mac Catalyst,
    /// so we generate the PDF directly and let the caller share/save it instead.
    @MainActor
    static func generatePDFData() async -> Data? {
        // SF Symbol / logo rendering must happen on the main thread.
        let icons = HelpPrintDocument.precomputeIcons()
        let logoBase64 = HelpPrintDocument.renderLogo()
        let html = HelpPrintDocument.buildHTML(icons: icons, logoBase64: logoBase64)
        return await withCheckedContinuation { cont in
            HelpPDFRenderer.render(html: html) { data in
                cont.resume(returning: data)
            }
        }
    }

    @ViewBuilder
    private func helpSection(_ heading: String, topics: [HelpTopic]) -> some View {
        if !topics.isEmpty {
            VStack(alignment: .leading, spacing: 12) {
                Text(heading)
                    .font(.title3.weight(.semibold))
                    .padding(.horizontal, 20)

                LazyVGrid(columns: columns, spacing: 12) {
                    ForEach(topics) { topic in
                        NavigationLink {
                            HelpDetailView(topic: topic)
                        } label: {
                            HelpTopicCard(topic: topic)
                        }
                        .buttonStyle(.plain)
                    }
                }
                .padding(.horizontal, 16)
            }
        }
    }
}

private struct HelpTopicCard: View {
    let topic: HelpTopic

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            ZStack {
                RoundedRectangle(cornerRadius: 10, style: .continuous)
                    .fill(topic.color.opacity(0.15))
                    .frame(width: 44, height: 44)
                Image(systemName: topic.icon)
                    .font(.title3.weight(.semibold))
                    .foregroundStyle(topic.color)
            }
            VStack(alignment: .leading, spacing: 3) {
                Text(topic.title)
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(.primary)
                Text(topic.subtitle)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: 10, style: .continuous)
                .fill(Color(.secondarySystemGroupedBackground))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 10, style: .continuous)
                .strokeBorder(Color.primary.opacity(0.10), lineWidth: 1)
        )
    }
}

// MARK: - Detail view

struct HelpDetailView: View {
    let topic: HelpTopic

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                HStack(spacing: 16) {
                    ZStack {
                        RoundedRectangle(cornerRadius: 14, style: .continuous)
                            .fill(topic.color.opacity(0.15))
                            .frame(width: 52, height: 52)
                        Image(systemName: topic.icon)
                            .font(.title2.weight(.semibold))
                            .foregroundStyle(topic.color)
                    }
                    Text(topic.title)
                        .font(.largeTitle.weight(.bold))
                    Spacer(minLength: 0)
                }
                .padding(.horizontal, 24)
                .padding(.top, 24)
                .padding(.bottom, 16)

                Divider().padding(.horizontal, 24)

                ForEach(topic.sections) { section in
                    VStack(alignment: .leading, spacing: 10) {
                        Text(section.heading)
                            .font(.headline)
                            .padding(.top, 22)
                        ForEach(section.body) { block in
                            HelpBlockView(block: block)
                        }
                    }
                    .padding(.horizontal, 24)
                }

                if topic.id == "demodata" {
                    Divider()
                        .padding(.horizontal, 24)
                        .padding(.top, 8)
                    Text("Generate Dataset")
                        .font(.headline)
                        .padding(.horizontal, 24)
                        .padding(.top, 22)
                        .padding(.bottom, 2)
                    DemoDataGeneratorView()
                }

                Spacer(minLength: 28)
            }
        }
        .background(Color(.systemGroupedBackground))
        .navigationTitle(topic.title)
        .navigationBarTitleDisplayMode(.inline)
    }
}

// MARK: - Block renderer

struct HelpBlockView: View {
    let block: HelpBlock

    var body: some View {
        switch block {
        case .paragraph(let text):
            Text(text)
                .font(.body)
                .fixedSize(horizontal: false, vertical: true)

        case .tip(let text):
            callout(text, icon: "lightbulb.fill",              tint: .yellow, label: "Tip")
        case .warning(let text):
            callout(text, icon: "exclamationmark.triangle.fill", tint: .orange, label: "Warning")

        case .bullets(let items):
            VStack(alignment: .leading, spacing: 6) {
                ForEach(items, id: \.self) { item in
                    HStack(alignment: .top, spacing: 8) {
                        Text("•").foregroundStyle(.secondary)
                        Text(item).fixedSize(horizontal: false, vertical: true)
                    }
                    .font(.body)
                }
            }

        case .definition(let term, let detail):
            HStack(alignment: .top, spacing: 0) {
                Text(term)
                    .font(.body.weight(.semibold))
                    .frame(minWidth: 130, alignment: .leading)
                Text(detail)
                    .font(.body)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .padding(.vertical, 2)

        case .code(let text):
            Text(text)
                .font(.system(.caption, design: .monospaced))
                .foregroundStyle(.primary)
                .padding(12)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(
                    RoundedRectangle(cornerRadius: 8, style: .continuous)
                        .fill(Color(.secondarySystemGroupedBackground))
                )
                .overlay(
                    RoundedRectangle(cornerRadius: 8, style: .continuous)
                        .stroke(Color.secondary.opacity(0.2), lineWidth: 0.5)
                )
        }
    }

    private func callout(_ text: String, icon: String, tint: Color, label: String) -> some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: icon)
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(tint)
                .padding(.top, 1)
            VStack(alignment: .leading, spacing: 2) {
                Text(label).font(.subheadline.weight(.semibold)).foregroundStyle(tint)
                Text(text).font(.subheadline).fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 10, style: .continuous).fill(tint.opacity(0.10)))
    }
}

// MARK: - Identifiable for HelpBlock

extension HelpBlock: Identifiable {
    var id: String {
        switch self {
        case .paragraph(let t):        return "p_\(t.prefix(30))"
        case .tip(let t):              return "tip_\(t.prefix(30))"
        case .warning(let t):          return "warn_\(t.prefix(30))"
        case .bullets(let b):          return "b_\(b.first?.prefix(30) ?? "")"
        case .definition(let term, _): return "def_\(term)"
        case .code(let t):             return "code_\(t.prefix(30))"
        }
    }
}

// MARK: - Demo Data Generator (interactive widget embedded in the Demo Data help topic)

private struct DemoDataGeneratorView: View {
    @ObservedObject private var db = DatabaseManager.shared
    @State private var schemaName   = DatabaseManager.shared.activeDatabaseServer?.schema.uppercased().isEmpty == false
                                        ? (DatabaseManager.shared.activeDatabaseServer!.schema.uppercased())
                                        : "DEMO"
    @State private var numJourneys  = 500
    @State private var isGenerating = false
    @State private var progress     = 0.0
    @State private var statusMsg    = ""
    @State private var isSuccess    = false

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 8) {
                Text("Schema")
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .frame(width: 70, alignment: .leading)
                TextField("DEMO", text: $schemaName)
                    .font(.callout)
                    .autocorrectionDisabled()
                    .textInputAutocapitalization(.characters)
                    .padding(.horizontal, 10)
                    .padding(.vertical, 7)
                    .background(
                        RoundedRectangle(cornerRadius: 8)
                            .fill(Color.secondary.opacity(0.12))
                    )
            }

            HStack(spacing: 8) {
                Text("Journeys")
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .frame(width: 70, alignment: .leading)
                Stepper(value: $numJourneys, in: 10...5_000, step: 100) {
                    Text("\(numJourneys)")
                        .font(.callout.monospacedDigit())
                }
            }

            Button {
                Task { await runGeneration() }
            } label: {
                if isGenerating {
                    HStack(spacing: 6) {
                        ProgressView().controlSize(.small)
                        Text("Generating")
                    }
                    .frame(maxWidth: .infinity)
                } else {
                    Label("Generate Demo Data", systemImage: "wand.and.stars")
                        .frame(maxWidth: .infinity)
                }
            }
            .buttonStyle(.borderedProminent)
            .disabled(!db.isConnected || isGenerating ||
                      schemaName.trimmingCharacters(in: .whitespaces).isEmpty)

            if !db.isConnected {
                Label("Connect to a database first.", systemImage: "exclamationmark.triangle")
                    .font(.callout)
                    .foregroundStyle(.orange)
            }

            if isGenerating || !statusMsg.isEmpty {
                VStack(alignment: .leading, spacing: 6) {
                    if isGenerating {
                        ProgressView(value: progress)
                            .progressViewStyle(.linear)
                    }
                    Text(statusMsg)
                        .font(.callout)
                        .foregroundStyle(
                            isSuccess    ? Color.green :
                            isGenerating ? Color.secondary : Color.red)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        }
        .padding(.horizontal, 24)
        .padding(.vertical, 12)
    }

    private func runGeneration() async {
        let schema = schemaName.trimmingCharacters(in: .whitespaces).uppercased()
        guard !schema.isEmpty else { return }

        isGenerating = true
        isSuccess    = false
        progress     = 0
        statusMsg    = "Generating journey data"

        let count = numJourneys
        let rows  = BookstoreGen.generateAllRows(count: count)
        let sq: (String) -> String = { $0.replacingOccurrences(of: "'", with: "''") }

        do {
            statusMsg = "Creating schema";  progress = 0.02
            _ = try await db.execute("CREATE SCHEMA IF NOT EXISTS \"\(schema)\"")

            statusMsg = "Creating tables"; progress = 0.06
            for sql in BookstoreGen.createTableSQLs(schema: schema) {
                _ = try await db.execute(sql)
            }

            statusMsg = "Inserting reference data"; progress = 0.12
            _ = try await db.execute(BookstoreGen.deleteProjectSQL(schema: schema, sq: sq))
            _ = try await db.execute(BookstoreGen.insertProjectSQL(schema: schema, sq: sq))
            _ = try await db.execute(BookstoreGen.deleteMetasSQL(schema: schema, sq: sq))
            _ = try await db.execute(BookstoreGen.insertMetasSQL(schema: schema, sq: sq))
            for sql in BookstoreGen.insertStepsSQLs(schema: schema, sq: sq) {
                _ = try await db.execute(sql)
            }

            statusMsg = "Clearing old journeys"; progress = 0.14
            _ = try await db.execute(BookstoreGen.deleteJourneysSQL(schema: schema, sq: sq))

            let batchSize  = 200
            let batchCount = Int(ceil(Double(rows.count) / Double(batchSize)))
            var batchIdx   = 0
            var offset     = 0
            while offset < rows.count {
                let end   = min(offset + batchSize, rows.count)
                let batch = Array(rows[offset..<end])
                _ = try await db.execute(
                    BookstoreGen.insertJourneysSQL(schema: schema, rows: batch, sq: sq))
                batchIdx += 1
                offset   += batchSize
                progress = 0.15 + 0.85 * Double(batchIdx) / Double(max(1, batchCount))
                statusMsg = "Inserting journeys (\(batchIdx)/\(batchCount))"
            }

            statusMsg = "Done — \(count) journeys created in \"\(schema)\".JOURNEYS"
            isSuccess = true
            progress  = 1.0
        } catch {
            statusMsg = error.localizedDescription
            isSuccess = false
        }

        isGenerating = false
    }
}

// MARK: - Bookstore demo data generator

private enum BookstoreGen {

    struct JEvent {
        let eventId:   String
        let step:      String
        let stepId:    Int
        let eventTime: Date
        let meta1:     String
        let meta2:     String
        let meta3:     String
    }

    static  let projectId         = "BOOKSTORE"
    private static let returnRate = 0.05

    private static let payments: [(String, Double)] = [
        ("Credit Card", 0.45), ("PayPal", 0.35), ("Bank Transfer", 0.20)
    ]
    private static let segments: [(String, Double)] = [
        ("New", 0.30), ("Regular", 0.50), ("Premium", 0.20)
    ]
    private static let orderVals: [(String, Double)] = [
        ("Low (<30 EUR)", 0.40), ("Medium (30-100 EUR)", 0.40), ("High (>100 EUR)", 0.20)
    ]

    private static func wc(_ dist: [(String, Double)]) -> String {
        let r = Double.random(in: 0..<1)
        var cum = 0.0
        for (item, w) in dist { cum += w; if r < cum { return item } }
        return dist.last!.0
    }

    private static func md5Id(_ raw: String) -> String {
        let digest = Insecure.MD5.hash(data: Data(raw.utf8))
        return digest.map { String(format: "%02x", $0) }.joined()
    }

    private static func randStart() -> Date {
        let cal   = Calendar(identifier: .gregorian)
        let start = cal.date(from: DateComponents(year: 2024, month: 1,  day: 1,  hour: 8))!
        let end   = cal.date(from: DateComponents(year: 2024, month: 12, day: 31, hour: 22))!
        return start.addingTimeInterval(Double.random(in: 0..<end.timeIntervalSince(start)))
    }

    static func generateAllRows(count: Int) -> [JEvent] {
        var all: [JEvent] = []
        all.reserveCapacity(count * 16)
        for i in 0..<count {
            let eid = md5Id(String(format: "ORD-%06d", i + 1))
            all += generateJourney(eventId: eid, t0: randStart(),
                                   payment: wc(payments), segment: wc(segments),
                                   orderVal: wc(orderVals))
        }
        return all
    }

    private static func generateJourney(eventId: String, t0: Date,
                                         payment: String, segment: String,
                                         orderVal: String) -> [JEvent] {
        var rows: [JEvent] = []
        var t   = t0
        var sid = 1

        func add(_ step: String, _ lo: Int, _ hi: Int) {
            t = t.addingTimeInterval(TimeInterval(Int.random(in: lo...hi)))
            rows.append(JEvent(eventId: eventId, step: step, stepId: sid,
                               eventTime: t, meta1: payment,
                               meta2: segment, meta3: orderVal))
            sid += 1
        }

        add("Login", 5, 60)
        for _ in 0..<Int.random(in: 1...4) {
            add("Browse Catalog", 20, 300)
            if Double.random(in: 0..<1) < 0.65 {
                add("View Book Details", 20, 180)
                if Double.random(in: 0..<1) < 0.18 { add("Browse Catalog", 10, 90) }
            }
        }
        for _ in 0..<Int.random(in: 1...3) { add("Add to Basket", 5, 25) }
        if Double.random(in: 0..<1) < 0.72  { add("View Basket", 10, 90) }

        add("Checkout",               10,  45)
        add("Enter Shipping Address", 45, 240)
        add("Select Payment Method",  10,  35)

        var success = false

        if payment == "Bank Transfer" {
            add("Payment: Bank Transfer", 30, 120)
            for attempt in 0..<3 {
                add("Payment Processing", 180, 900)
                if Double.random(in: 0..<1) < 0.35 {
                    add("Payment Failed", 5, 15)
                    if attempt < 2 && Double.random(in: 0..<1) < 0.55 {
                        add("Payment Retry", 90, 480)
                        continue
                    }
                    return rows
                }
                success = true
                break
            }
        } else if payment == "PayPal" {
            add("Payment: PayPal",    10, 35)
            add("Payment Processing",  8, 25)
            if Double.random(in: 0..<1) < 0.03 { add("Payment Failed", 5, 10); return rows }
            success = true
        } else {
            add("Payment: Credit Card", 20, 90)
            add("Payment Processing",    5, 20)
            if Double.random(in: 0..<1) < 0.02 { add("Payment Failed", 5, 10); return rows }
            success = true
        }

        guard success else { return rows }

        add("Payment Confirmed", 5, 10)
        add("Order Confirmed",   5, 10)
        add("Warehouse Picking",  3_600,  28_800)
        add("Warehouse Packing",  1_800,   7_200)
        add("Shipped",            3_600,  86_400)
        add("Delivered",         86_400, 604_800)

        if Double.random(in: 0..<1) < returnRate {
            add("Return Initiated",  3_600, 604_800)
            add("Return Shipped",   86_400, 259_200)
            add("Return Received",  86_400, 604_800)
            add("Refund Processed",  3_600,  86_400)
        }

        return rows
    }

    // MARK: SQL builders

    static func createTableSQLs(schema: String) -> [String] {[
        "CREATE TABLE IF NOT EXISTS \"\(schema)\".PROJECTS (PROJECT_ID VARCHAR(100) NOT NULL PRIMARY KEY, TITLE VARCHAR(200) NOT NULL, DESCRIPTION VARCHAR(500))",
        "CREATE TABLE IF NOT EXISTS \"\(schema)\".METAS (PROJECT_ID VARCHAR(100) NOT NULL PRIMARY KEY, META_1_TITLE VARCHAR(200), META_2_TITLE VARCHAR(200), META_3_TITLE VARCHAR(200))",
        "CREATE TABLE IF NOT EXISTS \"\(schema)\".STEPS (PROJECT_ID VARCHAR(100) NOT NULL, STEP VARCHAR(200) NOT NULL, DESCRIPTION VARCHAR(500), BG_COLOR VARCHAR(50), FG_COLOR VARCHAR(50), SCORE DECIMAL(5,0), SHAPE VARCHAR(20), END_OF_PROCESS DECIMAL(1,0) DEFAULT 0, BELONGS_TO VARCHAR(200), PRIMARY KEY (PROJECT_ID, STEP))",
        "CREATE TABLE IF NOT EXISTS \"\(schema)\".JOURNEYS (PROJECT_ID VARCHAR(100) NOT NULL, EVENT_ID VARCHAR(200) NOT NULL, STEP VARCHAR(200) NOT NULL, STEP_ID DECIMAL(18,0), EVENT_TIME TIMESTAMP NOT NULL, META_1 VARCHAR(500), META_2 VARCHAR(500), META_3 VARCHAR(500))"
    ]}
    static func deleteProjectSQL(schema: String, sq: (String) -> String) -> String {
        "DELETE FROM \"\(schema)\".PROJECTS WHERE PROJECT_ID = '\(sq(projectId))'"
    }
    static func deleteMetasSQL(schema: String, sq: (String) -> String) -> String {
        "DELETE FROM \"\(schema)\".METAS WHERE PROJECT_ID = '\(sq(projectId))'"
    }
    static func deleteJourneysSQL(schema: String, sq: (String) -> String) -> String {
        "DELETE FROM \"\(schema)\".JOURNEYS WHERE PROJECT_ID = '\(sq(projectId))'"
    }
    static func insertProjectSQL(schema: String, sq: (String) -> String) -> String {
        "INSERT INTO \"\(schema)\".PROJECTS VALUES ('\(sq(projectId))', 'Online Bookstore', 'End-to-end order flow: login, browse, basket, checkout, payment, fulfilment, delivery, returns. Bank Transfer has known payment reliability issues.')"
    }
    static func insertMetasSQL(schema: String, sq: (String) -> String) -> String {
        "INSERT INTO \"\(schema)\".METAS VALUES ('\(sq(projectId))', 'Payment Method', 'Customer Segment', 'Order Value')"
    }

    private static let stepDefs: [(String, String, String, String, Int, String, Int, String)] = [
        ("Login",                  "Customer authenticates",                       "3498DB","FFFFFF",  0,"round",   0,"Customer Interaction"),
        ("Browse Catalog",         "Customer browses book listings",               "5DADE2","FFFFFF",  0,"round",   0,"Customer Interaction"),
        ("View Book Details",      "Customer views a single book page",            "85C1E9","FFFFFF",  0,"round",   0,"Customer Interaction"),
        ("Add to Basket",          "Customer adds a book to shopping basket",      "27AE60","FFFFFF",  5,"round",   0,"Customer Interaction"),
        ("View Basket",            "Customer reviews basket before checkout",      "2ECC71","FFFFFF",  0,"round",   0,"Customer Interaction"),
        ("Checkout",               "Customer initiates checkout flow",             "E67E22","FFFFFF",  0,"round",   0,"Purchase Process"),
        ("Enter Shipping Address", "Customer enters or confirms delivery address", "CA6F1E","FFFFFF",  0,"round",   0,"Purchase Process"),
        ("Select Payment Method",  "Customer chooses a payment method",            "D35400","FFFFFF",  0,"round",   0,"Purchase Process"),
        ("Payment: Credit Card",   "Credit card payment selected",                 "F0B27A","000000",  0,"round",   0,"Payment"),
        ("Payment: PayPal",        "PayPal payment selected",                      "F7DC6F","000000",  0,"round",   0,"Payment"),
        ("Payment: Bank Transfer", "Bank transfer — known reliability issues",     "C0392B","FFFFFF", -5,"round",   0,"Payment"),
        ("Payment Processing",     "Payment gateway processing the transaction",   "BDC3C7","000000",  0,"round",   0,"Payment"),
        ("Payment Failed",         "Transaction declined or timed out",            "E74C3C","FFFFFF",-10,"hex",     0,"Payment"),
        ("Payment Retry",          "Customer retries a failed payment",            "E59866","000000", -5,"round",   0,"Payment"),
        ("Payment Confirmed",      "Payment successfully authorised",              "1ABC9C","FFFFFF", 10,"stadium", 0,"Payment"),
        ("Order Confirmed",        "Order reference issued to customer",           "16A085","FFFFFF", 10,"stadium", 0,"Purchase Process"),
        ("Warehouse Picking",      "Books located and picked from shelves",        "8E44AD","FFFFFF",  0,"round",   0,"Fulfilment"),
        ("Warehouse Packing",      "Order packed and label printed",               "7D3C98","FFFFFF",  0,"round",   0,"Fulfilment"),
        ("Shipped",                "Package handed over to carrier",               "2980B9","FFFFFF",  5,"round",   0,"Fulfilment"),
        ("Delivered",              "Package confirmed as delivered",               "229954","FFFFFF", 15,"stadium", 1,"Fulfilment"),
        ("Return Initiated",       "Customer requests return authorisation",       "C0392B","FFFFFF",-10,"hex",     0,"Returns"),
        ("Return Shipped",         "Customer sends package back",                  "E74C3C","FFFFFF",  0,"round",   0,"Returns"),
        ("Return Received",        "Returned package received at warehouse",       "D98880","FFFFFF",  0,"round",   0,"Returns"),
        ("Refund Processed",       "Refund issued to original payment method",     "F1948A","000000", -5,"stadium", 1,"Returns"),
    ]

    static func insertStepsSQLs(schema: String, sq: (String) -> String) -> [String] {
        stepDefs.map { (name, desc, bg, fg, score, shape, eop, group) in
            "INSERT INTO \"\(schema)\".STEPS (PROJECT_ID, STEP, DESCRIPTION, BG_COLOR, FG_COLOR, SCORE, SHAPE, END_OF_PROCESS, BELONGS_TO) SELECT '\(sq(projectId))', '\(sq(name))', '\(sq(desc))', '\(bg)', '\(fg)', \(score), '\(shape)', \(eop), '\(sq(group))' WHERE NOT EXISTS (SELECT 1 FROM \"\(schema)\".STEPS WHERE PROJECT_ID = '\(sq(projectId))' AND STEP = '\(sq(name))')"
        }
    }

    private static let tsFormatter: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd HH:mm:ss"
        f.locale = Locale(identifier: "en_US_POSIX")
        return f
    }()

    static func insertJourneysSQL(schema: String, rows: [JEvent], sq: (String) -> String) -> String {
        let vals = rows.map { r in
            "('\(sq(projectId))', '\(sq(r.eventId))', '\(sq(r.step))', \(r.stepId), TIMESTAMP '\(tsFormatter.string(from: r.eventTime))', '\(sq(r.meta1))', '\(sq(r.meta2))', '\(sq(r.meta3))')"
        }.joined(separator: ",\n  ")
        return "INSERT INTO \"\(schema)\".JOURNEYS (PROJECT_ID, EVENT_ID, STEP, STEP_ID, EVENT_TIME, META_1, META_2, META_3) VALUES\n  \(vals)"
    }
}

// MARK: - Help PDF renderer

/// Renders help HTML to paginated PDF data.
///
/// On macOS the renderer drives `WKWebView.printOperation(with:)` — WebKit's own
/// supported print pipeline — into an A4 `NSPrintInfo` with `jobDisposition = .save`.
/// Unlike `createPDF` (which captures the whole document as a single, page-break-
/// ignoring continuous sheet), this honours the CSS `page-break-*` rules and yields
/// real A4 pages. A "Page X of N" footer is then stamped onto every page. This is
/// distinct from constructing an `NSPrintOperation(view:)` by hand — that trips
/// AppKit's `_validatePagination` assertion; `WKWebView.printOperation(with:)` does
/// not. No print panel is shown, so it stays within the App Sandbox.
///
/// On iOS (non-shipping path) it falls back to `createPDF`, which produces a single
/// continuous page.
@MainActor
private final class HelpPDFRenderer: NSObject, WKNavigationDelegate {
    private var webView: WKWebView?
    private var completion: ((Data?) -> Void)?
    private var selfRef: HelpPDFRenderer?   // keep alive until the PDF is ready
    #if os(macOS)
    private var hostWindow: NSWindow?       // offscreen host required for printing
    #endif

    static func render(html: String, completion: @escaping (Data?) -> Void) {
        let renderer = HelpPDFRenderer()
        renderer.selfRef    = renderer
        renderer.completion = completion
        // A4 page width in points; WebKit reflows the content to this width.
        let wv = WKWebView(frame: CGRect(x: 0, y: 0, width: 595, height: 842))
        renderer.webView = wv
        wv.navigationDelegate = renderer
        wv.loadHTMLString(html, baseURL: nil)
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        #if os(macOS)
        // Let WebKit settle layout (embedded base64 images) before printing.
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) { [weak self] in
            self?.renderPaginatedPDF(from: webView)
        }
        #else
        webView.createPDF(configuration: WKPDFConfiguration()) { [weak self] result in
            switch result {
            case .success(let data): self?.finish(data)
            case .failure:           self?.finish(nil)
            }
        }
        #endif
    }

    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        finish(nil)
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        finish(nil)
    }

    private func finish(_ data: Data?) {
        completion?(data)
        completion = nil
        webView    = nil
        #if os(macOS)
        hostWindow = nil
        #endif
        selfRef    = nil
    }

    #if os(macOS)
    // A4 in points.
    private static let a4 = NSSize(width: 595.28, height: 841.89)
    private static let sideMargin: CGFloat   = 54    // top / left / right
    private static let footerMargin: CGFloat = 64    // bottom — leaves room for the page number

    private var savedURL: URL?   // PDF destination, read back in the didRun callback

    /// Prints the loaded web view into a paginated A4 PDF, then stamps page numbers.
    private func renderPaginatedPDF(from webView: WKWebView) {
        let url = URL(fileURLWithPath: NSTemporaryDirectory())
            .appendingPathComponent("help-\(UUID().uuidString).pdf")
        savedURL = url

        let info = NSPrintInfo()
        info.paperSize    = Self.a4
        info.topMargin    = Self.sideMargin
        info.leftMargin   = Self.sideMargin
        info.rightMargin  = Self.sideMargin
        info.bottomMargin = Self.footerMargin
        info.horizontalPagination = .automatic
        info.verticalPagination   = .automatic
        info.isHorizontallyCentered = false
        info.isVerticallyCentered   = false
        info.jobDisposition = .save
        info.dictionary()[NSPrintInfo.AttributeKey.jobSavingURL] = url

        // The web view must have a real frame inside a window for WebKit to lay out
        // its printing view.
        let window = NSWindow(contentRect: CGRect(origin: .zero, size: Self.a4),
                              styleMask: [.borderless],
                              backing: .buffered, defer: false)
        window.contentView = webView
        hostWindow = window

        let op = webView.printOperation(with: info)
        op.showsPrintPanel    = false
        op.showsProgressPanel = false

        // Run asynchronously: WebKit establishes the WKPrintingView frame on a later
        // run-loop turn. A synchronous run() races that and fails with
        // "view's frame was not initialized properly before knowsPageRange:".
        op.runModal(for: window,
                    delegate: self,
                    didRun: #selector(printOperationDidRun(_:success:contextInfo:)),
                    contextInfo: nil)
    }

    @objc private func printOperationDidRun(_ operation: NSPrintOperation,
                                            success: Bool,
                                            contextInfo: UnsafeMutableRawPointer?) {
        let url = savedURL
        savedURL = nil
        guard success, let url, let data = try? Data(contentsOf: url) else {
            finish(nil)
            return
        }
        try? FileManager.default.removeItem(at: url)
        finish(Self.stampPageNumbers(in: data) ?? data)
    }

    /// Overlays a centred "Page X of N" footer on every page of the PDF.
    private static func stampPageNumbers(in pdfData: Data) -> Data? {
        guard let provider = CGDataProvider(data: pdfData as CFData),
              let source   = CGPDFDocument(provider) else { return nil }
        let pageCount = source.numberOfPages
        guard pageCount > 0 else { return nil }

        let output = NSMutableData()
        guard let consumer = CGDataConsumer(data: output as CFMutableData) else { return nil }
        var defaultBox = CGRect(origin: .zero, size: a4)
        guard let ctx = CGContext(consumer: consumer, mediaBox: &defaultBox, nil) else { return nil }

        let attrs: [NSAttributedString.Key: Any] = [
            .font: NSFont.systemFont(ofSize: 8.5),
            .foregroundColor: NSColor(white: 0.55, alpha: 1)
        ]

        for i in 1...pageCount {
            guard let page = source.page(at: i) else { continue }
            var box = page.getBoxRect(.mediaBox)
            ctx.beginPage(mediaBox: &box)
            ctx.drawPDFPage(page)

            let text = NSAttributedString(string: "Page \(i) of \(pageCount)", attributes: attrs)
            let textSize = text.size()
            let nsCtx = NSGraphicsContext(cgContext: ctx, flipped: false)
            NSGraphicsContext.saveGraphicsState()
            NSGraphicsContext.current = nsCtx
            text.draw(at: CGPoint(x: box.midX - textSize.width / 2, y: 28))
            NSGraphicsContext.restoreGraphicsState()

            ctx.endPage()
        }
        ctx.closePDF()
        return output as Data
    }
    #endif
}

// MARK: - Print Document

private enum HelpPrintDocument {

    static func precomputeIcons() -> [String: String] {
        var result: [String: String] = [:]
        for t in HelpTopic.all {
            result[t.id] = symbolDataURI(t.icon, color: t.color, size: 48)
        }
        return result
    }

    @MainActor
    static func renderLogo() -> String {
        #if os(iOS)
        let renderer = ImageRenderer(content: LenticularisLogoView(120))
        renderer.scale = 2
        guard let uiImage = renderer.uiImage,
              let pngData = uiImage.pngData() else { return "" }
        return pngData.base64EncodedString()
        #else
        let nsRenderer = ImageRenderer(content: LenticularisLogoView(120))
        nsRenderer.scale = 2
        guard let nsImage = nsRenderer.nsImage,
              let tiff = nsImage.tiffRepresentation,
              let rep = NSBitmapImageRep(data: tiff),
              let png = rep.representation(using: .png, properties: [:]) else { return "" }
        return png.base64EncodedString()
        #endif
    }

    static func buildHTML(icons: [String: String], logoBase64: String) -> String {
        let dateStr = Date().formatted(date: .long, time: .omitted)

        var tocRows = ""
        for (i, t) in HelpTopic.all.enumerated() {
            let icon: String
            if let uri = icons[t.id], !uri.isEmpty {
                icon = "<img class=\"toc-ic\" src=\"\(uri)\" width=\"16\" height=\"16\">"
            } else {
                icon = "<span class=\"toc-dot\" style=\"background:\(hex(t.color));\"></span>"
            }
            tocRows += "<li><a href=\"#topic-\(t.id)\">\(icon)<span class=\"toc-num\">\(i + 1).</span>\(esc(t.title))</a></li>\n"
        }

        var chapters = ""
        for (i, t) in HelpTopic.all.enumerated() { chapters += topicHTML(t, index: i, icons: icons) }

        let coverLogoHTML = logoBase64.isEmpty
            ? "<p class=\"cover-bird\">🌥️</p>"
            : "<img class=\"cover-logo\" src=\"data:image/png;base64,\(logoBase64)\" width=\"120\" height=\"120\" alt=\"\">"

        return """
        <!DOCTYPE html>
        <html lang="en">
        <head>
          <meta charset="UTF-8">
          <style>\(css)</style>
        </head>
        <body>
        <div class="cover">
          \(coverLogoHTML)
          <h1>Process Mining Demonstrator</h1>
          <div class="cover-rule"></div>
          <h2>User Documentation</h2>
          <p class="cover-date">\(dateStr)</p>
        </div>
        <div class="toc">
          <div class="toc-hd">Table of Contents</div>
          <ul>\(tocRows)</ul>
        </div>
        \(chapters)
        </body></html>
        """
    }

    // MARK: CSS  (no flexbox — UIMarkupTextPrintFormatter lays out flex synchronously)

    private static let css = """
    /* Page margins are supplied by NSPrintInfo on the print path; keep CSS at 0
       so the two don't stack into an oversized margin. */
    @page { margin: 0; }
    * { margin: 0; padding: 0; }
    body {
      font-family: -apple-system, 'Helvetica Neue', Helvetica, Arial, sans-serif;
      font-size: 11pt; color: #1c1c1e; background: #fff; line-height: 1.6;
    }

    /* ── Cover ── */
    .cover {
      text-align: center;
      padding: 160pt 40pt 60pt;
      page-break-after: always; break-after: page;
    }
    .cover-bird { font-size: 60pt; display: block; margin-bottom: 20pt; }
    .cover-logo { width: 120pt; height: 120pt; display: block; margin: 0 auto 20pt; }
    .cover h1   { font-size: 26pt; font-weight: 800; color: #1c1c1e; margin-bottom: 0; }
    .cover-rule { width: 50pt; height: 3pt; background: #007AFF; margin: 16pt auto; }
    .cover h2   { font-size: 14pt; font-weight: 300; color: #3a3a3c; margin-bottom: 32pt; }
    .cover-date { font-size: 9pt; color: #8e8e93; }

    /* ── TOC ── */
    .toc { padding-bottom: 20pt; page-break-after: always; break-after: page; }
    .toc-hd { font-size: 18pt; font-weight: 800; color: #1c1c1e;
              border-bottom: 2pt solid #e5e5ea; padding-bottom: 10pt; margin-bottom: 14pt; }
    .toc ul { list-style: none; }
    .toc li { border-bottom: 1pt solid #f2f2f7; padding: 6pt 0; }
    .toc a  { text-decoration: none; color: #1c1c1e; font-size: 11pt; }
    .toc-dot { display: inline-block; width: 9pt; height: 9pt; border-radius: 50%;
               vertical-align: middle; margin-right: 7pt; }
    .toc-ic  { vertical-align: middle; margin-right: 7pt; }
    .toc-num { color: #8e8e93; margin-right: 5pt; }

    /* ── Topic: one per page ── */
    .topic { page-break-before: always; break-before: page; padding-bottom: 20pt; }

    /* ── Chapter header (table layout, no flex) ── */
    .topic-hd {
      border-left: 5pt solid #ccc;
      padding: 14pt 16pt;
      margin-bottom: 20pt;
      page-break-inside: avoid; break-inside: avoid;
      overflow: hidden;
    }
    .hd-icon { float: left; width: 46pt; height: 46pt; margin-right: 14pt;
               border-radius: 10pt; text-align: center; line-height: 46pt;
               font-size: 20pt; font-weight: 800; }
    .hd-icon img { width: 28pt; height: 28pt; vertical-align: middle; }
    .chap       { font-size: 8pt; font-weight: 700; text-transform: uppercase;
                  letter-spacing: 0.6pt; margin-bottom: 3pt; }
    .topic-name { font-size: 19pt; font-weight: 800; color: #1c1c1e; line-height: 1.15; }
    .topic-sub  { font-size: 10pt; color: #636366; margin-top: 2pt; }
    .hd-clear   { clear: both; }

    /* ── Sections ── */
    .sec { margin-bottom: 2pt; }
    h2 {
      font-size: 12pt; font-weight: 700; color: #1c1c1e;
      margin: 16pt 0 7pt; padding-bottom: 4pt; border-bottom: 1pt solid #e5e5ea;
      page-break-after: avoid; break-after: avoid;
    }
    p  { margin-bottom: 6pt; }
    ul { margin: 4pt 0 7pt 16pt; }
    li { margin-bottom: 3pt; page-break-inside: avoid; break-inside: avoid; }

    /* ── Callouts (table layout) ── */
    .callout {
      display: table; width: 100%;
      padding: 8pt 10pt; margin: 6pt 0;
      page-break-inside: avoid; break-inside: avoid;
    }
    .tip  { background: #fffbe6; }
    .warn { background: #fff3e0; }
    .co-ic { display: table-cell; width: 18pt; font-size: 12pt; vertical-align: top; padding-top: 1pt; }
    .co-bd { display: table-cell; vertical-align: top; font-size: 10pt; }
    .co-bd strong { display: block; margin-bottom: 2pt; }

    /* ── Definitions (table layout) ── */
    .def-row { display: table; width: 100%; padding: 5pt 0;
               border-bottom: 1pt solid #f2f2f7;
               page-break-inside: avoid; break-inside: avoid; }
    .term   { display: table-cell; width: 130pt; font-weight: 600;
              vertical-align: top; padding-right: 8pt; }
    .detail { display: table-cell; color: #3c3c43; vertical-align: top; }

    /* ── Code ── */
    pre {
      background: #f2f2f7; padding: 9pt 11pt; margin: 6pt 0;
      page-break-inside: avoid; break-inside: avoid;
    }
    code {
      font-family: 'Menlo', 'Courier New', monospace;
      font-size: 8pt; white-space: pre-wrap; word-break: break-all;
    }
    """

    // MARK: Helpers

    private static func symbolDataURI(_ name: String, color: Color, size: CGFloat) -> String {
        #if os(iOS)
        let cfg = UIImage.SymbolConfiguration(pointSize: size, weight: .semibold)
        guard let img = UIImage(systemName: name, withConfiguration: cfg)?
                .withTintColor(UIColor(color), renderingMode: .alwaysOriginal),
              let png = img.pngData()
        else { return "" }
        return "data:image/png;base64,\(png.base64EncodedString())"
        #else
        let cfg = NSImage.SymbolConfiguration(pointSize: size, weight: .semibold)
        guard let symbol = NSImage(systemSymbolName: name, accessibilityDescription: nil)?
                .withSymbolConfiguration(cfg) else { return "" }
        let target = symbol.size
        let tinted = NSImage(size: target)
        tinted.lockFocus()
        NSColor(color).set()
        let rect = NSRect(origin: .zero, size: target)
        symbol.draw(in: rect)
        rect.fill(using: .sourceAtop)
        tinted.unlockFocus()
        guard let tiff = tinted.tiffRepresentation,
              let rep = NSBitmapImageRep(data: tiff),
              let png = rep.representation(using: .png, properties: [:]) else { return "" }
        return "data:image/png;base64,\(png.base64EncodedString())"
        #endif
    }

    private static func hex(_ color: Color) -> String {
        let c = color.rgbaComponents
        return String(format: "#%02X%02X%02X", Int(c.red * 255), Int(c.green * 255), Int(c.blue * 255))
    }

    private static func esc(_ s: String) -> String {
        s.replacingOccurrences(of: "&", with: "&amp;")
         .replacingOccurrences(of: "<", with: "&lt;")
         .replacingOccurrences(of: ">", with: "&gt;")
    }

    private static func blockHTML(_ block: HelpBlock) -> String {
        switch block {
        case .paragraph(let t):
            return "<p>\(esc(t))</p>\n"
        case .tip(let t):
            return "<div class=\"callout tip\"><span class=\"co-ic\">💡</span><span class=\"co-bd\"><strong>Tip</strong><br>\(esc(t))</span></div>\n"
        case .warning(let t):
            return "<div class=\"callout warn\"><span class=\"co-ic\">⚠️</span><span class=\"co-bd\"><strong>Warning</strong><br>\(esc(t))</span></div>\n"
        case .bullets(let items):
            return "<ul>\n" + items.map { "<li>\(esc($0))</li>" }.joined(separator: "\n") + "\n</ul>\n"
        case .definition(let term, let detail):
            return "<div class=\"def-row\"><span class=\"term\">\(esc(term))</span><span class=\"detail\">\(esc(detail))</span></div>\n"
        case .code(let t):
            return "<pre><code>\(esc(t))</code></pre>\n"
        }
    }

    private static func topicHTML(_ topic: HelpTopic, index: Int, icons: [String: String]) -> String {
        let h   = hex(topic.color)
        var out = "<div class=\"topic\" id=\"topic-\(topic.id)\">\n"
        out += "<div class=\"topic-hd\" style=\"border-left-color:\(h);background:\(h)11;\">"
        if let uri = icons[topic.id], !uri.isEmpty {
            out += "<div class=\"hd-icon\" style=\"background:\(h)22;\"><img src=\"\(uri)\" width=\"28\" height=\"28\"></div>"
        } else {
            out += "<div class=\"hd-icon\" style=\"background:\(h)22;color:\(h);\">\(index + 1)</div>"
        }
        out += "<div class=\"chap\" style=\"color:\(h);\">Chapter \(index + 1)</div>"
        out += "<div class=\"topic-name\">\(esc(topic.title))</div>"
        out += "<div class=\"topic-sub\">\(esc(topic.subtitle))</div>"
        out += "<div class=\"hd-clear\"></div></div>\n"
        for sec in topic.sections {
            out += "<div class=\"sec\"><h2>\(esc(sec.heading))</h2>\n"
            for block in sec.body { out += blockHTML(block) }
            out += "</div>\n"
        }
        out += "</div>\n"
        return out
    }
}

// MARK: - Process Mining Demonstrator cloud logo

struct LenticularisLogoView: View {
    let size: CGFloat
    init(_ size: CGFloat = 72) { self.size = size }

    var body: some View {
        Canvas { ctx, sz in
            let cx = sz.width / 2
            let cloudTop = sz.height * 0.10
            let cloudBottom = sz.height * 0.68

            // Four stacked lenticular discs — widest at bottom, narrowing upward
            let discs: [(wf: CGFloat, hf: CGFloat, yf: CGFloat, bright: CGFloat)] = [
                (0.98, 0.20, 1.00, 0.88),
                (0.76, 0.17, 0.73, 0.91),
                (0.54, 0.14, 0.50, 0.94),
                (0.32, 0.11, 0.30, 0.97),
            ]

            for disc in discs {
                let w = sz.width  * disc.wf
                let h = sz.height * disc.hf
                let y = cloudTop + (cloudBottom - cloudTop) * disc.yf
                let rect = CGRect(x: cx - w / 2, y: y - h / 2, width: w, height: h)
                // Disc fill: pale blue-grey, lighter toward the top
                ctx.fill(Path(ellipseIn: rect),
                          with: .color(Color(hue: 0.59, saturation: 0.18,
                                             brightness: disc.bright, opacity: 0.82)))
                // Subtle highlight arc along the upper edge
                var shine = Path(ellipseIn: rect.insetBy(dx: w * 0.06, dy: h * 0.12))
                ctx.stroke(shine,
                            with: .color(.white.opacity(0.35)),
                            lineWidth: 1.2)
            }

            // Glider silhouette — plan view, centred below the cloud stack
            let gy  = sz.height * 0.86
            let gbl = sz.width  * 0.38   // body length
            let gbh = sz.height * 0.045  // body height
            let gws = sz.width  * 0.54   // half-wingspan (total = 2 × gws)

            // Fuselage
            let bodyRect = CGRect(x: cx - gbl / 2, y: gy - gbh / 2, width: gbl, height: gbh)
            ctx.fill(Path(ellipseIn: bodyRect),
                      with: .color(Color(hue: 0.59, saturation: 0.55, brightness: 0.45, opacity: 0.80)))

            // Wings — swept back, thin chevron
            var wings = Path()
            let wRootY = gy
            let wTipY  = gy + sz.height * 0.055
            wings.move(to:    CGPoint(x: cx - gbl * 0.12, y: wRootY - gbh * 0.4))
            wings.addLine(to: CGPoint(x: cx - gws,        y: wTipY))
            wings.addLine(to: CGPoint(x: cx - gws + sz.width * 0.04, y: wTipY))
            wings.addLine(to: CGPoint(x: cx,              y: wRootY + gbh * 0.5))
            wings.addLine(to: CGPoint(x: cx + gws - sz.width * 0.04, y: wTipY))
            wings.addLine(to: CGPoint(x: cx + gws,        y: wTipY))
            wings.addLine(to: CGPoint(x: cx + gbl * 0.12, y: wRootY - gbh * 0.4))
            wings.closeSubpath()
            ctx.fill(wings,
                      with: .color(Color(hue: 0.59, saturation: 0.55, brightness: 0.45, opacity: 0.80)))
        }
        .frame(width: size, height: size)
    }
}
