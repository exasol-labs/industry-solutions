"""All Exasol SQL — the port of ProcessRepository.swift.

The queries are kept character-for-character equivalent to the Swift originals so
results, edge cases and performance characteristics carry over unchanged.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Iterable, NamedTuple

from .. import log_events as logx
from ..config import QUERY_TIMEOUT_SECS
from ..models import (
    INT_MAX,
    INT_MIN,
    DurationBucket,
    DurationStats,
    FilterSnapshot,
    FilterSpec,
    JourneyPath,
    JourneyTimePoint,
    NoteTarget,
    ProcessGraph,
    ProcessNote,
    normalize_importance,
    ProcessTransition,
    Project,
    SampleSet,
    StepInfo,
    TimeGranularity,
    new_id,
)
from .manager import DatabaseManager

log = logging.getLogger(__name__)

_DATE_FORMATS = ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d")

# Hard caps on client-supplied row limits so a caller can't request a runaway
# result set (the query timeout bounds runtime, not the rows materialised/serialised).
_MAX_PATH_ROWS = 10_000  # variant / route path listings
_MAX_SUGGESTIONS = 100  # event-ID autocomplete
_MAX_LOG_ENTRIES = 1_000  # Actions "SHOW LAST N LOG ENTRIES"
_MAX_JOURNEY_ROWS = 1_000  # find/list journeys (per-case aggregate rows)

# ORDER BY clauses load_journeys accepts, keyed by the caller-facing name. A closed
# map (never interpolated caller text) keeps the sort out of reach of SQL injection.
JOURNEY_ORDERS: dict[str, str] = {
    "DURATION_DESC": "DURATION_SECS DESC",
    "DURATION_ASC": "DURATION_SECS ASC",
    "START_DESC": "START_TIME DESC",
    "START_ASC": "START_TIME ASC",
    "STEPS_DESC": "STEP_COUNT DESC",
    "STEPS_ASC": "STEP_COUNT ASC",
}

# Column headers returned by load_log_entries (the raw JOURNEYS row shape).
LOG_ENTRY_COLUMNS = ["EVENT_ID", "STEP", "EVENT_TIME", "META_1", "META_2", "META_3"]


class ProjectBounds(NamedTuple):
    """Whole-project filter-slider ranges, all computed in one scan."""
    date_min: datetime | None
    date_max: datetime | None
    step_min: int
    step_max: int
    time_min: int
    time_max: int
    score_min: int
    score_max: int


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(int(value), high))


def esc(value: str) -> str:
    """Escape a SQL string literal the way the Swift app did."""
    return value.replace("'", "''")


def _pid(project_id: int | str) -> int:
    """PROJECT_ID is a SMALLINT — render it as an unquoted integer literal. Coercing
    to int (from the API's number, or a numeric string) also makes injection
    impossible, so it needs no string escaping."""
    return int(project_id)


def as_int(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, Decimal)):
        return int(value)
    if isinstance(value, float):
        return int(value)
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return default


def as_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float, Decimal)):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def as_bool(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float, Decimal)):
        return value != 0
    return str(value).strip().lower() in {"true", "t", "1", "yes"}


def parse_date(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    text = str(value).strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def clean_str(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    trimmed = value.strip()
    return trimmed or None


def _ts(when: datetime) -> str:
    """Millisecond-precision timestamp literal, as written by the Swift app."""
    return when.strftime("%Y-%m-%d %H:%M:%S.") + f"{when.microsecond // 1000:03d}"


def dur_label(secs: float) -> str:
    """Bucket-boundary label — matches ProcessRepository.durLabel."""
    if secs < 60:
        return f"{round(secs)}s"
    if secs < 3600:
        minutes = secs / 60
        return f"{minutes:.1f}m" if minutes < 10 else f"{round(minutes)}m"
    if secs < 86400:
        hours = secs / 3600
        return f"{hours:.1f}h" if hours < 10 else f"{round(hours)}h"
    days = secs / 86400
    return f"{days:.1f}d" if days < 10 else f"{round(days)}d"


class ProcessRepository:
    def __init__(self, manager: DatabaseManager) -> None:
        self.db = manager
        self.active_sample_set: SampleSet = SampleSet.original
        # Which path the most recent load_transitions took: 'materialized' when it
        # read TRANSITIONS_RAW, 'live' for the on-the-fly LEAD() (incl. fallback).
        self.last_transitions_mode: str = "live"

    # ── clause builders (private helpers in the Swift original) ──────────────

    def _sample_clause(self, alias: str | None = None) -> str:
        return f"\n                AND {self.active_sample_set.sql_fragment(alias)}"

    def _date_clause(self, frm: datetime | None, to: datetime | None) -> str:
        if frm is None and to is None:
            return ""
        parts: list[str] = []
        if frm is not None:
            parts.append(f"AND EVENT_TIME >= TIMESTAMP '{frm:%Y-%m-%d} 00:00:00'")
        if to is not None:
            parts.append(f"AND EVENT_TIME <= TIMESTAMP '{to:%Y-%m-%d} 23:59:59'")
        return "\n                " + "\n                ".join(parts)

    def _meta_clause(self, meta1: str, meta2: str, meta3: str) -> str:
        parts: list[str] = []
        for column, value in (("META_1", meta1), ("META_2", meta2), ("META_3", meta3)):
            if value:
                parts.append(f"AND UPPER({column}) LIKE UPPER('%{esc(value)}%')")
        if not parts:
            return ""
        return "\n                " + "\n                ".join(parts)

    def _journey_qualifier(
        self, project_id: str, f: FilterSpec, *, include_date_meta: bool
    ) -> str:
        """One EVENT_ID semi-join folding every *journey-level* filter — active
        window + meta, included/excluded steps, step count, journey time and
        score — into a single ``GROUP BY EVENT_ID`` pass over JOURNEYS.

        Replaces the previous stack of up to six separate
        ``EVENT_ID IN (SELECT …)`` subqueries, so the event log is scanned once
        for the whole filter set instead of once per active filter.

        ``include_date_meta=True`` folds the date window + meta match in as an
        "has ≥1 event in window (matching meta)" condition — used by the LEAD()
        transition query, which must keep whole journeys. The row-level
        ``date_only`` path filters date/meta in the outer query instead and
        passes ``False``.
        """
        # STEPS also has a STEP column, so once the score join is present every
        # JOURNEYS column must be qualified with `j.` to stay unambiguous.
        score_active = f.minScore > INT_MIN or f.maxScore < INT_MAX
        p = "j." if score_active else ""

        def in_list(steps: Iterable[str]) -> str:
            return ", ".join(f"'{esc(s)}'" for s in steps)

        having: list[str] = []

        # Active-in-window + meta match (same row must satisfy all, mirroring the
        # old WHERE-based membership subquery).
        if include_date_meta:
            row: list[str] = []
            if f.fromDate is not None:
                row.append(f"{p}EVENT_TIME >= TIMESTAMP '{f.fromDate:%Y-%m-%d} 00:00:00'")
            if f.toDate is not None:
                row.append(f"{p}EVENT_TIME <= TIMESTAMP '{f.toDate:%Y-%m-%d} 23:59:59'")
            for column, value in (
                ("META_1", f.meta1),
                ("META_2", f.meta2),
                ("META_3", f.meta3),
            ):
                if value:
                    row.append(f"UPPER({p}{column}) LIKE UPPER('%{esc(value)}%')")
            if row:
                having.append(
                    f"MAX(CASE WHEN {' AND '.join(row)} THEN 1 ELSE 0 END) = 1"
                )

        included = list(f.includedSteps)
        excluded = list(f.excludedSteps)
        if included:
            having.append(
                f"MAX(CASE WHEN {p}STEP IN ({in_list(included)}) THEN 1 ELSE 0 END) = 1"
            )
        if excluded:
            having.append(
                f"MAX(CASE WHEN {p}STEP IN ({in_list(excluded)}) THEN 1 ELSE 0 END) = 0"
            )

        # META value include/exclude — same journey-level semantics as steps, per column.
        for column, inc, exc in (
            ("META_1", f.includedMeta1, f.excludedMeta1),
            ("META_2", f.includedMeta2, f.excludedMeta2),
            ("META_3", f.includedMeta3, f.excludedMeta3),
        ):
            if inc:
                having.append(
                    f"MAX(CASE WHEN {p}{column} IN ({in_list(inc)}) THEN 1 ELSE 0 END) = 1"
                )
            if exc:
                having.append(
                    f"MAX(CASE WHEN {p}{column} IN ({in_list(exc)}) THEN 1 ELSE 0 END) = 0"
                )

        if f.minSteps > 0 or f.maxSteps < INT_MAX:
            if f.minSteps > 0 and f.maxSteps < INT_MAX:
                having.append(f"COUNT(*) BETWEEN {f.minSteps} AND {f.maxSteps}")
            elif f.minSteps > 0:
                having.append(f"COUNT(*) >= {f.minSteps}")
            else:
                having.append(f"COUNT(*) <= {f.maxSteps}")

        if f.minJourneyTime > 0 or f.maxJourneyTime < INT_MAX:
            expr = f"SECONDS_BETWEEN(MAX({p}EVENT_TIME), MIN({p}EVENT_TIME))"
            if f.minJourneyTime > 0 and f.maxJourneyTime < INT_MAX:
                having.append(f"{expr} BETWEEN {f.minJourneyTime} AND {f.maxJourneyTime}")
            elif f.minJourneyTime > 0:
                having.append(f"{expr} >= {f.minJourneyTime}")
            else:
                having.append(f"{expr} <= {f.maxJourneyTime}")

        if score_active:
            having.append(
                f"SUM(COALESCE(s.SCORE, 0)) BETWEEN {f.minScore} AND {f.maxScore}"
            )

        if not having:
            return ""

        if score_active:
            # Join on the integer activity id (matches the transition template's
            # steps_u join) — STEP_ID is unique per project, so this is 1:1.
            source = (
                "JOURNEYS j LEFT JOIN STEPS s "
                "ON j.STEP_ID = s.STEP_ID AND j.PROJECT_ID = s.PROJECT_ID"
            )
            where = (
                f"j.PROJECT_ID = {project_id} "
                f"AND {self.active_sample_set.sql_fragment('j')}"
            )
            key = "j.EVENT_ID"
        else:
            source = "JOURNEYS"
            where = (
                f"PROJECT_ID = {project_id} "
                f"AND {self.active_sample_set.sql_fragment()}"
            )
            key = "EVENT_ID"

        return (
            "\n                AND EVENT_ID IN ("
            f"SELECT {key} FROM {source} WHERE {where} "
            f"GROUP BY {key} HAVING {' AND '.join(having)})"
        )

    def _all_filters(self, project_id: str, f: FilterSpec, *, date_only: bool) -> str:
        """`date_only=True` filters date + meta at row level (for row-level
        aggregates); `date_only=False` folds them into the journey qualifier as an
        "active in window" match, as the LEAD()-based transition query needs whole
        journeys. Every other journey-level filter goes through one consolidated
        EVENT_ID semi-join in both modes."""
        safe = _pid(project_id)
        clauses = self._sample_clause()
        if date_only:
            clauses += self._date_clause(f.fromDate, f.toDate)
            clauses += self._meta_clause(f.meta1, f.meta2, f.meta3)
            clauses += self._journey_qualifier(safe, f, include_date_meta=False)
        else:
            clauses += self._journey_qualifier(safe, f, include_date_meta=True)
        return clauses

    # ── projects, steps, metas ───────────────────────────────────────────────

    async def load_projects(self) -> list[Project]:
        result = await self.db.execute(
            "SELECT PROJECT_ID, TITLE, DESCRIPTION, TITLE_SHORT FROM PROJECTS ORDER BY TITLE"
        )
        projects: list[Project] = []
        for row in result.rows:
            if row[0] is None:  # PROJECT_ID is a SMALLINT (int) now, not a string
                continue
            projects.append(
                Project(
                    projectId=int(row[0]),
                    title=row[1] if isinstance(row[1], str) else "",
                    description=row[2] if isinstance(row[2], str) else "",
                    titleShort=row[3] if isinstance(row[3], str) else "",
                )
            )
        return projects

    async def load_steps(self, project_id: str) -> dict[str, StepInfo]:
        # STEPS is tiny and near-static but read on every map reload / journey view;
        # serve it from the per-user manager cache to save a serialised DB round trip.
        # The cache is invalidated by update_step and cleared on (dis)connect.
        cached = self.db._steps_cache.get(project_id)
        if cached is not None:
            return dict(cached)  # shallow copy so callers can't mutate the cache
        result = await self.db.execute(
            f"""
            SELECT STEP, DESCRIPTION, BG_COLOR, FG_COLOR, SCORE, SHAPE, END_OF_PROCESS, BELONGS_TO
            FROM STEPS
            WHERE PROJECT_ID = {_pid(project_id)}
            """
        )
        steps: dict[str, StepInfo] = {}
        for row in result.rows:
            step = row[0]
            if not isinstance(step, str):
                continue
            score = None if row[4] is None else as_int(row[4])
            steps[step] = StepInfo(
                step=step,
                description=row[1] if isinstance(row[1], str) else step,
                bgColor=row[2] if isinstance(row[2], str) else "blue",
                fgColor=row[3] if isinstance(row[3], str) else "white",
                score=score,
                shape=row[5] if isinstance(row[5], str) else "stadium",
                endOfProcess=as_bool(row[6]),
                belongsTo=row[7] if len(row) > 7 and isinstance(row[7], str) else None,
            )
        self.db._steps_cache[project_id] = steps
        return dict(steps)

    async def update_step(
        self,
        project_id: str,
        step: str,
        *,
        bg_color: str,
        fg_color: str,
        score: int | None,
        shape: str,
        belongs_to: str | None,
        description: str | None,
    ) -> None:
        score_sql = f"SCORE = {score}" if score is not None else "SCORE = NULL"
        belongs_sql = (
            f"BELONGS_TO = '{esc(belongs_to)}'" if belongs_to else "BELONGS_TO = NULL"
        )
        desc_sql = (
            f"DESCRIPTION = '{esc(description)}'"
            if description is not None
            else "DESCRIPTION = DESCRIPTION"
        )
        await self.db.execute(
            f"""
            UPDATE STEPS
            SET BG_COLOR = '{esc(bg_color)}',
                FG_COLOR = '{esc(fg_color)}',
                {score_sql},
                SHAPE = '{esc(shape)}',
                {belongs_sql},
                {desc_sql}
            WHERE PROJECT_ID = {_pid(project_id)}
            AND STEP = '{esc(step)}'
            """
        )
        # A step's colour/score/shape just changed — drop the cache so the next
        # load_steps re-reads (the update-step endpoint reloads immediately after).
        self.db.invalidate_steps(project_id)

    async def load_meta_titles(self, project_id: str) -> tuple[str | None, str | None, str | None]:
        result = await self.db.execute(
            f"""
            SELECT META_1_TITLE, META_2_TITLE, META_3_TITLE
            FROM METAS
            WHERE PROJECT_ID = {_pid(project_id)}
            """
        )
        if not result.rows:
            return (None, None, None)
        row = result.rows[0]
        return (clean_str(row[0]), clean_str(row[1]), clean_str(row[2]))

    async def load_meta_values(self, project_id: str, column: str) -> list[str]:
        if column not in {"META_1", "META_2", "META_3"}:
            raise ValueError(f"unsupported meta column {column!r}")
        result = await self.db.execute(
            f"""
            SELECT DISTINCT {column}
            FROM JOURNEYS
            WHERE PROJECT_ID = {_pid(project_id)}
            AND {self.active_sample_set.sql_fragment()}
            AND {column} IS NOT NULL
            ORDER BY {column}
            """
        )
        return [r[0] for r in result.rows if isinstance(r[0], str)]

    async def load_all_step_names(self, project_id: str) -> list[str]:
        result = await self.db.execute(
            "SELECT DISTINCT STEP FROM JOURNEYS "
            f"WHERE PROJECT_ID = {_pid(project_id)} "
            f"AND {self.active_sample_set.sql_fragment()} ORDER BY STEP"
        )
        return [r[0] for r in result.rows if isinstance(r[0], str)]

    # ── bounds ───────────────────────────────────────────────────────────────

    async def load_date_bounds(
        self, project_id: str
    ) -> tuple[datetime | None, datetime | None]:
        result = await self.db.execute(
            "SELECT MIN(EVENT_TIME), MAX(EVENT_TIME) FROM JOURNEYS "
            f"WHERE PROJECT_ID = {_pid(project_id)} "
            f"AND {self.active_sample_set.sql_fragment()}"
        )
        if not result.rows:
            return (None, None)
        row = result.rows[0]
        return (parse_date(row[0]), parse_date(row[1]))

    async def load_journey_time_bounds(self, project_id: str) -> tuple[int, int]:
        result = await self.db.execute(
            f"""
            SELECT MIN(dur), MAX(dur)
            FROM (
                SELECT SECONDS_BETWEEN(MAX(EVENT_TIME), MIN(EVENT_TIME)) AS dur
                FROM JOURNEYS
                WHERE PROJECT_ID = {_pid(project_id)}
                AND {self.active_sample_set.sql_fragment()}
                GROUP BY EVENT_ID
            ) AS j
            """
        )
        if not result.rows:
            return (0, 0)
        row = result.rows[0]
        return (max(0, as_int(row[0])), max(0, as_int(row[1])))

    async def load_step_count_bounds(self, project_id: str) -> tuple[int, int]:
        result = await self.db.execute(
            f"""
            SELECT MIN(cnt), MAX(cnt)
            FROM (
                SELECT COUNT(*) AS cnt
                FROM JOURNEYS
                WHERE PROJECT_ID = {_pid(project_id)}
                AND {self.active_sample_set.sql_fragment()}
                GROUP BY EVENT_ID
            ) AS j
            """
        )
        if not result.rows:
            return (1, 1)
        row = result.rows[0]
        return (as_int(row[0], 1), as_int(row[1], 1))

    async def load_score_bounds(self, project_id: str) -> tuple[int, int]:
        result = await self.db.execute(
            f"""
            SELECT MIN(journey_score), MAX(journey_score)
            FROM (
                SELECT j.EVENT_ID, SUM(COALESCE(s.SCORE, 0)) AS journey_score
                FROM JOURNEYS j
                LEFT JOIN STEPS s ON j.STEP = s.STEP AND j.PROJECT_ID = s.PROJECT_ID
                WHERE j.PROJECT_ID = {_pid(project_id)}
                AND {self.active_sample_set.sql_fragment('j')}
                GROUP BY j.EVENT_ID
            ) AS scored
            """
        )
        if not result.rows:
            return (0, 0)
        row = result.rows[0]
        return (as_int(row[0]), as_int(row[1]))

    async def load_project_bounds(self, project_id: str) -> "ProjectBounds":
        """All four whole-project filter-slider ranges — date, step-count, journey-
        time and score — in ONE scan instead of four separate queries. Values and
        empty-project defaults match the individual load_*_bounds methods above.

        Relies on the same assumption load_score_bounds already does: STEPS holds one
        row per (PROJECT_ID, STEP), so the LEFT JOIN never multiplies journey rows —
        COUNT(*) and MIN/MAX(EVENT_TIME) per journey stay identical to the un-joined
        queries, and SUM(score) is the journey score."""
        frag = self.active_sample_set.sql_fragment("j")
        result = await self.db.execute(
            f"""
            SELECT MIN(min_time), MAX(max_time),
                   MIN(cnt),      MAX(cnt),
                   MIN(dur),      MAX(dur),
                   MIN(jscore),   MAX(jscore)
            FROM (
                SELECT j.EVENT_ID,
                       MIN(j.EVENT_TIME) AS min_time,
                       MAX(j.EVENT_TIME) AS max_time,
                       COUNT(*)          AS cnt,
                       SECONDS_BETWEEN(MAX(j.EVENT_TIME), MIN(j.EVENT_TIME)) AS dur,
                       SUM(COALESCE(s.SCORE, 0)) AS jscore
                FROM JOURNEYS j
                LEFT JOIN STEPS s ON j.STEP = s.STEP AND j.PROJECT_ID = s.PROJECT_ID
                WHERE j.PROJECT_ID = {_pid(project_id)}
                AND {frag}
                GROUP BY j.EVENT_ID
            ) AS jb
            """
        )
        row = result.rows[0] if result.rows else [None] * 8
        return ProjectBounds(
            date_min=parse_date(row[0]), date_max=parse_date(row[1]),
            step_min=as_int(row[2], 1), step_max=as_int(row[3], 1),
            time_min=max(0, as_int(row[4])), time_max=max(0, as_int(row[5])),
            score_min=as_int(row[6]), score_max=as_int(row[7]),
        )

    async def load_meta_values_multi(
        self, project_id: str, columns: list[str]
    ) -> dict[str, list[str]]:
        """DISTINCT values for several META columns in ONE round trip (UNION ALL,
        tagged by column). Each list is sorted, matching load_meta_values."""
        cols = [c for c in columns if c in {"META_1", "META_2", "META_3"}]
        out: dict[str, list[str]] = {c: [] for c in cols}
        if not cols:
            return out
        safe = _pid(project_id)
        frag = self.active_sample_set.sql_fragment()
        parts = [
            f"SELECT '{c}' AS col, {c} AS val FROM JOURNEYS "
            f"WHERE PROJECT_ID = {safe} AND {frag} AND {c} IS NOT NULL GROUP BY {c}"
            for c in cols
        ]
        sql = " UNION ALL ".join(parts) + " ORDER BY col, val"
        result = await self.db.execute(sql)
        for row in result.rows:
            col, val = row[0], row[1]
            if isinstance(col, str) and col in out and isinstance(val, str):
                out[col].append(val)
        return out

    async def load_node_meta_values(
        self, project_id: str, step: str
    ) -> dict[str, list[dict[str, Any]]]:
        """The META_1/2/3 values that occur on the events of ONE step (node) — what the
        node's "Meta Infos" panel lists, scoped to that node. Each distinct value carries
        the date/time it was last seen (``time``) and how many of the node's events carry
        it (``count``), so the panel can show and search a second date/time field. One
        round trip (UNION ALL tagged by column), newest first."""
        cols = ["META_1", "META_2", "META_3"]
        out: dict[str, list[dict[str, Any]]] = {c: [] for c in cols}
        safe = _pid(project_id)
        frag = self.active_sample_set.sql_fragment()
        step_sql = f"STEP = '{esc(step)}'"
        parts = [
            f"SELECT '{c}' AS col, {c} AS val, MAX(EVENT_TIME) AS ts, COUNT(*) AS cnt "
            f"FROM JOURNEYS "
            f"WHERE PROJECT_ID = {safe} AND {frag} AND {step_sql} AND {c} IS NOT NULL "
            f"GROUP BY {c}"
            for c in cols
        ]
        # Order by output position (unambiguous across UNION ALL): column, then most
        # recent occurrence first, then value.
        sql = " UNION ALL ".join(parts) + " ORDER BY 1, 3 DESC, 2"
        result = await self.db.execute(sql)
        for row in result.rows:
            col, val = row[0], row[1]
            if not (isinstance(col, str) and col in out and isinstance(val, str)):
                continue
            when = parse_date(row[2]) if len(row) > 2 else None
            out[col].append({
                "value": val,
                "time": when.strftime("%Y-%m-%d %H:%M:%S") if when else "",
                "count": as_int(row[3]) if len(row) > 3 else 1,
            })
        return out

    async def find_nearest_day_with_data(
        self, day: datetime, project_id: str
    ) -> datetime | None:
        safe = _pid(project_id)
        frag = self.active_sample_set.sql_fragment()
        start_of_day = datetime(day.year, day.month, day.day)
        next_day = start_of_day + timedelta(days=1)

        forward = await self.db.execute(
            f"SELECT MIN(EVENT_TIME) FROM JOURNEYS WHERE PROJECT_ID = {safe} "
            f"AND {frag} AND EVENT_TIME >= '{next_day:%Y-%m-%d}'"
        )
        if forward.rows and (found := parse_date(forward.rows[0][0])):
            return datetime(found.year, found.month, found.day)

        backward = await self.db.execute(
            f"SELECT MAX(EVENT_TIME) FROM JOURNEYS WHERE PROJECT_ID = {safe} "
            f"AND {frag} AND EVENT_TIME < '{start_of_day:%Y-%m-%d}'"
        )
        if backward.rows and (found := parse_date(backward.rows[0][0])):
            return datetime(found.year, found.month, found.day)
        return None

    # ── counts, transitions, graph ───────────────────────────────────────────

    async def load_journey_count(self, project_id: str, f: FilterSpec) -> int:
        filters = self._all_filters(project_id, f, date_only=True)
        result = await self.db.execute(
            f"""
            SELECT COUNT(DISTINCT EVENT_ID)
            FROM JOURNEYS
            WHERE PROJECT_ID = {_pid(project_id)}{filters}
            """
        )
        if not result.rows:
            return 0
        return as_int(result.rows[0][0])

    @staticmethod
    def _normalize_event_id(raw: str) -> str:
        """Match the app's EVENT_ID convention: a 32-char hex string is already the
        stored MD5; anything else (a business id like ``CRA-000124``) is MD5-hashed."""
        raw = raw.strip()
        is_md5 = len(raw) == 32 and all(c in "0123456789abcdefABCDEF" for c in raw)
        return raw if is_md5 else hashlib.md5(raw.encode("utf-8")).hexdigest()

    def _log_entries_sql(
        self,
        project_id: str,
        steps: list[str],
        f: FilterSpec,
        *,
        event_ids: list[str] | None,
        limit: int,
        descending: bool,
    ) -> str:
        step_list = ", ".join(f"'{esc(s)}'" for s in steps)
        clauses = self._all_filters(project_id, f, date_only=True)
        clauses += f"\n                AND STEP IN ({step_list})"
        if event_ids:
            eid_list = ", ".join(
                f"'{esc(self._normalize_event_id(e))}'" for e in event_ids if e.strip()
            )
            if eid_list:
                clauses += f"\n                AND EVENT_ID IN ({eid_list})"
        order = "DESC" if descending else "ASC"
        return f"""
            SELECT EVENT_ID, STEP, EVENT_TIME, META_1, META_2, META_3
            FROM JOURNEYS
            WHERE PROJECT_ID = {_pid(project_id)}{clauses}
            ORDER BY EVENT_TIME {order}, STEP_ID {order}
            LIMIT {_clamp(limit, 1, _MAX_LOG_ENTRIES)}
            """

    async def load_log_entries(
        self,
        project_id: str,
        steps: list[str],
        f: FilterSpec,
        *,
        event_ids: list[str] | None = None,
        limit: int = 1,
        descending: bool = True,
    ) -> dict[str, Any]:
        """Raw JOURNEYS rows for the given steps (an Action's resolved node set),
        honouring the chart filter ``f`` plus an optional EVENT_ID allow-list, newest
        first by default. Returns ``{columns, rows}`` for a generic result table."""
        if not steps:
            return {"columns": LOG_ENTRY_COLUMNS, "rows": []}
        result = await self.db.execute(
            self._log_entries_sql(
                project_id, steps, f, event_ids=event_ids, limit=limit, descending=descending
            ),
            timeout=QUERY_TIMEOUT_SECS,
        )
        rows: list[list[Any]] = []
        for row in result.rows:
            cells = (list(row) + [None] * 6)[:6]
            eid, step, when = cells[0], cells[1], cells[2]
            dt = parse_date(when)
            rows.append(
                [
                    eid if isinstance(eid, str) else (str(eid) if eid is not None else None),
                    step if isinstance(step, str) else (str(step) if step is not None else None),
                    dt.isoformat(sep=" ") if dt else (str(when) if when is not None else None),
                    clean_str(cells[3]),
                    clean_str(cells[4]),
                    clean_str(cells[5]),
                ]
            )
        return {"columns": LOG_ENTRY_COLUMNS, "rows": rows}

    async def load_transitions(
        self, project_id: str, f: FilterSpec
    ) -> list[ProcessTransition]:
        filters = self._all_filters(project_id, f, date_only=False)

        # When the active connection opts into pre-materialised transitions, read
        # the precomputed pairs (no LEAD() window at request time). The same
        # {filters} applies unchanged — TRANSITIONS_RAW carries PROJECT_ID,
        # SAMPLE_SET and EVENT_ID. Any failure (table not built yet, missing) is
        # non-fatal: fall back to the live query so the map never breaks.
        #
        # Sample sets always use the LIVE query, never TRANSITIONS_RAW. A sample is
        # created/rebuilt on demand and TRANSITIONS_RAW is only rebuilt separately, so a
        # materialised read of a just-made sample would come back EMPTY (its pairs aren't
        # in the table yet) — the map would silently look blank. Samples are subsets, so
        # the live LEAD() over them is cheap anyway.
        enabled = bool(getattr(self.db, "use_materialized_transitions", False))
        if enabled and not self.active_sample_set.is_original:
            enabled = False
        if enabled:
            try:
                result = await self.db.execute(
                    self._materialized_transitions_sql(project_id, filters)
                )
                self.last_transitions_mode = "materialized"
                return self._rows_to_transitions(result.rows)
            except Exception as exc:  # noqa: BLE001 — graceful fallback to live
                # Loud on purpose: if materialized is enabled and TRANSITIONS_RAW
                # exists but the read still fails, this is the only place the real
                # cause surfaces (admin Logging tab, operation=materialize).
                logx.warn(
                    f"Pre-materialized transitions are enabled but reading "
                    f"TRANSITIONS_RAW failed for project {project_id!r} — falling "
                    f"back to the live query. Cause: {exc}",
                    operation="materialize",
                )

        # 'fallback' = enabled but the table isn't usable yet (needs a rebuild);
        # 'live' = not enabled at all. Both run the live query; the distinction
        # lets the UI tell the user their setting is on but a rebuild is pending.
        self.last_transitions_mode = "fallback" if enabled else "live"
        result = await self.db.execute(self._live_transitions_sql(project_id, filters))
        return self._rows_to_transitions(result.rows)

    @staticmethod
    def _materialized_transitions_sql(project_id: str, filters: str) -> str:
        """Aggregate the precomputed pairs — no window function at request time.

        TRANSITIONS_RAW stores FROM_STEP_ID / TO_STEP_ID (activity ids); grouping
        runs on those integers and STEP names are attached in the final join,
        matching the live query so both paths return identical rows."""
        safe = _pid(project_id)
        return f"""
            SELECT S.STEP AS FROM_STEP, T.STEP AS TO_STEP,
                   H.CNT, H.AVG_SECS, H.MEDIAN_SECS, H.MIN_SECS, H.MAX_SECS, H.STDDEV_SECS
            FROM (
                SELECT FROM_STEP_ID, TO_STEP_ID, COUNT(*) AS CNT,
                       AVG(DUR_SECS)    AS AVG_SECS,
                       MIN(DUR_SECS)    AS MIN_SECS,
                       MAX(DUR_SECS)    AS MAX_SECS,
                       STDDEV(DUR_SECS) AS STDDEV_SECS,
                       MEDIAN(DUR_SECS) AS MEDIAN_SECS
                FROM TRANSITIONS_RAW
                WHERE PROJECT_ID = {safe}{filters}
                GROUP BY FROM_STEP_ID, TO_STEP_ID
            ) AS H
            JOIN STEPS S ON S.PROJECT_ID = {safe} AND S.STEP_ID = H.FROM_STEP_ID
            JOIN STEPS T ON T.PROJECT_ID = {safe} AND T.STEP_ID = H.TO_STEP_ID
            """

    @staticmethod
    def _live_transitions_sql(project_id: str, filters: str) -> str:
        """Compute pairs on the fly with LEAD() — the always-available path.

        The DFG is built on the integer STEP_ID (activity id): LEAD / GROUP BY /
        PARTITION BY all run on STEP_ID, and the step NAMES are attached only in
        the final projection (one join per direction against STEPS). Grouping on a
        DECIMAL id instead of a VARCHAR(500) name is the performance win."""
        safe = _pid(project_id)
        return f"""
            SELECT S.STEP AS FROM_STEP, T.STEP AS TO_STEP,
                   H.CNT, H.AVG_SECS, H.MEDIAN_SECS, H.MIN_SECS, H.MAX_SECS, H.STDDEV_SECS
            FROM (
                SELECT FROM_STEP_ID, TO_STEP_ID, COUNT(*) AS CNT,
                       AVG(DUR_SECS)    AS AVG_SECS,
                       MIN(DUR_SECS)    AS MIN_SECS,
                       MAX(DUR_SECS)    AS MAX_SECS,
                       STDDEV(DUR_SECS) AS STDDEV_SECS,
                       MEDIAN(DUR_SECS) AS MEDIAN_SECS
                FROM (
                    SELECT FROM_STEP_ID, TO_STEP_ID,
                           SECONDS_BETWEEN(TO_TIME, FROM_TIME) AS DUR_SECS
                    FROM (
                        SELECT
                            STEP_ID    AS FROM_STEP_ID,
                            EVENT_TIME AS FROM_TIME,
                            LEAD(STEP_ID)    OVER (PARTITION BY EVENT_ID ORDER BY EVENT_TIME, STEP_ID) AS TO_STEP_ID,
                            LEAD(EVENT_TIME) OVER (PARTITION BY EVENT_ID ORDER BY EVENT_TIME, STEP_ID) AS TO_TIME
                        FROM JOURNEYS
                        WHERE PROJECT_ID = {safe}{filters}
                    ) AS t
                    WHERE TO_STEP_ID IS NOT NULL AND TO_TIME IS NOT NULL
                ) AS d
                GROUP BY FROM_STEP_ID, TO_STEP_ID
            ) AS H
            JOIN STEPS S ON S.PROJECT_ID = {safe} AND S.STEP_ID = H.FROM_STEP_ID
            JOIN STEPS T ON T.PROJECT_ID = {safe} AND T.STEP_ID = H.TO_STEP_ID
            """

    @staticmethod
    def _rows_to_transitions(rows: list[list[Any]]) -> list[ProcessTransition]:
        transitions: list[ProcessTransition] = []
        for row in rows:
            if not isinstance(row[0], str) or not isinstance(row[1], str):
                continue
            if row[2] is None:
                continue
            transitions.append(
                ProcessTransition(
                    fromStep=row[0],
                    toStep=row[1],
                    occurrences=as_int(row[2]),
                    avgSecs=as_float(row[3]),
                    medianSecs=as_float(row[4]),
                    minSecs=as_float(row[5]),
                    maxSecs=as_float(row[6]),
                    stdDevSecs=as_float(row[7]),
                )
            )
        return transitions

    @staticmethod
    def _assemble_graph(
        steps: dict[str, StepInfo], transitions: list[ProcessTransition]
    ) -> ProcessGraph:
        referenced = {t.fromStep for t in transitions} | {t.toStep for t in transitions}
        pruned = {name: info for name, info in steps.items() if name in referenced}
        for node in referenced:
            if node not in pruned:
                pruned[node] = StepInfo(
                    step=node,
                    description=node,
                    bgColor="gray",
                    fgColor="white",
                    shape="stadium",
                )
        return ProcessGraph(steps=pruned, transitions=transitions)

    async def load_graph(self, project_id: str, f: FilterSpec) -> ProcessGraph:
        steps = await self.load_steps(project_id)
        transitions = await self.load_transitions(project_id, f)
        return self._assemble_graph(steps, transitions)

    async def load_journey_duration_stats(
        self, project_id: str, f: FilterSpec
    ) -> DurationStats:
        filters = self._all_filters(project_id, f, date_only=True)
        result = await self.db.execute(
            f"""
            SELECT
                MIN(SECONDS_BETWEEN(MAX_TIME, MIN_TIME)) AS MIN_SECS,
                AVG(SECONDS_BETWEEN(MAX_TIME, MIN_TIME)) AS AVG_SECS,
                MEDIAN(SECONDS_BETWEEN(MAX_TIME, MIN_TIME)) AS MEDIAN_SECS,
                MAX(SECONDS_BETWEEN(MAX_TIME, MIN_TIME)) AS MAX_SECS,
                STDDEV(SECONDS_BETWEEN(MAX_TIME, MIN_TIME)) AS STDDEV_SECS
            FROM (
                SELECT EVENT_ID,
                       MIN(EVENT_TIME) AS MIN_TIME,
                       MAX(EVENT_TIME) AS MAX_TIME
                FROM JOURNEYS
                WHERE PROJECT_ID = {_pid(project_id)}{filters}
                GROUP BY EVENT_ID
            ) AS j
            """
        )
        if not result.rows:
            return DurationStats()
        row = result.rows[0]
        return DurationStats(
            minSecs=as_float(row[0]),
            avgSecs=as_float(row[1]),
            medianSecs=as_float(row[2]),
            maxSecs=as_float(row[3]),
            stdDevSecs=as_float(row[4]),
        )

    async def load_duration_buckets(
        self, project_id: str, f: FilterSpec, bin_count: int = 10
    ) -> list[DurationBucket]:
        filters = self._all_filters(project_id, f, date_only=True)
        safe = _pid(project_id)
        n = bin_count
        # Per-journey durations are computed ONCE; the global min/max come from
        # window aggregates over that same result (MIN/MAX OVER ()), so JOURNEYS is
        # scanned a single time — the previous self-join aggregated it twice.
        sql = f"""
            SELECT bin_idx, COUNT(*) AS cnt, MIN(min_dur) AS min_dur, MIN(max_dur) AS max_dur
            FROM (
                SELECT
                    CASE
                        WHEN mx = mn THEN 0
                        ELSE LEAST(FLOOR((dur - mn) / (mx - mn) * {n}), {n - 1})
                    END AS bin_idx,
                    mn AS min_dur,
                    mx AS max_dur
                FROM (
                    SELECT dur,
                           MIN(dur) OVER () AS mn,
                           MAX(dur) OVER () AS mx
                    FROM (
                        SELECT SECONDS_BETWEEN(MAX(EVENT_TIME), MIN(EVENT_TIME)) AS dur
                        FROM JOURNEYS
                        WHERE PROJECT_ID = {safe}{filters}
                        GROUP BY EVENT_ID
                    ) d
                ) w
            ) binned
            GROUP BY bin_idx
            ORDER BY bin_idx
            """
        result = await self.db.execute(sql)
        if not result.rows:
            return []

        min_dur = as_float(result.rows[0][2]) or 0.0
        max_dur = as_float(result.rows[0][3]) or 0.0
        bin_width = (max_dur - min_dur) / n if max_dur > min_dur else max(max_dur, 1.0)

        buckets: list[DurationBucket] = []
        for row in result.rows:
            idx = as_int(row[0])
            low = min_dur + idx * bin_width
            high = low + bin_width
            buckets.append(
                DurationBucket(
                    label=f"{dur_label(low)}–{dur_label(high)}", count=as_int(row[1])
                )
            )
        return buckets

    async def load_journey_time_series(
        self, project_id: str, f: FilterSpec, granularity: TimeGranularity
    ) -> list[JourneyTimePoint]:
        filters = self._all_filters(project_id, f, date_only=True)
        trunc = {
            TimeGranularity.day: "CAST(EVENT_TIME AS DATE)",
            TimeGranularity.week: "TRUNC(EVENT_TIME, 'IW')",
            TimeGranularity.month: "TRUNC(EVENT_TIME, 'MM')",
        }[granularity]
        result = await self.db.execute(
            f"""
            SELECT {trunc} AS period, COUNT(DISTINCT EVENT_ID) AS cnt
            FROM JOURNEYS
            WHERE PROJECT_ID = {_pid(project_id)}{filters}
            GROUP BY {trunc}
            ORDER BY {trunc}
            """
        )
        points: list[JourneyTimePoint] = []
        for row in result.rows:
            when = parse_date(row[0])
            if when is None:
                continue
            points.append(JourneyTimePoint(date=when, count=as_int(row[1])))
        return points

    # ── variants & goodness ──────────────────────────────────────────────────

    async def load_journey_paths(
        self, project_id: str, f: FilterSpec, limit: int = 500
    ) -> list[JourneyPath]:
        limit = _clamp(limit, 1, _MAX_PATH_ROWS)
        filters = self._all_filters(project_id, f, date_only=True)
        sql = f"""
            WITH ordered_paths AS (
                SELECT
                    j.EVENT_ID,
                    LISTAGG(j.STEP, ' -> ') WITHIN GROUP (ORDER BY j.EVENT_TIME ASC) AS full_path,
                    COUNT(j.STEP)             AS path_length,
                    SUM(COALESCE(s.SCORE, 0)) AS score
                FROM JOURNEYS j
                LEFT JOIN STEPS s ON j.STEP = s.STEP AND j.PROJECT_ID = s.PROJECT_ID
                WHERE j.PROJECT_ID = {_pid(project_id)}{filters}
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
            LIMIT {limit}
            """
        try:
            result = await self.db.execute(sql, timeout=QUERY_TIMEOUT_SECS)
        except asyncio.TimeoutError as exc:
            raise TimeoutError(
                f"Statistics query timed out ({QUERY_TIMEOUT_SECS:.0f} s). "
                "Narrow your date range or filters and try again."
            ) from exc

        paths: list[JourneyPath] = []
        for row in result.rows:
            if not isinstance(row[0], str):
                continue
            paths.append(
                JourneyPath(
                    path=row[0],
                    journeyCount=as_int(row[1]),
                    stepCount=as_int(row[2]),
                    totalScore=as_int(row[3]),
                )
            )
        return paths

    async def load_process_goodness(
        self, project_id: str, f: FilterSpec
    ) -> tuple[float, int] | None:
        """Returns (rawGoodness, filteredCount); the caller applies the coverage
        penalty `raw * (filtered / total) ** 0.5`."""
        filters = self._all_filters(project_id, f, date_only=True)
        # Goodness is a path-frequency-weighted mean, but the per-path term
        # (total_score / sqrt(path_length) - 0.01 * avg_duration) is CONSTANT across the
        # journeys that share a path (score and length are fixed by the step sequence), so
        # the frequency weighting collapses algebraically to a plain per-journey average:
        #   sum_paths (count_p/total) * term_p  ==  avg_journeys(term_j).
        # That removes the LISTAGG path string and the distinct-path GROUP BY entirely — one
        # cheap GROUP BY EVENT_ID pass, no per-journey sort. The `{filters}` semi-join +
        # row-level date/meta are unchanged, so the result is identical to the grouped form.
        # (Valid only while the term is linear per journey; if goodness ever gains a factor
        # applied ONCE PER DISTINCT PATH, restore the ordered_paths/distinct_paths grouping.)
        sql = f"""
            WITH per_journey AS (
                SELECT
                    COUNT(j.STEP)                                                      AS path_length,
                    SUM(COALESCE(s.SCORE, 0))                                          AS total_score,
                    COALESCE(SECONDS_BETWEEN(MAX(j.EVENT_TIME), MIN(j.EVENT_TIME)), 0) AS journey_duration
                FROM JOURNEYS j
                LEFT JOIN STEPS s ON j.STEP_ID = s.STEP_ID AND j.PROJECT_ID = s.PROJECT_ID
                WHERE j.PROJECT_ID = {_pid(project_id)}{filters}
                GROUP BY j.EVENT_ID
            )
            SELECT
                AVG(
                    CAST(total_score AS DOUBLE) / SQRT(CAST(GREATEST(path_length, 1) AS DOUBLE)) -
                    0.01 * journey_duration
                ) AS raw_goodness,
                COUNT(*) AS filtered_count
            FROM per_journey
            """
        try:
            result = await self.db.execute(sql, timeout=QUERY_TIMEOUT_SECS)
        except asyncio.TimeoutError:
            return None
        if not result.rows:
            return None
        raw = as_float(result.rows[0][0])
        if raw is None:
            return None
        return (raw, as_int(result.rows[0][1]))

    # ── individual journeys ──────────────────────────────────────────────────

    async def load_event_id_suggestions(
        self, project_id: str, prefix: str, limit: int = 10
    ) -> list[str]:
        limit = _clamp(limit, 1, _MAX_SUGGESTIONS)
        result = await self.db.execute(
            f"""
            SELECT DISTINCT EVENT_ID
            FROM JOURNEYS
            WHERE PROJECT_ID = {_pid(project_id)}
            AND {self.active_sample_set.sql_fragment()}
            AND UPPER(CAST(EVENT_ID AS VARCHAR(32))) LIKE UPPER('%{esc(prefix)}%')
            ORDER BY EVENT_ID
            LIMIT {limit}
            """
        )
        return [r[0] for r in result.rows if isinstance(r[0], str)]

    async def load_journeys(
        self,
        project_id: str,
        f: FilterSpec,
        *,
        order_by: str = "DURATION_DESC",
        limit: int = 20,
        min_duration_secs: float | None = None,
        max_duration_secs: float | None = None,
        min_steps: int | None = None,
        max_steps: int | None = None,
        include_path: bool = False,
    ) -> list[dict[str, Any]]:
        """Individual journeys matching ``f``, one aggregate row per EVENT_ID.

        The counterpart to the aggregate loaders: where load_journey_paths collapses
        cases into variants and load_journey_duration_stats into four numbers, this
        keeps the cases themselves, so a caller can get from "the average is 63 min"
        to the actual slowest journeys and open one with load_journey_sequence.

        Duration and step-count bounds are HAVING clauses on the same grouping, so a
        journey qualifies on its whole trace, not on individual rows. ``order_by`` is
        a key of JOURNEY_ORDERS; EVENT_ID breaks ties so the order is total.
        """
        clause = JOURNEY_ORDERS.get(order_by.upper())
        if clause is None:
            raise ValueError(
                f"Unknown order_by {order_by!r}; expected one of {', '.join(JOURNEY_ORDERS)}."
            )
        limit = _clamp(limit, 1, _MAX_JOURNEY_ROWS)
        filters = self._all_filters(project_id, f, date_only=True)

        # HAVING repeats the aggregate expressions rather than the SELECT aliases:
        # alias visibility in HAVING is not portable, the ORDER BY alias is.
        secs = "SECONDS_BETWEEN(MAX(EVENT_TIME), MIN(EVENT_TIME))"
        having: list[str] = []
        if min_duration_secs is not None:
            having.append(f"{secs} >= {float(min_duration_secs)}")
        if max_duration_secs is not None:
            having.append(f"{secs} <= {float(max_duration_secs)}")
        if min_steps is not None:
            having.append(f"COUNT(*) >= {int(min_steps)}")
        if max_steps is not None:
            having.append(f"COUNT(*) <= {int(max_steps)}")
        having_sql = ("\n            HAVING " + "\n              AND ".join(having)) if having else ""

        # PATH is reserved in Exasol, so the column is JOURNEY_PATH — load_journey_paths
        # sidesteps this by aliasing in lower case inside a CTE; here it is a plain alias.
        path_select = (
            ",\n                LISTAGG(STEP, ' -> ') WITHIN GROUP (ORDER BY EVENT_TIME ASC)"
            " AS JOURNEY_PATH"
            if include_path
            else ""
        )

        sql = f"""
            SELECT
                EVENT_ID,
                MIN(EVENT_TIME) AS START_TIME,
                MAX(EVENT_TIME) AS END_TIME,
                SECONDS_BETWEEN(MAX(EVENT_TIME), MIN(EVENT_TIME)) AS DURATION_SECS,
                COUNT(*) AS STEP_COUNT,
                MAX(META_1) AS META_1,
                MAX(META_2) AS META_2,
                MAX(META_3) AS META_3{path_select}
            FROM JOURNEYS
            WHERE PROJECT_ID = {_pid(project_id)}{filters}
            GROUP BY EVENT_ID{having_sql}
            ORDER BY {clause}, EVENT_ID
            LIMIT {limit}
            """
        try:
            result = await self.db.execute(sql, timeout=QUERY_TIMEOUT_SECS)
        except asyncio.TimeoutError as exc:
            raise TimeoutError(
                f"Journey query timed out ({QUERY_TIMEOUT_SECS:.0f} s). "
                "Narrow your date range or filters and try again."
            ) from exc

        journeys: list[dict[str, Any]] = []
        for row in result.rows:
            if not isinstance(row[0], str):
                continue
            journeys.append(
                {
                    "eventId": row[0],
                    "startDate": parse_date(row[1]),
                    "endDate": parse_date(row[2]),
                    "durationSecs": as_float(row[3]),
                    "stepCount": as_int(row[4]),
                    "meta1": clean_str(row[5]),
                    "meta2": clean_str(row[6]),
                    "meta3": clean_str(row[7]),
                    "path": clean_str(row[8]) if include_path and len(row) > 8 else None,
                }
            )
        return journeys

    async def load_journey_info(self, project_id: str, event_id: str) -> dict[str, Any]:
        result = await self.db.execute(
            f"""
            SELECT MIN(EVENT_TIME), MAX(EVENT_TIME),
                   MAX(META_1), MAX(META_2), MAX(META_3)
            FROM JOURNEYS
            WHERE PROJECT_ID = {_pid(project_id)}
            AND {self.active_sample_set.sql_fragment()}
            AND EVENT_ID = '{esc(event_id)}'
            """
        )
        if not result.rows:
            return {}
        row = result.rows[0]
        return {
            "startDate": parse_date(row[0]),
            "endDate": parse_date(row[1]),
            "meta1": clean_str(row[2]),
            "meta2": clean_str(row[3]),
            "meta3": clean_str(row[4]),
        }

    async def load_journey_sequence(
        self, project_id: str, event_id: str
    ) -> list[dict[str, Any]]:
        """The journey's events in time order — ``[{step, eventTime}, …]``.

        This is the raw ordered trace (the same ordering the journey graph is built from:
        EVENT_TIME then STEP_ID), so the swimlane view can lay each event out
        sequentially. A revisited step simply appears again — loops are unrolled by
        construction — which is exactly what a strictly-sequential lane layout needs.
        """
        result = await self.db.execute(
            f"""
            SELECT STEP, EVENT_TIME
            FROM JOURNEYS
            WHERE PROJECT_ID = {_pid(project_id)}
            AND {self.active_sample_set.sql_fragment()}
            AND EVENT_ID = '{esc(event_id)}'
            ORDER BY EVENT_TIME, STEP_ID
            """
        )
        out: list[dict[str, Any]] = []
        for row in result.rows:
            step = row[0]
            when = parse_date(row[1])
            if isinstance(step, str) and when is not None:
                out.append({"step": step, "eventTime": when})
        return out

    async def load_journey_graph(self, project_id: str, event_id: str) -> ProcessGraph:
        safe_pid, safe_eid = _pid(project_id), esc(event_id)
        frag = self.active_sample_set.sql_fragment()

        trans_result = await self.db.execute(
            f"""
            SELECT S.STEP AS FROM_STEP, T.STEP AS TO_STEP,
                   H.CNT, H.AVG_SECS, H.MEDIAN_SECS, H.MIN_SECS, H.MAX_SECS, H.STDDEV_SECS
            FROM (
                SELECT FROM_STEP_ID, TO_STEP_ID, COUNT(*) AS CNT,
                       AVG(DUR_SECS)    AS AVG_SECS,
                       MIN(DUR_SECS)    AS MIN_SECS,
                       MAX(DUR_SECS)    AS MAX_SECS,
                       STDDEV(DUR_SECS) AS STDDEV_SECS,
                       MEDIAN(DUR_SECS) AS MEDIAN_SECS
                FROM (
                    SELECT FROM_STEP_ID, TO_STEP_ID,
                           SECONDS_BETWEEN(TO_TIME, FROM_TIME) AS DUR_SECS
                    FROM (
                        SELECT
                            STEP_ID    AS FROM_STEP_ID,
                            EVENT_TIME AS FROM_TIME,
                            LEAD(STEP_ID)    OVER (PARTITION BY EVENT_ID ORDER BY EVENT_TIME, STEP_ID) AS TO_STEP_ID,
                            LEAD(EVENT_TIME) OVER (PARTITION BY EVENT_ID ORDER BY EVENT_TIME, STEP_ID) AS TO_TIME
                        FROM JOURNEYS
                        WHERE PROJECT_ID = {safe_pid}
                        AND {frag}
                        AND EVENT_ID = '{safe_eid}'
                    ) AS t
                    WHERE TO_STEP_ID IS NOT NULL AND TO_TIME IS NOT NULL
                ) AS d
                GROUP BY FROM_STEP_ID, TO_STEP_ID
            ) AS H
            JOIN STEPS S ON S.PROJECT_ID = {safe_pid} AND S.STEP_ID = H.FROM_STEP_ID
            JOIN STEPS T ON T.PROJECT_ID = {safe_pid} AND T.STEP_ID = H.TO_STEP_ID
            """
        )
        transitions = self._rows_to_transitions(trans_result.rows)

        time_result = await self.db.execute(
            f"""
            SELECT STEP, MIN(EVENT_TIME) AS FIRST_TIME
            FROM JOURNEYS
            WHERE PROJECT_ID = {safe_pid}
            AND {frag}
            AND EVENT_ID = '{safe_eid}'
            GROUP BY STEP
            """
        )
        step_times: dict[str, datetime] = {}
        for row in time_result.rows:
            if isinstance(row[0], str) and (when := parse_date(row[1])):
                step_times[row[0]] = when

        steps = await self.load_steps(project_id)
        graph = self._assemble_graph(steps, transitions)
        for name, when in step_times.items():
            if name in graph.steps:
                graph.steps[name].eventTime = when
        return graph

    # ── NOTES table ──────────────────────────────────────────────────────────

    async def ensure_notes_table(self) -> None:
        from .schema_ddl import NOTES_DDL

        await self.db.execute_quiet(NOTES_DDL)
        await self.db.execute_quiet(
            "ALTER TABLE NOTES ADD COLUMN IS_SHARED BOOLEAN DEFAULT FALSE"
        )
        await self.db.execute_quiet(
            "ALTER TABLE NOTES ADD COLUMN EDITED_BY VARCHAR(200) DEFAULT ''"
        )
        await self.db.execute_quiet(
            "ALTER TABLE NOTES ADD COLUMN IMPORTANCE VARCHAR(20) DEFAULT 'NORMAL'"
        )
        await self.db.execute_quiet(
            "ALTER TABLE NOTES ADD COLUMN RESOLVED BOOLEAN DEFAULT FALSE"
        )
        await self.db.execute_quiet(
            "ALTER TABLE NOTES ADD COLUMN TITLE VARCHAR(500) DEFAULT ''"
        )
        # Widen NOTE (was VARCHAR(8000)) so an append-only comment thread has room.
        await self.db.execute_quiet(
            "ALTER TABLE NOTES MODIFY COLUMN NOTE VARCHAR(100000)"
        )

    # Column order shared by load_notes / get_note — indices used by _row_to_note.
    _NOTE_COLUMNS = (
        "ID, NOTES_DATE, EDITED_DATE, NOTE_USER, NOTE, IS_SHARED, EDITED_BY, "
        "TARGET_TYPE, TARGET_FROM, TARGET_TO, FILTER_SNAPSHOT, IMPORTANCE, RESOLVED, TITLE"
    )

    @staticmethod
    def _row_to_note(row) -> ProcessNote | None:
        created = parse_date(row[1])
        if not isinstance(row[0], str) or created is None:
            return None
        target_type = row[7] if isinstance(row[7], str) else "node"
        target_from = row[8] if isinstance(row[8], str) else ""
        target_to = row[9] if isinstance(row[9], str) else ""
        if target_type == "edge" and target_to:
            target = NoteTarget.model_validate(
                {"type": "edge", "from": target_from, "to": target_to}
            )
        else:
            target = NoteTarget(type="node", value=target_from)

        snapshot: FilterSnapshot | None = None
        if isinstance(row[10], str) and row[10]:
            try:
                snapshot = FilterSnapshot(**json.loads(row[10]))
            except (json.JSONDecodeError, TypeError, ValueError):
                snapshot = None
        if snapshot is None:
            now = datetime.now()
            snapshot = FilterSnapshot(fromDate=now, toDate=now)

        return ProcessNote(
            id=row[0],
            title=row[13] if len(row) > 13 and isinstance(row[13], str) else "",
            text=row[4] if isinstance(row[4], str) else "",
            createdAt=created,
            editedAt=parse_date(row[2]),
            target=target,
            filterSnapshot=snapshot,
            username=row[3] if isinstance(row[3], str) else "",
            lastEditedBy=row[6] if isinstance(row[6], str) else "",
            isShared=as_bool(row[5]),
            importance=normalize_importance(row[11] if len(row) > 11 else None),
            resolved=as_bool(row[12]) if len(row) > 12 else False,
        )

    async def load_notes(self, project_id: str, username: str) -> list[ProcessNote]:
        # Always visibility-filter (fail closed): an unknown/empty user must still
        # only see unowned or shared notes, never another user's private ones.
        safe_user = esc(username.upper())
        vis_filter = (
            f"AND (UPPER(NOTE_USER) = '{safe_user}' "
            "OR NOTE_USER = '' OR IS_SHARED = TRUE)"
        )
        result = await self.db.execute(
            f"""
            SELECT {self._NOTE_COLUMNS}
            FROM NOTES
            WHERE PROJECT_ID = {_pid(project_id)}
            {vis_filter}
            ORDER BY NOTES_DATE ASC
            """
        )
        return [n for row in result.rows if (n := self._row_to_note(row)) is not None]

    async def get_note(self, note_id: str, project_id: str) -> ProcessNote | None:
        result = await self.db.execute(
            f"SELECT {self._NOTE_COLUMNS} FROM NOTES "
            f"WHERE ID = '{esc(note_id)}' AND PROJECT_ID = {_pid(project_id)}"
        )
        for row in result.rows:
            return self._row_to_note(row)
        return None

    async def note_meta(self, note_id: str) -> tuple[str, bool] | None:
        """(author, is_shared) for a note by ID, or None if it doesn't exist —
        used to authorize comments/updates independently of visibility filtering."""
        result = await self.db.execute(
            f"SELECT NOTE_USER, IS_SHARED FROM NOTES WHERE ID = '{esc(note_id)}'"
        )
        for row in result.rows:
            return (row[0] if isinstance(row[0], str) else ""), as_bool(row[1])
        return None

    async def update_note(
        self,
        note_id: str,
        project_id: str,
        *,
        edited_by: str,
        comment_block: str | None = None,
        title: str | None = None,
        resolved: bool | None = None,
        importance: str | None = None,
        is_shared: bool | None = None,
    ) -> None:
        """Apply a partial update: optionally add a thread comment (prepended so the
        newest is on top), set the note's title to the latest entry's, the resolved
        flag, importance and/or shared. Callers decide which fields a given user may
        pass (owner-only for importance/isShared)."""
        sets = ["EDITED_DATE = CURRENT_TIMESTAMP", f"EDITED_BY = '{esc(edited_by)}'"]
        if comment_block:
            # Prepend so the most recent comment appears at the top of the thread.
            sets.append(f"NOTE = '{esc(comment_block)}' || NOTE")
        if title is not None:
            sets.append(f"TITLE = '{esc(title)}'")
        if resolved is not None:
            sets.append(f"RESOLVED = {'TRUE' if resolved else 'FALSE'}")
        if importance is not None:
            sets.append(f"IMPORTANCE = '{normalize_importance(importance)}'")
        if is_shared is not None:
            sets.append(f"IS_SHARED = {'TRUE' if is_shared else 'FALSE'}")
        await self.db.execute(
            f"UPDATE NOTES SET {', '.join(sets)} "
            f"WHERE ID = '{esc(note_id)}' AND PROJECT_ID = {_pid(project_id)}"
        )

    async def note_owner(self, note_id: str) -> str | None:
        """The NOTE_USER (author) of a note by its globally-unique ID, or None if
        no such note exists. Used to authorize edits/deletes independently of note
        *visibility* (shared notes are visible to all, but only the author owns them)."""
        result = await self.db.execute(
            f"SELECT NOTE_USER FROM NOTES WHERE ID = '{esc(note_id)}'"
        )
        for row in result.rows:
            return row[0] if isinstance(row[0], str) else ""
        return None

    async def upsert_note(self, note: ProcessNote, project_id: str, username: str) -> None:
        # Scope the delete-then-insert to the caller's own (or an unowned/legacy)
        # note so a crafted ID can never clobber another user's note. The endpoint
        # already 403s a non-owner edit; this is defence in depth.
        safe_user = esc(username.upper())
        await self.db.execute_quiet(
            f"DELETE FROM NOTES WHERE ID = '{esc(note.id)}' "
            f"AND (UPPER(NOTE_USER) = '{safe_user}' OR NOTE_USER = '')"
        )

        if note.target.is_node:
            target_type, target_from, target_to = "node", note.target.value or "", ""
        else:
            target_type = "edge"
            target_from = note.target.from_ or ""
            target_to = note.target.to or ""

        created_sql = f"TIMESTAMP '{_ts(note.createdAt)}'"
        edited_sql = f"TIMESTAMP '{_ts(note.editedAt)}'" if note.editedAt else "NULL"
        snapshot_json = note.filterSnapshot.model_dump_json(by_alias=True)
        importance = normalize_importance(note.importance)  # whitelist, never raw input
        await self.db.execute(
            f"""
            INSERT INTO NOTES
                (ID, PROJECT_ID, NOTES_DATE, EDITED_DATE, NOTE_USER, NOTE, IS_SHARED, EDITED_BY,
                 IMPORTANCE, RESOLVED, TITLE, TARGET_TYPE, TARGET_FROM, TARGET_TO, FILTER_SNAPSHOT)
            VALUES (
                '{esc(note.id)}', {_pid(project_id)},
                {created_sql}, {edited_sql},
                '{esc(note.username)}', '{esc(note.text)}',
                {'TRUE' if note.isShared else 'FALSE'}, '{esc(note.lastEditedBy)}',
                '{importance}', {'TRUE' if note.resolved else 'FALSE'}, '{esc(note.title)}',
                '{target_type}', '{esc(target_from)}', '{esc(target_to)}',
                '{esc(snapshot_json)}'
            )
            """
        )

    async def delete_note(self, note_id: str, project_id: str, username: str) -> None:
        # Only the note's own author may delete it — not another user (even for a
        # shared note whose ID is visible to them). In anonymous mode the author is
        # the empty string, so UPPER('') = UPPER('') still matches the caller's notes.
        safe_user = esc(username.upper())
        await self.db.execute(
            f"DELETE FROM NOTES WHERE ID = '{esc(note_id)}' "
            f"AND PROJECT_ID = {_pid(project_id)} "
            f"AND UPPER(NOTE_USER) = '{safe_user}'"
        )

    # ── sampling ─────────────────────────────────────────────────────────────

    async def ensure_sample_set_column(self) -> None:
        await self.db.execute_quiet(
            "ALTER TABLE JOURNEYS ADD COLUMN SAMPLE_SET VARCHAR(20) DEFAULT 'ORIGINAL'"
        )
        await self.db.execute_quiet(
            "UPDATE JOURNEYS SET SAMPLE_SET = 'ORIGINAL' WHERE SAMPLE_SET IS NULL"
        )

    async def load_sample_journey_counts(self, project_id: str) -> dict[str, int]:
        result = await self.db.execute(
            f"""
            SELECT SAMPLE_SET, COUNT(DISTINCT EVENT_ID) AS cnt
            FROM JOURNEYS
            WHERE PROJECT_ID = {_pid(project_id)}
            GROUP BY SAMPLE_SET
            """
        )
        counts: dict[str, int] = {}
        for row in result.rows:
            if not isinstance(row[0], str):
                continue
            try:
                key = SampleSet(row[0]).value
            except ValueError:
                continue
            counts[key] = as_int(row[1])
        return counts

    async def load_all_event_ids_for_sampling(self, project_id: str) -> list[str]:
        result = await self.db.execute(
            f"""
            SELECT DISTINCT EVENT_ID
            FROM JOURNEYS
            WHERE PROJECT_ID = {_pid(project_id)}
            AND (SAMPLE_SET = 'ORIGINAL' OR SAMPLE_SET IS NULL)
            """
        )
        return [r[0] for r in result.rows if isinstance(r[0], str)]

    async def load_event_ids_with_start_times(
        self, project_id: str
    ) -> list[tuple[str, datetime]]:
        result = await self.db.execute(
            f"""
            SELECT EVENT_ID, MIN(EVENT_TIME) AS start_time
            FROM JOURNEYS
            WHERE PROJECT_ID = {_pid(project_id)}
            AND (SAMPLE_SET = 'ORIGINAL' OR SAMPLE_SET IS NULL)
            GROUP BY EVENT_ID
            """
        )
        pairs: list[tuple[str, datetime]] = []
        for row in result.rows:
            when = parse_date(row[1])
            if isinstance(row[0], str) and when is not None:
                pairs.append((row[0], when))
        return pairs

    async def load_event_ids_with_paths(self, project_id: str) -> list[tuple[str, str]]:
        result = await self.db.execute(
            f"""
            SELECT EVENT_ID,
                   LISTAGG(STEP, '->') WITHIN GROUP (ORDER BY EVENT_TIME, STEP_ID) AS journey_path
            FROM JOURNEYS
            WHERE PROJECT_ID = {_pid(project_id)}
            AND (SAMPLE_SET = 'ORIGINAL' OR SAMPLE_SET IS NULL)
            GROUP BY EVENT_ID
            """
        )
        return [
            (r[0], r[1]) for r in result.rows if isinstance(r[0], str) and isinstance(r[1], str)
        ]

    async def insert_sample_journeys(
        self, project_id: str, event_ids: list[str], sample_set: SampleSet
    ) -> None:
        if not event_ids or sample_set.is_original:
            return
        safe_pid = _pid(project_id)
        batch_size = 200
        for start in range(0, len(event_ids), batch_size):
            batch = event_ids[start : start + batch_size]
            in_list = ", ".join(f"'{esc(e)}'" for e in batch)
            await self.db.execute(
                f"""
                INSERT INTO JOURNEYS
                    (PROJECT_ID, EVENT_ID, STEP, STEP_ID, EVENT_TIME, META_1, META_2, META_3, SAMPLE_SET)
                SELECT PROJECT_ID, EVENT_ID, STEP, STEP_ID, EVENT_TIME, META_1, META_2, META_3, '{sample_set.value}'
                FROM JOURNEYS
                WHERE PROJECT_ID = {safe_pid}
                AND (SAMPLE_SET = 'ORIGINAL' OR SAMPLE_SET IS NULL)
                AND EVENT_ID IN ({in_list})
                """
            )

    async def delete_sample(self, project_id: str, sample_set: SampleSet) -> None:
        if sample_set.is_original:
            return
        await self.db.execute(
            f"""
            DELETE FROM JOURNEYS
            WHERE PROJECT_ID = {_pid(project_id)}
            AND SAMPLE_SET = '{sample_set.value}'
            """
        )
