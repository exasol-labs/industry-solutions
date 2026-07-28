import SwiftUI

/// The macOS Settings window (⌘,). A category sidebar lists Database and LLM
/// server definitions; the detail pane edits the selected entry. Extensible:
/// add more sections for future categories.
struct PreferencesView: View {
    @ObservedObject private var db = DatabaseManager.shared
    @State private var selection: PrefSelection?

    enum PrefSelection: Hashable {
        case database(UUID)
        case llm(UUID)
        case sampling
        case flowchart
    }

    var body: some View {
        NavigationSplitView {
            List(selection: $selection) {
                Section("Database") {
                    ForEach(db.databaseServers) { server in
                        Label(server.name.isEmpty ? "Untitled server" : server.name,
                              systemImage: "cylinder.split.1x2")
                            .tag(PrefSelection.database(server.id))
                    }
                    .onDelete { offsets in
                        offsets.map { db.databaseServers[$0] }.forEach(db.deleteDatabaseServer)
                    }
                    Button {
                        addDatabaseServer()
                    } label: {
                        Label("Add Database Server", systemImage: "plus")
                    }
                    .buttonStyle(.borderless)
                }

                Section("LLM") {
                    ForEach(db.llmServers) { server in
                        Label(server.name.isEmpty ? "Untitled server" : server.name,
                              systemImage: "brain")
                            .tag(PrefSelection.llm(server.id))
                    }
                    .onDelete { offsets in
                        offsets.map { db.llmServers[$0] }.forEach(db.deleteLLMServer)
                    }
                    Button {
                        addLLMServer()
                    } label: {
                        Label("Add LLM Server", systemImage: "plus")
                    }
                    .buttonStyle(.borderless)
                }

                Section("Sampling") {
                    Label("Sampling Preferences", systemImage: "square.3.layers.3d")
                        .tag(PrefSelection.sampling)
                }

                Section("Appearance") {
                    Label("Flow Chart", systemImage: "arrow.triangle.branch")
                        .tag(PrefSelection.flowchart)
                }
            }
            .navigationTitle("Settings")
            .frame(minWidth: 220)
        } detail: {
            detailView
        }
        .frame(minWidth: 760, minHeight: 520)
    }

    @ViewBuilder
    private var detailView: some View {
        switch selection {
        case .database(let id):
            if let server = db.databaseServers.first(where: { $0.id == id }) {
                DatabaseServerEditor(server: server)
                    .id(server.id)
                    .toolbar { deleteToolbar { db.deleteDatabaseServer(server); selection = nil } }
            } else {
                placeholder
            }
        case .llm(let id):
            if let server = db.llmServers.first(where: { $0.id == id }) {
                LLMServerEditor(server: server)
                    .id(server.id)
                    .toolbar { deleteToolbar { db.deleteLLMServer(server); selection = nil } }
            } else {
                placeholder
            }
        case .sampling:
            SamplingPreferencesView()
        case .flowchart:
            FlowChartPreferencesView()
        case nil:
            placeholder
        }
    }

    private var placeholder: some View {
        ContentUnavailableView(
            "No Selection",
            systemImage: "gearshape",
            description: Text("Select a server on the left, or add a new one.")
        )
    }

    @ToolbarContentBuilder
    private func deleteToolbar(_ action: @escaping () -> Void) -> some ToolbarContent {
        ToolbarItem(placement: .destructiveAction) {
            Button(role: .destructive, action: action) {
                Label("Delete", systemImage: "trash")
            }
        }
    }

    private func addDatabaseServer() {
        var server = DatabaseServer()
        server.name = "New Database Server"
        db.addDatabaseServer(server, password: "")
        selection = .database(server.id)
    }

    private func addLLMServer() {
        var server = LLMServer()
        server.name = "New LLM Server"
        db.addLLMServer(server)
        selection = .llm(server.id)
    }
}
struct SamplingPreferencesView: View {
    @AppStorage("sampling.defaultMethod") private var defaultMethodRaw: String = "random"
    @AppStorage("sampling.activeSampleSet") private var activeSampleSetRaw: String = "ORIGINAL"

    private var defaultMethod: Binding<SamplingMethod> {
        Binding(
            get: { SamplingMethod(rawValue: defaultMethodRaw) ?? .random },
            set: { defaultMethodRaw = $0.rawValue }
        )
    }
    private var activeSampleSet: Binding<SampleSet> {
        Binding(
            get: { SampleSet(rawValue: activeSampleSetRaw) ?? .original },
            set: { activeSampleSetRaw = $0.rawValue }
        )
    }

    var body: some View {
        Form {
            Section("Active Data Set") {
                Picker("Active data", selection: activeSampleSet) {
                    ForEach(SampleSet.allCases) { set in
                        Text(set.label).tag(set)
                    }
                }
                .pickerStyle(.radioGroup)
                Text("Chooses which data set is used for all analysis. Sample sets must be created first in the Sampling panel.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            Section("Default Sampling Method") {
                Picker("Default method", selection: defaultMethod) {
                    ForEach(SamplingMethod.allCases) { m in
                        Label(m.label, systemImage: m.icon).tag(m)
                    }
                }
                .pickerStyle(.radioGroup)

                VStack(alignment: .leading, spacing: 6) {
                    ForEach(SamplingMethod.allCases) { m in
                        HStack(alignment: .top, spacing: 6) {
                            Image(systemName: m.icon)
                                .frame(width: 16)
                                .foregroundStyle(.secondary)
                            VStack(alignment: .leading, spacing: 1) {
                                Text(m.label).font(.caption.weight(.medium))
                                Text(m.shortDescription).font(.caption).foregroundStyle(.secondary)
                            }
                        }
                    }
                }
                .padding(.top, 4)
            }
        }
        .formStyle(.grouped)
        .navigationTitle("Sampling Preferences")
        .frame(minWidth: 420, minHeight: 380)
    }
}

// MARK: - Flow Chart preferences

struct FlowChartPreferencesView: View {
    @AppStorage("graph.edge.colorizeByWeight") private var colorize = true

    var body: some View {
        Form {
            Section("Connection Coloring") {
                Toggle("Colorize connections by weight", isOn: $colorize)
                    .padding(.vertical, 2)

                if colorize {
                    Text("Choose a color scale for each metric. Connections are colored from low (few/short) to high (many/long). Edge thickness encodes value independently.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                        .padding(.top, 2)
                }
            }

            if colorize {
                Section("Color Scale per Metric") {
                    ForEach(TransitionMetric.allCases) { metric in
                        EdgeColorSchemaRow(metric: metric)
                    }
                }
            }

            Section {
                Button("Reset to Defaults") {
                    colorize = true
                    for metric in TransitionMetric.allCases {
                        UserDefaults.standard.removeObject(
                            forKey: "graph.edge.colorSchema.\(metric.rawValue)")
                    }
                }
            }
        }
        .formStyle(.grouped)
        .navigationTitle("Flow Chart")
        .frame(minWidth: 460, minHeight: 400)
    }
}

private struct EdgeColorSchemaRow: View {
    let metric: TransitionMetric

    @AppStorage private var schemaRaw: String

    init(metric: TransitionMetric) {
        self.metric = metric
        self._schemaRaw = AppStorage(
            wrappedValue: EdgeColorSchema.defaultSchema(for: metric).rawValue,
            "graph.edge.colorSchema.\(metric.rawValue)")
    }

    private var schema: Binding<EdgeColorSchema> {
        Binding(
            get: { EdgeColorSchema(rawValue: schemaRaw) ?? .neutral },
            set: { schemaRaw = $0.rawValue }
        )
    }

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: metric.icon)
                .font(.body)
                .foregroundStyle(Color.accentColor)
                .frame(width: 22)
            Text(metric.rawValue)
                .frame(maxWidth: .infinity, alignment: .leading)
            gradientPreview(for: schema.wrappedValue)
            Picker("", selection: schema) {
                ForEach(EdgeColorSchema.allCases) { s in
                    Text(s.label).tag(s)
                }
            }
            .labelsHidden()
            .frame(width: 170)
        }
    }

    private func gradientPreview(for s: EdgeColorSchema) -> some View {
        Group {
            if let colors = s.gradientColors {
                LinearGradient(colors: [colors.low, colors.high],
                               startPoint: .leading, endPoint: .trailing)
            } else {
                Color.secondary.opacity(0.25)
            }
        }
        .frame(width: 44, height: 12)
        .clipShape(RoundedRectangle(cornerRadius: 3, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 3, style: .continuous)
                .strokeBorder(Color.primary.opacity(0.15), lineWidth: 0.5)
        )
    }
}
