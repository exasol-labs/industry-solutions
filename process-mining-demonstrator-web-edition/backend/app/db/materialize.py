"""Materialise an aggregate: copy a project into new high-level + detail projects.

Given a source project and a set of **member** step names, this builds two new
projects on a chosen (possibly new) schema/connection:

* **high-level** — a full copy of the source where each journey's maximal *run* of
  member steps is collapsed into a single ``Σ`` event (keeping the run's first entry
  time). The normal DFG engine then computes the Σ node's black-box metrics for free:
  internal transitions vanish, and incoming/outgoing edges connect the Σ node to the
  rest of the map.
* **detail** — only the member steps' events, so the sub-process can be opened
  standalone and drilled into.

The copy is read-then-reinsert (rows are read from the source into memory, then
inserted into the destination), so it works uniformly whether the target is the same
schema, a new schema, or a different connection/database.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from .demo_data import _sq

# JOURNEYS columns we populate (SAMPLE_SET keeps its 'ORIGINAL' default).
_JOURNEY_COLUMNS = [
    "PROJECT_ID", "EVENT_ID", "STEP", "STEP_ID", "EVENT_TIME", "META_1", "META_2", "META_3",
]
# EVENT_TIME is read pre-formatted as 'YYYY-MM-DD HH24:MI:SS'; the bulk IMPORT parses
# it against this session timestamp format.
_TS_FORMAT = "YYYY-MM-DD HH24:MI:SS"
# Fallback batch size for INSERT … VALUES (used only if HTTP-transport IMPORT fails).
_BATCH = 2000


@dataclass
class SourceEvent:
    event_id: str
    step: str
    step_id: int | None
    event_time: str  # 'YYYY-MM-DD HH:MM:SS' (already formatted on read)
    meta1: str | None
    meta2: str | None
    meta3: str | None


@dataclass
class StepRow:
    step: str
    description: str
    bg_color: str
    fg_color: str
    score: int | None
    shape: str
    end_of_process: bool
    belongs_to: str
    step_id: int | None = None  # stable activity id (matches JOURNEYS.STEP_ID)


# ── pure transforms (unit-testable, no DB) ────────────────────────────────────


@dataclass(frozen=True)
class AggGroup:
    """One aggregate: the set of member steps and the Σ super-step they collapse into."""

    members: frozenset[str]
    sigma: str


def collapse_high_level_multi(
    events: list[SourceEvent], groups: list[AggGroup],
    sigma_ids: dict[str, int] | None = None,
) -> list[SourceEvent]:
    """Collapse SEVERAL aggregates at once into one high-level event stream.

    Each journey's maximal consecutive run of steps belonging to the *same* aggregate is
    folded into one Σ event for that aggregate; the run breaks when the owning aggregate
    changes (to a different aggregate, or to a non-member step). Member sets across groups
    must be disjoint. Assumes ``events`` ordered by (event_id, event_time, step_id).

    ``sigma_ids`` maps each Σ name to its own activity id, stamped on the collapsed Σ
    event (NOT a member's id) so the high-level transition query groups the Σ correctly."""
    owner: dict[str, str] = {}
    for g in groups:
        for m in g.members:
            owner[m] = g.sigma
    sids = sigma_ids or {}
    out: list[SourceEvent] = []
    last_eid: str | None = None
    cur_sigma: str | None = None  # the Σ of the run in progress, or None outside any run
    for e in events:
        if e.event_id != last_eid:
            last_eid = e.event_id
            cur_sigma = None
        sig = owner.get(e.step)
        if sig is not None:
            if cur_sigma == sig:
                continue  # same aggregate run — folded into the Σ event already emitted
            cur_sigma = sig
            out.append(
                SourceEvent(e.event_id, sig, sids.get(sig), e.event_time, e.meta1, e.meta2, e.meta3)
            )
        else:
            cur_sigma = None
            out.append(e)
    return out


def collapse_high_level(
    events: list[SourceEvent], members: set[str], sigma: str
) -> list[SourceEvent]:
    """Single-aggregate collapse (see :func:`collapse_high_level_multi`)."""
    return collapse_high_level_multi(events, [AggGroup(frozenset(members), sigma)])


def filter_detail(events: list[SourceEvent], members: set[str]) -> list[SourceEvent]:
    """Only the member steps' events — the partial sub-process."""
    return [e for e in events if e.step in members]


def sigma_step_row(
    sigma: str, members: set[str], steps: list[StepRow], step_id: int | None = None
) -> StepRow:
    """A synthetic STEPS row for the Σ super-step; score = sum of member scores.

    The Σ step inherits the members' BELONGS_TO group when they all share one (ignoring
    members without a group), so the super-step stays inside the same swimlane/grouping
    on the high-level map. If the members span more than one group, it gets none."""
    total = sum((s.score or 0) for s in steps if s.step in members)
    groups = {(s.belongs_to or "").strip() for s in steps if s.step in members}
    groups.discard("")
    belongs_to = next(iter(groups)) if len(groups) == 1 else ""
    return StepRow(
        step=sigma,
        description=f"Aggregate of {len(members)} steps.",
        bg_color="#5b6bff",
        fg_color="#ffffff",
        score=total or None,
        shape="rectangle",
        end_of_process=False,
        belongs_to=belongs_to,
        step_id=step_id,
    )


# ── SQL helpers ───────────────────────────────────────────────────────────────


def _steps_insert_sqls(project_id: str, steps: list[StepRow]) -> list[str]:
    out: list[str] = []
    for s in steps:
        eop = "TRUE" if s.end_of_process else "FALSE"
        score = "NULL" if s.score is None else str(int(s.score))
        sid = "NULL" if s.step_id is None else str(int(s.step_id))
        out.append(
            "INSERT INTO STEPS (PROJECT_ID, STEP, STEP_ID, DESCRIPTION, BG_COLOR, FG_COLOR, SCORE, "
            "SHAPE, END_OF_PROCESS, BELONGS_TO) VALUES "
            f"({int(project_id)}, '{_sq(s.step)}', {sid}, '{_sq(s.description or '')}', "
            f"'{_sq(s.bg_color or '')}', '{_sq(s.fg_color or '')}', {score}, "
            f"'{_sq(s.shape or 'rectangle')}', {eop}, '{_sq(s.belongs_to or '')}')"
        )
    return out


def _journey_rows(project_id: str, events: list[SourceEvent]):
    """Yield JOURNEYS rows (in _JOURNEY_COLUMNS order) for the bulk IMPORT."""
    pid = int(project_id)  # PROJECT_ID is a SMALLINT
    for e in events:
        yield (pid, e.event_id, e.step, e.step_id, e.event_time, e.meta1, e.meta2, e.meta3)


def _lit(value: str | None) -> str:
    return "NULL" if value is None else f"'{_sq(str(value))}'"


def _journeys_insert_values(project_id: str, rows: list[SourceEvent]) -> str:
    """A batched INSERT … VALUES for JOURNEYS — the slow fallback when HTTP IMPORT is
    unavailable (e.g. the Exasol cluster cannot open a data channel to this host)."""
    vals = ",\n  ".join(
        f"({int(project_id)}, '{_sq(r.event_id)}', '{_sq(r.step)}', "
        f"{'NULL' if r.step_id is None else int(r.step_id)}, "
        f"TIMESTAMP '{r.event_time}', "
        f"{_lit(r.meta1)}, {_lit(r.meta2)}, {_lit(r.meta3)})"
        for r in rows
    )
    return (
        "INSERT INTO JOURNEYS (PROJECT_ID, EVENT_ID, STEP, STEP_ID, EVENT_TIME, "
        f"META_1, META_2, META_3) VALUES\n  {vals}"
    )


# ── read the source ───────────────────────────────────────────────────────────


def _read_source(run_sql, schema: str, project_id: str) -> tuple[list[SourceEvent], list[StepRow], tuple[str, str, str]]:
    from .schema_ddl import _quote_ident

    run_sql(f"OPEN SCHEMA {_quote_ident(schema)}")
    ev_rows = run_sql(
        "SELECT EVENT_ID, STEP, STEP_ID, "
        "TO_CHAR(EVENT_TIME, 'YYYY-MM-DD HH24:MI:SS'), META_1, META_2, META_3 "
        f"FROM JOURNEYS WHERE PROJECT_ID = {int(project_id)} "
        "AND (SAMPLE_SET = 'ORIGINAL' OR SAMPLE_SET IS NULL) "
        "ORDER BY EVENT_ID, EVENT_TIME, STEP_ID"
    )
    events = [
        SourceEvent(str(r[0]), str(r[1]), None if r[2] is None else int(r[2]),
                    str(r[3]), r[4], r[5], r[6])
        for r in ev_rows
    ]
    st_rows = run_sql(
        "SELECT STEP, DESCRIPTION, BG_COLOR, FG_COLOR, SCORE, SHAPE, END_OF_PROCESS, BELONGS_TO, STEP_ID "
        f"FROM STEPS WHERE PROJECT_ID = {int(project_id)}"
    )
    steps = [
        StepRow(str(r[0]), r[1] or "", r[2] or "", r[3] or "",
                None if r[4] is None else int(r[4]), r[5] or "rectangle",
                bool(r[6]), r[7] or "", None if r[8] is None else int(r[8]))
        for r in st_rows
    ]
    meta_rows = run_sql(
        "SELECT META_1_TITLE, META_2_TITLE, META_3_TITLE "
        f"FROM METAS WHERE PROJECT_ID = {int(project_id)}"
    )
    titles = (
        (str(meta_rows[0][0] or ""), str(meta_rows[0][1] or ""), str(meta_rows[0][2] or ""))
        if meta_rows
        else ("", "", "")
    )
    return events, steps, titles


# ── write a destination project ───────────────────────────────────────────────


def _write_project(
    raw,
    run_sql,
    *,
    schema: str,
    provision: bool,
    project_id: str,
    title: str,
    title_short: str,
    description: str,
    meta_titles: tuple[str, str, str],
    steps: list[StepRow],
    events: list[SourceEvent],
) -> None:
    from .schema_ddl import PROCESS_MINING_TABLES, _quote_ident

    ident = _quote_ident(schema)
    if provision:
        run_sql(f"CREATE SCHEMA IF NOT EXISTS {ident}")
    run_sql(f"OPEN SCHEMA {ident}")
    if provision:
        for _name, ddl in PROCESS_MINING_TABLES:
            run_sql(ddl)

    # Replace any pre-existing rows for this fresh project id (idempotent re-run).
    for table in ("JOURNEYS", "STEPS", "METAS", "PROJECTS"):
        run_sql(f"DELETE FROM {table} WHERE PROJECT_ID = {int(project_id)}")

    run_sql(
        "INSERT INTO PROJECTS (PROJECT_ID, TITLE, DESCRIPTION, TITLE_SHORT) VALUES "
        f"({int(project_id)}, '{_sq(title)}', '{_sq(description)}', '{_sq(title_short)}')"
    )
    run_sql(
        "INSERT INTO METAS (PROJECT_ID, META_1_TITLE, META_2_TITLE, META_3_TITLE) VALUES "
        f"({int(project_id)}, '{_sq(meta_titles[0])}', '{_sq(meta_titles[1])}', "
        f"'{_sq(meta_titles[2])}')"
    )
    for sql in _steps_insert_sqls(project_id, steps):
        run_sql(sql)

    # Bulk-load JOURNEYS — the large table — via Exasol's parallel HTTP IMPORT instead of
    # thousands of INSERT … VALUES round trips. One statement, one commit; pyexasol
    # CSV-encodes the rows (correct quoting for commas/quotes/newlines for free). If the
    # HTTP transport is unavailable (the cluster can't reach this host), a failed IMPORT
    # rolls back cleanly, so we fall back to batched INSERTs — slower but always works.
    if events:
        run_sql(f"ALTER SESSION SET NLS_TIMESTAMP_FORMAT = '{_TS_FORMAT}'")
        try:
            raw.import_from_iterable(
                _journey_rows(project_id, events),
                (schema, "JOURNEYS"),
                import_params={"columns": _JOURNEY_COLUMNS},
            )
        except Exception:  # noqa: BLE001 — any transport failure falls back to VALUES
            run_sql(f"DELETE FROM JOURNEYS WHERE PROJECT_ID = {int(project_id)}")  # clear a partial IMPORT
            for offset in range(0, len(events), _BATCH):
                run_sql(_journeys_insert_values(project_id, events[offset : offset + _BATCH]))


@dataclass
class Target:
    connection: object  # a Connection with secrets
    schema: str
    provision: bool  # create the schema + tables first
    project_id: str  # an allocated SMALLINT (int, or numeric string)
    title: str
    title_short: str = ""  # human code; 'Σ…' high-level, '#…' detail (drives sidebar hiding)


def _open_conn(conn):
    """Open a stored connection with **autocommit ON** and return ``(raw, run_sql)``.

    Autocommit must stay ON: the destination writes run ``CREATE SCHEMA`` / ``CREATE
    TABLE`` DDL, and on Exasol DDL held inside a never-committed transaction blocks
    forever ("waiting for commit of transaction …") against any concurrent session.
    This mirrors the proven demo-provisioning path (``generate_demo_content``), which
    also opens with the driver's default autocommit and issues one commit at the end.
    """
    from ..db.manager import DatabaseManager
    from ..models import DatabaseServer

    server = DatabaseServer(
        id="aggregate", host=conn.host, port=conn.port, username=conn.username,
        useTLS=conn.use_tls, certModeRaw=conn.cert_mode, fingerprint=conn.fingerprint,
        minRSAKeySizeBits=conn.min_rsa_bits, **{"schema": conn.schema or ""},
    )
    mgr = DatabaseManager.__new__(DatabaseManager)  # no store side effects
    raw = mgr._open(server, conn.password)  # default autocommit (ON)

    def run_sql(sql: str):
        st = raw.execute(sql)
        return [list(r) for r in st.fetchall()] if st.result_type == "resultSet" else []

    return raw, run_sql


def _write_target(tgt: "Target", steps, events, meta_titles) -> None:
    raw, run = _open_conn(tgt.connection)
    try:
        _write_project(
            raw, run,
            schema=tgt.schema, provision=tgt.provision, project_id=tgt.project_id,
            title=tgt.title, title_short=tgt.title_short, description="",
            meta_titles=meta_titles, steps=steps, events=events,
        )
        raw.commit()
    finally:
        raw.close()


async def materialize_aggregate_set(
    *,
    source_connection: object,
    source_project_id: str,
    groups: list[AggGroup],
    high_level: Target,
    details: list[tuple[Target, frozenset[str]]],
) -> dict:
    """Read the source project once, then write ONE high-level project collapsing ALL
    ``groups`` (a Σ super-step per group) plus a member-only detail project for each entry
    in ``details`` (each to its own target). ``groups`` is the full set — pass every group
    so the high-level map stays consistent; ``details`` is only the projects to (re)write
    now (so 'add another aggregate later' re-writes the map but only the new detail)."""

    def _run() -> None:
        src_raw, src_run = _open_conn(source_connection)
        try:
            events, steps, meta_titles = _read_source(
                src_run, source_connection.schema or "", source_project_id
            )
        finally:
            src_raw.close()

        all_members: set[str] = set().union(*[set(g.members) for g in groups]) if groups else set()
        # Give each Σ super-step its own activity id above the source ids, and stamp it
        # on both the collapsed Σ events and the synthetic Σ STEPS row so the high-level
        # transition query groups the Σ node on a real, unique id.
        max_id = max((s.step_id or 0 for s in steps), default=0)
        sigma_ids = {g.sigma: max_id + i + 1 for i, g in enumerate(groups)}
        hi_events = collapse_high_level_multi(events, groups, sigma_ids)
        hi_steps = [s for s in steps if s.step not in all_members]
        hi_steps.extend(
            sigma_step_row(g.sigma, set(g.members), steps, sigma_ids[g.sigma]) for g in groups
        )
        _write_target(high_level, hi_steps, hi_events, meta_titles)

        for tgt, members in details:
            det_events = filter_detail(events, members)
            det_steps = [s for s in steps if s.step in members]
            _write_target(tgt, det_steps, det_events, meta_titles)

    await asyncio.to_thread(_run)
    return {
        "highLevelProjectId": high_level.project_id,
        "detailProjectIds": [t.project_id for t, _ in details],
    }


async def materialize_aggregate(
    *,
    source_connection: object,
    source_project_id: str,
    members: set[str],
    sigma: str,
    high_level: Target,
    detail: Target,
) -> dict:
    """Single-aggregate convenience wrapper over :func:`materialize_aggregate_set`."""
    result = await materialize_aggregate_set(
        source_connection=source_connection,
        source_project_id=source_project_id,
        groups=[AggGroup(frozenset(members), sigma)],
        high_level=high_level,
        details=[(detail, frozenset(members))],
    )
    return {
        "highLevelProjectId": result["highLevelProjectId"],
        "detailProjectId": detail.project_id,
    }
