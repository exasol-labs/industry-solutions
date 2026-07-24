import Foundation

// MARK: - A/B side (used in A/B Comparison mode)

enum ABSide: Equatable { case a, b }

// MARK: - Date slider mode

enum SliderMode: String, CaseIterable, Identifiable {
    case range     = "Range"
    case singleDay = "Day"
    var id: String { rawValue }
}

// MARK: - Chart view mode (owned here so both ViewModel and View can reference it)

enum DetailViewMode: String, CaseIterable, Identifiable {
    case aChart             = "A-Chart"
    case bChart             = "B-Chart"
    case abComparison       = "A/B Comparison"
    case individualJourney  = "Individual Journey"
    case aiAnalysis         = "AI supported Documentation"
    case statistics         = "Statistics"
    case complianceCheck    = "Conformance Check"
    case happyPath          = "Happy Path"
    case comments           = "Notes"
    case simulation         = "Simulation"

    var id: String { rawValue }

    var icon: String {
        switch self {
        case .aChart:            return "chart.xyaxis.line"
        case .bChart:            return "chart.xyaxis.line"
        case .abComparison:      return "arrow.left.arrow.right.circle"
        case .individualJourney: return "person.crop.rectangle.stack"
        case .aiAnalysis:        return "brain"
        case .statistics:        return "chart.bar.fill"
        case .complianceCheck:   return "checkmark.shield.fill"
        case .happyPath:         return "signpost.right.fill"
        case .comments:          return "note.text"
        case .simulation:        return "chart.line.flattrend.xyaxis"
        }
    }
}

// MARK: - Per-chart filter + result state

struct ChartFilterState {
    var fromDate:         Date
    var toDate:           Date
    var includedSteps:    Set<String>
    var excludedSteps:    Set<String>
    var meta1Filter:      String
    var meta2Filter:      String
    var meta3Filter:      String
    var eventIdFilter:    String        // used by .individualJourney only
    var journeyDate:      Date?         // first event time of the loaded individual journey
    var journeyEndDate:   Date?         // last event time of the loaded individual journey
    var processGraph:        ProcessGraph
    var journeyCount:        Int?
    var transitionMetric:    TransitionMetric
    var minJourneyDuration:    Double?
    var avgJourneyDuration:    Double?
    var stdDevJourneyDuration: Double?
    var maxJourneyDuration:    Double?
    var minStepsFilter:      Int
    var maxStepsFilter:      Int
    var minJourneyTimeFilter: Int
    var maxJourneyTimeFilter: Int
    var minScoreFilter:       Int
    var maxScoreFilter:       Int
    var processGoodness:      Double?  = nil

    static func defaultState(from: Date, to: Date,
                             minSteps: Int = 0, maxSteps: Int = Int.max,
                             minJourneyTime: Int = 0, maxJourneyTime: Int = Int.max,
                             minScore: Int = Int.min, maxScore: Int = Int.max) -> ChartFilterState {
        ChartFilterState(
            fromDate:             from,
            toDate:               to,
            includedSteps:        [],
            excludedSteps:        [],
            meta1Filter:          "",
            meta2Filter:          "",
            meta3Filter:          "",
            eventIdFilter:        "",
            journeyDate:          nil,
            journeyEndDate:       nil,
            processGraph:         .empty,
            journeyCount:         nil,
            transitionMetric:     .count,
            minJourneyDuration:   nil,
            avgJourneyDuration:   nil,
            stdDevJourneyDuration: nil,
            maxJourneyDuration:   nil,
            minStepsFilter:       minSteps,
            maxStepsFilter:       maxSteps,
            minJourneyTimeFilter: minJourneyTime,
            maxJourneyTimeFilter: maxJourneyTime,
            minScoreFilter:       minScore,
            maxScoreFilter:       maxScore
        )
    }
}
