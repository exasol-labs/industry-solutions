import SwiftUI
#if canImport(AppKit)
import AppKit
#endif

// MARK: - AB sync state (shared zoom/pan between A and B panels when valve is open)

@Observable
final class ABSyncState {
    var zoomScale:     CGFloat = 1.0
    var panOffset:     CGSize  = .zero
    var lastZoom:      CGFloat = 1.0
    var lastPan:       CGSize  = .zero
    var nodeOverrides: [String: CGPoint] = [:]
    var canvasSize:    CGSize  = .zero

    func copyValues(from other: ABSyncState) {
        zoomScale     = other.zoomScale
        panOffset     = other.panOffset
        lastZoom      = other.lastZoom
        lastPan       = other.lastPan
        nodeOverrides = other.nodeOverrides
        canvasSize    = other.canvasSize
    }
}

// MARK: - Note editor item

private struct NoteEditorItem: Identifiable {
    let id             = UUID()
    let target:        ProcessNote.NoteTarget
    let existingNote:  ProcessNote?
    let filterSnapshot: FilterSnapshot
}

// MARK: - Note list item

private struct NoteListItem: Identifiable {
    let id             = UUID()
    let target:        ProcessNote.NoteTarget
    let notes:         [ProcessNote]
    let filterSnapshot: FilterSnapshot
}

// MARK: - ProcessMapView

struct ProcessMapView: View {
    @ObservedObject var vm: AppViewModel
    @ObservedObject private var db = DatabaseManager.shared

    @AppStorage("processmap.kpiExpanded") private var kpiExpanded = true
    @AppStorage("abComparison.valveOpen") private var valveOpen  = true
    @AppStorage("slider.mode")            private var sliderMode: SliderMode = .range
    @State private var abSyncState       = ABSyncState()  // A's master — always alive
    @State private var bInitialState: ABSyncState? = nil  // seed for B when valve closes
    @State private var bStateId          = UUID()         // bump → forces B to re-create
    @State private var showSentPrompt    = false
    @State private var noteEditorItem: NoteEditorItem? = nil
    @State private var noteListItem:   NoteListItem?   = nil
    @State private var isExporting       = false
    @State private var pdfShareURL: URL?
    @State private var bLayoutSeed       = UUID()
    @State private var complianceEditMode  = false
    @State private var complianceSyncState = ABSyncState()
    @State private var showGapTable        = false
    @State private var showRenameFilterGroup = false
    @State private var filterGroupRenameId:  UUID?   = nil
    @State private var filterGroupNewName:   String  = ""
    @State private var abSliderFromA:     Date = Date()
    @State private var abSliderToA:       Date = Date()
    @State private var abSliderFromB:     Date = Date()
    @State private var abSliderToB:       Date = Date()
    @State private var aChartSliderFrom:  Date = Date()
    @State private var aChartSliderTo:    Date = Date()
    @State private var bChartSliderFrom:  Date = Date()
    @State private var bChartSliderTo:    Date = Date()
    @AppStorage("achart.controlsExpanded")      private var aChartControlsExpanded     = true
    @AppStorage("bchart.controlsExpanded")      private var bChartControlsExpanded     = true
    @AppStorage("compliance.controlsExpanded")  private var complianceControlsExpanded = true
    @AppStorage("compliance.kpiExpanded")       private var complianceKpiExpanded      = true
    @AppStorage("compliance.normIsMinimum")     private var normIsMinimum              = false
    @State private var complianceSliderFrom: Date = Date()
    @State private var complianceSliderTo:   Date = Date()
    @AppStorage("abpanel.a.controlsExpanded") private var abPanelAControlsExpanded = true
    @AppStorage("abpanel.b.controlsExpanded") private var abPanelBControlsExpanded = true
    @AppStorage("abpanel.a.kpiExpanded")      private var abPanelAKpiExpanded      = true
    @AppStorage("abpanel.b.kpiExpanded")      private var abPanelBKpiExpanded      = true
    @AppStorage("kpi.show.totalJourneys")     private var kpiShowTotalJourneys    = true
    @AppStorage("kpi.show.filteredJourneys")  private var kpiShowFilteredJourneys = true
    @AppStorage("kpi.show.shortestJourney")   private var kpiShowShortestJourney  = true
    @AppStorage("kpi.show.avgJourney")        private var kpiShowAvgJourney       = true
    @AppStorage("kpi.show.stdDev")            private var kpiShowStdDev           = true
    @AppStorage("kpi.show.longestJourney")    private var kpiShowLongestJourney   = true
    @AppStorage("kpi.show.graphValue")        private var kpiShowGraphValue       = true
    @AppStorage("kpi.show.processGoodness")    private var kpiShowProcessGoodness   = true
    @AppStorage("kpi.show.processSimilarity")  private var kpiShowProcessSimilarity = true
    @AppStorage("kpi.show.activeSample")       private var kpiShowActiveSample      = true
    @AppStorage("kpi.order")                   private var kpiOrderRaw              = kpiDefaultOrder

    private var orderedKPIIds: [String] {
        let stored = kpiOrderRaw.split(separator: ",").map(String.init)
        let all    = kpiDefaultOrder.split(separator: ",").map(String.init)
        return stored + all.filter { !stored.contains($0) }
    }

    @Environment(\.horizontalSizeClass) private var horizontalSizeClass

    private var titleCapsule: some View {
        VStack(spacing: 0) {
            Text(vm.selectedProject?.title ?? "Process Map")
                .font(.subheadline.weight(.semibold))
                .lineLimit(1)
            Text(vm.activeChartMode.rawValue)
                .font(.caption2)
                .foregroundStyle(.secondary)
                .lineLimit(1)
                .opacity(vm.selectedProject != nil ? 1 : 0)
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 5)
        .background(.regularMaterial, in: Capsule())
        .overlay(Capsule().strokeBorder(Color.primary.opacity(0.08), lineWidth: 0.5))
        .shadow(color: .black.opacity(0.22), radius: 10, x: 0, y: 5)
        .shadow(color: .black.opacity(0.08), radius: 2, x: 0, y: 1)
    }

    var body: some View {
        VStack(spacing: 0) {
            if db.isConnected && vm.selectedProject != nil {
                if vm.activeChartMode == .abComparison || vm.activeChartMode == .statistics
                    || vm.activeChartMode == .comments || vm.activeChartMode == .aiAnalysis
                    || vm.activeChartMode == .happyPath || vm.activeChartMode == .complianceCheck
                    || vm.activeChartMode == .simulation {
                    // These modes manage their own display; no shared KPI strip
                    Color(.secondarySystemGroupedBackground)
                        .frame(height: 24)
                } else if (vm.activeChartMode != .individualJourney && !vm.processGraph.transitions.isEmpty)
                       || (vm.activeChartMode == .individualJourney && vm.journeyDate != nil) {
                // ── Collapse handle at top of KPI area ────────────────────
                Button {
                    withAnimation(.easeInOut(duration: 0.2)) { kpiExpanded.toggle() }
                } label: {
                    HStack(spacing: 6) {
                        Image(systemName: kpiExpanded ? "chevron.down" : "chevron.up")
                            .font(.caption2.weight(.semibold))
                            .foregroundStyle(.secondary)
                        if !kpiExpanded {
                            if let total = vm.totalJourneyCount, let filtered = vm.journeyCount {
                                Text("\(filtered.formatted()) / \(total.formatted()) Journeys")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            } else if let filtered = vm.journeyCount {
                                Text("\(filtered.formatted()) Filtered Journeys")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                        }
                        Spacer(minLength: 0)
                    }
                    .padding(.horizontal, 16)
                    .padding(.vertical, 5)
                    .background(Color(.secondarySystemGroupedBackground))
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)

                // ── KPI panel ──────────────────────────────────────────────
                if kpiExpanded {
                    kpiPanel
                        .transition(.move(edge: .top).combined(with: .opacity))
                }
                } // end else (non-A/B, non-empty-individual-journey modes)
            }

            // ── Active view ────────────────────────────────────────────
            activeView
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color(.systemGroupedBackground))
        .safeAreaInset(edge: .top, spacing: 0) {
            if horizontalSizeClass == .regular {
                titleCapsule
                    .padding(.top, 8)
                    .padding(.bottom, 4)
                    .frame(maxWidth: .infinity, alignment: .center)
            }
        }
        .navigationTitle("")
        .toolbar {
            if horizontalSizeClass != .regular {
                ToolbarItem(placement: .principal) {
                    titleCapsule
                }
            }

            if canShare {
                ToolbarItem(placement: .primaryAction) {
                    Button {
                        Task { await exportPDF() }
                    } label: {
                        if isExporting {
                            ProgressView().controlSize(.small)
                        } else {
                            Label("Share", systemImage: "square.and.arrow.up")
                        }
                    }
                    .disabled(isExporting)
                }
            }

            if db.isConnected && vm.selectedProject != nil {
                ToolbarItem(placement: .primaryAction) {
                    Menu {
                        Picker("View", selection: Binding(
                            get: { vm.activeChartMode },
                            set: { vm.switchChartMode(to: $0) }
                        )) {
                            ForEach(DetailViewMode.allCases) { mode in
                                Label(mode.rawValue, systemImage: mode.icon).tag(mode)
                            }
                        }
                        .pickerStyle(.inline)
                    } label: {
                        Image(systemName: "line.3.horizontal")
                            .font(.body.weight(.medium))
                    }
                }
            }
        }
        .sheet(isPresented: $showSentPrompt) {
            SentPromptSheet(prompt: vm.lastSentLLMPrompt ?? "")
        }
        .sheet(item: $pdfShareURL) { url in
            ShareSheet(items: [url])
        }
        .sheet(item: $noteEditorItem) { item in
            NoteEditorSheet(
                item:     item,
                onSave:   { note in Task { await vm.setNote(note) } },
                onDelete: { note in Task { await vm.deleteNote(note) } }
            )
        }
        .sheet(item: $noteListItem) { listItem in
            NoteListSheet(
                item:     listItem,
                onSave:   { note in Task { await vm.setNote(note) } },
                onDelete: { note in Task { await vm.deleteNote(note) } }
            )
        }
        // Reset A's master state when a different project is selected so stale
        // node positions and zoom from the old project don't carry into the new one.
        .onChange(of: vm.selectedProject?.projectId) { _, _ in
            abSyncState         = ABSyncState()
            bInitialState       = nil
            bStateId            = UUID()
            complianceSyncState = ABSyncState()
        }
        // Initialise all sliders once selectProject has fetched the real date bounds.
        // initialToDate is @Published and is set after loadMaxDate completes, so by
        // this point vm.initialFromDate/initialToDate are correct.
        .onChange(of: vm.initialToDate) { _, newMax in
            let newMin = vm.initialFromDate
            aChartSliderFrom      = newMin; aChartSliderTo      = newMax
            bChartSliderFrom      = newMin; bChartSliderTo      = newMax
            abSliderFromA         = newMin; abSliderToA         = newMax
            abSliderFromB         = newMin; abSliderToB         = newMax
            complianceSliderFrom  = newMin; complianceSliderTo  = newMax
        }
        // When a filter group is applied from any view, sync the single-chart sliders
        .onChange(of: vm.selectedFilterGroupId) { _, _ in
            guard let group = vm.selectedFilterGroup else { return }
            aChartSliderFrom     = group.fromDate; aChartSliderTo     = group.toDate
            bChartSliderFrom     = group.fromDate; bChartSliderTo     = group.toDate
            complianceSliderFrom = group.fromDate; complianceSliderTo = group.toDate
        }
        .alert("Rename Filter Preset", isPresented: $showRenameFilterGroup) {
            TextField("Name", text: $filterGroupNewName)
            Button("Rename") {
                if let id = filterGroupRenameId {
                    vm.renameFilterGroup(id: id, name: filterGroupNewName)
                }
                filterGroupRenameId = nil
                filterGroupNewName  = ""
            }
            Button("Cancel", role: .cancel) {
                filterGroupRenameId = nil
                filterGroupNewName  = ""
            }
        }
    }

    // MARK: - Active view switcher

    @ViewBuilder
    private var activeView: some View {
        switch vm.activeChartMode {
        case .aChart:
            aChartContent
        case .bChart:
            bChartContent
        case .abComparison:
            abComparisonContent
        case .individualJourney:
            individualJourneyContent
        case .aiAnalysis:
            aiAnalysisContent
        case .statistics:
            StatisticsView(vm: vm)
        case .complianceCheck:
            complianceCheckContent
        case .happyPath:
            HappyPathView(vm: vm,
                          onNodeAction:     handleNodeAction,
                          notes:            vm.projectNotes,
                          ownNoteNodeNames: myNoteNodeNames,
                          ownNoteEdgeIds:   myNoteEdgeIds,
                          onNodeNote:       handleNodeNoteEdit,
                          onEdgeNote:       handleEdgeNoteEdit)
        case .comments:
            commentsContent
        case .simulation:
            SimulationView(vm: vm)
        }
    }

    // MARK: - Node action handler

    private func handleNodeAction(_ node: String, _ action: NodeAction) {
        switch action {
        case .include:
            vm.includedSteps.insert(node)
            vm.excludedSteps.remove(node)
        case .exclude:
            vm.excludedSteps.insert(node)
            vm.includedSteps.remove(node)
        }
        Task { await vm.reloadGraph() }
    }

    // MARK: - Note handler functions

    private var myNoteNodeNames: Set<String> {
        let me = DatabaseManager.shared.activeDatabaseServer?.username ?? ""
        return Set(vm.projectNotes.compactMap { note in
            guard note.username == me, case .node(let n) = note.target else { return nil }
            return n
        })
    }

    private var myNoteEdgeIds: Set<String> {
        let me = DatabaseManager.shared.activeDatabaseServer?.username ?? ""
        return Set(vm.projectNotes.compactMap { note in
            guard note.username == me, case .edge(let f, let t) = note.target else { return nil }
            return "\(f)->\(t)"
        })
    }

    private func handleNodeNoteEdit(_ node: String) {
        let matching = vm.projectNotes.filter {
            if case .node(let n) = $0.target { return n == node }
            return false
        }
        switch matching.count {
        case 0:
            noteEditorItem = NoteEditorItem(target: .node(node), existingNote: nil,
                                            filterSnapshot: vm.currentFilterSnapshot())
        case 1:
            noteEditorItem = NoteEditorItem(target: .node(node), existingNote: matching[0],
                                            filterSnapshot: matching[0].filterSnapshot)
        default:
            noteListItem = NoteListItem(target: .node(node), notes: matching,
                                        filterSnapshot: vm.currentFilterSnapshot())
        }
    }

    private func handleEdgeNoteEdit(_ edge: ProcessTransition) {
        let matching = vm.projectNotes.filter {
            if case .edge(let f, let t) = $0.target {
                return f == edge.fromStep && t == edge.toStep
            }
            return false
        }
        switch matching.count {
        case 0:
            noteEditorItem = NoteEditorItem(
                target: .edge(from: edge.fromStep, to: edge.toStep),
                existingNote: nil, filterSnapshot: vm.currentFilterSnapshot())
        case 1:
            noteEditorItem = NoteEditorItem(
                target: .edge(from: edge.fromStep, to: edge.toStep),
                existingNote: matching[0], filterSnapshot: matching[0].filterSnapshot)
        default:
            noteListItem = NoteListItem(
                target: .edge(from: edge.fromStep, to: edge.toStep),
                notes: matching, filterSnapshot: vm.currentFilterSnapshot())
        }
    }

    // MARK: - Shared process chart content (A-Chart & B-Chart)

    @ViewBuilder
    private func processChartContent(loadingLabel: String, emptyHint: String,
                                     syncState: ABSyncState? = nil) -> some View {
        if vm.selectedProject == nil {
            ContentUnavailableView(
                "No Project Selected",
                systemImage: "flowchart",
                description: Text("Select a project from the sidebar.")
            )
        } else if let error = vm.errorMessage, !vm.isLoading {
            ContentUnavailableView(
                "Failed to Load",
                systemImage: "exclamationmark.triangle",
                description: Text(error)
            )
        } else if vm.processGraph.transitions.isEmpty {
            // Initial load or genuinely empty result — show spinner or empty state.
            if vm.isLoading {
                ProgressView(loadingLabel)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                ContentUnavailableView {
                    Label("No Process Data", systemImage: "chart.bar.xaxis")
                } description: {
                    Text(emptyHint)
                } actions: {
                    Button("Load") { Task { await vm.reloadGraph() } }
                        .buttonStyle(.borderedProminent)
                }
            }
        } else {
            // Graph has data. Keep FlowChartView mounted during reloads so zoom/pan
            // state is preserved. Overlay a subtle spinner while a reload is in flight.
            FlowChartView(graph: vm.processGraph,
                          projectId: vm.selectedProject?.projectId ?? "",
                          chartMode: vm.activeChartMode.rawValue,
                          metric: vm.transitionMetric,
                          isLoading: vm.isLoading,
                          syncState: syncState,
                          onNodeAction: handleNodeAction,
                          notes:            vm.projectNotes,
                          ownNoteNodeNames: myNoteNodeNames,
                          ownNoteEdgeIds:   myNoteEdgeIds,
                          onNodeNote:       handleNodeNoteEdit,
                          onEdgeNote:       handleEdgeNoteEdit)
                .id(vm.selectedProject?.projectId)
                .overlay(alignment: .top) {
                    if vm.isLoading {
                        ProgressView()
                            .padding(.horizontal, 16)
                            .padding(.vertical, 8)
                            .background(.regularMaterial, in: Capsule())
                            .padding(.top, 12)
                            .transition(.opacity)
                    }
                }
        }
    }

    // Use the real dataset minimum so the track and boundary label span the full
    // project history. Fall back to the 30-day window start if projectMinDate has
    // not yet been loaded (it defaults to Date() before any project is selected).
    private var sliderRangeMin: Date {
        vm.projectMinDate < vm.initialToDate ? vm.projectMinDate : vm.initialFromDate
    }

    // MARK: - Filter group preset menu

    @ViewBuilder
    private func filterGroupMenu(selectedId: UUID?,
                                 onApply: @escaping (FilterGroup) -> Void) -> some View {
        if !vm.filterGroups.isEmpty {
            let selectedGroup = vm.filterGroups.first { $0.id == selectedId }
            Menu {
                ForEach(vm.filterGroups) { group in
                    Button {
                        onApply(group)
                    } label: {
                        if group.id == selectedId {
                            Label(group.name, systemImage: "checkmark")
                        } else {
                            Text(group.name)
                        }
                    }
                }
                Divider()
                if selectedGroup != nil {
                    Button {
                        filterGroupRenameId   = selectedId
                        filterGroupNewName    = selectedGroup?.name ?? ""
                        showRenameFilterGroup = true
                    } label: {
                        Label("Rename\u{2026}", systemImage: "pencil")
                    }
                    Button(role: .destructive) {
                        if let id = selectedId {
                            vm.deleteFilterGroup(id: id)
                        }
                    } label: {
                        Label("Delete", systemImage: "trash")
                    }
                }
            } label: {
                HStack(spacing: 4) {
                    Image(systemName: "slider.horizontal.3")
                        .font(.caption2)
                        .foregroundStyle(selectedId != nil ? Color.accentColor : Color.secondary)
                    Text(selectedGroup?.name ?? "Presets")
                        .font(.caption2.weight(.medium))
                        .lineLimit(1)
                    Image(systemName: "chevron.up.chevron.down")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }
                .padding(.horizontal, 8)
                .padding(.vertical, 5)
                .background(Color.primary.opacity(0.07))
                .clipShape(Capsule())
            }
        }
    }

    // MARK: - Metric selector bar (shared between A-Chart and B-Chart)

    private var metricSelectorBar: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 6) {
                ForEach(TransitionMetric.allCases) { m in
                    let selected = vm.transitionMetric == m
                    Button { vm.transitionMetric = m } label: {
                        HStack(spacing: 4) {
                            Image(systemName: m.icon).font(.caption2)
                            Text(m.rawValue).font(.caption2.weight(.medium)).lineLimit(1)
                        }
                        .padding(.horizontal, 8)
                        .padding(.vertical, 5)
                        .background(selected ? Color.accentColor : Color.primary.opacity(0.07))
                        .foregroundStyle(selected ? Color.white : Color.primary)
                        .clipShape(Capsule())
                    }
                    .buttonStyle(.plain)
                    .disabled(vm.processGraph.transitions.isEmpty)
                }
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 7)
        }
        .background(Color(.secondarySystemGroupedBackground))
    }

    // MARK: - A-Chart
    // Always writes zoom/pan/nodes into abSyncState so A/B view inherits them on switch.

    @ViewBuilder
    private var aChartContent: some View {
        VStack(spacing: 0) {
            if db.isConnected && vm.selectedProject != nil && !vm.processGraph.transitions.isEmpty {
                // ── Date slider + Metrics card ─────────────────────────────
                VStack(spacing: 0) {
                    HStack(spacing: 0) {
                        Button {
                            withAnimation(.easeInOut(duration: 0.2)) { aChartControlsExpanded.toggle() }
                        } label: {
                            HStack(spacing: 6) {
                                Image(systemName: aChartControlsExpanded ? "chevron.down" : "chevron.right")
                                    .font(.caption2.weight(.semibold))
                                    .foregroundStyle(.secondary)
                                Text("Date & Metrics")
                                    .font(.caption2.weight(.medium))
                                    .foregroundStyle(.secondary)
                                Spacer(minLength: 0)
                            }
                            .padding(.horizontal, 12)
                            .padding(.vertical, 7)
                            .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                        filterGroupMenu(selectedId: vm.selectedFilterGroupId) { group in
                            vm.applyFilterGroup(group)
                            aChartSliderFrom = group.fromDate
                            aChartSliderTo   = group.toDate
                            Task { await vm.reloadGraph() }
                        }
                        .padding(.trailing, 8)
                    }
                    if aChartControlsExpanded {
                        Divider().padding(.horizontal, 8)
                        JourneyTimeSlider(
                            rangeMin:  sliderRangeMin,
                            rangeMax:  vm.initialToDate,
                            mode:      sliderMode,
                            fromDate:  $aChartSliderFrom,
                            toDate:    $aChartSliderTo,
                            onCommit:  { from, to in
                                if sliderMode == .singleDay {
                                    Task {
                                        if let actual = await vm.reloadGraphForDay(from), actual != from {
                                            aChartSliderFrom = actual; aChartSliderTo = actual
                                        }
                                    }
                                } else {
                                    vm.fromDate = from; vm.toDate = to
                                    Task { await vm.reloadGraph() }
                                }
                            }
                        )
                        Divider().padding(.horizontal, 8)
                        metricSelectorBar
                    }
                }
                .background(Color(.secondarySystemGroupedBackground),
                             in: RoundedRectangle(cornerRadius: 10, style: .continuous))
                .overlay(
                    RoundedRectangle(cornerRadius: 10, style: .continuous)
                        .strokeBorder(Color.primary.opacity(0.10), lineWidth: 1)
                )
                .padding(.horizontal, 12)
                .padding(.top, 10)
                .padding(.bottom, 6)
            }
            processChartContent(
                loadingLabel: "Loading process map",
                emptyHint:    "No event transitions found for this project.",
                syncState:    abSyncState
            )
        }
    }

    // MARK: - B-Chart

    @ViewBuilder
    private var bChartContent: some View {
        VStack(spacing: 0) {
            if db.isConnected && vm.selectedProject != nil && !vm.processGraph.transitions.isEmpty {
                // ── Date slider + Metrics card ─────────────────────────────
                VStack(spacing: 0) {
                    HStack(spacing: 0) {
                        Button {
                            withAnimation(.easeInOut(duration: 0.2)) { bChartControlsExpanded.toggle() }
                        } label: {
                            HStack(spacing: 6) {
                                Image(systemName: bChartControlsExpanded ? "chevron.down" : "chevron.right")
                                    .font(.caption2.weight(.semibold))
                                    .foregroundStyle(.secondary)
                                Text("Date & Metrics")
                                    .font(.caption2.weight(.medium))
                                    .foregroundStyle(.secondary)
                                Spacer(minLength: 0)
                            }
                            .padding(.horizontal, 12)
                            .padding(.vertical, 7)
                            .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                        filterGroupMenu(selectedId: vm.selectedFilterGroupId) { group in
                            vm.applyFilterGroup(group)
                            bChartSliderFrom = group.fromDate
                            bChartSliderTo   = group.toDate
                            Task { await vm.reloadGraph() }
                        }
                        .padding(.trailing, 8)
                    }
                    if bChartControlsExpanded {
                        Divider().padding(.horizontal, 8)
                        JourneyTimeSlider(
                            rangeMin:  sliderRangeMin,
                            rangeMax:  vm.initialToDate,
                            mode:      sliderMode,
                            fromDate:  $bChartSliderFrom,
                            toDate:    $bChartSliderTo,
                            onCommit:  { from, to in
                                if sliderMode == .singleDay {
                                    Task {
                                        if let actual = await vm.reloadGraphForDay(from), actual != from {
                                            bChartSliderFrom = actual; bChartSliderTo = actual
                                        }
                                    }
                                } else {
                                    vm.fromDate = from; vm.toDate = to
                                    Task { await vm.reloadGraph() }
                                }
                            }
                        )
                        Divider().padding(.horizontal, 8)
                        metricSelectorBar
                    }
                }
                .background(Color(.secondarySystemGroupedBackground),
                             in: RoundedRectangle(cornerRadius: 10, style: .continuous))
                .overlay(
                    RoundedRectangle(cornerRadius: 10, style: .continuous)
                        .strokeBorder(Color.primary.opacity(0.10), lineWidth: 1)
                )
                .padding(.horizontal, 12)
                .padding(.top, 10)
                .padding(.bottom, 6)
            }
            processChartContent(
                loadingLabel: "Loading B-Chart",
                emptyHint:    "Use the sidebar filters and tap Apply to load the B-Chart."
            )
        }
    }

    // MARK: - Individual journey view

    @ViewBuilder
    private var individualJourneyContent: some View {
        if vm.isLoading {
            ProgressView("Loading journey")
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        } else if let error = vm.errorMessage {
            ContentUnavailableView(
                "Failed to Load",
                systemImage: "exclamationmark.triangle",
                description: Text(error)
            )
        } else if vm.selectedProject == nil {
            ContentUnavailableView(
                "No Project Selected",
                systemImage: "flowchart",
                description: Text("Select a project from the sidebar to view a journey.")
            )
        } else if vm.eventIdFilter.trimmingCharacters(in: .whitespaces).isEmpty {
            ContentUnavailableView(
                "No Journey Selected",
                systemImage: "person.crop.rectangle.stack",
                description: Text("Enter an Event ID in the sidebar and tap Load Journey.")
            )
        } else if vm.processGraph.transitions.isEmpty {
            ContentUnavailableView(
                "Journey Not Found",
                systemImage: "magnifyingglass",
                description: Text("No steps found for \"\(vm.eventIdFilter)\".\nQueried hash: \(vm.lastQueriedEventId)")
            )
        } else {
            FlowChartView(graph: vm.processGraph,
                          projectId: vm.selectedProject?.projectId ?? "",
                          chartMode: "ij_\(vm.eventIdFilter)",
                          metric: vm.transitionMetric)
                .id(vm.eventIdFilter)
        }
    }

    // MARK: - A/B Comparison view

    @ViewBuilder
    private var abComparisonContent: some View {
        if vm.selectedProject == nil {
            ContentUnavailableView(
                "No Project Selected",
                systemImage: "flowchart",
                description: Text("Select a project from the sidebar.")
            )
        } else {
            HStack(spacing: 0) {
                // A is the permanent master — always drives abSyncState
                abPanel(side: .a, graph: vm.abGraphA, label: "A-Chart", metric: vm.abMetricA,
                        syncState: abSyncState, skipInitialFit: false,
                        sliderFrom: $abSliderFromA, sliderTo: $abSliderToA,
                        kpiExpanded: $abPanelAKpiExpanded,
                        controlsExpanded: $abPanelAControlsExpanded,
                        onSliderCommit: { from, to in
                            if sliderMode == .singleDay {
                                Task {
                                    if let actual = await vm.reloadABSideForDay(.a, day: from), actual != from {
                                        abSliderFromA = actual; abSliderToA = actual
                                    }
                                }
                            } else {
                                Task { await vm.reloadABSide(.a, from: from, to: to) }
                            }
                        })
                Divider()
                    .overlay { valveButton }
                // B adopts A's state when open; keeps it when closed (via seed)
                abPanel(side: .b, graph: vm.abGraphB, label: "B-Chart", metric: vm.abMetricB,
                        syncState: valveOpen ? abSyncState : nil,
                        initialViewState: valveOpen ? nil : bInitialState,
                        skipInitialFit: valveOpen || bInitialState != nil,
                        bStateId: bStateId,
                        sliderFrom: $abSliderFromB, sliderTo: $abSliderToB,
                        kpiExpanded: $abPanelBKpiExpanded,
                        controlsExpanded: $abPanelBControlsExpanded,
                        onSliderCommit: { from, to in
                            if sliderMode == .singleDay {
                                Task {
                                    if let actual = await vm.reloadABSideForDay(.b, day: from), actual != from {
                                        abSliderFromB = actual; abSliderToB = actual
                                    }
                                }
                            } else {
                                Task { await vm.reloadABSide(.b, from: from, to: to) }
                            }
                        })
            }
            .overlay(alignment: .top) {
                if kpiShowProcessSimilarity {
                    similarityBadge
                        .padding(.top, abControlsAreaHeight)
                        .allowsHitTesting(false)
                }
            }
        }
    }

    // Estimated top-padding so the badge lands just below the date-range slider group
    private var abControlsAreaHeight: CGFloat {
        var h: CGFloat = 30                          // panel header bar
        if abPanelAKpiExpanded      { h += 82 }     // KPI scroll row
        h += 30                                      // Date & Metrics collapse header
        if abPanelAControlsExpanded { h += 148 }    // slider + metrics chips
        return h + 8                                 // small gap
    }

    // Similarity badge: horizontal chip that floats on the A/B divider
    @ViewBuilder
    private var similarityBadge: some View {
        if let q = vm.abSimilarityScore {
            let color: Color = q >= 0.7 ? .green : q <= 0.3 ? .red : .blue
            HStack(spacing: 6) {
                Image(systemName: "arrow.triangle.2.circlepath")
                    .font(.caption2)
                    .foregroundStyle(color)
                Text("Similarity")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                Text(q.formatted(.number.precision(.fractionLength(2))))
                    .font(.callout.weight(.semibold))
                    .monospacedDigit()
                    .foregroundStyle(color)
            }
            .padding(.horizontal, 10)
            .padding(.vertical, 6)
            .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 10, style: .continuous)
                    .strokeBorder(color.opacity(0.45), lineWidth: 1.5)
            )
            .shadow(color: .black.opacity(0.15), radius: 6, y: 2)
        } else if vm.isLoading {
            ProgressView()
                .controlSize(.small)
                .padding(10)
                .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
        }
    }

    // Valve toggle button that sits centred on the A/B divider
    private var valveButton: some View {
        Button {
            if valveOpen {
                // Closing: snapshot A's master state so B keeps those values
                let snap = ABSyncState()
                snap.copyValues(from: abSyncState)
                bInitialState = snap
            } else {
                // Opening: discard seed — B will read straight from A's master
                bInitialState = nil
            }
            bStateId = UUID()   // force B to re-create with new seed/syncState
            valveOpen.toggle()
        } label: {
            Image(systemName: valveOpen
                  ? "arrow.left.arrow.right.circle.fill"
                  : "arrow.left.arrow.right.circle")
                .font(.title3)
                .foregroundStyle(valveOpen ? Color.accentColor : Color.secondary)
                .padding(8)
                .background(.regularMaterial, in: Circle())
                .overlay(Circle().strokeBorder(Color.primary.opacity(0.10), lineWidth: 0.5))
                .shadow(color: .black.opacity(0.18), radius: 6, y: 2)
        }
        .buttonStyle(.plain)
        .accessibilityLabel(valveOpen ? "Sync viewport: on" : "Sync viewport: off")
        .help(valveOpen
              ? "Valve open — pan, zoom and reset are synchronised"
              : "Valve closed — charts move independently")
    }

    @ViewBuilder
    private func abPanel(side: ABSide, graph: ProcessGraph, label: String, metric: TransitionMetric,
                         syncState: ABSyncState? = nil,
                         initialViewState: ABSyncState? = nil,
                         skipInitialFit: Bool = false,
                         bStateId: UUID = UUID(),
                         sliderFrom: Binding<Date>,
                         sliderTo: Binding<Date>,
                         kpiExpanded: Binding<Bool>,
                         controlsExpanded: Binding<Bool>,
                         onSliderCommit: @escaping (Date, Date) -> Void) -> some View {
        let isActive = vm.abActiveSide == side
        VStack(spacing: 0) {
            // Header bar: side-switcher button on the left, optional copy action + journey count on the right
            HStack(spacing: 0) {
                Button { vm.switchABSide(to: side) } label: {
                    HStack(spacing: 6) {
                        Image(systemName: isActive ? "pencil.tip.crop.circle.fill" : "circle")
                            .font(.caption)
                            .foregroundStyle(isActive ? Color.accentColor : Color.secondary.opacity(0.5))
                        Text(label)
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(isActive ? Color.accentColor : .secondary)
                        if isActive {
                            Text("· editing")
                                .font(.caption2)
                                .foregroundStyle(Color.accentColor.opacity(0.8))
                        }
                        Spacer()
                    }
                    .padding(.leading, 12)
                    .padding(.vertical, 7)
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)

                if side == .a && !graph.transitions.isEmpty {
                    Button { copyLayoutAtoB() } label: {
                        Label("Copy layout to B", systemImage: "square.on.square")
                            .labelStyle(.iconOnly)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .padding(.horizontal, 8)
                            .padding(.vertical, 7)
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel("Copy A layout to B")
                    .help("Copy A's node layout to B")
                }

                if let count = (side == .a ? vm.abJourneyCountA : vm.abJourneyCountB) {
                    Text("\(count.formatted()) journeys")
                        .font(.caption2.monospacedDigit())
                        .foregroundStyle(.secondary)
                        .padding(.horizontal, 6)
                        .padding(.vertical, 7)
                }

                Button {
                    withAnimation(.easeInOut(duration: 0.2)) { kpiExpanded.wrappedValue.toggle() }
                } label: {
                    Image(systemName: kpiExpanded.wrappedValue ? "chevron.down" : "chevron.right")
                        .font(.caption2.weight(.semibold))
                        .foregroundStyle(.secondary)
                        .padding(.horizontal, 8)
                        .padding(.vertical, 7)
                }
                .buttonStyle(.plain)
                .help(kpiExpanded.wrappedValue ? "Hide KPIs" : "Show KPIs")
                .opacity(graph.transitions.isEmpty ? 0 : 1)
                .allowsHitTesting(!graph.transitions.isEmpty)
            }
            .background(isActive
                ? Color.accentColor.opacity(0.08)
                : Color(.secondarySystemGroupedBackground))

            let journeyCount  = side == .a ? vm.abJourneyCountA  : vm.abJourneyCountB
            let minDur        = side == .a ? vm.abMinDurationA    : vm.abMinDurationB
            let avgDur        = side == .a ? vm.abAvgDurationA    : vm.abAvgDurationB
            let stdDevDur     = side == .a ? vm.abStdDevDurationA : vm.abStdDevDurationB
            let maxDur        = side == .a ? vm.abMaxDurationA    : vm.abMaxDurationB
            let isSideLoading = side == .a ? vm.isLoadingA        : vm.isLoadingB

            Divider()

            // Per-panel KPI tiles — hidden until this panel has data
            if !graph.transitions.isEmpty && kpiExpanded.wrappedValue {
                AnyView(ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 12) {
                        ForEach(orderedKPIIds, id: \.self) { id in
                            abPanelKPITile(id: id, side: side, graph: graph,
                                           journeyCount: journeyCount,
                                           minDur: minDur, avgDur: avgDur,
                                           stdDevDur: stdDevDur, maxDur: maxDur,
                                           isSideLoading: isSideLoading, isActive: isActive)
                        }
                    }
                    .padding(.horizontal, 12)
                    .padding(.vertical, 10)
                })
            }

            // ── Date slider + Metrics card — hidden until this panel has data
            if !graph.transitions.isEmpty && db.isConnected && vm.selectedProject != nil {
                AnyView(VStack(spacing: 0) {
                    HStack(spacing: 0) {
                        Button {
                            withAnimation(.easeInOut(duration: 0.2)) { controlsExpanded.wrappedValue.toggle() }
                        } label: {
                            HStack(spacing: 6) {
                                Image(systemName: controlsExpanded.wrappedValue ? "chevron.down" : "chevron.right")
                                    .font(.caption2.weight(.semibold))
                                    .foregroundStyle(.secondary)
                                Text("Date & Metrics")
                                    .font(.caption2.weight(.medium))
                                    .foregroundStyle(.secondary)
                                Spacer(minLength: 0)
                            }
                            .padding(.horizontal, 12)
                            .padding(.vertical, 7)
                            .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                        AnyView(
                            filterGroupMenu(
                                selectedId: side == .a ? vm.abFilterGroupIdA : vm.abFilterGroupIdB
                            ) { group in
                                vm.switchABSide(to: side)
                                vm.applyFilterGroup(group)
                                if side == .a {
                                    vm.abFilterGroupIdA = group.id
                                    abSliderFromA = group.fromDate; abSliderToA = group.toDate
                                } else {
                                    vm.abFilterGroupIdB = group.id
                                    abSliderFromB = group.fromDate; abSliderToB = group.toDate
                                }
                                Task { await vm.reloadGraph() }
                            }
                        )
                        .padding(.trailing, 8)
                    }
                    if controlsExpanded.wrappedValue {
                        Divider().padding(.horizontal, 8)
                        JourneyTimeSlider(
                            rangeMin:  sliderRangeMin,
                            rangeMax:  vm.initialToDate,
                            mode:      sliderMode,
                            fromDate:  sliderFrom,
                            toDate:    sliderTo,
                            onCommit:  { from, to in onSliderCommit(from, to) }
                        )
                        Divider().padding(.horizontal, 8)
                        ScrollView(.horizontal, showsIndicators: false) {
                            HStack(spacing: 6) {
                                ForEach(TransitionMetric.allCases) { m in
                                    let selected = metric == m
                                    Button { vm.setABMetric(m, for: side) } label: {
                                        HStack(spacing: 4) {
                                            Image(systemName: m.icon).font(.caption2)
                                            Text(m.rawValue).font(.caption2.weight(.medium)).lineLimit(1)
                                        }
                                        .padding(.horizontal, 8)
                                        .padding(.vertical, 5)
                                        .background(selected ? Color.accentColor : Color.primary.opacity(0.07))
                                        .foregroundStyle(selected ? Color.white : Color.primary)
                                        .clipShape(Capsule())
                                    }
                                    .buttonStyle(.plain)
                                    .disabled(graph.transitions.isEmpty)
                                }
                            }
                            .padding(.horizontal, 12)
                            .padding(.vertical, 7)
                        }
                    }
                }
                .background(Color(.secondarySystemGroupedBackground),
                             in: RoundedRectangle(cornerRadius: 10, style: .continuous))
                .overlay(
                    RoundedRectangle(cornerRadius: 10, style: .continuous)
                        .strokeBorder(Color.primary.opacity(0.10), lineWidth: 1)
                )
                .padding(.horizontal, 12)
                .padding(.top, 4)
                .padding(.bottom, 6))
            }

            if graph.transitions.isEmpty {
                if isSideLoading {
                    ProgressView("Loading \(label)")
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                } else {
                    ContentUnavailableView {
                        Label(label, systemImage: "chart.xyaxis.line")
                    } description: {
                        Text(isActive
                            ? "Apply filters in the sidebar to load."
                            : "Tap the header to make this side active, then load.")
                    } actions: {
                        Button("Load") {
                            vm.switchABSide(to: side)
                            Task { await vm.reloadGraph() }
                        }
                        .buttonStyle(.borderedProminent)
                    }
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                }
            } else {
                FlowChartView(graph: graph,
                              projectId: vm.selectedProject?.projectId ?? "",
                              chartMode: label,
                              metric: metric,
                              isLoading: isSideLoading,
                              syncState: syncState,
                              initialViewState: initialViewState,
                              skipInitialFit: skipInitialFit,
                              onNodeAction: { node, action in
                                  vm.switchABSide(to: side)
                                  handleNodeAction(node, action)
                              },
                              notes:            vm.projectNotes,
                              ownNoteNodeNames: myNoteNodeNames,
                              ownNoteEdgeIds:   myNoteEdgeIds,
                              onNodeNote:       handleNodeNoteEdit,
                              onEdgeNote:       handleEdgeNoteEdit)
                    .id(side == .b ? "\(bStateId.uuidString)-\(bLayoutSeed)" : label)
                    .overlay(alignment: .top) {
                        if isSideLoading {
                            ProgressView()
                                .padding(.horizontal, 16)
                                .padding(.vertical, 8)
                                .background(.regularMaterial, in: Capsule())
                                .padding(.top, 12)
                                .transition(.opacity)
                        }
                    }
            }
        }
        .frame(maxWidth: .infinity)
    }

    // MARK: - AI supported Documentation view

    private var analysisParametersSection: String {
        var md = "\n\n## Analysis Parameters\n\n"
        if let model = vm.llmAnalysisModel {
            md += "**Model:** `\(model)`\n\n"
        }
        if !vm.llmPromptTemplate.isEmpty {
            md += "**Prompt template:**\n\n"
            md += vm.llmPromptTemplate
                .split(separator: "\n", omittingEmptySubsequences: false)
                .map { "> \($0)" }
                .joined(separator: "\n")
        }
        return md
    }

    private var notesMarkdownSection: String {
        guard !vm.projectNotes.isEmpty else { return "" }
        let sorted = vm.projectNotes.sorted { $0.createdAt < $1.createdAt }
        var md = "\n\n## User Comments\n\n"
        md += "| Element | Type | User | Note | Date |\n"
        md += "|---------|------|------|------|------|\n"
        for note in sorted {
            let element = note.target.displayName
            let type    = note.target.isNode ? "Node" : "Edge"
            let user    = note.username.isEmpty ? "—" : note.username
            let text    = note.text
                .replacingOccurrences(of: "|", with: "｜")
                .replacingOccurrences(of: "\n", with: "<br>")
            let date    = note.createdAt.formatted(date: .abbreviated, time: .shortened)
            md += "| \(element) | \(type) | \(user) | \(text) | \(date) |\n"
        }
        return md
    }

    // Assembles the full structured report with title page, TOC, and page-break chapters
    private var reportDocument: String {
        guard let result = vm.llmAnalysisResult,
              let project = vm.selectedProject else { return "" }

        func esc(_ s: String) -> String {
            s.replacingOccurrences(of: "&", with: "&amp;")
             .replacingOccurrences(of: "<", with: "&lt;")
             .replacingOccurrences(of: ">", with: "&gt;")
        }

        let pb = "\n\n<div class=\"page-break\"></div>\n\n"

        // Title page (single HTML line so div passthrough captures it atomically)
        var tp = "<div class=\"title-page\">"
        tp += "<p class=\"tp-app\">Process Mining Demonstrator</p>"
        tp += "<h1>\(esc(project.title))</h1>"
        tp += "<p class=\"tp-sub\">AI-Supported Process Documentation</p>"
        tp += "<hr class=\"tp-rule\">"
        tp += "<p class=\"tp-meta\">\(esc(vm.aChartFilterSummary))</p>"
        if let date = vm.llmAnalysisDate {
            tp += "<p class=\"tp-meta\">Generated: \(date.formatted(date: .long, time: .shortened))</p>"
        }
        tp += "</div>"

        // HTML chapter heading with anchor id (single line — captured by div passthrough)
        func chHead(_ n: Int, _ title: String) -> String {
            "<div id=\"ch\(n)\"><h2>\(n). \(title)</h2></div>"
        }

        // Replace a section's leading "## …" line with an HTML chapter heading that carries an id
        func replaceHeading(_ content: String, n: Int, title: String) -> String {
            let s = content.trimmingCharacters(in: .newlines)
            let head = chHead(n, title)
            if s.hasPrefix("## ") {
                if let nl = s.firstIndex(of: "\n") { return head + String(s[nl...]) }
                return head
            }
            return head + "\n\n" + s
        }

        // Build chapter list in order (title + optional section content)
        var chapters: [(title: String, content: String?)] = [("AI Analysis", nil)]
        if !vm.llmJourneyPathsSummary.isEmpty  { chapters.append(("Journey Paths",          vm.llmJourneyPathsSummary)) }
        if !vm.llmHappyPathSummary.isEmpty     { chapters.append(("Happy Path Conformance", vm.llmHappyPathSummary)) }
        if !vm.llmConformanceSummary.isEmpty   { chapters.append(("Conformance Check",      vm.llmConformanceSummary)) }
        if !vm.projectNotes.isEmpty            { chapters.append(("User Comments",          notesMarkdownSection)) }
        chapters.append(("Analysis Parameters", analysisParametersSection))

        // TOC — HTML div so it is caught by the div passthrough; toc-pg spans are filled by JS
        var tocHTML = "<div class=\"toc\"><h2>Table of Contents</h2><ol>"
        for (idx, ch) in chapters.enumerated() {
            let n = idx + 1
            tocHTML += "<li><a href=\"#ch\(n)\">\(n). \(ch.title)</a>"
            tocHTML += "<span id=\"toc-pg-\(n)\" class=\"toc-pg\"></span></li>"
        }
        tocHTML += "</ol></div>"

        // Assemble: title → TOC → chapters, each on its own page
        var doc = tp + pb + tocHTML + pb + chHead(1, "AI Analysis") + "\n\n" + result.trimmingCharacters(in: .newlines)

        for (idx, chapter) in chapters.dropFirst().enumerated() {
            let n = idx + 2
            if let content = chapter.content {
                doc += pb + replaceHeading(content, n: n, title: chapter.title)
            }
        }
        return doc
    }

    @ViewBuilder
    private var aiAnalysisContent: some View {
        if vm.isLLMAnalyzing {
            VStack(spacing: 20) {
                ZStack {
                    Circle()
                        .stroke(Color.accentColor.opacity(0.15), lineWidth: 3)
                        .frame(width: 64, height: 64)
                    ProgressView()
                        .controlSize(.large)
                        .tint(.accentColor)
                }
                Text("AI is analyzing")
                    .font(.callout)
                    .foregroundStyle(.secondary)
                Text(vm.aChartFilterSummary)
                    .font(.caption)
                    .foregroundStyle(.tertiary)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, 32)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        } else if vm.selectedProject == nil {
            ContentUnavailableView(
                "No Project Selected",
                systemImage: "flowchart",
                description: Text("Select a project from the sidebar.")
            )
        } else if vm.llmAnalysisResult != nil {
            VStack(spacing: 0) {
                // Context bar: shows what filters were used + re-run button
                HStack(spacing: 8) {
                    Image(systemName: "line.3.horizontal.decrease.circle")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Text(vm.aChartFilterSummary)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                    Spacer(minLength: 0)
                    Button {
                        Task { await vm.runLLMAnalysis() }
                    } label: {
                        Label("Re-run", systemImage: "arrow.clockwise")
                    }
                    .buttonStyle(.bordered)
                    .controlSize(.mini)
                    .disabled(!db.isLLMReachable)
                }
                .padding(.horizontal, 16)
                .padding(.vertical, 8)
                .background(Color(.secondarySystemGroupedBackground))

                Divider()

                MarkdownView(markdown: reportDocument)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        } else if let error = vm.llmAnalysisError {
            VStack(spacing: 20) {
                ContentUnavailableView(
                    "Analysis Failed",
                    systemImage: "exclamationmark.triangle",
                    description: Text(error)
                )
                Button {
                    Task { await vm.runLLMAnalysis() }
                } label: {
                    Label("Try Again", systemImage: "arrow.clockwise")
                }
                .buttonStyle(.borderedProminent)
                .disabled(!db.isLLMReachable)
            }
        } else {
            // No analysis yet — show brain icon, filter context card, and run button
            VStack(spacing: 24) {
                Image(systemName: "brain")
                    .font(.system(size: 60))
                    .foregroundStyle(.secondary.opacity(0.35))

                VStack(alignment: .leading, spacing: 6) {
                    Label("A-Chart filters in use", systemImage: "line.3.horizontal.decrease.circle")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(.secondary)
                    Text(vm.aChartFilterSummary)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                .padding(14)
                .frame(maxWidth: 340, alignment: .leading)
                .background(Color(.secondarySystemGroupedBackground),
                            in: RoundedRectangle(cornerRadius: 10, style: .continuous))
                .overlay(
                    RoundedRectangle(cornerRadius: 10, style: .continuous)
                        .strokeBorder(Color.primary.opacity(0.10), lineWidth: 1)
                )

                // Happy Path notice card
                VStack(alignment: .leading, spacing: 6) {
                    Label("Happy Path Conformance",
                          systemImage: "signpost.right.fill")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(vm.happyPaths.isEmpty ? Color.orange : Color.secondary)
                    if vm.happyPaths.isEmpty {
                        Text("No Happy Paths defined — conformance data will not be included. Create one in the Happy Path view to enrich the analysis.")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    } else {
                        let count = vm.happyPaths.count
                        Text("\(count) path\(count == 1 ? "" : "s") will be evaluated: \(vm.happyPaths.map(\.name).joined(separator: ", "))")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
                .padding(14)
                .frame(maxWidth: 340, alignment: .leading)
                .background(Color(.secondarySystemGroupedBackground),
                            in: RoundedRectangle(cornerRadius: 10, style: .continuous))
                .overlay(
                    RoundedRectangle(cornerRadius: 10, style: .continuous)
                        .strokeBorder(
                            vm.happyPaths.isEmpty ? Color.orange.opacity(0.45) : Color.primary.opacity(0.10),
                            lineWidth: 1)
                )

                // Conformance norms notice card
                let allNormCount = vm.targetNorms.values.reduce(0) { $0 + $1.count }
                let metricNormCount = vm.targetNorms.filter { !$0.value.isEmpty }.count
                VStack(alignment: .leading, spacing: 6) {
                    Label("Conformance Check", systemImage: "checkmark.shield.fill")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(allNormCount == 0 ? Color.orange : Color.secondary)
                    if allNormCount == 0 {
                        Text("No norms defined — gap analysis will not be included. Open Conformance Check and tap edges (Edit mode) to define target values.")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    } else {
                        Text("\(allNormCount) norm\(allNormCount == 1 ? "" : "s") across \(metricNormCount) metric\(metricNormCount == 1 ? "" : "s") — gap analysis will be appended to the report.")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
                .padding(14)
                .frame(maxWidth: 340, alignment: .leading)
                .background(Color(.secondarySystemGroupedBackground),
                            in: RoundedRectangle(cornerRadius: 10, style: .continuous))
                .overlay(
                    RoundedRectangle(cornerRadius: 10, style: .continuous)
                        .strokeBorder(
                            allNormCount == 0 ? Color.orange.opacity(0.45) : Color.primary.opacity(0.10),
                            lineWidth: 1)
                )

                Button {
                    Task { await vm.runLLMAnalysis() }
                } label: {
                    Label("AI supported Documentation", systemImage: "brain")
                        .frame(minWidth: 200)
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.regular)
                .disabled(vm.selectedProject == nil || !db.isLLMReachable)

                if !db.isLLMReachable {
                    Label("LLM server not reachable. Check your connection profile.",
                          systemImage: "exclamationmark.triangle")
                        .font(.caption)
                        .foregroundStyle(.orange)
                        .multilineTextAlignment(.center)
                        .frame(maxWidth: 300)
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
    }

    // MARK: - Notes (comments) view

    @ViewBuilder
    private var commentsContent: some View {
        if vm.projectNotes.isEmpty {
            ContentUnavailableView(
                "No Notes",
                systemImage: "note.text",
                description: Text("Tap-hold a node or edge to add a note.")
            )
        } else {
            List {
                ForEach(vm.projectNotes.sorted { $0.createdAt > $1.createdAt }) { note in
                    Button {
                        noteEditorItem = NoteEditorItem(
                            target:         note.target,
                            existingNote:   note,
                            filterSnapshot: note.filterSnapshot
                        )
                    } label: {
                        VStack(alignment: .leading, spacing: 5) {
                            HStack(spacing: 6) {
                                Image(systemName: note.target.isNode ? "circle.fill" : "arrow.right.circle.fill")
                                    .foregroundStyle(.yellow)
                                    .font(.caption)
                                Text(note.target.displayName)
                                    .font(.subheadline.weight(.semibold))
                                if !note.username.isEmpty {
                                    Text("· \(note.username)")
                                        .font(.caption)
                                        .foregroundStyle(.secondary)
                                }
                                if note.isShared {
                                    Image(systemName: "person.2.fill")
                                        .font(.caption2)
                                        .foregroundStyle(.teal)
                                }
                                Spacer()
                                Text(note.createdAt, format: .dateTime.day().month(.abbreviated).hour().minute())
                                    .font(.caption2)
                                    .foregroundStyle(.secondary)
                            }
                            Text(note.text)
                                .font(.subheadline)
                                .foregroundStyle(.primary)
                                .lineLimit(3)
                            if let editedAt = note.editedAt {
                                let editorNote = !note.lastEditedBy.isEmpty && note.lastEditedBy != note.username
                                    ? "Edited by \(note.lastEditedBy) · \(editedAt.formatted(date: .abbreviated, time: .shortened))"
                                    : "Edited \(editedAt.formatted(date: .abbreviated, time: .shortened))"
                                Text(editorNote)
                                    .font(.caption2)
                                    .foregroundStyle(.secondary)
                                    .italic()
                            }
                            Text(note.filterSnapshot.summaryText)
                                .font(.caption2)
                                .foregroundStyle(.secondary)
                                .lineLimit(1)
                        }
                        .padding(.vertical, 2)
                    }
                    .buttonStyle(.plain)
                    .swipeActions(edge: .trailing) {
                        Button(role: .destructive) { Task { await vm.deleteNote(note) } } label: {
                            Label("Delete", systemImage: "trash")
                        }
                    }
                }
            }
        }
    }

    // MARK: - Conformance Check view

    // MARK: - Compliance KPI strip

    private var complianceKPIStrip: some View {
        let norms = vm.currentMetricNorms
        let isCountPct = vm.targetMetric == .count
        let transitions = vm.processGraph.transitions.filter { $0.fromStep != $0.toStep }
        // Pre-compute per-node outgoing totals for count%
        var outgoing: [String: Int] = [:]
        if isCountPct {
            for t in transitions { outgoing[t.fromStep, default: 0] += t.occurrences }
        }
        var violations = 0, compliant = 0, noNorm = 0
        for t in transitions {
            let actual: Double = isCountPct
                ? { let tot = outgoing[t.fromStep] ?? 1
                    return Double(t.occurrences) / Double(tot) * 100.0 }()
                : (t.metricValue(for: vm.targetMetric) ?? Double(t.occurrences))
            if let norm = norms[t.id] {
                let isViolation = normIsMinimum ? actual < norm : actual > norm
                if isViolation { violations += 1 } else { compliant += 1 }
            } else { noNorm += 1 }
        }
        let normedCount = violations + compliant
        let rate: Double? = normedCount > 0 ? Double(compliant) / Double(normedCount) : nil

        return ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 12) {
                if let rate {
                    complianceKPITile(
                        value: rate.formatted(.percent.precision(.fractionLength(0))),
                        label: "Conformance",
                        icon: "checkmark.shield.fill",
                        color: rate >= 0.7 ? .green : rate >= 0.3 ? .orange : .red)
                }
                if normedCount > 0 {
                    complianceKPITile(value: "\(violations)", label: "Violations",
                                     icon: "xmark.circle.fill",
                                     color: violations > 0 ? .red : Color.secondary)
                    complianceKPITile(value: "\(compliant)", label: "Compliant",
                                     icon: "checkmark.circle.fill",
                                     color: compliant > 0 ? .green : Color.secondary)
                }
                complianceKPITile(value: "\(noNorm)", label: "No Norm",
                                  icon: "circle.dashed", color: .secondary)
                if norms.isEmpty {
                    HStack(spacing: 6) {
                        Image(systemName: "info.circle").font(.caption).foregroundStyle(.secondary)
                        Text("Tap any edge in the right panel (Edit mode) to define norm values.")
                            .font(.caption).foregroundStyle(.secondary)
                    }
                    .padding(.horizontal, 4)
                }
            }
            .padding(.horizontal, 20)
            .padding(.vertical, 12)
        }
        .background(Color(.systemBackground))
    }

    private func complianceKPITile(value: String, label: String,
                                   icon: String, color: Color) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 5) {
                Image(systemName: icon).font(.caption2).foregroundStyle(color)
                Text(label).font(.caption2).foregroundStyle(.secondary).lineLimit(1)
            }
            Text(value)
                .font(.title3.weight(.semibold))
                .monospacedDigit()
                .lineLimit(1)
                .minimumScaleFactor(0.65)
                .foregroundStyle(color)
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 10)
        .background(Color(.secondarySystemGroupedBackground),
                    in: RoundedRectangle(cornerRadius: 10, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 10, style: .continuous)
            .strokeBorder(Color.primary.opacity(0.10), lineWidth: 1))
    }

    @ViewBuilder
    private var complianceCheckContent: some View {
        if vm.selectedProject == nil {
            ContentUnavailableView(
                "No Project Selected",
                systemImage: "flowchart",
                description: Text("Select a project from the sidebar.")
            )
        } else {
            VStack(spacing: 0) {
                // Header: mode toggle + gap table
                HStack(spacing: 0) {
                    filterGroupMenu(selectedId: vm.selectedFilterGroupId) { group in
                        vm.applyFilterGroup(group)
                        complianceSliderFrom = group.fromDate
                        complianceSliderTo   = group.toDate
                        Task { await vm.reloadGraph() }
                    }
                    .padding(.horizontal, 8)

                    Divider().frame(height: 36)

                    Picker("Mode", selection: $complianceEditMode) {
                        Label("Edit", systemImage: "pencil").tag(true)
                        Label("Execution", systemImage: "play.circle.fill").tag(false)
                    }
                    .pickerStyle(.segmented)
                    .frame(width: 190)
                    .padding(.horizontal, 12)
                    .padding(.vertical, 8)

                    Divider().frame(height: 36)

                    Button {
                        withAnimation(.easeInOut(duration: 0.2)) { showGapTable.toggle() }
                    } label: {
                        HStack(spacing: 4) {
                            Image(systemName: "tablecells").font(.caption2)
                            Text("Gap Table").font(.caption2.weight(.medium))
                        }
                        .padding(.horizontal, 8)
                        .padding(.vertical, 5)
                        .background(showGapTable ? Color.accentColor : Color.primary.opacity(0.07))
                        .foregroundStyle(showGapTable ? Color.white : Color.primary)
                        .clipShape(Capsule())
                    }
                    .buttonStyle(.plain)
                    .disabled(vm.processGraph.transitions.isEmpty)
                    .padding(.horizontal, 8)
                }
                .background(Color(.secondarySystemGroupedBackground))

                Divider()

                // Collapsible Conformance KPI strip
                if !vm.processGraph.transitions.isEmpty {
                    VStack(spacing: 0) {
                        Button {
                            withAnimation(.easeInOut(duration: 0.2)) { complianceKpiExpanded.toggle() }
                        } label: {
                            HStack(spacing: 6) {
                                Image(systemName: complianceKpiExpanded ? "chevron.down" : "chevron.right")
                                    .font(.caption2.weight(.semibold))
                                    .foregroundStyle(.secondary)
                                Text("Conformance KPIs")
                                    .font(.caption2.weight(.medium))
                                    .foregroundStyle(.secondary)
                                Spacer(minLength: 0)
                            }
                            .padding(.horizontal, 12)
                            .padding(.vertical, 7)
                            .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                        if complianceKpiExpanded {
                            Divider().padding(.horizontal, 8)
                            complianceKPIStrip
                        }
                    }
                    .background(Color(.secondarySystemGroupedBackground))
                    Divider()
                }

                // Collapsible date & metrics card
                VStack(spacing: 0) {
                    HStack(spacing: 0) {
                        Button {
                            withAnimation(.easeInOut(duration: 0.2)) { complianceControlsExpanded.toggle() }
                        } label: {
                            HStack(spacing: 6) {
                                Image(systemName: complianceControlsExpanded ? "chevron.down" : "chevron.right")
                                    .font(.caption2.weight(.semibold))
                                    .foregroundStyle(.secondary)
                                Text("Date & Metrics")
                                    .font(.caption2.weight(.medium))
                                    .foregroundStyle(.secondary)
                                Spacer(minLength: 0)
                            }
                            .padding(.horizontal, 12)
                            .padding(.vertical, 7)
                            .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                    }
                    if complianceControlsExpanded {
                        Divider().padding(.horizontal, 8)
                        JourneyTimeSlider(
                            rangeMin: sliderRangeMin,
                            rangeMax: vm.initialToDate,
                            mode:     sliderMode,
                            fromDate: $complianceSliderFrom,
                            toDate:   $complianceSliderTo,
                            onCommit: { from, to in
                                if sliderMode == .singleDay {
                                    Task {
                                        if let actual = await vm.reloadGraphForDay(from), actual != from {
                                            complianceSliderFrom = actual; complianceSliderTo = actual
                                        }
                                    }
                                } else {
                                    vm.fromDate = from; vm.toDate = to
                                    Task { await vm.reloadGraph() }
                                }
                            }
                        )
                        Divider().padding(.horizontal, 8)
                        ScrollView(.horizontal, showsIndicators: false) {
                            HStack(spacing: 6) {
                                ForEach(TransitionMetric.allCases) { m in
                                    let selected = vm.targetMetric == m
                                    Button { vm.setTargetMetric(m) } label: {
                                        HStack(spacing: 4) {
                                            Image(systemName: m.icon).font(.caption2)
                                            Text(m == .count ? "Count %" : m.rawValue)
                                                .font(.caption2.weight(.medium)).lineLimit(1)
                                        }
                                        .padding(.horizontal, 8)
                                        .padding(.vertical, 5)
                                        .background(selected ? Color.accentColor : Color.primary.opacity(0.07))
                                        .foregroundStyle(selected ? Color.white : Color.primary)
                                        .clipShape(Capsule())
                                    }
                                    .buttonStyle(.plain)
                                    .disabled(vm.processGraph.transitions.isEmpty)
                                }
                            }
                            .padding(.horizontal, 12)
                            .padding(.vertical, 7)
                        }
                        .background(Color(.secondarySystemGroupedBackground))
                        Divider().padding(.horizontal, 8)
                        // Norm direction toggle: norm is a ceiling (max) or a floor (min)
                        HStack(spacing: 8) {
                            Image(systemName: "arrow.up.arrow.down.circle")
                                .font(.caption2)
                                .foregroundStyle(.secondary)
                            Text("Norm is")
                                .font(.caption2)
                                .foregroundStyle(.secondary)
                            HStack(spacing: 4) {
                                Button {
                                    withAnimation(.easeInOut(duration: 0.15)) { normIsMinimum = false }
                                } label: {
                                    Text("Max \u{2264}")
                                        .font(.caption2.weight(.medium))
                                        .padding(.horizontal, 8)
                                        .padding(.vertical, 5)
                                        .background(!normIsMinimum ? Color.accentColor : Color.primary.opacity(0.07))
                                        .foregroundStyle(!normIsMinimum ? Color.white : Color.primary)
                                        .clipShape(Capsule())
                                }
                                .buttonStyle(.plain)
                                Button {
                                    withAnimation(.easeInOut(duration: 0.15)) { normIsMinimum = true }
                                } label: {
                                    Text("Min \u{2265}")
                                        .font(.caption2.weight(.medium))
                                        .padding(.horizontal, 8)
                                        .padding(.vertical, 5)
                                        .background(normIsMinimum ? Color.accentColor : Color.primary.opacity(0.07))
                                        .foregroundStyle(normIsMinimum ? Color.white : Color.primary)
                                        .clipShape(Capsule())
                                }
                                .buttonStyle(.plain)
                            }
                            Spacer(minLength: 0)
                        }
                        .padding(.horizontal, 12)
                        .padding(.vertical, 7)
                        .background(Color(.secondarySystemGroupedBackground))
                    }
                }
                .background(Color(.secondarySystemGroupedBackground),
                             in: RoundedRectangle(cornerRadius: 10, style: .continuous))
                .overlay(
                    RoundedRectangle(cornerRadius: 10, style: .continuous)
                        .strokeBorder(Color.primary.opacity(0.10), lineWidth: 1)
                )
                .padding(.horizontal, 12)
                .padding(.top, 10)
                .padding(.bottom, 6)

                HStack(spacing: 0) {
                    // Left: actual process (with compliance coloring in execution mode)
                    VStack(spacing: 0) {
                        HStack {
                            Text("Actual Process")
                                .font(.caption.weight(.semibold))
                                .foregroundStyle(.secondary)
                                .padding(.leading, 12)
                                .padding(.vertical, 7)
                            Spacer()
                            if let count = vm.journeyCount {
                                Text("\(count.formatted()) journeys")
                                    .font(.caption2.monospacedDigit())
                                    .foregroundStyle(.secondary)
                                    .padding(.trailing, 12)
                            }
                        }
                        .background(Color(.secondarySystemGroupedBackground))
                        Divider()

                        if vm.processGraph.transitions.isEmpty {
                            if vm.isLoading {
                                ProgressView("Loading process map\u{2026}")
                                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                            } else {
                                ContentUnavailableView {
                                    Label("No Process Data", systemImage: "chart.xyaxis.line")
                                } description: {
                                    Text("Apply filters to load the process map.")
                                } actions: {
                                    Button("Load") { Task { await vm.reloadGraph() } }
                                        .buttonStyle(.borderedProminent)
                                }
                            }
                        } else {
                            let complianceKey = "compliance_\(vm.selectedProject?.projectId ?? "")"
                            FlowChartView(
                                graph: vm.processGraph,
                                projectId: vm.selectedProject?.projectId ?? "",
                                chartMode: complianceKey,
                                metric: vm.targetMetric,
                                isLoading: vm.isLoading,
                                syncState: complianceSyncState,
                                onNodeAction: handleNodeAction,
                                normValues: complianceEditMode ? nil : vm.currentMetricNorms,
                                normMetric: vm.targetMetric,
                                showCompliance: !complianceEditMode,
                                normIsMinimum: normIsMinimum,
                                notes:            vm.projectNotes,
                                ownNoteNodeNames: myNoteNodeNames,
                                onNodeNote:       handleNodeNoteEdit
                            )
                            .id(vm.selectedProject?.projectId)
                            .overlay(alignment: .top) {
                                if vm.isLoading {
                                    ProgressView()
                                        .padding(.horizontal, 16)
                                        .padding(.vertical, 8)
                                        .background(.regularMaterial, in: Capsule())
                                        .padding(.top, 12)
                                        .transition(.opacity)
                                }
                            }
                        }
                    }
                    .frame(maxWidth: .infinity)

                    Divider()

                    // Right: target process norm editor — same syncState and chartMode key as left
                    VStack(spacing: 0) {
                        HStack {
                            Text("Target Process")
                                .font(.caption.weight(.semibold))
                                .foregroundStyle(.secondary)
                                .padding(.leading, 12)
                                .padding(.vertical, 7)
                            Spacer()
                            let normCount = vm.currentMetricNorms.count
                            if normCount > 0 {
                                Text("\(normCount) norms")
                                    .font(.caption2.monospacedDigit())
                                    .foregroundStyle(.secondary)
                                    .padding(.trailing, 12)
                            }
                        }
                        .background(Color(.secondarySystemGroupedBackground))
                        Divider()
                        TargetProcessView(
                            vm: vm,
                            showMetricSelector: false,
                            showEditControls: complianceEditMode,
                            syncState: complianceSyncState,
                            skipInitialFit: true,
                            chartModeKey: "compliance_\(vm.selectedProject?.projectId ?? "")"
                        )
                    }
                    .frame(maxWidth: .infinity)
                }

                if showGapTable {
                    Divider()
                    GapAnalysisTableView(
                        graph: vm.processGraph,
                        norms: vm.currentMetricNorms,
                        metric: vm.targetMetric,
                        normIsMinimum: normIsMinimum
                    )
                    .frame(height: 256)
                    .transition(.move(edge: .bottom).combined(with: .opacity))
                }
            }
        }
    }

    // MARK: - A/B layout copy

    private func copyLayoutAtoB() {
        guard let projectId = vm.selectedProject?.projectId else { return }
        // Persist A's node overrides to B's UserDefaults key for future cold starts
        let aKey = "layout_\(projectId)_A-Chart"
        let bKey = "layout_\(projectId)_B-Chart"
        if let data = UserDefaults.standard.data(forKey: aKey) {
            UserDefaults.standard.set(data, forKey: bKey)
        } else {
            UserDefaults.standard.removeObject(forKey: bKey)
        }
        // Snapshot A's live zoom, pan, and node overrides so B recreates with A's exact viewport.
        // Setting bInitialState to a non-nil snapshot ensures skipInitialFit = true, which
        // prevents fitToView from resetting the zoom/pan when B is reconstructed.
        let snap = ABSyncState()
        snap.copyValues(from: abSyncState)
        bInitialState = snap
        bStateId      = UUID()
        bLayoutSeed   = UUID()
    }

    // MARK: - Share / Export

    private var canShare: Bool {
        switch vm.activeChartMode {
        case .aChart, .bChart, .individualJourney:
            return !vm.processGraph.transitions.isEmpty
        case .abComparison:
            return !vm.abGraphA.transitions.isEmpty || !vm.abGraphB.transitions.isEmpty
        case .aiAnalysis:
            return vm.llmAnalysisResult != nil
        case .statistics, .complianceCheck, .happyPath, .comments, .simulation:
            return false
        }
    }

    @MainActor
    private func exportPDF() async {
        guard let project = vm.selectedProject else { return }
        isExporting = true
        defer { isExporting = false }

        let data: Data?
        switch vm.activeChartMode {
        case .aChart, .bChart, .individualJourney:
            data = chartPDF(graph: vm.processGraph,
                            projectId: project.projectId,
                            chartMode: vm.activeChartMode.rawValue,
                            metric: vm.transitionMetric)
        case .abComparison:
            data = abComparisonPDF(projectId: project.projectId)
        case .aiAnalysis:
            if vm.llmAnalysisResult != nil {
                data = await MarkdownView.generatePDF(markdown: reportDocument)
            } else { data = nil }
        case .statistics, .complianceCheck, .happyPath, .comments, .simulation:
            data = nil
        }

        guard let pdf = data else { return }
        let name = project.title + " – " + vm.activeChartMode.rawValue
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent(name.replacingOccurrences(of: "/", with: "-") + ".pdf")
        try? pdf.write(to: url)
        pdfShareURL = url
    }

    @MainActor
    private func chartPDF(graph: ProcessGraph, projectId: String, chartMode: String, metric: TransitionMetric = .count) -> Data? {
        #if os(iOS)
        let canvasSize = FlowChartView.exportCanvasSize(graph: graph, projectId: projectId, chartMode: chartMode)

        let exportView = FlowChartView(graph: graph, projectId: projectId,
                                       chartMode: chartMode, forExport: true, metric: metric)
            .frame(width: canvasSize.width, height: canvasSize.height)
            .background(Color(.systemBackground))

        let renderer = ImageRenderer(content: exportView)
        renderer.scale = 2.0
        guard let image = renderer.uiImage else { return nil }

        let pageRect = CGRect(origin: .zero, size: canvasSize)
        let pdfRenderer = UIGraphicsPDFRenderer(bounds: pageRect)
        return pdfRenderer.pdfData { ctx in
            ctx.beginPage()
            image.draw(in: pageRect)
        }
        #else
        let canvasSize = FlowChartView.exportCanvasSize(graph: graph, projectId: projectId, chartMode: chartMode)
        let exportView = FlowChartView(graph: graph, projectId: projectId,
                                       chartMode: chartMode, forExport: true, metric: metric)
            .frame(width: canvasSize.width, height: canvasSize.height)
            .background(Color(.systemBackground))
        let renderer = ImageRenderer(content: exportView)
        renderer.scale = 2.0
        return renderViewsToPDF([(renderer, canvasSize)])
        #endif
    }

    @MainActor
    private func abComparisonPDF(projectId: String) -> Data? {
        #if os(iOS)
        var pages: [(UIImage, CGSize)] = []
        for (graph, mode, metric) in [
            (vm.abGraphA, "A-Chart", vm.abMetricA),
            (vm.abGraphB, "B-Chart", vm.abMetricB)
        ] where !graph.transitions.isEmpty {
            let canvasSize = FlowChartView.exportCanvasSize(graph: graph, projectId: projectId, chartMode: mode)
            let exportView = FlowChartView(graph: graph, projectId: projectId,
                                           chartMode: mode, forExport: true, metric: metric)
                .frame(width: canvasSize.width, height: canvasSize.height)
                .background(Color(.systemBackground))
            let r = ImageRenderer(content: exportView)
            r.scale = 2.0
            if let img = r.uiImage { pages.append((img, canvasSize)) }
        }
        guard !pages.isEmpty else { return nil }
        let defaultBounds = CGRect(origin: .zero, size: pages[0].1)
        let pdfRenderer = UIGraphicsPDFRenderer(bounds: defaultBounds)
        return pdfRenderer.pdfData { ctx in
            for (img, size) in pages {
                ctx.beginPage(withBounds: CGRect(origin: .zero, size: size), pageInfo: [:])
                img.draw(in: CGRect(origin: .zero, size: size))
            }
        }
        #else
        let specs: [(ProcessGraph, String, TransitionMetric)] = [
            (vm.abGraphA, "A-Chart", vm.abMetricA),
            (vm.abGraphB, "B-Chart", vm.abMetricB)
        ].filter { !$0.0.transitions.isEmpty }
        let pages = specs.map { spec -> (ImageRenderer<AnyView>, CGSize) in
            let canvasSize = FlowChartView.exportCanvasSize(graph: spec.0, projectId: projectId, chartMode: spec.1)
            let view = FlowChartView(graph: spec.0, projectId: projectId,
                                     chartMode: spec.1, forExport: true, metric: spec.2)
                .frame(width: canvasSize.width, height: canvasSize.height)
                .background(Color(.systemBackground))
            let r = ImageRenderer(content: AnyView(view))
            r.scale = 2.0
            return (r, canvasSize)
        }
        return renderViewsToPDF(pages)
        #endif
    }

    // MARK: - KPI panel

    private var journeyScoreSum: Int? {
        let scores = vm.processGraph.steps.values.compactMap(\.score)
        return scores.isEmpty ? nil : scores.reduce(0, +)
    }

    private func formatSecs(_ secs: Double?) -> String {
        guard let secs, secs >= 0 else { return "—" }
        let s = Int(secs.rounded())
        if s < 60   { return "\(s)s" }
        if s < 3600 { return "\(s / 60)m \(s % 60)s" }
        let h = s / 3600; let m = (s % 3600) / 60
        if s < 86400 { return "\(h)h \(m)m" }
        let d = s / 86400; let rh = (s % 86400) / 3600
        return "\(d)d \(rh)h"
    }

    private var journeyDurationString: String? {
        guard let start = vm.journeyDate, let end = vm.journeyEndDate else { return nil }
        let secs = Int(end.timeIntervalSince(start).rounded())
        guard secs >= 0 else { return nil }
        let h = secs / 3600
        let m = (secs % 3600) / 60
        let s = secs % 60
        if h > 0 { return "\(h)h \(m)m" }
        if m > 0 { return "\(m)m \(s)s" }
        return "\(s)s"
    }

    private var journeyStepStats: (total: Int, distinct: Int)? {
        guard !vm.processGraph.transitions.isEmpty else { return nil }
        let total = vm.processGraph.transitions.reduce(0) { $0 + $1.occurrences } + 1
        return (total, vm.processGraph.steps.count)
    }

    // Sum of (score × journey visits) for every scored node in the graph.
    // Visit count per node = max(incoming occurrences, outgoing occurrences)
    // so both start nodes (no incoming) and end nodes (no outgoing) are handled.
    private func graphValue(for graph: ProcessGraph) -> Int? {
        guard !graph.transitions.isEmpty else { return nil }
        var incoming: [String: Int] = [:]
        var outgoing: [String: Int] = [:]
        for t in graph.transitions {
            incoming[t.toStep,   default: 0] += t.occurrences
            outgoing[t.fromStep, default: 0] += t.occurrences
        }
        var total = 0
        var hasScore = false
        for (name, step) in graph.steps {
            guard let score = step.score else { continue }
            let visits = max(incoming[name] ?? 0, outgoing[name] ?? 0)
            guard visits > 0 else { continue }
            total += score * visits
            hasScore = true
        }
        return hasScore ? total : nil
    }

    private var kpiPanel: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 12) {
                switch vm.activeChartMode {
                case .individualJourney:
                    kpiTile(value: vm.journeyDate.map { $0.formatted(date: .abbreviated, time: .omitted) } ?? "—",
                            label: "Date", icon: "calendar", loading: vm.isLoading)
                    kpiTile(value: journeyDurationString ?? "—",
                            label: "Duration", icon: "timer", loading: vm.isLoading)
                    kpiTile(value: journeyScoreSum.map { $0.formatted(.number.sign(strategy: .always())) } ?? "—",
                            label: "Sum of Scores", icon: "function", loading: vm.isLoading)
                    if let s = journeyStepStats {
                        kpiTile(value: "\(s.total) / \(s.distinct)",
                                label: "Steps visited / distinct", icon: "arrow.triangle.branch",
                                loading: vm.isLoading)
                    }
                    if let title = vm.meta1Title, let val = vm.journeyMeta1 {
                        kpiTile(value: val, label: title, icon: "tag", loading: false)
                    }
                    if let title = vm.meta2Title, let val = vm.journeyMeta2 {
                        kpiTile(value: val, label: title, icon: "tag", loading: false)
                    }
                    if let title = vm.meta3Title, let val = vm.journeyMeta3 {
                        kpiTile(value: val, label: title, icon: "tag", loading: false)
                    }

                case .abComparison:
                    EmptyView()

                default:
                    ForEach(orderedKPIIds, id: \.self) { id in
                        singleChartKPITile(id: id)
                    }
                }
            }
            .padding(.horizontal, 20)
            .padding(.vertical, 14)
        }
        .background(Color(.systemBackground))
    }

    private func kpiTile(value: String, label: String, icon: String, loading: Bool,
                         valueColor: Color = .primary) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 5) {
                Image(systemName: icon)
                    .font(.caption2)
                    .foregroundStyle(valueColor == .primary ? Color.accentColor : valueColor)
                Text(label)
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
            if loading {
                ProgressView().controlSize(.small)
                    .frame(height: 26)
            } else {
                Text(value)
                    .font(.title3.weight(.semibold))
                    .monospacedDigit()
                    .lineLimit(1)
                    .minimumScaleFactor(0.65)
                    .foregroundStyle(valueColor)
            }
        }
        .padding(12)
        .frame(minWidth: 110, alignment: .leading)
        .background(Color(.secondarySystemGroupedBackground),
                    in: RoundedRectangle(cornerRadius: 10, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 10, style: .continuous)
                .strokeBorder(valueColor == .primary ? Color.primary.opacity(0.10) : valueColor.opacity(0.40),
                              lineWidth: valueColor == .primary ? 1 : 1.5)
        )
    }

    // MARK: - Ordered KPI tile renderers

    @ViewBuilder
    private func abPanelKPITile(
        id: String, side: ABSide, graph: ProcessGraph,
        journeyCount: Int?, minDur: Double?, avgDur: Double?,
        stdDevDur: Double?, maxDur: Double?,
        isSideLoading: Bool, isActive: Bool
    ) -> some View {
        let panelGoodness = side == .a ? vm.abGoodnessA : vm.abGoodnessB
        let otherGoodness = side == .a ? vm.abGoodnessB : vm.abGoodnessA
        let sampleSet     = side == .a ? vm.activeSampleSetA : vm.activeSampleSetB
        let sampleCnt     = vm.sampleCounts[sampleSet] ?? (sampleSet.isOriginal ? vm.totalJourneyCount : nil)
        switch id {
        case "totalJourneys" where kpiShowTotalJourneys:
            kpiTile(value: vm.totalJourneyCount.map { $0.formatted() } ?? "—",
                    label: "Total Journeys", icon: "person.2.fill",
                    loading: isSideLoading && vm.totalJourneyCount == nil)
        case "filteredJourneys" where kpiShowFilteredJourneys:
            kpiTile(value: journeyCount.map { $0.formatted() } ?? "—",
                    label: "Filtered Journeys", icon: "line.3.horizontal.decrease.circle.fill",
                    loading: isSideLoading && journeyCount == nil)
        case "shortestJourney" where kpiShowShortestJourney:
            kpiTile(value: formatSecs(minDur), label: "Shortest Journey", icon: "hare",              loading: isSideLoading)
        case "avgJourney" where kpiShowAvgJourney:
            kpiTile(value: formatSecs(avgDur), label: "Avg Journey",      icon: "timer",             loading: isSideLoading)
        case "stdDev" where kpiShowStdDev:
            kpiTile(value: formatSecs(stdDevDur), label: "Std Dev",       icon: "waveform.path.ecg", loading: isSideLoading)
        case "longestJourney" where kpiShowLongestJourney:
            kpiTile(value: formatSecs(maxDur), label: "Longest Journey",  icon: "tortoise",          loading: isSideLoading)
        case "graphValue" where kpiShowGraphValue:
            if let val = graphValue(for: graph) {
                kpiTile(value: val.formatted(.number.sign(strategy: .always())),
                        label: "Graph Value", icon: "function", loading: isSideLoading)
            }
        case "processGoodness" where kpiShowProcessGoodness:
            if let val = panelGoodness {
                let gc: Color = {
                    guard let other = otherGoodness else { return .primary }
                    if abs(val - other) < 0.005 { return .blue }
                    return val > other ? .green : .red
                }()
                kpiTile(value: val.formatted(.number.precision(.fractionLength(2)).sign(strategy: .always())),
                        label: "Process Goodness", icon: "gauge.high",
                        loading: vm.isLoading && isActive, valueColor: gc)
            }
        case "activeSample" where kpiShowActiveSample:
            kpiTile(value: sampleCnt?.formatted() ?? "—",
                    label: sampleSet.shortLabel, icon: "square.3.layers.3d", loading: false)
        default:
            EmptyView()
        }
    }

    @ViewBuilder
    private func singleChartKPITile(id: String) -> some View {
        switch id {
        case "totalJourneys" where kpiShowTotalJourneys:
            kpiTile(value: vm.totalJourneyCount.map { $0.formatted() } ?? "—",
                    label: "Total Journeys", icon: "person.2.fill",
                    loading: vm.isLoading && vm.totalJourneyCount == nil)
        case "filteredJourneys" where kpiShowFilteredJourneys:
            kpiTile(value: vm.journeyCount.map { $0.formatted() } ?? "—",
                    label: "Filtered Journeys", icon: "line.3.horizontal.decrease.circle.fill",
                    loading: vm.isLoading)
        case "shortestJourney" where kpiShowShortestJourney:
            kpiTile(value: formatSecs(vm.minJourneyDuration),   label: "Shortest Journey", icon: "hare",              loading: vm.isLoading)
        case "avgJourney" where kpiShowAvgJourney:
            kpiTile(value: formatSecs(vm.avgJourneyDuration),   label: "Avg Journey",      icon: "timer",             loading: vm.isLoading)
        case "stdDev" where kpiShowStdDev:
            kpiTile(value: formatSecs(vm.stdDevJourneyDuration), label: "Std Dev",          icon: "waveform.path.ecg", loading: vm.isLoading)
        case "longestJourney" where kpiShowLongestJourney:
            kpiTile(value: formatSecs(vm.maxJourneyDuration),   label: "Longest Journey",  icon: "tortoise",          loading: vm.isLoading)
        case "graphValue" where kpiShowGraphValue:
            if let val = graphValue(for: vm.processGraph) {
                kpiTile(value: val.formatted(.number.sign(strategy: .always())),
                        label: "Graph Value", icon: "function", loading: vm.isLoading)
            }
        case "processGoodness" where kpiShowProcessGoodness:
            if let val = vm.processGoodnessScore {
                kpiTile(value: val.formatted(.number.precision(.fractionLength(2)).sign(strategy: .always())),
                        label: "Process Goodness", icon: "gauge.high", loading: vm.isLoading)
            }
        case "activeSample" where kpiShowActiveSample:
            let cnt = vm.sampleCounts[vm.activeSampleSetA] ?? vm.totalJourneyCount
            kpiTile(value: cnt?.formatted() ?? "—",
                    label: vm.activeSampleSetA.shortLabel, icon: "square.3.layers.3d", loading: false)
        default:
            EmptyView()
        }
    }
}

// MARK: - Journey Time Slider

private struct JourneyTimeSlider: View {
    let rangeMin: Date
    let rangeMax: Date
    let mode:     SliderMode
    @Binding var fromDate: Date
    @Binding var toDate:   Date
    /// Called with the final (from, to) pair only for genuine user interactions.
    let onCommit: (Date, Date) -> Void

    @GestureState private var fromDrag:   CGFloat = 0
    @GestureState private var toDrag:     CGFloat = 0
    @GestureState private var singleDrag: CGFloat = 0
    // Local state drives the DatePickers. External binding changes sync here silently
    // (no onCommit), so programmatic date resets (e.g. project load) never trigger a
    // spurious reloadGraph / concurrent WebSocket query.
    @State private var localFrom: Date = Date()
    @State private var localTo:   Date = Date()

    // Day-normalised boundaries ensure the thumb always snaps to real calendar days
    // regardless of whether rangeMin/rangeMax carry a time component from the DB.
    private var dayMin: Date { Calendar.current.startOfDay(for: rangeMin) }
    private var dayMax: Date { Calendar.current.startOfDay(for: rangeMax) }

    private func fraction(for date: Date) -> Double {
        let total = dayMax.timeIntervalSince(dayMin)
        guard total > 0 else { return 0 }
        return max(0, min(1, date.timeIntervalSince(dayMin) / total))
    }

    private func date(for fraction: Double) -> Date {
        let total = dayMax.timeIntervalSince(dayMin)
        return dayMin.addingTimeInterval(total * max(0, min(1, fraction)))
    }

    private var safeRange: ClosedRange<Date> {
        // Lower bound: extend to localFrom so a historically committed date (e.g. from
        // a filter group) is never clamped out of the DatePicker by the track minimum.
        let lo = min(dayMin, Calendar.current.startOfDay(for: localFrom))
        let hi = max(lo, dayMax)
        return lo == hi ? lo...lo.addingTimeInterval(1) : lo...hi
    }

    private func boundaryLabel(_ date: Date) -> some View {
        Text(date, format: .dateTime.day().month(.abbreviated).year())
            .font(.caption.monospacedDigit())
            .foregroundStyle(.secondary)
            .lineLimit(1)
            .fixedSize()
    }

    var body: some View {
        VStack(spacing: 6) {
            HStack(spacing: 8) {
                boundaryLabel(dayMin)
                if mode == .singleDay {
                    singleDayTrack
                } else {
                    rangeTrack
                }
                boundaryLabel(dayMax)
            }
            .padding(.horizontal, 16)
            .padding(.top, 38)
            .padding(.bottom, 8)
        }
        .background(Color(.secondarySystemGroupedBackground))
        // Keep local DatePicker state in sync when the binding is updated externally
        // (project load, sidebar Anwenden, etc.). Does NOT call onCommit.
        .onChange(of: fromDate) { _, val in if localFrom != val { localFrom = val } }
        .onChange(of: toDate)   { _, val in if localTo   != val { localTo   = val } }
        .onAppear {
            localFrom = fromDate
            localTo   = toDate
        }
        // When switching to Day mode, snap both ends to the same valid calendar day
        // and commit immediately so the query reflects the correct single-day filter.
        .onChange(of: mode) { _, newMode in
            guard newMode == .singleDay else { return }
            let lo      = dayMin
            let hi      = dayMax
            let clamped = Calendar.current.startOfDay(for: min(max(localFrom, lo), hi))
            if localFrom != clamped { localFrom = clamped }
            if localTo   != clamped { localTo   = clamped }
            onCommit(clamped, clamped)
        }
    }

    // MARK: - Single-day track

    private var singleDayTrack: some View {
        GeometryReader { geo in
            let pad:    CGFloat = 10
            let width         = geo.size.width - pad * 2
            let frac          = fraction(for: localFrom)
            let thumbX        = CGFloat(frac) * width + pad
            let thumbR: CGFloat = 9

            // Clamp limits: keep the thumb center within [pad, pad+width]
            let dragMin = pad - thumbX          // max leftward pixels from start pos
            let dragMax = pad + width - thumbX  // max rightward pixels from start pos

            ZStack(alignment: .leading) {
                Capsule()
                    .fill(Color.primary.opacity(0.12))
                    .frame(height: 4)
                    .padding(.horizontal, pad)

                Circle()
                    .fill(Color(.systemBackground))
                    .frame(width: thumbR * 2, height: thumbR * 2)
                    .overlay(Circle().strokeBorder(Color.accentColor, lineWidth: 2))
                    .shadow(color: .black.opacity(0.18), radius: 3, y: 1)
                    .offset(x: thumbX - thumbR + singleDrag)
                    .gesture(
                        DragGesture(minimumDistance: 0)
                            .updating($singleDrag) { v, state, _ in
                                // Clamp the GestureState so the thumb never escapes the track
                                state = max(dragMin, min(dragMax, v.translation.width))
                            }
                            .onEnded { v in
                                let clampedTranslation = max(dragMin, min(dragMax, v.translation.width))
                                let newFrac = max(0, min(1,
                                    Double(thumbX + clampedTranslation - pad) / Double(max(1.0, width))))
                                let day = Calendar.current.startOfDay(for: date(for: newFrac))
                                localFrom = day; localTo = day
                                fromDate = day; toDate = day
                                onCommit(day, day)
                            }
                    )

                // Date badge — always visible, tracks thumb while dragging
                let badgeCX = singleDrag != 0 ? thumbX + singleDrag : thumbX
                let badgeFrac = singleDrag != 0
                    ? max(0, min(1, Double(badgeCX - pad) / Double(max(1.0, width))))
                    : fraction(for: localFrom)
                let badgeDate = Calendar.current.startOfDay(for: date(for: badgeFrac))
                dragDateBadge(badgeDate, thumbCenterX: badgeCX,
                              trackWidth: geo.size.width, thumbR: thumbR)
            }
            .frame(height: thumbR * 2)
        }
        .frame(height: 18)
    }

    // MARK: - Range track

    private var rangeTrack: some View {
        GeometryReader { geo in
            let pad:    CGFloat = 10
            let width         = geo.size.width - pad * 2
            let fromFrac      = fraction(for: fromDate)
            let toFrac        = fraction(for: toDate)
            let fromX         = CGFloat(fromFrac) * width + pad
            let toX           = CGFloat(toFrac)   * width + pad
            let thumbR: CGFloat = 9

            // Clamp limits for each thumb
            let fromDragMin = pad - fromX;  let fromDragMax = pad + width - fromX
            let toDragMin   = pad - toX;    let toDragMax   = pad + width - toX

            ZStack(alignment: .leading) {
                Capsule()
                    .fill(Color.primary.opacity(0.12))
                    .frame(height: 4)
                    .padding(.horizontal, pad)

                Rectangle()
                    .fill(Color.accentColor.opacity(0.45))
                    .frame(width: max(0, toX - fromX), height: 4)
                    .offset(x: fromX)

                // From thumb
                Circle()
                    .fill(Color(.systemBackground))
                    .frame(width: thumbR * 2, height: thumbR * 2)
                    .overlay(Circle().strokeBorder(Color.accentColor, lineWidth: 2))
                    .shadow(color: .black.opacity(0.18), radius: 3, y: 1)
                    .offset(x: fromX - thumbR + fromDrag)
                    .gesture(
                        DragGesture(minimumDistance: 0)
                            .updating($fromDrag) { v, state, _ in
                                state = max(fromDragMin, min(fromDragMax, v.translation.width))
                            }
                            .onEnded { v in
                                let t = max(fromDragMin, min(fromDragMax, v.translation.width))
                                let newFrac = max(0, min(fraction(for: toDate) - 0.001,
                                    Double(fromX + t - pad) / Double(max(1.0, width))))
                                let newFrom = Calendar.current.startOfDay(for: date(for: newFrac))
                                fromDate = newFrom
                                onCommit(newFrom, toDate)
                            }
                    )

                // To thumb
                Circle()
                    .fill(Color(.systemBackground))
                    .frame(width: thumbR * 2, height: thumbR * 2)
                    .overlay(Circle().strokeBorder(Color.accentColor, lineWidth: 2))
                    .shadow(color: .black.opacity(0.18), radius: 3, y: 1)
                    .offset(x: toX - thumbR + toDrag)
                    .gesture(
                        DragGesture(minimumDistance: 0)
                            .updating($toDrag) { v, state, _ in
                                state = max(toDragMin, min(toDragMax, v.translation.width))
                            }
                            .onEnded { v in
                                let t = max(toDragMin, min(toDragMax, v.translation.width))
                                let newFrac = max(fraction(for: fromDate) + 0.001, min(1,
                                    Double(toX + t - pad) / Double(max(1.0, width))))
                                let newTo = Calendar.current.startOfDay(for: date(for: newFrac))
                                toDate = newTo
                                onCommit(fromDate, newTo)
                            }
                    )

                // From-thumb date badge — always visible; tracks thumb live while dragging
                let fromBadgeCX = fromDrag != 0 ? fromX + fromDrag : fromX
                let fromBadgeFrac = fromDrag != 0
                    ? max(0.0, min(fraction(for: toDate) - 0.001,
                          Double(fromBadgeCX - pad) / Double(max(1.0, width))))
                    : fraction(for: fromDate)
                let fromBadgeDate = Calendar.current.startOfDay(for: date(for: fromBadgeFrac))
                dragDateBadge(fromBadgeDate, thumbCenterX: fromBadgeCX,
                              trackWidth: geo.size.width, thumbR: thumbR)

                // To-thumb date badge — always visible; tracks thumb live while dragging
                let toBadgeCX = toDrag != 0 ? toX + toDrag : toX
                let toBadgeFrac = toDrag != 0
                    ? max(fraction(for: fromDate) + 0.001, min(1.0,
                          Double(toBadgeCX - pad) / Double(max(1.0, width))))
                    : fraction(for: toDate)
                let toBadgeDate = Calendar.current.startOfDay(for: date(for: toBadgeFrac))
                dragDateBadge(toBadgeDate, thumbCenterX: toBadgeCX,
                              trackWidth: geo.size.width, thumbR: thumbR)
            }
            .frame(height: thumbR * 2)
        }
        .frame(height: 18)
    }

    @ViewBuilder
    private func dragDateBadge(_ date: Date, thumbCenterX: CGFloat,
                                trackWidth: CGFloat, thumbR: CGFloat) -> some View {
        let badgeW: CGFloat = 96
        let badgeX = max(0, min(trackWidth - badgeW, thumbCenterX - badgeW / 2))
        Text(date.formatted(.dateTime.day().month(.abbreviated).year()))
            .font(.caption2.weight(.semibold))
            .foregroundStyle(.primary)
            .lineLimit(1)
            .padding(.horizontal, 8)
            .padding(.vertical, 4)
            .frame(width: badgeW)
            .background(.regularMaterial, in: Capsule())
            .overlay(Capsule().strokeBorder(Color.accentColor.opacity(0.4), lineWidth: 0.5))
            .shadow(color: .black.opacity(0.15), radius: 4, y: 2)
            .offset(x: badgeX, y: -(thumbR + 22))
            .allowsHitTesting(false)
    }
}

// MARK: - Gap Analysis Table

private struct GapAnalysisTableView: View {
    let graph:         ProcessGraph
    let norms:         [String: Double]
    let metric:        TransitionMetric
    let normIsMinimum: Bool

    // Row model
    private struct GapRow: Identifiable {
        let id:            String   // transition.id
        let from:          String
        let to:            String
        let actual:        Double
        let norm:          Double?
        let normIsMinimum: Bool

        var delta: Double? { norm.map { actual - $0 } }

        enum Status { case violation, compliant, noNorm }
        var status: Status {
            guard let d = delta else { return .noNorm }
            // For max norm: violation when actual exceeds norm (d > 0)
            // For min norm: violation when actual falls short of norm (d < 0)
            return (normIsMinimum ? d < 0 : d > 0) ? .violation : .compliant
        }
    }

    private var rows: [GapRow] {
        // For count metric: actual = occurrences / totalOutgoingFromSameNode * 100
        var outgoing: [String: Int] = [:]
        if metric == .count {
            for t in graph.transitions { outgoing[t.fromStep, default: 0] += t.occurrences }
        }
        return graph.transitions
            .filter { $0.fromStep != $0.toStep }
            .map { t in
                let actual: Double = metric == .count
                    ? {
                        let tot = outgoing[t.fromStep] ?? 1
                        return Double(t.occurrences) / Double(tot) * 100.0
                      }()
                    : (t.metricValue(for: metric) ?? Double(t.occurrences))
                return GapRow(id: t.id, from: t.fromStep, to: t.toStep,
                              actual: actual, norm: norms[t.id], normIsMinimum: normIsMinimum)
            }
            .sorted { a, b in
                switch (a.status, b.status) {
                // Worst violations first: for max norms largest positive delta; for min norms largest negative delta
                case (.violation, .violation):
                    return normIsMinimum ? (a.delta ?? 0) < (b.delta ?? 0) : (a.delta ?? 0) > (b.delta ?? 0)
                case (.compliant, .compliant): return (a.delta ?? 0) < (b.delta ?? 0)
                case (.noNorm, .noNorm):       return a.actual > b.actual
                case (.violation, _):          return true
                case (_, .violation):          return false
                case (.compliant, _):          return true
                default:                       return false
                }
            }
    }

    private func fmt(_ val: Double) -> String {
        if metric == .count {
            return String(format: "%.1f%%", val)
        }
        if metric.isTimeBased {
            if val < 60    { return String(format: "%.0fs", val) }
            if val < 3600  { return String(format: "%.0fm", val / 60) }
            if val < 86400 { return String(format: "%.1fh", val / 3600) }
            return           String(format: "%.1fd", val / 86400)
        } else {
            let n = Int(val.rounded())
            switch n {
            case 0..<1_000:     return "\(n)"
            case 0..<1_000_000: return String(format: "%.1fk", Double(n) / 1_000)
            default:            return String(format: "%.1fM", Double(n) / 1_000_000)
            }
        }
    }

    private func statusColor(_ s: GapRow.Status) -> Color {
        switch s {
        case .violation: return .red
        case .compliant: return .green
        case .noNorm:    return Color.secondary.opacity(0.35)
        }
    }

    private func statusIcon(_ s: GapRow.Status) -> String {
        switch s {
        case .violation: return "xmark.circle.fill"
        case .compliant: return "checkmark.circle.fill"
        case .noNorm:    return "circle"
        }
    }

    var body: some View {
        VStack(spacing: 0) {
            // Column headers
            HStack(spacing: 0) {
                Text("From → To")
                    .frame(maxWidth: .infinity, alignment: .leading)
                Text("Actual")
                    .frame(width: 74, alignment: .trailing)
                Text("Norm")
                    .frame(width: 74, alignment: .trailing)
                Text("Δ Delta")
                    .frame(width: 88, alignment: .trailing)
            }
            .font(.caption2.weight(.semibold))
            .foregroundStyle(.secondary)
            .padding(.horizontal, 16)
            .padding(.vertical, 7)
            .background(Color(.secondarySystemGroupedBackground))

            Divider()

            if rows.isEmpty {
                ContentUnavailableView(
                    "No Transitions",
                    systemImage: "arrow.left.arrow.right",
                    description: Text("Apply filters to load data.")
                )
            } else {
                ScrollView {
                    LazyVStack(spacing: 0) {
                        ForEach(rows) { row in
                            rowView(row)
                            Divider().padding(.leading, 28)
                        }
                    }
                }
            }
        }
        .background(Color(.systemBackground))
    }

    @ViewBuilder
    private func rowView(_ row: GapRow) -> some View {
        HStack(spacing: 0) {
            // Status icon
            Image(systemName: statusIcon(row.status))
                .foregroundStyle(statusColor(row.status))
                .font(.system(size: 14, weight: .semibold))
                .padding(.leading, 12)
                .padding(.trailing, 4)

            Text("\(row.from) → \(row.to)")
                .font(.caption)
                .lineLimit(1)
                .frame(maxWidth: .infinity, alignment: .leading)

            Text(fmt(row.actual))
                .font(.caption.monospacedDigit())
                .frame(width: 74, alignment: .trailing)

            Group {
                if let nv = row.norm {
                    Text(fmt(nv))
                } else {
                    Text("—").foregroundStyle(.tertiary)
                }
            }
            .font(.caption.monospacedDigit())
            .frame(width: 74, alignment: .trailing)

            // Delta column
            Group {
                if let d = row.delta {
                    HStack(spacing: 3) {
                        Image(systemName: d > 0 ? "arrow.up" : "arrow.down")
                            .font(.system(size: 9, weight: .bold))
                        Text((d > 0 ? "+" : "") + fmt(abs(d)))
                            .font(.caption.monospacedDigit())
                    }
                    .foregroundStyle(d > 0 ? Color.red : Color.green)
                } else {
                    Text("—")
                        .font(.caption)
                        .foregroundStyle(.tertiary)
                }
            }
            .frame(width: 88, alignment: .trailing)
            .padding(.trailing, 16)
        }
        .padding(.vertical, 7)
    }
}

// MARK: - Share sheet

#if os(iOS)
private struct ShareSheet: UIViewControllerRepresentable {
    let items: [Any]
    func makeUIViewController(context: Context) -> UIActivityViewController {
        UIActivityViewController(activityItems: items, applicationActivities: nil)
    }
    func updateUIViewController(_ vc: UIActivityViewController, context: Context) {}
}
#else
private struct ShareSheet: View {
    let items: [Any]
    @Environment(\.dismiss) private var dismiss
    var body: some View {
        VStack(spacing: 16) {
            Image(systemName: "square.and.arrow.up").font(.largeTitle).foregroundStyle(.secondary)
            Text("Share").font(.headline)
            SharePickerButton(items: items)
            Button("Close") { dismiss() }
        }
        .padding(28)
        .frame(minWidth: 260)
    }
}

/// Bridges to AppKit's `NSSharingServicePicker`, anchored to a native button.
private struct SharePickerButton: NSViewRepresentable {
    let items: [Any]
    func makeNSView(context: Context) -> NSButton {
        let button = NSButton(title: "Share…", target: context.coordinator,
                              action: #selector(Coordinator.present(_:)))
        button.bezelStyle = .rounded
        context.coordinator.items = items
        return button
    }
    func updateNSView(_ nsView: NSButton, context: Context) { context.coordinator.items = items }
    func makeCoordinator() -> Coordinator { Coordinator() }

    final class Coordinator: NSObject {
        var items: [Any] = []
        @objc func present(_ sender: NSButton) {
            let picker = NSSharingServicePicker(items: items)
            picker.show(relativeTo: sender.bounds, of: sender, preferredEdge: .maxY)
        }
    }
}
#endif

extension URL: @retroactive Identifiable {
    public var id: String { absoluteString }
}

// MARK: - Note list sheet (shown when a node/edge has more than one note)

private struct NoteListSheet: View {
    let item:     NoteListItem
    let onSave:   (ProcessNote) -> Void
    let onDelete: (ProcessNote) -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var notes: [ProcessNote]
    @State private var selectedEditorItem: NoteEditorItem? = nil

    init(item: NoteListItem, onSave: @escaping (ProcessNote) -> Void, onDelete: @escaping (ProcessNote) -> Void) {
        self.item     = item
        self.onSave   = onSave
        self.onDelete = onDelete
        _notes = State(initialValue: item.notes)
    }

    var body: some View {
        NavigationStack {
            List {
                Section {
                    ForEach(notes) { note in
                        Button {
                            selectedEditorItem = NoteEditorItem(
                                target: item.target,
                                existingNote: note,
                                filterSnapshot: note.filterSnapshot)
                        } label: {
                            NoteRow(note: note)
                        }
                        .buttonStyle(.plain)
                        .swipeActions(edge: .trailing, allowsFullSwipe: true) {
                            Button(role: .destructive) {
                                notes.removeAll { $0.id == note.id }
                                onDelete(note)
                            } label: {
                                Label("Delete", systemImage: "trash")
                            }
                        }
                    }
                }
                Section {
                    Button {
                        selectedEditorItem = NoteEditorItem(
                            target: item.target,
                            existingNote: nil,
                            filterSnapshot: item.filterSnapshot)
                    } label: {
                        Label("Add Note", systemImage: "plus.circle")
                    }
                }
            }
            .navigationTitle("Notes (\(notes.count))")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Close") { dismiss() } }
            }
        }
        // On macOS a sheet sizes to its content's ideal size, and a bare List
        // reports almost no height — without this the popup collapses and the
        // note rows are not visible. iOS sheets ignore the min frame.
        #if os(macOS)
        .frame(minWidth: 380, minHeight: 460)
        #endif
        .sheet(item: $selectedEditorItem) { editorItem in
            NoteEditorSheet(
                item: editorItem,
                onSave: { note in
                    if let idx = notes.firstIndex(where: { $0.id == note.id }) {
                        notes[idx] = note
                    } else {
                        notes.append(note)
                    }
                    onSave(note)
                },
                onDelete: { note in
                    notes.removeAll { $0.id == note.id }
                    onDelete(note)
                }
            )
        }
    }
}

private struct NoteRow: View {
    let note: ProcessNote

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                if !note.username.isEmpty {
                    Text(note.username)
                        .font(.caption.weight(.semibold))
                }
                Spacer()
                Text(note.createdAt, style: .date)
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }
            Text(note.text)
                .font(.caption)
                .lineLimit(2)
                .foregroundStyle(.secondary)
        }
        .padding(.vertical, 2)
    }
}

// MARK: - Note editor sheet

private struct NoteEditorSheet: View {
    let item: NoteEditorItem
    let onSave:   (ProcessNote) -> Void
    let onDelete: (ProcessNote) -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var text: String
    @State private var isShared: Bool
    @State private var showNewNoteSheet = false

    init(item: NoteEditorItem, onSave: @escaping (ProcessNote) -> Void, onDelete: @escaping (ProcessNote) -> Void) {
        self.item     = item
        self.onSave   = onSave
        self.onDelete = onDelete
        _text     = State(initialValue: item.existingNote?.text     ?? "")
        _isShared = State(initialValue: item.existingNote?.isShared ?? false)
    }

    var body: some View {
        NavigationStack {
            Form {
                Section("Target") {
                    Label(item.target.displayName,
                          systemImage: item.target.isNode ? "circle.fill" : "arrow.right.circle.fill")
                }
                Section {
                    Text(item.filterSnapshot.summaryText)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                } header: {
                    Text("Filters at creation")
                }
                Section {
                    let author = item.existingNote?.username.isEmpty == false
                        ? item.existingNote!.username
                        : (DatabaseManager.shared.activeDatabaseServer?.username ?? "")
                    if !author.isEmpty {
                        LabeledContent("Author", value: author)
                    }
                    if let existing = item.existingNote {
                        LabeledContent("Created",
                            value: existing.createdAt.formatted(date: .abbreviated, time: .shortened))
                        if let editedAt = existing.editedAt {
                            let editorLabel = existing.lastEditedBy.isEmpty || existing.lastEditedBy == existing.username
                                ? "Last edited"
                                : "Last edited by \(existing.lastEditedBy)"
                            LabeledContent(editorLabel,
                                value: editedAt.formatted(date: .abbreviated, time: .shortened))
                        }
                    }
                }
                Section("Note") {
                    TextEditor(text: $text)
                        .frame(minHeight: 120)
                }
                Section {
                    Toggle(isOn: $isShared) {
                        Label("Share with all users", systemImage: "person.2")
                    }
                } footer: {
                    Text(isShared
                         ? "This note is visible to everyone connected to this database."
                         : "This note is private — only you can see it.")
                }
                if item.existingNote != nil {
                    Section {
                        Button {
                            showNewNoteSheet = true
                        } label: {
                            Label("Add New Note", systemImage: "plus.circle")
                        }
                    }
                }
                if let existing = item.existingNote {
                    Section {
                        Button(role: .destructive) {
                            onDelete(existing)
                            dismiss()
                        } label: {
                            Label("Delete Note", systemImage: "trash")
                        }
                    }
                }
            }
            .formStyle(.grouped)
            .navigationTitle(item.existingNote == nil ? "New Note" : "Edit Note")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save") {
                        var note = item.existingNote ?? ProcessNote(
                            text: "", target: item.target, filterSnapshot: item.filterSnapshot)
                        if item.existingNote != nil && text != (item.existingNote?.text ?? "") {
                            note.editedAt = Date()
                        }
                        note.text     = text
                        note.isShared = isShared
                        onSave(note)
                        dismiss()
                    }
                    .disabled(text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
            }
            .sheet(isPresented: $showNewNoteSheet) {
                NoteEditorSheet(
                    item: NoteEditorItem(
                        target: item.target,
                        existingNote: nil,
                        filterSnapshot: item.filterSnapshot
                    ),
                    onSave: onSave,
                    onDelete: onDelete
                )
            }
        }
    }
}

// MARK: - Sent prompt inspector sheet

private struct SentPromptSheet: View {
    let prompt: String
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            ScrollView {
                Text(prompt)
                    .font(.system(.body, design: .monospaced))
                    .textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(20)
            }
            .background(Color(.systemGroupedBackground))
            .navigationTitle("Prompt Sent to LLM")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") { dismiss() }
                }
            }
        }
        .presentationDetents([.medium, .large])
        .presentationDragIndicator(.visible)
    }
}
