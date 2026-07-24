import Foundation

// MARK: - Configuration

struct SimulationConfig: Sendable {
    var journeyCount:         Int    = 200
    var startDate:            Date   = Date()
    var avgInterArrivalHours: Double = 2.0
    var excludedSteps:        Set<String> = []
    var requiredSteps:        Set<String> = []
    var maxStepsPerJourney:   Int    = 60
}

// MARK: - Output models

struct SimulatedEvent: Identifiable, Sendable {
    let id:        UUID   = UUID()
    let journeyId: String
    let step:      String
    let timestamp: Date
}

struct SimulationVariant: Identifiable, Sendable {
    let id:               UUID   = UUID()
    let path:             String
    let count:            Int
    let percentage:       Double
    let avgCycleTimeSecs: Double
}

struct SimulationResult: Sendable {
    let runId             = UUID()               // unique per run — used as FlowChartView .id() to force remount + re-fit
    let events:               [SimulatedEvent]
    let variants:             [SimulationVariant]
    let cycleTimes:           [Double]          // per-journey cycle time in seconds
    let simProcessGraph:      ProcessGraph      // aggregated directly-follows graph for FlowChartView
    let totalJourneys:        Int
    let avgCycleTimeSecs:     Double
    let minCycleTimeSecs:     Double
    let maxCycleTimeSecs:     Double
    let stdDevCycleTimeSecs:  Double

    static let empty = SimulationResult(
        events: [], variants: [], cycleTimes: [], simProcessGraph: .empty, totalJourneys: 0,
        avgCycleTimeSecs: 0, minCycleTimeSecs: 0, maxCycleTimeSecs: 0,
        stdDevCycleTimeSecs: 0
    )
}

// MARK: - Engine

enum SimulationEngine {

    static func simulate(
        graph:     ProcessGraph,
        stepInfos: [String: StepInfo],
        config:    SimulationConfig
    ) -> SimulationResult {

        let model = MarkovModel(graph: graph, stepInfos: stepInfos, excluded: config.excludedSteps)
        guard !model.startSteps.isEmpty else { return .empty }

        var allEvents:  [SimulatedEvent]                           = []
        var cycleSecs:  [Double]                                   = []
        var variantMap: [String: (count: Int, totalSecs: Double)]  = [:]

        let lambdaSecs  = config.avgInterArrivalHours * 3600.0
        var arrivalTime = config.startDate

        var generated   = 0
        let maxAttempts = max(config.journeyCount * 20, 1000)

        for _ in 0 ..< maxAttempts {
            guard generated < config.journeyCount else { break }

            // Exponential inter-arrival (Poisson process)
            let u = Double.random(in: 1e-10 ... 1.0)
            arrivalTime = arrivalTime.addingTimeInterval(-lambdaSecs * log(u))

            guard let journey = simulateJourney(
                model:     model,
                startTime: arrivalTime,
                journeyId: "SIM-\(generated + 1)",
                maxSteps:  config.maxStepsPerJourney
            ) else { continue }

            // Required-steps filter: discard journeys that don't pass through all required steps
            if !config.requiredSteps.isEmpty {
                let visitedSteps = Set(journey.events.map(\.step))
                guard config.requiredSteps.isSubset(of: visitedSteps) else { continue }
            }

            allEvents.append(contentsOf: journey.events)
            cycleSecs.append(journey.cycleTimeSecs)

            let prev = variantMap[journey.path] ?? (0, 0.0)
            variantMap[journey.path] = (prev.0 + 1, prev.1 + journey.cycleTimeSecs)
            generated += 1
        }

        guard !cycleSecs.isEmpty else { return .empty }

        let avg      = cycleSecs.reduce(0, +) / Double(cycleSecs.count)
        let variance = cycleSecs.map { pow($0 - avg, 2) }.reduce(0, +) / Double(cycleSecs.count)
        let total    = Double(generated)

        let variants: [SimulationVariant] = variantMap
            .map { path, stat in
                SimulationVariant(
                    path:             path,
                    count:            stat.count,
                    percentage:       Double(stat.count) / total * 100.0,
                    avgCycleTimeSecs: stat.count > 0 ? stat.totalSecs / Double(stat.count) : 0
                )
            }
            .sorted { $0.count > $1.count }

        return SimulationResult(
            events:              allEvents,
            variants:            variants,
            cycleTimes:          cycleSecs,
            simProcessGraph:     buildGraph(from: allEvents, stepInfos: stepInfos),
            totalJourneys:       generated,
            avgCycleTimeSecs:    avg,
            minCycleTimeSecs:    cycleSecs.min() ?? 0,
            maxCycleTimeSecs:    cycleSecs.max() ?? 0,
            stdDevCycleTimeSecs: sqrt(variance)
        )
    }

    // MARK: – Build ProcessGraph from event log

    static func buildGraph(from events: [SimulatedEvent], stepInfos: [String: StepInfo]) -> ProcessGraph {
        var byJourney: [String: [SimulatedEvent]] = [:]
        for e in events { byJourney[e.journeyId, default: []].append(e) }

        struct TKey: Hashable { let from, to: String }
        struct TStats {
            var count  = 0
            var total  = 0.0
            var mn     = Double.infinity
            var mx     = -Double.infinity
            var sumSq  = 0.0
        }

        var stats: [TKey: TStats] = [:]
        var stepSet: Set<String>  = []

        for (_, evs) in byJourney {
            let sorted = evs.sorted { $0.timestamp < $1.timestamp }
            for i in sorted.indices {
                stepSet.insert(sorted[i].step)
                guard i + 1 < sorted.count else { continue }
                let secs = sorted[i + 1].timestamp.timeIntervalSince(sorted[i].timestamp)
                let k    = TKey(from: sorted[i].step, to: sorted[i + 1].step)
                var s    = stats[k] ?? TStats()
                s.count += 1; s.total += secs
                s.mn = min(s.mn, secs); s.mx = max(s.mx, secs)
                s.sumSq += secs * secs
                stats[k] = s
            }
        }

        let transitions: [ProcessTransition] = stats.map { k, s in
            let avg = s.total / Double(s.count)
            let std = sqrt(max(0, s.sumSq / Double(s.count) - avg * avg))
            return ProcessTransition(
                fromStep:   k.from, toStep:    k.to,
                occurrences: s.count,
                avgSecs:     avg,
                minSecs:     s.mn.isFinite ? s.mn : nil,
                maxSecs:     s.mx.isFinite ? s.mx : nil,
                stdDevSecs:  std > 0 ? std : nil
            )
        }

        var steps: [String: StepInfo] = [:]
        for step in stepSet {
            steps[step] = stepInfos[step] ?? StepInfo(
                step: step, description: step,
                bgColor: "blue", fgColor: "white",
                score: nil, shape: "stadium",
                endOfProcess: false, belongsTo: nil
            )
        }

        return ProcessGraph(steps: steps, transitions: transitions)
    }

    // MARK: – Single journey

    private struct JourneyResult {
        let events:        [SimulatedEvent]
        let path:          String
        let cycleTimeSecs: Double
    }

    private static func simulateJourney(
        model:     MarkovModel,
        startTime: Date,
        journeyId: String,
        maxSteps:  Int
    ) -> JourneyResult? {
        guard let first = model.sampleStartStep() else { return nil }

        var events:      [SimulatedEvent] = []
        var currentStep  = first
        var currentTime  = startTime
        var pathSteps:   [String]         = [first]

        events.append(SimulatedEvent(journeyId: journeyId, step: first, timestamp: currentTime))

        for _ in 0 ..< maxSteps {
            let isEnd = model.stepInfos[currentStep]?.endOfProcess ?? false
            guard !isEnd, let next = model.sampleNextStep(from: currentStep) else { break }

            let dur     = model.sampleDuration(from: currentStep, to: next)
            currentTime = currentTime.addingTimeInterval(dur)
            currentStep = next
            pathSteps.append(next)
            events.append(SimulatedEvent(journeyId: journeyId, step: next, timestamp: currentTime))

            if model.stepInfos[next]?.endOfProcess ?? false { break }
        }

        return JourneyResult(
            events:        events,
            path:          pathSteps.joined(separator: " → "),
            cycleTimeSecs: currentTime.timeIntervalSince(startTime)
        )
    }
}

// MARK: - Markov model

private struct MarkovModel {

    let stepInfos:      [String: StepInfo]
    // fromStep → [(toStep, cumulative probability)]
    let transitions:    [String: [(step: String, cumProb: Double)]]
    // (from→to) → (mu, sigma) of fitted lognormal in log-seconds
    let durationParams: [String: (mu: Double, sigma: Double)]
    // (step, weight) pairs for sampling the first step of a journey
    let startSteps:     [(step: String, weight: Double)]

    init(graph: ProcessGraph, stepInfos: [String: StepInfo], excluded: Set<String>) {

        // ── 1. Identify start steps from the ORIGINAL graph (before exclusions) ─
        // This is the critical step. If we compute in-degrees from the filtered
        // graph, a step B that only received edges from excluded step A will
        // have in-degree 0 after A is removed — making it look like a process
        // entry point. Reading the original in-degrees prevents that: B's
        // original in-degree is > 0, so it is never placed in startSet.
        // User-excluded steps are then removed from startSet explicitly.
        var origInC:  [String: Int] = [:]
        var origOutC: [String: Int] = [:]
        for t in graph.transitions {
            origInC [t.toStep,   default: 0] += t.occurrences
            origOutC[t.fromStep, default: 0] += t.occurrences
        }

        var startSet: Set<String> = []
        for (step, oc) in origOutC {
            let ic = Double(origInC[step] ?? 0)
            if ic / Double(oc) < 0.2 { startSet.insert(step) }
        }
        if startSet.isEmpty, let best = origOutC.max(by: { $0.value < $1.value }) {
            startSet.insert(best.key)
        }
        startSet.subtract(excluded)   // excluded start steps cannot seed journeys

        // ── 2. Apply user-specified exclusions to transitions ─────────────────
        let filtered = graph.transitions.filter {
            !excluded.contains($0.fromStep) && !excluded.contains($0.toStep)
        }

        // ── 3. BFS reachability from the true start steps ───────────────────
        // Propagates forward through the filtered graph. Any step not reached
        // from startSet — including steps that only received edges from excluded
        // steps (or from steps that themselves became unreachable) — is pruned.
        var adj: [String: [String]] = [:]
        for t in filtered { adj[t.fromStep, default: []].append(t.toStep) }

        var reachable: Set<String> = []
        var queue = Array(startSet)
        while !queue.isEmpty {
            let step = queue.removeFirst()
            guard reachable.insert(step).inserted else { continue }
            for next in adj[step, default: []] where !reachable.contains(next) {
                queue.append(next)
            }
        }

        // ── 4. Prune to reachable transitions only ──────────────────────────
        let valid = filtered.filter {
            reachable.contains($0.fromStep) && reachable.contains($0.toStep)
        }

        // ── 5. Build the Markov model from the pruned transition set ─────────
        self.stepInfos = stepInfos.filter { reachable.contains($0.key) }

        // Transition probability matrix
        var out: [String: [(step: String, count: Int)]] = [:]
        for t in valid { out[t.fromStep, default: []].append((t.toStep, t.occurrences)) }

        var trans: [String: [(step: String, cumProb: Double)]] = [:]
        for (from, tos) in out {
            let total = Double(tos.map(\.count).reduce(0, +))
            guard total > 0 else { continue }
            var cum = 0.0
            trans[from] = tos.map { e in
                cum += Double(e.count) / total
                return (e.step, cum)
            }
        }
        self.transitions = trans

        // Lognormal duration parameters per edge
        var dp: [String: (mu: Double, sigma: Double)] = [:]
        for t in valid {
            let key = "\(t.fromStep)→\(t.toStep)"
            if let avg = t.avgSecs, avg > 0 {
                if let sd = t.stdDevSecs, sd > 0 {
                    let v   = sd * sd
                    let mu  = log(avg * avg / sqrt(avg * avg + v))
                    let sig = sqrt(log(1.0 + v / (avg * avg)))
                    dp[key] = (mu, sig)
                } else {
                    dp[key] = (log(avg), 0.0)
                }
            } else {
                dp[key] = (log(3600.0), 0.5)
            }
        }
        self.durationParams = dp

        // Start step weights re-derived from the pruned graph so that an
        // excluded step's share is redistributed rather than left as a gap.
        var prunedOutC: [String: Int] = [:]
        for t in valid { prunedOutC[t.fromStep, default: 0] += t.occurrences }

        let validStart  = startSet.filter { prunedOutC[$0] != nil }
        let startTotal  = Double(validStart.compactMap { prunedOutC[$0] }.reduce(0, +))

        if validStart.isEmpty {
            self.startSteps = []
        } else {
            self.startSteps = validStart.map {
                ($0, Double(prunedOutC[$0] ?? 1) / max(startTotal, 1.0))
            }
        }
    }

    func sampleStartStep() -> String? {
        guard !startSteps.isEmpty else { return nil }
        let r = Double.random(in: 0.0 ... 1.0)
        var cum = 0.0
        for (step, w) in startSteps { cum += w; if r <= cum { return step } }
        return startSteps.last?.step
    }

    func sampleNextStep(from step: String) -> String? {
        guard let tos = transitions[step], !tos.isEmpty else { return nil }
        let r = Double.random(in: 0.0 ... 1.0)
        for (next, cp) in tos { if r <= cp { return next } }
        return tos.last?.step
    }

    func sampleDuration(from: String, to: String) -> TimeInterval {
        guard let p = durationParams["\(from)→\(to)"] else { return 3600.0 }
        guard p.sigma > 0 else { return max(60.0, exp(p.mu)) }
        // Box-Muller transform → standard normal → scale to lognormal
        let u1 = Double.random(in: 1e-10 ... 1.0)
        let u2 = Double.random(in: 0.0 ... 1.0)
        let z  = sqrt(-2.0 * log(u1)) * cos(2.0 * .pi * u2)
        return max(60.0, exp(p.mu + p.sigma * z))
    }
}
