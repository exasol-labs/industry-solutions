import Foundation
import ExasolConnector

final class ProcessRepository {
    private let db: DatabaseManager

    init(db: DatabaseManager = .shared) {
        self.db = db
    }

    var activeSampleSet: SampleSet = .original

    func loadProjects() async throws -> [Project] {
        let result = try await db.execute(
            "SELECT PROJECT_ID, TITLE, DESCRIPTION FROM PROJECTS ORDER BY TITLE"
        )
        return result.rows.compactMap { row in
            guard let id    = row[0] as? String,
                  let title = row[1] as? String else { return nil }
            return Project(
                projectId:   id,
                title:       title,
                description: row[2] as? String ?? ""
            )
        }
    }

    func loadSteps(projectId: String) async throws -> [String: StepInfo] {
        let safe = projectId.replacingOccurrences(of: "'", with: "''")
        let result = try await db.execute("""
            SELECT STEP, DESCRIPTION, BG_COLOR, FG_COLOR, SCORE, SHAPE, END_OF_PROCESS, BELONGS_TO
            FROM STEPS
            WHERE PROJECT_ID = '\(safe)'
            """)
        var map: [String: StepInfo] = [:]
        for row in result.rows {
            guard let step = row[0] as? String else { continue }
            let score: Int?
            if let i = row[4] as? Int         { score = i }
            else if let d = row[4] as? Double  { score = Int(d) }
            else                               { score = nil }

            let endOf: Bool
            if let i = row[6] as? Int          { endOf = i != 0 }
            else if let d = row[6] as? Double  { endOf = d != 0 }
            else                               { endOf = false }

            let belongsTo = row.count > 7 ? row[7] as? String : nil

            map[step] = StepInfo(
                step:         step,
                description:  row[1] as? String ?? step,
                bgColor:      row[2] as? String ?? "blue",
                fgColor:      row[3] as? String ?? "white",
                score:        score,
                shape:        row[5] as? String ?? "stadium",
                endOfProcess: endOf,
                belongsTo:    belongsTo
            )
        }
        return map
    }

    func updateStep(
        projectId: String, step: String,
        bgColor: String, fgColor: String,
        score: Int?, shape: String, belongsTo: String?, description: String?
    ) async throws {
        func esc(_ s: String) -> String { s.replacingOccurrences(of: "'", with: "''") }
        let scoreSQL   = score.map     { "SCORE = \($0)" }              ?? "SCORE = NULL"
        let belongsSQL = belongsTo.map { "BELONGS_TO = '\(esc($0))'" }  ?? "BELONGS_TO = NULL"
        let descSQL    = description.map { "DESCRIPTION = '\(esc($0))'" } ?? "DESCRIPTION = DESCRIPTION"
        _ = try await db.execute("""
            UPDATE STEPS
            SET BG_COLOR = '\(esc(bgColor))',
                FG_COLOR = '\(esc(fgColor))',
                \(scoreSQL),
                SHAPE = '\(esc(shape))',
                \(belongsSQL),
                \(descSQL)
            WHERE PROJECT_ID = '\(esc(projectId))'
            AND STEP = '\(esc(step))'
            """)
    }

    func loadJourneyTimeBounds(projectId: String) async throws -> (min: Int, max: Int) {
        let safe = projectId.replacingOccurrences(of: "'", with: "''")
        let result = try await db.execute("""
            SELECT MIN(dur), MAX(dur)
            FROM (
                SELECT SECONDS_BETWEEN(MAX(EVENT_TIME), MIN(EVENT_TIME)) AS dur
                FROM JOURNEYS
                WHERE PROJECT_ID = '\(safe)'
                AND \(activeSampleSet.sqlFragment())
                GROUP BY EVENT_ID
            ) AS j
            """)
        guard let row = result.rows.first else { return (0, 0) }
        func int(_ v: Any?) -> Int {
            if let i = v as? Int           { return i }
            if let d = v as? Double        { return Int(d) }
            if let f = v as? Float         { return Int(f) }
            if let n = v as? NSNumber      { return n.intValue }
            if let d = v as? Decimal       { return NSDecimalNumber(decimal: d).intValue }
            if let s = v as? String        { return Int(Double(s) ?? 0) }
            return 0
        }
        return (max(0, int(row[0])), max(0, int(row[1])))
    }

    func loadStepCountBounds(projectId: String) async throws -> (min: Int, max: Int) {
        let safe = projectId.replacingOccurrences(of: "'", with: "''")
        let result = try await db.execute("""
            SELECT MIN(cnt), MAX(cnt)
            FROM (
                SELECT COUNT(*) AS cnt
                FROM JOURNEYS
                WHERE PROJECT_ID = '\(safe)'
                AND \(activeSampleSet.sqlFragment())
                GROUP BY EVENT_ID
            ) AS j
            """)
        guard let row = result.rows.first else { return (1, 1) }
        func int(_ v: Any?) -> Int {
            if let i = v as? Int           { return i }
            if let d = v as? Double        { return Int(d) }
            if let f = v as? Float         { return Int(f) }
            if let n = v as? NSNumber      { return n.intValue }
            if let d = v as? Decimal       { return NSDecimalNumber(decimal: d).intValue }
            if let s = v as? String        { return Int(Double(s) ?? 1) }
            return 1
        }
        return (int(row[0]), int(row[1]))
    }

    func loadScoreBounds(projectId: String) async throws -> (min: Int, max: Int) {
        let safe = projectId.replacingOccurrences(of: "'", with: "''")
        let result = try await db.execute("""
            SELECT MIN(journey_score), MAX(journey_score)
            FROM (
                SELECT j.EVENT_ID, SUM(COALESCE(s.SCORE, 0)) AS journey_score
                FROM JOURNEYS j
                LEFT JOIN STEPS s ON j.STEP = s.STEP AND j.PROJECT_ID = s.PROJECT_ID
                WHERE j.PROJECT_ID = '\(safe)'
                AND \(activeSampleSet.sqlFragment(alias: "j"))
                GROUP BY j.EVENT_ID
            ) AS scored
            """)
        guard let row = result.rows.first else { return (0, 0) }
        func int(_ v: Any?) -> Int {
            if let i = v as? Int           { return i }
            if let d = v as? Double        { return Int(d) }
            if let f = v as? Float         { return Int(f) }
            if let n = v as? NSNumber      { return n.intValue }
            if let d = v as? Decimal       { return NSDecimalNumber(decimal: d).intValue }
            if let s = v as? String        { return Int(Double(s) ?? 0) }
            return 0
        }
        return (int(row[0]), int(row[1]))
    }

    func loadJourneyCount(
        projectId: String,
        from: Date? = nil, to: Date? = nil,
        included: [String] = [], excluded: [String] = [],
        meta1: String = "", meta2: String = "", meta3: String = "",
        minSteps: Int = 0, maxSteps: Int = Int.max,
        minJourneyTime: Int = 0, maxJourneyTime: Int = Int.max,
        minScore: Int = Int.min, maxScore: Int = Int.max
    ) async throws -> Int {
        let safe = projectId.replacingOccurrences(of: "'", with: "''")
        let filters = sampleSetClause()
                    + dateClause(from: from, to: to)
                    + stepClause(included: included, excluded: excluded, projectId: safe)
                    + metaClause(meta1: meta1, meta2: meta2, meta3: meta3)
                    + stepsClause(min: minSteps, max: maxSteps, projectId: safe)
                    + journeyTimeClause(minSecs: minJourneyTime, maxSecs: maxJourneyTime, projectId: safe)
                    + scoreClause(min: minScore, max: maxScore, projectId: safe)
        let result = try await db.execute("""
            SELECT COUNT(DISTINCT EVENT_ID)
            FROM JOURNEYS
            WHERE PROJECT_ID = '\(safe)'\(filters)
            """)
        guard let row = result.rows.first, let val = row[0] else { return 0 }
        if let i = val as? Int    { return i }
        if let d = val as? Double { return Int(d) }
        return 0
    }

    func loadMetaTitles(projectId: String) async throws -> (String?, String?, String?) {
        let safe = projectId.replacingOccurrences(of: "'", with: "''")
        let result = try await db.execute("""
            SELECT META_1_TITLE, META_2_TITLE, META_3_TITLE
            FROM METAS
            WHERE PROJECT_ID = '\(safe)'
            """)
        guard let row = result.rows.first else { return (nil, nil, nil) }
        func clean(_ v: Any?) -> String? {
            guard let s = v as? String, !s.trimmingCharacters(in: .whitespaces).isEmpty else { return nil }
            return s.trimmingCharacters(in: .whitespaces)
        }
        return (clean(row[0]), clean(row[1]), clean(row[2]))
    }

    func loadMetaValues(projectId: String, column: String) async throws -> [String] {
        let safe = projectId.replacingOccurrences(of: "'", with: "''")
        let result = try await db.execute("""
            SELECT DISTINCT \(column)
            FROM JOURNEYS
            WHERE PROJECT_ID = '\(safe)'
            AND \(activeSampleSet.sqlFragment())
            AND \(column) IS NOT NULL
            ORDER BY \(column)
            """)
        return result.rows.compactMap { $0[0] as? String }
    }

    func loadAllStepNames(projectId: String) async throws -> [String] {
        let safe = projectId.replacingOccurrences(of: "'", with: "''")
        let result = try await db.execute(
            "SELECT DISTINCT STEP FROM JOURNEYS WHERE PROJECT_ID = '\(safe)' AND \(activeSampleSet.sqlFragment()) ORDER BY STEP"
        )
        return result.rows.compactMap { $0[0] as? String }
    }

    func loadMaxDate(projectId: String) async throws -> Date? {
        let safe = projectId.replacingOccurrences(of: "'", with: "''")
        let result = try await db.execute(
            "SELECT MAX(EVENT_TIME) FROM JOURNEYS WHERE PROJECT_ID = '\(safe)' AND \(activeSampleSet.sqlFragment())"
        )
        guard let row = result.rows.first, let val = row[0] else { return nil }
        if let str = val as? String {
            for fmt in ["yyyy-MM-dd HH:mm:ss.SSSSSS", "yyyy-MM-dd HH:mm:ss", "yyyy-MM-dd"] {
                let df = DateFormatter(); df.dateFormat = fmt
                if let d = df.date(from: str) { return d }
            }
        }
        return val as? Date
    }

    func loadDateBounds(projectId: String) async throws -> (min: Date?, max: Date?) {
        let safe = projectId.replacingOccurrences(of: "'", with: "''")
        let result = try await db.execute(
            "SELECT MIN(EVENT_TIME), MAX(EVENT_TIME) FROM JOURNEYS WHERE PROJECT_ID = '\(safe)' AND \(activeSampleSet.sqlFragment())"
        )
        guard let row = result.rows.first else { return (nil, nil) }
        func parse(_ val: Any?) -> Date? {
            guard let val else { return nil }
            if let str = val as? String {
                for fmt in ["yyyy-MM-dd HH:mm:ss.SSSSSS", "yyyy-MM-dd HH:mm:ss", "yyyy-MM-dd"] {
                    let df = DateFormatter(); df.dateFormat = fmt
                    if let d = df.date(from: str) { return d }
                }
            }
            return val as? Date
        }
        return (parse(row[0]), parse(row[1]))
    }

    func findNearestDayWithData(relativeTo day: Date, projectId: String) async throws -> Date? {
        let safe = projectId.replacingOccurrences(of: "'", with: "''")
        let cal  = Calendar.current
        let df   = DateFormatter()
        df.dateFormat = "yyyy-MM-dd"

        func parse(_ val: Any?) -> Date? {
            guard let val else { return nil }
            if let str = val as? String {
                for fmt in ["yyyy-MM-dd HH:mm:ss.SSSSSS", "yyyy-MM-dd HH:mm:ss", "yyyy-MM-dd"] {
                    let f = DateFormatter(); f.dateFormat = fmt
                    if let d = f.date(from: str) { return d }
                }
            }
            return val as? Date
        }

        // Try the first day strictly after the selected day
        let nextDay  = cal.date(byAdding: .day, value: 1, to: cal.startOfDay(for: day))!
        let fwdResult = try await db.execute(
            "SELECT MIN(EVENT_TIME) FROM JOURNEYS WHERE PROJECT_ID = '\(safe)' AND \(activeSampleSet.sqlFragment()) AND EVENT_TIME >= '\(df.string(from: nextDay))'"
        )
        if let row = fwdResult.rows.first, let date = parse(row[0]) {
            return cal.startOfDay(for: date)
        }

        // Fall back to the last day strictly before the selected day
        let bwdResult = try await db.execute(
            "SELECT MAX(EVENT_TIME) FROM JOURNEYS WHERE PROJECT_ID = '\(safe)' AND \(activeSampleSet.sqlFragment()) AND EVENT_TIME < '\(df.string(from: cal.startOfDay(for: day)))'"
        )
        if let row = bwdResult.rows.first, let date = parse(row[0]) {
            return cal.startOfDay(for: date)
        }

        return nil
    }

    func loadTransitions(
        projectId: String,
        from: Date? = nil, to: Date? = nil,
        included: [String] = [], excluded: [String] = [],
        meta1: String = "", meta2: String = "", meta3: String = "",
        minSteps: Int = 0, maxSteps: Int = Int.max,
        minJourneyTime: Int = 0, maxJourneyTime: Int = Int.max,
        minScore: Int = Int.min, maxScore: Int = Int.max
    ) async throws -> [ProcessTransition] {
        let safe = projectId.replacingOccurrences(of: "'", with: "''")
        // Date and meta filters select journeys (cases) that had activity in the
        // requested window. LEAD() then sees every step of each qualifying journey
        // so cross-day transitions are never silently dropped.
        let filters = sampleSetClause()
                    + journeyActivityFilter(from: from, to: to, projectId: safe,
                                            meta1: meta1, meta2: meta2, meta3: meta3)
                    + stepClause(included: included, excluded: excluded, projectId: safe)
                    + stepsClause(min: minSteps, max: maxSteps, projectId: safe)
                    + journeyTimeClause(minSecs: minJourneyTime, maxSecs: maxJourneyTime, projectId: safe)
                    + scoreClause(min: minScore, max: maxScore, projectId: safe)
        // LEAD() ordered by EVENT_TIME finds the chronologically next step within
        // each journey. STEP_ID breaks ties when two steps share the same EVENT_TIME.
        let result = try await db.execute("""
            SELECT FROM_STEP, TO_STEP, COUNT(*) AS CNT,
                   AVG(SECONDS_BETWEEN(TO_TIME, FROM_TIME)) AS AVG_SECS,
                   MIN(SECONDS_BETWEEN(TO_TIME, FROM_TIME)) AS MIN_SECS,
                   MAX(SECONDS_BETWEEN(TO_TIME, FROM_TIME)) AS MAX_SECS,
                   STDDEV(SECONDS_BETWEEN(TO_TIME, FROM_TIME)) AS STDDEV_SECS
            FROM (
                SELECT
                    STEP       AS FROM_STEP,
                    EVENT_TIME AS FROM_TIME,
                    LEAD(STEP)       OVER (PARTITION BY EVENT_ID ORDER BY EVENT_TIME, STEP_ID) AS TO_STEP,
                    LEAD(EVENT_TIME) OVER (PARTITION BY EVENT_ID ORDER BY EVENT_TIME, STEP_ID) AS TO_TIME
                FROM JOURNEYS
                WHERE PROJECT_ID = '\(safe)'\(filters)
            ) AS t
            WHERE TO_STEP IS NOT NULL AND TO_TIME IS NOT NULL
            GROUP BY FROM_STEP, TO_STEP
            ORDER BY CNT DESC
            """)
        func dbl(_ v: Any?) -> Double? {
            if let d = v as? Double        { return d }
            if let f = v as? Float         { return Double(f) }
            if let i = v as? Int           { return Double(i) }
            if let n = v as? NSNumber      { return n.doubleValue }
            if let d = v as? Decimal       { return NSDecimalNumber(decimal: d).doubleValue }
            if let s = v as? String        { return Double(s) }
            return nil
        }
        return result.rows.compactMap { row in
            guard let from = row[0] as? String,
                  let to   = row[1] as? String else { return nil }
            let cnt: Int
            if let i = row[2] as? Int         { cnt = i }
            else if let d = row[2] as? Double  { cnt = Int(d) }
            else                               { return nil }
            return ProcessTransition(fromStep: from, toStep: to, occurrences: cnt,
                                     avgSecs: dbl(row[3]), minSecs: dbl(row[4]),
                                     maxSecs: dbl(row[5]), stdDevSecs: dbl(row[6]))
        }
    }

    func loadEventIdSuggestions(projectId: String, prefix: String, limit: Int = 10) async throws -> [String] {
        let safePid    = projectId.replacingOccurrences(of: "'", with: "''")
        let safePrefix = prefix.replacingOccurrences(of: "'", with: "''")
        let result = try await db.execute("""
            SELECT DISTINCT EVENT_ID
            FROM JOURNEYS
            WHERE PROJECT_ID = '\(safePid)'
            AND \(activeSampleSet.sqlFragment())
            AND UPPER(EVENT_ID) LIKE UPPER('%\(safePrefix)%')
            ORDER BY EVENT_ID
            LIMIT \(limit)
            """)
        return result.rows.compactMap { $0[0] as? String }
    }

    func loadJourneyDurationStats(
        projectId: String,
        from: Date? = nil, to: Date? = nil,
        included: [String] = [], excluded: [String] = [],
        meta1: String = "", meta2: String = "", meta3: String = "",
        minSteps: Int = 0, maxSteps: Int = Int.max,
        minJourneyTime: Int = 0, maxJourneyTime: Int = Int.max,
        minScore: Int = Int.min, maxScore: Int = Int.max
    ) async throws -> (minSecs: Double?, avgSecs: Double?, maxSecs: Double?, stdDevSecs: Double?) {
        let safe = projectId.replacingOccurrences(of: "'", with: "''")
        let filters = sampleSetClause()
                    + dateClause(from: from, to: to)
                    + stepClause(included: included, excluded: excluded, projectId: safe)
                    + metaClause(meta1: meta1, meta2: meta2, meta3: meta3)
                    + stepsClause(min: minSteps, max: maxSteps, projectId: safe)
                    + journeyTimeClause(minSecs: minJourneyTime, maxSecs: maxJourneyTime, projectId: safe)
                    + scoreClause(min: minScore, max: maxScore, projectId: safe)
        let result = try await db.execute("""
            SELECT
                MIN(SECONDS_BETWEEN(MAX_TIME, MIN_TIME)) AS MIN_SECS,
                AVG(SECONDS_BETWEEN(MAX_TIME, MIN_TIME)) AS AVG_SECS,
                MAX(SECONDS_BETWEEN(MAX_TIME, MIN_TIME)) AS MAX_SECS,
                STDDEV(SECONDS_BETWEEN(MAX_TIME, MIN_TIME)) AS STDDEV_SECS
            FROM (
                SELECT EVENT_ID,
                       MIN(EVENT_TIME) AS MIN_TIME,
                       MAX(EVENT_TIME) AS MAX_TIME
                FROM JOURNEYS
                WHERE PROJECT_ID = '\(safe)'\(filters)
                GROUP BY EVENT_ID
            ) AS j
            """)
        func dbl(_ v: Any?) -> Double? {
            if let d = v as? Double        { return d }
            if let f = v as? Float         { return Double(f) }
            if let i = v as? Int           { return Double(i) }
            if let n = v as? NSNumber      { return n.doubleValue }
            if let d = v as? Decimal       { return NSDecimalNumber(decimal: d).doubleValue }
            if let s = v as? String        { return Double(s) }
            return nil
        }
        guard let row = result.rows.first else { return (nil, nil, nil, nil) }
        return (dbl(row[0]), dbl(row[1]), dbl(row[2]), dbl(row[3]))
    }

    func loadDurationBuckets(
        projectId: String,
        from: Date? = nil, to: Date? = nil,
        included: [String] = [], excluded: [String] = [],
        meta1: String = "", meta2: String = "", meta3: String = "",
        minSteps: Int = 0, maxSteps: Int = Int.max,
        minJourneyTime: Int = 0, maxJourneyTime: Int = Int.max,
        minScore: Int = Int.min, maxScore: Int = Int.max,
        binCount: Int = 10
    ) async throws -> [DurationBucket] {
        let safe = projectId.replacingOccurrences(of: "'", with: "''")
        let filters = sampleSetClause()
                    + dateClause(from: from, to: to)
                    + stepClause(included: included, excluded: excluded, projectId: safe)
                    + metaClause(meta1: meta1, meta2: meta2, meta3: meta3)
                    + stepsClause(min: minSteps, max: maxSteps, projectId: safe)
                    + journeyTimeClause(minSecs: minJourneyTime, maxSecs: maxJourneyTime, projectId: safe)
                    + scoreClause(min: minScore, max: maxScore, projectId: safe)
        let n = binCount
        // Compute durations once (d), derive min/max range (r), assign each journey
        // to one of n equal-width bins, then aggregate counts per bin.
        let sql = """
            SELECT bin_idx, COUNT(*) AS cnt, MIN(min_dur) AS min_dur, MIN(max_dur) AS max_dur
            FROM (
                SELECT
                    CASE
                        WHEN r.max_dur = r.min_dur THEN 0
                        ELSE LEAST(FLOOR((d.dur - r.min_dur) / (r.max_dur - r.min_dur) * \(n)), \(n - 1))
                    END AS bin_idx,
                    r.min_dur,
                    r.max_dur
                FROM (
                    SELECT EVENT_ID, SECONDS_BETWEEN(MAX(EVENT_TIME), MIN(EVENT_TIME)) AS dur
                    FROM JOURNEYS
                    WHERE PROJECT_ID = '\(safe)'\(filters)
                    GROUP BY EVENT_ID
                ) d,
                (
                    SELECT MIN(dur) AS min_dur, MAX(dur) AS max_dur
                    FROM (
                        SELECT EVENT_ID, SECONDS_BETWEEN(MAX(EVENT_TIME), MIN(EVENT_TIME)) AS dur
                        FROM JOURNEYS
                        WHERE PROJECT_ID = '\(safe)'\(filters)
                        GROUP BY EVENT_ID
                    ) d2
                ) r
            ) binned
            GROUP BY bin_idx
            ORDER BY bin_idx
            """
        let result = try await db.execute(sql)
        guard !result.rows.isEmpty else { return [] }

        func dbl(_ v: Any?) -> Double {
            if let d = v as? Double   { return d }
            if let f = v as? Float    { return Double(f) }
            if let i = v as? Int      { return Double(i) }
            if let n = v as? NSNumber { return n.doubleValue }
            if let d = v as? Decimal  { return NSDecimalNumber(decimal: d).doubleValue }
            if let s = v as? String   { return Double(s) ?? 0 }
            return 0
        }
        func intVal(_ v: Any?) -> Int {
            if let i = v as? Int      { return i }
            if let d = v as? Double   { return Int(d) }
            if let n = v as? NSNumber { return n.intValue }
            if let d = v as? Decimal  { return NSDecimalNumber(decimal: d).intValue }
            if let s = v as? String   { return Int(s) ?? 0 }
            return 0
        }

        let minDur  = dbl(result.rows[0][2])
        let maxDur  = dbl(result.rows[0][3])
        let binWidth = maxDur > minDur ? (maxDur - minDur) / Double(n) : max(maxDur, 1)

        return result.rows.compactMap { row in
            let binIdx = intVal(row[0])
            let count  = intVal(row[1])
            let lo = minDur + Double(binIdx) * binWidth
            let hi = lo + binWidth
            return DurationBucket(label: "\(durLabel(lo))–\(durLabel(hi))", count: count)
        }
    }

    private func durLabel(_ secs: Double) -> String {
        if secs < 60    { return "\(Int(secs.rounded()))s" }
        if secs < 3600  {
            let m = secs / 60
            return m < 10 ? String(format: "%.1fm", m) : "\(Int(m.rounded()))m"
        }
        if secs < 86400 {
            let h = secs / 3600
            return h < 10 ? String(format: "%.1fh", h) : "\(Int(h.rounded()))h"
        }
        let d = secs / 86400
        return d < 10 ? String(format: "%.1fd", d) : "\(Int(d.rounded()))d"
    }

    // Returns startDate, endDate, meta1, meta2, meta3 in a single query.
    func loadJourneyInfo(projectId: String, eventId: String) async throws
        -> (startDate: Date?, endDate: Date?, meta1: String?, meta2: String?, meta3: String?)
    {
        let safePid = projectId.replacingOccurrences(of: "'", with: "''")
        let safeEid = eventId.replacingOccurrences(of: "'", with: "''")
        let result = try await db.execute("""
            SELECT MIN(EVENT_TIME), MAX(EVENT_TIME),
                   MAX(META_1), MAX(META_2), MAX(META_3)
            FROM JOURNEYS
            WHERE PROJECT_ID = '\(safePid)'
            AND \(activeSampleSet.sqlFragment())
            AND EVENT_ID = '\(safeEid)'
            """)
        guard let row = result.rows.first else { return (nil, nil, nil, nil, nil) }
        func clean(_ v: Any?) -> String? {
            guard let s = v as? String,
                  !s.trimmingCharacters(in: .whitespaces).isEmpty else { return nil }
            return s.trimmingCharacters(in: .whitespaces)
        }
        return (
            row[0].flatMap { parseDate($0) },
            row[1].flatMap { parseDate($0) },
            clean(row[2]),
            clean(row[3]),
            clean(row[4])
        )
    }

    func loadJourneyGraph(projectId: String, eventId: String) async throws -> ProcessGraph {
        let safePid = projectId.replacingOccurrences(of: "'", with: "''")
        let safeEid = eventId.replacingOccurrences(of: "'", with: "''")

        // Transitions
        let transResult = try await db.execute("""
            SELECT FROM_STEP, TO_STEP, COUNT(*) AS CNT,
                   AVG(SECONDS_BETWEEN(TO_TIME, FROM_TIME)) AS AVG_SECS,
                   MIN(SECONDS_BETWEEN(TO_TIME, FROM_TIME)) AS MIN_SECS,
                   MAX(SECONDS_BETWEEN(TO_TIME, FROM_TIME)) AS MAX_SECS,
                   STDDEV(SECONDS_BETWEEN(TO_TIME, FROM_TIME)) AS STDDEV_SECS
            FROM (
                SELECT
                    STEP       AS FROM_STEP,
                    EVENT_TIME AS FROM_TIME,
                    LEAD(STEP)       OVER (PARTITION BY EVENT_ID ORDER BY EVENT_TIME, STEP_ID) AS TO_STEP,
                    LEAD(EVENT_TIME) OVER (PARTITION BY EVENT_ID ORDER BY EVENT_TIME, STEP_ID) AS TO_TIME
                FROM JOURNEYS
                WHERE PROJECT_ID = '\(safePid)'
                AND \(activeSampleSet.sqlFragment())
                AND EVENT_ID = '\(safeEid)'
            ) AS t
            WHERE TO_STEP IS NOT NULL AND TO_TIME IS NOT NULL
            GROUP BY FROM_STEP, TO_STEP
            ORDER BY CNT DESC
            """)
        func dbl(_ v: Any?) -> Double? {
            if let d = v as? Double        { return d }
            if let f = v as? Float         { return Double(f) }
            if let i = v as? Int           { return Double(i) }
            if let n = v as? NSNumber      { return n.doubleValue }
            if let d = v as? Decimal       { return NSDecimalNumber(decimal: d).doubleValue }
            if let s = v as? String        { return Double(s) }
            return nil
        }
        let transitions: [ProcessTransition] = transResult.rows.compactMap { row in
            guard let from = row[0] as? String,
                  let to   = row[1] as? String else { return nil }
            let cnt: Int
            if let i = row[2] as? Int         { cnt = i }
            else if let d = row[2] as? Double  { cnt = Int(d) }
            else                               { return nil }
            return ProcessTransition(fromStep: from, toStep: to, occurrences: cnt,
                                     avgSecs: dbl(row[3]), minSecs: dbl(row[4]),
                                     maxSecs: dbl(row[5]), stdDevSecs: dbl(row[6]))
        }

        // Earliest timestamp per step (used to display time inside each node)
        let timeResult = try await db.execute("""
            SELECT STEP, MIN(EVENT_TIME) AS FIRST_TIME
            FROM JOURNEYS
            WHERE PROJECT_ID = '\(safePid)'
            AND \(activeSampleSet.sqlFragment())
            AND EVENT_ID = '\(safeEid)'
            GROUP BY STEP
            """)
        var stepTimes: [String: Date] = [:]
        for row in timeResult.rows {
            guard let step = row[0] as? String, let val = row[1] else { continue }
            stepTimes[step] = parseDate(val)
        }

        var stepsMap = try await loadSteps(projectId: projectId)
        let referencedNodes = Set(transitions.flatMap { [$0.fromStep, $0.toStep] })
        stepsMap = stepsMap.filter { referencedNodes.contains($0.key) }
        for node in referencedNodes where stepsMap[node] == nil {
            stepsMap[node] = StepInfo(
                step: node, description: node, bgColor: "gray",
                fgColor: "white", score: nil, shape: "stadium", endOfProcess: false, belongsTo: nil
            )
        }
        // Attach timestamps to each step
        for node in referencedNodes {
            if let time = stepTimes[node] {
                stepsMap[node]?.eventTime = time
            }
        }
        return ProcessGraph(steps: stepsMap, transitions: transitions)
    }

    private func parseDate(_ val: Any) -> Date? {
        if let str = val as? String {
            for fmt in ["yyyy-MM-dd HH:mm:ss.SSSSSS", "yyyy-MM-dd HH:mm:ss", "yyyy-MM-dd"] {
                let df = DateFormatter(); df.dateFormat = fmt
                if let d = df.date(from: str) { return d }
            }
        }
        return val as? Date
    }

    func loadJourneyPaths(
        projectId: String,
        from: Date? = nil, to: Date? = nil,
        included: [String] = [], excluded: [String] = [],
        meta1: String = "", meta2: String = "", meta3: String = "",
        minSteps: Int = 0, maxSteps: Int = Int.max,
        minJourneyTime: Int = 0, maxJourneyTime: Int = Int.max,
        minScore: Int = Int.min, maxScore: Int = Int.max,
        limit: Int = 500
    ) async throws -> [JourneyPath] {
        let safe = projectId.replacingOccurrences(of: "'", with: "''")
        let filters = sampleSetClause()
                    + dateClause(from: from, to: to)
                    + stepClause(included: included, excluded: excluded, projectId: safe)
                    + metaClause(meta1: meta1, meta2: meta2, meta3: meta3)
                    + stepsClause(min: minSteps, max: maxSteps, projectId: safe)
                    + journeyTimeClause(minSecs: minJourneyTime, maxSecs: maxJourneyTime, projectId: safe)
                    + scoreClause(min: minScore, max: maxScore, projectId: safe)
        let sql = """
            WITH ordered_paths AS (
                SELECT
                    j.EVENT_ID,
                    LISTAGG(j.STEP, ' -> ') WITHIN GROUP (ORDER BY j.EVENT_TIME ASC) AS full_path,
                    COUNT(j.STEP)             AS path_length,
                    SUM(COALESCE(s.SCORE, 0)) AS score
                FROM JOURNEYS j
                LEFT JOIN STEPS s ON j.STEP = s.STEP AND j.PROJECT_ID = s.PROJECT_ID
                WHERE j.PROJECT_ID = '\(safe)'\(filters)
                GROUP BY j.EVENT_ID
            ),
            distinct_paths AS (
                SELECT
                    full_path,
                    path_length,
                    score,
                    COUNT(*) AS journey_count
                FROM ordered_paths
                GROUP BY full_path, path_length, score
            )
            SELECT
                full_path,
                journey_count,
                path_length,
                score
            FROM distinct_paths
            ORDER BY journey_count DESC
            LIMIT \(limit)
            """

        // Race the query against a 30-second wall-clock timeout.
        let result = try await withThrowingTaskGroup(of: QueryResult.self) { group in
            group.addTask { try await self.db.execute(sql) }
            group.addTask {
                try await Task.sleep(nanoseconds: 30_000_000_000)
                throw NSError(
                    domain: "Stats", code: -1,
                    userInfo: [NSLocalizedDescriptionKey:
                        "Statistics query timed out (30 s). Narrow your date range or filters and try again."]
                )
            }
            let first = try await group.next()!
            group.cancelAll()
            return first
        }

        func int(_ v: Any?) -> Int {
            if let i = v as? Int       { return i }
            if let d = v as? Double    { return Int(d) }
            if let n = v as? NSNumber  { return n.intValue }
            if let d = v as? Decimal   { return NSDecimalNumber(decimal: d).intValue }
            if let s = v as? String    { return Int(s) ?? 0 }
            return 0
        }
        return result.rows.compactMap { row in
            guard let path = row[0] as? String else { return nil }
            return JourneyPath(path: path,
                               journeyCount: int(row[1]),
                               stepCount:    int(row[2]),
                               totalScore:   int(row[3]))
        }
    }

    // Returns (rawGoodness, filteredCount) for the process-goodness formula.
    // raw_goodness = Σ_path (freq/total) * (totalScore / √stepCount − 0.01 * avgDuration)
    // Caller multiplies by (filteredCount / totalJourneyCount)^0.5 to apply coverage penalty.
    func loadProcessGoodness(
        projectId: String,
        from: Date? = nil, to: Date? = nil,
        included: [String] = [], excluded: [String] = [],
        meta1: String = "", meta2: String = "", meta3: String = "",
        minSteps: Int = 0, maxSteps: Int = Int.max,
        minJourneyTime: Int = 0, maxJourneyTime: Int = Int.max,
        minScore: Int = Int.min, maxScore: Int = Int.max
    ) async throws -> (rawGoodness: Double, filteredCount: Int)? {
        let safe = projectId.replacingOccurrences(of: "'", with: "''")
        let filters = sampleSetClause()
                    + dateClause(from: from, to: to)
                    + stepClause(included: included, excluded: excluded, projectId: safe)
                    + metaClause(meta1: meta1, meta2: meta2, meta3: meta3)
                    + stepsClause(min: minSteps, max: maxSteps, projectId: safe)
                    + journeyTimeClause(minSecs: minJourneyTime, maxSecs: maxJourneyTime, projectId: safe)
                    + scoreClause(min: minScore, max: maxScore, projectId: safe)
        let sql = """
            WITH ordered_paths AS (
                SELECT
                    j.EVENT_ID,
                    LISTAGG(j.STEP, ' -> ') WITHIN GROUP (ORDER BY j.EVENT_TIME ASC) AS full_path,
                    COUNT(j.STEP)                                                      AS path_length,
                    SUM(COALESCE(s.SCORE, 0))                                          AS total_score,
                    COALESCE(SECONDS_BETWEEN(MAX(j.EVENT_TIME), MIN(j.EVENT_TIME)), 0) AS journey_duration
                FROM JOURNEYS j
                LEFT JOIN STEPS s ON j.STEP = s.STEP AND j.PROJECT_ID = s.PROJECT_ID
                WHERE j.PROJECT_ID = '\(safe)'\(filters)
                GROUP BY j.EVENT_ID
            ),
            distinct_paths AS (
                SELECT
                    path_length,
                    total_score,
                    COUNT(*)              AS journey_count,
                    AVG(journey_duration) AS avg_duration
                FROM ordered_paths
                GROUP BY full_path, path_length, total_score
            ),
            totals AS (
                SELECT SUM(journey_count) AS total_freq FROM distinct_paths
            )
            SELECT
                SUM(
                    (CAST(dp.journey_count AS DOUBLE) / CAST(t.total_freq AS DOUBLE)) *
                    (CAST(dp.total_score   AS DOUBLE) / SQRT(CAST(GREATEST(dp.path_length, 1) AS DOUBLE)) -
                     0.01 * dp.avg_duration)
                ) AS raw_goodness,
                t.total_freq AS filtered_count
            FROM distinct_paths dp, totals t
            GROUP BY t.total_freq
            """

        let result = try await withThrowingTaskGroup(of: QueryResult.self) { group in
            group.addTask { try await self.db.execute(sql) }
            group.addTask {
                try await Task.sleep(nanoseconds: 30_000_000_000)
                throw NSError(
                    domain: "Goodness", code: -1,
                    userInfo: [NSLocalizedDescriptionKey: "Process goodness query timed out (30 s)."]
                )
            }
            let first = try await group.next()!
            group.cancelAll()
            return first
        }

        func dbl(_ v: Any?) -> Double? {
            if let d = v as? Double        { return d }
            if let f = v as? Float         { return Double(f) }
            if let i = v as? Int           { return Double(i) }
            if let n = v as? NSNumber      { return n.doubleValue }
            if let d = v as? Decimal       { return NSDecimalNumber(decimal: d).doubleValue }
            if let s = v as? String        { return Double(s) }
            return nil
        }
        func int(_ v: Any?) -> Int {
            if let i = v as? Int       { return i }
            if let d = v as? Double    { return Int(d) }
            if let n = v as? NSNumber  { return n.intValue }
            if let d = v as? Decimal   { return NSDecimalNumber(decimal: d).intValue }
            if let s = v as? String    { return Int(s) ?? 0 }
            return 0
        }

        guard let row = result.rows.first, let rawGoodness = dbl(row[0]) else { return nil }
        return (rawGoodness, int(row[1]))
    }

    func loadJourneyTimeSeries(
        projectId: String,
        from: Date? = nil, to: Date? = nil,
        included: [String] = [], excluded: [String] = [],
        meta1: String = "", meta2: String = "", meta3: String = "",
        minSteps: Int = 0, maxSteps: Int = Int.max,
        minJourneyTime: Int = 0, maxJourneyTime: Int = Int.max,
        minScore: Int = Int.min, maxScore: Int = Int.max,
        granularity: TimeGranularity
    ) async throws -> [JourneyTimePoint] {
        let safe = projectId.replacingOccurrences(of: "'", with: "''")
        let filters = sampleSetClause()
                    + dateClause(from: from, to: to)
                    + stepClause(included: included, excluded: excluded, projectId: safe)
                    + metaClause(meta1: meta1, meta2: meta2, meta3: meta3)
                    + stepsClause(min: minSteps, max: maxSteps, projectId: safe)
                    + journeyTimeClause(minSecs: minJourneyTime, maxSecs: maxJourneyTime, projectId: safe)
                    + scoreClause(min: minScore, max: maxScore, projectId: safe)
        let trunc: String
        switch granularity {
        case .day:   trunc = "CAST(EVENT_TIME AS DATE)"
        case .week:  trunc = "TRUNC(EVENT_TIME, 'IW')"
        case .month: trunc = "TRUNC(EVENT_TIME, 'MM')"
        }
        let sql = """
            SELECT \(trunc) AS period, COUNT(DISTINCT EVENT_ID) AS cnt
            FROM JOURNEYS
            WHERE PROJECT_ID = '\(safe)'\(filters)
            GROUP BY \(trunc)
            ORDER BY \(trunc)
            """
        let result = try await db.execute(sql)
        func int(_ v: Any?) -> Int {
            if let i = v as? Int     { return i }
            if let d = v as? Double  { return Int(d) }
            if let n = v as? NSNumber { return n.intValue }
            if let s = v as? String  { return Int(s) ?? 0 }
            return 0
        }
        return result.rows.compactMap { row in
            guard let val = row[0], let date = parseDate(val) else { return nil }
            return JourneyTimePoint(date: date, count: int(row[1]))
        }
    }

    func loadGraph(
        projectId: String,
        from: Date? = nil, to: Date? = nil,
        included: [String] = [], excluded: [String] = [],
        meta1: String = "", meta2: String = "", meta3: String = "",
        minSteps: Int = 0, maxSteps: Int = Int.max,
        minJourneyTime: Int = 0, maxJourneyTime: Int = Int.max,
        minScore: Int = Int.min, maxScore: Int = Int.max
    ) async throws -> ProcessGraph {
        var stepsMap    = try await loadSteps(projectId: projectId)
        let transitions = try await loadTransitions(
            projectId: projectId, from: from, to: to,
            included: included, excluded: excluded,
            meta1: meta1, meta2: meta2, meta3: meta3,
            minSteps: minSteps, maxSteps: maxSteps,
            minJourneyTime: minJourneyTime, maxJourneyTime: maxJourneyTime,
            minScore: minScore, maxScore: maxScore
        )

        // Restrict to nodes that appear in the filtered transitions
        let referencedNodes = Set(transitions.flatMap { [$0.fromStep, $0.toStep] })
        stepsMap = stepsMap.filter { referencedNodes.contains($0.key) }

        // Ensure every referenced node has a StepInfo
        for node in referencedNodes where stepsMap[node] == nil {
            stepsMap[node] = StepInfo(
                step: node, description: node, bgColor: "gray",
                fgColor: "white", score: nil, shape: "stadium", endOfProcess: false, belongsTo: nil
            )
        }
        return ProcessGraph(steps: stepsMap, transitions: transitions)
    }

    // Selects journeys (EVENT_IDs) that had at least one event within the date
    // window AND matching meta values. Wrapping the filter in an EVENT_ID IN (…)
    // subquery lets the LEAD() window in loadTransitions see every step of each
    // qualifying journey, so cross-day transitions are never silently dropped.
    private func journeyActivityFilter(
        from: Date?, to: Date?,
        projectId: String,
        meta1: String, meta2: String, meta3: String
    ) -> String {
        guard from != nil || to != nil || !meta1.isEmpty || !meta2.isEmpty || !meta3.isEmpty else { return "" }
        var parts: [String] = ["PROJECT_ID = '\(projectId)'", activeSampleSet.sqlFragment()]
        let df = DateFormatter(); df.dateFormat = "yyyy-MM-dd"
        if let f = from { parts.append("EVENT_TIME >= TIMESTAMP '\(df.string(from: f)) 00:00:00'") }
        if let t = to   { parts.append("EVENT_TIME <= TIMESTAMP '\(df.string(from: t)) 23:59:59'") }
        func addMeta(_ col: String, _ val: String) {
            guard !val.isEmpty else { return }
            let s = val.replacingOccurrences(of: "'", with: "''")
            parts.append("UPPER(\(col)) LIKE UPPER('%\(s)%')")
        }
        addMeta("META_1", meta1)
        addMeta("META_2", meta2)
        addMeta("META_3", meta3)
        return "\n                AND EVENT_ID IN (SELECT DISTINCT EVENT_ID FROM JOURNEYS WHERE \(parts.joined(separator: " AND ")))"
    }

    private func sampleSetClause() -> String {
        "\n                AND \(activeSampleSet.sqlFragment())"
    }

    private func sampleSetClause(alias: String) -> String {
        "\n                AND \(activeSampleSet.sqlFragment(alias: alias))"
    }

    private func dateClause(from: Date?, to: Date?) -> String {
        guard from != nil || to != nil else { return "" }
        let df = DateFormatter(); df.dateFormat = "yyyy-MM-dd"
        var parts: [String] = []
        if let f = from { parts.append("AND EVENT_TIME >= TIMESTAMP '\(df.string(from: f)) 00:00:00'") }
        if let t = to   { parts.append("AND EVENT_TIME <= TIMESTAMP '\(df.string(from: t)) 23:59:59'") }
        return "\n                " + parts.joined(separator: "\n                ")
    }

    // Case-level text filter on META columns using case-insensitive LIKE contains.
    private func metaClause(meta1: String, meta2: String, meta3: String) -> String {
        var parts: [String] = []
        func add(_ column: String, _ value: String) {
            guard !value.isEmpty else { return }
            let safe = value.replacingOccurrences(of: "'", with: "''")
            parts.append("AND UPPER(\(column)) LIKE UPPER('%\(safe)%')")
        }
        add("META_1", meta1)
        add("META_2", meta2)
        add("META_3", meta3)
        return parts.isEmpty ? "" : "\n                " + parts.joined(separator: "\n                ")
    }

    // Filters at journey/case level: include only (or exclude entirely) cases
    // that passed through the specified steps.
    private func stepClause(included: [String], excluded: [String], projectId: String) -> String {
        func inList(_ steps: [String]) -> String {
            steps.map { "'\($0.replacingOccurrences(of: "'", with: "''"))'" }.joined(separator: ", ")
        }
        var parts: [String] = []
        if !included.isEmpty {
            parts.append(
                "AND EVENT_ID IN (SELECT DISTINCT EVENT_ID FROM JOURNEYS WHERE PROJECT_ID = '\(projectId)' AND \(activeSampleSet.sqlFragment()) AND STEP IN (\(inList(included))))"
            )
        }
        if !excluded.isEmpty {
            parts.append(
                "AND EVENT_ID NOT IN (SELECT DISTINCT EVENT_ID FROM JOURNEYS WHERE PROJECT_ID = '\(projectId)' AND \(activeSampleSet.sqlFragment()) AND STEP IN (\(inList(excluded))))"
            )
        }
        return parts.isEmpty ? "" : "\n                " + parts.joined(separator: "\n                ")
    }

    private func stepsClause(min: Int, max: Int, projectId: String) -> String {
        guard min > 0 || max < Int.max else { return "" }
        let having: String
        if min > 0 && max < Int.max {
            having = "HAVING COUNT(*) BETWEEN \(min) AND \(max)"
        } else if min > 0 {
            having = "HAVING COUNT(*) >= \(min)"
        } else {
            having = "HAVING COUNT(*) <= \(max)"
        }
        return "\n                AND EVENT_ID IN (SELECT EVENT_ID FROM JOURNEYS WHERE PROJECT_ID = '\(projectId)' AND \(activeSampleSet.sqlFragment()) GROUP BY EVENT_ID \(having))"
    }

    private func journeyTimeClause(minSecs: Int, maxSecs: Int, projectId: String) -> String {
        guard minSecs > 0 || maxSecs < Int.max else { return "" }
        let having: String
        if minSecs > 0 && maxSecs < Int.max {
            having = "HAVING SECONDS_BETWEEN(MAX(EVENT_TIME), MIN(EVENT_TIME)) BETWEEN \(minSecs) AND \(maxSecs)"
        } else if minSecs > 0 {
            having = "HAVING SECONDS_BETWEEN(MAX(EVENT_TIME), MIN(EVENT_TIME)) >= \(minSecs)"
        } else {
            having = "HAVING SECONDS_BETWEEN(MAX(EVENT_TIME), MIN(EVENT_TIME)) <= \(maxSecs)"
        }
        return "\n                AND EVENT_ID IN (SELECT EVENT_ID FROM JOURNEYS WHERE PROJECT_ID = '\(projectId)' AND \(activeSampleSet.sqlFragment()) GROUP BY EVENT_ID \(having))"
    }

    private func scoreClause(min: Int, max: Int, projectId: String) -> String {
        guard min > Int.min || max < Int.max else { return "" }
        return "\n                AND EVENT_ID IN (SELECT j.EVENT_ID FROM JOURNEYS j LEFT JOIN STEPS s ON j.STEP = s.STEP AND j.PROJECT_ID = s.PROJECT_ID WHERE j.PROJECT_ID = '\(projectId)' AND \(activeSampleSet.sqlFragment(alias: "j")) GROUP BY j.EVENT_ID HAVING SUM(COALESCE(s.SCORE, 0)) BETWEEN \(min) AND \(max))"
    }

    // MARK: - NOTES table

    /// Creates the NOTES table if it does not already exist, and migrates older schemas.
    /// Silently ignored if the user lacks CREATE TABLE permission.
    func ensureNotesTable() async throws {
        _ = try await db.execute("""
            CREATE TABLE IF NOT EXISTS NOTES (
                ID              VARCHAR(36)   NOT NULL,
                PROJECT_ID      VARCHAR(100)  NOT NULL,
                NOTES_DATE      TIMESTAMP     NOT NULL,
                EDITED_DATE     TIMESTAMP,
                NOTE_USER       VARCHAR(200)  DEFAULT '',
                NOTE            VARCHAR(8000) DEFAULT '',
                IS_SHARED       BOOLEAN       DEFAULT FALSE,
                EDITED_BY       VARCHAR(200)  DEFAULT '',
                TARGET_TYPE     VARCHAR(10)   DEFAULT 'node',
                TARGET_FROM     VARCHAR(500)  DEFAULT '',
                TARGET_TO       VARCHAR(500),
                FILTER_SNAPSHOT VARCHAR(4000),
                PRIMARY KEY (ID)
            )
            """)
        // Migrations for tables created before these columns existed (silent on duplicate).
        _ = try? await db.execute(
            "ALTER TABLE NOTES ADD COLUMN IS_SHARED BOOLEAN DEFAULT FALSE"
        )
        _ = try? await db.execute(
            "ALTER TABLE NOTES ADD COLUMN EDITED_BY VARCHAR(200) DEFAULT ''"
        )
    }

    /// Loads notes visible to `username`: the user's own notes, legacy notes (no username), and shared notes.
    /// Pass an empty string to load all notes (single-user / unauthenticated scenario).
    func loadNotes(projectId: String, username: String) async throws -> [ProcessNote] {
        let safe     = projectId.replacingOccurrences(of: "'", with: "''")
        let safeUser = username.uppercased().replacingOccurrences(of: "'", with: "''")
        // NOTE_USER = '' catches legacy notes created before username tracking was added.
        // UPPER() handles Exasol usernames which are stored uppercase regardless of input.
        let visFilter = username.isEmpty
            ? ""
            : "AND (UPPER(NOTE_USER) = '\(safeUser)' OR NOTE_USER = '' OR IS_SHARED = TRUE)"

        let result = try await db.execute("""
            SELECT ID, NOTES_DATE, EDITED_DATE, NOTE_USER, NOTE, IS_SHARED, EDITED_BY,
                   TARGET_TYPE, TARGET_FROM, TARGET_TO, FILTER_SNAPSHOT
            FROM NOTES
            WHERE PROJECT_ID = '\(safe)'
            \(visFilter)
            ORDER BY NOTES_DATE ASC
            """)
        let decoder = JSONDecoder()
        return result.rows.compactMap { row in
            guard let idStr   = row[0] as? String,
                  let id      = UUID(uuidString: idStr),
                  let dateVal = row[1],
                  let date    = parseDate(dateVal) else { return nil }

            let editedAt    = row[2].flatMap { parseDate($0) }
            let username    = row[3] as? String ?? ""
            let text        = row[4] as? String ?? ""

            let isShared: Bool
            if let b = row[5] as? Bool        { isShared = b }
            else if let i = row[5] as? Int    { isShared = i != 0 }
            else if let d = row[5] as? Double { isShared = d != 0 }
            else                               { isShared = false }

            let lastEditedBy = row[6] as? String ?? ""

            let targetType = row[7] as? String ?? "node"
            let targetFrom = row[8] as? String ?? ""
            let targetTo   = row[9] as? String ?? ""

            let target: ProcessNote.NoteTarget
            if targetType == "edge", !targetTo.isEmpty {
                target = .edge(from: targetFrom, to: targetTo)
            } else {
                target = .node(targetFrom)
            }

            let filterSnapshot: FilterSnapshot
            if let snapshotStr  = row[10] as? String,
               let snapshotData = snapshotStr.data(using: .utf8),
               let snapshot     = try? decoder.decode(FilterSnapshot.self, from: snapshotData) {
                filterSnapshot = snapshot
            } else {
                let now = Date()
                filterSnapshot = FilterSnapshot(
                    fromDate: now, toDate: now,
                    includedSteps: [], excludedSteps: [],
                    meta1: "", meta2: "", meta3: "",
                    minSteps: 0, maxSteps: Int.max,
                    minJourneyTime: 0, maxJourneyTime: Int.max,
                    minScore: Int.min, maxScore: Int.max
                )
            }
            return ProcessNote(id: id, text: text, createdAt: date, editedAt: editedAt,
                               target: target, filterSnapshot: filterSnapshot,
                               username: username, lastEditedBy: lastEditedBy, isShared: isShared)
        }
    }

    func upsertNote(_ note: ProcessNote, projectId: String) async throws {
        func esc(_ s: String) -> String { s.replacingOccurrences(of: "'", with: "''") }
        let df = DateFormatter()
        df.locale     = Locale(identifier: "en_US_POSIX")
        df.timeZone   = TimeZone(identifier: "UTC")
        df.dateFormat = "yyyy-MM-dd HH:mm:ss.SSS"

        let safeId  = note.id.uuidString
        let safePid = esc(projectId)

        // Remove any prior record with this ID before re-inserting
        _ = try? await db.execute("DELETE FROM NOTES WHERE ID = '\(safeId)'")

        let targetType: String; let targetFrom: String; let targetTo: String
        switch note.target {
        case .node(let n):        targetType = "node"; targetFrom = n; targetTo = ""
        case .edge(let f, let t): targetType = "edge"; targetFrom = f; targetTo = t
        }

        let notesDateSQL = "TIMESTAMP '\(df.string(from: note.createdAt))'"
        let editedSQL    = note.editedAt.map { "TIMESTAMP '\(df.string(from: $0))'" } ?? "NULL"
        let isSharedSQL  = note.isShared ? "TRUE" : "FALSE"

        let snapshotSQL: String
        if let data = try? JSONEncoder().encode(note.filterSnapshot),
           let json = String(data: data, encoding: .utf8) {
            snapshotSQL = "'\(esc(json))'"
        } else {
            snapshotSQL = "NULL"
        }

        _ = try await db.execute("""
            INSERT INTO NOTES
                (ID, PROJECT_ID, NOTES_DATE, EDITED_DATE, NOTE_USER, NOTE, IS_SHARED, EDITED_BY,
                 TARGET_TYPE, TARGET_FROM, TARGET_TO, FILTER_SNAPSHOT)
            VALUES (
                '\(safeId)', '\(safePid)',
                \(notesDateSQL), \(editedSQL),
                '\(esc(note.username))', '\(esc(note.text))', \(isSharedSQL), '\(esc(note.lastEditedBy))',
                '\(targetType)', '\(esc(targetFrom))', '\(esc(targetTo))',
                \(snapshotSQL)
            )
            """)
    }

    func deleteNote(id: UUID, projectId: String) async throws {
        let safeId  = id.uuidString
        let safePid = projectId.replacingOccurrences(of: "'", with: "''")
        _ = try await db.execute(
            "DELETE FROM NOTES WHERE ID = '\(safeId)' AND PROJECT_ID = '\(safePid)'"
        )
    }

    // MARK: - Sampling

    func ensureSampleSetColumn() async throws {
        _ = try? await db.execute(
            "ALTER TABLE JOURNEYS ADD COLUMN SAMPLE_SET VARCHAR(20) DEFAULT 'ORIGINAL'"
        )
        _ = try? await db.execute(
            "UPDATE JOURNEYS SET SAMPLE_SET = 'ORIGINAL' WHERE SAMPLE_SET IS NULL"
        )
    }

    func loadSampleJourneyCounts(projectId: String) async throws -> [SampleSet: Int] {
        let safe = projectId.replacingOccurrences(of: "'", with: "''")
        let result = try await db.execute("""
            SELECT SAMPLE_SET, COUNT(DISTINCT EVENT_ID) AS cnt
            FROM JOURNEYS
            WHERE PROJECT_ID = '\(safe)'
            GROUP BY SAMPLE_SET
            """)
        var counts: [SampleSet: Int] = [:]
        for row in result.rows {
            guard let raw = row[0] as? String,
                  let set = SampleSet(rawValue: raw) else { continue }
            let cnt: Int
            if let i = row[1] as? Int         { cnt = i }
            else if let d = row[1] as? Double  { cnt = Int(d) }
            else { continue }
            counts[set] = cnt
        }
        return counts
    }

    func loadAllEventIdsForSampling(projectId: String) async throws -> [String] {
        let safe = projectId.replacingOccurrences(of: "'", with: "''")
        let result = try await db.execute("""
            SELECT DISTINCT EVENT_ID
            FROM JOURNEYS
            WHERE PROJECT_ID = '\(safe)'
            AND (SAMPLE_SET = 'ORIGINAL' OR SAMPLE_SET IS NULL)
            """)
        return result.rows.compactMap { $0[0] as? String }
    }

    func loadEventIdsWithStartTimesForSampling(projectId: String) async throws -> [(String, Date)] {
        let safe = projectId.replacingOccurrences(of: "'", with: "''")
        let result = try await db.execute("""
            SELECT EVENT_ID, MIN(EVENT_TIME) AS start_time
            FROM JOURNEYS
            WHERE PROJECT_ID = '\(safe)'
            AND (SAMPLE_SET = 'ORIGINAL' OR SAMPLE_SET IS NULL)
            GROUP BY EVENT_ID
            """)
        return result.rows.compactMap { row in
            guard let id = row[0] as? String, let val = row[1] else { return nil }
            return parseDate(val).map { (id, $0) }
        }
    }

    func loadEventIdsWithPathsForSampling(projectId: String) async throws -> [(String, String)] {
        let safe = projectId.replacingOccurrences(of: "'", with: "''")
        let result = try await db.execute("""
            SELECT EVENT_ID,
                   LISTAGG(STEP, '->') WITHIN GROUP (ORDER BY EVENT_TIME, STEP_ID) AS journey_path
            FROM JOURNEYS
            WHERE PROJECT_ID = '\(safe)'
            AND (SAMPLE_SET = 'ORIGINAL' OR SAMPLE_SET IS NULL)
            GROUP BY EVENT_ID
            """)
        return result.rows.compactMap { row in
            guard let id   = row[0] as? String,
                  let path = row[1] as? String else { return nil }
            return (id, path)
        }
    }

    func insertSampleJourneys(projectId: String, eventIds: [String], sampleSet: SampleSet) async throws {
        guard !eventIds.isEmpty, !sampleSet.isOriginal else { return }
        let safePid = projectId.replacingOccurrences(of: "'", with: "''")
        let setVal  = sampleSet.rawValue
        let batchSize = 200
        for batchStart in stride(from: 0, to: eventIds.count, by: batchSize) {
            let batch = eventIds[batchStart..<min(batchStart + batchSize, eventIds.count)]
            let inList = batch.map { "'\($0.replacingOccurrences(of: "'", with: "''"))'" }.joined(separator: ", ")
            _ = try await db.execute("""
                INSERT INTO JOURNEYS
                    (PROJECT_ID, EVENT_ID, STEP, STEP_ID, EVENT_TIME, META_1, META_2, META_3, SAMPLE_SET)
                SELECT PROJECT_ID, EVENT_ID, STEP, STEP_ID, EVENT_TIME, META_1, META_2, META_3, '\(setVal)'
                FROM JOURNEYS
                WHERE PROJECT_ID = '\(safePid)'
                AND (SAMPLE_SET = 'ORIGINAL' OR SAMPLE_SET IS NULL)
                AND EVENT_ID IN (\(inList))
                """)
        }
    }

    func deleteSample(projectId: String, sampleSet: SampleSet) async throws {
        guard !sampleSet.isOriginal else { return }
        let safePid = projectId.replacingOccurrences(of: "'", with: "''")
        _ = try await db.execute("""
            DELETE FROM JOURNEYS
            WHERE PROJECT_ID = '\(safePid)'
            AND SAMPLE_SET = '\(sampleSet.rawValue)'
            """)
    }
}
