import SwiftUI
import Charts
import UniformTypeIdentifiers

// MARK: - CSV file document

struct SimulationCSVDocument: FileDocument {
    static var readableContentTypes:  [UTType] { [.commaSeparatedText] }
    static var writableContentTypes:  [UTType] { [.commaSeparatedText] }

    let content: String

    init(content: String) { self.content = content }

    init(configuration: ReadConfiguration) throws {
        content = String(
            data: configuration.file.regularFileContents ?? Data(),
            encoding: .utf8
        ) ?? ""
    }

    func fileWrapper(configuration: WriteConfiguration) throws -> FileWrapper {
        FileWrapper(regularFileWithContents: content.data(using: .utf8) ?? Data())
    }
}

// MARK: - Main view

struct SimulationView: View {
    @ObservedObject var vm: AppViewModel

    // Target slot for storing the result
    @State private var simTarget: SimSlot = .simA

    // Configuration state
    @State private var journeyCount          = 200
    @State private var startDate             = Date()
    @State private var avgInterArrivalHours  = 2.0
    @State private var maxStepsPerJourney    = 60
    @State private var excludedSteps: Set<String> = []
    @State private var requiredSteps: Set<String> = []
    @State private var excludedExpanded      = false
    @State private var includedExpanded      = false

    // Execution state
    @State private var isRunning             = false
    @State private var result: SimulationResult? = nil
    @State private var resultsTab            = ResultsTab.flow

    // Export state
    @State private var showExporter          = false
    @State private var csvDocument: SimulationCSVDocument? = nil

    @Environment(\.horizontalSizeClass) private var hsc

    var body: some View {
        Group {
            if hsc == .regular {
                HStack(alignment: .top, spacing: 0) {
                    configPanel
                        .frame(width: 310)
                    Divider()
                    resultsPanel
                }
            } else {
                ScrollView {
                    VStack(alignment: .leading, spacing: 0) {
                        configPanel
                        Divider()
                        resultsPanel.frame(minHeight: 380)
                    }
                }
            }
        }
        .background(Color(.systemGroupedBackground))
        .fileExporter(
            isPresented: $showExporter,
            document: csvDocument,
            contentType: .commaSeparatedText,
            defaultFilename: "simulation_log"
        ) { _ in csvDocument = nil }
        // Auto-load the process graph when entering simulation with no data yet
        .task {
            if vm.processGraph.transitions.isEmpty, vm.selectedProject != nil, !vm.isLoading {
                await vm.reloadGraph()
            }
        }
    }

    // MARK: – Config panel

    private var configPanel: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 0) {

                if vm.isLoading {
                    HStack(spacing: 8) {
                        ProgressView().controlSize(.small)
                        Text("Loading process data…")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    .padding(.horizontal, 20)
                    .padding(.top, 16)
                    .padding(.bottom, 4)
                } else if vm.processGraph.transitions.isEmpty {
                    HStack(alignment: .top, spacing: 8) {
                        Image(systemName: "exclamationmark.triangle")
                            .font(.subheadline)
                            .foregroundStyle(.orange)
                        Text("No process data available. Select a project and ensure data is loaded in the A-Chart first.")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    .padding(.horizontal, 20)
                    .padding(.top, 16)
                    .padding(.bottom, 4)
                } else {
                    HStack(spacing: 6) {
                        Image(systemName: "checkmark.circle.fill")
                            .font(.caption)
                            .foregroundStyle(.green)
                        Text("Calibrated from \(vm.processGraph.transitions.count) transitions")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    .padding(.horizontal, 20)
                    .padding(.top, 12)
                    .padding(.bottom, 2)
                }

                sectionHeader("Store Result As")

                configCard {
                    Picker("Target", selection: $simTarget) {
                        ForEach(SimSlot.allCases) { slot in
                            Text(slot.rawValue).tag(slot)
                        }
                    }
                    .pickerStyle(.segmented)
                    .padding(.horizontal, 14)
                    .padding(.vertical, 10)

                    Divider().padding(.leading, 14)

                    ForEach(SimSlot.allCases) { slot in
                        let stored = slot == .simA ? vm.simResultA : vm.simResultB
                        let isTarget = slot == simTarget
                        HStack(spacing: 10) {
                            Image(systemName: stored != nil ? "checkmark.circle.fill" : "circle.dashed")
                                .font(.caption)
                                .foregroundStyle(stored != nil ? (isTarget ? Color.accentColor : .green) : .secondary)
                            VStack(alignment: .leading, spacing: 1) {
                                Text(slot.rawValue)
                                    .font(.caption.weight(isTarget ? .semibold : .regular))
                                    .foregroundStyle(isTarget ? Color.accentColor : .primary)
                                if let r = stored {
                                    Text("\(r.totalJourneys.formatted()) journeys · \(r.variants.count.formatted()) variants")
                                        .font(.caption2)
                                        .foregroundStyle(.secondary)
                                } else {
                                    Text("Not loaded")
                                        .font(.caption2)
                                        .foregroundStyle(.secondary)
                                }
                            }
                            Spacer(minLength: 0)
                            if stored != nil {
                                Button {
                                    vm.switchChartMode(to: .abComparison)
                                    Task {
                                        await vm.setABDataSource(
                                            .simulation(slot),
                                            for: slot == .simA ? .a : .b
                                        )
                                    }
                                } label: {
                                    Label("Open in A/B", systemImage: "arrow.left.arrow.right.circle")
                                        .font(.caption2)
                                        .foregroundStyle(Color.accentColor)
                                }
                                .buttonStyle(.borderless)
                            }
                        }
                        .padding(.horizontal, 14)
                        .padding(.vertical, 7)
                        if slot != SimSlot.allCases.last { Divider().padding(.leading, 14) }
                    }
                }

                sectionHeader("Parameters")

                configCard {
                    paramRow("Journey Count") {
                        Stepper(
                            value: $journeyCount,
                            in: 10 ... 10_000,
                            step: journeyCount < 100 ? 10 : journeyCount < 1_000 ? 50 : 100
                        ) {
                            Text(journeyCount.formatted())
                                .monospacedDigit()
                                .frame(minWidth: 56, alignment: .trailing)
                                .font(.subheadline)
                        }
                    }
                    rowDiv()
                    paramRow("Start Date") {
                        DatePicker("", selection: $startDate, displayedComponents: [.date])
                            .labelsHidden()
                    }
                    rowDiv()
                    paramRow("Avg Arrival (h)") {
                        Stepper(value: $avgInterArrivalHours, in: 0.1 ... 720.0, step: 0.5) {
                            Text(String(format: "%.1f", avgInterArrivalHours))
                                .monospacedDigit()
                                .frame(minWidth: 44, alignment: .trailing)
                                .font(.subheadline)
                        }
                    }
                    rowDiv()
                    paramRow("Max Steps") {
                        Stepper(value: $maxStepsPerJourney, in: 10 ... 200, step: 5) {
                            Text("\(maxStepsPerJourney)")
                                .monospacedDigit()
                                .frame(minWidth: 36, alignment: .trailing)
                                .font(.subheadline)
                        }
                    }
                }

                Divider()
                    .padding(.top, 12)

                // Exclude Steps — sidebar-style header + StepFilterListView
                stepFilterHeader("Exclude Steps", count: excludedSteps.count,
                                  expanded: $excludedExpanded) {
                    excludedSteps.removeAll()
                }
                if excludedExpanded {
                    StepFilterListView(
                        steps: vm.allSteps,
                        selected: $excludedSteps,
                        disabled: requiredSteps
                    )
                    .padding(.horizontal, 20)
                    .padding(.bottom, 10)
                }

                Divider()

                // Include Steps — sidebar-style header + StepFilterListView
                stepFilterHeader("Include Steps", count: requiredSteps.count,
                                  expanded: $includedExpanded) {
                    requiredSteps.removeAll()
                }
                if includedExpanded {
                    StepFilterListView(
                        steps: vm.allSteps,
                        selected: $requiredSteps,
                        disabled: excludedSteps
                    )
                    .padding(.horizontal, 20)
                    .padding(.bottom, 10)
                }

                Divider()
                    .padding(.bottom, 6)

                // Simulate button
                let buttonActive = canSimulate && !isRunning && !vm.isLoading
                Button { runSimulation() } label: {
                    HStack(spacing: 8) {
                        if isRunning || vm.isLoading {
                            ProgressView()
                                .controlSize(.small)
                                .tint(.white)
                        } else {
                            Image(systemName: "play.fill")
                        }
                        Text(isRunning ? "Simulating…" : vm.isLoading ? "Loading data…" : "Simulate")
                            .font(.headline)
                    }
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 12)
                    .background(
                        buttonActive ? Color.accentColor : Color.secondary.opacity(0.25),
                        in: RoundedRectangle(cornerRadius: 12, style: .continuous)
                    )
                    .foregroundStyle(buttonActive ? Color.white : Color.secondary)
                }
                .buttonStyle(.plain)
                .disabled(!buttonActive)
                .padding(.horizontal, 16)
                .padding(.top, 16)
                .padding(.bottom, 24)
                .animation(.easeInOut(duration: 0.15), value: canSimulate)
            }
        }
    }

    // MARK: – Results panel

    @ViewBuilder
    private var resultsPanel: some View {
        if isRunning {
            VStack(spacing: 12) {
                ProgressView()
                Text("Running simulation…")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        } else if let r = result {
            resultsContent(r)
        } else {
            VStack(spacing: 14) {
                Image(systemName: "chart.line.flattrend.xyaxis")
                    .font(.system(size: 44))
                    .foregroundStyle(.secondary.opacity(0.35))
                Text("Configure parameters and tap Simulate")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
                    .frame(maxWidth: 250)
                Text("The model calibrates automatically from the current process graph.")
                    .font(.caption)
                    .foregroundStyle(.tertiary)
                    .multilineTextAlignment(.center)
                    .frame(maxWidth: 250)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
    }

    @ViewBuilder
    private func resultsContent(_ r: SimulationResult) -> some View {
        VStack(spacing: 0) {

            // KPI strip — always visible, identical on all three tabs
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 12) {
                    kpiTile(value: r.totalJourneys.formatted(),        label: "Simulated Journeys", icon: "person.3.fill")
                    kpiTile(value: r.variants.count.formatted(),        label: "Variants",           icon: "arrow.triangle.branch")
                    kpiTile(value: formatSecs(r.minCycleTimeSecs),     label: "Shortest Journey",   icon: "hare")
                    kpiTile(value: formatSecs(r.avgCycleTimeSecs),     label: "Avg Journey",        icon: "timer")
                    kpiTile(value: formatSecs(r.stdDevCycleTimeSecs),  label: "Std Dev",            icon: "waveform.path.ecg")
                    kpiTile(value: formatSecs(r.maxCycleTimeSecs),     label: "Longest Journey",    icon: "tortoise")
                }
                .padding(.horizontal, 20)
                .padding(.vertical, 14)
            }
            .background(Color(.systemBackground))

            Divider()

            // Export + tab picker — always visible
            HStack(spacing: 10) {
                Button {
                    csvDocument = SimulationCSVDocument(content: makeCSV(r))
                    showExporter = true
                } label: {
                    Label("Export CSV", systemImage: "square.and.arrow.up")
                        .font(.subheadline)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 9)
                        .background(
                            Color(.secondarySystemGroupedBackground),
                            in: RoundedRectangle(cornerRadius: 10, style: .continuous)
                        )
                        .foregroundStyle(.primary)
                }
                .buttonStyle(.plain)

                Picker("View", selection: $resultsTab) {
                    ForEach(ResultsTab.allCases, id: \.self) { tab in
                        Text(tab.rawValue)
                            .lineLimit(1)
                            .fixedSize()
                            .tag(tab)
                    }
                }
                .pickerStyle(.segmented)
                .fixedSize(horizontal: true, vertical: false)
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 10)
            .background(Color(.systemGroupedBackground))

            Divider()

            // Content — fills remaining height
            switch resultsTab {
            case .table:
                ScrollView { variantTable(r) }
            case .charts:
                ScrollView { chartsView(r) }
            case .flow:
                FlowChartView(
                    graph:     r.simProcessGraph,
                    projectId: (vm.selectedProject?.projectId ?? "sim") + "_sim",
                    chartMode: "simulation",
                    metric:    .count
                )
                .id(r.runId)
            }
        }
    }

    // MARK: – Variant table

    @ViewBuilder
    private func variantTable(_ r: SimulationResult) -> some View {
        let shown = r.variants.prefix(50)
        sectionHeader("Variant Distribution — Top \(shown.count) of \(r.variants.count)")

        configCard {
            HStack(spacing: 0) {
                Text("#")
                    .frame(width: 28, alignment: .trailing)
                Text("Path")
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.leading, 8)
                Text("N")
                    .frame(width: 46, alignment: .trailing)
                Text("%")
                    .frame(width: 44, alignment: .trailing)
                Text("Avg")
                    .frame(width: 58, alignment: .trailing)
            }
            .font(.caption2.weight(.semibold))
            .foregroundStyle(.secondary)
            .padding(.horizontal, 12)
            .padding(.vertical, 6)
            .background(Color.primary.opacity(0.04))

            ForEach(Array(shown.enumerated()), id: \.element.id) { idx, v in
                Divider().padding(.leading, 12)
                HStack(spacing: 0) {
                    Text("\(idx + 1)")
                        .font(.caption2.weight(.medium))
                        .foregroundStyle(.secondary)
                        .frame(width: 28, alignment: .trailing)
                    Text(v.path)
                        .font(.caption2)
                        .lineLimit(1)
                        .truncationMode(.middle)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(.leading, 8)
                        .help(v.path)
                    Text(v.count.formatted())
                        .font(.caption2.weight(.medium))
                        .monospacedDigit()
                        .frame(width: 46, alignment: .trailing)
                    Text(String(format: "%.1f%%", v.percentage))
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                        .monospacedDigit()
                        .frame(width: 44, alignment: .trailing)
                    Text(formatSecs(v.avgCycleTimeSecs))
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                        .monospacedDigit()
                        .frame(width: 58, alignment: .trailing)
                }
                .padding(.horizontal, 12)
                .padding(.vertical, 5)
            }
        }
        .padding(.bottom, 24)
    }

    // MARK: – Charts view

    @ViewBuilder
    private func chartsView(_ r: SimulationResult) -> some View {
        // Top-10 variant bar chart (horizontal)
        let top = Array(r.variants.prefix(10).enumerated())
        sectionHeader("Top \(top.count) Variants by Count")

        configCard {
            Chart(top, id: \.offset) { idx, v in
                BarMark(
                    x: .value("Count", v.count),
                    y: .value("Variant", "V\(idx + 1)")
                )
                .foregroundStyle(Color.accentColor.gradient)
                .annotation(position: .trailing, alignment: .leading) {
                    Text(String(format: "%.0f%%", v.percentage))
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                        .fixedSize()
                }
            }
            .chartYAxis {
                AxisMarks { _ in AxisValueLabel() }
            }
            .chartXAxisLabel("Journey count")
            .frame(height: CGFloat(top.count) * 34 + 24)
            .padding(.horizontal, 16)
            .padding(.vertical, 12)
        }

        // Variant key (V1 = ... legend)
        configCard {
            VStack(alignment: .leading, spacing: 4) {
                ForEach(top, id: \.offset) { idx, v in
                    HStack(alignment: .top, spacing: 6) {
                        Text("V\(idx + 1)")
                            .font(.caption2.weight(.semibold))
                            .foregroundStyle(Color.accentColor)
                            .frame(width: 24, alignment: .trailing)
                        Text(v.path)
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                            .lineLimit(2)
                    }
                    if idx < top.count - 1 { Divider().padding(.leading, 30) }
                }
            }
            .padding(12)
        }

        // Cycle-time histogram
        let buckets = cycleTimeBuckets(from: r.cycleTimes)
        sectionHeader("Cycle Time Distribution (\(r.cycleTimes.count) journeys)")

        configCard {
            if buckets.isEmpty {
                Text("No data")
                    .font(.caption).foregroundStyle(.secondary).padding(12)
            } else {
                Chart(buckets, id: \.index) { b in
                    BarMark(
                        x: .value("Midpoint (s)", b.midSecs),
                        y: .value("Journeys", b.count)
                    )
                    .foregroundStyle(Color.accentColor.opacity(0.85).gradient)
                }
                .chartXAxis {
                    AxisMarks(values: .automatic(desiredCount: 6)) { v in
                        AxisValueLabel {
                            if let s = v.as(Double.self) {
                                Text(formatSecs(s)).font(.caption2)
                            }
                        }
                        AxisGridLine()
                    }
                }
                .chartYAxisLabel("Journeys")
                .frame(height: 180)
                .padding(.horizontal, 16)
                .padding(.vertical, 12)
            }
        }
        .padding(.bottom, 24)
    }

    // MARK: – Cycle-time histogram helper

    private struct CycleTimeBucket {
        let index:   Int
        let midSecs: Double
        let count:   Int
    }

    private func cycleTimeBuckets(from times: [Double], binCount: Int = 12) -> [CycleTimeBucket] {
        guard times.count > 1, let mn = times.min(), let mx = times.max(), mx > mn else {
            return times.isEmpty ? [] : [CycleTimeBucket(index: 0, midSecs: times[0], count: times.count)]
        }
        let width = (mx - mn) / Double(binCount)
        var counts = Array(repeating: 0, count: binCount)
        for t in times {
            let idx = min(Int((t - mn) / width), binCount - 1)
            counts[idx] += 1
        }
        return counts.enumerated().compactMap { i, c in
            guard c > 0 else { return nil }
            return CycleTimeBucket(index: i, midSecs: mn + (Double(i) + 0.5) * width, count: c)
        }
    }

    // MARK: – Results tab enum

    enum ResultsTab: String, CaseIterable {
        case flow   = "Flow"
        case table  = "Table"
        case charts = "Charts"
    }

    // MARK: – Step filter header (mirrors sidebar filterSubHeader)

    private func stepFilterHeader(
        _ title: String,
        count: Int,
        expanded: Binding<Bool>,
        onClear: @escaping () -> Void
    ) -> some View {
        HStack(spacing: 0) {
            Button {
                withAnimation(.easeInOut(duration: 0.15)) { expanded.wrappedValue.toggle() }
            } label: {
                HStack(spacing: 5) {
                    Image(systemName: "chevron.right")
                        .font(.caption2.weight(.semibold))
                        .foregroundStyle(.tertiary)
                        .frame(width: 10, alignment: .center)
                        .rotationEffect(.degrees(expanded.wrappedValue ? 90 : 0))
                    Text(title)
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(.secondary)
                    Spacer(minLength: 0)
                }
                .contentShape(Rectangle())
                .padding(.vertical, 6)
            }
            .buttonStyle(.plain)

            if count > 0 {
                Text("\(count)")
                    .font(.caption2.weight(.medium))
                    .foregroundStyle(.white)
                    .padding(.horizontal, 5)
                    .padding(.vertical, 1)
                    .background(Color.accentColor, in: Capsule())
                Button { onClear() } label: {
                    Image(systemName: "xmark.circle.fill")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                .buttonStyle(.plain)
                .padding(.trailing, 4)
            }
        }
        .padding(.horizontal, 20)
    }

    // MARK: – Layout helpers

    private func sectionHeader(_ title: String) -> some View {
        Text(title.uppercased())
            .font(.caption.weight(.semibold))
            .foregroundStyle(.secondary)
            .padding(.horizontal, 20)
            .padding(.top, 16)
            .padding(.bottom, 4)
    }

    @ViewBuilder
    private func configCard<C: View>(@ViewBuilder _ content: () -> C) -> some View {
        VStack(spacing: 0) { content() }
            .background(
                Color(.secondarySystemGroupedBackground),
                in: RoundedRectangle(cornerRadius: 12, style: .continuous)
            )
            .padding(.horizontal, 16)
    }

    private func paramRow<C: View>(_ label: String, @ViewBuilder control: () -> C) -> some View {
        HStack(spacing: 8) {
            Text(label)
                .font(.subheadline)
                .frame(maxWidth: .infinity, alignment: .leading)
            control()
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 8)
    }

    private func rowDiv() -> some View {
        Divider().padding(.leading, 14)
    }

    private func kpiTile(value: String, label: String, icon: String) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 5) {
                Image(systemName: icon)
                    .font(.caption2)
                    .foregroundStyle(Color.accentColor)
                Text(label)
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
            Text(value)
                .font(.title3.weight(.semibold))
                .monospacedDigit()
                .lineLimit(1)
                .minimumScaleFactor(0.65)
        }
        .padding(12)
        .frame(minWidth: 110, alignment: .leading)
        .background(Color(.secondarySystemGroupedBackground),
                    in: RoundedRectangle(cornerRadius: 10, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 10, style: .continuous)
                .strokeBorder(Color.primary.opacity(0.10), lineWidth: 1)
        )
    }

    // MARK: – Computed properties

    private var canSimulate: Bool { !vm.processGraph.transitions.isEmpty }

    // MARK: – Duration formatter

    private func formatSecs(_ secs: Double) -> String {
        if secs < 60    { return String(format: "%.0fs",  secs) }
        if secs < 3600  { return String(format: "%.0fm",  secs / 60) }
        if secs < 86400 { return String(format: "%.1fh",  secs / 3600) }
        return              String(format: "%.1fd",  secs / 86400)
    }

    // MARK: – Simulation runner

    private func runSimulation() {
        guard canSimulate, !isRunning else { return }
        isRunning = true
        result    = nil

        let graph  = vm.processGraph
        let infos  = vm.allStepInfos
        let config = SimulationConfig(
            journeyCount:         journeyCount,
            startDate:            startDate,
            avgInterArrivalHours: avgInterArrivalHours,
            excludedSteps:        excludedSteps,
            requiredSteps:        requiredSteps,
            maxStepsPerJourney:   maxStepsPerJourney
        )

        let target = simTarget
        Task {
            let r = await Task.detached(priority: .userInitiated) {
                SimulationEngine.simulate(graph: graph, stepInfos: infos, config: config)
            }.value

            await MainActor.run {
                result    = r
                isRunning = false
                vm.storeSimulation(r, to: target)
            }
        }
    }

    // MARK: – CSV generation

    private func makeCSV(_ r: SimulationResult) -> String {
        let iso = ISO8601DateFormatter()
        var lines = ["JOURNEY_ID,STEP,EVENT_TIME"]
        for e in r.events {
            // Escape step names that contain commas
            let escapedStep = e.step.contains(",") ? "\"\(e.step)\"" : e.step
            lines.append("\(e.journeyId),\(escapedStep),\(iso.string(from: e.timestamp))")
        }
        return lines.joined(separator: "\n")
    }
}
