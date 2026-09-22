"""Repository helper tests — the pure SQL-building and coercion logic that runs
without a database connection.

The clause builders in ProcessRepository are exercised through a stub manager;
no query is ever sent. This mirrors how the Swift app's SQL fragments were
implicitly validated by the queries that consumed them.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from app.models import FilterSpec, SampleSet
from app.db.repository import (
    ProcessRepository,
    as_bool,
    as_float,
    as_int,
    dur_label,
    esc,
    parse_date,
)


class _StubManager:
    """Stands in for DatabaseManager — the clause builders never call it."""

    is_connected = False


def repo(sample_set: SampleSet = SampleSet.original) -> ProcessRepository:
    r = ProcessRepository(_StubManager())  # type: ignore[arg-type]
    r.active_sample_set = sample_set
    return r


# ── Coercion helpers ──────────────────────────────────────────────────────────


def test_esc_doubles_single_quotes():
    assert esc("O'Brien") == "O''Brien"
    assert esc("plain") == "plain"


def test_as_int_handles_driver_types():
    assert as_int(5) == 5
    assert as_int(5.9) == 5
    assert as_int(Decimal("7")) == 7
    assert as_int("12") == 12
    assert as_int(None, default=3) == 3
    assert as_int("nonsense", default=1) == 1


def test_as_float_handles_driver_types():
    assert as_float(1) == 1.0
    assert as_float(Decimal("2.5")) == 2.5
    assert as_float("3.25") == 3.25
    assert as_float(None) is None
    assert as_float("nope") is None


def test_as_bool_handles_driver_types():
    assert as_bool(True) is True
    assert as_bool(1) is True
    assert as_bool(0) is False
    assert as_bool("TRUE") is True
    assert as_bool("f") is False
    assert as_bool(None) is False


def test_parse_date_accepts_multiple_formats():
    assert parse_date("2024-01-02 03:04:05") == datetime(2024, 1, 2, 3, 4, 5)
    assert parse_date("2024-01-02") == datetime(2024, 1, 2)
    assert parse_date(datetime(2024, 1, 2)) == datetime(2024, 1, 2)
    assert parse_date(date(2024, 1, 2)) == datetime(2024, 1, 2)
    assert parse_date(None) is None
    assert parse_date("not a date") is None


def test_dur_label_scales_units():
    # Below 10 units the Swift label keeps one decimal; at/above 10 it rounds.
    assert dur_label(30) == "30s"
    assert dur_label(300) == "5.0m"
    assert dur_label(900) == "15m"
    assert dur_label(7200) == "2.0h"
    assert dur_label(172800) == "2.0d"


# ── Clause builders ───────────────────────────────────────────────────────────


def test_sample_clause_uses_active_set():
    assert "SAMPLE_SET = 'ORIGINAL' OR SAMPLE_SET IS NULL" in repo()._sample_clause()
    assert "SAMPLE_SET = 'SAMPLE_1'" in repo(SampleSet.sample1)._sample_clause()


def test_date_clause_bounds():
    clause = repo()._date_clause(datetime(2024, 1, 1), datetime(2024, 1, 31))
    assert "EVENT_TIME >= TIMESTAMP '2024-01-01 00:00:00'" in clause
    assert "EVENT_TIME <= TIMESTAMP '2024-01-31 23:59:59'" in clause
    assert repo()._date_clause(None, None) == ""


def test_journey_qualifier_folds_all_filters_into_one_semijoin():
    f = FilterSpec(
        fromDate=datetime(2024, 1, 1),
        toDate=datetime(2024, 1, 31),
        includedSteps=["Login"],
        excludedSteps=["Return"],
        minSteps=2,
        maxSteps=10,
        minJourneyTime=60,
        maxScore=100,
    )
    # Transition path folds date + meta in as an active-window match.
    sql = repo()._journey_qualifier(7, f, include_date_meta=True)
    # The whole filter set is ONE semi-join / ONE scan (was up to six).
    assert sql.count("EVENT_ID IN") == 1
    assert sql.count("SELECT") == 1
    # A score bound pulls in the STEPS join and qualifies journey columns with j.
    assert "LEFT JOIN STEPS s" in sql
    assert "SUM(COALESCE(s.SCORE, 0)) BETWEEN" in sql
    assert "MAX(CASE WHEN j.STEP IN ('Login') THEN 1 ELSE 0 END) = 1" in sql
    assert "MAX(CASE WHEN j.STEP IN ('Return') THEN 1 ELSE 0 END) = 0" in sql
    assert "COUNT(*) BETWEEN 2 AND 10" in sql
    assert "SECONDS_BETWEEN(MAX(j.EVENT_TIME), MIN(j.EVENT_TIME)) >= 60" in sql
    assert "j.EVENT_TIME >= TIMESTAMP '2024-01-01 00:00:00'" in sql
    assert "j.EVENT_TIME <= TIMESTAMP '2024-01-31 23:59:59'" in sql


def test_journey_qualifier_folds_meta_value_include_exclude():
    # The node "Meta Infos" panel adds list-based META include/exclude, journey-level
    # like steps: kept when the journey has ≥1 event with an included META value and none
    # with an excluded one, per column.
    f = FilterSpec(
        includedMeta1=["Visa", "SEPA"],
        excludedMeta2=["Bank"],
        includedMeta3=["alice"],
    )
    sql = repo()._journey_qualifier(7, f, include_date_meta=False)
    assert "MAX(CASE WHEN META_1 IN ('Visa', 'SEPA') THEN 1 ELSE 0 END) = 1" in sql
    assert "MAX(CASE WHEN META_2 IN ('Bank') THEN 1 ELSE 0 END) = 0" in sql
    assert "MAX(CASE WHEN META_3 IN ('alice') THEN 1 ELSE 0 END) = 1" in sql
    assert sql.count("EVENT_ID IN") == 1  # still one semi-join
    # Values are escaped like everything else.
    esc = FilterSpec(includedMeta1=["O'Neil"])
    assert "'O''Neil'" in repo()._journey_qualifier(7, esc, include_date_meta=False)


def test_load_node_meta_values_scopes_to_the_step():
    import asyncio
    import types

    captured: dict[str, str] = {}

    class _Cap:
        async def execute(self, sql: str):
            captured["sql"] = sql
            return types.SimpleNamespace(rows=[
                ("META_1", "Visa", "2026-09-17 13:54:02", 3),
                ("META_1", "SEPA", "2026-09-16 09:10:00", 1),
                ("META_2", "Retail", "2026-09-17 13:54:02", 4),
            ])

    r = repo()
    r.db = _Cap()  # type: ignore[assignment]
    out = asyncio.run(r.load_node_meta_values(7, "Check'out"))
    # Scoped to the node's step (escaped), grouped by column, with the last-seen time+count.
    assert "STEP = 'Check''out'" in captured["sql"]
    assert "MAX(EVENT_TIME)" in captured["sql"]
    assert out["META_1"] == [
        {"value": "Visa", "time": "2026-09-17 13:54:02", "count": 3},
        {"value": "SEPA", "time": "2026-09-16 09:10:00", "count": 1},
    ]
    assert out["META_2"] == [{"value": "Retail", "time": "2026-09-17 13:54:02", "count": 4}]
    assert out["META_3"] == []


def test_journey_qualifier_without_score_needs_no_join():
    f = FilterSpec(includedSteps=["Login"], minSteps=3)
    sql = repo()._journey_qualifier(7, f, include_date_meta=False)
    assert "LEFT JOIN STEPS" not in sql  # no score bound → no join, no alias
    assert "MAX(CASE WHEN STEP IN ('Login') THEN 1 ELSE 0 END) = 1" in sql
    assert "COUNT(*) >= 3" in sql
    assert sql.count("EVENT_ID IN") == 1


def test_journey_qualifier_is_empty_without_journey_filters():
    # No step/count/time/score filters → the qualifier contributes nothing
    # (date/meta are handled row-level in date_only mode).
    assert repo()._journey_qualifier(7, FilterSpec(), include_date_meta=False) == ""
    assert repo()._journey_qualifier(7, FilterSpec(), include_date_meta=True) == ""


def test_journey_qualifier_escapes_values():
    f = FilterSpec(includedSteps=["O'Neil"], meta1="A'B")
    sql = repo()._journey_qualifier(7, f, include_date_meta=True)
    assert "'O''Neil'" in sql
    assert "A''B" in sql


def test_all_filters_transition_mode_uses_a_single_semijoin():
    f = FilterSpec(
        fromDate=datetime(2024, 1, 1),
        toDate=datetime(2024, 1, 31),
        includedSteps=["Login"],
        minSteps=2,
        minScore=-5,
        maxScore=20,
    )
    sql = repo()._all_filters(7, f, date_only=False)
    # Previously one subquery per active filter; now consolidated to one.
    assert sql.count("EVENT_ID IN") == 1
    assert "SAMPLE_SET" in sql


def test_all_filters_combines_clauses():
    f = FilterSpec(
        fromDate=datetime(2024, 1, 1),
        toDate=datetime(2024, 1, 31),
        includedSteps=["Login"],
        minSteps=2,
        maxScore=100,
    )
    sql = repo()._all_filters(7, f, date_only=True)
    assert "SAMPLE_SET" in sql
    assert "EVENT_TIME >= TIMESTAMP '2024-01-01 00:00:00'" in sql
    assert "STEP IN ('Login')" in sql
    assert "COUNT(*) >= 2" in sql


# ── Note authorization scoping (security: cross-user write/delete) ─────────────


class _CapturingManager:
    """Captures the SQL the repository would run, and can return canned rows."""

    is_connected = True

    def __init__(self, rows=()):
        self.executed: list[str] = []
        self._rows = list(rows)
        self._steps_cache: dict = {}  # mirrors DatabaseManager for the STEPS cache

    def invalidate_steps(self, project_id=None):
        if project_id is None:
            self._steps_cache.clear()
        else:
            self._steps_cache.pop(project_id, None)

    async def execute(self, sql, *a, **k):
        self.executed.append(sql)
        return type("R", (), {"rows": self._rows})()

    async def execute_quiet(self, sql, *a, **k):
        self.executed.append(sql)


def _cap_repo(rows=()):
    r = ProcessRepository(_CapturingManager(rows))  # type: ignore[arg-type]
    return r, r.db  # type: ignore[return-value]


import asyncio

from app.models import NoteTarget, ProcessNote, FilterSnapshot


def test_delete_note_is_scoped_to_owner():
    r, mgr = _cap_repo()
    asyncio.run(r.delete_note("n-1", 7, "Alice"))
    sql = mgr.executed[-1]
    # Only the author may delete — owner-only, no unowned/other-user fallback.
    assert "DELETE FROM NOTES" in sql
    assert "ID = 'n-1'" in sql
    assert "UPPER(NOTE_USER) = 'ALICE'" in sql
    assert "OR NOTE_USER = ''" not in sql


def test_upsert_note_predelete_is_scoped_to_owner():
    r, mgr = _cap_repo()
    note = ProcessNote(
        id="n-2",
        text="hi",
        createdAt=datetime(2026, 1, 1),
        target=NoteTarget(type="node", value="A"),
        filterSnapshot=FilterSnapshot(fromDate=datetime(2026, 1, 1), toDate=datetime(2026, 1, 2)),
        username="Bob",
    )
    asyncio.run(r.upsert_note(note, 7, "Bob"))
    predelete = mgr.executed[0]
    assert predelete.startswith("DELETE FROM NOTES") or "DELETE FROM NOTES" in predelete
    assert "ID = 'n-2'" in predelete
    assert "UPPER(NOTE_USER) = 'BOB'" in predelete  # can't clobber another user's ID


def test_upsert_note_whitelists_importance():
    r, mgr = _cap_repo()
    note = ProcessNote(
        id="n-8",
        text="hi",
        createdAt=datetime(2026, 1, 1),
        target=NoteTarget(type="node", value="A"),
        filterSnapshot=FilterSnapshot(fromDate=datetime(2026, 1, 1), toDate=datetime(2026, 1, 2)),
        username="Bob",
        importance="URGENT",
    )
    asyncio.run(r.upsert_note(note, 7, "Bob"))
    insert = mgr.executed[-1]
    assert "IMPORTANCE" in insert and "'URGENT'" in insert

    # A bogus importance (or an injection attempt) is coerced to NORMAL.
    note.importance = "evil'; DROP TABLE NOTES; --"
    asyncio.run(r.upsert_note(note, 7, "Bob"))
    assert "'NORMAL'" in mgr.executed[-1]
    assert "DROP TABLE" not in mgr.executed[-1]


def test_note_owner_returns_author_or_none():
    r, _ = _cap_repo(rows=[["Carol"]])
    assert asyncio.run(r.note_owner("n-3")) == "Carol"
    r2, _ = _cap_repo(rows=[])
    assert asyncio.run(r2.note_owner("missing")) is None


# ── Note update: comment append + resolved; owner-only reclassification ────────


def test_update_note_builds_partial_update_sql():
    r, mgr = _cap_repo()
    asyncio.run(
        r.update_note(
            "n-9",
            7,
            edited_by="Bob",
            comment_block="—— Bob · 2026-07-25 ——\nlooks fixed\n\n",
            resolved=True,
            importance="URGENT",
            is_shared=True,
        )
    )
    sql = mgr.executed[-1]
    assert sql.startswith("UPDATE NOTES SET")
    assert "|| NOTE" in sql and "looks fixed" in sql  # prepended (newest on top)
    assert "RESOLVED = TRUE" in sql
    assert "IMPORTANCE = 'URGENT'" in sql
    assert "IS_SHARED = TRUE" in sql
    assert "EDITED_BY = 'Bob'" in sql
    assert "ID = 'n-9'" in sql and "PROJECT_ID = 7" in sql


def test_update_note_omits_untouched_fields():
    r, mgr = _cap_repo()
    asyncio.run(r.update_note("n-9", 7, edited_by="Bob", resolved=False))
    sql = mgr.executed[-1]
    assert "RESOLVED = FALSE" in sql
    assert "|| NOTE" not in sql  # no comment prepended
    assert "IMPORTANCE" not in sql and "IS_SHARED" not in sql


def test_note_meta_returns_owner_and_shared():
    r, _ = _cap_repo(rows=[["alice", True]])
    assert asyncio.run(r.note_meta("n-1")) == ("alice", True)
    r2, _ = _cap_repo(rows=[])
    assert asyncio.run(r2.note_meta("missing")) is None


# ── update_note endpoint: per-field authorization ─────────────────────────────


class _EndpointRepo:
    def __init__(self, meta):
        self._meta = meta
        self.update_kwargs = None

    async def ensure_notes_table(self):
        pass

    async def note_meta(self, note_id):
        return self._meta

    async def update_note(self, note_id, project_id, **kw):
        self.update_kwargs = kw

    async def get_note(self, note_id, project_id):
        return ProcessNote(
            id=note_id,
            text="hi",
            createdAt=datetime(2026, 1, 1),
            target=NoteTarget(type="node", value="A"),
            filterSnapshot=FilterSnapshot(
                fromDate=datetime(2026, 1, 1), toDate=datetime(2026, 1, 2)
            ),
            username=self._meta[0] if self._meta else "",
        )


def _run_update(monkeypatch, *, caller, meta, body):
    from app.api import features

    repo = _EndpointRepo(meta)
    monkeypatch.setattr(features, "require_connection", lambda: None)
    monkeypatch.setattr(features, "repo", lambda: repo)
    monkeypatch.setattr(features, "current_user", lambda: caller)
    monkeypatch.setattr(features, "_note_display_name", lambda u: u)
    result = asyncio.run(features.update_note(7, "n1", body))
    return repo, result


def test_endpoint_owner_can_reclassify(monkeypatch):
    from app.api.features import NoteUpdateBody

    repo, _ = _run_update(
        monkeypatch,
        caller="alice",
        meta=("alice", False),
        body=NoteUpdateBody(comment="more", resolved=True, importance="URGENT", isShared=True),
    )
    assert "more" in repo.update_kwargs["comment_block"]
    assert repo.update_kwargs["resolved"] is True
    assert repo.update_kwargs["importance"] == "URGENT"
    assert repo.update_kwargs["is_shared"] is True


def test_endpoint_non_owner_can_comment_but_not_reclassify(monkeypatch):
    from app.api.features import NoteUpdateBody

    repo, _ = _run_update(
        monkeypatch,
        caller="bob",
        meta=("alice", True),  # alice's shared note → bob may comment + resolve
        body=NoteUpdateBody(comment="fixed", resolved=True, importance="URGENT", isShared=False),
    )
    assert "fixed" in repo.update_kwargs["comment_block"]
    assert repo.update_kwargs["resolved"] is True
    assert repo.update_kwargs["importance"] is None  # ignored for non-owner
    assert repo.update_kwargs["is_shared"] is None


def test_endpoint_non_owner_private_note_is_403(monkeypatch):
    from fastapi import HTTPException

    from app.api.features import NoteUpdateBody

    with __import__("pytest").raises(HTTPException) as ei:
        _run_update(
            monkeypatch,
            caller="bob",
            meta=("alice", False),  # not shared → bob can't even see it
            body=NoteUpdateBody(comment="peek"),
        )
    assert ei.value.status_code == 403


def test_endpoint_missing_note_is_404(monkeypatch):
    from fastapi import HTTPException

    from app.api.features import NoteUpdateBody

    with __import__("pytest").raises(HTTPException) as ei:
        _run_update(monkeypatch, caller="bob", meta=None, body=NoteUpdateBody(comment="x"))
    assert ei.value.status_code == 404


# ── Security hardening (6th review): comment cap, create-only PUT, fail-closed ──


def test_note_comment_length_is_capped():
    from pydantic import ValidationError

    from app.api.features import NoteUpdateBody

    NoteUpdateBody(comment="x" * 4000)  # at the limit — accepted
    with __import__("pytest").raises(ValidationError):
        NoteUpdateBody(comment="x" * 4001)  # over the limit — rejected


def test_load_notes_is_fail_closed_for_empty_user():
    r, mgr = _cap_repo(rows=[])
    asyncio.run(r.load_notes(7, ""))
    sql = mgr.executed[-1]
    # An unknown/empty user still only sees unowned or shared notes — never all.
    assert "IS_SHARED = TRUE" in sql
    assert "NOTE_USER = ''" in sql


def _run_save(monkeypatch, *, caller, existing_owner):
    from app.api import features

    class _Repo:
        def __init__(self):
            self.upserted = False

        async def ensure_notes_table(self):
            pass

        async def note_owner(self, note_id):
            return existing_owner  # None ⇒ brand-new note

        async def upsert_note(self, note, project_id, author):
            self.upserted = True

    repo = _Repo()
    monkeypatch.setattr(features, "require_connection", lambda: None)
    monkeypatch.setattr(features, "repo", lambda: repo)
    monkeypatch.setattr(features, "current_user", lambda: caller)
    monkeypatch.setattr(features, "_note_display_name", lambda u: u)
    note = ProcessNote(
        id="n1",
        text="hi",
        createdAt=datetime(2026, 1, 1),
        target=NoteTarget(type="node", value="A"),
        filterSnapshot=FilterSnapshot(fromDate=datetime(2026, 1, 1), toDate=datetime(2026, 1, 2)),
    )
    return repo, asyncio.run(features.save_note(7, note))


def test_save_note_creates_a_new_note(monkeypatch):
    repo, result = _run_save(monkeypatch, caller="alice", existing_owner=None)
    assert repo.upserted is True
    assert result.username == "alice"


def test_save_note_rejects_existing_note_id(monkeypatch):
    from fastapi import HTTPException

    # PUT on an existing note is refused (409) so it can't overwrite the thread —
    # edits go through the append-only update endpoint instead.
    with __import__("pytest").raises(HTTPException) as ei:
        _run_save(monkeypatch, caller="bob", existing_owner="alice")
    assert ei.value.status_code == 409


# ── Note titles (subject shown separately in the overview / editor) ────────────


def test_upsert_note_includes_title():
    r, mgr = _cap_repo()
    note = ProcessNote(
        id="n-7",
        title="Bottleneck here",
        text="hi",
        createdAt=datetime(2026, 1, 1),
        target=NoteTarget(type="node", value="A"),
        filterSnapshot=FilterSnapshot(fromDate=datetime(2026, 1, 1), toDate=datetime(2026, 1, 2)),
        username="Bob",
    )
    asyncio.run(r.upsert_note(note, 7, "Bob"))
    insert = mgr.executed[-1]
    assert "TITLE" in insert and "'Bottleneck here'" in insert


def test_update_note_sets_title():
    r, mgr = _cap_repo()
    asyncio.run(r.update_note("n-9", 7, edited_by="Bob", title="New subject"))
    assert "TITLE = 'New subject'" in mgr.executed[-1]


def test_endpoint_comment_title_updates_note_title(monkeypatch):
    from app.api.features import NoteUpdateBody

    repo, _ = _run_update(
        monkeypatch,
        caller="alice",
        meta=("alice", False),
        body=NoteUpdateBody(title="Bottleneck", comment="we see delays here"),
    )
    # The comment's title becomes the note's shown title and appears in the header.
    assert repo.update_kwargs["title"] == "Bottleneck"
    assert "Bottleneck" in repo.update_kwargs["comment_block"]


def test_journey_paths_limit_is_clamped():
    from app.db.repository import _MAX_PATH_ROWS

    r, mgr = _cap_repo()
    f = FilterSpec()
    # A runaway limit is capped; a zero/negative one floors at 1.
    asyncio.run(r.load_journey_paths(7, f, limit=10**9))
    assert f"LIMIT {_MAX_PATH_ROWS}" in mgr.executed[-1]
    asyncio.run(r.load_journey_paths(7, f, limit=0))
    assert "LIMIT 1" in mgr.executed[-1]


def test_goodness_query_is_the_collapsed_per_journey_average():
    # Goodness is a path-frequency-weighted mean whose per-path term is constant across a
    # path's journeys, so it collapses to a plain per-journey AVG — no LISTAGG path string
    # and no distinct-path grouping. Guard that the optimised shape stays in place.
    r, mgr = _cap_repo(rows=[[2.5, 42]])
    got = asyncio.run(r.load_process_goodness(7, FilterSpec()))
    assert got == (2.5, 42)  # (raw_goodness, filtered_count) read straight off the AVG/COUNT
    sql = mgr.executed[-1]
    assert "LISTAGG" not in sql and "distinct_paths" not in sql and "ordered_paths" not in sql
    assert "WITH per_journey AS" in sql
    assert "AVG(" in sql and "COUNT(*) AS filtered_count" in sql
    assert "SECONDS_BETWEEN(MAX(j.EVENT_TIME), MIN(j.EVENT_TIME))" in sql
    assert "LEFT JOIN STEPS s ON j.STEP_ID = s.STEP_ID" in sql  # integer join, not STEP name


def test_event_id_suggestions_limit_is_clamped():
    from app.db.repository import _MAX_SUGGESTIONS

    r, mgr = _cap_repo()
    asyncio.run(r.load_event_id_suggestions(7, "pre", limit=10**9))
    assert f"LIMIT {_MAX_SUGGESTIONS}" in mgr.executed[-1]


def test_journey_sequence_is_time_ordered_and_shaped():
    import asyncio as _aio

    rows = [
        ["login", datetime(2026, 1, 1, 8, 0, 0)],
        ["search", datetime(2026, 1, 1, 8, 1, 0)],
        ["login", datetime(2026, 1, 1, 8, 5, 0)],  # a revisit — kept, not collapsed
    ]
    r, mgr = _cap_repo(rows=rows)
    seq = _aio.run(r.load_journey_sequence(7, "abc123"))
    # Ordered by EVENT_TIME then STEP_ID — the ordering the graph is built from.
    assert "ORDER BY EVENT_TIME, STEP_ID" in mgr.executed[-1]
    assert "EVENT_ID = 'abc123'" in mgr.executed[-1]
    # The raw trace is returned as {step, eventTime}; the loop (login twice) is preserved.
    assert [e["step"] for e in seq] == ["login", "search", "login"]
    assert all(set(e) == {"step", "eventTime"} for e in seq)


def test_friendly_error_hides_raw_driver_text_without_detail():
    """The client-facing (detail=False) message carries no raw driver text; the
    verbose form (used by power/admin probes) still does."""
    from app.db.manager import friendly_error

    exc = RuntimeError("ORA-XYZ internal host db-prod-07.corp.example:8563 leaked")
    generic = friendly_error(exc, detail=False)
    verbose = friendly_error(exc, detail=True)
    assert "db-prod-07" not in generic and "leaked" not in generic
    assert "db-prod-07" in verbose  # operator setting up the connection still sees it

    # Categorised guidance survives without echoing the raw text.
    auth = friendly_error(RuntimeError("authentication failed for secret-user"), detail=False)
    assert "Authentication failed" in auth and "secret-user" not in auth


# ── STEPS cache (perf: one round trip per session, not per map reload) ────────

_STEP_ROW = ["A", "descA", "blue", "white", 5, "stadium", False, None]


def _step_selects(mgr):
    return [s for s in mgr.executed if "FROM STEPS" in s and "SELECT STEP" in s]


def test_load_steps_is_cached_after_first_read():
    r, mgr = _cap_repo([_STEP_ROW])
    first = asyncio.run(r.load_steps(7))
    second = asyncio.run(r.load_steps(7))
    assert set(first) == set(second) == {"A"}
    assert len(_step_selects(mgr)) == 1  # second call served from cache


def test_load_steps_returns_a_copy_so_callers_cannot_poison_the_cache():
    r, mgr = _cap_repo([_STEP_ROW])
    d = asyncio.run(r.load_steps(7))
    d.clear()  # mutate the returned dict
    again = asyncio.run(r.load_steps(7))
    assert set(again) == {"A"}                 # cache intact
    assert len(_step_selects(mgr)) == 1         # still no re-read


def test_update_step_invalidates_the_cache():
    r, mgr = _cap_repo([_STEP_ROW])
    asyncio.run(r.load_steps(7))
    asyncio.run(r.update_step(
        7, "A", bg_color="red", fg_color="white", score=1,
        shape="stadium", belongs_to=None, description=None))
    asyncio.run(r.load_steps(7))
    assert len(_step_selects(mgr)) == 2         # re-read after the update


def test_steps_cache_is_keyed_per_project():
    r, mgr = _cap_repo([_STEP_ROW])
    asyncio.run(r.load_steps(11))
    asyncio.run(r.load_steps(12))         # different project → its own read
    assert len(_step_selects(mgr)) == 2
    asyncio.run(r.load_steps(11))         # cached
    assert len(_step_selects(mgr)) == 2


# ── Merged bootstrap queries (perf: fewer serialised round trips) ─────────────


def test_load_project_bounds_is_a_single_scan_with_all_four_ranges():
    # One query returns date + step-count + journey-time + score ranges.
    rows = [["2024-01-01 00:00:00", "2024-02-01 00:00:00", 2, 9, 30, 600, -4, 20]]
    r, mgr = _cap_repo(rows)
    b = asyncio.run(r.load_project_bounds(7))
    assert len(mgr.executed) == 1                       # ONE round trip
    sql = mgr.executed[0]
    assert "LEFT JOIN STEPS s" in sql and "GROUP BY j.EVENT_ID" in sql
    assert "SECONDS_BETWEEN" in sql and "SUM(COALESCE(s.SCORE, 0))" in sql
    assert (b.date_min, b.date_max) == (datetime(2024, 1, 1), datetime(2024, 2, 1))
    assert (b.step_min, b.step_max) == (2, 9)
    assert (b.time_min, b.time_max) == (30, 600)
    assert (b.score_min, b.score_max) == (-4, 20)


def test_load_project_bounds_empty_project_uses_the_same_defaults():
    # An empty project → one row of NULLs → the same defaults as the split methods.
    r, mgr = _cap_repo([[None] * 8])
    b = asyncio.run(r.load_project_bounds(7))
    assert b.date_min is None and b.date_max is None
    assert (b.step_min, b.step_max) == (1, 1)
    assert (b.time_min, b.time_max) == (0, 0)
    assert (b.score_min, b.score_max) == (0, 0)


def test_load_meta_values_multi_one_round_trip_grouped_by_column():
    rows = [["META_1", "a"], ["META_1", "b"], ["META_3", "z"]]
    r, mgr = _cap_repo(rows)
    out = asyncio.run(r.load_meta_values_multi(7, ["META_1", "META_3"]))
    assert len(mgr.executed) == 1                       # ONE round trip
    sql = mgr.executed[0]
    assert sql.count("UNION ALL") == 1                  # two branches, one union
    assert "META_2" not in sql                          # only requested columns
    assert out == {"META_1": ["a", "b"], "META_3": ["z"]}


def test_load_meta_values_multi_no_columns_makes_no_query():
    r, mgr = _cap_repo()
    out = asyncio.run(r.load_meta_values_multi(7, []))
    assert out == {} and mgr.executed == []             # nothing configured → no SQL


def test_load_meta_values_multi_rejects_unknown_columns():
    r, mgr = _cap_repo()
    # An unsupported column name is dropped (never interpolated into SQL).
    out = asyncio.run(r.load_meta_values_multi(7, ["META_1; DROP", "META_2"]))
    assert "META_1; DROP" not in out
    assert set(out) == {"META_2"}


# ── Duration buckets: single JOURNEYS scan (was a self-join scanning twice) ───


def test_duration_buckets_scans_journeys_once_via_window_functions():
    from app.models import FilterSpec as _FS
    # rows shaped (bin_idx, cnt, min_dur, max_dur)
    rows = [[0, 3, 0.0, 100.0], [1, 5, 0.0, 100.0], [9, 2, 0.0, 100.0]]
    r, mgr = _cap_repo(rows)
    buckets = asyncio.run(r.load_duration_buckets(7, _FS(), bin_count=10))
    sql = mgr.executed[0]
    # JOURNEYS is aggregated once; the global min/max come from window aggregates.
    assert sql.count("FROM JOURNEYS") == 1
    assert "MIN(dur) OVER ()" in sql and "MAX(dur) OVER ()" in sql
    assert "GROUP BY EVENT_ID" in sql
    # Same output shape: one labelled bucket per returned bin.
    assert [b.count for b in buckets] == [3, 5, 2]
    assert all("–" in b.label for b in buckets)


def test_duration_buckets_empty_returns_no_buckets():
    from app.models import FilterSpec as _FS
    r, mgr = _cap_repo([])
    assert asyncio.run(r.load_duration_buckets(7, _FS())) == []


# ── Actions: raw log-entry query (SHOW LAST N LOG ENTRIES FROM NODE(...)) ─────


def test_log_entries_sql_scopes_by_step_order_and_limit():
    from app.models import FilterSpec as _FS

    r = repo()
    sql = r._log_entries_sql(
        7, ["PAYMENT", "LOGIN"], _FS(), event_ids=None, limit=5, descending=True
    )
    assert "SELECT EVENT_ID, STEP, EVENT_TIME, META_1, META_2, META_3" in sql
    assert "STEP IN ('PAYMENT', 'LOGIN')" in sql
    assert "ORDER BY EVENT_TIME DESC, STEP_ID DESC" in sql
    assert "LIMIT 5" in sql
    # Project scope + the sample-set fragment are always applied.
    assert "WHERE PROJECT_ID = 7" in sql
    assert "SAMPLE_SET = 'ORIGINAL'" in sql


def test_log_entries_sql_ascending_and_clamps_the_limit():
    from app.models import FilterSpec as _FS

    r = repo()
    sql = r._log_entries_sql(7, ["A"], _FS(), event_ids=None, limit=10_000, descending=False)
    assert "ORDER BY EVENT_TIME ASC, STEP_ID ASC" in sql
    assert "LIMIT 1000" in sql  # _MAX_LOG_ENTRIES


def test_log_entries_sql_event_id_list_is_md5_normalised_and_escaped():
    import hashlib

    from app.models import FilterSpec as _FS

    r = repo()
    sql = r._log_entries_sql(
        7, ["A"], _FS(), event_ids=["CRA-000124"], limit=1, descending=True
    )
    digest = hashlib.md5(b"CRA-000124").hexdigest()
    assert f"EVENT_ID IN ('{digest}')" in sql  # business id hashed to the stored MD5

    # An already-hashed 32-char hex id is used as-is; single quotes are escaped.
    already = "0" * 32
    sql2 = r._log_entries_sql(9, ["O'Brien"], _FS(), event_ids=[already], limit=1, descending=True)
    assert f"EVENT_ID IN ('{already}')" in sql2
    assert "STEP IN ('O''Brien')" in sql2 and "PROJECT_ID = 9" in sql2


def test_load_log_entries_empty_steps_runs_no_query():
    from app.models import FilterSpec as _FS

    r, mgr = _cap_repo(rows=[["e1", "PAYMENT", datetime(2024, 1, 1), None, None, None]])
    out = asyncio.run(r.load_log_entries(7, [], _FS()))
    assert out == {"columns": ["EVENT_ID", "STEP", "EVENT_TIME", "META_1", "META_2", "META_3"], "rows": []}
    assert mgr.executed == []  # no steps ⇒ never touches the database


def test_load_log_entries_shapes_rows():
    from app.models import FilterSpec as _FS

    rows = [["e1", "PAYMENT", datetime(2024, 1, 2, 3, 4, 5), "m1", None, "m3"]]
    r, mgr = _cap_repo(rows=rows)
    out = asyncio.run(r.load_log_entries(7, ["PAYMENT"], _FS(), limit=1))
    assert len(mgr.executed) == 1
    assert out["rows"] == [["e1", "PAYMENT", "2024-01-02 03:04:05", "m1", None, "m3"]]


def test_live_transitions_sql_groups_on_step_id_then_maps_to_names():
    # The DFG is built on the integer STEP_ID (activity id) — LEAD and GROUP BY run
    # on the id — and STEP names are attached only in the final projection, matching
    # the performance template.
    sql = ProcessRepository._live_transitions_sql(7, "")
    assert "LEAD(STEP_ID)" in sql and "LEAD(STEP)" not in sql
    assert "GROUP BY FROM_STEP_ID, TO_STEP_ID" in sql
    assert "S.STEP_ID = H.FROM_STEP_ID" in sql and "T.STEP_ID = H.TO_STEP_ID" in sql
    assert "S.STEP AS FROM_STEP" in sql and "T.STEP AS TO_STEP" in sql


def test_materialized_transitions_sql_groups_on_step_id_then_maps_to_names():
    sql = ProcessRepository._materialized_transitions_sql(7, "")
    assert "GROUP BY FROM_STEP_ID, TO_STEP_ID" in sql
    assert "S.STEP_ID = H.FROM_STEP_ID" in sql and "T.STEP_ID = H.TO_STEP_ID" in sql
    assert "S.STEP AS FROM_STEP" in sql and "T.STEP AS TO_STEP" in sql


# ── load_journeys (per-case aggregate rows behind an aggregate) ───────────────


def _journeys_sql(**kwargs) -> str:
    repo_, mgr = _cap_repo()
    asyncio.run(repo_.load_journeys("4", FilterSpec(), **kwargs))
    return mgr.executed[-1]


def test_load_journeys_groups_per_case_and_orders_by_duration_desc_by_default():
    sql = _journeys_sql()
    assert "GROUP BY EVENT_ID" in sql
    assert "SECONDS_BETWEEN(MAX(EVENT_TIME), MIN(EVENT_TIME)) AS DURATION_SECS" in sql
    # Slowest first, with EVENT_ID breaking ties so the order is total.
    assert "ORDER BY DURATION_SECS DESC, EVENT_ID" in sql
    assert "LIMIT 20" in sql
    assert "LISTAGG" not in sql  # the path costs extra; it is opt-in


def test_load_journeys_rejects_an_unknown_order_and_never_interpolates_it():
    import pytest

    with pytest.raises(ValueError, match="Unknown order_by"):
        _journeys_sql(order_by="EVENT_ID; DROP TABLE JOURNEYS--")


def test_load_journeys_accepts_every_advertised_order():
    from app.db.repository import JOURNEY_ORDERS

    for name, clause in JOURNEY_ORDERS.items():
        assert f"ORDER BY {clause}, EVENT_ID" in _journeys_sql(order_by=name)


def test_load_journeys_bounds_are_having_clauses_on_the_aggregates():
    sql = _journeys_sql(min_duration_secs=600, max_steps=8)
    assert "HAVING SECONDS_BETWEEN(MAX(EVENT_TIME), MIN(EVENT_TIME)) >= 600.0" in sql
    assert "COUNT(*) <= 8" in sql
    # Aliases are not portable in HAVING — the expressions are repeated instead.
    assert "HAVING DURATION_SECS" not in sql


def test_load_journeys_clamps_the_limit_and_can_add_the_path():
    from app.db.repository import _MAX_JOURNEY_ROWS

    assert f"LIMIT {_MAX_JOURNEY_ROWS}" in _journeys_sql(limit=10_000)
    assert "LIMIT 1" in _journeys_sql(limit=0)
    assert "LISTAGG(STEP, ' -> ') WITHIN GROUP (ORDER BY EVENT_TIME ASC)" in _journeys_sql(
        include_path=True
    )


def test_load_journeys_does_not_alias_the_path_to_a_reserved_word():
    # Exasol rejects `AS PATH` outright ("unexpected PATH_"), and a string assertion on
    # the generated SQL cannot see that — so name the trap in a test of its own.
    sql = _journeys_sql(include_path=True)
    assert "AS JOURNEY_PATH" in sql
    assert "AS PATH" not in sql


def test_load_journeys_shapes_rows_and_skips_the_path_when_not_requested():
    rows = [["abc123", "2024-04-21 04:36:09", "2024-04-21 04:55:03", 1134, 5, "Manage", "ANA", None]]
    repo_, _ = _cap_repo(rows)
    out = asyncio.run(repo_.load_journeys("1", FilterSpec()))
    assert out[0]["eventId"] == "abc123"
    assert out[0]["durationSecs"] == 1134.0 and out[0]["stepCount"] == 5
    assert out[0]["startDate"] == datetime(2024, 4, 21, 4, 36, 9)
    assert out[0]["meta1"] == "Manage" and out[0]["meta3"] is None
    assert out[0]["path"] is None
