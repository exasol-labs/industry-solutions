import Foundation
import CryptoKit
import CommonCrypto
import Security

// MARK: - Encryption

enum BackupCryptoError: LocalizedError {
    case randomGenerationFailed
    case keyDerivationFailed
    case encryptionFailed
    case invalidFormat
    case wrongPassword

    var errorDescription: String? {
        switch self {
        case .randomGenerationFailed: return "Could not generate random bytes for encryption."
        case .keyDerivationFailed:    return "Could not derive encryption key from password."
        case .encryptionFailed:       return "Encryption failed."
        case .invalidFormat:          return "The backup file format is invalid or corrupted."
        case .wrongPassword:          return "Incorrect password — the backup could not be decrypted."
        }
    }
}

private struct EncryptedEnvelope: Codable {
    let encrypted:  Bool
    let salt:       String  // base64, 16 random bytes
    let ciphertext: String  // base64, AES-GCM combined (12-byte nonce + ciphertext + 16-byte tag)
}

// MARK: - Backup payload

struct AppBackup: Codable {
    let version:           Int
    let createdAt:         Date
    let includesPasswords: Bool
    let includesUsername:  Bool
    let includesLlmApiKey: Bool
    let appSettings:       AppSettings
    let connections:       [BackupProfile]
    let activeProfileId:   String?
    /// String-valued dynamic UserDefaults keys: norms_metric_*, llm_prompt_*
    let stringDefaults:    [String: String]
    /// Data-valued dynamic UserDefaults keys (base64): layout_*, graph.collapsedGroups_*, norms_*
    let dataDefaults:      [String: String]

    // MARK: Nested types

    struct AppSettings: Codable {
        let appTheme:                          String
        let graphStartMode:                    String
        let sliderMode:                        String
        let showGrouping:                      Bool
        let showNodeDescriptions:              Bool
        let kpiExpanded:                       Bool
        let valveOpen:                         Bool
        let sidebarProjectsExpanded:           Bool
        let sidebarFiltersExpanded:            Bool
        let sidebarFiltersDateExpanded:        Bool
        let sidebarFiltersMetaExpanded:        Bool
        let sidebarFiltersIncludeExpanded:     Bool
        let sidebarFiltersExcludeExpanded:     Bool
        let sidebarFiltersStepsExpanded:       Bool
        let sidebarFiltersJourneyTimeExpanded: Bool
        let sidebarFiltersScoreExpanded:       Bool
        let sidebarMetricsExpanded:            Bool
        let sidebarConfigExpanded:             Bool
        let sidebarConfigStepsExpanded:        Bool
    }

    struct BackupProfile: Codable {
        let id:           String
        let name:         String
        let comment:      String?   // nil in backups created before the comment field was added
        let host:         String
        let port:         Int
        let username:     String?   // nil when the export was created with includesUsername = false
        let schema:       String
        let useTLS:       Bool
        let certModeRaw:       String
        let fingerprint:       String
        let minRSAKeySizeBits: Int?     // nil in backups created before this field was added
        let llmServerURL: String
        let llmApiKey:    String?   // nil when the export was created with includesLlmApiKey = false
        let llmModel:     String
        let password:     String?
    }

    struct Summary {
        let createdAt:         Date
        let includesPasswords: Bool
        let includesUsername:  Bool
        let includesLlmApiKey: Bool
        let connectionCount:   Int
        let projectCount:      Int
        let hasLayouts:        Bool
        let hasNorms:          Bool
        let hasHappyPaths:     Bool
        let hasFilterGroups:   Bool
    }

    var summary: Summary {
        var projectIds = Set<String>()
        for key in stringDefaults.keys {
            if      key.hasPrefix("norms_metric_") { projectIds.insert(String(key.dropFirst("norms_metric_".count))) }
            else if key.hasPrefix("llm_prompt_")   { projectIds.insert(String(key.dropFirst("llm_prompt_".count))) }
        }
        for key in dataDefaults.keys where key.hasPrefix("norms_") {
            projectIds.insert(String(key.dropFirst("norms_".count)))
        }

        return Summary(
            createdAt:         createdAt,
            includesPasswords: includesPasswords,
            includesUsername:  includesUsername,
            includesLlmApiKey: includesLlmApiKey,
            connectionCount:   connections.count,
            projectCount:      projectIds.count,
            hasLayouts:        dataDefaults.keys.contains(where: { $0.hasPrefix("layout_") }),
            hasNorms:          dataDefaults.keys.contains(where: { $0.hasPrefix("norms_") }),
            hasHappyPaths:     dataDefaults.keys.contains(where: { $0.hasPrefix("happyPaths_") }),
            hasFilterGroups:   dataDefaults.keys.contains(where: { $0.hasPrefix("filterGroups_") })
        )
    }
}

// MARK: - Restore options

struct RestoreOptions {
    var appSettings:   Bool = true
    var connections:   Bool = true
    var username:      Bool = true   // only applied when backup.includesUsername
    var llmApiKey:     Bool = true   // only applied when backup.includesLlmApiKey
    var passwords:     Bool = true   // only applied when backup.includesPasswords
    var layouts:       Bool = true
    var norms:         Bool = true
    var happyPaths:    Bool = true
    var filterPresets: Bool = true
}

// MARK: - Backup manager

enum BackupManager {

    // Keys whose values are Strings in UserDefaults
    private static let stringPrefixes = ["norms_metric_", "llm_prompt_"]
    // Keys whose values are Data in UserDefaults (norms_metric_ excluded since it's a String)
    private static let dataPrefixes   = ["layout_", "graph.collapsedGroups_", "norms_", "happyPaths_", "filterGroups_"]

    private static func bool(_ key: String, `default` def: Bool) -> Bool {
        (UserDefaults.standard.object(forKey: key) as? Bool) ?? def
    }

    // MARK: Export

    static func exportPayload(includePasswords: Bool,
                              includeUsername:  Bool,
                              includeLlmApiKey: Bool) -> AppBackup {
        let ud = UserDefaults.standard
        var stringDefaults: [String: String] = [:]
        var dataDefaults:   [String: String] = [:]

        for (key, value) in ud.dictionaryRepresentation() {
            if stringPrefixes.contains(where: { key.hasPrefix($0) }), let s = value as? String {
                stringDefaults[key] = s
            } else if dataPrefixes.contains(where: { key.hasPrefix($0) }),
                      !key.hasPrefix("norms_metric_"),
                      let d = value as? Data {
                dataDefaults[key] = d.base64EncodedString()
            }
        }

        let db       = DatabaseManager.shared
        // Flatten each connection (pairing) back into the combined backup record by
        // resolving its database/LLM servers, keeping the on-disk backup format stable.
        let profiles = db.profiles.map { p -> AppBackup.BackupProfile in
            let dbSrv  = db.databaseServer(for: p)
            let llmSrv = db.llmServer(for: p)
            return AppBackup.BackupProfile(
                id:           p.id.uuidString,
                name:         p.name,
                comment:      p.comment.isEmpty ? nil : p.comment,
                host:         dbSrv?.host ?? "",
                port:         dbSrv?.port ?? 8563,
                username:     includeUsername  ? (dbSrv?.username ?? "") : nil,
                schema:       dbSrv?.schema ?? "",
                useTLS:       dbSrv?.useTLS ?? false,
                certModeRaw:       dbSrv?.certModeRaw ?? "verify",
                fingerprint:       dbSrv?.fingerprint ?? "",
                minRSAKeySizeBits: dbSrv?.minRSAKeySizeBits ?? 2048,
                llmServerURL: llmSrv?.serverURL ?? "",
                llmApiKey:    includeLlmApiKey ? (llmSrv?.apiKey ?? "") : nil,
                llmModel:     llmSrv?.model ?? "",
                password:     includePasswords ? db.password(for: dbSrv?.id ?? p.id) : nil
            )
        }

        let s = AppBackup.AppSettings(
            appTheme:                          ud.string(forKey: "app.theme")       ?? "system",
            graphStartMode:                    ud.string(forKey: "graph.startMode") ?? "expanded",
            sliderMode:                        ud.string(forKey: "slider.mode")     ?? "Range",
            showGrouping:                      bool("processmap.showGrouping",            default: true),
            showNodeDescriptions:              bool("processmap.showNodeDescriptions",    default: true),
            kpiExpanded:                       bool("processmap.kpiExpanded",   default: true),
            valveOpen:                         bool("abComparison.valveOpen",   default: true),
            sidebarProjectsExpanded:           bool("sidebar.projectsExpanded",           default: true),
            sidebarFiltersExpanded:            bool("sidebar.filtersExpanded",            default: true),
            sidebarFiltersDateExpanded:        bool("sidebar.filtersDateExpanded",        default: true),
            sidebarFiltersMetaExpanded:        bool("sidebar.filtersMetaExpanded",        default: false),
            sidebarFiltersIncludeExpanded:     bool("sidebar.filtersIncludeExpanded",     default: false),
            sidebarFiltersExcludeExpanded:     bool("sidebar.filtersExcludeExpanded",     default: false),
            sidebarFiltersStepsExpanded:       bool("sidebar.filtersStepsExpanded",       default: false),
            sidebarFiltersJourneyTimeExpanded: bool("sidebar.filtersJourneyTimeExpanded", default: false),
            sidebarFiltersScoreExpanded:       bool("sidebar.filtersScoreExpanded",       default: false),
            sidebarMetricsExpanded:            bool("sidebar.metricsExpanded",            default: true),
            sidebarConfigExpanded:             bool("sidebar.configExpanded",             default: true),
            sidebarConfigStepsExpanded:        bool("sidebar.configStepsExpanded",        default: true)
        )

        return AppBackup(
            version:           1,
            createdAt:         Date(),
            includesPasswords: includePasswords,
            includesUsername:  includeUsername,
            includesLlmApiKey: includeLlmApiKey,
            appSettings:       s,
            connections:       profiles,
            activeProfileId:   db.activeProfile?.id.uuidString,
            stringDefaults:    stringDefaults,
            dataDefaults:      dataDefaults
        )
    }

    static func encode(_ backup: AppBackup) throws -> Data {
        let encoder = JSONEncoder()
        encoder.outputFormatting   = [.prettyPrinted, .sortedKeys]
        encoder.dateEncodingStrategy = .iso8601
        return try encoder.encode(backup)
    }

    static func decode(from data: Data) throws -> AppBackup {
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        return try decoder.decode(AppBackup.self, from: data)
    }

    // MARK: Encryption

    static func isEncrypted(_ data: Data) -> Bool {
        struct Probe: Decodable { let encrypted: Bool? }
        return (try? JSONDecoder().decode(Probe.self, from: data))?.encrypted == true
    }

    static func encryptBackup(_ data: Data, password: String) throws -> Data {
        var salt = [UInt8](repeating: 0, count: 16)
        guard SecRandomCopyBytes(kSecRandomDefault, salt.count, &salt) == errSecSuccess else {
            throw BackupCryptoError.randomGenerationFailed
        }
        let key    = try deriveKey(from: password, salt: salt)
        let sealed = try AES.GCM.seal(data, using: key)
        guard let combined = sealed.combined else { throw BackupCryptoError.encryptionFailed }
        let envelope = EncryptedEnvelope(
            encrypted:  true,
            salt:       Data(salt).base64EncodedString(),
            ciphertext: combined.base64EncodedString()
        )
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        return try encoder.encode(envelope)
    }

    static func decryptBackup(_ data: Data, password: String) throws -> Data {
        let envelope = try JSONDecoder().decode(EncryptedEnvelope.self, from: data)
        guard let saltData = Data(base64Encoded: envelope.salt),
              let combined = Data(base64Encoded: envelope.ciphertext) else {
            throw BackupCryptoError.invalidFormat
        }
        let key = try deriveKey(from: password, salt: [UInt8](saltData))
        do {
            return try AES.GCM.open(try AES.GCM.SealedBox(combined: combined), using: key)
        } catch {
            throw BackupCryptoError.wrongPassword
        }
    }

    private static func deriveKey(from password: String, salt: [UInt8]) throws -> SymmetricKey {
        let passwordData = Data(password.utf8)
        var derivedBytes = [UInt8](repeating: 0, count: 32)
        let status: Int32 = passwordData.withUnsafeBytes { pwPtr in
            salt.withUnsafeBytes { saltPtr in
                CCKeyDerivationPBKDF(
                    CCPBKDFAlgorithm(kCCPBKDF2),
                    pwPtr.baseAddress?.assumingMemoryBound(to: Int8.self),
                    passwordData.count,
                    saltPtr.baseAddress?.assumingMemoryBound(to: UInt8.self),
                    salt.count,
                    CCPseudoRandomAlgorithm(kCCPRFHmacAlgSHA256),
                    100_000,
                    &derivedBytes,
                    derivedBytes.count
                )
            }
        }
        guard status == kCCSuccess else { throw BackupCryptoError.keyDerivationFailed }
        return SymmetricKey(data: Data(derivedBytes))
    }

    // MARK: Restore

    @MainActor
    static func apply(_ backup: AppBackup, options: RestoreOptions) {
        let ud = UserDefaults.standard
        let db = DatabaseManager.shared

        // 1. App settings
        if options.appSettings {
            let s = backup.appSettings
            ud.set(s.appTheme,       forKey: "app.theme")
            ud.set(s.graphStartMode, forKey: "graph.startMode")
            ud.set(s.sliderMode,     forKey: "slider.mode")
            ud.set(s.showGrouping,         forKey: "processmap.showGrouping")
            ud.set(s.showNodeDescriptions, forKey: "processmap.showNodeDescriptions")
            ud.set(s.kpiExpanded,    forKey: "processmap.kpiExpanded")
            ud.set(s.valveOpen,      forKey: "abComparison.valveOpen")
            ud.set(s.sidebarProjectsExpanded,           forKey: "sidebar.projectsExpanded")
            ud.set(s.sidebarFiltersExpanded,            forKey: "sidebar.filtersExpanded")
            ud.set(s.sidebarFiltersDateExpanded,        forKey: "sidebar.filtersDateExpanded")
            ud.set(s.sidebarFiltersMetaExpanded,        forKey: "sidebar.filtersMetaExpanded")
            ud.set(s.sidebarFiltersIncludeExpanded,     forKey: "sidebar.filtersIncludeExpanded")
            ud.set(s.sidebarFiltersExcludeExpanded,     forKey: "sidebar.filtersExcludeExpanded")
            ud.set(s.sidebarFiltersStepsExpanded,       forKey: "sidebar.filtersStepsExpanded")
            ud.set(s.sidebarFiltersJourneyTimeExpanded, forKey: "sidebar.filtersJourneyTimeExpanded")
            ud.set(s.sidebarFiltersScoreExpanded,       forKey: "sidebar.filtersScoreExpanded")
            ud.set(s.sidebarMetricsExpanded,            forKey: "sidebar.metricsExpanded")
            ud.set(s.sidebarConfigExpanded,             forKey: "sidebar.configExpanded")
            ud.set(s.sidebarConfigStepsExpanded,        forKey: "sidebar.configStepsExpanded")
        }

        // 2. Connections — merge by ID. Each combined backup record is split into a
        //    database server (id = record id, so the password key stays valid), an
        //    optional LLM server, and a connection pairing. Existing items not present
        //    in the backup are kept.
        if options.connections {
            for bp in backup.connections {
                guard let uuid = UUID(uuidString: bp.id) else { continue }
                let existingProfile = db.profiles.first(where: { $0.id == uuid })

                // Database server (id == connection id)
                let existingDB = db.databaseServers.first(where: { $0.id == uuid })
                var dbServer = existingDB ?? DatabaseServer()
                dbServer.id                = uuid
                dbServer.name              = bp.name.isEmpty ? bp.host : bp.name
                dbServer.comment           = bp.comment ?? existingDB?.comment ?? ""
                dbServer.host              = bp.host
                dbServer.port              = bp.port
                dbServer.username          = (options.username ? bp.username : nil) ?? existingDB?.username ?? ""
                dbServer.schema            = bp.schema
                dbServer.useTLS            = bp.useTLS
                dbServer.certModeRaw       = bp.certModeRaw
                dbServer.fingerprint       = bp.fingerprint
                dbServer.minRSAKeySizeBits = bp.minRSAKeySizeBits ?? existingDB?.minRSAKeySizeBits ?? 2048
                let pw = options.passwords ? bp.password : nil
                if existingDB != nil {
                    db.updateDatabaseServer(dbServer, password: pw)
                } else {
                    db.addDatabaseServer(dbServer, password: pw ?? "")
                }

                // LLM server (optional) — reuse the pairing's existing LLM server if any
                var llmId: UUID? = existingProfile?.llmServerId
                if !bp.llmServerURL.isEmpty {
                    let existingLLM = llmId.flatMap { id in db.llmServers.first(where: { $0.id == id }) }
                    var llm = existingLLM ?? LLMServer()
                    llm.name      = (existingLLM?.name.isEmpty == false)
                        ? existingLLM!.name
                        : (bp.name.isEmpty ? "LLM" : "\(bp.name) LLM")
                    llm.serverURL = bp.llmServerURL
                    llm.apiKey    = (options.llmApiKey ? bp.llmApiKey : nil) ?? existingLLM?.apiKey ?? ""
                    llm.model     = bp.llmModel
                    if existingLLM != nil { db.updateLLMServer(llm) } else { db.addLLMServer(llm) }
                    llmId = llm.id
                }

                // Connection pairing
                var profile = existingProfile ?? ConnectionProfile()
                profile.id               = uuid
                profile.name             = bp.name
                profile.comment          = bp.comment ?? existingProfile?.comment ?? ""
                profile.databaseServerId = dbServer.id
                profile.llmServerId      = llmId
                if existingProfile != nil { db.updateProfile(profile) } else { db.addProfile(profile) }
            }

            // Restore active profile (only if the profile exists after merge)
            if let idStr = backup.activeProfileId,
               let uuid  = UUID(uuidString: idStr),
               db.profiles.contains(where: { $0.id == uuid }) {
                db.activeProfileId = uuid
                ud.set(uuid.uuidString, forKey: "active_profile_id")
            }
        }

        // 3. Dynamic string defaults (norms_metric_*, llm_prompt_*)
        for (key, value) in backup.stringDefaults {
            if key.hasPrefix("norms_metric_") { guard options.norms         else { continue } }
            // llm_prompt_* follows the norms toggle (per-project AI settings)
            if key.hasPrefix("llm_prompt_")   { guard options.norms         else { continue } }
            ud.set(value, forKey: key)
        }

        // 4. Dynamic data defaults (layout_*, graph.collapsedGroups_*, norms_*, happyPaths_*, filterGroups_*)
        for (key, b64) in backup.dataDefaults {
            if key.hasPrefix("layout_") || key.hasPrefix("graph.collapsedGroups_") {
                guard options.layouts       else { continue }
            } else if key.hasPrefix("norms_") {
                guard options.norms         else { continue }
            } else if key.hasPrefix("happyPaths_") {
                guard options.happyPaths    else { continue }
            } else if key.hasPrefix("filterGroups_") {
                guard options.filterPresets else { continue }
            }
            if let data = Data(base64Encoded: b64) {
                ud.set(data, forKey: key)
            }
        }

        ud.synchronize()
    }
}
