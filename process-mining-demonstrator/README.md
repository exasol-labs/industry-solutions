<!--
industry: Cross-Industry
status: demo
-->

# Process Mining Demonstrator

A native **macOS** process-mining application for **Apple Silicon** Macs. Process Mining Demonstrator connects to an [Exasol](https://www.exasol.com) database, reads a journey/event log, and renders how real cases flow through your business processes as an interactive map — with rich filtering, A/B comparison, Monte Carlo simulation, conformance checking, and optional AI-assisted documentation.

> Built with SwiftUI for Apple Silicon Macs running macOS. iOS and iPadOS are not supported.

> **Purpose — Demo & Education only.**
> Process Mining Demonstrator is a pure demonstrator for new and emerging use cases of the Exasol Analytical Database that are not yet in the focus of a typical Exasol deployment: **log file analysis and process mining**. It is intended exclusively for demo and educational purposes and is not designed or validated for production use.

---

## Table of contents

- [Features](#features)
- [Requirements](#requirements)
- [Building with Xcode](#building-with-xcode)
- [Database schema](#database-schema)
- [Getting started](#getting-started)
- [Configuration](#configuration)
- [Running the tests](#running-the-tests)
- [Project structure](#project-structure)
- [Architecture notes](#architecture-notes)
- [Exporting the documentation](#exporting-the-documentation)
- [Troubleshooting](#troubleshooting)
- [License](#license)

---

## **What Is Process Mining and why it matters?**
Every transaction in your ERP, CRM, or ticketing system leaves a trace: a case ID, an activity, a timestamp. Process mining reads those event logs and reconstructs how your processes actually run — not how the flowchart says they should.
The gap between the two is where the money sits. A purchase-to-pay process designed with five steps often has forty variants in practice: rework loops, manual workarounds, orders bouncing between departments. Process mining surfaces those variants, counts them, and attaches cost and duration to each.
For business analysts, this replaces workshop guesswork with evidence. Rather than interviewing ten people about how they handle exceptions, you see the exceptions, ranked by frequency and impact. Which supplier causes the most payment delays? Does that extra approval step reduce errors, or just add four days?
For process owners, the payoff is decision confidence. Quantify a bottleneck before investing in automation, then measure whether the fix worked. Conformance checking flags compliance breaches — an invoice approved by the person who raised it — across every case, not a sample.
Process mining doesn't replace domain expertise. It gives that expertise a factual baseline, so effort targets the few variants driving most of the delay.

### From Transactions to Traces: Log Data as a New Source for Exasol
Analytical workloads are usually fed by transactional systems — orders, invoices, ledger postings — which describe state. Process mining instead consumes event logs from ERP change tables, audit trails, and application journals: append-only, high-volume, semi-structured. Reconstructing process paths requires self-joins, window functions, and sequence analysis over hundreds of millions of rows, where Exasol's in-memory columnar engine keeps exploration interactive.
***Note: this application is intended for demonstration and educational purposes only, and is not a production-ready process mining solution.***

## Features

### Process map
Every path between process steps rendered as an interactive directly-follows graph.
Nodes display step names, descriptions, colour coding, shapes (stadium / round /
hex / circle), score badges, and end-of-process markers. Node groups can be
expanded or collapsed; layout is persisted per project.

### A / B Comparison
Load two independent filter states (Chart A / Chart B) side-by-side. Each slot
has its own metric selector, journey count, and duration KPIs. A **Process
Similarity** score (Q-metric) compares the two variant distributions.

### Filtering & filter presets
- Date range, included / excluded steps, journey step-count bounds, journey-time
  bounds, score range, and up to three free-text meta attributes.
- Named **Filter Groups** let you save, rename, and re-apply any combination of
  filters with a single tap.

### Statistics & KPIs
Journey counts, duration distribution histogram, time-series chart (daily / weekly
/ monthly), top journey-path variants, step-traffic breakdown, and a **Process
Goodness** quality score.

### Conformance & Happy Path
Define named ideal step sequences, each with optional named branches. A weighted
edge-coverage score (0–100 %) measures how closely the actual variant distribution
follows the defined path(s). Paths are persisted per project.

### Target Process / Norms
Overlay user-defined target values on any transition metric (count, avg time, min
time, max time, std dev). Norms are stored per project and per metric, with
automatic migration from the legacy single-metric format.

### Monte Carlo Simulation
Simulate a synthetic event log from the observed process graph using a Markov
model — no database writes required.

| Parameter | Default | Description |
|---|---|---|
| Journey count | 200 | Simulated cases to produce |
| Start date | now | Earliest possible arrival |
| Avg inter-arrival | 2 h | Mean of the Poisson arrival process |
| Max steps per journey | 60 | Guard against infinite loops |
| Excluded steps | — | Removed before building the Markov model |
| Required steps | — | Journeys not visiting all required steps are discarded |

Outputs: event log, cycle-time histogram, variant table, directly-follows graph.
Results can be exported as CSV.

**Engine highlights**

- Start steps are identified from the **original** graph (in-degree / out-degree
  ratio < 0.2), preventing excluded-step artefacts from becoming false entry points.
- BFS reachability prunes any steps that become disconnected after exclusions.
- Edge durations are sampled from fitted lognormal distributions via the Box–Muller
  transform; a minimum of 60 s is enforced per transition.

### Sampling
Create up to three named sample sets (Sample 1 – 3) from the original data:

| Strategy | Description |
|---|---|
| Random | Uniform random journey selection |
| Temporal Stratified | Proportional selection across equal time periods |
| Path Diversity | Coverage-maximising selection across journey variants |

Sample sets are stored in an Exasol `SAMPLE_SET` column and can be selected
independently for the A-chart and B-chart slots.

### AI Documentation
Any OpenAI-compatible endpoint (local or cloud). A customisable prompt template
is sent together with the current dataset; the response is rendered as Markdown
and can be exported as PDF. Per-project prompt templates are persisted in
UserDefaults.

### Process Notes
Sticky-note annotations attached to any process node or edge. Each note stores
the author, last-edited-by, the full filter context at creation time, and an
optional shared flag. Notes are persisted in a `NOTES` table in the Exasol
database (auto-created on first use if the user has `CREATE TABLE` permission).

### Connection management
Server definitions and connection profiles are managed separately:
- **Database servers** — host, port, TLS settings, certificate verification mode,
  optional SHA-256 fingerprint pin, RSA key-size minimum. Passwords stored in the
  system Keychain.
- **LLM servers** — OpenAI-compatible base URL, model name, optional API key.
- **Connection profiles** — lightweight pairings of a database server with an
  optional LLM server. Automatic migration from the legacy single-profile format.

### Backup & Restore
Export / import all device settings as a single JSON file with optional AES-256-GCM
encryption (PBKDF2-derived key, random 16-byte salt, 12-byte nonce). Includes
connection definitions, filter groups, happy paths, target norms, LLM prompt
templates, and app preferences. Passwords and API keys are included or excluded per
your choice.

### Security
- **Biometric / passcode lock** — optional Face ID, Touch ID, or passcode gate on
  every foreground return. Locks automatically on background; unlocks automatically
  on foreground.
- **First-launch legal disclaimer** — must be accepted before the app is usable.

### Splash screen & About
A splash screen shown on launch (auto-closes after 5 s) doubles as the **About**
panel available from the application menu. It displays the app name, version, and
the demo-use disclaimer.

### Help & documentation
A floating, draggable, resizable help panel accessible via a keyboard shortcut.
The complete documentation can be exported as a **paginated A4 PDF** (cover,
table of contents, chapter pages, page numbers).

---

## Requirements

| Item              | Version / Notes                                                       |
| ----------------- | --------------------------------------------------------------------- |
| macOS             | 26.6 or later — Apple Silicon only                                    |
| Xcode             | 26 or later                                                           |
| Swift             | 5 language mode                                                       |
| Database          | An Exasol instance reachable from the Mac (see below)                 |
| LLM (optional)    | Any OpenAI-compatible endpoint (local or cloud) for AI Documentation  |

The app depends on the **SwiftExasolConnector** Swift package, which provides the
Exasol WebSocket client. The package is available at
<https://github.com/exasol-labs/exa-connector-for-swift-on-mac>. It is referenced
as a local Swift package; make sure it is present (and resolvable in Xcode) before
building.

---

## Building with Xcode

Process Mining Demonstrator is compiled and run directly from Xcode. No pre-built
binary is distributed.

**Prerequisites**

- macOS 26 or later on an Apple Silicon Mac
- Xcode 26 or later (download from the Mac App Store or developer.apple.com)

**Steps**

1. Clone the repository, including the `SwiftExasolConnector` subpackage.
2. Open **`Process Mining Demonstrator.xcodeproj`** in Xcode.
3. Wait for Xcode to resolve Swift package dependencies (bottom status bar shows progress).
4. In the scheme selector, choose **Process Mining Demonstrator** and **My Mac** as the run destination.
5. Press **⌘R** (or **Product → Run**) to build and launch the app.

You can also build from the command line:

```sh
xcodebuild \
  -project "Process Mining Demonstrator.xcodeproj" \
  -scheme  "Process Mining Demonstrator" \
  -destination 'platform=macOS' \
  build
```

---

## Database schema

Process Mining Demonstrator reads from four tables — **PROJECTS**, **JOURNEYS**, **STEPS**, and **METAS** — all of which are required. A **NOTES** table is created automatically on first use if the connecting user has `CREATE TABLE` permission. All table and column names are case-insensitive in Exasol.

```sql
-- Required: one row per process-mining project
CREATE TABLE PROJECTS (
  PROJECT_ID  VARCHAR(100) NOT NULL PRIMARY KEY,
  TITLE       VARCHAR(200) NOT NULL,
  DESCRIPTION VARCHAR(500)
);

-- Required: the event log — one row per activity within a journey/case
CREATE TABLE JOURNEYS (
  PROJECT_ID  VARCHAR(100) NOT NULL,        -- → PROJECTS.PROJECT_ID
  EVENT_ID    VARCHAR(200) NOT NULL,        -- one journey = all rows sharing an EVENT_ID
  STEP        VARCHAR(200) NOT NULL,        -- activity name → a node in the map
  STEP_ID     DECIMAL(18,0),               -- tie-breaker when EVENT_TIME is equal
  EVENT_TIME  TIMESTAMP    NOT NULL,        -- orders steps; drives date filters
  META_1      VARCHAR(500),                -- optional case-level attributes
  META_2      VARCHAR(500),
  META_3      VARCHAR(500)
);

-- Required: visual/semantic config per step (the in-app Step Editor writes here)
CREATE TABLE STEPS (
  PROJECT_ID      VARCHAR(100) NOT NULL,
  STEP            VARCHAR(200) NOT NULL,
  DESCRIPTION     VARCHAR(500),
  BG_COLOR        VARCHAR(50),             -- CSS colour name or 6-digit hex (e.g. FF8000)
  FG_COLOR        VARCHAR(50),
  SCORE           DECIMAL(5,0),            -- −999…999, shown as a badge
  SHAPE           VARCHAR(20),             -- stadium (default), round, hex, circle
  END_OF_PROCESS  DECIMAL(1,0) DEFAULT 0,  -- 1 = terminal state
  BELONGS_TO      VARCHAR(200),            -- optional grouping label
  PRIMARY KEY (PROJECT_ID, STEP)
);

-- Required: display names for the three META columns
CREATE TABLE METAS (
  PROJECT_ID    VARCHAR(100) NOT NULL PRIMARY KEY,
  META_1_TITLE  VARCHAR(200),
  META_2_TITLE  VARCHAR(200),
  META_3_TITLE  VARCHAR(200)
);
```

For best performance, index `JOURNEYS (PROJECT_ID, EVENT_TIME)` and
`JOURNEYS (PROJECT_ID, EVENT_ID)`.

> No Exasol instance yet? The in-app **Help → Getting Exasol** chapter covers the
> free Community Edition and a local Docker setup, and **Help → Demo Data** can
> generate a sample bookstore dataset.

---

## Getting started

1. Build and run the app following the steps in [Building with Xcode](#building-with-xcode).
2. On first launch, open the sidebar's **Connections** section to add a database connection.
3. Select a project from the list to start exploring your process data.

---

## Configuration

### Database connection

Add a connection in the sidebar with host, port (default **8563**), username,
password, and schema. TLS options include certificate verification and an
optional SHA-256 fingerprint pin. Passwords are stored in the macOS Keychain.

### AI Documentation (optional)

Each connection profile can define an LLM **server URL**, **API key**, and
**model**. With these set, the AI Documentation view sends the current,
filtered transition dataset to the model and renders a structured report you can
export as PDF. Without them, every other feature still works.

---

## Running the tests

The project ships two test targets:

| Target | Framework | What it covers |
|---|---|---|
| `Process Mining DemonstratorTests` | Swift Testing | Pure model & simulation logic — no database needed |
| `Process Mining DemonstratorUITests` | XCUIAutomation | App launch and main-window smoke tests |

Run everything from Xcode with **⌘U**, or from the command line:

```sh
xcodebuild \
  -project "Process Mining Demonstrator.xcodeproj" \
  -scheme  "Process Mining Demonstrator" \
  -destination 'platform=macOS' \
  test
```

All unit tests are deterministic and require no Exasol connection.

> **One-time setup for the UI tests:** select the
> **Process Mining DemonstratorUITests** target → **General** →
> **Target to Be Tested** → **Process Mining Demonstrator**.
> macOS UI tests also require granting the test runner **Accessibility/Automation**
> permission the first time they run.

### ModelLogicTests

Pure unit tests for value-type model logic.

| Test | What it covers |
|---|---|
| `timeGranularityPicksBucketBySpan` | `TimeGranularity.auto` returns `.day` / `.week` / `.month` by date span |
| `onlyTimeMetricsAreTimeBased` | `TransitionMetric.isTimeBased` is false only for `.count` |
| `transitionExposesTheRightMetricValue` | `ProcessTransition.metricValue(for:)` maps each metric correctly |
| `processGraphReportsMaxima` | `maxOccurrences` and `maxValue(for:)` return the correct maxima |
| `emptyProcessGraphFallsBackToOne` | Empty graph never returns 0 for max (prevents division-by-zero) |
| `happyPathDecodesLegacyJSONWithoutBranches` | Backward-compatible decode when `branches` key is absent |
| `happyPathRoundTripsBranches` | `HappyPath` with branches encodes and decodes correctly |
| `databaseServerHasSaneDefaultsAndRoundTrips` | Default port 8563, cert mode "verify", full Codable round-trip |
| `llmServerRoundTrips` | `LLMServer` encodes and decodes correctly |
| `connectionProfileIsAPairingAndRoundTrips` | Profile starts with nil server IDs; round-trips correctly |
| `legacyProfileSplitsIntoServersAndPairing` | Legacy flat profile is split into DB server + LLM server + pairing |
| `legacyProfileWithoutLLMHasNoLLMServer` | DB-only legacy profile produces no `LLMServer` |
| `noteTargetEdgeRoundTrips` | `NoteTarget.edge` encodes, decodes, and has the right `displayName` |
| `noteTargetNodeRoundTrips` | `NoteTarget.node` encodes, decodes, and `isNode` is true |
| `errorAlertWithRetryExposesSecondaryAction` | Retry closure fires correctly; secondary cancel button present |
| `errorAlertWithoutRetryIsInformational` | Alert without retry has a single OK button and no secondary |
| `colorParsesAndReproducesHex` | Hex string round-trips; named colours resolve to SwiftUI constants |

### SimulationEngineTests

18 tests for `SimulationEngine` and its `buildGraph` helper. Two fixture graphs
are used throughout:

- **Linear** — `A → B → C` (C is `endOfProcess`): every journey visits exactly
  three steps.
- **Fork** — `A → B → C` and `A → D → C` with equal weights: journeys split
  across two paths.

| Test | What it covers |
|---|---|
| `emptyGraphReturnsEmptyResult` | Empty `ProcessGraph` input → zero-journey `SimulationResult` |
| `linearGraphProducesRequestedJourneyCount` | `totalJourneys` and `cycleTimes.count` match the requested count |
| `linearJourneyVisitsEachStepExactlyOnce` | Linear A→B→C produces exactly 3 events per journey |
| `eventsAreChronologicallyOrderedWithinJourney` | Timestamps within each `journeyId` are monotonically increasing |
| `cycleTimesAreAllPositive` | Every sampled cycle time is > 0 |
| `statisticsAreConsistentWithCycleTimes` | `min`, `max`, `avg`, `stdDev` match direct computation over `cycleTimes` |
| `variantPercentagesSumToHundred` | Variant percentages sum to exactly 100 % |
| `variantCountsSumToTotalJourneys` | Sum of variant counts equals `totalJourneys` |
| `variantsAreSortedByCountDescending` | Variants array is sorted highest-count first |
| `excludedStepNeverAppearsInEvents` | Excluding step D removes it from all events; all journeys still generated |
| `excludingAllTransitionsFromStartReturnsEmpty` | Excluding the only intermediate step → no valid path → empty result |
| `requiredStepThatIsNeverVisitedFiltersAllJourneys` | Requiring a non-existent step drops all journeys → empty result |
| `requiredStepVisitedByEveryJourneyPreservesCount` | Requiring B on the linear graph keeps all journeys |
| `buildGraphFromEmptyEventsIsEmpty` | `buildGraph(from: [])` returns an empty graph |
| `buildGraphComputesCorrectTransitionStats` | Two-journey event log produces correct occurrence count and avg duration |
| `buildGraphContainsAllVisitedSteps` | All steps in events appear as nodes in the graph |
| `simulatedGraphContainsExpectedTransitions` | `simProcessGraph` has exactly the A→B and B→C transitions |
| `simulatedGraphTransitionOccurrencesMatchJourneyCount` | Each edge in the linear graph is crossed exactly once per journey |

---

## Project structure

```
Process Mining Demonstrator.xcodeproj           # Xcode project
Process Mining Demonstrator/                      # App sources (SwiftUI)
  ├─ Lenticularis___Process_InsightsApp.swift    # App entry point + About window scene
  ├─ ContentView.swift                           # Root split-view UI + help panel + lock screen
  ├─ SidebarView.swift                           # Project list, filter controls, connection selector
  ├─ SettingsView.swift                          # App preferences, theme, security
  ├─ ConnectionEditorView.swift                  # Database server / LLM server / profile editor
  ├─ ProcessMapView.swift / FlowChartView.swift  # Process map and flow-chart rendering
  ├─ StatisticsView.swift / ChartState.swift     # KPIs, statistics, A/B comparison
  ├─ HappyPathView.swift                         # Happy path definition + conformance score
  ├─ TargetProcessView.swift                     # Target norms overlay
  ├─ SimulationView.swift                        # Simulation config, results, CSV export
  ├─ SimulationEngine.swift                      # Markov model + Monte Carlo engine (pure)
  ├─ SamplingView.swift                          # Sample-set creation UI
  ├─ StepEditorView.swift                        # Per-step colour / shape / score editor
  ├─ SplashScreenView.swift                      # Launch splash + About panel
  ├─ DatabaseManager.swift                       # Connection management, Keychain, legacy migration
  ├─ ProcessRepository.swift                     # All Exasol queries
  ├─ AppViewModel.swift                          # Central ObservableObject state machine
  ├─ LLMService.swift                            # OpenAI-compatible chat client
  ├─ BackupManager.swift                         # AES-GCM encrypted backup / restore
  ├─ Persistence.swift                           # UserDefaults helpers
  ├─ HelpView.swift                              # In-app documentation + paginated PDF export
  ├─ MarkdownView.swift                          # Lightweight Markdown renderer
  ├─ Models.swift                                # Core value types (Sendable, Codable)
  └─ PlatformCompat.swift                        # macOS / iPadOS shims
Process Mining DemonstratorTests/                # Swift Testing unit tests
Process Mining DemonstratorUITests/              # XCUIAutomation UI tests
SwiftExasolConnector/                            # Exasol WebSocket client (local Swift package)
```

---

## Architecture notes

| Layer | Technology |
|---|---|
| UI | SwiftUI (`NavigationSplitView`, Charts framework, adaptive `horizontalSizeClass` layout) |
| State | `AppViewModel` (`ObservableObject`), per-chart `ChartFilterState` snapshots |
| Database | Exasol via `SwiftExasolConnector` (local Swift package, WebSocket protocol) |
| Persistence | UserDefaults (settings, filter groups, happy paths, norms) + Keychain (passwords) |
| Simulation | `SimulationEngine` — pure `enum`, all types `Sendable`, no I/O |
| AI | `LLMService` — async/await, OpenAI chat-completions endpoint |
| Backup | `BackupManager` — AES-256-GCM via CryptoKit + PBKDF2 via CommonCrypto |

- **macOS + iPadOS.** The UI is written in iOS-style SwiftUI; `PlatformCompat.swift`
  provides `#if os(macOS)` shims so the same source compiles as a native macOS app
  (App Sandbox enabled) and as an iPadOS app.
- **Concurrency.** All networking and database access use Swift `async`/`await` — no
  Combine.
- **App Sandbox.** File exports (PDF, backup, CSV) use the user-selected-file
  entitlement (`ENABLE_USER_SELECTED_FILES = readwrite`).

---

## Exporting the documentation

The complete in-app user documentation can be saved as a **paginated A4 PDF**
(cover page, table of contents, one chapter per page, and "Page X of N" footers).
Open **Help** and click the share button (↑) in the Help window's title bar.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| "missing the User Selected File … entitlement" when exporting | Ensure the app target's `ENABLE_USER_SELECTED_FILES` build setting is `readwrite` |
| UI tests report "not run" / no result | Re-point the UI-test target's *Target to Be Tested* to **Process Mining Demonstrator** (see [Running the tests](#running-the-tests)) |
| Cannot connect to Exasol | Verify host / port / TLS settings and that the user has `SELECT` permission on the required tables; see **Help → Database Setup** |
| Simulation returns no journeys | Check that the process graph has at least one step with in-degree / out-degree ratio < 0.2 (a start step); excluded steps may have removed all entry points |
| AI Documentation tab stays blank | Confirm the LLM server URL, model name, and (if required) API key are set in the active Connection Profile |
| Backup restore overwrites wrong profile | The restore preview lists all profiles that will be overwritten; cancel and export a backup first if needed |

---

## License

See [`LICENSE.txt`](LICENSE.txt) for the full license text.
