"""Tests for the demo-data generators (app.db.demo_data): the retail (Online
Bookstore), finance (Online Credit Application) and transportation
(Flight Booking & Management) datasets.

The event-log generators are pure (seedable RNG) so structure and determinism are
asserted directly; the loader is driven with a fake connection that records SQL.
"""

from __future__ import annotations

import asyncio
import random
from collections import defaultdict

from app.db import demo_data as d
from app.db import manager


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows

    def fetchval(self):
        return self._rows[0][0] if self._rows else None


class FakeConn:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.committed = False
        self.closed = False

    def execute(self, sql: str):
        self.calls.append(sql)
        if "MAX(PROJECT_ID)" in sql:
            return _Result([[0]])          # empty PROJECTS → next id = 1
        return _Result([])                 # e.g. no existing project for this TITLE_SHORT

    def commit(self) -> None:
        self.committed = True

    def close(self) -> None:
        self.closed = True


def _run(monkeypatch, conn, dataset="retail", **overrides):
    monkeypatch.setattr(manager.DatabaseManager, "_open", lambda self, server, pw: conn)
    kwargs = dict(
        dataset=dataset, host="h", port=8563, username="u", password="p", schema="PM", journeys=2
    )
    kwargs.update(overrides)
    return asyncio.run(d.generate_demo_content(**kwargs))


def _by_journey(rows):
    grouped: dict[str, list] = defaultdict(list)
    for r in rows:
        grouped[r.event_id].append(r)
    return grouped


# ── retail: Online Bookstore ──────────────────────────────────────────────────


def test_retail_journeys_start_with_login_and_are_ordered():
    grouped = _by_journey(d.generate_retail_rows(40, random.Random(1)))
    assert len(grouped) == 40
    ids = d.step_id_map(d._RETAIL_STEP_DEFS)
    for events in grouped.values():
        assert events[0].step == "Login"
        # STEP_ID is now the stable activity id (not a 1..N sequence); ordering is
        # carried by strictly-increasing timestamps.
        times = [e.event_time for e in events]
        assert times == sorted(times) and len(set(times)) == len(times)
        assert all(e.step_id == ids[e.step] for e in events)
        assert events[0].meta1 in {"Credit Card", "PayPal", "Bank Transfer"}


def test_retail_step_defs_and_determinism():
    assert len(d._RETAIL_STEP_DEFS) == 24
    a = d.generate_retail_rows(8, random.Random(5))
    b = d.generate_retail_rows(8, random.Random(5))
    assert [(r.event_id, r.step) for r in a] == [(r.event_id, r.step) for r in b]


# ── finance: Online Credit Application ────────────────────────────────────────


def test_finance_entry_and_exit_points_and_metas():
    grouped = _by_journey(d.generate_finance_rows(600, random.Random(2)))
    for events in grouped.values():
        # Entry points are the "Bank"/"Affiliate" steps; exits are Payment/Rejected.
        assert events[0].step in {"Bank", "Affiliate"}
        assert events[-1].step in {"Payment", "Rejected"}
        # meta3 mirrors the channel; metas are constant within a journey.
        assert events[0].meta3 == events[0].step
        assert len({e.meta3 for e in events}) == 1
    # Meta titles as specified.
    assert d.DATASETS["finance"].meta_titles == ("Applied Credit Sum", "Income Class", "Channel")


def test_finance_flow_features_present():
    rows = d.generate_finance_rows(2000, random.Random(9))
    seen = {r.step for r in rows}
    # Assessment naming, agent-review + senior-approval loops, and the accept path.
    for step in (
        "Application Checked",
        "Additional Information Requested",  # 20% rework loop
        "Credit Assessment",
        "Credit Check",
        "Agent Review",  # 75–90% score band
        "Senior Agent Approval",  # >10.000 EUR extra agent
        "Accepted",
        "Payment to Applicant",
    ):
        assert step in seen, step
    # A rework loop means some journeys hit "Application Checked" more than once.
    grouped = _by_journey(rows)
    assert any(
        sum(1 for e in v if e.step == "Application Checked") >= 2 for v in grouped.values()
    )


def test_finance_affiliate_pays_out_faster_than_bank():
    grouped = _by_journey(d.generate_finance_rows(3000, random.Random(11)))
    paid = [v for v in grouped.values() if v[-1].step == "Payment"]

    def cycle(v):
        return (v[-1].event_time - v[0].event_time).total_seconds()

    bank = [cycle(v) for v in paid if v[0].step == "Bank"]
    affiliate = [cycle(v) for v in paid if v[0].step == "Affiliate"]
    assert sum(affiliate) / len(affiliate) < sum(bank) / len(bank)


# ── loader ────────────────────────────────────────────────────────────────────


def test_loader_provisions_and_loads_retail(monkeypatch):
    conn = FakeConn()
    res = _run(monkeypatch, conn, dataset="retail", journeys=3)
    assert res["ok"] and res["journeys"] == 3
    assert res["project"] == "Online Bookstore" and res["dataset"] == "retail"
    joined = "\n".join(conn.calls)
    assert conn.calls[0] == 'CREATE SCHEMA IF NOT EXISTS "PM"'
    for tbl in ("PROJECTS", "JOURNEYS", "STEPS", "METAS", "NOTES"):
        assert f"CREATE TABLE IF NOT EXISTS {tbl}" in joined
    assert "PROJECT_ID = 1" in joined and "BOOKSTORE" in joined and "Online Bookstore" in joined
    assert joined.count("INSERT INTO STEPS") == 24
    assert conn.committed and conn.closed


def test_loader_provisions_and_loads_finance(monkeypatch):
    conn = FakeConn()
    res = _run(monkeypatch, conn, dataset="finance", journeys=3)
    assert res["ok"] and res["project"] == "Online Credit Application"
    joined = "\n".join(conn.calls)
    assert "PROJECT_ID = 1" in joined and "CREDIT" in joined
    assert "Applied Credit Sum" in joined  # META titles inserted
    assert joined.count("INSERT INTO STEPS") == len(d._FINANCE_STEP_DEFS)
    assert "INSERT INTO JOURNEYS" in joined


def test_loader_touches_only_the_dataset_project(monkeypatch):
    conn = FakeConn()
    _run(monkeypatch, conn, dataset="finance", journeys=1)
    for verb in ("DELETE FROM PROJECTS", "DELETE FROM METAS", "DELETE FROM JOURNEYS"):
        stmts = [c for c in conn.calls if c.startswith(verb)]
        assert stmts and all("PROJECT_ID = 1" in s for s in stmts)


def test_loader_rejects_unknown_dataset(monkeypatch):
    conn = FakeConn()
    res = _run(monkeypatch, conn, dataset="nope")
    assert res["ok"] is False and "nope" in res["error"]
    assert conn.calls == []


def test_loader_clamps_journeys(monkeypatch):
    seen: dict = {}

    def _fake(count, rng=None):
        seen["count"] = count
        return []

    monkeypatch.setattr(d.DATASETS["retail"], "generate", _fake)
    conn = FakeConn()
    res = _run(monkeypatch, conn, dataset="retail", journeys=10_000_000)
    assert seen["count"] == d.MAX_JOURNEYS and res["journeys"] == d.MAX_JOURNEYS


def test_loader_validates_schema_and_count(monkeypatch):
    conn = FakeConn()
    assert _run(monkeypatch, conn, schema="  ", journeys=10)["ok"] is False
    assert conn.calls == []
    conn2 = FakeConn()
    assert _run(monkeypatch, conn2, journeys=0)["ok"] is False


def test_loader_reports_a_friendly_error(monkeypatch):
    class BoomConn(FakeConn):
        def execute(self, sql: str):
            r = super().execute(sql)
            if "INSERT INTO JOURNEYS" in sql:
                raise RuntimeError("insufficient privileges: INSERT denied")
            return r

    conn = BoomConn()
    res = _run(monkeypatch, conn, journeys=2)
    assert res["ok"] is False and "insufficient privileges" in res["error"]
    assert conn.closed


# ── transportation: Flight Booking & Management ───────────────────────────────


def test_transportation_structure_and_metas():
    spec = d.DATASETS["transportation"]
    assert spec.title_short == "FLIGHTS"
    assert spec.meta_titles == ("Journey Type", "Airline", "Payment Method")

    grouped = _by_journey(d.generate_transportation_rows(1200, random.Random(3)))
    assert all(evs[0].step == "Login" for evs in grouped.values())

    new = [e for e in grouped.values() if e[0].meta1 == "New Booking"]
    manage = [e for e in grouped.values() if e[0].meta1 == "Manage Booking"]
    assert 0.72 < len(new) / len(grouped) < 0.88  # ~80/20 split
    assert len(manage) > 0
    assert all(e[-1].step == "Confirm Booking" for e in new)
    assert all(e[-1].step == "Confirm Changes" for e in manage)

    # The two interline steps always appear together (a partner search implies a
    # partner booking connection), and interline covers ~half of new bookings.
    for e in grouped.values():
        steps = [x.step for x in e]
        assert ("Query Partner Airline System" in steps) == (
            "Connect Partner Booking System" in steps
        )
    interline = sum(1 for e in new if "Query Partner Airline System" in [x.step for x in e])
    assert 0.4 < interline / len(new) < 0.6

    # All five payment options appear, including the rare Advance Payment.
    pays = {e[-1].meta3 for e in grouped.values()}
    for method in ("Credit Card", "SEPA", "Apple Pay", "Google Pay", "Advance Payment"):
        assert method in pays

    defined = {s[0] for s in spec.step_defs}
    assert {x.step for e in grouped.values() for x in e} <= defined


def test_transportation_determinism():
    a = d.generate_transportation_rows(12, random.Random(7))
    b = d.generate_transportation_rows(12, random.Random(7))
    assert [(r.event_id, r.step, r.step_id, r.meta1, r.meta3) for r in a] == [
        (r.event_id, r.step, r.step_id, r.meta1, r.meta3) for r in b
    ]


def test_loader_provisions_and_loads_transportation(monkeypatch):
    conn = FakeConn()
    res = _run(monkeypatch, conn, dataset="transportation", journeys=4)
    assert res["ok"] and res["journeys"] == 4
    assert res["project"] == "Flight Booking & Management"
    assert res["dataset"] == "transportation"
    joined = "\n".join(conn.calls)
    assert "PROJECT_ID = 1" in joined and "FLIGHTS" in joined
    assert joined.count("INSERT INTO STEPS") == 15
    assert conn.committed and conn.closed


# ── transportation: Airport Passenger Flow ────────────────────────────────────


def test_airport_step_defs_shape():
    # 10 pre-airside steps + 9 airside/boarding steps each for the Dom and Int sides.
    assert len(d._AIRPORT_STEP_DEFS) == 28


def test_airport_topology_and_dom_int_split():
    grouped = _by_journey(d.generate_airport_rows(500, random.Random(11)))
    assert grouped
    saw_dom = saw_int = saw_denied = saw_early_exit = False
    for evs in grouped.values():
        steps = [e.step for e in evs]
        assert steps[0] == "ENTER Departure Hall"
        assert all(e.meta1.startswith("Terminal-") for e in evs)
        assert all(e.meta2 == "-" and e.meta3 == "-" for e in evs)
        assert [e.event_time for e in evs] == sorted(e.event_time for e in evs)
        # A passenger is on exactly one airside: the Int variant iff they cleared
        # Passport Control, the Dom variant otherwise (or neither, if they left early).
        has_passport = "ENTER Passport Control" in steps
        dom = [s for s in steps if s.endswith(" Dom")]
        intl = [s for s in steps if s.endswith(" Int")]
        if has_passport:
            assert intl and not dom
        else:
            assert not intl
        assert steps[-1].startswith(("BOARD Aircraft", "DENIED Boarding", "LEAVE Departure Hall"))
        saw_dom = saw_dom or bool(dom)
        saw_int = saw_int or bool(intl)
        saw_denied = saw_denied or any(s.startswith("DENIED Boarding") for s in steps)
        saw_early_exit = saw_early_exit or steps == ["ENTER Departure Hall", "LEAVE Departure Hall"]
    assert saw_dom and saw_int and saw_denied and saw_early_exit


def test_airport_streams_through_the_per_journey_generator(monkeypatch):
    # The airport dataset carries a per-journey generator; the loader must stream
    # through it (never the batch `generate`) and still load the APF project.
    spec = d.DATASETS["airport"]
    assert spec.generate_one is not None and spec.title_short == "APF"

    def _boom(*_a, **_k):
        raise AssertionError("batch generate path used for a streamed dataset")

    monkeypatch.setattr(spec, "generate", _boom)
    conn = FakeConn()
    res = _run(monkeypatch, conn, dataset="airport", journeys=3)
    assert res["ok"] and res["journeys"] == 3 and res["dataset"] == "airport"
    joined = "\n".join(conn.calls)
    assert "APF" in joined and "PROJECT_ID = 1" in joined and "INSERT INTO JOURNEYS" in joined
    assert conn.committed and conn.closed


def test_airport_uses_the_streamed_ceiling(monkeypatch):
    # Streamed datasets clamp to MAX_JOURNEYS_STREAMED, not the in-memory limit.
    # Shrink the ceiling so the assertion stays fast.
    monkeypatch.setattr(d, "MAX_JOURNEYS_STREAMED", 5)
    spec = d.DATASETS["airport"]
    calls = {"n": 0}
    real = spec.generate_one

    def _counting(i, rng):
        calls["n"] += 1
        return real(i, rng)

    monkeypatch.setattr(spec, "generate_one", _counting)
    conn = FakeConn()
    res = _run(monkeypatch, conn, dataset="airport", journeys=1000)
    assert res["journeys"] == 5 and calls["n"] == 5


# ── cross-dataset invariants (guards every dataset, incl. future ones) ────────

import pytest  # noqa: E402


@pytest.mark.parametrize("key", sorted(d.DATASETS))
def test_dataset_is_well_formed(key):
    spec = d.DATASETS[key]
    assert spec.key == key
    assert len(spec.meta_titles) == 3 and all(spec.meta_titles)
    names = [sd[0] for sd in spec.step_defs]
    assert len(names) == len(set(names)), f"{key} has duplicate step names"
    assert all(len(sd) == 8 for sd in spec.step_defs)
    # At least one end-of-process step is defined.
    assert any(sd[6] == 1 for sd in spec.step_defs), f"{key} has no end-of-process step"

    defined = set(names)
    grouped = _by_journey(spec.generate(200, random.Random(123)))
    assert grouped
    ids = d.step_id_map(spec.step_defs)
    for evs in grouped.values():
        # STEP_ID is the stable activity id for the step name; events are emitted in
        # (strictly increasing) time order. Only defined steps, three meta values each.
        times = [e.event_time for e in evs]
        assert times == sorted(times), f"{key} journey is not time-ordered"
        for e in evs:
            assert e.step in defined, f"{key} emits undefined step {e.step!r}"
            assert e.step_id == ids[e.step], f"{key} step_id != activity id for {e.step!r}"
            assert e.meta1 is not None and e.meta2 is not None and e.meta3 is not None


@pytest.mark.parametrize("key", sorted(d.DATASETS))
def test_dataset_generation_is_deterministic(key):
    spec = d.DATASETS[key]
    a = spec.generate(15, random.Random(99))
    b = spec.generate(15, random.Random(99))
    assert [(r.event_id, r.step, r.step_id, r.meta1) for r in a] == [
        (r.event_id, r.step, r.step_id, r.meta1) for r in b
    ]
