import SwiftUI

// MARK: - HappyPathView

struct HappyPathView: View {
    @ObservedObject var vm: AppViewModel

    // Contextual-menu support — same callbacks as A/B chart
    var onNodeAction:     ((String, NodeAction) -> Void)?     = nil
    var notes:            [ProcessNote]                       = []
    var ownNoteNodeNames: Set<String>                         = []
    var ownNoteEdgeIds:   Set<String>                         = []
    var onNodeNote:       ((String) -> Void)?                 = nil
    var onEdgeNote:       ((ProcessTransition) -> Void)?      = nil

    @State private var editMode          = false
    @State private var syncState         = ABSyncState()
    @State private var showNewPath       = false
    @State private var showRename        = false
    @State private var newPathName       = ""
    @State private var showRenamePreset  = false
    @State private var presetRenameId:   UUID?   = nil
    @State private var presetNewName:    String  = ""
    @State private var renamingBranchId: UUID?   = nil
    @State private var branchNewLabel:   String  = ""

    var body: some View {
        VStack(spacing: 0) {
            topBar
            Divider()
            if vm.happyPaths.isEmpty {
                emptyState
            } else if vm.selectedHappyPath == nil {
                ContentUnavailableView("No Path Selected", systemImage: "signpost.right",
                    description: Text("Select a happy path from the menu above."))
            } else {
                HStack(spacing: 0) {
                    actualPanel
                    Divider()
                    happyPathPanel
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .onAppear { Task { await vm.refreshHappyPathConformance() } }
        .onChange(of: vm.selectedHappyPathId) { _, _ in
            editMode = false
            Task { await vm.refreshHappyPathConformance() }
        }
        .alert("New Happy Path", isPresented: $showNewPath) {
            TextField("Name", text: $newPathName)
            Button("Create") {
                vm.createHappyPath(name: newPathName)
                newPathName = ""
                Task { await vm.refreshHappyPathConformance() }
            }
            Button("Cancel", role: .cancel) { newPathName = "" }
        } message: {
            Text("Enter a name for the new happy path.")
        }
        .alert("Rename Happy Path", isPresented: $showRename) {
            TextField("Name", text: $newPathName)
            Button("Rename") {
                if let id = vm.selectedHappyPathId {
                    vm.renameHappyPath(id: id, name: newPathName)
                }
                newPathName = ""
            }
            Button("Cancel", role: .cancel) { newPathName = "" }
        }
        .alert("Rename Filter Preset", isPresented: $showRenamePreset) {
            TextField("Name", text: $presetNewName)
            Button("Rename") {
                if let id = presetRenameId {
                    vm.renameFilterGroup(id: id, name: presetNewName)
                }
                presetRenameId = nil; presetNewName = ""
            }
            Button("Cancel", role: .cancel) { presetRenameId = nil; presetNewName = "" }
        }
        .alert("Rename Branch", isPresented: Binding(
            get: { renamingBranchId != nil },
            set: { if !$0 { renamingBranchId = nil; branchNewLabel = "" } }
        )) {
            TextField("Label", text: $branchNewLabel)
            Button("Rename") {
                if let pid = vm.selectedHappyPathId, let bid = renamingBranchId {
                    vm.renameHappyPathBranch(pathId: pid, branchId: bid, label: branchNewLabel)
                }
                renamingBranchId = nil; branchNewLabel = ""
            }
            Button("Cancel", role: .cancel) { renamingBranchId = nil; branchNewLabel = "" }
        }
    }

    // MARK: - Top bar

    private var topBar: some View {
        HStack(spacing: 0) {
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
                    if !vm.filterGroups.isEmpty {
                        filterGroupMenu
                    }
                }
                .padding(.horizontal, 12)
                .padding(.vertical, 8)
            }
            .frame(maxWidth: .infinity)

            Divider().frame(height: 36)

            HStack(spacing: 0) {
                if !vm.happyPaths.isEmpty {
                    pathSelectorMenu
                        .padding(.horizontal, 8)
                }
                if let score = vm.happyPathScore {
                    conformanceBadge(score: score)
                        .padding(.horizontal, 8)
                }
                Spacer(minLength: 0)
                if vm.selectedHappyPath != nil {
                    Divider().frame(height: 36)
                    Button {
                        withAnimation(.easeInOut(duration: 0.2)) { editMode.toggle() }
                    } label: {
                        HStack(spacing: 4) {
                            Image(systemName: editMode ? "checkmark" : "pencil").font(.caption2)
                            Text(editMode ? "Done" : "Edit Path").font(.caption2.weight(.medium))
                        }
                        .padding(.horizontal, 8)
                        .padding(.vertical, 5)
                        .background(editMode ? Color.accentColor : Color.primary.opacity(0.07))
                        .foregroundStyle(editMode ? Color.white : Color.primary)
                        .clipShape(Capsule())
                    }
                    .buttonStyle(.plain)
                    .padding(.horizontal, 8)
                }
            }
            .frame(maxWidth: .infinity)
        }
        .background(Color(.secondarySystemGroupedBackground))
    }

    // MARK: - Filter group preset menu

    @ViewBuilder
    private var filterGroupMenu: some View {
        Menu {
            ForEach(vm.filterGroups) { group in
                Button {
                    vm.applyFilterGroup(group)
                    Task { await vm.reloadGraph() }
                } label: {
                    if group.id == vm.selectedFilterGroupId {
                        Label(group.name, systemImage: "checkmark")
                    } else {
                        Text(group.name)
                    }
                }
            }
            Divider()
            if vm.selectedFilterGroup != nil {
                Button {
                    presetRenameId   = vm.selectedFilterGroupId
                    presetNewName    = vm.selectedFilterGroup?.name ?? ""
                    showRenamePreset = true
                } label: {
                    Label("Rename\u{2026}", systemImage: "pencil")
                }
                Button(role: .destructive) {
                    if let id = vm.selectedFilterGroupId { vm.deleteFilterGroup(id: id) }
                } label: {
                    Label("Delete", systemImage: "trash")
                }
            }
        } label: {
            HStack(spacing: 4) {
                Image(systemName: "slider.horizontal.3")
                    .font(.caption2)
                    .foregroundStyle(vm.selectedFilterGroupId != nil ? Color.accentColor : Color.secondary)
                Text(vm.selectedFilterGroup?.name ?? "Presets")
                    .font(.caption2.weight(.medium)).lineLimit(1)
                Image(systemName: "chevron.up.chevron.down")
                    .font(.caption2).foregroundStyle(.secondary)
            }
            .padding(.horizontal, 8).padding(.vertical, 5)
            .background(Color.primary.opacity(0.07))
            .clipShape(Capsule())
        }
    }

    // MARK: - Path selector menu

    private var pathSelectorMenu: some View {
        Menu {
            ForEach(vm.happyPaths) { path in
                Button {
                    vm.selectHappyPath(id: path.id)
                } label: {
                    if path.id == vm.selectedHappyPathId {
                        Label(path.name, systemImage: "checkmark")
                    } else {
                        Text(path.name)
                    }
                }
            }
            Divider()
            Button {
                newPathName = ""; showNewPath = true
            } label: {
                Label("New Happy Path\u{2026}", systemImage: "plus")
            }
            if vm.selectedHappyPath != nil {
                Button {
                    newPathName = vm.selectedHappyPath?.name ?? ""
                    showRename = true
                } label: {
                    Label("Rename\u{2026}", systemImage: "pencil")
                }
                Button(role: .destructive) {
                    if let id = vm.selectedHappyPathId { vm.deleteHappyPath(id: id) }
                } label: {
                    Label("Delete", systemImage: "trash")
                }
            }
        } label: {
            HStack(spacing: 4) {
                Image(systemName: "signpost.right.fill")
                    .font(.caption2).foregroundStyle(Color.accentColor)
                Text(vm.selectedHappyPath?.name ?? "Select Path")
                    .font(.caption2.weight(.medium)).lineLimit(1)
                Image(systemName: "chevron.up.chevron.down")
                    .font(.caption2).foregroundStyle(.secondary)
            }
            .padding(.horizontal, 8).padding(.vertical, 5)
            .background(Color.primary.opacity(0.07))
            .clipShape(Capsule())
        }
    }

    // MARK: - Conformance badge

    private func conformanceBadge(score: Double) -> some View {
        let color: Color = score >= 0.7 ? .green : score <= 0.3 ? .red : .orange
        return HStack(spacing: 6) {
            Image(systemName: "signpost.right.fill")
                .font(.caption2).foregroundStyle(color)
            Text("Conformance")
                .font(.caption2).foregroundStyle(.secondary)
            Text(score.formatted(.number.precision(.fractionLength(2))))
                .font(.callout.weight(.semibold))
                .monospacedDigit().foregroundStyle(color)
        }
        .padding(.horizontal, 10).padding(.vertical, 6)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(color.opacity(0.45), lineWidth: 1.5))
    }

    // MARK: - Actual process panel (left)

    private var actualPanel: some View {
        VStack(spacing: 0) {
            HStack {
                Text("Actual Process")
                    .font(.caption.weight(.semibold)).foregroundStyle(.secondary)
                    .padding(.leading, 12).padding(.vertical, 7)
                Spacer()
                if let count = vm.journeyCount {
                    Text("\(count.formatted()) journeys")
                        .font(.caption2.monospacedDigit()).foregroundStyle(.secondary)
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
                        Text("Apply filters in the sidebar to load the process map.")
                    } actions: {
                        Button("Load") { Task { await vm.reloadGraph() } }
                            .buttonStyle(.borderedProminent)
                    }
                }
            } else {
                FlowChartView(
                    graph:            vm.processGraph,
                    projectId:        vm.selectedProject?.projectId ?? "",
                    chartMode:        "happyPath_\(vm.selectedProject?.projectId ?? "")",
                    metric:           vm.transitionMetric,
                    isLoading:        vm.isLoading,
                    syncState:        syncState,
                    onNodeAction:     onNodeAction,
                    notes:            notes.isEmpty ? nil : notes,
                    ownNoteNodeNames: ownNoteNodeNames,
                    ownNoteEdgeIds:   ownNoteEdgeIds,
                    onNodeNote:       onNodeNote,
                    onEdgeNote:       onEdgeNote
                )
                .id(vm.selectedProject?.projectId)
                .overlay(alignment: .top) {
                    if vm.isLoading {
                        ProgressView()
                            .padding(.horizontal, 16).padding(.vertical, 8)
                            .background(.regularMaterial, in: Capsule())
                            .padding(.top, 12).transition(.opacity)
                    }
                }
            }
        }
        .frame(maxWidth: .infinity)
    }

    // MARK: - Happy Path panel (right)

    private var happyPathPanel: some View {
        VStack(spacing: 0) {
            HStack {
                Text(vm.selectedHappyPath?.name ?? "Happy Path")
                    .font(.caption.weight(.semibold)).foregroundStyle(.secondary)
                    .padding(.leading, 12).padding(.vertical, 7)
                Spacer()
                if editMode, let path = vm.selectedHappyPath {
                    addStepMenu(for: path, branchId: nil) {
                        Image(systemName: "plus")
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(Color.accentColor)
                    }
                    .padding(.trailing, 12)
                }
            }
            .background(Color(.secondarySystemGroupedBackground))
            Divider()

            if let path = vm.selectedHappyPath {
                if path.steps.isEmpty {
                    ContentUnavailableView(
                        "No Steps Defined",
                        systemImage: "signpost.right",
                        description: Text(editMode
                            ? "Tap + to add the first step."
                            : "Enable Edit mode to define the happy path.")
                    )
                } else if editMode {
                    happyPathEditor(path: path)
                } else {
                    happyPathVisualisation(path: path)
                }
            }
        }
        .frame(maxWidth: .infinity)
    }

    // MARK: - Visualisation (view mode)

    private func happyPathVisualisation(path: HappyPath) -> some View {
        let steps    = path.steps
        let branches = path.branches
        let coverage = stepCoverageMap
        return ScrollView {
            VStack(spacing: 0) {
                // Trunk steps
                ForEach(Array(steps.enumerated()), id: \.offset) { idx, step in
                    let inGraph = vm.processGraph.steps[step] != nil
                    ZStack(alignment: .topTrailing) {
                        stepCard(step, inGraph: inGraph, coverage: coverage[step])
                            .padding(.horizontal, 24)
                            .padding(.top, idx == 0 ? 16 : 0)
                        if !branches.isEmpty && idx == steps.count - 1 {
                            Text("+")
                                .font(.caption2.weight(.bold))
                                .foregroundStyle(.white)
                                .padding(.horizontal, 5).padding(.vertical, 2)
                                .background(Color.accentColor, in: Capsule())
                                .padding(.top, idx == 0 ? 20 : 4)
                                .padding(.trailing, 28)
                        }
                    }
                    if idx < steps.count - 1 {
                        Image(systemName: "chevron.down")
                            .font(.caption2.weight(.semibold))
                            .foregroundStyle(.secondary)
                            .padding(.vertical, 4)
                    }
                }

                // Branch section
                if !branches.isEmpty {
                    HStack(spacing: 6) {
                        Rectangle().fill(Color.secondary.opacity(0.25)).frame(height: 1)
                        Image(systemName: "arrow.triangle.branch")
                            .font(.caption2).foregroundStyle(.secondary)
                        Rectangle().fill(Color.secondary.opacity(0.25)).frame(height: 1)
                    }
                    .padding(.horizontal, 24)
                    .padding(.top, 8).padding(.bottom, 0)

                    HStack(alignment: .top, spacing: 0) {
                        ForEach(Array(branches.enumerated()), id: \.element.id) { idx, branch in
                            if idx > 0 { Divider() }
                            branchColumn(branch, number: idx + 1, coverage: coverage)
                        }
                    }
                    .frame(maxWidth: .infinity)
                }
            }
            .padding(.bottom, 16)
        }
    }

    // Coverage percentage per step: max(incoming, outgoing) occurrences / total journeys
    private var stepCoverageMap: [String: Double] {
        guard let total = vm.journeyCount, total > 0 else { return [:] }
        var incoming: [String: Int] = [:]
        var outgoing: [String: Int] = [:]
        for t in vm.processGraph.transitions {
            outgoing[t.fromStep, default: 0] += t.occurrences
            incoming[t.toStep, default: 0]   += t.occurrences
        }
        var result: [String: Double] = [:]
        for step in vm.processGraph.steps.keys {
            let count = max(incoming[step] ?? 0, outgoing[step] ?? 0)
            result[step] = min(1.0, Double(count) / Double(total))
        }
        return result
    }

    // Shared step card used in both trunk and branch columns
    private func stepCard(_ name: String, inGraph: Bool, coverage: Double? = nil) -> some View {
        VStack(spacing: 2) {
            Text(name)
                .font(.caption.weight(.medium))
                .foregroundStyle(inGraph ? .primary : .secondary)
                .multilineTextAlignment(.center)
            if inGraph, let pct = coverage {
                Text(String(format: "%.0f%%", pct * 100))
                    .font(.caption2.monospacedDigit())
                    .foregroundStyle(Color.green.opacity(0.8))
            }
        }
        .frame(maxWidth: .infinity)
        .padding(.horizontal, 12).padding(.vertical, 8)
        .background(
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .fill(inGraph ? Color.green.opacity(0.12) : Color.primary.opacity(0.06))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .strokeBorder(
                    inGraph ? Color.green.opacity(0.5) : Color.primary.opacity(0.15),
                    lineWidth: 1)
        )
    }

    private func branchColumn(_ branch: HappyPathBranch, number: Int, coverage: [String: Double]) -> some View {
        let label = branch.label.isEmpty ? "Branch \(number)" : branch.label
        return VStack(spacing: 0) {
            Text(label)
                .font(.caption2.weight(.semibold))
                .foregroundStyle(.secondary)
                .padding(.top, 10).padding(.bottom, 6)
            if branch.steps.isEmpty {
                Text("No steps")
                    .font(.caption2).foregroundStyle(.tertiary)
                    .padding(12)
            } else {
                ForEach(Array(branch.steps.enumerated()), id: \.offset) { idx, step in
                    let inGraph = vm.processGraph.steps[step] != nil
                    stepCard(step, inGraph: inGraph, coverage: coverage[step])
                        .padding(.horizontal, 12)
                    if idx < branch.steps.count - 1 {
                        Image(systemName: "chevron.down")
                            .font(.caption2.weight(.semibold))
                            .foregroundStyle(.secondary)
                            .padding(.vertical, 3)
                    }
                }
            }
        }
        .padding(.bottom, 12)
        .frame(maxWidth: .infinity)
    }

    // MARK: - Add-step drop-down

    /// Steps not already used anywhere in the path (trunk or any branch), sorted.
    private func availableSteps(for path: HappyPath) -> [String] {
        var used = Set(path.steps)
        for branch in path.branches { used.formUnion(branch.steps) }
        return vm.allSteps.filter { !used.contains($0) }.sorted()
    }

    /// A drop-down menu that lists the selectable steps. `branchId` nil targets the
    /// trunk; otherwise the step is appended to that branch.
    private func addStepMenu<Label: View>(
        for path: HappyPath,
        branchId: UUID?,
        @ViewBuilder label: () -> Label
    ) -> some View {
        let available = availableSteps(for: path)
        return Menu {
            if available.isEmpty {
                Text("All steps already added")
            } else {
                ForEach(available, id: \.self) { step in
                    Button(step) {
                        if let branchId {
                            vm.addStepToBranch(pathId: path.id, branchId: branchId, step: step)
                        } else {
                            vm.addHappyPathStep(toPath: path.id, step: step)
                        }
                        Task { await vm.refreshHappyPathConformance() }
                    }
                }
            }
        } label: {
            label()
        }
        .menuIndicator(.hidden)
        .fixedSize()
        .disabled(available.isEmpty)
    }

    // MARK: - Editor (edit mode)

    /// A step row in the editor with an explicit delete button (macOS has no
    /// swipe-to-delete or edit-mode minus affordance).
    private func stepEditRow(_ step: String, delete: @escaping () -> Void) -> some View {
        HStack {
            Text(step).font(.body)
            Spacer(minLength: 8)
            Button(role: .destructive, action: delete) {
                Image(systemName: "minus.circle.fill")
                    .foregroundStyle(.red)
            }
            .buttonStyle(.borderless)
            .help("Remove step")
        }
    }

    private func happyPathEditor(path: HappyPath) -> some View {
        VStack(spacing: 0) {
            List {
                // Trunk
                Section {
                    ForEach(Array(path.steps.enumerated()), id: \.offset) { idx, step in
                        stepEditRow(step) {
                            if let id = vm.selectedHappyPathId {
                                vm.removeHappyPathSteps(pathId: id, at: IndexSet(integer: idx))
                                Task { await vm.refreshHappyPathConformance() }
                            }
                        }
                    }
                    .onDelete { offsets in
                        if let id = vm.selectedHappyPathId {
                            vm.removeHappyPathSteps(pathId: id, at: offsets)
                            Task { await vm.refreshHappyPathConformance() }
                        }
                    }
                    .onMove { from, to in
                        if let id = vm.selectedHappyPathId {
                            vm.moveHappyPathSteps(pathId: id, from: from, to: to)
                            Task { await vm.refreshHappyPathConformance() }
                        }
                    }
                } header: {
                    Text("Trunk").font(.caption.weight(.semibold))
                }

                // Branch sections
                ForEach(Array(path.branches.enumerated()), id: \.element.id) { bIdx, branch in
                    Section {
                        ForEach(Array(branch.steps.enumerated()), id: \.offset) { idx, step in
                            stepEditRow(step) {
                                vm.removeStepsFromBranch(pathId: path.id, branchId: branch.id, at: IndexSet(integer: idx))
                                Task { await vm.refreshHappyPathConformance() }
                            }
                        }
                        .onDelete { offsets in
                            vm.removeStepsFromBranch(pathId: path.id, branchId: branch.id, at: offsets)
                            Task { await vm.refreshHappyPathConformance() }
                        }
                        .onMove { from, to in
                            vm.moveStepsInBranch(pathId: path.id, branchId: branch.id, from: from, to: to)
                            Task { await vm.refreshHappyPathConformance() }
                        }
                    } header: {
                        HStack(spacing: 8) {
                            Text(branch.label.isEmpty ? "Branch \(bIdx + 1)" : branch.label)
                                .font(.caption.weight(.semibold))
                            Spacer(minLength: 0)
                            Button {
                                branchNewLabel   = branch.label
                                renamingBranchId = branch.id
                            } label: {
                                Image(systemName: "pencil")
                                    .font(.caption).foregroundStyle(.secondary)
                            }
                            .buttonStyle(.plain)
                            addStepMenu(for: path, branchId: branch.id) {
                                Image(systemName: "plus")
                                    .font(.caption).foregroundStyle(Color.accentColor)
                            }
                            Button {
                                vm.removeHappyPathBranch(pathId: path.id, branchId: branch.id)
                                Task { await vm.refreshHappyPathConformance() }
                            } label: {
                                Image(systemName: "trash")
                                    .font(.caption).foregroundStyle(.red)
                            }
                            .buttonStyle(.plain)
                        }
                    }
                }
            }
            .listStyle(.plain)
            #if os(iOS)
            .environment(\.editMode, .constant(.active))
            #endif

            Divider()
            Button {
                if let id = vm.selectedHappyPathId {
                    vm.addHappyPathBranch(pathId: id)
                    Task { await vm.refreshHappyPathConformance() }
                }
            } label: {
                Label("Add Alternative Path (Branch)", systemImage: "arrow.triangle.branch")
                    .font(.callout.weight(.medium))
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.large)
            .padding(12)
            .background(Color(.secondarySystemGroupedBackground))
        }
    }

    // MARK: - Empty state

    private var emptyState: some View {
        ContentUnavailableView {
            Label("No Happy Paths", systemImage: "signpost.right.fill")
        } description: {
            Text("Create a happy path to define the ideal sequence of steps and measure conformance.")
        } actions: {
            Button("New Happy Path") {
                newPathName = ""
                showNewPath = true
            }
            .buttonStyle(.borderedProminent)
        }
    }
}

