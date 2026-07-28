import SwiftUI
import Charts

private enum SortCol { case path, journeys, steps, score, total }

private struct NamedCount: Identifiable {
    var id: String { name }
    let name: String
    let count: Int
}

private struct TransitionCell: Identifiable {
    var id: String { "\(from)→\(to)" }
    let from: String
    let to: String
    let count: Int
}


// MARK: - Custom heatmap grid (replaces Swift Charts RectangleMark to avoid y-axis overlap)

private struct HeatmapGrid: View {
    let cells: [TransitionCell]

    @State private var hoveredKey: String? = nil

    private var steps: [String] { Array(Set(cells.map(\.from))).sorted() }
    private var maxCount: Int { cells.map(\.count).max() ?? 1 }
    private var lookup: [String: Int] {
        cells.reduce(into: [:]) { $0["\($1.from)→\($1.to)"] = $1.count }
    }

    private let cellSize:    CGFloat = 22
    private let yLabelWidth: CGFloat = 150

    private func cellColor(_ count: Int) -> Color {
        guard count > 0 else { return Color.primary.opacity(0.06) }
        let t = Double(count) / Double(maxCount)
        return Color(hue: t * 0.333, saturation: 0.72, brightness: 0.82)
    }

    private var tooltipText: String {
        guard let key = hoveredKey, let arrowRange = key.range(of: "→") else { return " " }
        let from  = String(key[key.startIndex..<arrowRange.lowerBound])
        let to    = String(key[arrowRange.upperBound...])
        let count = lookup[key] ?? 0
        return count > 0 ? "\(from) → \(to): \(count.formatted()) transitions" : "\(from) → \(to): no transitions"
    }

    var body: some View {
        let st    = steps
        let gridH = CGFloat(st.count) * cellSize
        VStack(alignment: .leading, spacing: 6) {
            // Fixed-height tooltip bar — always present so layout doesn't shift
            Text(tooltipText)
                .font(.caption2)
                .foregroundStyle(.secondary)
                .lineLimit(1)
                .frame(maxWidth: .infinity, alignment: .leading)

            ScrollView(.horizontal, showsIndicators: false) {
                HStack(alignment: .top, spacing: 12) {
                    // Grid + x-axis labels
                    VStack(alignment: .leading, spacing: 0) {
                        HStack(alignment: .top, spacing: 0) {
                            // Y-axis label column (fixed width, right-aligned)
                            VStack(alignment: .trailing, spacing: 0) {
                                ForEach(st, id: \.self) { step in
                                    Text(step)
                                        .font(.caption2)
                                        .lineLimit(1)
                                        .frame(width: yLabelWidth, height: cellSize, alignment: .trailing)
                                }
                            }
                            .padding(.trailing, 6)

                            // Cell grid
                            VStack(spacing: 0) {
                                ForEach(st, id: \.self) { toStep in
                                    HStack(spacing: 0) {
                                        ForEach(st, id: \.self) { fromStep in
                                            let key       = "\(fromStep)→\(toStep)"
                                            let count     = lookup[key] ?? 0
                                            let isHovered = hoveredKey == key
                                            Rectangle()
                                                .fill(cellColor(count))
                                                .frame(width: cellSize, height: cellSize)
                                                .overlay(
                                                    Rectangle().stroke(
                                                        isHovered ? Color.white : Color(.systemBackground).opacity(0.5),
                                                        lineWidth: isHovered ? 1.5 : 0.5
                                                    )
                                                )
                                                .overlay {
                                                    if isHovered && count > 0 {
                                                        Text(count.formatted())
                                                            .font(.system(size: 8, weight: .bold))
                                                            .foregroundStyle(.white)
                                                    }
                                                }
                                                .onHover { hoveredKey = $0 ? key : nil }
                                                .simultaneousGesture(TapGesture().onEnded {
                                                    hoveredKey = hoveredKey == key ? nil : key
                                                })
                                        }
                                    }
                                }
                            }
                        }

                        // X-axis label row — spacer is shortened by one cellSize so the
                        // topTrailing rotation anchor lands on the LEFT edge of each column
                        // (= visual tick position), not the right edge which reads as col+1.
                        HStack(alignment: .top, spacing: 0) {
                            Color.clear.frame(width: yLabelWidth + 6 - cellSize, height: 1)
                            ForEach(st, id: \.self) { step in
                                Text(step)
                                    .font(.caption2)
                                    .fixedSize()
                                    .frame(width: cellSize, alignment: .trailing)
                                    .rotationEffect(.degrees(-45), anchor: .topTrailing)
                                    .frame(width: cellSize, height: 120, alignment: .topLeading)
                            }
                        }
                    }

                    // Color legend (green = high, red = low, empty = 0)
                    VStack(alignment: .center, spacing: 4) {
                        Text(maxCount.formatted())
                            .font(.system(size: 9))
                            .foregroundStyle(.secondary)
                            .monospacedDigit()
                        LinearGradient(
                            stops: (0...20).map { i in
                                let t = Double(20 - i) / 20.0
                                return Gradient.Stop(
                                    color: t > 0
                                        ? Color(hue: t * 0.333, saturation: 0.72, brightness: 0.82)
                                        : Color.primary.opacity(0.06),
                                    location: Double(i) / 20.0
                                )
                            },
                            startPoint: .top, endPoint: .bottom
                        )
                        .frame(width: 14, height: gridH)
                        .clipShape(RoundedRectangle(cornerRadius: 4))
                        Text("1")
                            .font(.system(size: 9))
                            .foregroundStyle(.secondary)
                            .monospacedDigit()
                    }
                }
                .padding(.bottom, 4)
            }
        }
    }
}

struct StatisticsView: View {
    @ObservedObject var vm: AppViewModel

    @State private var statsTab:    Int     = 0
    @State private var sortCol:    SortCol = .journeys
    @State private var sortAsc:    Bool    = false
    @State private var currentPage = 0
    @State private var pageSize    = 25
    @State private var searchText  = ""

    @AppStorage("kpi.show.totalJourneys")    private var kpiShowTotalJourneys    = true
    @AppStorage("kpi.show.filteredJourneys") private var kpiShowFilteredJourneys = true
    @AppStorage("kpi.show.shortestJourney")  private var kpiShowShortestJourney  = true
    @AppStorage("kpi.show.avgJourney")       private var kpiShowAvgJourney       = true
    @AppStorage("kpi.show.stdDev")           private var kpiShowStdDev           = true
    @AppStorage("kpi.show.longestJourney")   private var kpiShowLongestJourney   = true
    @AppStorage("kpi.show.graphValue")       private var kpiShowGraphValue       = true
    @AppStorage("kpi.show.processGoodness")  private var kpiShowProcessGoodness  = true
    @AppStorage("kpi.show.activeSample")     private var kpiShowActiveSample     = true
    @AppStorage("kpi.order")                 private var kpiOrderRaw             = kpiDefaultOrder
    @AppStorage("statistics.kpiExpanded")    private var kpiExpanded             = true

    private var orderedKPIIds: [String] {
        let stored = kpiOrderRaw.split(separator: ",").map(String.init)
        let all    = kpiDefaultOrder.split(separator: ",").map(String.init)
        return stored + all.filter { !stored.contains($0) }
    }

    // MARK: - Column widths

    private enum W {
        static let journeys: CGFloat = 76
        static let steps: CGFloat    = 54
        static let score: CGFloat    = 84
        static let total: CGFloat    = 84
    }

    // MARK: - Derived

    private var filtered: [JourneyPath] {
        searchText.isEmpty ? vm.statisticsPaths
            : vm.statisticsPaths.filter {
                $0.path.localizedCaseInsensitiveContains(searchText)
            }
    }

    private var sorted: [JourneyPath] {
        filtered.sorted { a, b in
            switch sortCol {
            case .path:     return sortAsc ? a.path < b.path                       : a.path > b.path
            case .journeys: return sortAsc ? a.journeyCount < b.journeyCount       : a.journeyCount > b.journeyCount
            case .steps:    return sortAsc ? a.stepCount < b.stepCount             : a.stepCount > b.stepCount
            case .score:    return sortAsc ? a.totalScore < b.totalScore           : a.totalScore > b.totalScore
            case .total:    return sortAsc ? a.aggregatedScore < b.aggregatedScore : a.aggregatedScore > b.aggregatedScore
            }
        }
    }

    private var totalPages: Int { max(1, (sorted.count + pageSize - 1) / pageSize) }

    private var statsAreStale: Bool {
        guard let loaded = vm.statsLoadedSnapshot, !vm.statisticsPaths.isEmpty else { return false }
        return vm.currentFilterSnapshot() != loaded
    }

    private var pageItems: [JourneyPath] {
        let start = currentPage * pageSize
        guard start < sorted.count else { return [] }
        return Array(sorted[start ..< min(start + pageSize, sorted.count)])
    }

    // MARK: - Body

    var body: some View {
        VStack(spacing: 0) {
            if vm.isLoadingStats {
                VStack(spacing: 20) {
                    ProgressView("Computing journey routes")
                    Button("Cancel") { vm.cancelJourneyPaths() }
                        .buttonStyle(.bordered)
                        .controlSize(.small)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)

            } else if vm.selectedProject == nil {
                ContentUnavailableView(
                    "No Project Selected",
                    systemImage: "flowchart",
                    description: Text("Select a project from the sidebar.")
                )

            } else if vm.statisticsPaths.isEmpty {
                VStack(spacing: 16) {
                    if let err = vm.statsErrorMessage {
                        Image(systemName: "exclamationmark.triangle")
                            .font(.system(size: 48))
                            .foregroundStyle(.orange)
                        Text("Query Failed")
                            .font(.title2.weight(.semibold))
                        Text(err)
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                            .multilineTextAlignment(.center)
                            .frame(maxWidth: 420)
                    } else {
                        Image(systemName: "arrow.triangle.branch")
                            .font(.system(size: 48))
                            .foregroundStyle(.secondary)
                        Text("No Routes Yet")
                            .font(.title2.weight(.semibold))
                        Text("Compute all journey routes for the current filters.")
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                            .multilineTextAlignment(.center)
                    }
                    Button {
                        Task { await vm.loadJourneyPaths() }
                    } label: {
                        Label(vm.statsErrorMessage != nil ? "Retry" : "Compute Routes",
                              systemImage: "arrow.clockwise")
                    }
                    .buttonStyle(.borderedProminent)
                    .padding(.top, 4)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)

            } else {
                // ── KPI collapse handle ──────────────────────────────────
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
                if kpiExpanded {
                    metricsTiles
                        .transition(.move(edge: .top).combined(with: .opacity))
                }
                HStack(spacing: 6) {
                    Image(systemName: "info.circle")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                    Text("Statistics use the same filters as Chart A.")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                    Spacer(minLength: 0)
                }
                .padding(.horizontal, 16)
                .padding(.vertical, 5)
                .background(Color(.secondarySystemGroupedBackground))
                if statsAreStale {
                    HStack(spacing: 10) {
                        Image(systemName: "exclamationmark.triangle.fill")
                            .foregroundStyle(.orange)
                            .font(.caption)
                        Text("Filters changed since last load")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        Spacer(minLength: 0)
                        Button {
                            Task { await vm.loadJourneyPaths() }
                        } label: {
                            Label("Reload", systemImage: "arrow.clockwise")
                                .font(.caption.weight(.semibold))
                        }
                        .buttonStyle(.bordered)
                        .controlSize(.mini)
                    }
                    .padding(.horizontal, 16)
                    .padding(.vertical, 7)
                    .background(Color.orange.opacity(0.10))
                }
                Picker("View", selection: $statsTab) {
                    Text("Routes").tag(0)
                    Text("Analytics").tag(1)
                }
                .pickerStyle(.segmented)
                .padding(.horizontal, 16)
                .padding(.vertical, 8)
                .background(Color(.secondarySystemGroupedBackground))
                Divider()
                if statsTab == 0 {
                    VStack(spacing: 0) {
                        controlBar
                        Divider()
                        ScrollView {
                            LazyVStack(spacing: 0, pinnedViews: .sectionHeaders) {
                                if !vm.statsTimeSeries.isEmpty {
                                    timeSeriesSection
                                    Divider()
                                }
                                routeTableSection
                            }
                        }
                        .onChange(of: sortCol)    { _, _ in currentPage = 0 }
                        .onChange(of: searchText) { _, _ in currentPage = 0 }
                        Divider()
                        paginationBar
                    }
                } else {
                    chartsPage
                }
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color(.systemGroupedBackground))
        .task(id: vm.selectedProject?.projectId) {
            guard vm.selectedProject != nil, vm.statisticsPaths.isEmpty else { return }
            await vm.loadJourneyPaths()
        }
    }

    // MARK: - Control bar

    private var controlBar: some View {
        HStack(spacing: 12) {
            HStack(spacing: 6) {
                Image(systemName: "magnifyingglass").foregroundStyle(.secondary)
                TextField("Filter paths", text: $searchText)
                    .textFieldStyle(.plain)
                if !searchText.isEmpty {
                    Button { searchText = "" } label: {
                        Image(systemName: "xmark.circle.fill").foregroundStyle(.secondary)
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding(.horizontal, 10)
            .padding(.vertical, 7)
            .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 9))
            .frame(maxWidth: 300)

            Spacer()

            if vm.statisticsIsTruncated {
                Label("Result capped at \(vm.statsRouteLimit.formatted()) routes. Raise the limit or narrow filters.",
                      systemImage: "exclamationmark.triangle")
                    .font(.caption2)
                    .foregroundStyle(.orange)
                    .lineLimit(2)
                    .frame(maxWidth: 280)
            } else {
                Text("\(vm.statisticsPaths.count.formatted()) unique routes")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            HStack(spacing: 6) {
                Text("Limit")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Picker("Route limit", selection: $vm.statsRouteLimit) {
                    Text("100").tag(100)
                    Text("250").tag(250)
                    Text("500").tag(500)
                    Text("1 000").tag(1_000)
                    Text("2 500").tag(2_500)
                }
                .pickerStyle(.menu)
                .labelsHidden()
            }

            Picker("Rows per page", selection: $pageSize) {
                Text("25").tag(25)
                Text("50").tag(50)
                Text("100").tag(100)
            }
            .pickerStyle(.segmented)
            .frame(width: 130)
            .onChange(of: pageSize) { _, _ in currentPage = 0 }

            Button {
                Task { await vm.loadJourneyPaths() }
            } label: {
                Label("Reload", systemImage: "arrow.clockwise")
                    .labelStyle(.iconOnly)
            }
            .buttonStyle(.bordered)
            .controlSize(.small)
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 10)
        .background(Color(.secondarySystemGroupedBackground))
    }

    // MARK: - Metrics tiles

    private var metricsTiles: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 12) {
                ForEach(orderedKPIIds, id: \.self) { id in
                    statsKPITile(id: id)
                }
                // Statistics-specific (always visible)
                kpiTile(value: vm.statisticsPaths.count.formatted(),
                        label: "Distinct Routes", icon: "arrow.triangle.branch", loading: false)
                kpiTile(
                    value: "\(vm.fromDate.formatted(date: .abbreviated, time: .omitted)) → \(vm.toDate.formatted(date: .abbreviated, time: .omitted))",
                    label: "Date Range", icon: "calendar", loading: false)
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 14)
        }
    }

    @ViewBuilder
    private func statsKPITile(id: String) -> some View {
        switch id {
        case "totalJourneys" where kpiShowTotalJourneys:
            kpiTile(value: vm.totalJourneyCount.map { $0.formatted() } ?? "—",
                    label: "Total Journeys", icon: "person.2.fill",
                    loading: vm.isLoadingStats && vm.totalJourneyCount == nil)
        case "filteredJourneys" where kpiShowFilteredJourneys:
            kpiTile(value: vm.journeyCount.map { $0.formatted() } ?? "—",
                    label: "Filtered Journeys", icon: "line.3.horizontal.decrease.circle.fill",
                    loading: vm.isLoadingStats)
        case "shortestJourney" where kpiShowShortestJourney:
            kpiTile(value: formatSecs(vm.minJourneyDuration),    label: "Shortest Journey", icon: "hare",              loading: vm.isLoadingStats)
        case "avgJourney" where kpiShowAvgJourney:
            kpiTile(value: formatSecs(vm.avgJourneyDuration),    label: "Avg Journey",      icon: "timer",             loading: vm.isLoadingStats)
        case "stdDev" where kpiShowStdDev:
            kpiTile(value: formatSecs(vm.stdDevJourneyDuration), label: "Std Dev",          icon: "waveform.path.ecg", loading: vm.isLoadingStats)
        case "longestJourney" where kpiShowLongestJourney:
            kpiTile(value: formatSecs(vm.maxJourneyDuration),    label: "Longest Journey",  icon: "tortoise",          loading: vm.isLoadingStats)
        case "graphValue" where kpiShowGraphValue:
            if let val = graphValue(for: vm.processGraph) {
                kpiTile(value: val.formatted(.number.sign(strategy: .always())),
                        label: "Graph Value", icon: "function", loading: false)
            }
        case "processGoodness" where kpiShowProcessGoodness:
            if let val = vm.processGoodnessScore {
                kpiTile(value: val.formatted(.number.precision(.fractionLength(2)).sign(strategy: .always())),
                        label: "Process Goodness", icon: "gauge.high", loading: false)
            }
        case "activeSample" where kpiShowActiveSample:
            let cnt = vm.sampleCounts[vm.activeSampleSetA] ?? vm.totalJourneyCount
            kpiTile(value: cnt?.formatted() ?? "—",
                    label: vm.activeSampleSetA.shortLabel, icon: "square.3.layers.3d", loading: false)
        default:
            EmptyView()
        }
    }

    private func kpiTile(value: String, label: String, icon: String, loading: Bool) -> some View {
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
            if loading {
                ProgressView().controlSize(.small)
                    .frame(height: 26)
            } else {
                Text(value)
                    .font(.title3.weight(.semibold))
                    .monospacedDigit()
                    .lineLimit(1)
                    .minimumScaleFactor(0.65)
            }
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

    // MARK: - Time series chart

    private var timeSeriesSection: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 6) {
                Text("Journeys Over Time")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
                Text("·")
                    .font(.caption)
                    .foregroundStyle(.tertiary)
                Text(vm.statsTimeGranularity.label)
                    .font(.caption)
                    .foregroundStyle(.tertiary)
            }
            .padding(.horizontal, 16)
            .padding(.top, 16)
            .padding(.bottom, 10)

            Chart(vm.statsTimeSeries) { point in
                AreaMark(
                    x: .value("Date",     point.date),
                    y: .value("Journeys", point.count)
                )
                .foregroundStyle(
                    LinearGradient(
                        colors: [Color.accentColor.opacity(0.22), Color.accentColor.opacity(0.03)],
                        startPoint: .top, endPoint: .bottom
                    )
                )
                .interpolationMethod(.catmullRom)

                LineMark(
                    x: .value("Date",     point.date),
                    y: .value("Journeys", point.count)
                )
                .foregroundStyle(Color.accentColor)
                .lineStyle(StrokeStyle(lineWidth: 2))
                .interpolationMethod(.catmullRom)
            }
            .chartXAxis {
                AxisMarks(values: .automatic(desiredCount: 6)) { _ in
                    AxisGridLine(stroke: StrokeStyle(lineWidth: 0.4))
                    AxisTick(stroke: StrokeStyle(lineWidth: 0.4))
                    AxisValueLabel(
                        format: vm.statsTimeGranularity == .month
                            ? .dateTime.month(.abbreviated).year(.twoDigits)
                            : .dateTime.month(.abbreviated).day()
                    )
                }
            }
            .chartYAxis {
                AxisMarks(position: .leading, values: .automatic(desiredCount: 4)) { _ in
                    AxisGridLine(stroke: StrokeStyle(lineWidth: 0.4))
                    AxisValueLabel()
                }
            }
            .chartYScale(domain: .automatic(includesZero: true))
            .frame(height: 200)
            .padding(.horizontal, 16)
            .padding(.bottom, 20)
        }
        .background(Color(.systemGroupedBackground))
    }

    // MARK: - Table section

    @ViewBuilder
    private var routeTableSection: some View {
        Section {
            ForEach(Array(pageItems.enumerated()), id: \.element.id) { idx, row in
                rowView(row, isEven: idx.isMultiple(of: 2))
                Divider().padding(.leading, 10)
            }
        } header: {
            headerRow
        }
    }

    private var headerRow: some View {
        HStack(spacing: 0) {
            sortButton("Journey Path", col: .path,     leading: true)
            colDivider
            sortButton("Journeys",     col: .journeys, width: W.journeys)
            colDivider
            sortButton("Steps",        col: .steps,    width: W.steps)
            colDivider
            sortButton("Score/J",      col: .score,    width: W.score)
            colDivider
            sortButton("Total",        col: .total,    width: W.total)
        }
        .frame(height: 30)
        .background(Color(.secondarySystemGroupedBackground))
        .overlay(alignment: .bottom) { Divider() }
    }

    private var colDivider: some View {
        Rectangle()
            .fill(Color(.separator))
            .frame(width: 0.5, height: 20)
    }

    private func sortButton(
        _ label: String,
        col: SortCol,
        width: CGFloat? = nil,
        leading: Bool = false
    ) -> some View {
        Button {
            if sortCol == col { sortAsc.toggle() }
            else { sortCol = col; sortAsc = (col == .path) }
            currentPage = 0
        } label: {
            HStack(spacing: 3) {
                if !leading { Spacer(minLength: 0) }
                Text(label).lineLimit(1)
                if sortCol == col {
                    Image(systemName: sortAsc ? "chevron.up" : "chevron.down")
                        .font(.caption2.weight(.bold))
                }
                if leading { Spacer(minLength: 0) }
            }
            .font(.caption.weight(.semibold))
            .foregroundStyle(.primary)
            .padding(.horizontal, 8)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .frame(width: width)
    }

    private func rowView(_ row: JourneyPath, isEven: Bool) -> some View {
        HStack(alignment: .top, spacing: 0) {
            Text(row.path)
                .font(.system(.caption2, design: .monospaced))
                .fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.horizontal, 10)
                .padding(.vertical, 5)
            numCell(row.journeyCount.formatted(),
                    width: W.journeys)
            numCell(row.stepCount.formatted(),
                    width: W.steps)
            numCell(row.totalScore.formatted(.number.sign(strategy: .always())),
                    width: W.score,
                    color: scoreColor(row.totalScore))
            numCell(row.aggregatedScore.formatted(.number.sign(strategy: .always())),
                    width: W.total,
                    color: scoreColor(row.aggregatedScore))
        }
        .background(isEven ? Color(.secondarySystemGroupedBackground).opacity(0.4) : .clear)
    }

    private func numCell(_ text: String, width: CGFloat, color: Color = .primary) -> some View {
        Text(text)
            .font(.caption)
            .monospacedDigit()
            .foregroundStyle(color)
            .frame(width: width, alignment: .trailing)
            .padding(.horizontal, 8)
            .padding(.vertical, 5)
    }

    // MARK: - Pagination bar

    private var paginationBar: some View {
        HStack(spacing: 0) {
            Button {
                withAnimation { currentPage = max(0, currentPage - 1) }
            } label: {
                Image(systemName: "chevron.left")
                    .font(.body.weight(.semibold))
                    .frame(width: 44, height: 44)
            }
            .disabled(currentPage == 0)

            Spacer()

            let start = currentPage * pageSize + 1
            let end   = min((currentPage + 1) * pageSize, sorted.count)
            VStack(spacing: 2) {
                Text("Page \(currentPage + 1) of \(totalPages)")
                    .font(.caption.weight(.semibold))
                Text("\(start)–\(end) of \(sorted.count.formatted()) routes")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }

            Spacer()

            Button {
                withAnimation { currentPage = min(totalPages - 1, currentPage + 1) }
            } label: {
                Image(systemName: "chevron.right")
                    .font(.body.weight(.semibold))
                    .frame(width: 44, height: 44)
            }
            .disabled(currentPage >= totalPages - 1)
        }
        .padding(.horizontal, 12)
        .frame(height: 48)
        .background(Color(.secondarySystemGroupedBackground))
    }

    // MARK: - Helpers

    private func scoreColor(_ score: Int) -> Color {
        score > 0 ? .green : score < 0 ? .red : .blue
    }

    // MARK: - In-memory chart data

    private var stepFrequencyData: [NamedCount] {
        guard !vm.statsProcessGraph.transitions.isEmpty else { return [] }
        var incoming: [String: Int] = [:]
        var outgoing: [String: Int] = [:]
        for t in vm.statsProcessGraph.transitions {
            outgoing[t.fromStep, default: 0] += t.occurrences
            incoming[t.toStep,   default: 0] += t.occurrences
        }
        let all = Set(incoming.keys).union(outgoing.keys)
        return Array(
            all.map { NamedCount(name: $0, count: max(incoming[$0] ?? 0, outgoing[$0] ?? 0)) }
               .sorted { $0.count > $1.count }
               .prefix(20)
        )
    }

    private var dropOffData: [NamedCount] {
        guard !vm.statisticsPaths.isEmpty else { return [] }
        var counts: [String: Int] = [:]
        for p in vm.statisticsPaths {
            let steps = p.path.components(separatedBy: " -> ")
            guard let last = steps.last else { continue }
            counts[last, default: 0] += p.journeyCount
        }
        return Array(
            counts.map { NamedCount(name: $0.key, count: $0.value) }
                  .sorted { $0.count > $1.count }
                  .prefix(15)
        )
    }

    private var transitionMatrix: [TransitionCell] {
        let top = vm.statsProcessGraph.transitions
            .sorted { $0.occurrences > $1.occurrences }
            .prefix(25)
        guard !top.isEmpty else { return [] }
        let steps = Array(Set(top.flatMap { [$0.fromStep, $0.toStep] })).sorted()
        var lookup: [String: Int] = [:]
        for t in top { lookup["\(t.fromStep)→\(t.toStep)"] = t.occurrences }
        var cells: [TransitionCell] = []
        for from in steps {
            for to in steps {
                cells.append(TransitionCell(from: from, to: to, count: lookup["\(from)→\(to)"] ?? 0))
            }
        }
        return cells
    }

    // Buckets arrive pre-sorted from the DB (ORDER BY bin_idx).
    private var sortedDurationBuckets: [DurationBucket] { vm.statsDurationBuckets }

    // MARK: - Charts page (page 2)

    private var chartsPage: some View {
        ScrollView {
            VStack(spacing: 16) {
                HStack(alignment: .top, spacing: 16) {
                    chartCard(title: "Step Frequency",
                              subtitle: "Visits per step — top 20 by traffic") {
                        let data = stepFrequencyData
                        if data.isEmpty {
                            emptyChartPlaceholder
                        } else {
                            Chart(data) { item in
                                BarMark(
                                    x: .value("Visits", item.count),
                                    y: .value("Step",   item.name)
                                )
                                .foregroundStyle(Color.accentColor.gradient)
                                .annotation(position: .trailing, alignment: .leading) {
                                    Text(item.count.formatted())
                                        .font(.caption2)
                                        .foregroundStyle(.secondary)
                                        .monospacedDigit()
                                        .padding(.leading, 4)
                                }
                            }
                            .chartXAxis {
                                AxisMarks(position: .bottom, values: .automatic(desiredCount: 4)) { _ in
                                    AxisGridLine(stroke: StrokeStyle(lineWidth: 0.4))
                                    AxisValueLabel()
                                }
                            }
                            .chartYAxis { AxisMarks { _ in AxisValueLabel() } }
                            .frame(height: CGFloat(max(120, min(480, data.count * 26))))
                        }
                    }

                    chartCard(title: "Journey Exit Points",
                              subtitle: "Last step reached — top 15") {
                        let data = dropOffData
                        if data.isEmpty {
                            emptyChartPlaceholder
                        } else {
                            Chart(data) { item in
                                BarMark(
                                    x: .value("Journeys", item.count),
                                    y: .value("Step",     item.name)
                                )
                                .foregroundStyle(Color.orange.gradient)
                                .annotation(position: .trailing, alignment: .leading) {
                                    Text(item.count.formatted())
                                        .font(.caption2)
                                        .foregroundStyle(.secondary)
                                        .monospacedDigit()
                                        .padding(.leading, 4)
                                }
                            }
                            .chartXAxis {
                                AxisMarks(position: .bottom, values: .automatic(desiredCount: 4)) { _ in
                                    AxisGridLine(stroke: StrokeStyle(lineWidth: 0.4))
                                    AxisValueLabel()
                                }
                            }
                            .chartYAxis { AxisMarks { _ in AxisValueLabel() } }
                            .frame(maxHeight: .infinity)
                        }
                    }
                    .frame(maxHeight: .infinity)
                }

                HStack(alignment: .top, spacing: 16) {
                    chartCard(title: "Transition Heatmap",
                              subtitle: "Step→step frequency matrix (top 25 transitions)") {
                        let data = transitionMatrix
                        if data.isEmpty {
                            emptyChartPlaceholder
                        } else {
                            HeatmapGrid(cells: data)
                        }
                    }

                    chartCard(title: "Journey Duration Distribution",
                              subtitle: "How long journeys take") {
                        let data = sortedDurationBuckets
                        if data.isEmpty {
                            emptyChartPlaceholder
                        } else {
                            Chart(data) { bucket in
                                BarMark(
                                    x: .value("Duration", bucket.label),
                                    y: .value("Journeys", bucket.count)
                                )
                                .foregroundStyle(Color.green.gradient)
                                .annotation(position: .top, alignment: .center) {
                                    Text(bucket.count.formatted())
                                        .font(.caption2)
                                        .foregroundStyle(.secondary)
                                        .monospacedDigit()
                                }
                            }
                            .chartXAxis { AxisMarks { _ in AxisValueLabel().font(.caption2) } }
                            .frame(maxHeight: .infinity)
                        }
                    }
                    .frame(maxHeight: .infinity)
                }
            }
            .padding(16)
            .padding(.bottom, 28)
        }
        .background(Color(.systemGroupedBackground))
    }

    private func chartCard<Content: View>(
        title: String, subtitle: String,
        @ViewBuilder content: () -> Content
    ) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .font(.caption.weight(.semibold))
                Text(subtitle)
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }
            content()
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color(.secondarySystemGroupedBackground),
                    in: RoundedRectangle(cornerRadius: 10, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 10, style: .continuous)
                .strokeBorder(Color.primary.opacity(0.10), lineWidth: 1)
        )
    }

    private var emptyChartPlaceholder: some View {
        Text("No data available")
            .font(.caption)
            .foregroundStyle(.secondary)
            .frame(maxWidth: .infinity, minHeight: 60)
    }
}
