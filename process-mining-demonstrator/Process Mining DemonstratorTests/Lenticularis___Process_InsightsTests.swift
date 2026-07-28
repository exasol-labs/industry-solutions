//  Lenticularis___Process_InsightsTests.swift
//  Lenticularis – Process Insights
//
//  Unit tests for the pure, dependency-free model logic. These run on the
//  native macOS host application and require no database connection.

import Testing
import Foundation
import SwiftUI
@testable import Lenticularis___Process_Insights

struct ModelLogicTests {

    // MARK: - TimeGranularity.auto

    @Test func timeGranularityPicksBucketBySpan() throws {
        let cal  = Calendar.current
        let base = Date(timeIntervalSince1970: 1_700_000_000)
        func granularity(daysApart days: Int) -> TimeGranularity {
            let to = cal.date(byAdding: .day, value: days, to: base)!
            return TimeGranularity.auto(from: base, to: to)
        }
        #expect(granularity(daysApart: 0)  == .day)
        #expect(granularity(daysApart: 14) == .day)
        #expect(granularity(daysApart: 15) == .week)
        #expect(granularity(daysApart: 90) == .week)
        #expect(granularity(daysApart: 91) == .month)
    }

    // MARK: - TransitionMetric

    @Test func onlyTimeMetricsAreTimeBased() {
        #expect(TransitionMetric.count.isTimeBased == false)
        for metric in [TransitionMetric.avgTime, .minTime, .maxTime, .stdDev] {
            #expect(metric.isTimeBased)
        }
    }

    @Test func transitionExposesTheRightMetricValue() {
        let t = ProcessTransition(fromStep: "A", toStep: "B", occurrences: 7,
                                  avgSecs: 1.0, minSecs: 0.5, maxSecs: 3.0, stdDevSecs: 0.25)
        #expect(t.id == "A->B")
        #expect(t.metricValue(for: .count)   == 7)
        #expect(t.metricValue(for: .avgTime) == 1.0)
        #expect(t.metricValue(for: .minTime) == 0.5)
        #expect(t.metricValue(for: .maxTime) == 3.0)
        #expect(t.metricValue(for: .stdDev)  == 0.25)
    }

    // MARK: - ProcessGraph aggregates

    @Test func processGraphReportsMaxima() {
        let t1 = ProcessTransition(fromStep: "A", toStep: "B", occurrences: 3,
                                   avgSecs: 2, minSecs: 1, maxSecs: 4, stdDevSecs: nil)
        let t2 = ProcessTransition(fromStep: "B", toStep: "C", occurrences: 9,
                                   avgSecs: 5, minSecs: 2, maxSecs: 8, stdDevSecs: nil)
        let graph = ProcessGraph(steps: [:], transitions: [t1, t2])
        #expect(graph.maxOccurrences == 9)
        #expect(graph.maxValue(for: .count)   == 9)
        #expect(graph.maxValue(for: .avgTime) == 5)
        #expect(graph.maxValue(for: .maxTime) == 8)
    }

    @Test func emptyProcessGraphFallsBackToOne() {
        let graph = ProcessGraph.empty
        #expect(graph.transitions.isEmpty)
        #expect(graph.maxOccurrences == 1)            // guarded fallback, never 0
        #expect(graph.maxValue(for: .count) == 1)
    }

    // MARK: - HappyPath backward-compatible decoding

    @Test func happyPathDecodesLegacyJSONWithoutBranches() throws {
        let json = """
        {"id":"\(UUID().uuidString)","name":"Ideal","steps":["A","B","C"]}
        """.data(using: .utf8)!
        let path = try JSONDecoder().decode(HappyPath.self, from: json)
        #expect(path.name == "Ideal")
        #expect(path.steps == ["A", "B", "C"])
        #expect(path.branches.isEmpty)                // missing "branches" key → []
    }

    @Test func happyPathRoundTripsBranches() throws {
        let original = HappyPath(name: "Main", steps: ["A", "B"],
                                 branches: [HappyPathBranch(label: "alt", steps: ["B", "X"])])
        let data    = try JSONEncoder().encode(original)
        let decoded = try JSONDecoder().decode(HappyPath.self, from: data)
        #expect(decoded.name == "Main")
        #expect(decoded.branches.count == 1)
        #expect(decoded.branches.first?.steps == ["B", "X"])
    }

    // MARK: - Server definitions & connection pairing

    @Test func databaseServerHasSaneDefaultsAndRoundTrips() throws {
        var server = DatabaseServer()
        #expect(server.port == 8563)
        #expect(server.certModeRaw == "verify")
        #expect(server.minRSAKeySizeBits == 2048)

        server.name = "Prod"
        server.host = "db.example.com"
        let data    = try JSONEncoder().encode(server)
        let decoded = try JSONDecoder().decode(DatabaseServer.self, from: data)
        #expect(decoded == server)
    }

    @Test func llmServerRoundTrips() throws {
        var server = LLMServer()
        server.name      = "Local"
        server.serverURL = "http://localhost:1234/v1"
        server.model     = "qwen3"
        let data    = try JSONEncoder().encode(server)
        let decoded = try JSONDecoder().decode(LLMServer.self, from: data)
        #expect(decoded == server)
    }

    @Test func connectionProfileIsAPairingAndRoundTrips() throws {
        var profile = ConnectionProfile()
        #expect(profile.databaseServerId == nil)
        #expect(profile.llmServerId == nil)

        profile.name             = "Prod"
        profile.databaseServerId = UUID()
        profile.llmServerId      = UUID()
        let data    = try JSONEncoder().encode(profile)
        let decoded = try JSONDecoder().decode(ConnectionProfile.self, from: data)
        #expect(decoded == profile)
    }

    @Test func legacyProfileSplitsIntoServersAndPairing() {
        var legacy = DatabaseManager.LegacyConnectionProfile()
        legacy.name         = "Old"
        legacy.host         = "legacy.example.com"
        legacy.username     = "sys"
        legacy.llmServerURL = "http://localhost:1234/v1"
        legacy.llmModel     = "qwen3"

        let parts = DatabaseManager.splitLegacyProfile(legacy)

        // DB server id is preserved so the stored password key keeps working.
        #expect(parts.database.id == legacy.id)
        #expect(parts.database.host == "legacy.example.com")
        #expect(parts.database.username == "sys")

        // An LLM server is created and carried over.
        #expect(parts.llm != nil)
        #expect(parts.llm?.serverURL == "http://localhost:1234/v1")
        #expect(parts.llm?.model == "qwen3")

        // Pairing id preserved (so activeProfileId still matches) and references both.
        #expect(parts.profile.id == legacy.id)
        #expect(parts.profile.databaseServerId == legacy.id)
        #expect(parts.profile.llmServerId == parts.llm?.id)
    }

    @Test func legacyProfileWithoutLLMHasNoLLMServer() {
        var legacy = DatabaseManager.LegacyConnectionProfile()
        legacy.name = "DB only"
        legacy.host = "db.example.com"

        let parts = DatabaseManager.splitLegacyProfile(legacy)
        #expect(parts.llm == nil)
        #expect(parts.profile.llmServerId == nil)
        #expect(parts.profile.databaseServerId == parts.database.id)
    }

    // MARK: - ProcessNote.NoteTarget Codable

    @Test func noteTargetEdgeRoundTrips() throws {
        let target = ProcessNote.NoteTarget.edge(from: "A", to: "B")
        #expect(target.displayName == "A → B")
        #expect(target.isNode == false)
        let data    = try JSONEncoder().encode(target)
        let decoded = try JSONDecoder().decode(ProcessNote.NoteTarget.self, from: data)
        #expect(decoded == target)
    }

    @Test func noteTargetNodeRoundTrips() throws {
        let target = ProcessNote.NoteTarget.node("Checkout")
        #expect(target.displayName == "Checkout")
        #expect(target.isNode)
        let data    = try JSONEncoder().encode(target)
        let decoded = try JSONDecoder().decode(ProcessNote.NoteTarget.self, from: data)
        #expect(decoded == target)
    }

    // MARK: - AppAlert

    @Test func errorAlertWithRetryExposesSecondaryAction() {
        var retried = false
        let alert = AppAlert.error(title: "Oops", message: "Failed") { retried = true }
        #expect(alert.secondary != nil)
        #expect(alert.primary.label == "Retry")
        alert.primary.action?()
        #expect(retried)
    }

    @Test func errorAlertWithoutRetryIsInformational() {
        let alert = AppAlert.error(title: "Oops", message: "Failed")
        #expect(alert.secondary == nil)
        #expect(alert.primary.label == "OK")
    }

    // MARK: - Color hex helpers

    @Test func colorParsesAndReproducesHex() {
        #expect(Color.named("1A2B3C").hexString == "1A2B3C")
        #expect(Color.named("blue") == .blue)
    }
}

// MARK: - SimulationEngine Tests

struct SimulationEngineTests {

    // MARK: – Helpers

    private func step(_ name: String, endOfProcess: Bool = false) -> StepInfo {
        StepInfo(step: name, description: name, bgColor: "blue", fgColor: "white",
                 score: nil, shape: "stadium", endOfProcess: endOfProcess, belongsTo: nil)
    }

    private func edge(_ from: String, _ to: String, count: Int = 10,
                      avgSecs: Double? = 3600.0) -> ProcessTransition {
        ProcessTransition(fromStep: from, toStep: to, occurrences: count,
                          avgSecs: avgSecs, minSecs: nil, maxSecs: nil, stdDevSecs: nil)
    }

    /// Linear process: A → B → C  (C is the end step)
    private func linearGraph() -> (graph: ProcessGraph, stepInfos: [String: StepInfo]) {
        let infos: [String: StepInfo] = [
            "A": step("A"),
            "B": step("B"),
            "C": step("C", endOfProcess: true)
        ]
        return (ProcessGraph(steps: infos, transitions: [edge("A", "B"), edge("B", "C")]), infos)
    }

    /// Forked process: A → B → C  and  A → D → C  (C is the end step, equal weights)
    private func forkGraph() -> (graph: ProcessGraph, stepInfos: [String: StepInfo]) {
        let infos: [String: StepInfo] = [
            "A": step("A"), "B": step("B"),
            "D": step("D"), "C": step("C", endOfProcess: true)
        ]
        let g = ProcessGraph(steps: infos,
                             transitions: [edge("A","B"), edge("B","C"), edge("A","D"), edge("D","C")])
        return (g, infos)
    }

    private func config(journeyCount: Int = 100,
                        excluded: Set<String> = [],
                        required: Set<String> = []) -> SimulationConfig {
        var c = SimulationConfig()
        c.journeyCount  = journeyCount
        c.excludedSteps = excluded
        c.requiredSteps = required
        return c
    }

    // MARK: – Empty / boundary

    @Test func emptyGraphReturnsEmptyResult() {
        let result = SimulationEngine.simulate(graph: .empty, stepInfos: [:], config: config())
        #expect(result.totalJourneys == 0)
        #expect(result.events.isEmpty)
        #expect(result.variants.isEmpty)
        #expect(result.cycleTimes.isEmpty)
    }

    // MARK: – Journey count

    @Test func linearGraphProducesRequestedJourneyCount() {
        let (graph, infos) = linearGraph()
        let result = SimulationEngine.simulate(graph: graph, stepInfos: infos, config: config(journeyCount: 100))
        #expect(result.totalJourneys == 100)
        #expect(result.cycleTimes.count == 100)
    }

    @Test func linearJourneyVisitsEachStepExactlyOnce() {
        let (graph, infos) = linearGraph()
        let result = SimulationEngine.simulate(graph: graph, stepInfos: infos, config: config(journeyCount: 50))
        // A → B → C: 3 events per journey
        #expect(result.events.count == 150)
    }

    // MARK: – Event ordering

    @Test func eventsAreChronologicallyOrderedWithinJourney() {
        let (graph, infos) = linearGraph()
        let result = SimulationEngine.simulate(graph: graph, stepInfos: infos, config: config(journeyCount: 50))

        var byJourney: [String: [SimulatedEvent]] = [:]
        for e in result.events { byJourney[e.journeyId, default: []].append(e) }

        for (_, events) in byJourney {
            let timestamps = events.map(\.timestamp)
            #expect(timestamps == timestamps.sorted())
        }
    }

    // MARK: – Cycle times

    @Test func cycleTimesAreAllPositive() {
        let (graph, infos) = linearGraph()
        let result = SimulationEngine.simulate(graph: graph, stepInfos: infos, config: config(journeyCount: 50))
        #expect(result.cycleTimes.allSatisfy { $0 > 0 })
    }

    // MARK: – Statistics consistency

    @Test func statisticsAreConsistentWithCycleTimes() {
        let (graph, infos) = linearGraph()
        let result = SimulationEngine.simulate(graph: graph, stepInfos: infos, config: config(journeyCount: 100))

        let times = result.cycleTimes
        #expect(result.totalJourneys == times.count)
        #expect(result.minCycleTimeSecs == times.min()!)
        #expect(result.maxCycleTimeSecs == times.max()!)

        let avg = times.reduce(0, +) / Double(times.count)
        #expect(abs(result.avgCycleTimeSecs - avg) < 1e-6)
        #expect(result.stdDevCycleTimeSecs >= 0)
    }

    // MARK: – Variant accounting

    @Test func variantPercentagesSumToHundred() {
        let (graph, infos) = forkGraph()
        let result = SimulationEngine.simulate(graph: graph, stepInfos: infos, config: config(journeyCount: 100))
        let total = result.variants.map(\.percentage).reduce(0, +)
        #expect(abs(total - 100.0) < 1e-6)
    }

    @Test func variantCountsSumToTotalJourneys() {
        let (graph, infos) = forkGraph()
        let result = SimulationEngine.simulate(graph: graph, stepInfos: infos, config: config(journeyCount: 100))
        let sumCounts = result.variants.map(\.count).reduce(0, +)
        #expect(sumCounts == result.totalJourneys)
    }

    @Test func variantsAreSortedByCountDescending() {
        let (graph, infos) = forkGraph()
        let result = SimulationEngine.simulate(graph: graph, stepInfos: infos, config: config(journeyCount: 200))
        let counts = result.variants.map(\.count)
        #expect(zip(counts, counts.dropFirst()).allSatisfy { $0 >= $1 })
    }

    // MARK: – Variant path labels

    @Test func linearGraphHasExactlyOneVariantWithCorrectPath() {
        let (graph, infos) = linearGraph()
        let result = SimulationEngine.simulate(graph: graph, stepInfos: infos, config: config(journeyCount: 50))
        #expect(result.variants.count == 1)
        #expect(result.variants.first?.path == "A → B → C")
    }

    @Test func forkGraphProducesTwoVariantsWithCorrectPaths() {
        let (graph, infos) = forkGraph()
        // 200 journeys with equal 50/50 branch probability — both paths will appear
        let result = SimulationEngine.simulate(graph: graph, stepInfos: infos, config: config(journeyCount: 200))
        let paths = Set(result.variants.map(\.path))
        #expect(paths == ["A → B → C", "A → D → C"])
    }

    @Test func variantAvgCycleTimeSecsIsPositive() {
        let (graph, infos) = forkGraph()
        let result = SimulationEngine.simulate(graph: graph, stepInfos: infos, config: config(journeyCount: 100))
        #expect(result.variants.allSatisfy { $0.avgCycleTimeSecs > 0 })
    }

    // MARK: – Excluded steps

    @Test func excludedStepNeverAppearsInEvents() {
        let (graph, infos) = forkGraph()
        // Excluding D forces all journeys through the B-path
        let result = SimulationEngine.simulate(graph: graph, stepInfos: infos,
                                               config: config(journeyCount: 100, excluded: ["D"]))
        let stepsVisited = Set(result.events.map(\.step))
        #expect(!stepsVisited.contains("D"))
        #expect(result.totalJourneys == 100)
    }

    @Test func excludingAllTransitionsFromStartReturnsEmpty() {
        let (graph, infos) = linearGraph()
        // Excluding B removes A→B and B→C; no valid path exists from A
        let result = SimulationEngine.simulate(graph: graph, stepInfos: infos,
                                               config: config(journeyCount: 50, excluded: ["B"]))
        #expect(result.totalJourneys == 0)
    }

    // MARK: – Required steps

    @Test func requiredStepThatIsNeverVisitedFiltersAllJourneys() {
        let (graph, infos) = linearGraph()
        let result = SimulationEngine.simulate(graph: graph, stepInfos: infos,
                                               config: config(journeyCount: 50, required: ["MISSING"]))
        #expect(result.totalJourneys == 0)
    }

    @Test func requiredStepVisitedByEveryJourneyPreservesCount() {
        let (graph, infos) = linearGraph()
        // B is on every journey in the linear graph, so no journey should be dropped
        let result = SimulationEngine.simulate(graph: graph, stepInfos: infos,
                                               config: config(journeyCount: 50, required: ["B"]))
        #expect(result.totalJourneys == 50)
    }

    @Test func requiredStepOnOneForkBranchFiltersOtherBranch() {
        let (graph, infos) = forkGraph()
        // B only appears in A→B→C journeys; A→D→C journeys must be discarded
        let result = SimulationEngine.simulate(graph: graph, stepInfos: infos,
                                               config: config(journeyCount: 200, required: ["B"]))
        #expect(result.totalJourneys > 0)
        let stepsVisited = Set(result.events.map(\.step))
        #expect(!stepsVisited.contains("D"))
    }

    @Test func mutuallyExclusiveRequiredStepsYieldNoJourneys() {
        let (graph, infos) = forkGraph()
        // B and D are on separate branches — no single journey visits both
        let result = SimulationEngine.simulate(graph: graph, stepInfos: infos,
                                               config: config(journeyCount: 100, required: ["B", "D"]))
        #expect(result.totalJourneys == 0)
    }

    // MARK: – Cyclic graph / maxStepsPerJourney

    @Test func cyclicGraphRespectsMaxStepsPerJourney() {
        // A → B → A with no end step — would loop forever without the cap
        let infos: [String: StepInfo] = ["A": step("A"), "B": step("B")]
        let g = ProcessGraph(steps: infos, transitions: [edge("A", "B"), edge("B", "A")])
        var cfg = SimulationConfig()
        cfg.journeyCount       = 20
        cfg.maxStepsPerJourney = 4
        let result = SimulationEngine.simulate(graph: g, stepInfos: infos, config: cfg)
        #expect(result.totalJourneys == 20)
        var byJourney: [String: [SimulatedEvent]] = [:]
        for e in result.events { byJourney[e.journeyId, default: []].append(e) }
        // First step + at most maxStepsPerJourney transitions = 5 events max
        for (_, events) in byJourney {
            #expect(events.count <= cfg.maxStepsPerJourney + 1)
        }
    }

    // MARK: – buildGraph

    @Test func buildGraphFromEmptyEventsIsEmpty() {
        let graph = SimulationEngine.buildGraph(from: [], stepInfos: [:])
        #expect(graph.transitions.isEmpty)
        #expect(graph.steps.isEmpty)
    }

    @Test func buildGraphComputesCorrectTransitionStats() throws {
        let base = Date(timeIntervalSince1970: 1_700_000_000)
        let events: [SimulatedEvent] = [
            SimulatedEvent(journeyId: "J1", step: "A", timestamp: base),
            SimulatedEvent(journeyId: "J1", step: "B", timestamp: base.addingTimeInterval(7200)), // dur = 7200s
            SimulatedEvent(journeyId: "J2", step: "A", timestamp: base.addingTimeInterval(100)),
            SimulatedEvent(journeyId: "J2", step: "B", timestamp: base.addingTimeInterval(3700)), // dur = 3600s
        ]
        let graph = SimulationEngine.buildGraph(from: events, stepInfos: [:])

        #expect(graph.transitions.count == 1)
        let t = try #require(graph.transitions.first)
        #expect(t.fromStep == "A" && t.toStep == "B")
        #expect(t.occurrences == 2)
        // avg of 7200s and 3600s = 5400s
        #expect(abs((t.avgSecs ?? 0) - 5400.0) < 1.0)
    }

    @Test func buildGraphComputesMinMaxAndStdDev() throws {
        let base = Date(timeIntervalSince1970: 1_700_000_000)
        // Three A→B traversals with durations 1000s, 2000s, 3000s
        // avg=2000, min=1000, max=3000, stdDev=sqrt((1e6+0+1e6)/3)≈816.5
        let events: [SimulatedEvent] = [
            SimulatedEvent(journeyId: "J1", step: "A", timestamp: base),
            SimulatedEvent(journeyId: "J1", step: "B", timestamp: base.addingTimeInterval(1000)),
            SimulatedEvent(journeyId: "J2", step: "A", timestamp: base.addingTimeInterval(5000)),
            SimulatedEvent(journeyId: "J2", step: "B", timestamp: base.addingTimeInterval(7000)),
            SimulatedEvent(journeyId: "J3", step: "A", timestamp: base.addingTimeInterval(10000)),
            SimulatedEvent(journeyId: "J3", step: "B", timestamp: base.addingTimeInterval(13000)),
        ]
        let graph = SimulationEngine.buildGraph(from: events, stepInfos: [:])
        let t = try #require(graph.transitions.first)
        #expect(t.occurrences == 3)
        #expect(abs((t.minSecs ?? 0) - 1000.0) < 1.0)
        #expect(abs((t.maxSecs ?? 0) - 3000.0) < 1.0)
        // Population stdDev: sqrt((1_000_000 + 0 + 1_000_000) / 3) ≈ 816.5
        #expect(abs((t.stdDevSecs ?? 0) - 816.5) < 1.0)
    }

    @Test func buildGraphSortsEventsByTimestampWithinJourney() throws {
        let base = Date(timeIntervalSince1970: 1_700_000_000)
        // Events provided in reverse order — buildGraph must sort by timestamp
        let events: [SimulatedEvent] = [
            SimulatedEvent(journeyId: "J1", step: "B", timestamp: base.addingTimeInterval(3600)),
            SimulatedEvent(journeyId: "J1", step: "A", timestamp: base),
        ]
        let graph = SimulationEngine.buildGraph(from: events, stepInfos: [:])
        let t = try #require(graph.transitions.first)
        // Must be A→B, not B→A
        #expect(t.fromStep == "A" && t.toStep == "B")
        #expect(abs((t.avgSecs ?? 0) - 3600.0) < 1.0)
    }

    @Test func buildGraphContainsAllVisitedSteps() {
        let base = Date(timeIntervalSince1970: 1_700_000_000)
        let events: [SimulatedEvent] = [
            SimulatedEvent(journeyId: "J1", step: "X", timestamp: base),
            SimulatedEvent(journeyId: "J1", step: "Y", timestamp: base.addingTimeInterval(60)),
        ]
        let graph = SimulationEngine.buildGraph(from: events, stepInfos: [:])
        #expect(graph.steps.keys.sorted() == ["X", "Y"])
    }

    // MARK: – simProcessGraph

    @Test func simulatedGraphContainsExpectedTransitions() {
        let (graph, infos) = linearGraph()
        let result = SimulationEngine.simulate(graph: graph, stepInfos: infos, config: config(journeyCount: 50))
        let ids = Set(result.simProcessGraph.transitions.map(\.id))
        #expect(ids == ["A->B", "B->C"])
    }

    @Test func simulatedGraphTransitionOccurrencesMatchJourneyCount() {
        let (graph, infos) = linearGraph()
        let result = SimulationEngine.simulate(graph: graph, stepInfos: infos, config: config(journeyCount: 50))
        let ab = result.simProcessGraph.transitions.first { $0.id == "A->B" }
        let bc = result.simProcessGraph.transitions.first { $0.id == "B->C" }
        // Linear graph: every journey crosses each edge exactly once
        #expect(ab?.occurrences == 50)
        #expect(bc?.occurrences == 50)
    }
}
