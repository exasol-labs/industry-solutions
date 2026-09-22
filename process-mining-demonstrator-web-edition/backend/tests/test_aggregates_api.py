"""Aggregate endpoint auth + validation gates (all fire before any database work)."""

from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def backend(tmp_path, monkeypatch):
    monkeypatch.setenv("PMW_DATA_DIR", str(tmp_path))
    import app.config as config

    importlib.reload(config)
    import app.store.crypto as crypto

    importlib.reload(crypto)
    import app.services.certs  # noqa: F401

    import app.store.security as security_mod

    importlib.reload(security_mod)
    import app.db.manager as manager

    importlib.reload(manager)
    import app.api.connections as connections_api

    importlib.reload(connections_api)
    import app.api.aggregates as aggregates_api

    importlib.reload(aggregates_api)
    import app.main as main

    importlib.reload(main)
    return main.app, security_mod.store


def _user(store, name, *, power=False, developer=False, admin=False):
    store.create_user(name, "pw", is_admin=admin)
    if power:
        store.set_power(name, True)
    if developer:
        store.set_developer(name, True)


def _conn(store, *, assignments):
    return store.upsert_connection({
        "name": "Cust", "host": "db.example.com", "port": 8563, "username": "svc",
        "schema": "MINING", "password": "s3cret", "llmURL": "", "llmModel": "", "llmKey": "",
        "assignments": assignments,
    }).id


def _body(cid, members):
    return {
        "connectionId": cid,
        "members": members,
        "sigmaName": "Σ Test",
        "highLevel": {"name": "High", "targetConnectionId": "", "targetSchema": ""},
        "detail": {"name": "Detail", "targetConnectionId": "", "targetSchema": ""},
    }


def test_non_developer_cannot_create(backend):
    app, store = backend
    _user(store, "pat", power=True)  # power user is NOT allowed
    cid = _conn(store, assignments=["pat"])
    client = TestClient(app)
    r = client.post(f"/api/projects/7/aggregate", json=_body(cid, ["A", "B"]), headers={"X-PMW-User": "pat"})
    assert r.status_code == 403


def test_developer_needs_at_least_two_members(backend):
    app, store = backend
    _user(store, "dev", developer=True)
    cid = _conn(store, assignments=["dev"])
    client = TestClient(app)
    r = client.post(f"/api/projects/7/aggregate", json=_body(cid, ["A"]), headers={"X-PMW-User": "dev"})
    assert r.status_code == 400


def test_idor_unassigned_connection(backend):
    app, store = backend
    _user(store, "dev", developer=True)  # assigned to nothing
    _user(store, "owner", developer=True)
    cid = _conn(store, assignments=["owner"])
    client = TestClient(app)
    r = client.post(f"/api/projects/7/aggregate", json=_body(cid, ["A", "B"]), headers={"X-PMW-User": "dev"})
    assert r.status_code == 403


def test_list_aggregates_empty(backend):
    app, store = backend
    _user(store, "dev", developer=True)
    cid = _conn(store, assignments=["dev"])
    client = TestClient(app)
    r = client.get("/api/projects/7/aggregates", params={"connectionId": cid}, headers={"X-PMW-User": "dev"})
    assert r.status_code == 200 and r.json()["aggregates"] == []


def _group(sigma, members, name="Detail"):
    return {"sigmaName": sigma, "members": members, "detail": {"name": name, "targetConnectionId": "", "targetSchema": ""}}


def _set_body(cid, groups):
    return {"connectionId": cid, "highLevel": {"name": "High", "targetConnectionId": "", "targetSchema": ""}, "aggregates": groups}


def test_set_create_rejects_overlapping_members(backend):
    app, store = backend
    _user(store, "dev", developer=True)
    cid = _conn(store, assignments=["dev"])
    client = TestClient(app)
    body = _set_body(cid, [_group("Σ1", ["A", "B"]), _group("Σ2", ["B", "C"])])  # B in both
    r = client.post("/api/projects/7/aggregate-set", json=body, headers={"X-PMW-User": "dev"})
    assert r.status_code == 400 and "only one aggregate" in r.json()["detail"]


def test_set_create_needs_developer(backend):
    app, store = backend
    _user(store, "pat", power=True)
    cid = _conn(store, assignments=["pat"])
    client = TestClient(app)
    r = client.post("/api/projects/7/aggregate-set", json=_set_body(cid, [_group("Σ1", ["A", "B"])]), headers={"X-PMW-User": "pat"})
    assert r.status_code == 403


def test_add_to_missing_set_is_404(backend):
    app, store = backend
    _user(store, "dev", developer=True)
    cid = _conn(store, assignments=["dev"])
    client = TestClient(app)
    body = {"connectionId": cid, "aggregates": [_group("Σ1", ["A", "B"])]}
    r = client.post("/api/projects/999/aggregate-set/add", json=body, headers={"X-PMW-User": "dev"})
    assert r.status_code == 404


def test_aggregate_set_roundtrips_in_store(backend):
    _app, store = backend
    rec = store.save_aggregate_set({
        "sourceConnectionId": "c1", "sourceProjectId": "P",
        "highLevelConnectionId": "c1", "highLevelProjectId": "agg_1",
        "highLevelSchema": "MINING", "highLevelTitle": "High",
        "aggregates": [{"sigmaStep": "Σ1", "members": ["A", "B"], "detailConnectionId": "c1", "detailProjectId": "d1", "detailSchema": "MINING", "detailTitle": "D"}],
    })
    assert rec["createdAt"] and rec["updatedAt"]
    assert store.aggregate_set_by_source("c1", "P")["highLevelProjectId"] == "agg_1"
    assert store.aggregate_set_by_high_level("c1", "agg_1")["sourceProjectId"] == "P"
    # upsert by source: a second save with an extra aggregate replaces, keeps createdAt.
    rec["aggregates"].append({"sigmaStep": "Σ2", "members": ["C", "D"], "detailConnectionId": "c1", "detailProjectId": "d2", "detailSchema": "MINING", "detailTitle": "D2"})
    rec2 = store.save_aggregate_set(rec)
    assert rec2["createdAt"] == rec["createdAt"]
    assert len(store.aggregate_set_by_source("c1", "P")["aggregates"]) == 2


def test_aggregate_connection_roles_group_by_role(backend):
    _app, store = backend
    cid = _conn(store, assignments=[])  # host db.example.com, schema MINING
    store.save_aggregate_set({
        "sourceConnectionId": cid, "sourceProjectId": "P",
        "highLevelConnectionId": cid, "highLevelProjectId": "agg_1",
        "highLevelSchema": "MINING", "highLevelTitle": "High",
        "aggregates": [{"sigmaStep": "Σ1", "members": ["A", "B"], "detailConnectionId": cid, "detailProjectId": "d1", "detailSchema": "AGG_DETAIL", "detailTitle": "D"}],
    })
    roles = store.aggregate_connection_roles()
    # Matching is by the exact connection picked for each role, not by (host, schema).
    assert cid in roles["source"]
    assert cid in roles["high"]
    assert cid in roles["detail"]


def test_connection_flags_source_marked_but_not_hideable(backend):
    """A connection whose schema holds the high-level/source is marked but never hidden; a
    separate connection pointing only at the detail schema is marked AND hideable."""
    app, store = backend
    _user(store, "dev", developer=True)
    src = _conn(store, assignments=["dev"])  # schema MINING (source + high-level here)
    det = store.upsert_connection({
        "name": "Detail", "host": "db.example.com", "port": 8563, "username": "svc",
        "schema": "AGG_DETAIL", "password": "s3cret", "llmURL": "", "llmModel": "", "llmKey": "",
        "assignments": ["dev"],
    }).id
    store.save_aggregate_set({
        "sourceConnectionId": src, "sourceProjectId": "P",
        "highLevelConnectionId": src, "highLevelProjectId": "agg_1",
        "highLevelSchema": "MINING", "highLevelTitle": "High",
        "aggregates": [{"sigmaStep": "Σ1", "members": ["A", "B"], "detailConnectionId": det, "detailProjectId": "d1", "detailSchema": "AGG_DETAIL", "detailTitle": "D"}],
    })
    client = TestClient(app)
    conns = {c["id"]: c for c in client.get("/api/connections", headers={"X-PMW-User": "dev"}).json()}
    assert conns[src]["hasAggregates"] and not conns[src]["aggregateDetailOnly"]  # source: shown, kept
    assert conns[det]["hasAggregates"] and conns[det]["aggregateDetailOnly"]  # detail-only: hideable


def test_aggregate_link_roundtrips_in_store(backend):
    # PROJECT_ID is a SMALLINT: projectId/detailProjectId are ints. Guards against
    # .strip()-ing them (which crashed link storage, so Σ nodes had no drill target).
    _app, store = backend
    store.add_aggregate_link(
        {"connectionId": "c1", "projectId": 2, "sigmaStep": "Σ", "detailConnectionId": "c1", "detailProjectId": 3}
    )
    got = store.aggregates_for("c1", 2)
    assert len(got) == 1 and got[0]["detailProjectId"] == 3
    # keyed by (connection, project, sigma) — a second call with the same key replaces.
    store.add_aggregate_link(
        {"connectionId": "c1", "projectId": 2, "sigmaStep": "Σ", "detailConnectionId": "c2", "detailProjectId": 4}
    )
    got2 = store.aggregates_for("c1", 2)
    assert len(got2) == 1 and got2[0]["detailProjectId"] == 4


def test_aggregates_for_falls_back_to_the_set_when_links_are_missing(backend):
    # A set saved without its per-Σ link rows (e.g. an older build) must still offer
    # drill targets, derived from the set's aggregates.
    _app, store = backend
    store.save_aggregate_set({
        "sourceConnectionId": "c1", "sourceProjectId": 1,
        "highLevelConnectionId": "c1", "highLevelProjectId": 2,
        "highLevelSchema": "MINING", "highLevelTitle": "High",
        "aggregates": [
            {"sigmaStep": "Σ1", "members": ["A", "B"], "detailConnectionId": "c1", "detailProjectId": 3, "detailSchema": "MINING", "detailTitle": "D1"},
            {"sigmaStep": "Σ2", "members": ["C", "D"], "detailConnectionId": "c1", "detailProjectId": 4, "detailSchema": "MINING", "detailTitle": "D2"},
        ],
    })
    got = store.aggregates_for("c1", 2)  # no explicit link rows exist
    assert {g["sigmaStep"]: g["detailProjectId"] for g in got} == {"Σ1": 3, "Σ2": 4}
    # An explicit link takes precedence over the derived fallback.
    store.add_aggregate_link(
        {"connectionId": "c1", "projectId": 2, "sigmaStep": "Σ1", "detailConnectionId": "c1", "detailProjectId": 9}
    )
    got2 = store.aggregates_for("c1", 2)
    assert len(got2) == 1 and got2[0]["detailProjectId"] == 9
