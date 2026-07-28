import SwiftUI

// MARK: - App alert model

struct AppAlert: Identifiable {
    struct Button {
        let label:  String
        let role:   ButtonRole?
        let action: (() -> Void)?

        static let ok     = Button(label: "OK",     role: nil,     action: nil)
        static let cancel = Button(label: "Cancel", role: .cancel, action: nil)
    }

    let id       = UUID()
    let title:   String
    let message: String
    let primary:   Button
    let secondary: Button?

    // Convenience: informational alert, no retry
    static func info(title: String, message: String) -> AppAlert {
        AppAlert(title: title, message: message, primary: .ok, secondary: nil)
    }

    // Convenience: error with optional retry closure
    static func error(title: String, message: String, retry: (() -> Void)? = nil) -> AppAlert {
        if let retry {
            return AppAlert(
                title: title, message: message,
                primary:   Button(label: "Retry",  role: nil,     action: retry),
                secondary: Button(label: "Cancel", role: .cancel, action: nil)
            )
        }
        return AppAlert(title: title, message: message, primary: .ok, secondary: nil)
    }
}

// MARK: - Database server definition

/// A reusable Exasol database server definition. Managed in the Settings window
/// and referenced by one or more connections. The password is stored separately
/// (keyed by this server's `id`) in `DatabaseManager`.
struct DatabaseServer: Identifiable, Codable, Equatable {
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
}

// MARK: - LLM server definition

/// A reusable LLM (OpenAI-compatible) server definition. Managed in the Settings
/// window and optionally referenced by a connection.
struct LLMServer: Identifiable, Codable, Equatable {
    var id        = UUID()
    var name:     String = ""
    var comment:  String = ""
    var serverURL: String = ""
    var apiKey:    String = ""
    var model:     String = ""
}

// MARK: - Connection profile

/// A connection is a lightweight *pairing* of a database server with an optional
/// LLM server. The actual server details live in `DatabaseServer` / `LLMServer`
/// definitions referenced by id.
struct ConnectionProfile: Identifiable, Codable, Equatable {
    var id       = UUID()
    var name:    String = ""
    var comment: String = ""
    var databaseServerId: UUID?
    var llmServerId:      UUID?
}

// MARK: - Project

struct Project: Identifiable, Hashable, Equatable, Sendable {
    var id: String { projectId }
    let projectId: String
    let title: String
    let description: String
}

struct StepInfo: Identifiable, Equatable, Sendable {
    var id: String { step }
    let step: String
    let description: String
    let bgColor: String
    let fgColor: String
    let score: Int?
    let shape: String
    let endOfProcess: Bool
    let belongsTo: String?
    var eventTime: Date? = nil   // populated only for individual journey graphs

    var backgroundColor: Color { Color.named(bgColor) }
    var foregroundColor: Color  { Color.named(fgColor) }
}

struct ProcessTransition: Identifiable, Equatable, Sendable {
    var id: String { "\(fromStep)->\(toStep)" }
    let fromStep:    String
    let toStep:      String
    let occurrences: Int
    let avgSecs:     Double?
    let minSecs:     Double?
    let maxSecs:     Double?
    let stdDevSecs:  Double?

    func metricValue(for metric: TransitionMetric) -> Double? {
        switch metric {
        case .count:   return Double(occurrences)
        case .avgTime: return avgSecs
        case .minTime: return minSecs
        case .maxTime: return maxSecs
        case .stdDev:  return stdDevSecs
        }
    }
}

// MARK: - Statistics

struct JourneyTimePoint: Identifiable, Sendable {
    let id    = UUID()
    let date:  Date
    let count: Int
}

enum TimeGranularity: Sendable {
    case day, week, month

    static func auto(from: Date, to: Date) -> TimeGranularity {
        let days = Calendar.current.dateComponents([.day], from: from, to: to).day ?? 0
        if days <= 14 { return .day }
        if days <= 90 { return .week }
        return .month
    }

    var label: String {
        switch self {
        case .day:   return "Daily"
        case .week:  return "Weekly"
        case .month: return "Monthly"
        }
    }
}

// MARK: - Graph initial group-collapse preference

enum GraphStartMode: String, CaseIterable, Identifiable {
    case expanded  = "expanded"
    case collapsed = "collapsed"
    case persisted = "persisted"

    var id: String { rawValue }

    var label: String {
        switch self {
        case .expanded:  return "Expanded"
        case .collapsed: return "Collapsed"
        case .persisted: return "Persisted"
        }
    }
}

// MARK: - KPI ordering

let kpiDefaultOrder = "totalJourneys,filteredJourneys,shortestJourney,avgJourney,stdDev,longestJourney,graphValue,processGoodness,processSimilarity,activeSample"

// MARK: - Edge Color Schema

enum EdgeColorSchema: String, CaseIterable, Identifiable {
    case neutral     = "neutral"
    case greenHigh   = "greenHigh"
    case redHigh     = "redHigh"
    case blueScale   = "blueScale"
    case orangeScale = "orangeScale"
    case purpleScale = "purpleScale"

    var id: String { rawValue }

    var label: String {
        switch self {
        case .neutral:     return "None (grey)"
        case .greenHigh:   return "Green (high is good)"
        case .redHigh:     return "Red (low is good)"
        case .blueScale:   return "Blue scale"
        case .orangeScale: return "Orange scale"
        case .purpleScale: return "Purple scale"
        }
    }

    var gradientColors: (low: Color, high: Color)? {
        switch self {
        case .neutral:     return nil
        case .greenHigh:   return (Color(red: 0.85, green: 0.15, blue: 0.10), Color(red: 0.10, green: 0.75, blue: 0.20))
        case .redHigh:     return (Color(red: 0.10, green: 0.75, blue: 0.20), Color(red: 0.85, green: 0.15, blue: 0.10))
        case .blueScale:   return (Color(red: 0.60, green: 0.82, blue: 1.00), Color(red: 0.05, green: 0.25, blue: 0.80))
        case .orangeScale: return (Color(red: 1.00, green: 0.92, blue: 0.60), Color(red: 0.90, green: 0.38, blue: 0.00))
        case .purpleScale: return (Color(red: 0.82, green: 0.72, blue: 1.00), Color(red: 0.40, green: 0.05, blue: 0.80))
        }
    }

    static func defaultSchema(for metric: TransitionMetric) -> EdgeColorSchema {
        switch metric {
        case .count:   return .greenHigh
        case .avgTime: return .orangeScale
        case .minTime: return .blueScale
        case .maxTime: return .redHigh
        case .stdDev:  return .purpleScale
        }
    }
}

// MARK: - Sample Set

enum SampleSet: String, CaseIterable, Identifiable, Codable {
    case original = "ORIGINAL"
    case sample1  = "SAMPLE_1"
    case sample2  = "SAMPLE_2"
    case sample3  = "SAMPLE_3"

    var id: String { rawValue }

    var label: String {
        switch self {
        case .original: return "Original Data"
        case .sample1:  return "Sample Set 1"
        case .sample2:  return "Sample Set 2"
        case .sample3:  return "Sample Set 3"
        }
    }

    var shortLabel: String {
        switch self {
        case .original: return "Original"
        case .sample1:  return "Sample 1"
        case .sample2:  return "Sample 2"
        case .sample3:  return "Sample 3"
        }
    }

    var isOriginal: Bool { self == .original }

    var sampleNumber: Int? {
        switch self {
        case .original: return nil
        case .sample1:  return 1
        case .sample2:  return 2
        case .sample3:  return 3
        }
    }

    func sqlFragment(alias: String? = nil) -> String {
        let col = alias.map { "\($0).SAMPLE_SET" } ?? "SAMPLE_SET"
        switch self {
        case .original: return "(\(col) = 'ORIGINAL' OR \(col) IS NULL)"
        default:        return "\(col) = '\(rawValue)'"
        }
    }
}

// MARK: - Sampling Method

enum SamplingMethod: String, CaseIterable, Identifiable, Codable {
    case random      = "random"
    case temporal    = "temporal"
    case pathDiverse = "pathDiverse"

    var id: String { rawValue }

    var label: String {
        switch self {
        case .random:      return "Random"
        case .temporal:    return "Temporal Stratified"
        case .pathDiverse: return "Path Diversity"
        }
    }

    var icon: String {
        switch self {
        case .random:      return "shuffle"
        case .temporal:    return "calendar.badge.clock"
        case .pathDiverse: return "arrow.triangle.branch"
        }
    }

    var shortDescription: String {
        switch self {
        case .random:      return "Uniform random selection"
        case .temporal:    return "Proportional across time periods"
        case .pathDiverse: return "Coverage across journey variants"
        }
    }
}

// MARK: - Transition metric

enum TransitionMetric: String, CaseIterable, Identifiable, Codable, Sendable {
    case count   = "Count"
    case avgTime = "Avg Time"
    case minTime = "Min Time"
    case maxTime = "Max Time"
    case stdDev  = "Std Dev"

    var id: String { rawValue }

    var icon: String {
        switch self {
        case .count:   return "number"
        case .avgTime: return "timer"
        case .minTime: return "chevron.down.circle"
        case .maxTime: return "chevron.up.circle"
        case .stdDev:  return "waveform.path"
        }
    }

    var isTimeBased: Bool { self != .count }
}

// MARK: - Filter group (saved filter preset)

struct FilterGroup: Identifiable, Codable {
    var id:             UUID    = UUID()
    var name:           String
    var fromDate:       Date
    var toDate:         Date
    var includedSteps:  [String]
    var excludedSteps:  [String]
    var meta1:          String
    var meta2:          String
    var meta3:          String
    var minSteps:       Int
    var maxSteps:       Int
    var minJourneyTime: Int
    var maxJourneyTime: Int
    var minScore:       Int
    var maxScore:       Int
}

// MARK: - Happy Path definition

struct HappyPathBranch: Identifiable, Codable {
    var id:    UUID     = UUID()
    var label: String   = ""
    var steps: [String] = []
}

struct HappyPath: Identifiable, Codable {
    var id:       UUID              = UUID()
    var name:     String
    var steps:    [String]
    var branches: [HappyPathBranch] = []

    // Custom decoder so existing saved paths (without "branches") still load correctly.
    init(id: UUID = UUID(), name: String, steps: [String] = [], branches: [HappyPathBranch] = []) {
        self.id = id; self.name = name; self.steps = steps; self.branches = branches
    }

    init(from decoder: Decoder) throws {
        let c    = try decoder.container(keyedBy: CodingKeys.self)
        id       = try c.decode(UUID.self,     forKey: .id)
        name     = try c.decode(String.self,   forKey: .name)
        steps    = try c.decode([String].self, forKey: .steps)
        branches = (try? c.decode([HappyPathBranch].self, forKey: .branches)) ?? []
    }

    enum CodingKeys: String, CodingKey { case id, name, steps, branches }
}

struct JourneyPath: Identifiable, Sendable {
    let id           = UUID()
    let path:         String
    let journeyCount: Int
    let stepCount:    Int
    let totalScore:   Int

    var aggregatedScore: Int { totalScore * journeyCount }
}

struct DurationBucket: Identifiable, Sendable {
    var id: String { label }
    let label: String
    let count: Int
}

struct ProcessGraph: Sendable, Equatable {
    let steps: [String: StepInfo]
    let transitions: [ProcessTransition]

    var maxOccurrences: Int { transitions.map(\.occurrences).max() ?? 1 }

    func maxValue(for metric: TransitionMetric) -> Double {
        let vals = transitions.compactMap { $0.metricValue(for: metric) }
        return vals.max() ?? 1
    }

    static let empty = ProcessGraph(steps: [:], transitions: [])
}

// MARK: - Filter snapshot (captured when a note is created)

struct FilterSnapshot: Codable, Equatable {
    let fromDate:          Date
    let toDate:            Date
    let includedSteps:     [String]
    let excludedSteps:     [String]
    let meta1:             String
    let meta2:             String
    let meta3:             String
    let minSteps:          Int
    let maxSteps:          Int
    let minJourneyTime:    Int
    let maxJourneyTime:    Int
    let minScore:          Int
    let maxScore:          Int

    var summaryText: String {
        let df = DateFormatter(); df.dateStyle = .short; df.timeStyle = .none
        var parts = ["\(df.string(from: fromDate)) – \(df.string(from: toDate))"]
        if !includedSteps.isEmpty { parts.append("include: \(includedSteps.joined(separator: ", "))") }
        if !excludedSteps.isEmpty { parts.append("exclude: \(excludedSteps.joined(separator: ", "))") }
        if !meta1.isEmpty { parts.append("M1: \(meta1)") }
        if !meta2.isEmpty { parts.append("M2: \(meta2)") }
        if !meta3.isEmpty { parts.append("M3: \(meta3)") }
        if minJourneyTime > 0 || maxJourneyTime < Int.max { parts.append("journey time filter") }
        if minSteps > 0       || maxSteps < Int.max       { parts.append("step count filter") }
        if minScore > Int.min || maxScore < Int.max       { parts.append("score filter") }
        return parts.joined(separator: " · ")
    }
}

// MARK: - Process note (sticky-note annotation on a node or edge)

struct ProcessNote: Identifiable, Codable, Equatable {
    var id             = UUID()
    var text:          String
    var createdAt:     Date           = Date()
    var editedAt:      Date?          = nil
    var target:        NoteTarget
    var filterSnapshot: FilterSnapshot
    var username:      String         = ""
    var lastEditedBy:  String         = ""
    var isShared:      Bool           = false

    enum NoteTarget: Codable, Equatable {
        case node(String)
        case edge(from: String, to: String)

        var displayName: String {
            switch self {
            case .node(let n):        return n
            case .edge(let f, let t): return "\(f) → \(t)"
            }
        }
        var isNode: Bool { if case .node = self { return true }; return false }

        // Manual Codable because associated-value enums need it
        enum CodingKeys: String, CodingKey { case type, value, from, to }
        init(from decoder: Decoder) throws {
            let c    = try decoder.container(keyedBy: CodingKeys.self)
            let type = try c.decode(String.self, forKey: .type)
            if type == "edge" {
                self = .edge(from: try c.decode(String.self, forKey: .from),
                             to:   try c.decode(String.self, forKey: .to))
            } else {
                self = .node(try c.decode(String.self, forKey: .value))
            }
        }
        func encode(to encoder: Encoder) throws {
            var c = encoder.container(keyedBy: CodingKeys.self)
            switch self {
            case .node(let v):
                try c.encode("node", forKey: .type); try c.encode(v, forKey: .value)
            case .edge(let f, let t):
                try c.encode("edge", forKey: .type)
                try c.encode(f, forKey: .from); try c.encode(t, forKey: .to)
            }
        }
    }
}

// MARK: - Simulation Slot

enum SimSlot: String, CaseIterable, Identifiable {
    case simA = "Sim-A"
    case simB = "Sim-B"
    var id: String { rawValue }
}

// MARK: - A/B Data Source

enum ABDataSource: Equatable {
    case sampleSet(SampleSet)
    case simulation(SimSlot)

    var shortLabel: String {
        switch self {
        case .sampleSet(let s): return s.shortLabel
        case .simulation(let s): return s.rawValue
        }
    }

    var sampleSet: SampleSet? {
        if case .sampleSet(let s) = self { return s }
        return nil
    }

    var simSlot: SimSlot? {
        if case .simulation(let s) = self { return s }
        return nil
    }
}

extension Color {
    static func named(_ name: String) -> Color {
        switch name.lowercased() {
        case "red":          return .red
        case "green":        return .green
        case "blue":         return .blue
        case "yellow":       return .yellow
        case "orange":       return .orange
        case "purple":       return .purple
        case "gray", "grey": return .gray
        case "black":        return .black
        case "white":        return .white
        case "cyan":         return .cyan
        case "mint":         return .mint
        case "teal":         return .teal
        case "indigo":       return .indigo
        case "pink":         return .pink
        case "brown":        return .brown
        default:
            let hex = name.trimmingCharacters(in: CharacterSet.alphanumerics.inverted)
            var int: UInt64 = 0
            guard Scanner(string: hex).scanHexInt64(&int), hex.count == 6 else { return .accentColor }
            return Color(
                red:   Double((int >> 16) & 0xFF) / 255,
                green: Double((int >> 8)  & 0xFF) / 255,
                blue:  Double(int         & 0xFF) / 255
            )
        }
    }

    // Returns a 6-digit uppercase hex string (no #), e.g. "FF8000"
    var hexString: String {
        let c = rgbaComponents
        return String(format: "%02X%02X%02X",
                      Int((c.red * 255).rounded()),
                      Int((c.green * 255).rounded()),
                      Int((c.blue * 255).rounded()))
    }
}
