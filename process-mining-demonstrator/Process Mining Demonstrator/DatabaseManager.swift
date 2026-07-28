import Foundation
import Combine
import ExasolConnector

final class DatabaseManager: ObservableObject {
    static let shared = DatabaseManager()

    private var connection: ExasolConnection?

    @Published var databaseServers: [DatabaseServer] = []
    @Published var llmServers:      [LLMServer]       = []
    @Published var profiles:        [ConnectionProfile] = []
    @Published var activeProfileId: UUID?
    @Published var isConnected      = false
    @Published var isLLMReachable   = false
    @Published var lastError:       String?
    @Published var pendingAlert:    AppAlert?

    // MARK: - Resolvers

    var activeProfile: ConnectionProfile? {
        profiles.first { $0.id == activeProfileId }
    }

    var activeDatabaseServer: DatabaseServer? {
        activeProfile.flatMap { databaseServer(for: $0) }
    }

    var activeLLMServer: LLMServer? {
        activeProfile.flatMap { llmServer(for: $0) }
    }

    func databaseServer(for profile: ConnectionProfile) -> DatabaseServer? {
        guard let id = profile.databaseServerId else { return nil }
        return databaseServers.first { $0.id == id }
    }

    func llmServer(for profile: ConnectionProfile) -> LLMServer? {
        guard let id = profile.llmServerId else { return nil }
        return llmServers.first { $0.id == id }
    }

    private init() {
        loadAll()
        migrateLegacyProfilesIfNeeded()
    }

    // MARK: - Persistence

    private enum Keys {
        static let databaseServers = "database_servers"
        static let llmServers      = "llm_servers"
        static let profiles        = "connection_profiles"
        static let activeProfile   = "active_profile_id"
        static let migratedV2      = "settings.v2.migrated"
    }

    private func loadAll() {
        let ud = UserDefaults.standard
        if let data = ud.data(forKey: Keys.databaseServers),
           let decoded = try? JSONDecoder().decode([DatabaseServer].self, from: data) {
            databaseServers = decoded
        }
        if let data = ud.data(forKey: Keys.llmServers),
           let decoded = try? JSONDecoder().decode([LLMServer].self, from: data) {
            llmServers = decoded
        }
        if let data = ud.data(forKey: Keys.profiles),
           let decoded = try? JSONDecoder().decode([ConnectionProfile].self, from: data) {
            profiles = decoded
        }
        if let str = ud.string(forKey: Keys.activeProfile),
           let uuid = UUID(uuidString: str) {
            activeProfileId = uuid
        }
    }

    func save() {
        let ud = UserDefaults.standard
        if let data = try? JSONEncoder().encode(databaseServers) {
            ud.set(data, forKey: Keys.databaseServers)
        }
        if let data = try? JSONEncoder().encode(llmServers) {
            ud.set(data, forKey: Keys.llmServers)
        }
        if let data = try? JSONEncoder().encode(profiles) {
            ud.set(data, forKey: Keys.profiles)
        }
        if let id = activeProfileId {
            ud.set(id.uuidString, forKey: Keys.activeProfile)
        } else {
            ud.removeObject(forKey: Keys.activeProfile)
        }
    }

    // MARK: - Passwords (keyed by database-server id)

    private func pwKey(_ id: UUID) -> String { "conn_pw_\(id.uuidString)" }

    func password(for serverId: UUID) -> String {
        UserDefaults.standard.string(forKey: pwKey(serverId)) ?? ""
    }

    private func setPassword(_ pw: String, for serverId: UUID) {
        UserDefaults.standard.set(pw, forKey: pwKey(serverId))
    }

    // MARK: - Database server CRUD

    func addDatabaseServer(_ server: DatabaseServer, password: String) {
        databaseServers.append(server)
        setPassword(password, for: server.id)
        save()
    }

    func updateDatabaseServer(_ server: DatabaseServer, password: String? = nil) {
        guard let idx = databaseServers.firstIndex(where: { $0.id == server.id }) else { return }
        databaseServers[idx] = server
        if let pw = password { setPassword(pw, for: server.id) }
        save()
    }

    func deleteDatabaseServer(_ server: DatabaseServer) {
        // Disconnect if the active connection uses this server.
        if activeDatabaseServer?.id == server.id {
            Task { await disconnect() }
        }
        databaseServers.removeAll { $0.id == server.id }
        UserDefaults.standard.removeObject(forKey: pwKey(server.id))
        // Null out references from any connection.
        for idx in profiles.indices where profiles[idx].databaseServerId == server.id {
            profiles[idx].databaseServerId = nil
        }
        save()
    }

    // MARK: - LLM server CRUD

    func addLLMServer(_ server: LLMServer) {
        llmServers.append(server)
        save()
    }

    func updateLLMServer(_ server: LLMServer) {
        guard let idx = llmServers.firstIndex(where: { $0.id == server.id }) else { return }
        llmServers[idx] = server
        save()
    }

    func deleteLLMServer(_ server: LLMServer) {
        llmServers.removeAll { $0.id == server.id }
        for idx in profiles.indices where profiles[idx].llmServerId == server.id {
            profiles[idx].llmServerId = nil
        }
        save()
    }

    // MARK: - Connection (pairing) CRUD

    func addProfile(_ profile: ConnectionProfile) {
        profiles.append(profile)
        save()
    }

    func updateProfile(_ profile: ConnectionProfile) {
        guard let idx = profiles.firstIndex(where: { $0.id == profile.id }) else { return }
        profiles[idx] = profile
        save()
    }

    func deleteProfile(_ profile: ConnectionProfile) {
        if activeProfileId == profile.id {
            Task { await disconnect() }
        }
        profiles.removeAll { $0.id == profile.id }
        save()
    }

    // MARK: - Connection

    private func config(for server: DatabaseServer) -> ExasolConfig {
        let certMode = CertMode(rawValue: server.certModeRaw) ?? .verify
        return ExasolConfig(
            host:              server.host,
            port:              server.port,
            username:          server.username,
            schema:            server.schema,
            useTLS:            server.useTLS,
            certMode:          certMode,
            certFingerprint:   server.fingerprint,
            minRSAKeySizeBits: server.minRSAKeySizeBits
        )
    }

    func connect(profile: ConnectionProfile) async {
        activeProfileId = profile.id
        save()
        lastError = nil
        guard let server = databaseServer(for: profile) else {
            let msg = "This connection has no database server selected. Edit it and choose one."
            lastError   = msg
            isConnected = false
            pendingAlert = AppAlert.info(title: "No Database Server", message: msg)
            return
        }
        let conn = ExasolConnection()
        do {
            try await conn.connect(config: config(for: server), password: password(for: server.id))
            connection = conn
            isConnected = true
            await checkLLMReachability(for: llmServer(for: profile))
        } catch {
            let msg = DatabaseManager.friendlyError(error)
            lastError   = msg
            isConnected = false
            let retryProfile = profile
            if let e = error as? ExasolError, case .authFailed = e {
                pendingAlert = AppAlert(
                    title: "Authentication Failed",
                    message: msg + "\n\nEdit the database server in Settings to correct your username or password.",
                    primary:   .ok,
                    secondary: nil
                )
            } else {
                pendingAlert = AppAlert.error(title: "Connection Failed", message: msg) {
                    Task { await DatabaseManager.shared.connect(profile: retryProfile) }
                }
            }
        }
    }

    /// Tests a database server's credentials without affecting the active connection.
    /// Returns nil on success, or a user-friendly error string on failure.
    func testDatabaseServer(_ server: DatabaseServer, password: String) async -> String? {
        let conn = ExasolConnection()
        do {
            try await conn.connect(config: config(for: server), password: password)
            await conn.disconnect()
            return nil
        } catch {
            return DatabaseManager.friendlyError(error)
        }
    }

    // MARK: - Error formatting

    static func friendlyError(_ error: Error) -> String {
        guard let e = error as? ExasolError else { return error.localizedDescription }
        switch e {
        case .notConnected:
            return "Not connected."
        case .authFailed(let msg):
            let hint = msg.isEmpty ? "" : " (\(msg))"
            return "Authentication failed — check your username and password.\(hint)"
        case .rsaFailed:
            return "Password encryption failed. The server may be unreachable or returned an unexpected public key."
        case .weakRSAKey(let bits, let minBits):
            return "The server's RSA key is too weak (\(bits)-bit; minimum \(minBits) bits). Lower the minimum RSA key size in Security settings if connecting to a legacy server."
        case .connectionFailed(let detail):
            let d = detail.lowercased()
            if d.contains("timed out") || d.contains("timeout") {
                return "Connection timed out. Verify the host address, port, and network connectivity."
            }
            if d.contains("refused") {
                return "Connection refused. No server is accepting connections at this host and port."
            }
            if d.contains("certificate") || d.contains("trust") || d.contains("ssl") || d.contains("tls") {
                return "TLS certificate error. Try 'Skip verification' or configure a fingerprint in Security settings. (\(detail))"
            }
            if d.contains("no such host") || d.contains("host not found") || d.contains("nodename") || d.contains("name or service") {
                return "Host not found. Check the hostname spelling and your DNS / network connectivity."
            }
            return "Connection failed: \(detail)"
        case .queryFailed(let msg, let code):
            return "[\(code)] \(msg)"
        case .protocolError(let msg):
            return "Protocol error — unexpected server response. \(msg)"
        }
    }

    func disconnect() async {
        if let c = connection { await c.disconnect() }
        connection    = nil
        isConnected   = false
        isLLMReachable = false
    }

    // MARK: - LLM reachability

    func checkLLMReachability(for server: LLMServer?) async {
        guard let server, !server.serverURL.isEmpty,
              let base = URL(string: server.serverURL) else {
            isLLMReachable = false
            return
        }
        var req = URLRequest(url: base.appendingPathComponent("models"), timeoutInterval: 5)
        req.httpMethod = "GET"
        if !server.apiKey.isEmpty {
            req.setValue("Bearer \(server.apiKey)", forHTTPHeaderField: "Authorization")
        }
        do {
            let (_, response) = try await URLSession.shared.data(for: req)
            let code = (response as? HTTPURLResponse)?.statusCode ?? 200
            isLLMReachable = code < 500
        } catch {
            isLLMReachable = false
        }
    }

    /// Probes an LLM server's `/models` endpoint. Returns nil if reachable, or a
    /// user-facing error string otherwise. Does not mutate `isLLMReachable`.
    func testLLMServer(_ server: LLMServer) async -> String? {
        let urlString = server.serverURL.trimmingCharacters(in: .whitespaces)
        guard !urlString.isEmpty, let base = URL(string: urlString) else {
            return "Enter a valid server URL."
        }
        var req = URLRequest(url: base.appendingPathComponent("models"), timeoutInterval: 6)
        req.httpMethod = "GET"
        let key = server.apiKey.trimmingCharacters(in: .whitespaces)
        if !key.isEmpty {
            req.setValue("Bearer \(key)", forHTTPHeaderField: "Authorization")
        }
        do {
            let (_, response) = try await URLSession.shared.data(for: req)
            let code = (response as? HTTPURLResponse)?.statusCode ?? 200
            return code < 500 ? nil : "Server responded with HTTP \(code)."
        } catch {
            return "Server not reachable: \(error.localizedDescription)"
        }
    }

    func execute(_ sql: String) async throws -> QueryResult {
        guard let c = connection else { throw ExasolError.notConnected }
        return try await c.execute(sql)
    }

    // MARK: - Legacy migration (one-time)

    /// The shape connections had before the Database/LLM split, used only to read
    /// pre-existing UserDefaults / backups so they can be migrated.
    struct LegacyConnectionProfile: Codable {
        var id           = UUID()
        var name:        String = ""
        var comment:     String = ""
        var host:        String = ""
        var port:        Int    = 8563
        var username:    String = ""
        var schema:      String = ""
        var useTLS:           Bool   = false
        var certModeRaw:      String = "verify"
        var fingerprint:      String = ""
        var minRSAKeySizeBits: Int   = 2048
        var llmServerURL: String = ""
        var llmApiKey:    String = ""
        var llmModel:     String = ""
    }

    /// Pure split of a legacy profile into a database server (id preserved so the
    /// stored password key keeps working), an optional LLM server, and a connection
    /// pairing (id preserved so `activeProfileId` still matches). No side effects —
    /// safe to unit-test in isolation.
    static func splitLegacyProfile(_ legacy: LegacyConnectionProfile)
        -> (database: DatabaseServer, llm: LLMServer?, profile: ConnectionProfile)
    {
        var dbServer = DatabaseServer()
        dbServer.id                = legacy.id
        dbServer.name              = legacy.name.isEmpty ? legacy.host : legacy.name
        dbServer.comment           = legacy.comment
        dbServer.host              = legacy.host
        dbServer.port              = legacy.port
        dbServer.username          = legacy.username
        dbServer.schema            = legacy.schema
        dbServer.useTLS            = legacy.useTLS
        dbServer.certModeRaw       = legacy.certModeRaw
        dbServer.fingerprint       = legacy.fingerprint
        dbServer.minRSAKeySizeBits = legacy.minRSAKeySizeBits

        var llm: LLMServer? = nil
        if !legacy.llmServerURL.isEmpty {
            var s = LLMServer()
            s.name      = legacy.name.isEmpty ? "LLM" : "\(legacy.name) LLM"
            s.serverURL = legacy.llmServerURL
            s.apiKey    = legacy.llmApiKey
            s.model     = legacy.llmModel
            llm = s
        }

        var profile = ConnectionProfile()
        profile.id               = legacy.id
        profile.name             = legacy.name
        profile.comment          = legacy.comment
        profile.databaseServerId = dbServer.id
        profile.llmServerId      = llm?.id
        return (dbServer, llm, profile)
    }

    /// Applies `splitLegacyProfile` to the in-memory arrays (deduping by id).
    /// Does not persist.
    @discardableResult
    func ingestLegacyProfile(_ legacy: LegacyConnectionProfile) -> ConnectionProfile {
        let parts = DatabaseManager.splitLegacyProfile(legacy)
        if !databaseServers.contains(where: { $0.id == parts.database.id }) {
            databaseServers.append(parts.database)
        }
        if let llm = parts.llm {
            llmServers.append(llm)
        }
        if !profiles.contains(where: { $0.id == parts.profile.id }) {
            profiles.append(parts.profile)
        }
        return parts.profile
    }

    private func migrateLegacyProfilesIfNeeded() {
        let ud = UserDefaults.standard
        guard !ud.bool(forKey: Keys.migratedV2) else { return }
        defer { ud.set(true, forKey: Keys.migratedV2) }

        // Already on the new model (servers present) — nothing to migrate.
        guard databaseServers.isEmpty, llmServers.isEmpty else { return }

        guard let data = ud.data(forKey: Keys.profiles),
              let legacy = try? JSONDecoder().decode([LegacyConnectionProfile].self, from: data),
              legacy.contains(where: { !$0.host.isEmpty }) else { return }

        // Rebuild fresh from the legacy blob.
        databaseServers.removeAll()
        llmServers.removeAll()
        profiles.removeAll()
        for lp in legacy { ingestLegacyProfile(lp) }
        save()
    }
}
