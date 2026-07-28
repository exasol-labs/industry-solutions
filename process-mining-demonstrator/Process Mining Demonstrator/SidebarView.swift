import SwiftUI
import UniformTypeIdentifiers

// Drag-and-drop delegate used by the KPI order editor in the sidebar.
private struct KPIDropDelegate: DropDelegate {
    let targetId: String
    @Binding var kpiOrderRaw: String
    @Binding var draggingId: String?

    private func ids() -> [String] {
        kpiOrderRaw.split(separator: ",").map(String.init)
    }

    func dropUpdated(info: DropInfo) -> DropProposal? {
        DropProposal(operation: .move)
    }

    func dropEntered(info: DropInfo) {
        guard let dragged = draggingId, dragged != targetId else { return }
        var arr = ids()
        guard let fromIdx = arr.firstIndex(of: dragged),
              let toIdx   = arr.firstIndex(of: targetId) else { return }
        withAnimation(.easeInOut(duration: 0.2)) {
            arr.move(fromOffsets: IndexSet(integer: fromIdx),
                     toOffset: toIdx > fromIdx ? toIdx + 1 : toIdx)
            kpiOrderRaw = arr.joined(separator: ",")
        }
    }

    func performDrop(info: DropInfo) -> Bool {
        draggingId = nil
        return true
    }
}

private struct ConnectionEditorItem: Identifiable {
    let id: UUID
    let profile: ConnectionProfile?
    static func newConnection()        -> ConnectionEditorItem { ConnectionEditorItem(id: UUID(), profile: nil) }
    static func edit(_ p: ConnectionProfile) -> ConnectionEditorItem { ConnectionEditorItem(id: p.id, profile: p) }
}

struct SidebarView: View {
    @ObservedObject var vm: AppViewModel
    @Binding var selectedProjectId: String?
    @ObservedObject private var db = DatabaseManager.shared

    @State private var connectionsExpanded = true   // always open on launch; not persisted
    @State private var projectsExpanded        = false
    @State private var filtersExpanded         = false
    @State private var metricsExpanded         = false
    @State private var configExpanded          = false
    @State private var samplingExpanded        = false
    @AppStorage("sidebar.filtersDateExpanded")     private var filtersDateExpanded     = true
    @AppStorage("sidebar.filtersMetaExpanded")     private var filtersMetaExpanded     = false
    @AppStorage("sidebar.filtersIncludeExpanded")  private var filtersIncludeExpanded  = false
    @AppStorage("sidebar.filtersExcludeExpanded")  private var filtersExcludeExpanded  = false
    @AppStorage("sidebar.filtersStepsExpanded")       private var filtersStepsExpanded       = false
    @AppStorage("sidebar.filtersJourneyTimeExpanded") private var filtersJourneyTimeExpanded = false
    @AppStorage("sidebar.filtersScoreExpanded")       private var filtersScoreExpanded       = false
    @AppStorage("sidebar.configStepsExpanded")     private var configStepsExpanded     = true
    @AppStorage("sidebar.configKpisExpanded")      private var configKpisExpanded      = true
    @AppStorage("kpi.show.totalJourneys")          private var kpiShowTotalJourneys    = true
    @AppStorage("kpi.show.filteredJourneys")       private var kpiShowFilteredJourneys = true
    @AppStorage("kpi.show.shortestJourney")        private var kpiShowShortestJourney  = true
    @AppStorage("kpi.show.avgJourney")             private var kpiShowAvgJourney       = true
    @AppStorage("kpi.show.stdDev")                 private var kpiShowStdDev           = true
    @AppStorage("kpi.show.longestJourney")         private var kpiShowLongestJourney   = true
    @AppStorage("kpi.show.graphValue")             private var kpiShowGraphValue       = true
    @AppStorage("kpi.show.processGoodness")        private var kpiShowProcessGoodness  = true
    @AppStorage("kpi.show.processSimilarity")      private var kpiShowProcessSimilarity = true
    @AppStorage("kpi.show.activeSample")           private var kpiShowActiveSample      = true
    @AppStorage("kpi.order")                       private var kpiOrderRaw              = kpiDefaultOrder
    @State private var draggingKPIId: String?
    @AppStorage("processmap.showGrouping")          private var showGrouping            = true
    @AppStorage("processmap.showNodeDescriptions")  private var showNodeDescriptions    = true
    @AppStorage("graph.startMode")                 private var graphStartMode: GraphStartMode = .expanded
    @AppStorage("graph.optimisedLayout")           private var optimisedLayout         = true
    @AppStorage("security.requireAuthentication")  private var requireAuthentication   = false
    @AppStorage("slider.mode")                     private var sliderMode: SliderMode = .range
    @AppStorage("app.theme")                       private var appTheme                = "system"

    @Binding var columnVisibility: NavigationSplitViewVisibility

    @State private var connectionEditorItem: ConnectionEditorItem?
    @State private var profileToDelete:  ConnectionProfile? = nil
    @State private var showPromptEditor  = false
    @State private var showBackup        = false
    @State private var showSavePreset    = false
    @State private var presetNameInput   = ""

    var body: some View {
        VStack(spacing: 0) {
        ScrollView {
        VStack(spacing: 0) {

            // MARK: Branding header
            brandHeader

            Divider()

            // MARK: Connections
            sectionHeader(title: "Connections", count: db.profiles.count,
                          isExpanded: $connectionsExpanded,
                          onToggle: {
                              withAnimation(.easeInOut(duration: 0.2)) {
                                  let open = !connectionsExpanded
                                  collapseAllSections()
                                  connectionsExpanded = open
                              }
                          }) {
                Button {
                    connectionEditorItem = .newConnection()
                } label: {
                    Image(systemName: "plus.circle.fill")
                        .font(.title3)
                        .frame(minWidth: 44, minHeight: 44)
                        .contentShape(Rectangle())
                }
                .buttonStyle(.borderless)
                .accessibilityLabel("Add connection")
                .help("Add connection")
            }

            if connectionsExpanded {
                connectionsContent
                    .frame(height: connectionsHeight)
                    .animation(.easeInOut(duration: 0.2), value: db.profiles.count)
                    .transition(.opacity.combined(with: .move(edge: .top)))
            }

            Divider()

            // MARK: Projects
            sectionHeader(title: "Projects", count: vm.projects.count,
                          isExpanded: $projectsExpanded,
                          onToggle: {
                              withAnimation(.easeInOut(duration: 0.2)) {
                                  let open = !projectsExpanded
                                  collapseAllSections()
                                  projectsExpanded = open
                              }
                          }) {
                Button {
                    Task { await vm.loadProjects() }
                } label: {
                    Image(systemName: "arrow.clockwise.circle")
                        .font(.title3)
                        .frame(minWidth: 44, minHeight: 44)
                        .contentShape(Rectangle())
                }
                .buttonStyle(.borderless)
                .disabled(!db.isConnected)
                .accessibilityLabel("Reload projects")
                .help("Reload projects")
            }

            if projectsExpanded {
                projectsContent
                    .frame(height: projectsHeight)
                    .animation(.easeInOut(duration: 0.2), value: vm.projects.count)
                    .transition(.opacity.combined(with: .move(edge: .top)))
            }

            Divider()

            // MARK: Metrics
            sectionHeader(title: "Metrics", count: nil,
                          isExpanded: $metricsExpanded,
                          onToggle: {
                              withAnimation(.easeInOut(duration: 0.2)) {
                                  let open = !metricsExpanded
                                  collapseAllSections()
                                  metricsExpanded = open
                              }
                          }) { EmptyView() }

            if metricsExpanded {
                metricsContent
            }

            Divider()

            // MARK: Filters
            sectionHeader(title: "Filters", count: nil,
                          isExpanded: $filtersExpanded,
                          onToggle: {
                              withAnimation(.easeInOut(duration: 0.2)) {
                                  let open = !filtersExpanded
                                  collapseAllSections()
                                  filtersExpanded = open
                              }
                          }) { EmptyView() }

            if filtersExpanded {
                if vm.activeChartMode == .individualJourney {
                    individualJourneyFilter
                } else if vm.activeChartMode == .aiAnalysis {
                    aiAnalysisFilter
                } else if vm.activeChartMode == .statistics {
                    normalFilters { await vm.loadJourneyPaths() }
                } else {
                    if vm.activeChartMode == .abComparison {
                        abSideToggle
                        Divider()
                    }
                    normalFilters { await vm.reloadGraph() }
                }
            }

            Divider()

            // MARK: Sampling
            sectionHeader(title: "Sampling", count: nil,
                          isExpanded: $samplingExpanded,
                          onToggle: {
                              withAnimation(.easeInOut(duration: 0.2)) {
                                  let open = !samplingExpanded
                                  collapseAllSections()
                                  samplingExpanded = open
                              }
                          }) { EmptyView() }

            if samplingExpanded {
                SamplingView(vm: vm)
                    .transition(.opacity.combined(with: .move(edge: .top)))
            }

            Divider()

            // MARK: Configuration
            sectionHeader(title: "Configuration", count: nil,
                          isExpanded: $configExpanded,
                          onToggle: {
                              withAnimation(.easeInOut(duration: 0.2)) {
                                  let open = !configExpanded
                                  collapseAllSections()
                                  configExpanded = open
                              }
                          }) { EmptyView() }

            if configExpanded {
                VStack(alignment: .leading, spacing: 0) {
                    // Display options
                    HStack(spacing: 10) {
                        Image(systemName: "square.dashed")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        Toggle("Show step groups", isOn: $showGrouping.animation())
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    .padding(.horizontal, 20)
                    .padding(.vertical, 8)

                    if showGrouping {
                        VStack(alignment: .leading, spacing: 5) {
                            HStack(spacing: 10) {
                                Image(systemName: "rectangle.3.group")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                                Text("Groups start")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                            Picker("Groups start", selection: $graphStartMode) {
                                ForEach(GraphStartMode.allCases) { mode in
                                    Text(mode.label).tag(mode)
                                }
                            }
                            .pickerStyle(.segmented)
                            .labelsHidden()
                        }
                        .padding(.horizontal, 20)
                        .padding(.vertical, 6)
                        .transition(.opacity.combined(with: .move(edge: .top)))
                    }

                    HStack(spacing: 10) {
                        Image(systemName: "note.text")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        Toggle("Show node notes", isOn: $showNodeDescriptions)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    .padding(.horizontal, 20)
                    .padding(.vertical, 8)

                    HStack(spacing: 10) {
                        Image(systemName: "sparkles")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        Toggle("Optimise layout", isOn: $optimisedLayout)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    .padding(.horizontal, 20)
                    .padding(.vertical, 8)

                    HStack(spacing: 10) {
                        Image(systemName: "lock.fill")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        Toggle("Require authentication", isOn: $requireAuthentication)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    .padding(.horizontal, 20)
                    .padding(.vertical, 8)

                    Divider()

                    // Date slider mode
                    HStack(spacing: 10) {
                        Image(systemName: "slider.horizontal.below.rectangle")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        Text("Date slider")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        Spacer(minLength: 0)
                        Picker("Date slider", selection: $sliderMode) {
                            ForEach(SliderMode.allCases) { mode in
                                Text(mode.rawValue).tag(mode)
                            }
                        }
                        .pickerStyle(.segmented)
                        .labelsHidden()
                        .frame(maxWidth: 110)
                    }
                    .padding(.horizontal, 20)
                    .padding(.vertical, 8)

                    Divider()

                    // LLM prompt template
                    HStack(spacing: 10) {
                        Image(systemName: "text.bubble")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        Text("LLM Prompt")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        Spacer(minLength: 0)
                        Button("Edit") { showPromptEditor = true }
                            .font(.caption)
                            .buttonStyle(.bordered)
                            .controlSize(.mini)
                            .disabled(vm.selectedProject == nil)
                    }
                    .padding(.horizontal, 20)
                    .padding(.vertical, 8)

                    Divider()

                    // Backup & Restore
                    HStack(spacing: 10) {
                        Image(systemName: "externaldrive.badge.timemachine")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        Text("Backup & Restore")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        Spacer(minLength: 0)
                        Button("Open") { showBackup = true }
                            .font(.caption)
                            .buttonStyle(.bordered)
                            .controlSize(.mini)
                    }
                    .padding(.horizontal, 20)
                    .padding(.vertical, 8)

                    Divider()

                    filterSubHeader("KPIs", isExpanded: $configKpisExpanded) { EmptyView() }
                    if configKpisExpanded {
                        VStack(alignment: .leading, spacing: 0) {
                            ForEach(orderedKPIIds, id: \.self) { id in
                                HStack(spacing: 6) {
                                    Image(systemName: "line.3.horizontal")
                                        .font(.caption2)
                                        .foregroundStyle(.quaternary)
                                        .frame(width: 14)
                                    kpiToggleRowById(id)
                                }
                                .contentShape(Rectangle())
                                .opacity(draggingKPIId == id ? 0.4 : 1)
                                .onDrag {
                                    draggingKPIId = id
                                    return NSItemProvider(object: id as NSString)
                                }
                                .onDrop(of: [UTType.plainText],
                                        delegate: KPIDropDelegate(
                                            targetId: id,
                                            kpiOrderRaw: $kpiOrderRaw,
                                            draggingId: $draggingKPIId))
                            }
                        }
                        .padding(.horizontal, 14)
                        .padding(.bottom, 8)
                    }

                    Divider()

                    filterSubHeader("Steps", isExpanded: $configStepsExpanded) { EmptyView() }
                    if configStepsExpanded {
                        StepEditorView(vm: vm)
                            .padding(.horizontal, 20)
                            .padding(.bottom, 14)
                    }
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .top)
        } // ScrollView

        Divider()
        themeBar
        } // outer VStack
        .simultaneousGesture(
            DragGesture(minimumDistance: 30, coordinateSpace: .local)
                .onEnded { value in
                    guard value.translation.width < -60,
                          abs(value.translation.width) > abs(value.translation.height) * 1.5
                    else { return }
                    withAnimation(.easeInOut(duration: 0.25)) { columnVisibility = .detailOnly }
                }
        )
        .sheet(isPresented: $showPromptEditor) {
            PromptEditorSheet(vm: vm)
        }
        .sheet(isPresented: $showBackup) {
            BackupRestoreView()
        }
        .barHidden(true)
        .sheet(item: $connectionEditorItem) { item in
            ConnectionPairingEditor(
                profile: item.profile,
                onSave: { profile in
                    if db.profiles.contains(where: { $0.id == profile.id }) {
                        db.updateProfile(profile)
                    } else {
                        db.addProfile(profile)
                    }
                }
            )
        }
        .confirmationDialog(
            "Delete \"\(profileToDelete?.name ?? "")\"?",
            isPresented: Binding(
                get: { profileToDelete != nil },
                set: { if !$0 { profileToDelete = nil } }
            ),
            titleVisibility: .visible
        ) {
            Button("Delete", role: .destructive) {
                if let p = profileToDelete { db.deleteProfile(p) }
                profileToDelete = nil
            }
        }
    }

    // MARK: - Branding header

    private var brandHeader: some View {
        HStack(spacing: 14) {
            Image("AppLogo")
                .resizable()
                .aspectRatio(contentMode: .fit)
                .frame(width: 48, height: 48)
                .clipShape(RoundedRectangle(cornerRadius: 11, style: .continuous))
                .shadow(color: .black.opacity(0.18), radius: 4, x: 0, y: 2)

            VStack(alignment: .leading, spacing: 2) {
                Text("Process Mining")
                    .font(.title3.weight(.bold))
                    .foregroundStyle(.primary)
                Text("Demonstrator")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            Spacer(minLength: 0)
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 14)
        .background(Color(.secondarySystemGroupedBackground))
    }

    // MARK: - Connections list

    private var connectionsContent: some View {
        List {
            if db.profiles.isEmpty {
                Text("No connections yet — tap + to add one.")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                    .listRowBackground(Color.clear)
                    .listRowSeparator(.hidden)
            } else {
                let sorted = db.profiles.sorted { $0.name.localizedCompare($1.name) == .orderedAscending }
                ForEach(sorted) { profile in
                    connectionCard(profile)
                        .listRowBackground(Color.clear)
                        .listRowSeparator(.hidden)
                        .listRowInsets(EdgeInsets(top: 3, leading: 12, bottom: 3, trailing: 12))
                        .onTapGesture { Task { await connectOrDisconnect(profile) } }
                        .contextMenu {
                            Button {
                                connectionEditorItem = .edit(profile)
                            } label: { Label("Edit", systemImage: "pencil") }
                            Divider()
                            Button(role: .destructive) { profileToDelete = profile }
                                label: { Label("Delete", systemImage: "trash") }
                        }
                }
                .onDelete { idxSet in idxSet.forEach { db.deleteProfile(sorted[$0]) } }
            }
            if let err = db.lastError, !db.isConnected {
                Text(err)
                    .font(.caption)
                    .foregroundStyle(.red)
                    .listRowBackground(Color.clear)
                    .listRowSeparator(.hidden)
            }
        }
        .listStyle(.plain)
        .scrollContentBackground(.hidden)
    }

    @ViewBuilder
    private func connectionCard(_ profile: ConnectionProfile) -> some View {
        let isActive     = db.activeProfileId == profile.id
        let isConnected  = db.isConnected && isActive
        let dbServer     = db.databaseServer(for: profile)
        let llmServer    = db.llmServer(for: profile)
        let hasLLM       = profile.llmServerId != nil

        let dbText  = dbServer.map { "\($0.host.isEmpty ? "(no host)" : $0.host):\($0.port)" }
                      ?? "(no database server)"
        let llmText = llmServer.map { $0.serverURL.isEmpty ? "(no URL)" : $0.serverURL }

        HStack(spacing: 12) {
            Image(systemName: "cylinder.split.1x2")
                .font(.title3)
                .foregroundStyle(isConnected ? Color.green : Color.accentColor)

            VStack(alignment: .leading, spacing: 2) {
                Text(profile.name)
                    .font(.callout.weight(.medium))
                    .foregroundStyle(.primary)
                    .lineLimit(1)
                if !profile.comment.isEmpty {
                    Text(profile.comment)
                        .font(.caption)
                        .foregroundStyle(.primary.opacity(0.7))
                        .lineLimit(1)
                }
                Text("Database: \(dbText)")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                if let llmText {
                    Text("LLM: \(llmText)")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
            }

            Spacer()

            if isActive {
                VStack(spacing: 4) {
                    Circle()
                        .fill(isConnected ? Color.green : Color.orange)
                        .frame(width: 8, height: 8)
                    if hasLLM {
                        Circle()
                            .fill(db.isLLMReachable ? Color.blue : Color.orange)
                            .frame(width: 8, height: 8)
                    }
                }
            }

        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .frame(minHeight: 64)
        .background(
            RoundedRectangle(cornerRadius: 10, style: .continuous)
                .fill(isActive
                      ? AnyShapeStyle(Color.accentColor.opacity(0.15))
                      : AnyShapeStyle(.background.secondary))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 10, style: .continuous)
                .stroke(isActive
                        ? Color.accentColor.opacity(0.5)
                        : Color(.separator).opacity(0.7),
                        lineWidth: 0.5)
        )
    }

    // MARK: - Projects list

    private var projectsContent: some View {
        List {
            if !db.isConnected {
                Text("Connect to a database to load projects.")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                    .listRowBackground(Color.clear)
                    .listRowSeparator(.hidden)
            } else if vm.isLoading {
                HStack(spacing: 8) {
                    ProgressView().controlSize(.small)
                    Text("Loading").font(.footnote).foregroundStyle(.secondary)
                }
                .listRowBackground(Color.clear)
                .listRowSeparator(.hidden)
            } else if vm.projects.isEmpty {
                Text("No projects found.")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                    .listRowBackground(Color.clear)
                    .listRowSeparator(.hidden)
            } else {
                ForEach(vm.projects) { project in
                    projectCard(project)
                        .listRowBackground(Color.clear)
                        .listRowSeparator(.hidden)
                        .listRowInsets(EdgeInsets(top: 3, leading: 12, bottom: 3, trailing: 12))
                        .onTapGesture {
                            selectedProjectId = project.projectId
                            withAnimation(.easeInOut(duration: 0.2)) {
                                projectsExpanded = false
                            }
                        }
                }
            }
        }
        .listStyle(.plain)
        .scrollContentBackground(.hidden)
    }

    @ViewBuilder
    private func projectCard(_ project: Project) -> some View {
        let isSelected = selectedProjectId == project.projectId

        HStack(spacing: 12) {
            Image(systemName: "chart.xyaxis.line")
                .font(.callout)
                .foregroundStyle(Color.accentColor)
                .frame(width: 22)

            VStack(alignment: .leading, spacing: 2) {
                Text(project.title)
                    .font(.subheadline.weight(isSelected ? .semibold : .regular))
                    .foregroundStyle(.primary)
                    .lineLimit(1)
                if !project.description.isEmpty {
                    Text(project.description)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
            }

            Spacer()

            if isSelected {
                Image(systemName: "checkmark")
                    .font(.caption.bold())
                    .foregroundStyle(Color.accentColor)
            }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .frame(minHeight: 44)
        .background(
            RoundedRectangle(cornerRadius: 10, style: .continuous)
                .fill(isSelected
                      ? AnyShapeStyle(Color.accentColor.opacity(0.15))
                      : AnyShapeStyle(.background.secondary))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 10, style: .continuous)
                .stroke(isSelected
                        ? Color.accentColor.opacity(0.5)
                        : Color(.separator).opacity(0.7),
                        lineWidth: 0.5)
        )
    }

    // MARK: - Section heights

    private let connectionRowH: CGFloat = 96
    private let projectRowH:    CGFloat = 56
    private let maxVisibleRows          = 3

    private var connectionsHeight: CGFloat {
        guard !db.profiles.isEmpty else { return 52 }
        return CGFloat(min(db.profiles.count, maxVisibleRows)) * connectionRowH + 8
    }

    private var projectsHeight: CGFloat {
        guard !vm.projects.isEmpty else { return 44 }
        return CGFloat(min(vm.projects.count, maxVisibleRows)) * projectRowH + 8
    }

    // MARK: - Section header

    private func filterSubHeader<T: View>(
        _ title: String,
        isExpanded: Binding<Bool>,
        @ViewBuilder trailing: () -> T
    ) -> some View {
        HStack(spacing: 0) {
            Button {
                withAnimation(.easeInOut(duration: 0.15)) { isExpanded.wrappedValue.toggle() }
            } label: {
                HStack(spacing: 5) {
                    Image(systemName: "chevron.right")
                        .font(.caption2.weight(.semibold))
                        .foregroundStyle(.tertiary)
                        .frame(width: 10, alignment: .center)
                        .rotationEffect(.degrees(isExpanded.wrappedValue ? 90 : 0))
                    Text(title)
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(.secondary)
                    Spacer(minLength: 0)
                }
                .contentShape(Rectangle())
                .padding(.vertical, 6)
            }
            .buttonStyle(.plain)
            trailing()
                .padding(.trailing, 4)
        }
        .padding(.horizontal, 20)
    }

    @ViewBuilder
    private func kpiToggleRow(_ label: String, icon: String, binding: Binding<Bool>) -> some View {
        HStack(spacing: 10) {
            Image(systemName: icon)
                .font(.caption)
                .foregroundStyle(.secondary)
                .frame(width: 16, alignment: .center)
            Toggle(label, isOn: binding)
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .padding(.vertical, 6)
    }

    /// Ordered KPI ids from AppStorage, with any missing ones appended at the end.
    private var orderedKPIIds: [String] {
        let stored = kpiOrderRaw.split(separator: ",").map(String.init)
        let all    = kpiDefaultOrder.split(separator: ",").map(String.init)
        return stored + all.filter { !stored.contains($0) }
    }

    @ViewBuilder
    private func kpiToggleRowById(_ id: String) -> some View {
        switch id {
        case "totalJourneys":
            kpiToggleRow("Total Journeys",     icon: "person.2.fill",                          binding: $kpiShowTotalJourneys)
        case "filteredJourneys":
            kpiToggleRow("Filtered Journeys",  icon: "line.3.horizontal.decrease.circle.fill", binding: $kpiShowFilteredJourneys)
        case "shortestJourney":
            kpiToggleRow("Shortest Journey",   icon: "hare",                                   binding: $kpiShowShortestJourney)
        case "avgJourney":
            kpiToggleRow("Avg Journey",        icon: "timer",                                  binding: $kpiShowAvgJourney)
        case "stdDev":
            kpiToggleRow("Std Dev",            icon: "waveform.path.ecg",                      binding: $kpiShowStdDev)
        case "longestJourney":
            kpiToggleRow("Longest Journey",    icon: "tortoise",                               binding: $kpiShowLongestJourney)
        case "graphValue":
            kpiToggleRow("Graph Value",        icon: "function",                               binding: $kpiShowGraphValue)
        case "processGoodness":
            kpiToggleRow("Process Goodness",   icon: "gauge.high",                             binding: $kpiShowProcessGoodness)
        case "processSimilarity":
            kpiToggleRow("Process Similarity", icon: "arrow.triangle.2.circlepath",            binding: $kpiShowProcessSimilarity)
        case "activeSample":
            kpiToggleRow("Active Sample",      icon: "square.3.layers.3d",                     binding: $kpiShowActiveSample)
        default:
            EmptyView()
        }
    }

    private func collapseAllSections() {
        connectionsExpanded = false
        projectsExpanded    = false
        metricsExpanded     = false
        filtersExpanded     = false
        samplingExpanded    = false
        configExpanded      = false
    }

    private func sectionHeader<T: View>(
        title: String,
        count: Int?,
        isExpanded: Binding<Bool>,
        onToggle: (() -> Void)? = nil,
        @ViewBuilder trailing: () -> T
    ) -> some View {
        HStack(alignment: .center, spacing: 0) {
            Button {
                if let onToggle {
                    onToggle()
                } else {
                    withAnimation(.easeInOut(duration: 0.2)) { isExpanded.wrappedValue.toggle() }
                }
            } label: {
                HStack(spacing: 6) {
                    Image(systemName: "chevron.right")
                        .font(.caption2.weight(.bold))
                        .foregroundStyle(.secondary)
                        .frame(width: 10, alignment: .center)
                        .rotationEffect(.degrees(isExpanded.wrappedValue ? 90 : 0))
                    Text(title)
                        .font(.footnote.weight(.semibold))
                        .textCase(.uppercase)
                        .kerning(0.3)
                        .foregroundStyle(.secondary)
                    if let count, count > 0 {
                        Text("(\(count))")
                            .font(.caption2.weight(.medium))
                            .foregroundStyle(.tertiary)
                    }
                    Spacer(minLength: 0)
                }
                .contentShape(Rectangle())
                .padding(.vertical, 6)
            }
            .buttonStyle(.plain)

            trailing()
        }
        .padding(.horizontal, 16)
        .padding(.top, 8)
        .padding(.bottom, 4)
    }

    // MARK: - A/B side toggle (shown in Filters when in A/B Comparison mode)

    private var abSideToggle: some View {
        HStack(spacing: 10) {
            Text("Editing:")
                .font(.caption)
                .foregroundStyle(.secondary)
            Picker("", selection: Binding(
                get: { vm.abActiveSide },
                set: { vm.switchABSide(to: $0) }
            )) {
                Text("A-Chart").tag(ABSide.a)
                Text("B-Chart").tag(ABSide.b)
            }
            .pickerStyle(.segmented)
            .controlSize(.small)
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 8)
    }

    // MARK: - Individual journey filter

    private func formatSecs(_ secs: Int) -> String {
        if secs < 60   { return "\(secs)s" }
        if secs < 3600 { return "\(secs / 60)m \(secs % 60)s" }
        let h = secs / 3600; let m = (secs % 3600) / 60
        if secs < 86400 { return "\(h)h \(m)m" }
        let d = secs / 86400; let rh = (secs % 86400) / 3600
        return "\(d)d \(rh)h"
    }

    private var individualJourneyFilter: some View {
        EventIdFilterView(
            text:        $vm.eventIdFilter,
            suggestions: vm.eventIdSuggestions,
            disabled:    vm.selectedProject == nil,
            onTextChange: { Task { await vm.fetchEventIdSuggestions() } },
            onLoad:       { Task { await vm.loadIndividualJourney() } }
        )
    }

    // MARK: - Metrics content

    private var metricsContent: some View {
        VStack(alignment: .leading, spacing: 8) {
            Label("Transition metric", systemImage: "function")
                .font(.caption.weight(.semibold))
                .foregroundStyle(.secondary)

            let columns = [GridItem(.flexible()), GridItem(.flexible())]
            LazyVGrid(columns: columns, spacing: 6) {
                ForEach(TransitionMetric.allCases) { m in
                    let selected = vm.transitionMetric == m
                    Button { vm.transitionMetric = m } label: {
                        HStack(spacing: 5) {
                            Image(systemName: m.icon)
                                .font(.caption2)
                            Text(m.rawValue)
                                .font(.caption.weight(.medium))
                                .lineLimit(1)
                        }
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 6)
                        .background(selected ? Color.accentColor : Color.primary.opacity(0.07))
                        .foregroundStyle(selected ? Color.white : Color.primary)
                        .clipShape(RoundedRectangle(cornerRadius: 7))
                    }
                    .buttonStyle(.plain)
                    .disabled(vm.selectedProject == nil)
                }
            }
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 10)
    }

    // MARK: - Normal (aggregated) filters

    private func normalFilters(onApply: @escaping () async -> Void) -> some View {
        VStack(alignment: .leading, spacing: 0) {

            // Date sub-section
            filterSubHeader("Datum", isExpanded: $filtersDateExpanded) { EmptyView() }
            if filtersDateExpanded {
                VStack(alignment: .leading, spacing: 8) {
                    HStack {
                        Text("Von")
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                            .frame(width: 28, alignment: .leading)
                        DatePicker("", selection: $vm.fromDate, displayedComponents: .date)
                            .labelsHidden()
                    }
                    HStack {
                        Text("Bis")
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                            .frame(width: 28, alignment: .leading)
                        DatePicker("", selection: $vm.toDate, displayedComponents: .date)
                            .labelsHidden()
                    }
                }
                .padding(.horizontal, 20)
                .padding(.bottom, 10)
            }

            Divider()

            // Include sub-section
            filterSubHeader("Include Steps", isExpanded: $filtersIncludeExpanded) {
                if !vm.includedSteps.isEmpty {
                    Text("\(vm.includedSteps.count)")
                        .font(.caption2.weight(.medium))
                        .foregroundStyle(.white)
                        .padding(.horizontal, 5)
                        .padding(.vertical, 1)
                        .background(Color.accentColor, in: Capsule())
                    Button { vm.includedSteps.removeAll() } label: {
                        Image(systemName: "xmark.circle.fill")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    .buttonStyle(.plain)
                }
            }
            if filtersIncludeExpanded {
                StepFilterListView(
                    steps: vm.allSteps,
                    selected: $vm.includedSteps,
                    disabled: vm.excludedSteps
                )
                .padding(.horizontal, 20)
                .padding(.bottom, 10)
            }

            Divider()

            // Exclude sub-section
            filterSubHeader("Exclude Steps", isExpanded: $filtersExcludeExpanded) {
                if !vm.excludedSteps.isEmpty {
                    Text("\(vm.excludedSteps.count)")
                        .font(.caption2.weight(.medium))
                        .foregroundStyle(.white)
                        .padding(.horizontal, 5)
                        .padding(.vertical, 1)
                        .background(Color.accentColor, in: Capsule())
                    Button { vm.excludedSteps.removeAll() } label: {
                        Image(systemName: "xmark.circle.fill")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    .buttonStyle(.plain)
                }
            }
            if filtersExcludeExpanded {
                StepFilterListView(
                    steps: vm.allSteps,
                    selected: $vm.excludedSteps,
                    disabled: vm.includedSteps
                )
                .padding(.horizontal, 20)
                .padding(.bottom, 10)
            }

            Divider()

            // Num Steps sub-section
            let stepsActive = vm.minStepsFilter > vm.stepCountMin || vm.maxStepsFilter < vm.stepCountMax
            filterSubHeader("Num Steps", isExpanded: $filtersStepsExpanded) {
                if stepsActive {
                    Text("\(vm.minStepsFilter)–\(vm.maxStepsFilter)")
                        .font(.caption2.weight(.medium))
                        .foregroundStyle(.white)
                        .padding(.horizontal, 5)
                        .padding(.vertical, 1)
                        .background(Color.accentColor, in: Capsule())
                    Button {
                        vm.minStepsFilter = vm.stepCountMin
                        vm.maxStepsFilter = vm.stepCountMax
                    } label: {
                        Image(systemName: "xmark.circle.fill")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    .buttonStyle(.plain)
                }
            }
            if filtersStepsExpanded {
                let sMin = vm.stepCountMin
                let sMax = max(sMin, vm.stepCountMax)
                VStack(alignment: .leading, spacing: 8) {
                    RangeSliderView(
                        bounds: sMin...sMax,
                        low:    Binding(
                            get: { max(sMin, min(vm.minStepsFilter, sMax)) },
                            set: { vm.minStepsFilter = $0 }
                        ),
                        high:   Binding(
                            get: { max(sMin, min(vm.maxStepsFilter, sMax)) },
                            set: { vm.maxStepsFilter = $0 }
                        )
                    )
                    .disabled(vm.selectedProject == nil || vm.stepCountMin == vm.stepCountMax)
                }
                .padding(.horizontal, 20)
                .padding(.vertical, 10)
            }

            Divider()

            // Journey Time sub-section
            let timeActive = vm.minJourneyTimeFilter > vm.journeyTimeBoundsMin
                          || vm.maxJourneyTimeFilter < vm.journeyTimeBoundsMax
            filterSubHeader("Journey Time", isExpanded: $filtersJourneyTimeExpanded) {
                if timeActive {
                    Text("\(formatSecs(vm.minJourneyTimeFilter))–\(formatSecs(vm.maxJourneyTimeFilter))")
                        .font(.caption2.weight(.medium))
                        .foregroundStyle(.white)
                        .padding(.horizontal, 5)
                        .padding(.vertical, 1)
                        .background(Color.accentColor, in: Capsule())
                    Button {
                        vm.minJourneyTimeFilter = vm.journeyTimeBoundsMin
                        vm.maxJourneyTimeFilter = vm.journeyTimeBoundsMax
                    } label: {
                        Image(systemName: "xmark.circle.fill")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    .buttonStyle(.plain)
                }
            }
            if filtersJourneyTimeExpanded {
                let tMin = vm.journeyTimeBoundsMin
                let tMax = max(tMin + 1, vm.journeyTimeBoundsMax)
                VStack(alignment: .leading, spacing: 8) {
                    RangeSliderView(
                        bounds: tMin...tMax,
                        low:    Binding(
                            get: { max(tMin, min(vm.minJourneyTimeFilter, tMax)) },
                            set: { vm.minJourneyTimeFilter = $0 }
                        ),
                        high:   Binding(
                            get: { max(tMin, min(vm.maxJourneyTimeFilter, tMax)) },
                            set: { vm.maxJourneyTimeFilter = $0 }
                        ),
                        valueFormatter: { formatSecs($0) }
                    )
                    .disabled(vm.selectedProject == nil || vm.journeyTimeBoundsMax <= vm.journeyTimeBoundsMin)
                }
                .padding(.horizontal, 20)
                .padding(.vertical, 10)
            }

            Divider()

            // Journey Score sub-section
            let scoreActive = vm.minScoreFilter > vm.scoreBoundsMin || vm.maxScoreFilter < vm.scoreBoundsMax
            filterSubHeader("Journey Score", isExpanded: $filtersScoreExpanded) {
                if scoreActive {
                    Text("\(vm.minScoreFilter)–\(vm.maxScoreFilter)")
                        .font(.caption2.weight(.medium))
                        .foregroundStyle(.white)
                        .padding(.horizontal, 5)
                        .padding(.vertical, 1)
                        .background(Color.accentColor, in: Capsule())
                    Button {
                        vm.minScoreFilter = vm.scoreBoundsMin
                        vm.maxScoreFilter = vm.scoreBoundsMax
                    } label: {
                        Image(systemName: "xmark.circle.fill")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    .buttonStyle(.plain)
                }
            }
            if filtersScoreExpanded {
                let sMin = vm.scoreBoundsMin
                let sMax = max(sMin + 1, vm.scoreBoundsMax)
                VStack(alignment: .leading, spacing: 8) {
                    RangeSliderView(
                        bounds: sMin...sMax,
                        low:    Binding(
                            get: { max(sMin, min(vm.minScoreFilter, sMax)) },
                            set: { vm.minScoreFilter = $0 }
                        ),
                        high:   Binding(
                            get: { max(sMin, min(vm.maxScoreFilter, sMax)) },
                            set: { vm.maxScoreFilter = $0 }
                        )
                    )
                    .disabled(vm.selectedProject == nil || vm.scoreBoundsMax <= vm.scoreBoundsMin)
                }
                .padding(.horizontal, 20)
                .padding(.vertical, 10)
            }

            // Meta sub-section (only if project defines meta titles)
            let hasMetaFields = vm.meta1Title != nil || vm.meta2Title != nil || vm.meta3Title != nil
            if hasMetaFields {
                Divider()

                let activeMetaCount = (vm.meta1Title != nil && !vm.meta1Filter.isEmpty ? 1 : 0)
                                   + (vm.meta2Title != nil && !vm.meta2Filter.isEmpty ? 1 : 0)
                                   + (vm.meta3Title != nil && !vm.meta3Filter.isEmpty ? 1 : 0)
                filterSubHeader("Meta", isExpanded: $filtersMetaExpanded) {
                    if activeMetaCount > 0 {
                        Text("\(activeMetaCount)")
                            .font(.caption2.weight(.medium))
                            .foregroundStyle(.white)
                            .padding(.horizontal, 5)
                            .padding(.vertical, 1)
                            .background(Color.accentColor, in: Capsule())
                        Button {
                            vm.meta1Filter = ""
                            vm.meta2Filter = ""
                            vm.meta3Filter = ""
                        } label: {
                            Image(systemName: "xmark.circle.fill")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                        .buttonStyle(.plain)
                    }
                }
                if filtersMetaExpanded {
                    VStack(alignment: .leading, spacing: 6) {
                        if let title = vm.meta1Title {
                            MetaFilterFieldView(label: title, suggestions: vm.meta1Values, text: $vm.meta1Filter)
                        }
                        if let title = vm.meta2Title {
                            MetaFilterFieldView(label: title, suggestions: vm.meta2Values, text: $vm.meta2Filter)
                        }
                        if let title = vm.meta3Title {
                            MetaFilterFieldView(label: title, suggestions: vm.meta3Values, text: $vm.meta3Filter)
                        }
                    }
                    .padding(.horizontal, 20)
                    .padding(.bottom, 10)
                }
            }

            // Reset + Save Preset + Apply buttons
            HStack(spacing: 8) {
                Button {
                    vm.resetFilters()
                    Task { await onApply() }
                } label: {
                    Label("Reset", systemImage: "arrow.counterclockwise")
                }
                .buttonStyle(.bordered)
                .controlSize(.small)
                .disabled(vm.selectedProject == nil)

                Spacer(minLength: 0)

                Button {
                    presetNameInput = ""
                    showSavePreset  = true
                } label: {
                    Label("Save Preset\u{2026}", systemImage: "bookmark.fill")
                }
                .buttonStyle(.bordered)
                .controlSize(.small)
                .disabled(vm.selectedProject == nil)

                Button("Apply") {
                    Task { await onApply() }
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.small)
                .disabled(vm.selectedProject == nil)
            }
            .padding(.horizontal, 20)
            .padding(.vertical, 10)
            .alert("Save Filter Preset", isPresented: $showSavePreset) {
                TextField("Name", text: $presetNameInput)
                Button("Save") {
                    vm.createFilterGroup(name: presetNameInput)
                    presetNameInput = ""
                }
                Button("Cancel", role: .cancel) { presetNameInput = "" }
            } message: {
                Text("Saves the current filter settings as a named preset.")
            }
        }
    }

    // MARK: - Theme bar

    private var themeBar: some View {
        HStack(spacing: 8) {
            Image(systemName: "paintpalette")
                .font(.caption)
                .foregroundStyle(.secondary)
            Text("Theme")
                .font(.caption)
                .foregroundStyle(.secondary)
            Spacer(minLength: 0)
            HStack(spacing: 2) {
                themeButton(value: "system", icon: "circle.lefthalf.filled", label: "System")
                themeButton(value: "light",  icon: "sun.max.fill",           label: "Light")
                themeButton(value: "dark",   icon: "moon.fill",              label: "Dark")
            }
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 10)
        .background(Color(.secondarySystemGroupedBackground))
    }

    private func themeButton(value: String, icon: String, label: String) -> some View {
        Button { appTheme = value } label: {
            Image(systemName: icon)
                .font(.caption.weight(.semibold))
                .foregroundStyle(appTheme == value ? Color.accentColor : Color.secondary)
                .frame(width: 44, height: 44)
                .background(
                    RoundedRectangle(cornerRadius: 6, style: .continuous)
                        .fill(appTheme == value ? Color.accentColor.opacity(0.13) : Color.clear)
                )
        }
        .buttonStyle(.plain)
        .accessibilityLabel(label)
        .help(label)
    }

    // MARK: - AI supported Documentation filter

    private var aiAnalysisFilter: some View {
        HStack(alignment: .top, spacing: 8) {
            Image(systemName: "info.circle")
                .font(.caption)
                .foregroundStyle(.secondary)
                .padding(.top, 1)
            Text("AI supported Documentation uses the filter conditions from the A-Chart.")
                .font(.caption)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 12)
    }

    // MARK: - Connect action

    private func connectOrDisconnect(_ profile: ConnectionProfile) async {
        if db.isConnected && db.activeProfileId == profile.id {
            await db.disconnect()
            vm.clearSession()
            selectedProjectId = nil
        } else {
            if db.isConnected {
                await db.disconnect()
                vm.clearSession()
                selectedProjectId = nil
            }
            await db.connect(profile: profile)
            if db.isConnected {
                await vm.loadProjects()
                withAnimation(.easeInOut(duration: 0.2)) {
                    connectionsExpanded = false
                    projectsExpanded    = true
                }
            }
        }
    }
}

// MARK: - Prompt editor sheet

private struct PromptEditorSheet: View {
    @ObservedObject var vm: AppViewModel
    @Environment(\.dismiss) private var dismiss
    @State private var text: String

    init(vm: AppViewModel) {
        self.vm = vm
        _text   = State(initialValue: vm.llmPromptTemplate)
    }

    var body: some View {
        NavigationStack {
            VStack(alignment: .leading, spacing: 0) {
                Text("This prompt is sent to the LLM together with the current transition table. Use it to guide the analysis style and output format.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .padding(.horizontal, 20)
                    .padding(.top, 14)
                    .padding(.bottom, 10)

                TextEditor(text: $text)
                    .font(.body)
                    .padding(.horizontal, 16)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
            .background(Color(.systemGroupedBackground))
            .navigationTitle("LLM Prompt Template")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save") { vm.llmPromptTemplate = text; dismiss() }
                        .fontWeight(.semibold)
                }
                ToolbarItem(placement: .barBottom) {
                    Button("Reset to Default") {
                        text = AppViewModel.defaultLLMPrompt
                    }
                    .font(.caption)
                    .foregroundStyle(.secondary)
                }
            }
        }
    }
}

// MARK: - Meta filter field with autocomplete

// MARK: - Range slider for numeric bounds

private struct RangeSliderView: View {
    let bounds: ClosedRange<Int>
    @Binding var low:  Int
    @Binding var high: Int
    var valueFormatter: (Int) -> String = { "\($0)" }

    // Track drag offset with @State so .onChanged can update them and trigger re-renders.
    @State private var lowDrag:  CGFloat = 0
    @State private var highDrag: CGFloat = 0
    // Live display values — updated every gesture event so labels reflect the current thumb position.
    @State private var displayLow:  Int = 0
    @State private var displayHigh: Int = 0

    private let trackH:   CGFloat = 4
    private let handleSz: CGFloat = 22

    private func xFor(_ val: Int, span: CGFloat, usable: CGFloat) -> CGFloat {
        handleSz / 2 + CGFloat(val - bounds.lowerBound) / span * usable
    }
    private func valueFor(_ x: CGFloat, span: CGFloat, usable: CGFloat) -> Int {
        let frac = (x - handleSz / 2) / max(usable, 1)
        let raw  = Int(round(frac * span)) + bounds.lowerBound
        return max(bounds.lowerBound, min(bounds.upperBound, raw))
    }

    @ViewBuilder
    private func sliderTrack(width: CGFloat) -> some View {
        let span   = CGFloat(max(1, bounds.upperBound - bounds.lowerBound))
        let usable = width - handleSz
        let lowX   = xFor(low,  span: span, usable: usable) + lowDrag
        let highX  = xFor(high, span: span, usable: usable) + highDrag
        let lx     = min(lowX, highX)
        let rx     = max(lowX, highX)

        ZStack(alignment: .leading) {
            Capsule()
                .fill(Color.secondary.opacity(0.2))
                .frame(height: trackH)
                .padding(.horizontal, handleSz / 2)
                .frame(maxHeight: .infinity)

            Capsule()
                .fill(Color.accentColor)
                .frame(width: max(0, rx - lx), height: trackH)
                .offset(x: lx)
                .frame(maxHeight: .infinity, alignment: .leading)

            Circle()
                .fill(Color.white)
                .frame(width: handleSz, height: handleSz)
                .shadow(color: .black.opacity(0.22), radius: 3, y: 1)
                .offset(x: lowX - handleSz / 2)
                .frame(maxHeight: .infinity, alignment: .leading)
                .highPriorityGesture(DragGesture(minimumDistance: 0)
                    .onChanged { v in
                        lowDrag = v.translation.width
                        let newX = xFor(low, span: span, usable: usable) + v.translation.width
                        displayLow = min(valueFor(newX, span: span, usable: usable), high)
                    }
                    .onEnded { v in
                        let newX = xFor(low, span: span, usable: usable) + v.translation.width
                        low = min(valueFor(newX, span: span, usable: usable), high)
                        displayLow = low
                        lowDrag = 0
                    })

            Circle()
                .fill(Color.white)
                .frame(width: handleSz, height: handleSz)
                .shadow(color: .black.opacity(0.22), radius: 3, y: 1)
                .offset(x: highX - handleSz / 2)
                .frame(maxHeight: .infinity, alignment: .leading)
                .highPriorityGesture(DragGesture(minimumDistance: 0)
                    .onChanged { v in
                        highDrag = v.translation.width
                        let newX = xFor(high, span: span, usable: usable) + v.translation.width
                        displayHigh = max(low, valueFor(newX, span: span, usable: usable))
                    }
                    .onEnded { v in
                        let newX = xFor(high, span: span, usable: usable) + v.translation.width
                        high = max(low, valueFor(newX, span: span, usable: usable))
                        displayHigh = high
                        highDrag = 0
                    })
        }
    }

    var body: some View {
        VStack(spacing: 6) {
            HStack {
                Text(valueFormatter(displayLow))
                    .font(.caption.weight(.semibold).monospacedDigit())
                    .foregroundStyle(Color.accentColor)
                Spacer()
                Text(valueFormatter(displayHigh))
                    .font(.caption.weight(.semibold).monospacedDigit())
                    .foregroundStyle(Color.accentColor)
            }

            GeometryReader { geo in
                sliderTrack(width: geo.size.width)
            }
            .frame(height: handleSz)
            .contentShape(Rectangle())
            .simultaneousGesture(DragGesture(minimumDistance: 0).onChanged { _ in })
        }
        .onAppear {
            displayLow  = low
            displayHigh = high
        }
        .onChange(of: low)  { _, v in displayLow  = v }
        .onChange(of: high) { _, v in displayHigh = v }
    }
}

// MARK: - Event ID input with live autocomplete

private struct EventIdFilterView: View {
    @Binding var text: String
    let suggestions:  [String]
    let disabled:     Bool
    let onTextChange: () -> Void
    let onLoad:       () -> Void

    @FocusState private var isFocused: Bool
    @State private var suppressNextChange = false
    @State private var showSuggestions    = false

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Event ID")
                .font(.caption.weight(.semibold))
                .foregroundStyle(.secondary)
                .padding(.horizontal, 20)

            VStack(alignment: .leading, spacing: 0) {
                HStack(spacing: 6) {
                    TextField("Enter EVENT_ID", text: $text)
                        .font(.caption)
                        .autocorrectionDisabled()
                        .textInputAutocapitalization(.never)
                        .focused($isFocused)
                        .padding(.horizontal, 8)
                        .padding(.vertical, 5)
                        .background(
                            RoundedRectangle(cornerRadius: 6)
                                .fill(Color.secondary.opacity(0.12))
                        )
                        .onChange(of: text) { _, _ in
                            if suppressNextChange { suppressNextChange = false; return }
                            showSuggestions = true
                            onTextChange()
                        }
                        .onChange(of: isFocused) { _, focused in
                            if focused {
                                if !suggestions.isEmpty { showSuggestions = true }
                            } else {
                                // Delay so a suggestion button tap can register before we hide
                                Task {
                                    try? await Task.sleep(for: .milliseconds(200))
                                    showSuggestions = false
                                }
                            }
                        }
                        .onSubmit { isFocused = false; onLoad() }
                    if !text.isEmpty {
                        Button {
                            text = ""
                            showSuggestions = false
                            isFocused = false
                        } label: {
                            Image(systemName: "xmark.circle.fill")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                        .buttonStyle(.plain)
                    }
                }

                if showSuggestions && !suggestions.isEmpty {
                    VStack(alignment: .leading, spacing: 0) {
                        ForEach(suggestions, id: \.self) { id in
                            Button {
                                suppressNextChange = true
                                text = id
                                showSuggestions = false
                                isFocused = false
                                onLoad()
                            } label: {
                                Text(id)
                                    .font(.caption)
                                    .foregroundStyle(.primary)
                                    .frame(maxWidth: .infinity, alignment: .leading)
                                    .padding(.horizontal, 12)
                                    .padding(.vertical, 5)
                                    .contentShape(Rectangle())
                            }
                            .buttonStyle(.plain)
                            if id != suggestions.last { Divider().padding(.leading, 12) }
                        }
                    }
                    .background(
                        RoundedRectangle(cornerRadius: 7)
                            .fill(Color(.secondarySystemBackground))
                            .shadow(color: .black.opacity(0.18), radius: 6, y: 3)
                    )
                    .padding(.top, 2)
                }
            }
            .padding(.horizontal, 20)
            .zIndex(showSuggestions ? 10 : 0)

            Button("Load Journey") { isFocused = false; onLoad() }
                .buttonStyle(.borderedProminent)
                .controlSize(.small)
                .disabled(text.trimmingCharacters(in: .whitespaces).isEmpty || disabled)
                .frame(maxWidth: .infinity, alignment: .trailing)
                .padding(.horizontal, 20)
                .padding(.bottom, 10)
        }
        .padding(.top, 8)
    }
}

private struct MetaFilterFieldView: View {
    let label: String
    let suggestions: [String]
    @Binding var text: String

    @FocusState private var isFocused: Bool

    private var matches: [String] {
        let t = text.trimmingCharacters(in: .whitespaces)
        guard !t.isEmpty else { return [] }
        return Array(suggestions.filter { $0.localizedCaseInsensitiveContains(t) }.prefix(7))
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text(label)
                .font(.caption)
                .foregroundStyle(.secondary)
                .padding(.bottom, 3)

            HStack(spacing: 6) {
                TextField("Filter", text: $text)
                    .font(.caption)
                    .autocorrectionDisabled()
                    .textInputAutocapitalization(.never)
                    .focused($isFocused)
                    .padding(.horizontal, 8)
                    .padding(.vertical, 5)
                    .background(
                        RoundedRectangle(cornerRadius: 6)
                            .fill(Color.secondary.opacity(0.12))
                    )
                if !text.isEmpty {
                    Button { text = ""; isFocused = false } label: {
                        Image(systemName: "xmark.circle.fill")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    .buttonStyle(.plain)
                }
            }

            if isFocused && !matches.isEmpty {
                VStack(alignment: .leading, spacing: 0) {
                    ForEach(matches, id: \.self) { value in
                        Button {
                            text = value
                            isFocused = false
                        } label: {
                            Text(value)
                                .font(.caption)
                                .foregroundStyle(.primary)
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .padding(.horizontal, 12)
                                .padding(.vertical, 5)
                                .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                        if value != matches.last { Divider().padding(.leading, 12) }
                    }
                }
                .background(
                    RoundedRectangle(cornerRadius: 7)
                        .fill(Color(.secondarySystemBackground))
                        .shadow(color: .black.opacity(0.18), radius: 6, y: 3)
                )
                .padding(.top, 2)
            }
        }
        .zIndex(isFocused ? 10 : 0)
    }
}

// MARK: - Step filter list with search

struct StepFilterListView: View {
    let steps: [String]
    @Binding var selected: Set<String>
    let disabled: Set<String>

    @State private var searchText = ""

    private var filtered: [String] {
        searchText.isEmpty
            ? steps
            : steps.filter { $0.localizedCaseInsensitiveContains(searchText) }
    }

    var body: some View {
        VStack(spacing: 4) {
            HStack(spacing: 5) {
                Image(systemName: "magnifyingglass")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                TextField("Suchen", text: $searchText)
                    .font(.caption)
                    .autocorrectionDisabled()
                    .textInputAutocapitalization(.never)
                if !searchText.isEmpty {
                    Button { searchText = "" } label: {
                        Image(systemName: "xmark.circle.fill")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding(.horizontal, 8)
            .padding(.vertical, 5)
            .background(
                RoundedRectangle(cornerRadius: 6)
                    .fill(Color.secondary.opacity(0.12))
            )

            ScrollView {
                VStack(alignment: .leading, spacing: 2) {
                    if steps.isEmpty {
                        Text("Kein Projekt ausgewählt")
                            .font(.caption2)
                            .foregroundStyle(.tertiary)
                            .padding(.vertical, 4)
                            .padding(.horizontal, 8)
                    } else if filtered.isEmpty {
                        Text("Keine Treffer")
                            .font(.caption2)
                            .foregroundStyle(.tertiary)
                            .padding(.vertical, 4)
                            .padding(.horizontal, 8)
                    } else {
                        ForEach(filtered, id: \.self) { step in
                            Button {
                                if selected.contains(step) { selected.remove(step) }
                                else { selected.insert(step) }
                            } label: {
                                HStack(spacing: 6) {
                                    Image(systemName: selected.contains(step)
                                          ? "checkmark.circle.fill" : "circle")
                                        .font(.caption)
                                        .foregroundStyle(selected.contains(step)
                                                         ? Color.accentColor : Color.secondary)
                                    Text(step)
                                        .font(.caption)
                                        .lineLimit(1)
                                        .foregroundStyle(Color.primary)
                                    Spacer(minLength: 0)
                                }
                                .padding(.horizontal, 8)
                                .padding(.vertical, 3)
                                .background(
                                    RoundedRectangle(cornerRadius: 4)
                                        .fill(selected.contains(step)
                                              ? Color.accentColor.opacity(0.12) : Color.clear)
                                )
                            }
                            .buttonStyle(.plain)
                            .disabled(disabled.contains(step))
                            .opacity(disabled.contains(step) ? 0.35 : 1.0)
                        }
                    }
                }
                .padding(.vertical, 4)
            }
            .frame(maxHeight: 110)
        }
        .padding(6)
        .background(
            RoundedRectangle(cornerRadius: 8)
                .fill(Color.secondary.opacity(0.08))
        )
    }
}
