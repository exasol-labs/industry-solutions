import Foundation
import Combine
import CryptoKit
import SwiftUI

final class AppViewModel: ObservableObject {
    // MARK: - Project-level state (shared across all chart views)
    @Published var projects:          [Project]          = []
    @Published var selectedProject:   Project?
    @Published var isLoading                             = false
    @Published var errorMessage:      String?
    @Published var pendingAlert:      AppAlert?
    @Published var allSteps:          [String]           = []
    @Published var allStepInfos:      [String: StepInfo] = [:]
    @Published var meta1Title:        String?            = nil
    @Published var meta2Title:        String?            = nil
    @Published var meta3Title:        String?            = nil
    @Published var meta1Values:       [String]           = []
    @Published var meta2Values:       [String]           = []
    @Published var meta3Values:       [String]           = []
    @Published var totalJourneyCount: Int?               = nil
    @Published private(set) var initialFromDate: Date    = Date()
    @Published private(set) var initialToDate:   Date    = Date()
    @Published private(set) var projectMinDate:  Date    = Date()

    // MARK: - Chart-view selection
    @Published var activeChartMode: DetailViewMode = .aChart

    // MARK: - LLM analysis state
    @Published var isLLMAnalyzing:      Bool    = false
    @Published var llmAnalysisResult:   String? = nil
    @Published var llmAnalysisError:    String? = nil
    @Published var lastSentLLMPrompt:   String? = nil
    @Published var llmAnalysisModel:    String? = nil
    @Published var llmAnalysisDate:     Date?   = nil
    @Published var llmHappyPathSummary:       String = ""
    @Published var llmConformanceSummary:     String = ""
    @Published var llmJourneyPathsSummary:    String = ""
    @Published var llmPromptTemplate: String  = AppViewModel.defaultLLMPrompt {
        didSet {
            guard let id = selectedProject?.projectId else { return }
            UserDefaults.standard.set(llmPromptTemplate, forKey: "llm_prompt_\(id)")
        }
    }

    static let defaultLLMPrompt =
        "Analyze the transitions table and identify outliers, min, max, avg values for transitions. Use project name as a title, make a decent layout."

    // MARK: - Sampling state
    @AppStorage("sampling.activeSampleSetA") var activeSampleSetARaw: String = "ORIGINAL"
    @AppStorage("sampling.activeSampleSetB") var activeSampleSetBRaw: String = "ORIGINAL"
    @Published var sampleCounts: [SampleSet: Int] = [:]
    @Published var sampleMethods: [SampleSet: SamplingMethod] = [:]
    @Published var isSampling: Bool = false
    @Published var samplingError: String? = nil
    @Published var samplingProgress: String? = nil

    var activeSampleSetA: SampleSet {
        get { SampleSet(rawValue: activeSampleSetARaw) ?? .original }
        set { activeSampleSetARaw = newValue.rawValue }
    }

    var activeSampleSetB: SampleSet {
        get { SampleSet(rawValue: activeSampleSetBRaw) ?? .original }
        set { activeSampleSetBRaw = newValue.rawValue }
    }

    // A-Chart set is the "primary" set used by statistics, happy path, and journey views.
    var activeSampleSet: SampleSet {
        get { activeSampleSetA }
        set { activeSampleSetA = newValue }
    }

    // MARK: - Statistics state
    @Published var statisticsPaths:      [JourneyPath]    = []
    @Published var statsDurationBuckets: [DurationBucket] = []
    @Published var statsProcessGraph:    ProcessGraph     = .empty
    @Published var isLoadingStats        = false
    @Published var statisticsIsTruncated = false
    @Published var statsErrorMessage:    String?       = nil
    @Published var statsRouteLimit:      Int             = 500
    @Published var statsTimeSeries:      [JourneyTimePoint] = []
    @Published var statsTimeGranularity: TimeGranularity    = .month
    private var statsGeneration              = 0
    @Published var statsLoadedSnapshot: FilterSnapshot? = nil
    @Published var processGoodnessScore: Double? = nil
    @Published var abGoodnessA:           Double? = nil
    @Published var abGoodnessB:           Double? = nil
    @Published var abVariantsA:           [JourneyPath] = []
    @Published var abVariantsB:           [JourneyPath] = []
    @Published var abSimilarityScore:     Double? = nil

    private let abSimilarityVariantLimit = 500

    // MARK: - Happy Path
    @Published var happyPaths:          [HappyPath] = []
    @Published var selectedHappyPathId: UUID?       = nil
    @Published var happyPathScore:      Double?     = nil

    var selectedHappyPath: HappyPath? {
        guard let id = selectedHappyPathId else { return nil }
        return happyPaths.first { $0.id == id }
    }

    // MARK: - Target process / compliance norms
    // Outer key: TransitionMetric.rawValue  Inner key: edge id  Value: norm
    @Published var targetNorms:  [String: [String: Double]] = [:]
    @Published var targetMetric: TransitionMetric           = .count

    /// Norms for the currently selected metric, ready for use by chart/table views.
    var currentMetricNorms: [String: Double] { targetNorms[targetMetric.rawValue] ?? [:] }

    func loadNorms(for projectId: String) {
        if let data = UserDefaults.standard.data(forKey: "norms_\(projectId)") {
            if let decoded = try? JSONDecoder().decode([String: [String: Double]].self, from: data) {
                targetNorms = decoded
            } else if let legacy = try? JSONDecoder().decode([String: Double].self, from: data) {
                // Migrate old flat format: put all norms under the stored metric
                let metricKey = UserDefaults.standard.string(forKey: "norms_metric_\(projectId)")
                                ?? TransitionMetric.count.rawValue
                targetNorms = [metricKey: legacy]
                if let newData = try? JSONEncoder().encode(targetNorms) {
                    UserDefaults.standard.set(newData, forKey: "norms_\(projectId)")
                }
            } else {
                targetNorms = [:]
            }
        } else {
            targetNorms = [:]
        }
        if let raw    = UserDefaults.standard.string(forKey: "norms_metric_\(projectId)"),
           let metric = TransitionMetric(rawValue: raw) {
            targetMetric = metric
        } else {
            targetMetric = .count
        }
    }

    func saveNorm(_ value: Double?, forEdge edge: String) {
        guard let projectId = selectedProject?.projectId else { return }
        let key = targetMetric.rawValue
        var metricNorms = targetNorms[key] ?? [:]
        if let value { metricNorms[edge] = value } else { metricNorms.removeValue(forKey: edge) }
        if metricNorms.isEmpty { targetNorms.removeValue(forKey: key) }
        else                   { targetNorms[key] = metricNorms }
        if let data = try? JSONEncoder().encode(targetNorms) {
            UserDefaults.standard.set(data, forKey: "norms_\(projectId)")
        }
    }

    func setTargetMetric(_ metric: TransitionMetric) {
        guard let projectId = selectedProject?.projectId else { return }
        targetMetric = metric
        UserDefaults.standard.set(metric.rawValue, forKey: "norms_metric_\(projectId)")
    }

    // MARK: - Filter Groups

    @Published var filterGroups:          [FilterGroup] = []
    @Published var selectedFilterGroupId: UUID?         = nil
    @Published var abFilterGroupIdA:      UUID?         = nil
    @Published var abFilterGroupIdB:      UUID?         = nil

    var selectedFilterGroup: FilterGroup? {
        guard let id = selectedFilterGroupId else { return nil }
        return filterGroups.first { $0.id == id }
    }

    func loadFilterGroups(for projectId: String) {
        if let data    = UserDefaults.standard.data(forKey: "filterGroups_\(projectId)"),
           let decoded = try? JSONDecoder().decode([FilterGroup].self, from: data) {
            filterGroups = decoded
        } else {
            filterGroups = []
        }
        selectedFilterGroupId = nil
    }

    private func saveFilterGroups() {
        guard let projectId = selectedProject?.projectId else { return }
        if let data = try? JSONEncoder().encode(filterGroups) {
            UserDefaults.standard.set(data, forKey: "filterGroups_\(projectId)")
        }
    }

    func createFilterGroup(name: String) {
        let group = FilterGroup(
            name:           name.isEmpty ? "Preset \(filterGroups.count + 1)" : name,
            fromDate:       fromDate,
            toDate:         toDate,
            includedSteps:  Array(includedSteps),
            excludedSteps:  Array(excludedSteps),
            meta1:          meta1Filter,
            meta2:          meta2Filter,
            meta3:          meta3Filter,
            minSteps:       minStepsFilter,
            maxSteps:       maxStepsFilter,
            minJourneyTime: minJourneyTimeFilter,
            maxJourneyTime: maxJourneyTimeFilter,
            minScore:       minScoreFilter,
            maxScore:       maxScoreFilter
        )
        filterGroups.append(group)
        selectedFilterGroupId = group.id
        saveFilterGroups()
    }

    func deleteFilterGroup(id: UUID) {
        filterGroups.removeAll { $0.id == id }
        if selectedFilterGroupId == id { selectedFilterGroupId = nil }
        saveFilterGroups()
    }

    func renameFilterGroup(id: UUID, name: String) {
        guard let idx = filterGroups.firstIndex(where: { $0.id == id }) else { return }
        filterGroups[idx].name = name
        saveFilterGroups()
    }

    func applyFilterGroup(_ group: FilterGroup) {
        selectedFilterGroupId = group.id
        fromDate             = group.fromDate
        toDate               = group.toDate
        includedSteps        = Set(group.includedSteps)
        excludedSteps        = Set(group.excludedSteps)
        meta1Filter          = group.meta1
        meta2Filter          = group.meta2
        meta3Filter          = group.meta3
        minStepsFilter       = group.minSteps
        maxStepsFilter       = group.maxSteps
        minJourneyTimeFilter = group.minJourneyTime
        maxJourneyTimeFilter = group.maxJourneyTime
        minScoreFilter       = group.minScore
        maxScoreFilter       = group.maxScore
    }

    // MARK: - Happy Path persistence + mutation

    func loadHappyPaths(for projectId: String) {
        if let data    = UserDefaults.standard.data(forKey: "happyPaths_\(projectId)"),
           let decoded = try? JSONDecoder().decode([HappyPath].self, from: data) {
            happyPaths = decoded
        } else {
            happyPaths = []
        }
        selectedHappyPathId = happyPaths.first?.id
    }

    private func saveHappyPaths() {
        guard let projectId = selectedProject?.projectId else { return }
        if let data = try? JSONEncoder().encode(happyPaths) {
            UserDefaults.standard.set(data, forKey: "happyPaths_\(projectId)")
        }
    }

    func createHappyPath(name: String) {
        let path = HappyPath(name: name.isEmpty ? "Happy Path \(happyPaths.count + 1)" : name, steps: [])
        happyPaths.append(path)
        selectedHappyPathId = path.id
        saveHappyPaths()
    }

    func deleteHappyPath(id: UUID) {
        happyPaths.removeAll { $0.id == id }
        if selectedHappyPathId == id {
            selectedHappyPathId = happyPaths.first?.id
        }
        happyPathScore = nil
        saveHappyPaths()
    }

    func renameHappyPath(id: UUID, name: String) {
        guard let idx = happyPaths.firstIndex(where: { $0.id == id }) else { return }
        happyPaths[idx].name = name
        saveHappyPaths()
    }

    func selectHappyPath(id: UUID) {
        selectedHappyPathId = id
    }

    func addHappyPathStep(toPath pathId: UUID, step: String) {
        guard let idx = happyPaths.firstIndex(where: { $0.id == pathId }),
              !happyPaths[idx].steps.contains(step) else { return }
        happyPaths[idx].steps.append(step)
        saveHappyPaths()
    }

    func removeHappyPathSteps(pathId: UUID, at offsets: IndexSet) {
        guard let idx = happyPaths.firstIndex(where: { $0.id == pathId }) else { return }
        happyPaths[idx].steps = happyPaths[idx].steps.enumerated()
            .filter { !offsets.contains($0.offset) }
            .map(\.element)
        saveHappyPaths()
    }

    func moveHappyPathSteps(pathId: UUID, from source: IndexSet, to destination: Int) {
        guard let idx = happyPaths.firstIndex(where: { $0.id == pathId }) else { return }
        let moved = source.map { happyPaths[idx].steps[$0] }
        var arr = happyPaths[idx].steps
        for i in source.sorted().reversed() { arr.remove(at: i) }
        let insertAt = destination - source.filter { $0 < destination }.count
        arr.insert(contentsOf: moved, at: max(0, min(insertAt, arr.count)))
        happyPaths[idx].steps = arr
        saveHappyPaths()
    }

    // MARK: - Happy Path conformance

    func refreshHappyPathConformance() async {
        guard let project = selectedProject else { return }
        guard let path = selectedHappyPath, path.steps.count >= 2 else {
            happyPathScore = nil; return
        }
        syncSampleSet()
        let variants = (try? await repo.loadJourneyPaths(
            projectId: project.projectId,
            from: fromDate, to: toDate,
            included: Array(includedSteps), excluded: Array(excludedSteps),
            meta1: meta1Filter, meta2: meta2Filter, meta3: meta3Filter,
            minSteps: minStepsFilter, maxSteps: maxStepsFilter,
            minJourneyTime: minJourneyTimeFilter, maxJourneyTime: maxJourneyTimeFilter,
            minScore: minScoreFilter, maxScore: maxScoreFilter,
            limit: 500
        )) ?? []
        happyPathScore = computeHappyPathConformance(path: path, variants: variants)
    }

    private func computeHappyPathConformance(path: HappyPath, variants: [JourneyPath]) -> Double? {
        guard path.steps.count >= 2, !variants.isEmpty else { return nil }
        // Build one complete path per non-empty branch; if no branches, use trunk only.
        let nonEmptyBranches = path.branches.filter { !$0.steps.isEmpty }
        let completePaths: [[String]] = nonEmptyBranches.isEmpty
            ? [path.steps]
            : nonEmptyBranches.map { path.steps + $0.steps }.filter { $0.count >= 2 }
        guard !completePaths.isEmpty else { return nil }

        let pathEdgeSets = completePaths.map { steps in
            Set(zip(steps, steps.dropFirst()).map { "\($0) -> \($1)" })
        }
        var weightedSum = 0.0
        var totalCount  = 0
        for v in variants {
            let vSteps = v.path.components(separatedBy: " -> ")
            let vEdges = Set(zip(vSteps, vSteps.dropFirst()).map { "\($0) -> \($1)" })
            // A journey is scored against the branch it matches best.
            let coverage = pathEdgeSets.map { edges in
                Double(edges.intersection(vEdges).count) / Double(edges.count)
            }.max() ?? 0
            weightedSum += Double(v.journeyCount) * coverage
            totalCount  += v.journeyCount
        }
        guard totalCount > 0 else { return nil }
        return weightedSum / Double(totalCount)
    }

    // MARK: - Happy Path branch management

    func addHappyPathBranch(pathId: UUID) {
        guard let idx = happyPaths.firstIndex(where: { $0.id == pathId }) else { return }
        happyPaths[idx].branches.append(HappyPathBranch())
        saveHappyPaths()
    }

    func removeHappyPathBranch(pathId: UUID, branchId: UUID) {
        guard let idx = happyPaths.firstIndex(where: { $0.id == pathId }) else { return }
        happyPaths[idx].branches.removeAll { $0.id == branchId }
        saveHappyPaths()
    }

    func renameHappyPathBranch(pathId: UUID, branchId: UUID, label: String) {
        guard let pi = happyPaths.firstIndex(where: { $0.id == pathId }),
              let bi = happyPaths[pi].branches.firstIndex(where: { $0.id == branchId }) else { return }
        happyPaths[pi].branches[bi].label = label
        saveHappyPaths()
    }

    func addStepToBranch(pathId: UUID, branchId: UUID, step: String) {
        guard let pi = happyPaths.firstIndex(where: { $0.id == pathId }),
              let bi = happyPaths[pi].branches.firstIndex(where: { $0.id == branchId }) else { return }
        happyPaths[pi].branches[bi].steps.append(step)
        saveHappyPaths()
    }

    func removeStepsFromBranch(pathId: UUID, branchId: UUID, at offsets: IndexSet) {
        guard let pi = happyPaths.firstIndex(where: { $0.id == pathId }),
              let bi = happyPaths[pi].branches.firstIndex(where: { $0.id == branchId }) else { return }
        happyPaths[pi].branches[bi].steps = happyPaths[pi].branches[bi].steps.enumerated()
            .filter { !offsets.contains($0.offset) }.map(\.element)
        saveHappyPaths()
    }

    func moveStepsInBranch(pathId: UUID, branchId: UUID, from source: IndexSet, to destination: Int) {
        guard let pi = happyPaths.firstIndex(where: { $0.id == pathId }),
              let bi = happyPaths[pi].branches.firstIndex(where: { $0.id == branchId }) else { return }
        let moved = source.map { happyPaths[pi].branches[bi].steps[$0] }
        var arr = happyPaths[pi].branches[bi].steps
        for i in source.sorted().reversed() { arr.remove(at: i) }
        let insertAt = destination - source.filter { $0 < destination }.count
        arr.insert(contentsOf: moved, at: max(0, min(insertAt, arr.count)))
        happyPaths[pi].branches[bi].steps = arr
        saveHappyPaths()
    }

    // MARK: - Notes (stored in NOTES table of the connected database)

    @Published var projectNotes: [ProcessNote] = []

    func loadNotes(for projectId: String) async {
        try? await repo.ensureNotesTable()
        let username = DatabaseManager.shared.activeDatabaseServer?.username ?? ""
        projectNotes = (try? await repo.loadNotes(projectId: projectId, username: username)) ?? []
    }

    func setNote(_ note: ProcessNote) async {
        guard let projectId = selectedProject?.projectId else { return }
        var updatedNote = note
        let currentUser = DatabaseManager.shared.activeDatabaseServer?.username ?? ""

        if let existingIdx = projectNotes.firstIndex(where: { $0.id == note.id }) {
            // Editing: preserve the original author, record who made this edit
            updatedNote.username     = projectNotes[existingIdx].username
            updatedNote.lastEditedBy = currentUser
            projectNotes[existingIdx] = updatedNote
        } else {
            // New note: stamp author, no editor yet
            updatedNote.username     = currentUser
            updatedNote.lastEditedBy = ""
            projectNotes.append(updatedNote)
        }

        // Persist to database (best-effort: create table if missing, then upsert)
        do {
            try? await repo.ensureNotesTable()
            try await repo.upsertNote(updatedNote, projectId: projectId)
        } catch {
            let msg = "Note saved locally but could not be written to the database: \(error.localizedDescription)"
            errorMessage = msg
            pendingAlert = AppAlert.info(title: "Note Not Synced", message: msg)
        }
    }

    func deleteNote(_ note: ProcessNote) async {
        guard let projectId = selectedProject?.projectId else { return }
        projectNotes.removeAll { $0.id == note.id }
        try? await repo.deleteNote(id: note.id, projectId: projectId)
    }

    func currentFilterSnapshot() -> FilterSnapshot {
        FilterSnapshot(
            fromDate:       fromDate,
            toDate:         toDate,
            includedSteps:  Array(includedSteps),
            excludedSteps:  Array(excludedSteps),
            meta1:          meta1Filter,
            meta2:          meta2Filter,
            meta3:          meta3Filter,
            minSteps:       minStepsFilter,
            maxSteps:       maxStepsFilter,
            minJourneyTime: minJourneyTimeFilter,
            maxJourneyTime: maxJourneyTimeFilter,
            minScore:       minScoreFilter,
            maxScore:       maxScoreFilter
        )
    }

    // MARK: - A/B Comparison split state
    @Published var abActiveSide:     ABSide       = .a
    @Published private(set) var isLoadingA = false
    @Published private(set) var isLoadingB = false
    @Published var abGraphA:         ProcessGraph = .empty
    @Published var abGraphB:         ProcessGraph = .empty
    @Published var abJourneyCountA:  Int?         = nil
    @Published var abJourneyCountB:  Int?         = nil
    @Published var abMinDurationA:    Double?      = nil
    @Published var abAvgDurationA:    Double?      = nil
    @Published var abStdDevDurationA: Double?      = nil
    @Published var abMaxDurationA:    Double?      = nil
    @Published var abMinDurationB:    Double?      = nil
    @Published var abAvgDurationB:    Double?      = nil
    @Published var abStdDevDurationB: Double?      = nil
    @Published var abMaxDurationB:    Double?      = nil
    @Published var transitionMetric: TransitionMetric = .count
    @Published var abMetricA:        TransitionMetric = .count
    @Published var abMetricB:        TransitionMetric = .count

    // Stored simulation results (in-memory, cleared on project change)
    @Published var simResultA: SimulationResult? = nil
    @Published var simResultB: SimulationResult? = nil

    // Which data source each A/B side is currently showing
    @Published var abDataSourceA: ABDataSource = .sampleSet(.original)
    @Published var abDataSourceB: ABDataSource = .sampleSet(.original)

    func setABMetric(_ metric: TransitionMetric, for side: ABSide) {
        switch side {
        case .a:
            abMetricA = metric
            savedChartStates[.aChart]?.transitionMetric = metric
        case .b:
            abMetricB = metric
            savedChartStates[.bChart]?.transitionMetric = metric
        }
        if abActiveSide == side { transitionMetric = metric }
    }

    // MARK: - Simulation slot management

    func storeSimulation(_ result: SimulationResult, to slot: SimSlot) {
        switch slot {
        case .simA: simResultA = result
        case .simB: simResultB = result
        }
        // If a side is already showing this slot, refresh it immediately
        if abDataSourceA == .simulation(slot) { applySimulationToABSide(.a) }
        if abDataSourceB == .simulation(slot) { applySimulationToABSide(.b) }
    }

    func setABDataSource(_ source: ABDataSource, for side: ABSide) async {
        switch side {
        case .a: abDataSourceA = source
        case .b: abDataSourceB = source
        }
        switch source {
        case .sampleSet(let set):
            switch side {
            case .a: activeSampleSetA = set
            case .b: activeSampleSetB = set
            }
            guard selectedProject != nil else { return }
            if activeChartMode == .abComparison {
                let (from, to) = datesForABSide(side)
                await reloadABSide(side, from: from, to: to)
            } else if (activeChartMode == .aChart && side == .a) ||
                      (activeChartMode == .bChart && side == .b) {
                await reloadGraph()
            }
        case .simulation:
            applySimulationToABSide(side)
        }
    }

    func applySimulationToABSide(_ side: ABSide) {
        let source = side == .a ? abDataSourceA : abDataSourceB
        guard case .simulation(let slot) = source else { return }
        let result = slot == .simA ? simResultA : simResultB
        guard let result else { return }
        let graph = result.simProcessGraph
        let count = result.totalJourneys
        switch side {
        case .a:
            abGraphA = graph; abJourneyCountA = count
            abMinDurationA = result.minCycleTimeSecs; abAvgDurationA = result.avgCycleTimeSecs
            abStdDevDurationA = result.stdDevCycleTimeSecs; abMaxDurationA = result.maxCycleTimeSecs
            abGoodnessA = nil; abVariantsA = []
            if abActiveSide == .a { processGraph = graph; journeyCount = count; processGoodnessScore = nil }
        case .b:
            abGraphB = graph; abJourneyCountB = count
            abMinDurationB = result.minCycleTimeSecs; abAvgDurationB = result.avgCycleTimeSecs
            abStdDevDurationB = result.stdDevCycleTimeSecs; abMaxDurationB = result.maxCycleTimeSecs
            abGoodnessB = nil; abVariantsB = []
            if abActiveSide == .b { processGraph = graph; journeyCount = count; processGoodnessScore = nil }
        }
        abSimilarityScore = computeABSimilarity()
    }

    // MARK: - Per-chart filter state (active chart exposed as flat @Published for bindings)
    @Published var processGraph:   ProcessGraph   = .empty
    @Published var fromDate:       Date           = Date()
    @Published var toDate:         Date           = Date()
    @Published var includedSteps:  Set<String>    = []
    @Published var excludedSteps:  Set<String>    = []
    @Published var meta1Filter:    String         = ""
    @Published var meta2Filter:    String         = ""
    @Published var meta3Filter:    String         = ""
    @Published var eventIdFilter:       String    = ""
    @Published var eventIdSuggestions:  [String]  = []
    @Published var lastQueriedEventId:  String    = ""  // MD5 hash actually sent to DB
    @Published var journeyDate:    Date?          = nil
    @Published var journeyEndDate: Date?          = nil
    @Published var journeyCount:   Int?           = nil
    @Published var journeyMeta1:          String? = nil
    @Published var journeyMeta2:          String? = nil
    @Published var journeyMeta3:          String? = nil
    @Published var minJourneyDuration:    Double? = nil
    @Published var avgJourneyDuration:    Double? = nil
    @Published var stdDevJourneyDuration: Double? = nil
    @Published var maxJourneyDuration:    Double? = nil
    @Published var stepCountMin:          Int     = 1
    @Published var stepCountMax:          Int     = 100
    @Published var minStepsFilter:        Int     = 0
    @Published var maxStepsFilter:        Int     = Int.max
    @Published var journeyTimeBoundsMin:  Int     = 0
    @Published var journeyTimeBoundsMax:  Int     = 0
    @Published var minJourneyTimeFilter:  Int     = 0
    @Published var maxJourneyTimeFilter:  Int     = Int.max
    @Published var scoreBoundsMin:        Int     = 0
    @Published var scoreBoundsMax:        Int     = 0
    @Published var minScoreFilter:        Int     = Int.min
    @Published var maxScoreFilter:        Int     = Int.max

    private let repo = ProcessRepository()

    private func syncSampleSet(_ set: SampleSet) { repo.activeSampleSet = set }
    private func syncSampleSet() { repo.activeSampleSet = activeSampleSetA }

    // Persisted states for non-active charts
    private var savedChartStates: [DetailViewMode: ChartFilterState] = [:]

    /// A-Chart filter state — read by AI supported Documentation view to show context.
    var aChartState: ChartFilterState? { savedChartStates[.aChart] }

    /// Single-line summary of the A-Chart date window, journey count, and active filters.
    var aChartFilterSummary: String {
        let df = DateFormatter(); df.dateStyle = .short; df.timeStyle = .none
        guard let s = savedChartStates[.aChart] else {
            return "\(df.string(from: fromDate)) – \(df.string(from: toDate))"
        }
        var parts = ["\(df.string(from: s.fromDate)) – \(df.string(from: s.toDate))"]
        if let cnt = s.journeyCount { parts.append("\(cnt.formatted()) journeys") }
        if !s.includedSteps.isEmpty { parts.append("include: \(s.includedSteps.sorted().joined(separator: ", "))") }
        if !s.excludedSteps.isEmpty { parts.append("exclude: \(s.excludedSteps.sorted().joined(separator: ", "))") }
        if !s.meta1Filter.isEmpty { parts.append(s.meta1Filter) }
        if !s.meta2Filter.isEmpty { parts.append(s.meta2Filter) }
        if !s.meta3Filter.isEmpty { parts.append(s.meta3Filter) }
        return parts.joined(separator: " · ")
    }

    // MARK: - Chart switching

    func switchChartMode(to mode: DetailViewMode) {
        guard mode != activeChartMode else { return }

        // When leaving A/B Comparison, save the active side's state back to its slot
        if activeChartMode == .abComparison {
            let currentState = captureCurrentState()
            switch abActiveSide {
            case .a: savedChartStates[.aChart] = currentState; abGraphA = processGraph; abJourneyCountA = journeyCount; abMetricA = transitionMetric; abGoodnessA = processGoodnessScore
            case .b: savedChartStates[.bChart] = currentState; abGraphB = processGraph; abJourneyCountB = journeyCount; abMetricB = transitionMetric; abGoodnessB = processGoodnessScore
            }
        } else {
            savedChartStates[activeChartMode] = captureCurrentState()
        }

        activeChartMode = mode

        if mode == .abComparison {
            abActiveSide    = .a
            abGraphA        = savedChartStates[.aChart]?.processGraph  ?? .empty
            abGraphB        = savedChartStates[.bChart]?.processGraph  ?? .empty
            abJourneyCountA = savedChartStates[.aChart]?.journeyCount
            abJourneyCountB = savedChartStates[.bChart]?.journeyCount
            abMetricA       = savedChartStates[.aChart]?.transitionMetric ?? .count
            abMetricB       = savedChartStates[.bChart]?.transitionMetric ?? .count
            abMinDurationA    = savedChartStates[.aChart]?.minJourneyDuration
            abAvgDurationA    = savedChartStates[.aChart]?.avgJourneyDuration
            abStdDevDurationA = savedChartStates[.aChart]?.stdDevJourneyDuration
            abMaxDurationA    = savedChartStates[.aChart]?.maxJourneyDuration
            abMinDurationB    = savedChartStates[.bChart]?.minJourneyDuration
            abAvgDurationB    = savedChartStates[.bChart]?.avgJourneyDuration
            abStdDevDurationB = savedChartStates[.bChart]?.stdDevJourneyDuration
            abMaxDurationB    = savedChartStates[.bChart]?.maxJourneyDuration
            abGoodnessA = savedChartStates[.aChart]?.processGoodness
            abGoodnessB = savedChartStates[.bChart]?.processGoodness
            abSimilarityScore = computeABSimilarity()
            if let saved = savedChartStates[.aChart] { apply(saved) }
        } else if mode == .statistics, let aState = savedChartStates[.aChart] {
            // Statistics always inherits Chart A's filter state so date/step filters stay in sync
            apply(aState)
        } else if let saved = savedChartStates[mode] {
            apply(saved)
        }

        // Refresh notes from the database whenever switching to a view that displays them
        switch mode {
        case .aChart, .bChart, .abComparison, .aiAnalysis, .comments:
            if let projectId = selectedProject?.projectId {
                Task { await loadNotes(for: projectId) }
            }
        default:
            break
        }
    }

    // MARK: - A/B side switching (within Comparison mode)

    func switchABSide(to side: ABSide) {
        guard side != abActiveSide else { return }
        let currentState = captureCurrentState()

        // Save departing side
        switch abActiveSide {
        case .a:
            savedChartStates[.aChart] = currentState
            abGraphA          = processGraph
            abJourneyCountA   = journeyCount
            abMetricA         = transitionMetric
            abMinDurationA    = minJourneyDuration
            abAvgDurationA    = avgJourneyDuration
            abStdDevDurationA = stdDevJourneyDuration
            abMaxDurationA    = maxJourneyDuration
            abGoodnessA       = processGoodnessScore
        case .b:
            savedChartStates[.bChart] = currentState
            abGraphB          = processGraph
            abJourneyCountB   = journeyCount
            abMetricB         = transitionMetric
            abMinDurationB    = minJourneyDuration
            abAvgDurationB    = avgJourneyDuration
            abStdDevDurationB = stdDevJourneyDuration
            abMaxDurationB    = maxJourneyDuration
            abGoodnessB       = processGoodnessScore
        }

        abActiveSide = side
        let targetMode: DetailViewMode = side == .a ? .aChart : .bChart

        if let saved = savedChartStates[targetMode] {
            apply(saved)
        } else {
            processGraph  = .empty
            journeyCount  = nil
            includedSteps = []
            excludedSteps = []
            meta1Filter   = ""; meta2Filter = ""; meta3Filter = ""
        }

        // Sync arriving side's display graph, metric, durations, and goodness
        switch side {
        case .a:
            abGraphA = processGraph; abJourneyCountA = journeyCount; abMetricA = transitionMetric
            abMinDurationA = minJourneyDuration; abAvgDurationA = avgJourneyDuration
            abStdDevDurationA = stdDevJourneyDuration; abMaxDurationA = maxJourneyDuration
            abGoodnessA = processGoodnessScore
        case .b:
            abGraphB = processGraph; abJourneyCountB = journeyCount; abMetricB = transitionMetric
            abMinDurationB = minJourneyDuration; abAvgDurationB = avgJourneyDuration
            abStdDevDurationB = stdDevJourneyDuration; abMaxDurationB = maxJourneyDuration
            abGoodnessB = processGoodnessScore
        }
    }

    // MARK: - Project loading

    func loadProjects() async {
        guard DatabaseManager.shared.isConnected else { return }
        isLoading    = true
        errorMessage = nil
        defer { isLoading = false }
        do {
            projects = try await repo.loadProjects()
        } catch {
            let msg = error.localizedDescription
            errorMessage = msg
            pendingAlert = AppAlert.error(title: "Failed to Load Projects", message: msg) { [weak self] in
                Task { await self?.loadProjects() }
            }
        }
    }

    func selectProject(_ project: Project) async {
        syncSampleSet()
        selectedProject   = project
        activeChartMode   = .aChart
        savedChartStates  = [:]

        // Reset active-chart state
        processGraph   = .empty
        includedSteps  = []
        excludedSteps  = []
        meta1Filter    = ""; meta2Filter = ""; meta3Filter = ""
        eventIdFilter      = ""
        eventIdSuggestions = []
        journeyDate    = nil
        journeyEndDate = nil
        journeyCount   = nil
        journeyMeta1   = nil; journeyMeta2 = nil; journeyMeta3 = nil
        minJourneyDuration = nil; avgJourneyDuration = nil; stdDevJourneyDuration = nil; maxJourneyDuration = nil
        stepCountMin = 1; stepCountMax = 100
        minStepsFilter = 0; maxStepsFilter = Int.max
        journeyTimeBoundsMin = 0; journeyTimeBoundsMax = 0
        minJourneyTimeFilter = 0; maxJourneyTimeFilter = Int.max
        scoreBoundsMin = 0; scoreBoundsMax = 0
        minScoreFilter = Int.min; maxScoreFilter = Int.max

        // Reset A/B comparison state
        abActiveSide    = .a
        abGraphA        = .empty
        abGraphB        = .empty
        abJourneyCountA = nil; abJourneyCountB = nil
        abMinDurationA = nil; abAvgDurationA = nil; abStdDevDurationA = nil; abMaxDurationA = nil
        abMinDurationB = nil; abAvgDurationB = nil; abStdDevDurationB = nil; abMaxDurationB = nil
        processGoodnessScore = nil; abGoodnessA = nil; abGoodnessB = nil
        abVariantsA = []; abVariantsB = []; abSimilarityScore = nil
        simResultA = nil; simResultB = nil
        abDataSourceA = .sampleSet(.original); abDataSourceB = .sampleSet(.original)

        // Reset statistics
        statisticsPaths = []
        statsTimeSeries = []
        statsLoadedSnapshot = nil

        // Reset project-level state
        meta1Title = nil; meta2Title = nil; meta3Title = nil
        meta1Values = []; meta2Values = []; meta3Values = []
        totalJourneyCount = nil
        allStepInfos      = [:]
        projectMinDate    = Date()

        // Reset LLM analysis state and load per-project prompt
        isLLMAnalyzing    = false
        llmAnalysisResult = nil
        llmAnalysisError  = nil
        llmPromptTemplate = UserDefaults.standard.string(forKey: "llm_prompt_\(project.projectId)")
                            ?? AppViewModel.defaultLLMPrompt

        isLoading    = true
        errorMessage = nil
        defer { isLoading = false }
        do {
            let dateBounds = try? await repo.loadDateBounds(projectId: project.projectId)
            if let maxDate = dateBounds?.max {
                toDate   = maxDate
                fromDate = Calendar.current.date(byAdding: .day, value: -30, to: maxDate) ?? maxDate
            }
            initialFromDate = fromDate
            initialToDate   = toDate
            projectMinDate  = dateBounds?.min ?? fromDate

            if let bounds = try? await repo.loadStepCountBounds(projectId: project.projectId) {
                stepCountMin = bounds.min; stepCountMax = bounds.max
            }
            minStepsFilter = stepCountMin; maxStepsFilter = stepCountMax

            if let timeBounds = try? await repo.loadJourneyTimeBounds(projectId: project.projectId) {
                journeyTimeBoundsMin = timeBounds.min; journeyTimeBoundsMax = timeBounds.max
            }
            minJourneyTimeFilter = journeyTimeBoundsMin
            // Guard against bounds being 0 (failed load or all-instant journeys) which would
            // produce HAVING ... <= 0 and exclude all multi-step journeys from reloadGraph.
            maxJourneyTimeFilter = journeyTimeBoundsMax > 0 ? journeyTimeBoundsMax : Int.max

            if let sb = try? await repo.loadScoreBounds(projectId: project.projectId) {
                scoreBoundsMin = sb.min; scoreBoundsMax = sb.max
            }
            minScoreFilter = scoreBoundsMin; maxScoreFilter = scoreBoundsMax

            allSteps     = (try? await repo.loadAllStepNames(projectId: project.projectId)) ?? []
            allStepInfos = (try? await repo.loadSteps(projectId: project.projectId))        ?? [:]

            let titles = (try? await repo.loadMetaTitles(projectId: project.projectId)) ?? (nil, nil, nil)
            meta1Title = titles.0; meta2Title = titles.1; meta3Title = titles.2
            if meta1Title != nil { meta1Values = (try? await repo.loadMetaValues(projectId: project.projectId, column: "META_1")) ?? [] }
            if meta2Title != nil { meta2Values = (try? await repo.loadMetaValues(projectId: project.projectId, column: "META_2")) ?? [] }
            if meta3Title != nil { meta3Values = (try? await repo.loadMetaValues(projectId: project.projectId, column: "META_3")) ?? [] }

            // Load sample counts first so we can silently revert to original before the
            // initial graph load if a previously selected sample no longer exists in the DB.
            await refreshSampleCounts()
            if !activeSampleSetA.isOriginal && sampleCounts[activeSampleSetA] == nil {
                activeSampleSetA = .original
            }
            if !activeSampleSetB.isOriginal && sampleCounts[activeSampleSetB] == nil {
                activeSampleSetB = .original
            }

            // Always count ORIGINAL rows so the total never reflects a sample's size
            repo.activeSampleSet = .original
            totalJourneyCount = try? await repo.loadJourneyCount(projectId: project.projectId)
            syncSampleSet(activeSampleSetA)

            // A-Chart gets the initial load; all other charts start with the same date window but empty graph
            processGraph = try await repo.loadGraph(
                projectId: project.projectId, from: fromDate, to: toDate,
                included: [], excluded: [],
                minSteps: minStepsFilter, maxSteps: maxStepsFilter,
                minScore: minScoreFilter, maxScore: maxScoreFilter
            )
            journeyCount = try? await repo.loadJourneyCount(
                projectId: project.projectId, from: fromDate, to: toDate,
                included: [], excluded: [],
                minSteps: minStepsFilter, maxSteps: maxStepsFilter,
                minScore: minScoreFilter, maxScore: maxScoreFilter
            )
            let durations = try? await repo.loadJourneyDurationStats(
                projectId: project.projectId, from: fromDate, to: toDate,
                included: [], excluded: [],
                minSteps: minStepsFilter, maxSteps: maxStepsFilter,
                minScore: minScoreFilter, maxScore: maxScoreFilter
            )
            minJourneyDuration    = durations?.minSecs
            avgJourneyDuration    = durations?.avgSecs
            stdDevJourneyDuration = durations?.stdDevSecs
            maxJourneyDuration    = durations?.maxSecs
            if let g = try? await repo.loadProcessGoodness(
                projectId: project.projectId, from: fromDate, to: toDate,
                included: [], excluded: [],
                minSteps: minStepsFilter, maxSteps: maxStepsFilter,
                minScore: minScoreFilter, maxScore: maxScoreFilter
            ) {
                processGoodnessScore = applyGoodnessCoverage(raw: g.rawGoodness, filteredCount: g.filteredCount)
            }

            // Pre-seed saved states for other charts so they inherit the date window and real bounds
            let seed = ChartFilterState.defaultState(
                from: fromDate, to: toDate,
                minSteps: stepCountMin, maxSteps: stepCountMax,
                minJourneyTime: minJourneyTimeFilter, maxJourneyTime: maxJourneyTimeFilter,
                minScore: minScoreFilter, maxScore: maxScoreFilter)
            for mode in DetailViewMode.allCases where mode != .aChart {
                savedChartStates[mode] = seed
            }

            abFilterGroupIdA = nil; abFilterGroupIdB = nil
            loadNorms(for: project.projectId)
            loadHappyPaths(for: project.projectId)
            loadFilterGroups(for: project.projectId)
            await loadNotes(for: project.projectId)
        } catch {
            let msg = error.localizedDescription
            errorMessage = msg
            let proj = project
            pendingAlert = AppAlert.error(title: "Failed to Load Project", message: msg) { [weak self] in
                Task { await self?.selectProject(proj) }
            }
        }
    }

    // MARK: - Step editor

    func updateStep(projectId: String, step: String,
                    bgColor: String, fgColor: String,
                    score: Int?, shape: String, belongsTo: String?, description: String?) async {
        errorMessage = nil
        do {
            try await repo.updateStep(projectId: projectId, step: step,
                                      bgColor: bgColor, fgColor: fgColor,
                                      score: score, shape: shape, belongsTo: belongsTo,
                                      description: description)
            if var info = allStepInfos[step] {
                info = StepInfo(step: info.step,
                                description: description ?? info.description,
                                bgColor: bgColor, fgColor: fgColor,
                                score: score, shape: shape,
                                endOfProcess: info.endOfProcess, belongsTo: belongsTo,
                                eventTime: info.eventTime)
                allStepInfos[step] = info
            }
            // Reload score bounds so the slider range reflects the newly saved step score.
            // Reset the filter to the full new range (matching selectProject behaviour),
            // ensuring no journeys are silently dropped by a now-stale filter window.
            // Fall back to step-info scores if the DB query fails, so the slider is never
            // left showing a stale disabled range.
            if let sb = try? await repo.loadScoreBounds(projectId: projectId) {
                scoreBoundsMin = sb.min
                scoreBoundsMax = sb.max
            } else {
                let stepScores = allStepInfos.values.compactMap { $0.score }
                scoreBoundsMin = stepScores.isEmpty ? 0 : min(0, stepScores.min()!)
                scoreBoundsMax = stepScores.isEmpty ? 0 : stepScores.max()!
            }
            minScoreFilter = scoreBoundsMin
            maxScoreFilter = scoreBoundsMax
            await reloadGraph()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    // MARK: - Individual journey load

    private func md5(_ string: String) -> String {
        let digest = Insecure.MD5.hash(data: Data(string.utf8))
        return digest.map { String(format: "%02x", $0) }.joined()
    }

    private func isMD5Hex(_ s: String) -> Bool {
        s.count == 32 && s.allSatisfy { $0.isHexDigit }
    }

    func loadIndividualJourney() async {
        guard let project = selectedProject else { return }
        let raw = eventIdFilter.trimmingCharacters(in: .whitespaces)
        guard !raw.isEmpty else { return }
        // Already a 32-char hex hash (e.g. selected from autocomplete) → use directly.
        // Otherwise treat input as a source identifier and hash it.
        let eid = isMD5Hex(raw) ? raw : md5(raw)
        lastQueriedEventId = eid
        syncSampleSet()
        isLoading    = true
        errorMessage = nil
        journeyMeta1 = nil; journeyMeta2 = nil; journeyMeta3 = nil
        defer { isLoading = false }
        do {
            processGraph = try await repo.loadJourneyGraph(projectId: project.projectId, eventId: eid)
            journeyCount = processGraph.transitions.isEmpty ? 0 : 1
            if let info = try? await repo.loadJourneyInfo(projectId: project.projectId, eventId: eid) {
                journeyDate    = info.startDate
                journeyEndDate = info.endDate
                journeyMeta1   = info.meta1
                journeyMeta2   = info.meta2
                journeyMeta3   = info.meta3
            }
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    // MARK: - Filter reset

    func resetFilters() {
        fromDate       = initialFromDate
        toDate         = initialToDate
        includedSteps  = []
        excludedSteps  = []
        meta1Filter    = ""
        meta2Filter    = ""
        meta3Filter    = ""
        minStepsFilter       = stepCountMin
        maxStepsFilter       = stepCountMax
        minJourneyTimeFilter = journeyTimeBoundsMin
        maxJourneyTimeFilter = journeyTimeBoundsMax
        minScoreFilter       = scoreBoundsMin
        maxScoreFilter       = scoreBoundsMax
    }

    func fetchEventIdSuggestions() async {
        guard let projectId = selectedProject?.projectId,
              eventIdFilter.count >= 2 else {
            eventIdSuggestions = []
            return
        }
        eventIdSuggestions = (try? await repo.loadEventIdSuggestions(
            projectId: projectId, prefix: eventIdFilter)) ?? []
    }

    // MARK: - Graph reload (operates on active chart)

    func reloadGraph() async {
        let chartSampleSet: SampleSet
        switch activeChartMode {
        case .bChart: chartSampleSet = activeSampleSetB
        case .abComparison: chartSampleSet = abActiveSide == .b ? activeSampleSetB : activeSampleSetA
        default: chartSampleSet = activeSampleSetA
        }
        syncSampleSet(chartSampleSet)
        guard let project = selectedProject else { return }
        isLoading    = true
        errorMessage = nil
        defer { isLoading = false }
        do {
            processGraph = try await repo.loadGraph(
                projectId: project.projectId, from: fromDate, to: toDate,
                included: Array(includedSteps), excluded: Array(excludedSteps),
                meta1: meta1Filter, meta2: meta2Filter, meta3: meta3Filter,
                minSteps: minStepsFilter, maxSteps: maxStepsFilter,
                minJourneyTime: minJourneyTimeFilter, maxJourneyTime: maxJourneyTimeFilter,
                minScore: minScoreFilter, maxScore: maxScoreFilter
            )
            journeyCount = try? await repo.loadJourneyCount(
                projectId: project.projectId, from: fromDate, to: toDate,
                included: Array(includedSteps), excluded: Array(excludedSteps),
                meta1: meta1Filter, meta2: meta2Filter, meta3: meta3Filter,
                minSteps: minStepsFilter, maxSteps: maxStepsFilter,
                minJourneyTime: minJourneyTimeFilter, maxJourneyTime: maxJourneyTimeFilter,
                minScore: minScoreFilter, maxScore: maxScoreFilter
            )
            let durations = try? await repo.loadJourneyDurationStats(
                projectId: project.projectId, from: fromDate, to: toDate,
                included: Array(includedSteps), excluded: Array(excludedSteps),
                meta1: meta1Filter, meta2: meta2Filter, meta3: meta3Filter,
                minSteps: minStepsFilter, maxSteps: maxStepsFilter,
                minJourneyTime: minJourneyTimeFilter, maxJourneyTime: maxJourneyTimeFilter,
                minScore: minScoreFilter, maxScore: maxScoreFilter
            )
            minJourneyDuration    = durations?.minSecs
            avgJourneyDuration    = durations?.avgSecs
            stdDevJourneyDuration = durations?.stdDevSecs
            maxJourneyDuration    = durations?.maxSecs
            if let g = try? await repo.loadProcessGoodness(
                projectId: project.projectId, from: fromDate, to: toDate,
                included: Array(includedSteps), excluded: Array(excludedSteps),
                meta1: meta1Filter, meta2: meta2Filter, meta3: meta3Filter,
                minSteps: minStepsFilter, maxSteps: maxStepsFilter,
                minJourneyTime: minJourneyTimeFilter, maxJourneyTime: maxJourneyTimeFilter,
                minScore: minScoreFilter, maxScore: maxScoreFilter
            ) {
                processGoodnessScore = applyGoodnessCoverage(raw: g.rawGoodness, filteredCount: g.filteredCount)
            } else {
                processGoodnessScore = nil
            }
            // In A/B Comparison, propagate the result to the active side's display graph
            if activeChartMode == .abComparison {
                switch abActiveSide {
                case .a:
                    abGraphA          = processGraph
                    abJourneyCountA   = journeyCount
                    abMetricA         = transitionMetric
                    abMinDurationA    = minJourneyDuration
                    abAvgDurationA    = avgJourneyDuration
                    abStdDevDurationA = stdDevJourneyDuration
                    abMaxDurationA    = maxJourneyDuration
                    abGoodnessA       = processGoodnessScore
                    savedChartStates[.aChart] = captureCurrentState()
                case .b:
                    abGraphB          = processGraph
                    abJourneyCountB   = journeyCount
                    abMetricB         = transitionMetric
                    abMinDurationB    = minJourneyDuration
                    abAvgDurationB    = avgJourneyDuration
                    abStdDevDurationB = stdDevJourneyDuration
                    abMaxDurationB    = maxJourneyDuration
                    abGoodnessB       = processGoodnessScore
                    savedChartStates[.bChart] = captureCurrentState()
                }
                await refreshABSimilarity()
            }
            if activeChartMode == .happyPath {
                await refreshHappyPathConformance()
            }
        } catch {
            let msg = error.localizedDescription
            errorMessage = msg
            pendingAlert = AppAlert.error(title: "Failed to Reload Chart", message: msg) { [weak self] in
                Task { await self?.reloadGraph() }
            }
        }
    }

    // MARK: - Single-day reload with nearest-data fallback

    /// Reloads the graph for a single day. If no journeys exist on that day,
    /// finds the nearest date with data, reloads there, posts an info alert,
    /// and returns the date actually used. Returns nil only when no data exists at all.
    func reloadGraphForDay(_ day: Date) async -> Date? {
        fromDate = day
        toDate   = day
        await reloadGraph()
        guard processGraph.transitions.isEmpty else { return day }
        guard let project = selectedProject else { return nil }
        do {
            guard let nearest = try await repo.findNearestDayWithData(relativeTo: day, projectId: project.projectId) else {
                pendingAlert = AppAlert(
                    title: "No Journey Data",
                    message: "No journeys exist for this date or any nearby dates.",
                    primary: .ok,
                    secondary: nil
                )
                return nil
            }
            fromDate = nearest
            toDate   = nearest
            await reloadGraph()
            let df = DateFormatter()
            df.dateStyle = .medium; df.timeStyle = .none
            pendingAlert = AppAlert(
                title: "No Journeys on \(df.string(from: day))",
                message: "No journeys were found on \(df.string(from: day)). Jumped to the nearest date with data: \(df.string(from: nearest)).",
                primary: .ok,
                secondary: nil
            )
            return nearest
        } catch {
            return nil
        }
    }

    /// Same as reloadGraphForDay but operates on an A/B comparison side.
    func reloadABSideForDay(_ side: ABSide, day: Date) async -> Date? {
        await reloadABSide(side, from: day, to: day)
        let graph = side == .a ? abGraphA : abGraphB
        guard graph.transitions.isEmpty else { return day }
        guard let project = selectedProject else { return nil }
        do {
            guard let nearest = try await repo.findNearestDayWithData(relativeTo: day, projectId: project.projectId) else {
                pendingAlert = AppAlert(
                    title: "No Journey Data",
                    message: "No journeys exist for this date or any nearby dates.",
                    primary: .ok,
                    secondary: nil
                )
                return nil
            }
            await reloadABSide(side, from: nearest, to: nearest)
            let df = DateFormatter()
            df.dateStyle = .medium; df.timeStyle = .none
            pendingAlert = AppAlert(
                title: "No Journeys on \(df.string(from: day))",
                message: "No journeys were found on \(df.string(from: day)). Jumped to the nearest date with data: \(df.string(from: nearest)).",
                primary: .ok,
                secondary: nil
            )
            return nearest
        } catch {
            return nil
        }
    }

    // MARK: - A/B date-range reload (used by journey time slider)

    func reloadABSide(_ side: ABSide, from: Date, to: Date) async {
        // If this side is showing a simulation, re-apply the stored result and skip the DB
        let dataSource = side == .a ? abDataSourceA : abDataSourceB
        if case .simulation = dataSource { applySimulationToABSide(side); return }
        syncSampleSet(side == .b ? activeSampleSetB : activeSampleSetA)
        guard let project = selectedProject else { return }
        let mode: DetailViewMode = side == .a ? .aChart : .bChart
        // Use saved filter state if available; fall back to defaults so slider always works
        let state = savedChartStates[mode]
        isLoading = true
        switch side { case .a: isLoadingA = true; case .b: isLoadingB = true }
        errorMessage = nil
        defer {
            isLoading = false
            switch side { case .a: isLoadingA = false; case .b: isLoadingB = false }
        }
        do {
            let g = try await repo.loadGraph(
                projectId: project.projectId, from: from, to: to,
                included: state.map { Array($0.includedSteps) } ?? [],
                excluded: state.map { Array($0.excludedSteps) } ?? [],
                meta1: state?.meta1Filter ?? "",
                meta2: state?.meta2Filter ?? "",
                meta3: state?.meta3Filter ?? "",
                minSteps: state?.minStepsFilter ?? 0,
                maxSteps: state?.maxStepsFilter ?? Int.max,
                minJourneyTime: state?.minJourneyTimeFilter ?? 0,
                maxJourneyTime: state?.maxJourneyTimeFilter ?? Int.max,
                minScore: state?.minScoreFilter ?? Int.min,
                maxScore: state?.maxScoreFilter ?? Int.max
            )
            let cnt = try? await repo.loadJourneyCount(
                projectId: project.projectId, from: from, to: to,
                included: state.map { Array($0.includedSteps) } ?? [],
                excluded: state.map { Array($0.excludedSteps) } ?? [],
                meta1: state?.meta1Filter ?? "",
                meta2: state?.meta2Filter ?? "",
                meta3: state?.meta3Filter ?? "",
                minSteps: state?.minStepsFilter ?? 0,
                maxSteps: state?.maxStepsFilter ?? Int.max,
                minJourneyTime: state?.minJourneyTimeFilter ?? 0,
                maxJourneyTime: state?.maxJourneyTimeFilter ?? Int.max,
                minScore: state?.minScoreFilter ?? Int.min,
                maxScore: state?.maxScoreFilter ?? Int.max
            )
            let dur = try? await repo.loadJourneyDurationStats(
                projectId: project.projectId, from: from, to: to,
                included: state.map { Array($0.includedSteps) } ?? [],
                excluded: state.map { Array($0.excludedSteps) } ?? [],
                meta1: state?.meta1Filter ?? "",
                meta2: state?.meta2Filter ?? "",
                meta3: state?.meta3Filter ?? "",
                minSteps: state?.minStepsFilter ?? 0,
                maxSteps: state?.maxStepsFilter ?? Int.max,
                minJourneyTime: state?.minJourneyTimeFilter ?? 0,
                maxJourneyTime: state?.maxJourneyTimeFilter ?? Int.max,
                minScore: state?.minScoreFilter ?? Int.min,
                maxScore: state?.maxScoreFilter ?? Int.max
            )
            let goodness: Double?
            if let gd = try? await repo.loadProcessGoodness(
                projectId: project.projectId, from: from, to: to,
                included: state.map { Array($0.includedSteps) } ?? [],
                excluded: state.map { Array($0.excludedSteps) } ?? [],
                meta1: state?.meta1Filter ?? "",
                meta2: state?.meta2Filter ?? "",
                meta3: state?.meta3Filter ?? "",
                minSteps: state?.minStepsFilter ?? 0,
                maxSteps: state?.maxStepsFilter ?? Int.max,
                minJourneyTime: state?.minJourneyTimeFilter ?? 0,
                maxJourneyTime: state?.maxJourneyTimeFilter ?? Int.max,
                minScore: state?.minScoreFilter ?? Int.min,
                maxScore: state?.maxScoreFilter ?? Int.max
            ) {
                goodness = applyGoodnessCoverage(raw: gd.rawGoodness, filteredCount: gd.filteredCount)
            } else {
                goodness = nil
            }
            let variants = (try? await repo.loadJourneyPaths(
                projectId: project.projectId, from: from, to: to,
                included: state.map { Array($0.includedSteps) } ?? [],
                excluded: state.map { Array($0.excludedSteps) } ?? [],
                meta1: state?.meta1Filter ?? "",
                meta2: state?.meta2Filter ?? "",
                meta3: state?.meta3Filter ?? "",
                minSteps: state?.minStepsFilter ?? 0,
                maxSteps: state?.maxStepsFilter ?? Int.max,
                minJourneyTime: state?.minJourneyTimeFilter ?? 0,
                maxJourneyTime: state?.maxJourneyTimeFilter ?? Int.max,
                minScore: state?.minScoreFilter ?? Int.min,
                maxScore: state?.maxScoreFilter ?? Int.max,
                limit: abSimilarityVariantLimit
            )) ?? []
            var s = state ?? ChartFilterState.defaultState(from: from, to: to)
            s.fromDate = from; s.toDate = to; s.processGraph = g; s.journeyCount = cnt
            s.minJourneyDuration = dur?.minSecs; s.avgJourneyDuration = dur?.avgSecs
            s.stdDevJourneyDuration = dur?.stdDevSecs; s.maxJourneyDuration = dur?.maxSecs
            s.processGoodness = goodness
            savedChartStates[mode] = s
            switch side {
            case .a:
                abGraphA = g; abJourneyCountA = cnt
                abMinDurationA = dur?.minSecs; abAvgDurationA = dur?.avgSecs
                abStdDevDurationA = dur?.stdDevSecs; abMaxDurationA = dur?.maxSecs
                abGoodnessA = goodness
                abVariantsA = variants
                if abActiveSide == .a { processGraph = g; journeyCount = cnt; fromDate = from; toDate = to; processGoodnessScore = goodness }
            case .b:
                abGraphB = g; abJourneyCountB = cnt
                abMinDurationB = dur?.minSecs; abAvgDurationB = dur?.avgSecs
                abStdDevDurationB = dur?.stdDevSecs; abMaxDurationB = dur?.maxSecs
                abGoodnessB = goodness
                abVariantsB = variants
                if abActiveSide == .b { processGraph = g; journeyCount = cnt; fromDate = from; toDate = to; processGoodnessScore = goodness }
            }
            abSimilarityScore = computeABSimilarity()
        } catch {
            let msg = error.localizedDescription
            errorMessage = msg
            let s = side; let f = from; let t = to
            pendingAlert = AppAlert.error(title: "Failed to Reload Chart", message: msg) { [weak self] in
                Task { await self?.reloadABSide(s, from: f, to: t) }
            }
        }
    }

    // MARK: - LLM analysis

    func runLLMAnalysis() async {
        guard let project = selectedProject else { return }
        guard let llm = DatabaseManager.shared.activeLLMServer,
              !llm.serverURL.isEmpty else {
            llmAnalysisError = "No LLM server configured. Edit your connection to select an LLM server, or add one in Settings."
            return
        }

        isLLMAnalyzing         = true
        llmAnalysisResult      = nil
        llmAnalysisError       = nil
        llmHappyPathSummary       = ""
        llmConformanceSummary     = ""
        llmJourneyPathsSummary    = ""
        llmAnalysisModel    = llm.model.isEmpty ? nil : llm.model
        llmAnalysisDate     = Date()
        defer { isLLMAnalyzing = false }

        // Always use A-Chart data as the reference dataset for analysis
        let aGraph = savedChartStates[.aChart]?.processGraph ?? processGraph
        let sorted = aGraph.transitions.sorted { $0.occurrences > $1.occurrences }
        // Pre-compute per-node outgoing totals for count% across all gap sections
        var aOutgoing: [String: Int] = [:]
        for t in sorted { aOutgoing[t.fromStep, default: 0] += t.occurrences }
        var table = "| From Step | To Step | Count |\n|-----------|---------|-------|\n"
        for t in sorted { table += "| \(t.fromStep) | \(t.toStep) | \(t.occurrences) |\n" }
        let counts = sorted.map(\.occurrences)
        if !counts.isEmpty {
            let total = counts.reduce(0, +)
            let avg   = total / counts.count
            table += "\n**Transitions:** \(sorted.count)  |  **Total:** \(total)  |  **Min:** \(counts.min()!)  |  **Max:** \(counts.max()!)  |  **Avg:** \(avg)"
        }

        // Journey paths table — loaded fresh so it's always available regardless of Statistics view state
        var pathsTable = ""
        let paths = (try? await repo.loadJourneyPaths(
            projectId: project.projectId,
            from: fromDate, to: toDate,
            included: Array(includedSteps), excluded: Array(excludedSteps),
            meta1: meta1Filter, meta2: meta2Filter, meta3: meta3Filter,
            minSteps: minStepsFilter, maxSteps: maxStepsFilter,
            minJourneyTime: minJourneyTimeFilter, maxJourneyTime: maxJourneyTimeFilter,
            minScore: minScoreFilter, maxScore: maxScoreFilter,
            limit: 200
        )) ?? []
        if !paths.isEmpty {
            func esc(_ s: String) -> String {
                s.replacingOccurrences(of: "&", with: "&amp;")
                 .replacingOccurrences(of: "<", with: "&lt;")
                 .replacingOccurrences(of: ">", with: "&gt;")
            }
            var jpHTML = "<table style='table-layout:fixed;width:100%'>"
            jpHTML += "<colgroup>"
            jpHTML += "<col style='width:46%'>"
            jpHTML += "<col style='width:14%'>"
            jpHTML += "<col style='width:12%'>"
            jpHTML += "<col style='width:14%'>"
            jpHTML += "<col style='width:14%'>"
            jpHTML += "</colgroup>"
            jpHTML += "<thead><tr>"
            jpHTML += "<th>Journey Path</th>"
            jpHTML += "<th style='white-space:nowrap;text-align:right'>Journeys</th>"
            jpHTML += "<th style='white-space:nowrap;text-align:right'>Steps</th>"
            jpHTML += "<th style='white-space:nowrap;text-align:right'>Score/J</th>"
            jpHTML += "<th style='white-space:nowrap;text-align:right'>Total</th>"
            jpHTML += "</tr></thead><tbody>"
            for p in paths {
                jpHTML += "<tr>"
                jpHTML += "<td style='overflow-wrap:break-word;word-break:break-word'>\(esc(p.path))</td>"
                jpHTML += "<td style='text-align:right'>\(p.journeyCount.formatted())</td>"
                jpHTML += "<td style='text-align:right'>\(p.stepCount)</td>"
                jpHTML += "<td style='text-align:right'>\(p.totalScore)</td>"
                jpHTML += "<td style='text-align:right'>\(p.aggregatedScore.formatted())</td>"
                jpHTML += "</tr>"
            }
            jpHTML += "</tbody></table>"
            let totalJourneys = paths.reduce(0) { $0 + $1.journeyCount }
            pathsTable = jpHTML
            llmJourneyPathsSummary = "\n\n## Journey Paths\n\n\(jpHTML)\n\n**Paths:** \(paths.count)  |  **Total Journeys:** \(totalJourneys.formatted())"
        }

        // Build conformance gap summary (rendered directly — not sent to LLM)
        var conformanceParts: [String] = []
        let normedMetrics = targetNorms.filter { !$0.value.isEmpty }
        if !normedMetrics.isEmpty {
            struct GapEntry {
                let from: String, to: String
                let actual: Double, norm: Double?
                var delta: Double? { norm.map { actual - $0 } }
                var isViolation: Bool? { delta.map { $0 > 0 } }
            }

            func fmtVal(_ val: Double, for metric: TransitionMetric) -> String {
                if metric == .count {
                    return String(format: "%.1f%%", val)   // count norms are percentages
                }
                if metric.isTimeBased {
                    if val < 60    { return String(format: "%.0fs", val) }
                    if val < 3600  { return String(format: "%.0fm", val / 60) }
                    if val < 86400 { return String(format: "%.1fh", val / 3600) }
                    return           String(format: "%.1fd", val / 86400)
                } else {
                    return String(Int(val.rounded()))
                }
            }

            // Current targetMetric first, rest alphabetically
            let sortedKeys = normedMetrics.keys.sorted { a, b in
                if a == targetMetric.rawValue { return true }
                if b == targetMetric.rawValue { return false }
                return a < b
            }

            for metricKey in sortedKeys {
                guard let metricNorms = normedMetrics[metricKey],
                      let metric = TransitionMetric(rawValue: metricKey) else { continue }

                // For count: actual = occurrences / totalOutgoingFromSameNode * 100
                let isCountPct = metric == .count

                let entries = sorted
                    .filter { $0.fromStep != $0.toStep }
                    .map { t -> GapEntry in
                        let actual: Double = isCountPct
                            ? { let tot = aOutgoing[t.fromStep] ?? 1
                                return Double(t.occurrences) / Double(tot) * 100.0 }()
                            : (t.metricValue(for: metric) ?? Double(t.occurrences))
                        return GapEntry(from: t.fromStep, to: t.toStep, actual: actual, norm: metricNorms[t.id])
                    }
                    .sorted { a, b in
                        if a.isViolation == true && b.isViolation != true { return true }
                        if b.isViolation == true && a.isViolation != true { return false }
                        return (a.delta ?? 0) > (b.delta ?? 0)
                    }

                let violations = entries.filter { $0.isViolation == true }.count
                let compliant  = entries.filter { $0.isViolation == false }.count
                let noNorm     = entries.filter { $0.norm == nil }.count

                var gapTable = "| From Step | To Step | Actual | Norm | Delta | Status |\n"
                gapTable    += "|-----------|---------|--------|------|-------|--------|\n"
                for e in entries {
                    let act    = fmtVal(e.actual, for: metric)
                    let nrm    = e.norm.map { fmtVal($0, for: metric) } ?? "—"
                    let dlt    = e.delta.map { fmtVal($0, for: metric) } ?? "—"
                    let status = e.isViolation.map { $0 ? "❌ VIOLATION" : "✅ Compliant" } ?? "— No norm"
                    gapTable += "| \(e.from) | \(e.to) | \(act) | \(nrm) | \(dlt) | \(status) |\n"
                }

                conformanceParts.append(
                    "### \(metric.rawValue)\n\n" +
                    "Summary: **\(violations) violation(s)**, \(compliant) compliant, \(noNorm) without norm.\n\n" +
                    gapTable
                )
            }

            llmConformanceSummary = "\n\n## Conformance Check – Gap Analysis\n\n" +
                                    conformanceParts.joined(separator: "\n")
        }

        // Build Happy Path conformance summary (rendered directly — not sent to LLM)
        let qualifiedPaths = happyPaths.filter { $0.steps.count >= 2 }
        if happyPaths.isEmpty {
            llmHappyPathSummary = """
            \n\n## Happy Path Conformance\n\n\
            > ⚠️ **No Happy Paths defined for this project.** \
            Happy Path conformance could not be included in the analysis. \
            Open the Happy Path view and define at least one ideal process sequence \
            to measure how closely real journeys follow your intended design.\n
            """
        } else if !qualifiedPaths.isEmpty {
            let variants = (try? await repo.loadJourneyPaths(
                projectId: project.projectId,
                from: fromDate, to: toDate,
                included: Array(includedSteps), excluded: Array(excludedSteps),
                meta1: meta1Filter, meta2: meta2Filter, meta3: meta3Filter,
                minSteps: minStepsFilter, maxSteps: maxStepsFilter,
                minJourneyTime: minJourneyTimeFilter, maxJourneyTime: maxJourneyTimeFilter,
                minScore: minScoreFilter, maxScore: maxScoreFilter,
                limit: 500
            )) ?? []

            var tableRows = ""
            for path in qualifiedPaths {
                let score     = computeHappyPathConformance(path: path, variants: variants)
                let scoreStr  = score.map { String(format: "%.2f", $0) } ?? "N/A"
                let rating    = score.map { s -> String in
                    s >= 0.7 ? "✅  High (≥ 0.70)" : s >= 0.3 ? "⚠️  Moderate (0.30–0.69)" : "❌  Low (< 0.30)"
                } ?? "— No data"
                let branches  = path.branches.filter { !$0.steps.isEmpty }
                let branchStr = branches.isEmpty ? "—" :
                    branches.map { $0.label.isEmpty ? "Branch" : $0.label }.joined(separator: ", ")
                tableRows += "| \(path.name) | \(branchStr) | \(scoreStr) | \(rating) |\n"
            }
            let hpTable = "| Happy Path | Branches | Conformance | Rating |\n" +
                          "|------------|----------|-------------|--------|\n" +
                          tableRows

            llmHappyPathSummary = """
            \n\n## Happy Path Conformance\n\n\
            The Conformance Score is a journey-count-weighted average of edge coverage: \
            **1.00** = every journey follows the ideal path perfectly; \
            **0.00** = no journey shares a single transition with the ideal sequence. \
            For branching paths each journey is scored against the branch it matches best.\n\n\
            \(hpTable)\n\
            | Rating thresholds | Meaning |\n\
            |-------------------|---------|\n\
            | ✅ High (≥ 0.70) | Most journeys closely follow the designed process |\n\
            | ⚠️ Moderate (0.30–0.69) | Significant share of journeys deviate from the ideal |\n\
            | ❌ Low (< 0.30) | Most journeys diverge substantially from the ideal sequence |\n
            """

        }

        let fullPrompt = """
        # Project: \(project.title)

        \(llmPromptTemplate)

        **Important: Format your entire response in Markdown** (use # headers, **bold**, tables with | separators, - bullet lists, ``` code blocks).

        ## Transition Data

        \(table)\(pathsTable)
        """

        lastSentLLMPrompt = fullPrompt

        do {
            llmAnalysisResult = try await LLMService.chat(
                serverURL: llm.serverURL,
                apiKey:    llm.apiKey,
                model:     llm.model,
                prompt:    fullPrompt
            )
        } catch {
            llmAnalysisError = error.localizedDescription
        }
    }

    // MARK: - Statistics

    func loadJourneyPaths() async {
        syncSampleSet()
        guard let project = selectedProject else { return }
        statsGeneration += 1
        let gen = statsGeneration
        statsLoadedSnapshot   = currentFilterSnapshot()
        isLoadingStats        = true
        statsErrorMessage     = nil
        statisticsIsTruncated = false
        statsTimeSeries       = []
        do {
            // Refresh filtered journey count for the metrics tile
            if let count = try? await repo.loadJourneyCount(
                projectId: project.projectId,
                from: fromDate, to: toDate,
                included: Array(includedSteps), excluded: Array(excludedSteps),
                meta1: meta1Filter, meta2: meta2Filter, meta3: meta3Filter,
                minScore: minScoreFilter, maxScore: maxScoreFilter
            ), statsGeneration == gen {
                journeyCount = count
            }

            // Ensure total journey count is available (always ORIGINAL rows, not the active sample)
            if totalJourneyCount == nil, statsGeneration == gen {
                repo.activeSampleSet = .original
                if let total = try? await repo.loadJourneyCount(projectId: project.projectId),
                   statsGeneration == gen {
                    totalJourneyCount = total
                }
                syncSampleSet(activeSampleSetA)
            }

            // Load time series (granularity auto-detected from date range)
            let granularity = TimeGranularity.auto(from: fromDate, to: toDate)
            if statsGeneration == gen { statsTimeGranularity = granularity }
            if let ts = try? await repo.loadJourneyTimeSeries(
                projectId: project.projectId,
                from: fromDate, to: toDate,
                included: Array(includedSteps), excluded: Array(excludedSteps),
                meta1: meta1Filter, meta2: meta2Filter, meta3: meta3Filter,
                minSteps: minStepsFilter, maxSteps: maxStepsFilter,
                minJourneyTime: minJourneyTimeFilter, maxJourneyTime: maxJourneyTimeFilter,
                minScore: minScoreFilter, maxScore: maxScoreFilter,
                granularity: granularity
            ), statsGeneration == gen {
                statsTimeSeries = ts
            }

            if let durations = try? await repo.loadJourneyDurationStats(
                projectId: project.projectId, from: fromDate, to: toDate,
                included: Array(includedSteps), excluded: Array(excludedSteps),
                meta1: meta1Filter, meta2: meta2Filter, meta3: meta3Filter,
                minSteps: minStepsFilter, maxSteps: maxStepsFilter,
                minJourneyTime: minJourneyTimeFilter, maxJourneyTime: maxJourneyTimeFilter,
                minScore: minScoreFilter, maxScore: maxScoreFilter
            ), statsGeneration == gen {
                minJourneyDuration    = durations.minSecs
                avgJourneyDuration    = durations.avgSecs
                stdDevJourneyDuration = durations.stdDevSecs
                maxJourneyDuration    = durations.maxSecs
            }

            if let buckets = try? await repo.loadDurationBuckets(
                projectId: project.projectId, from: fromDate, to: toDate,
                included: Array(includedSteps), excluded: Array(excludedSteps),
                meta1: meta1Filter, meta2: meta2Filter, meta3: meta3Filter,
                minSteps: minStepsFilter, maxSteps: maxStepsFilter,
                minJourneyTime: minJourneyTimeFilter, maxJourneyTime: maxJourneyTimeFilter,
                minScore: minScoreFilter, maxScore: maxScoreFilter
            ), statsGeneration == gen {
                statsDurationBuckets = buckets
            }

            if let graph = try? await repo.loadGraph(
                projectId: project.projectId, from: fromDate, to: toDate,
                included: Array(includedSteps), excluded: Array(excludedSteps),
                meta1: meta1Filter, meta2: meta2Filter, meta3: meta3Filter,
                minSteps: minStepsFilter, maxSteps: maxStepsFilter,
                minJourneyTime: minJourneyTimeFilter, maxJourneyTime: maxJourneyTimeFilter,
                minScore: minScoreFilter, maxScore: maxScoreFilter
            ), statsGeneration == gen {
                statsProcessGraph = graph
            }

            let paths = try await repo.loadJourneyPaths(
                projectId: project.projectId,
                from: fromDate, to: toDate,
                included: Array(includedSteps), excluded: Array(excludedSteps),
                meta1: meta1Filter, meta2: meta2Filter, meta3: meta3Filter,
                minSteps: minStepsFilter, maxSteps: maxStepsFilter,
                minJourneyTime: minJourneyTimeFilter, maxJourneyTime: maxJourneyTimeFilter,
                minScore: minScoreFilter, maxScore: maxScoreFilter,
                limit: statsRouteLimit
            )
            guard statsGeneration == gen else { return }
            statisticsPaths       = paths
            statisticsIsTruncated = paths.count >= statsRouteLimit
        } catch {
            guard statsGeneration == gen else { return }
            let msg = error.localizedDescription
            statsErrorMessage = msg
            pendingAlert = AppAlert.error(title: "Statistics Error", message: msg) { [weak self] in
                Task { await self?.loadJourneyPaths() }
            }
        }
        if statsGeneration == gen { isLoadingStats = false }
    }

    func cancelJourneyPaths() {
        statsGeneration += 1
        isLoadingStats = false
    }

    // MARK: - Session clear (called on disconnect)

    func clearSession() {
        selectedProject   = nil
        projects          = []
        processGraph      = .empty
        savedChartStates  = [:]
        activeChartMode   = .aChart

        includedSteps = []; excludedSteps = []
        meta1Filter   = ""; meta2Filter = ""; meta3Filter = ""
        eventIdFilter = ""; eventIdSuggestions = []

        journeyDate    = nil; journeyEndDate = nil
        journeyCount   = nil; totalJourneyCount = nil
        journeyMeta1   = nil; journeyMeta2 = nil; journeyMeta3 = nil
        minJourneyDuration = nil; avgJourneyDuration = nil; stdDevJourneyDuration = nil; maxJourneyDuration = nil

        allSteps = []; allStepInfos = [:]
        meta1Title = nil; meta2Title = nil; meta3Title = nil
        meta1Values = []; meta2Values = []; meta3Values = []

        abActiveSide    = .a
        abGraphA        = .empty; abGraphB = .empty
        abJourneyCountA = nil;    abJourneyCountB = nil
        abMinDurationA = nil; abAvgDurationA = nil; abStdDevDurationA = nil; abMaxDurationA = nil
        abMinDurationB = nil; abAvgDurationB = nil; abStdDevDurationB = nil; abMaxDurationB = nil

        statisticsPaths = []; statsTimeSeries = []; statsDurationBuckets = []; statsProcessGraph = .empty
        statsLoadedSnapshot = nil
        llmAnalysisResult = nil; llmAnalysisError = nil; lastSentLLMPrompt = nil
        llmHappyPathSummary = ""; llmConformanceSummary = ""

        targetNorms  = [:]
        targetMetric = .count
        happyPaths = []; selectedHappyPathId = nil; happyPathScore = nil
        filterGroups = []; selectedFilterGroupId = nil; abFilterGroupIdA = nil; abFilterGroupIdB = nil
        projectNotes = []

        errorMessage = nil
        pendingAlert = nil
        isLoading    = false

        stepCountMin = 1; stepCountMax = 100
        minStepsFilter = 0; maxStepsFilter = Int.max
        journeyTimeBoundsMin = 0; journeyTimeBoundsMax = 0
        minJourneyTimeFilter = 0; maxJourneyTimeFilter = Int.max
        scoreBoundsMin = 0; scoreBoundsMax = 0
        minScoreFilter = Int.min; maxScoreFilter = Int.max
        processGoodnessScore = nil; abGoodnessA = nil; abGoodnessB = nil
        abVariantsA = []; abVariantsB = []; abSimilarityScore = nil
    }

    // MARK: - Private helpers

    // Applies the coverage penalty: goodness × (filteredCount / totalJourneyCount)^0.5
    func refreshABSimilarity() async {
        guard let project = selectedProject else { return }
        guard let stateA = savedChartStates[.aChart], let stateB = savedChartStates[.bChart] else { return }
        // Sequential queries — ExasolConnection is a single connection and does not support concurrency
        abVariantsA = (try? await repo.loadJourneyPaths(
            projectId: project.projectId,
            from: stateA.fromDate, to: stateA.toDate,
            included: Array(stateA.includedSteps), excluded: Array(stateA.excludedSteps),
            meta1: stateA.meta1Filter, meta2: stateA.meta2Filter, meta3: stateA.meta3Filter,
            minSteps: stateA.minStepsFilter, maxSteps: stateA.maxStepsFilter,
            minJourneyTime: stateA.minJourneyTimeFilter, maxJourneyTime: stateA.maxJourneyTimeFilter,
            minScore: stateA.minScoreFilter, maxScore: stateA.maxScoreFilter,
            limit: abSimilarityVariantLimit
        )) ?? []
        abVariantsB = (try? await repo.loadJourneyPaths(
            projectId: project.projectId,
            from: stateB.fromDate, to: stateB.toDate,
            included: Array(stateB.includedSteps), excluded: Array(stateB.excludedSteps),
            meta1: stateB.meta1Filter, meta2: stateB.meta2Filter, meta3: stateB.meta3Filter,
            minSteps: stateB.minStepsFilter, maxSteps: stateB.maxStepsFilter,
            minJourneyTime: stateB.minJourneyTimeFilter, maxJourneyTime: stateB.maxJourneyTimeFilter,
            minScore: stateB.minScoreFilter, maxScore: stateB.maxScoreFilter,
            limit: abSimilarityVariantLimit
        )) ?? []
        abSimilarityScore = computeABSimilarity()
    }

    private func computeABSimilarity() -> Double? {
        let varA = abVariantsA
        let varB = abVariantsB
        let graphA = abGraphA
        let graphB = abGraphB
        guard !varA.isEmpty && !varB.isEmpty else { return nil }
        // Practical guard: too many variants → skip (would be slow and untrustworthy)
        guard varA.count + varB.count <= abSimilarityVariantLimit * 2 else { return nil }

        let totalCount = varA.reduce(0) { $0 + $1.journeyCount }
                       + varB.reduce(0) { $0 + $1.journeyCount }
        guard totalCount > 0 else { return nil }
        let total = Double(totalCount)

        // Union variant set with combined normalised frequencies
        var variantFreq: [String: Double] = [:]
        for v in varA { variantFreq[v.path, default: 0] += Double(v.journeyCount) / total }
        for v in varB { variantFreq[v.path, default: 0] += Double(v.journeyCount) / total }

        // Edge sets for alignment cost
        struct EdgeKey: Hashable { let from, to: String }
        let edgesA = Set(graphA.transitions.map { EdgeKey(from: $0.fromStep, to: $0.toStep) })
        let edgesB = Set(graphB.transitions.map { EdgeKey(from: $0.fromStep, to: $0.toStep) })

        // Node importance weights |s_i| from both graphs (take max where both define a score)
        var nodeScores: [String: Double] = [:]
        for (name, step) in graphA.steps {
            if let s = step.score { nodeScores[name] = max(nodeScores[name] ?? 0, abs(Double(s))) }
        }
        for (name, step) in graphB.steps {
            if let s = step.score { nodeScores[name] = max(nodeScores[name] ?? 0, abs(Double(s))) }
        }

        var sumAbsDiff  = 0.0; var sumMaxCost  = 0.0
        var sumMinNodes = 0.0; var sumMaxNodes  = 0.0
        var sumFitsBoth = 0.0; var totalFreq    = 0.0

        for (path, freq) in variantFreq {
            let steps = path.components(separatedBy: " -> ")
            guard steps.count >= 2 else { continue }
            let numEdges = steps.count - 1

            // Edge-coverage alignment cost: fraction of edges missing in each graph
            var missingA = 0; var missingB = 0
            for i in 0..<numEdges {
                let e = EdgeKey(from: steps[i], to: steps[i + 1])
                if !edgesA.contains(e) { missingA += 1 }
                if !edgesB.contains(e) { missingB += 1 }
            }
            let costA = Double(missingA) / Double(numEdges)
            let costB = Double(missingB) / Double(numEdges)

            // Q_var components
            sumAbsDiff += freq * abs(costA - costB)
            sumMaxCost += freq * max(costA, costB)

            // Q_nodes_var: soft visit = presence in variant × (1 - alignmentCost)
            let nodesInVariant = Set(steps)
            var minNS = 0.0; var maxNS = 0.0
            for (name, absScore) in nodeScores {
                let inVar = nodesInVariant.contains(name) ? 1.0 : 0.0
                let v1 = inVar * (1.0 - costA)
                let v2 = inVar * (1.0 - costB)
                minNS += min(v1, v2) * absScore
                maxNS += max(v1, v2) * absScore
            }
            sumMinNodes += freq * minNS
            sumMaxNodes += freq * maxNS

            // Q_cov: variant fits both = zero missing edges in both graphs
            sumFitsBoth += freq * (costA == 0 && costB == 0 ? 1.0 : 0.0)
            totalFreq   += freq
        }

        let qVar   = sumMaxCost  > 0 ? 1.0 - sumAbsDiff / sumMaxCost  : 1.0
        let qNodes = sumMaxNodes > 0 ? sumMinNodes / sumMaxNodes        : 1.0
        let qCov   = totalFreq   > 0 ? sumFitsBoth / totalFreq         : 0.0

        let score = 0.4 * qVar + 0.4 * qNodes + 0.2 * qCov
        return score.isFinite ? score : nil
    }

    private func applyGoodnessCoverage(raw: Double, filteredCount: Int) -> Double {
        let baseline = Double(totalJourneyCount ?? filteredCount)
        guard baseline > 0, filteredCount > 0 else { return raw }
        let coverage = Double(filteredCount) / baseline
        return raw * pow(coverage, 0.5)
    }

    private func captureCurrentState() -> ChartFilterState {
        ChartFilterState(
            fromDate:            fromDate,
            toDate:              toDate,
            includedSteps:       includedSteps,
            excludedSteps:       excludedSteps,
            meta1Filter:         meta1Filter,
            meta2Filter:         meta2Filter,
            meta3Filter:         meta3Filter,
            eventIdFilter:       eventIdFilter,
            journeyDate:         journeyDate,
            journeyEndDate:      journeyEndDate,
            processGraph:        processGraph,
            journeyCount:        journeyCount,
            transitionMetric:    transitionMetric,
            minJourneyDuration:    minJourneyDuration,
            avgJourneyDuration:    avgJourneyDuration,
            stdDevJourneyDuration: stdDevJourneyDuration,
            maxJourneyDuration:    maxJourneyDuration,
            minStepsFilter:       minStepsFilter,
            maxStepsFilter:       maxStepsFilter,
            minJourneyTimeFilter: minJourneyTimeFilter,
            maxJourneyTimeFilter: maxJourneyTimeFilter,
            minScoreFilter:       minScoreFilter,
            maxScoreFilter:       maxScoreFilter,
            processGoodness:      processGoodnessScore
        )
    }

    private func apply(_ state: ChartFilterState) {
        fromDate             = state.fromDate
        toDate               = state.toDate
        includedSteps        = state.includedSteps
        excludedSteps        = state.excludedSteps
        meta1Filter          = state.meta1Filter
        meta2Filter          = state.meta2Filter
        meta3Filter          = state.meta3Filter
        eventIdFilter        = state.eventIdFilter
        journeyDate          = state.journeyDate
        journeyEndDate       = state.journeyEndDate
        processGraph         = state.processGraph
        journeyCount         = state.journeyCount
        transitionMetric     = state.transitionMetric
        minJourneyDuration    = state.minJourneyDuration
        avgJourneyDuration    = state.avgJourneyDuration
        stdDevJourneyDuration = state.stdDevJourneyDuration
        maxJourneyDuration    = state.maxJourneyDuration
        minStepsFilter        = state.minStepsFilter
        maxStepsFilter        = state.maxStepsFilter
        minJourneyTimeFilter  = state.minJourneyTimeFilter
        maxJourneyTimeFilter  = state.maxJourneyTimeFilter
        minScoreFilter        = state.minScoreFilter
        maxScoreFilter        = state.maxScoreFilter
        processGoodnessScore  = state.processGoodness
    }

    // MARK: - Sample management

    func refreshSampleCounts() async {
        guard let projectId = selectedProject?.projectId else {
            sampleCounts = [:]
            sampleMethods = [:]
            return
        }
        do {
            try await repo.ensureSampleSetColumn()
            sampleCounts = (try? await repo.loadSampleJourneyCounts(projectId: projectId)) ?? [:]
        } catch {
            sampleCounts = [:]
        }
        loadSampleMethods(for: projectId)
    }

    private func loadSampleMethods(for projectId: String) {
        var methods: [SampleSet: SamplingMethod] = [:]
        for set in [SampleSet.sample1, .sample2, .sample3] {
            let key = "sampling.method.\(set.rawValue).\(projectId)"
            if let raw = UserDefaults.standard.string(forKey: key),
               let m = SamplingMethod(rawValue: raw) {
                methods[set] = m
            }
        }
        sampleMethods = methods
    }

    func createSample(
        type: SampleSet,
        count: Int,
        method: SamplingMethod
    ) async {
        guard let projectId = selectedProject?.projectId, !type.isOriginal else { return }
        isSampling   = true
        samplingError = nil
        samplingProgress = "Preparing…"
        defer { isSampling = false; samplingProgress = nil }
        do {
            try await repo.ensureSampleSetColumn()
            // Delete any existing sample in that slot first
            try await repo.deleteSample(projectId: projectId, sampleSet: type)

            samplingProgress = "Fetching journeys…"
            let selectedIds: [String]
            switch method {
            case .random:
                var ids = try await repo.loadAllEventIdsForSampling(projectId: projectId)
                ids.shuffle()
                selectedIds = Array(ids.prefix(count))

            case .temporal:
                let pairs = try await repo.loadEventIdsWithStartTimesForSampling(projectId: projectId)
                selectedIds = temporalStratifiedSample(pairs: pairs, targetCount: count)

            case .pathDiverse:
                let pairs = try await repo.loadEventIdsWithPathsForSampling(projectId: projectId)
                selectedIds = pathDiverseSample(pairs: pairs, targetCount: count)
            }

            guard !selectedIds.isEmpty else {
                samplingError = "No journeys found in the original data."
                return
            }

            samplingProgress = "Writing \(selectedIds.count) journeys…"
            try await repo.insertSampleJourneys(projectId: projectId, eventIds: selectedIds, sampleSet: type)
            sampleCounts = (try? await repo.loadSampleJourneyCounts(projectId: projectId)) ?? [:]
            UserDefaults.standard.set(method.rawValue, forKey: "sampling.method.\(type.rawValue).\(projectId)")
            loadSampleMethods(for: projectId)
        } catch {
            samplingError = error.localizedDescription
        }
    }

    func deleteSample(type: SampleSet) async {
        guard let projectId = selectedProject?.projectId, !type.isOriginal else { return }
        isSampling    = true
        samplingError = nil
        defer { isSampling = false }
        do {
            try await repo.deleteSample(projectId: projectId, sampleSet: type)
            sampleCounts[type] = nil
            sampleMethods[type] = nil
            UserDefaults.standard.removeObject(forKey: "sampling.method.\(type.rawValue).\(projectId)")
            let switchedA = activeSampleSetA == type
            let switchedB = activeSampleSetB == type
            if switchedA { activeSampleSetA = .original }
            if switchedB { activeSampleSetB = .original }
            if switchedA || switchedB { await reloadGraph() }
        } catch {
            samplingError = error.localizedDescription
        }
    }

    func switchSampleSet(to set: SampleSet) async {
        activeSampleSet = set
        guard selectedProject != nil else { return }
        await selectProject(selectedProject!)
    }

    /// Switch A-Chart's sample set and immediately reload any chart that shows A data.
    func switchSampleSetA(to set: SampleSet) async {
        guard activeSampleSetA != set else { return }
        activeSampleSetA = set
        guard selectedProject != nil else { return }
        switch activeChartMode {
        case .bChart:
            break  // B-Chart doesn't use A's sample set
        case .abComparison:
            let (from, to) = datesForABSide(.a)
            await reloadABSide(.a, from: from, to: to)
        default:
            await reloadGraph()
        }
    }

    /// Switch B-Chart's sample set and immediately reload any chart that shows B data.
    func switchSampleSetB(to set: SampleSet) async {
        guard activeSampleSetB != set else { return }
        activeSampleSetB = set
        guard selectedProject != nil else { return }
        switch activeChartMode {
        case .bChart:
            await reloadGraph()
        case .abComparison:
            let (from, to) = datesForABSide(.b)
            await reloadABSide(.b, from: from, to: to)
        default:
            break  // Non-B views don't use B's sample set
        }
    }

    private func datesForABSide(_ side: ABSide) -> (Date, Date) {
        let mode: DetailViewMode = side == .a ? .aChart : .bChart
        let isActive = (side == .a && abActiveSide == .a) || (side == .b && abActiveSide == .b)
        if isActive {
            return (fromDate, toDate)
        }
        let saved = savedChartStates[mode]
        return (saved?.fromDate ?? fromDate, saved?.toDate ?? toDate)
    }

    // MARK: - Sampling algorithms (run in-memory on fetched event IDs)

    private func temporalStratifiedSample(pairs: [(String, Date)], targetCount: Int) -> [String] {
        guard !pairs.isEmpty, targetCount > 0 else { return [] }
        let cal = Calendar.current
        var buckets: [String: [(String, Date)]] = [:]
        for (id, date) in pairs {
            let comps = cal.dateComponents([.year, .month], from: date)
            let key   = "\(comps.year ?? 0)-\(String(format: "%02d", comps.month ?? 0))"
            buckets[key, default: []].append((id, date))
        }
        let total = pairs.count
        var result: [String] = []
        for (_, bucket) in buckets.sorted(by: { $0.key < $1.key }) {
            let share  = max(1, Int((Double(bucket.count) / Double(total) * Double(targetCount)).rounded()))
            var ids    = bucket.map { $0.0 }
            ids.shuffle()
            result.append(contentsOf: ids.prefix(share))
            if result.count >= targetCount { break }
        }
        if result.count > targetCount { result = Array(result.prefix(targetCount)) }
        return result
    }

    private func pathDiverseSample(pairs: [(String, String)], targetCount: Int) -> [String] {
        guard !pairs.isEmpty, targetCount > 0 else { return [] }
        var buckets: [String: [String]] = [:]
        for (id, path) in pairs {
            buckets[path, default: []].append(id)
        }
        let total = pairs.count
        var result: [String] = []
        // Sorted by path frequency descending so the most common paths fill their quota first
        for (_, ids) in buckets.sorted(by: { $0.value.count > $1.value.count }) {
            let share = max(1, Int((Double(ids.count) / Double(total) * Double(targetCount)).rounded()))
            var mutable = ids
            mutable.shuffle()
            result.append(contentsOf: mutable.prefix(share))
            if result.count >= targetCount { break }
        }
        if result.count > targetCount { result = Array(result.prefix(targetCount)) }
        return result
    }
}
