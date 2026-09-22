"""Pure run-collapse transforms behind the aggregate materialiser (no database)."""

from __future__ import annotations

from app.db.materialize import (
    _JOURNEY_COLUMNS,
    AggGroup,
    SourceEvent,
    StepRow,
    _journey_rows,
    _journeys_insert_values,
    collapse_high_level,
    collapse_high_level_multi,
    filter_detail,
    sigma_step_row,
)


def _ev(eid: str, step: str, sid: int) -> SourceEvent:
    return SourceEvent(eid, step, sid, f"2024-01-01 00:00:{sid:02d}", None, None, None)


def test_collapse_folds_each_member_run_into_one_sigma_event():
    # e1:  A  M1 M2  B  M3   (members M1,M2,M3)
    events = [_ev("e1", s, i) for i, s in enumerate(["A", "M1", "M2", "B", "M3"])]
    out = collapse_high_level(events, {"M1", "M2", "M3"}, "Σ")
    assert [e.step for e in out] == ["A", "Σ", "B", "Σ"]
    # The Σ event keeps the run's FIRST event's TIME (M1 at index 1). Its STEP_ID is the
    # Σ super-step's OWN activity id (from sigma_ids), not a member's — None when omitted.
    sigma = out[1]
    assert sigma.step_id is None and sigma.event_time.endswith(":01")
    # When sigma_ids is supplied, every Σ event is stamped with that id.
    stamped = collapse_high_level_multi(
        events, [AggGroup(frozenset({"M1", "M2", "M3"}), "Σ")], {"Σ": 99}
    )
    assert all(e.step_id == 99 for e in stamped if e.step == "Σ")


def test_collapse_resets_run_across_journeys():
    events = [_ev("e1", "M1", 0), _ev("e1", "M2", 1), _ev("e2", "M1", 0), _ev("e2", "X", 1)]
    out = collapse_high_level(events, {"M1", "M2"}, "Σ")
    # e1's M1,M2 fold to one Σ; e2 starts a fresh run → its own Σ, then X passes through.
    assert [(e.event_id, e.step) for e in out] == [("e1", "Σ"), ("e2", "Σ"), ("e2", "X")]


def test_collapse_passes_non_members_through_unchanged():
    events = [_ev("e1", "A", 0), _ev("e1", "B", 1), _ev("e1", "C", 2)]
    out = collapse_high_level(events, {"Z"}, "Σ")
    assert [e.step for e in out] == ["A", "B", "C"]


def test_multi_collapse_folds_each_aggregate_and_breaks_between_them():
    # e1: A A1 A2 B1 B2 C  (aggregate A={A1,A2} → ΣA, aggregate B={B1,B2} → ΣB)
    events = [_ev("e1", s, i) for i, s in enumerate(["A", "A1", "A2", "B1", "B2", "C"])]
    out = collapse_high_level_multi(
        events, [AggGroup(frozenset({"A1", "A2"}), "ΣA"), AggGroup(frozenset({"B1", "B2"}), "ΣB")]
    )
    assert [e.step for e in out] == ["A", "ΣA", "ΣB", "C"]


def test_multi_collapse_separates_adjacent_different_aggregates():
    # Adjacent members of DIFFERENT aggregates must NOT merge.
    events = [_ev("e1", s, i) for i, s in enumerate(["A1", "B1"])]
    out = collapse_high_level_multi(
        events, [AggGroup(frozenset({"A1"}), "ΣA"), AggGroup(frozenset({"B1"}), "ΣB")]
    )
    assert [e.step for e in out] == ["ΣA", "ΣB"]


def test_filter_detail_keeps_only_member_events():
    events = [_ev("e1", "A", 0), _ev("e1", "M1", 1), _ev("e1", "B", 2), _ev("e1", "M2", 3)]
    out = filter_detail(events, {"M1", "M2"})
    assert [e.step for e in out] == ["M1", "M2"]


def test_sigma_step_row_sums_member_scores():
    steps = [
        StepRow("M1", "", "", "", 3, "rectangle", False, ""),
        StepRow("M2", "", "", "", 4, "rectangle", False, ""),
        StepRow("X", "", "", "", 9, "rectangle", False, ""),
    ]
    row = sigma_step_row("Σ", {"M1", "M2"}, steps)
    assert row.step == "Σ" and row.score == 7  # 3 + 4, X excluded


def test_sigma_step_inherits_shared_belongs_to_group():
    steps = [
        StepRow("M1", "", "", "", None, "rectangle", False, "Payments"),
        StepRow("M2", "", "", "", None, "rectangle", False, "Payments"),
    ]
    assert sigma_step_row("Σ", {"M1", "M2"}, steps).belongs_to == "Payments"


def test_sigma_step_has_no_group_when_members_span_groups():
    steps = [
        StepRow("M1", "", "", "", None, "rectangle", False, "Payments"),
        StepRow("M2", "", "", "", None, "rectangle", False, "Fulfilment"),
        StepRow("M3", "", "", "", None, "rectangle", False, ""),  # ungrouped, ignored
    ]
    assert sigma_step_row("Σ", {"M1", "M2", "M3"}, steps).belongs_to == ""
    # A single group plus ungrouped members still inherits that one group.
    steps[1].belongs_to = "Payments"
    assert sigma_step_row("Σ", {"M1", "M2", "M3"}, steps).belongs_to == "Payments"


def test_journey_rows_match_import_column_order():
    events = [SourceEvent("e1", "A", 0, "2024-01-01 00:00:00", "m1", None, "m3")]
    rows = list(_journey_rows(1, events))
    assert len(_JOURNEY_COLUMNS) == 8
    assert rows == [(1, "e1", "A", 0, "2024-01-01 00:00:00", "m1", None, "m3")]


def test_fallback_values_sql_escapes_and_uses_timestamp_literal():
    events = [SourceEvent("e'1", "Pay'ment", None, "2024-01-01 00:00:00", "a,b", None, None)]
    sql = _journeys_insert_values(1, events)
    assert "INSERT INTO JOURNEYS" in sql
    assert "TIMESTAMP '2024-01-01 00:00:00'" in sql
    assert "'e''1'" in sql and "'Pay''ment'" in sql  # single quotes doubled
    assert "NULL" in sql  # STEP_ID None → NULL
