import SwiftUI

struct SamplingView: View {
    @ObservedObject var vm: AppViewModel
    @AppStorage("sampling.defaultMethod") private var defaultMethodRaw: String = "random"

    @State private var showCreateSheet  = false
    @State private var createTarget: SampleSet = .sample1
    @State private var sampleToDelete: SampleSet? = nil

    private var defaultMethod: SamplingMethod {
        SamplingMethod(rawValue: defaultMethodRaw) ?? .random
    }

    private let sampleSlots: [SampleSet] = [.sample1, .sample2, .sample3]

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            // Active data set — per-chart pickers
            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 6) {
                    Image(systemName: "square.3.layers.3d")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Text("Active data")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }

                HStack(spacing: 8) {
                    chartSourcePicker(
                        label: "A", labelColor: Color.accentColor,
                        current: vm.abDataSourceA
                    ) { newSource in Task { await vm.setABDataSource(newSource, for: .a) } }

                    Text("·")
                        .font(.caption2)
                        .foregroundStyle(.tertiary)

                    chartSourcePicker(
                        label: "B", labelColor: Color.indigo,
                        current: vm.abDataSourceB
                    ) { newSource in Task { await vm.setABDataSource(newSource, for: .b) } }

                    Spacer(minLength: 0)
                }
            }
            .padding(.horizontal, 20)
            .padding(.vertical, 8)

            if vm.isSampling {
                HStack(spacing: 8) {
                    ProgressView().controlSize(.mini)
                    Text(vm.samplingProgress ?? "Working…")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
                .padding(.horizontal, 20)
                .padding(.vertical, 6)
            }

            if let err = vm.samplingError {
                Text(err)
                    .font(.caption2)
                    .foregroundStyle(.red)
                    .lineLimit(2)
                    .padding(.horizontal, 20)
                    .padding(.bottom, 6)
            }

            Divider()

            // Sample slots
            ForEach(sampleSlots, id: \.id) { slot in
                sampleRow(slot)
                Divider()
            }
        }
        .sheet(isPresented: $showCreateSheet) {
            CreateSampleSheet(vm: vm, target: createTarget, defaultMethod: defaultMethod)
        }
        .confirmationDialog(
            "Delete \(sampleToDelete?.label ?? "")?",
            isPresented: Binding(
                get: { sampleToDelete != nil },
                set: { if !$0 { sampleToDelete = nil } }
            ),
            titleVisibility: .visible
        ) {
            Button("Delete", role: .destructive) {
                if let s = sampleToDelete {
                    Task { await vm.deleteSample(type: s) }
                }
                sampleToDelete = nil
            }
        } message: {
            if let s = sampleToDelete, let cnt = vm.sampleCounts[s] {
                Text("This removes \(cnt.formatted()) sample journey rows from the database. Original data is not affected.")
            } else {
                Text("This removes all sample journey rows from the database. Original data is not affected.")
            }
        }
    }

    @ViewBuilder
    private func chartSourcePicker(
        label: String,
        labelColor: Color,
        current: ABDataSource,
        onChange: @escaping (ABDataSource) -> Void
    ) -> some View {
        HStack(spacing: 4) {
            Text(label)
                .font(.caption2.weight(.bold))
                .foregroundStyle(labelColor)
            Menu {
                // ── Sample sets ────────────────────────────────────────
                ForEach(SampleSet.allCases) { set in
                    let source  = ABDataSource.sampleSet(set)
                    let count   = set.isOriginal ? vm.totalJourneyCount : vm.sampleCounts[set]
                    let ml      = vm.sampleMethods[set]?.label
                    Button { onChange(source) } label: {
                        if source == current {
                            if let c = count, let ml { Label("\(set.shortLabel) (\(c.formatted()) · \(ml))", systemImage: "checkmark") }
                            else if let c = count    { Label("\(set.shortLabel) (\(c.formatted()))", systemImage: "checkmark") }
                            else                     { Label(set.shortLabel, systemImage: "checkmark") }
                        } else if let c = count, let ml, !set.isOriginal { Text("\(set.shortLabel) (\(c.formatted()) · \(ml))") }
                        else if let c = count        { Text("\(set.shortLabel) (\(c.formatted()))") }
                        else if !set.isOriginal      { Text("\(set.shortLabel) — not created") }
                        else                         { Text(set.shortLabel) }
                    }
                    .disabled(!set.isOriginal && vm.sampleCounts[set] == nil)
                }
                Divider()
                // ── Simulation slots ────────────────────────────────────
                ForEach(SimSlot.allCases) { slot in
                    let source  = ABDataSource.simulation(slot)
                    let stored  = slot == .simA ? vm.simResultA : vm.simResultB
                    Button { onChange(source) } label: {
                        if source == current {
                            if let r = stored { Label("\(slot.rawValue) (\(r.totalJourneys.formatted()) sim)", systemImage: "checkmark") }
                            else              { Label("\(slot.rawValue) — not loaded", systemImage: "checkmark") }
                        } else if let r = stored { Text("\(slot.rawValue) (\(r.totalJourneys.formatted()) sim journeys)") }
                        else                     { Text("\(slot.rawValue) — not loaded") }
                    }
                    .disabled(stored == nil)
                }
            } label: {
                HStack(spacing: 3) {
                    // Show method label for sample sets, plain label for sim slots
                    if case .sampleSet(let set) = current, !set.isOriginal,
                       let ml = vm.sampleMethods[set]?.label {
                        Text("\(set.shortLabel) · \(ml)").font(.caption)
                    } else {
                        Text(current.shortLabel).font(.caption)
                    }
                    Image(systemName: "chevron.up.chevron.down").font(.caption2)
                }
                .foregroundStyle(.secondary)
                .padding(.horizontal, 6)
                .padding(.vertical, 3)
                .background(
                    RoundedRectangle(cornerRadius: 5)
                        .fill(Color(.secondarySystemGroupedBackground))
                        .overlay(
                            RoundedRectangle(cornerRadius: 5)
                                .stroke(Color(.separator).opacity(0.5), lineWidth: 0.5)
                        )
                )
            }
            .buttonStyle(.plain)
            .disabled(vm.selectedProject == nil)
        }
    }

    @ViewBuilder
    private func sampleRow(_ slot: SampleSet) -> some View {
        let count     = vm.sampleCounts[slot]
        let isActive  = vm.abDataSourceA == .sampleSet(slot) || vm.abDataSourceB == .sampleSet(slot)
        let isCreated = count != nil
        let method    = vm.sampleMethods[slot]

        HStack(spacing: 10) {
            Image(systemName: isCreated ? "checkmark.circle.fill" : "circle.dashed")
                .font(.caption)
                .foregroundStyle(isCreated ? Color.accentColor : Color.secondary)

            VStack(alignment: .leading, spacing: 1) {
                Text(slot.shortLabel)
                    .font(.caption.weight(isActive ? .semibold : .regular))
                    .foregroundStyle(isActive ? Color.accentColor : Color.primary)
                if let count {
                    HStack(spacing: 4) {
                        Text("\(count.formatted()) journeys")
                        if let m = method {
                            Text("·")
                            Image(systemName: m.icon)
                            Text(m.label)
                        }
                    }
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                } else {
                    Text("Not created")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }
            }

            Spacer(minLength: 0)

            if isCreated {
                Button {
                    sampleToDelete = slot
                } label: {
                    Image(systemName: "trash")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                .buttonStyle(.borderless)
                .help("Delete \(slot.shortLabel)")
            } else {
                Button {
                    createTarget   = slot
                    showCreateSheet = true
                } label: {
                    Image(systemName: "plus.circle")
                        .font(.caption)
                        .foregroundStyle(Color.accentColor)
                }
                .buttonStyle(.borderless)
                .disabled(vm.selectedProject == nil || vm.isSampling)
                .help("Create \(slot.shortLabel)")
            }
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 7)
    }
}

// MARK: - Create Sample Sheet

struct CreateSampleSheet: View {
    @ObservedObject var vm: AppViewModel
    let target: SampleSet
    let defaultMethod: SamplingMethod

    @AppStorage("sampling.defaultMethod") private var defaultMethodRaw: String = "random"

    @State private var countText: String = "1000"
    @State private var method: SamplingMethod
    @State private var isCreating = false

    @Environment(\.dismiss) private var dismiss

    init(vm: AppViewModel, target: SampleSet, defaultMethod: SamplingMethod) {
        self.vm = vm
        self.target = target
        self.defaultMethod = defaultMethod
        _method = State(initialValue: defaultMethod)
    }

    private var parsedCount: Int? {
        guard let n = Int(countText.trimmingCharacters(in: .whitespaces)), n > 0 else { return nil }
        return n
    }

    private var originalCount: Int {
        vm.sampleCounts[.original] ?? vm.totalJourneyCount ?? 0
    }

    var body: some View {
        VStack(spacing: 0) {
            // Header
            HStack {
                Image(systemName: "square.3.layers.3d")
                    .font(.title2)
                    .foregroundStyle(Color.accentColor)
                VStack(alignment: .leading, spacing: 2) {
                    Text("Create \(target.label)")
                        .font(.headline)
                    if originalCount > 0 {
                        Text("\(originalCount.formatted()) journeys available")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
                Spacer()
                Button {
                    dismiss()
                } label: {
                    Image(systemName: "xmark.circle.fill")
                        .font(.title3)
                        .foregroundStyle(.secondary)
                }
                .buttonStyle(.borderless)
                .disabled(isCreating)
            }
            .padding()

            Divider()

            Form {
                Section {
                    HStack {
                        Text("Journeys")
                        Spacer()
                        TextField("Count", text: $countText)
                            .multilineTextAlignment(.trailing)
                            .frame(width: 90)
                    }
                }

                Section("Sampling Method") {
                    ForEach(SamplingMethod.allCases) { m in
                        HStack(alignment: .top, spacing: 12) {
                            Image(systemName: m.icon)
                                .foregroundStyle(method == m ? Color.accentColor : Color.secondary)
                                .frame(width: 20)
                            VStack(alignment: .leading, spacing: 2) {
                                Text(m.label)
                                    .font(.body)
                                Text(m.shortDescription)
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                            Spacer()
                            if method == m {
                                Image(systemName: "checkmark")
                                    .foregroundStyle(Color.accentColor)
                            }
                        }
                        .contentShape(Rectangle())
                        .onTapGesture { method = m }
                        .padding(.vertical, 2)
                    }
                }
            }
            .formStyle(.grouped)
            .disabled(isCreating)

            // Progress / error feedback
            if isCreating || vm.samplingError != nil {
                Divider()
                VStack(alignment: .leading, spacing: 6) {
                    if isCreating {
                        ProgressView(vm.samplingProgress ?? "Working…")
                            .progressViewStyle(.linear)
                            .font(.caption2)
                    }
                    if let error = vm.samplingError {
                        Label(error, systemImage: "exclamationmark.triangle.fill")
                            .font(.caption2)
                            .foregroundStyle(.red)
                            .lineLimit(3)
                    }
                }
                .padding(.horizontal)
                .padding(.vertical, 10)
            }

            Divider()

            HStack {
                Button("Cancel") { dismiss() }
                    .keyboardShortcut(.escape)
                    .disabled(isCreating)
                Spacer()
                Button("Create Sample") {
                    if let n = parsedCount {
                        defaultMethodRaw = method.rawValue
                        isCreating = true
                        vm.samplingError = nil
                        Task {
                            await vm.createSample(type: target, count: n, method: method)
                            if vm.samplingError == nil {
                                dismiss()
                            } else {
                                isCreating = false
                            }
                        }
                    }
                }
                .buttonStyle(.borderedProminent)
                .disabled(parsedCount == nil || isCreating)
                .keyboardShortcut(.return)
            }
            .padding()
        }
        .frame(minWidth: 380, minHeight: 420)
    }
}
