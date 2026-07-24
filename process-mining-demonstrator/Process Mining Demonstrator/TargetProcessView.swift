import SwiftUI

// MARK: - Target Process View
// Shows the process flowchart with norm values on each edge.
// showMetricSelector = false when embedded inside ComplianceCheckView.
// showEditControls   = false when the compliance view is in Execution mode.
// syncState / skipInitialFit are used by ComplianceCheckView to keep both panels locked.
// chartModeKey overrides the default UserDefaults key for node layouts so both compliance
// panels share the same persisted positions.

struct TargetProcessView: View {
    @ObservedObject var vm: AppViewModel
    var showMetricSelector: Bool    = true
    var showEditControls:   Bool    = true
    var syncState:          ABSyncState? = nil
    var skipInitialFit:     Bool    = false
    var chartModeKey:       String? = nil   // when set, both panels persist to the same key

    @State private var editingEdge:  ProcessTransition? = nil
    @State private var normInputText = ""
    @State private var normEditorPos = CGPoint.zero

    private var metric: TransitionMetric { vm.targetMetric }
    private var resolvedChartMode: String {
        chartModeKey ?? "target_\(vm.selectedProject?.projectId ?? "")"
    }

    var body: some View {
        VStack(spacing: 0) {
            if showMetricSelector {
                metricSelectorRow
                Divider()
            }
            chartLayer
        }
    }

    // MARK: Metric selector chips

    private var metricSelectorRow: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 6) {
                ForEach(TransitionMetric.allCases) { m in
                    let selected = metric == m
                    Button { vm.setTargetMetric(m) } label: {
                        HStack(spacing: 4) {
                            Image(systemName: m.icon).font(.caption2)
                            // Count norms are percentages — indicate that in the chip
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
            .padding(.vertical, 8)
        }
        .background(Color(.secondarySystemGroupedBackground))
    }

    // MARK: Chart

    @ViewBuilder
    private var chartLayer: some View {
        if vm.processGraph.transitions.isEmpty {
            if vm.isLoading {
                ProgressView("Loading process map\u{2026}")
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                ContentUnavailableView(
                    "No Process Data",
                    systemImage: "chart.xyaxis.line",
                    description: Text("Apply filters to load the process map.")
                )
            }
        } else {
            GeometryReader { geo in
                ZStack {
                    FlowChartView(
                        graph: vm.processGraph,
                        projectId: vm.selectedProject?.projectId ?? "",
                        chartMode: resolvedChartMode,
                        metric: metric,
                        isLoading: vm.isLoading,
                        syncState: syncState,
                        skipInitialFit: skipInitialFit,
                        normValues: vm.currentMetricNorms,
                        normMetric: metric,
                        showCompliance: false,
                        onEdgeTap: showEditControls ? { edge, pos in
                            handleEdgeTap(edge, pos, in: geo.size)
                        } : nil
                    )
                    .id(vm.selectedProject?.projectId)

                    if editingEdge != nil {
                        Color.clear
                            .contentShape(Rectangle())
                            .onTapGesture { editingEdge = nil }
                    }
                    if let edge = editingEdge {
                        normEditorPanel(for: edge)
                            .position(normEditorPos)
                    }
                }
            }
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

    // MARK: Edge tap handler

    private func handleEdgeTap(_ edge: ProcessTransition, _ screenPos: CGPoint, in viewSize: CGSize) {
        editingEdge   = edge
        let existing  = vm.currentMetricNorms[edge.id]
        normInputText = existing.map { formatNormDisplay($0) } ?? ""

        let panelW:    CGFloat = 252
        // Count metric has extra budget row; Clear Norm row adds ~33pt
        var panelEstH: CGFloat = metric == .count ? 148 : 105
        if vm.currentMetricNorms[edge.id] != nil { panelEstH += 33 }
        let margin:    CGFloat = 12
        let rawY = screenPos.y + 64
        let x = max(panelW / 2 + margin, min(viewSize.width  - panelW / 2 - margin, screenPos.x))
        let y = max(panelEstH / 2 + margin, min(viewSize.height - panelEstH / 2 - margin, rawY))
        normEditorPos = CGPoint(x: x, y: y)
    }

    private func formatNormDisplay(_ val: Double) -> String {
        // Both time-based and count (%) are shown as integers in the text field
        String(Int(val.rounded()))
    }

    // MARK: Norm editor floating panel

    private func normEditorPanel(for edge: ProcessTransition) -> some View {
        let isCount  = metric == .count
        let unit     = isCount ? " (% of journeys)" : metric.isTimeBased ? " (secs)" : ""
        let hint     = isCount ? "0 – 100" : "Enter norm value"

        // Budget: sum of norms for OTHER outgoing edges from the same source node
        // Edge IDs have format "fromStep->toStep" so prefix-match on "fromStep->"
        let nodePrefix = "\(edge.fromStep)->"
        let otherSum = vm.currentMetricNorms
            .filter { $0.key != edge.id && $0.key.hasPrefix(nodePrefix) }
            .values.reduce(0.0, +)
        let inputVal   = Double(normInputText) ?? 0.0
        let projected  = otherSum + inputVal
        let overBudget = projected > 100.0

        let saveable: Bool = {
            guard let val = Double(normInputText) else { return false }
            if isCount { return val >= 0 && val <= 100 && !overBudget }
            return true
        }()

        return VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 8) {
                VStack(alignment: .leading, spacing: 2) {
                    Text("\(edge.fromStep) \u{2192} \(edge.toStep)")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                    Text("Norm \u{00B7} \(metric.rawValue)\(unit)")
                        .font(.caption2)
                        .foregroundStyle(.tertiary)
                }
                Spacer(minLength: 0)
                Button { editingEdge = nil } label: {
                    Image(systemName: "xmark.circle.fill")
                        .font(.body)
                        .foregroundStyle(.secondary)
                        .frame(width: 36, height: 36)
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
            }
            .padding(.horizontal, 12)
            .padding(.top, 10)
            .padding(.bottom, 6)

            Divider()

            HStack(spacing: 8) {
                TextField(hint, text: $normInputText)
                    .textFieldStyle(.roundedBorder)
                    .keyboardType(.numbersAndPunctuation)
                Button("Save") {
                    if let val = Double(normInputText) {
                        vm.saveNorm(val, forEdge: edge.id)
                    }
                    editingEdge = nil
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.small)
                .disabled(!saveable)
            }
            .padding(.horizontal, 12)
            .padding(.top, 10)
            .padding(.bottom, isCount ? 6 : 10)

            // Budget row — only for Count (%) metric
            if isCount {
                HStack(spacing: 4) {
                    Image(systemName: overBudget ? "exclamationmark.triangle.fill" : "percent")
                        .font(.caption2)
                        .foregroundStyle(overBudget ? Color.red : Color.secondary.opacity(0.6))
                    Text(overBudget
                        ? String(format: "Outgoing from '\(edge.fromStep)': sum %.0f%% > 100%%", projected)
                        : String(format: "Outgoing from '\(edge.fromStep)': %.0f%% used · %.0f%% free", projected, 100 - projected))
                        .font(.caption2)
                        .foregroundStyle(overBudget ? Color.red : Color.secondary.opacity(0.6))
                }
                .padding(.horizontal, 12)
                .padding(.bottom, 8)
            }

            if vm.currentMetricNorms[edge.id] != nil {
                Divider()
                Button {
                    vm.saveNorm(nil, forEdge: edge.id)
                    editingEdge = nil
                } label: {
                    Label("Clear Norm", systemImage: "trash")
                        .font(.callout)
                        .foregroundStyle(.red)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(.horizontal, 12)
                        .padding(.vertical, 9)
                }
                .buttonStyle(.plain)
            }
        }
        .frame(width: 252)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 12))
        .overlay(RoundedRectangle(cornerRadius: 12)
            .strokeBorder(Color.primary.opacity(0.10), lineWidth: 0.5))
        .shadow(color: .black.opacity(0.22), radius: 14, x: 0, y: 6)
    }
}
