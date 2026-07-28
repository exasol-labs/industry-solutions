import SwiftUI
import ExasolConnector

private enum LLMStatus: Equatable { case unchecked, checking, reachable, failed(String) }
private enum DBStatus: Equatable { case unchecked, checking, ok, failed(String) }

// MARK: - Database server editor (Settings detail pane)

struct DatabaseServerEditor: View {
    let server: DatabaseServer

    @State private var name:        String
    @State private var comment:     String
    @State private var host:        String
    @State private var port:        Int
    @State private var username:    String
    @State private var password:    String
    @State private var schema:      String
    @State private var useTLS:      Bool
    @State private var certModeRaw:       String
    @State private var fingerprint:       String
    @State private var minRSAKeySizeBits: Int
    @State private var showPassword = false
    @State private var dbStatus:    DBStatus = .unchecked

    private var certMode: CertMode { CertMode(rawValue: certModeRaw) ?? .verify }

    init(server: DatabaseServer) {
        self.server = server
        _name         = State(initialValue: server.name)
        _comment      = State(initialValue: server.comment)
        _host         = State(initialValue: server.host)
        _port         = State(initialValue: server.port)
        _username     = State(initialValue: server.username)
        _password     = State(initialValue: DatabaseManager.shared.password(for: server.id))
        _schema       = State(initialValue: server.schema)
        _useTLS       = State(initialValue: server.useTLS)
        _certModeRaw       = State(initialValue: server.certModeRaw)
        _fingerprint       = State(initialValue: server.fingerprint)
        _minRSAKeySizeBits = State(initialValue: server.minRSAKeySizeBits)
    }

    var body: some View {
        Form {
            Section {
                HStack(spacing: 10) {
                    dbStatusIndicator
                    Spacer()
                    if dbStatus != .checking {
                        Button("Test") { Task { await checkConnection() } }
                            .buttonStyle(.bordered)
                            .controlSize(.small)
                            .disabled(host.isEmpty || username.isEmpty)
                    }
                }
            }

            Section("Connection") {
                LabeledContent("Name") {
                    TextField("My Exasol", text: $name)
                        .multilineTextAlignment(.trailing)
                }
                LabeledContent("Comment") {
                    TextField("Optional note", text: $comment)
                        .multilineTextAlignment(.trailing)
                }
                LabeledContent("Host") {
                    TextField("exasol.example.com", text: $host)
                        .multilineTextAlignment(.trailing)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .keyboardType(.URL)
                }
                LabeledContent("Port") {
                    TextField("8563", value: $port, format: .number.grouping(.never))
                        .multilineTextAlignment(.trailing)
                        .keyboardType(.numberPad)
                }
                LabeledContent("Username") {
                    TextField("sys", text: $username)
                        .multilineTextAlignment(.trailing)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                }
                LabeledContent("Password") {
                    HStack {
                        if showPassword {
                            TextField("Password", text: $password)
                                .autocorrectionDisabled()
                                .textInputAutocapitalization(.never)
                                .multilineTextAlignment(.trailing)
                        } else {
                            SecureField("Password", text: $password)
                                .multilineTextAlignment(.trailing)
                        }
                        Button { showPassword.toggle() } label: {
                            Image(systemName: showPassword ? "eye.slash" : "eye")
                                .foregroundStyle(.secondary)
                        }
                        .buttonStyle(.plain)
                    }
                }
                LabeledContent("Schema") {
                    TextField("Optional", text: $schema)
                        .multilineTextAlignment(.trailing)
                        .textInputAutocapitalization(.characters)
                        .autocorrectionDisabled()
                }
            }

            Section("Security") {
                Toggle("Use TLS / SSL", isOn: $useTLS)
                if useTLS {
                    Picker("Certificate", selection: $certModeRaw) {
                        Text("Verify (system trust)").tag(CertMode.verify.rawValue)
                        Text("Skip verification").tag(CertMode.skipVerification.rawValue)
                        Text("Fingerprint").tag(CertMode.fingerprint.rawValue)
                    }
                    if certMode == .skipVerification {
                        Label("Certificate will not be verified. Use only on trusted networks.",
                              systemImage: "exclamationmark.triangle")
                            .font(.caption)
                            .foregroundStyle(.orange)
                    }
                    if certMode == .fingerprint {
                        TextField("SHA-256 fingerprint (hex)", text: $fingerprint)
                            .font(.system(.footnote, design: .monospaced))
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                    }
                }
                Picker("Min. RSA key size", selection: $minRSAKeySizeBits) {
                    Text("1024 bits (legacy)").tag(1024)
                    Text("2048 bits (standard)").tag(2048)
                    Text("3072 bits").tag(3072)
                    Text("4096 bits").tag(4096)
                }
            }

            Section {
                Text("Changes are saved automatically.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .formStyle(.grouped)
        .navigationTitle(name.isEmpty ? "Database Server" : name)
        // Auto-save on edit (macOS Settings convention — no explicit Save button).
        .onChange(of: name)             { _, _ in save() }
        .onChange(of: comment)          { _, _ in save() }
        .onChange(of: host)             { _, _ in dbStatus = .unchecked; save() }
        .onChange(of: port)             { _, _ in dbStatus = .unchecked; save() }
        .onChange(of: username)         { _, _ in dbStatus = .unchecked; save() }
        .onChange(of: password)         { _, _ in dbStatus = .unchecked; save() }
        .onChange(of: schema)           { _, _ in save() }
        .onChange(of: useTLS)           { _, _ in dbStatus = .unchecked; save() }
        .onChange(of: certModeRaw)      { _, _ in dbStatus = .unchecked; save() }
        .onChange(of: fingerprint)      { _, _ in dbStatus = .unchecked; save() }
        .onChange(of: minRSAKeySizeBits){ _, _ in dbStatus = .unchecked; save() }
    }

    private func save() {
        var updated = server
        updated.name              = name
        updated.comment           = comment
        updated.host              = host
        updated.port              = port
        updated.username          = username
        updated.schema            = schema
        updated.useTLS            = useTLS
        updated.certModeRaw       = certModeRaw
        updated.fingerprint       = fingerprint
        updated.minRSAKeySizeBits = minRSAKeySizeBits
        DatabaseManager.shared.updateDatabaseServer(updated, password: password)
    }

    private func checkConnection() async {
        guard !host.isEmpty, !username.isEmpty else { return }
        dbStatus = .checking
        var temp = server
        temp.host              = host
        temp.port              = port
        temp.username          = username
        temp.schema            = schema
        temp.useTLS            = useTLS
        temp.certModeRaw       = certModeRaw
        temp.fingerprint       = fingerprint
        temp.minRSAKeySizeBits = minRSAKeySizeBits
        if let msg = await DatabaseManager.shared.testDatabaseServer(temp, password: password) {
            dbStatus = .failed(msg)
        } else {
            dbStatus = .ok
        }
    }

    private var dbStatusIndicator: some View {
        HStack(spacing: 8) {
            switch dbStatus {
            case .unchecked:
                Image(systemName: "circle.dashed").foregroundStyle(.secondary)
                Text("Not tested").foregroundStyle(.secondary)
            case .checking:
                ProgressView().controlSize(.small)
                Text("Connecting…").foregroundStyle(.secondary)
            case .ok:
                Circle().fill(Color.blue).frame(width: 10, height: 10)
                    .shadow(color: .blue.opacity(0.4), radius: 4)
                Text("Connection successful").foregroundStyle(.blue)
            case .failed(let msg):
                Image(systemName: "xmark.circle.fill").foregroundStyle(.red)
                Text(msg)
                    .font(.caption).foregroundStyle(.red)
                    .lineLimit(3).fixedSize(horizontal: false, vertical: true)
            }
        }
        .font(.callout)
        .animation(.easeInOut(duration: 0.2), value: dbStatus)
    }
}

// MARK: - LLM server editor (Settings detail pane)

struct LLMServerEditor: View {
    let server: LLMServer

    @State private var name:      String
    @State private var comment:   String
    @State private var serverURL: String
    @State private var apiKey:    String
    @State private var model:     String
    @State private var llmStatus: LLMStatus = .unchecked

    init(server: LLMServer) {
        self.server = server
        _name      = State(initialValue: server.name)
        _comment   = State(initialValue: server.comment)
        _serverURL = State(initialValue: server.serverURL)
        _apiKey    = State(initialValue: server.apiKey)
        _model     = State(initialValue: server.model)
    }

    var body: some View {
        Form {
            Section {
                HStack(spacing: 10) {
                    llmStatusIndicator
                    Spacer()
                    if llmStatus != .checking {
                        Button("Test") { Task { await check() } }
                            .buttonStyle(.bordered)
                            .controlSize(.small)
                    }
                }
            }

            Section("Server") {
                LabeledContent("Name") {
                    TextField("Local LLM", text: $name)
                        .multilineTextAlignment(.trailing)
                }
                LabeledContent("Comment") {
                    TextField("Optional note", text: $comment)
                        .multilineTextAlignment(.trailing)
                }
                LabeledContent("Server URL") {
                    ZStack(alignment: .trailing) {
                        if serverURL.isEmpty {
                            Text("http://localhost:1234/v1")
                                .foregroundStyle(Color(.placeholderText))
                                .allowsHitTesting(false)
                        }
                        TextField("", text: $serverURL)
                            .multilineTextAlignment(.trailing)
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                            .keyboardType(.URL)
                            .onSubmit { Task { await check() } }
                    }
                }
                LabeledContent("API Key") {
                    TextField("not-needed", text: $apiKey)
                        .multilineTextAlignment(.trailing)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                }
                LabeledContent("Model") {
                    TextField("qwen3-coder:30B", text: $model)
                        .multilineTextAlignment(.trailing)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                }
            }

            Section {
                Text("Changes are saved automatically.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .formStyle(.grouped)
        .navigationTitle(name.isEmpty ? "LLM Server" : name)
        // Auto-save on edit (macOS Settings convention — no explicit Save button).
        .onChange(of: name)      { _, _ in save() }
        .onChange(of: comment)   { _, _ in save() }
        .onChange(of: serverURL) { _, _ in llmStatus = .unchecked; save() }
        .onChange(of: apiKey)    { _, _ in save() }
        .onChange(of: model)     { _, _ in save() }
    }

    private func save() {
        var updated = server
        updated.name      = name
        updated.comment   = comment
        updated.serverURL = serverURL
        updated.apiKey    = apiKey
        updated.model     = model
        DatabaseManager.shared.updateLLMServer(updated)
    }

    private func check() async {
        var temp = server
        temp.serverURL = serverURL
        temp.apiKey    = apiKey
        temp.model     = model
        llmStatus = .checking
        let err = await DatabaseManager.shared.testLLMServer(temp)
        llmStatus = err == nil ? .reachable : .failed(err ?? "Not reachable")
    }

    private var llmStatusIndicator: some View {
        HStack(spacing: 8) {
            switch llmStatus {
            case .unchecked:
                Image(systemName: "circle.dashed").foregroundStyle(.secondary)
                Text("Not checked").foregroundStyle(.secondary)
            case .checking:
                ProgressView().controlSize(.small)
                Text("Checking").foregroundStyle(.secondary)
            case .reachable:
                Circle().fill(Color.blue).frame(width: 10, height: 10)
                    .shadow(color: .blue.opacity(0.4), radius: 4)
                Text("Server reachable").foregroundStyle(.blue)
            case .failed(let msg):
                Image(systemName: "xmark.circle.fill").foregroundStyle(.red)
                Text(msg)
                    .font(.caption).foregroundStyle(.red)
                    .lineLimit(3).fixedSize(horizontal: false, vertical: true)
            }
        }
        .font(.callout)
        .animation(.easeInOut(duration: 0.2), value: llmStatus)
    }
}

// MARK: - Connection pairing editor (sidebar sheet)

/// Pairs a database server with an optional LLM server into a connection.
/// The servers themselves are managed in the Settings window.
struct ConnectionPairingEditor: View {
    let profile: ConnectionProfile?
    let onSave:  (ConnectionProfile) -> Void

    @Environment(\.dismiss) private var dismiss
    @ObservedObject private var db = DatabaseManager.shared

    @State private var name:    String
    @State private var comment: String
    @State private var databaseServerId: UUID?
    @State private var llmServerId:      UUID?

    init(profile: ConnectionProfile?, onSave: @escaping (ConnectionProfile) -> Void) {
        self.profile = profile
        self.onSave  = onSave
        _name             = State(initialValue: profile?.name    ?? "")
        _comment          = State(initialValue: profile?.comment ?? "")
        _databaseServerId = State(initialValue: profile?.databaseServerId)
        _llmServerId      = State(initialValue: profile?.llmServerId)
    }

    var body: some View {
        NavigationStack {
            Form {
                Section("Connection") {
                    LabeledContent("Name") {
                        TextField("My Connection", text: $name)
                            .multilineTextAlignment(.trailing)
                    }
                    LabeledContent("Comment") {
                        TextField("Optional note", text: $comment)
                            .multilineTextAlignment(.trailing)
                    }
                }

                Section("Database Server") {
                    if db.databaseServers.isEmpty {
                        Label("No database servers yet. Add one in Settings (⌘,).",
                              systemImage: "exclamationmark.triangle")
                            .font(.caption)
                            .foregroundStyle(.orange)
                    } else {
                        Picker("Database", selection: $databaseServerId) {
                            Text("None").tag(UUID?.none)
                            ForEach(db.databaseServers) { server in
                                Text(server.name.isEmpty ? server.host : server.name)
                                    .tag(UUID?.some(server.id))
                            }
                        }
                    }
                }

                Section("LLM Server (optional)") {
                    Picker("LLM", selection: $llmServerId) {
                        Text("None").tag(UUID?.none)
                        ForEach(db.llmServers) { server in
                            Text(server.name.isEmpty ? server.serverURL : server.name)
                                .tag(UUID?.some(server.id))
                        }
                    }
                }

                Section {
                    Label("Manage database and LLM servers in Settings (⌘,).",
                          systemImage: "gearshape")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            .formStyle(.grouped)
            #if os(macOS)
            .frame(minWidth: 420, minHeight: 440)
            #endif
            .navigationTitle(profile == nil ? "New Connection" : "Edit Connection")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save") {
                        var updated = profile ?? ConnectionProfile()
                        updated.name             = name
                        updated.comment          = comment
                        updated.databaseServerId = databaseServerId
                        updated.llmServerId      = llmServerId
                        onSave(updated)
                        dismiss()
                    }
                    .disabled(name.isEmpty || databaseServerId == nil)
                }
            }
        }
    }
}
