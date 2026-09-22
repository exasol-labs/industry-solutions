"""App-backend Actions endpoints: the admin-gated feature flag, role-gated authoring
(developers/admins) vs running (everyone except a plain standard user), the
per-(connection, project) IDOR guard, CRUD, and the SQL-preview translation."""

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
    import app.api.actions as actions_api

    importlib.reload(actions_api)
    import app.main as main

    importlib.reload(main)
    # The feature is opt-in; enable it for most tests (one test asserts the off state).
    security_mod.store.set_actions_enabled(True)
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


def _spec(**over):
    spec = {
        "availability": {"allNodes": True, "steps": []},
        "show": {"kind": "logEntries", "limit": 3, "metrics": [], "forLast": None},
        "from": {"selectors": ["THIS"]},
        "sort": "DESC",
        "where": None,
    }
    spec.update(over)
    return spec


def test_developer_can_crud_actions_scoped_to_connection_and_project(backend):
    app, store = backend
    _user(store, "dev", developer=True)
    cid = _conn(store, assignments=["dev"])
    client = TestClient(app)
    H = {"X-PMW-User": "dev"}

    # None yet.
    r = client.get("/api/projects/7/actions", params={"connectionId": cid}, headers=H)
    assert r.status_code == 200 and r.json()["actions"] == []

    # Create.
    r = client.post(
        "/api/projects/7/actions",
        json={"connectionId": cid, "name": "Last 3", "script": "…", "spec": _spec(), "enabled": True},
        headers=H,
    )
    assert r.status_code == 200
    aid = r.json()["id"]
    assert r.json()["name"] == "Last 3"

    # Listed under this (connection, project) only.
    assert len(client.get("/api/projects/7/actions", params={"connectionId": cid}, headers=H).json()["actions"]) == 1
    assert client.get("/api/projects/8/actions", params={"connectionId": cid}, headers=H).json()["actions"] == []

    # Update.
    r = client.put(
        f"/api/projects/7/actions/{aid}",
        json={"connectionId": cid, "name": "Renamed", "script": "…", "spec": _spec(), "enabled": False},
        headers=H,
    )
    assert r.status_code == 200 and r.json()["name"] == "Renamed" and r.json()["enabled"] is False

    # Delete.
    assert client.delete(f"/api/projects/7/actions/{aid}", params={"connectionId": cid}, headers=H).status_code == 200
    assert client.get("/api/projects/7/actions", params={"connectionId": cid}, headers=H).json()["actions"] == []


def test_create_rejects_an_unknown_selector(backend):
    app, store = backend
    _user(store, "dev", developer=True)
    cid = _conn(store, assignments=["dev"])
    client = TestClient(app)
    r = client.post(
        "/api/projects/7/actions",
        json={"connectionId": cid, "name": "bad", "spec": _spec(**{"from": {"selectors": ["SIDEWAYS"]}})},
        headers={"X-PMW-User": "dev"},
    )
    assert r.status_code == 400


def test_transition_table_accepts_all_metrics(backend):
    app, store = backend
    _user(store, "dev", developer=True)
    cid = _conn(store, assignments=["dev"])
    client = TestClient(app)
    spec = _spec(
        show={
            "kind": "transitionTable",
            "limit": 0,
            "metrics": ["COUNT", "%JOURNEY%", "%OUTGOING%", "AVG TIME", "MIN TIME", "MAX TIME", "STD DEV"],
            "forLast": None,
        }
    )
    r = client.post(
        "/api/projects/7/actions",
        json={"connectionId": cid, "name": "TT", "spec": spec},
        headers={"X-PMW-User": "dev"},
    )
    assert r.status_code == 200


def test_flowchart_action_saves_with_a_target(backend):
    app, store = backend
    _user(store, "dev", developer=True)
    cid = _conn(store, assignments=["dev"])
    client = TestClient(app)
    spec = _spec(
        show={"kind": "flowchart", "limit": 0, "metrics": [], "forLast": None},
        **{"from": {"selectors": []}},
    )
    spec["target"] = {"connection": "01 - Exasol Nano", "project": "Airport Passenger Flow Analysis"}
    r = client.post(
        "/api/projects/7/actions",
        json={"connectionId": cid, "name": "Cross map", "spec": spec},
        headers={"X-PMW-User": "dev"},
    )
    assert r.status_code == 200
    # Round-trips the target back on the saved action.
    assert r.json()["spec"]["target"]["project"] == "Airport Passenger Flow Analysis"


def test_flowchart_action_requires_a_target(backend):
    app, store = backend
    _user(store, "dev", developer=True)
    cid = _conn(store, assignments=["dev"])
    client = TestClient(app)
    spec = _spec(show={"kind": "flowchart", "limit": 0, "metrics": [], "forLast": None})
    # No target → 400.
    r = client.post(
        "/api/projects/7/actions",
        json={"connectionId": cid, "name": "bad", "spec": spec},
        headers={"X-PMW-User": "dev"},
    )
    assert r.status_code == 400


def test_transition_table_rejects_unknown_metric(backend):
    app, store = backend
    _user(store, "dev", developer=True)
    cid = _conn(store, assignments=["dev"])
    client = TestClient(app)
    spec = _spec(show={"kind": "transitionTable", "limit": 0, "metrics": ["BOGUS"], "forLast": None})
    r = client.post(
        "/api/projects/7/actions",
        json={"connectionId": cid, "name": "bad", "spec": spec},
        headers={"X-PMW-User": "dev"},
    )
    assert r.status_code == 400


def test_power_user_may_list_but_not_author(backend):
    app, store = backend
    _user(store, "pat", power=True)  # run-role, but not an author
    cid = _conn(store, assignments=["pat"])
    client = TestClient(app)
    H = {"X-PMW-User": "pat"}
    assert client.get("/api/projects/7/actions", params={"connectionId": cid}, headers=H).status_code == 200
    r = client.post(
        "/api/projects/7/actions",
        json={"connectionId": cid, "name": "x", "spec": _spec()},
        headers=H,
    )
    assert r.status_code == 403  # authoring is developer/admin only


def test_standard_user_cannot_even_list(backend):
    app, store = backend
    _user(store, "reg")  # no role → standard user
    cid = _conn(store, assignments=["reg"])
    client = TestClient(app)
    assert client.get(
        "/api/projects/7/actions", params={"connectionId": cid}, headers={"X-PMW-User": "reg"}
    ).status_code == 403


def test_idor_blocks_a_connection_not_assigned_to_the_caller(backend):
    app, store = backend
    _user(store, "dev", developer=True)  # assigned to nothing
    _user(store, "owner", developer=True)
    cid = _conn(store, assignments=["owner"])
    client = TestClient(app)
    assert client.get(
        "/api/projects/7/actions", params={"connectionId": cid}, headers={"X-PMW-User": "dev"}
    ).status_code == 403


def test_disabled_feature_forbids_everything(backend):
    app, store = backend
    store.set_actions_enabled(False)  # admin turned it off
    _user(store, "dev", developer=True)
    cid = _conn(store, assignments=["dev"])
    client = TestClient(app)
    assert client.get(
        "/api/projects/7/actions", params={"connectionId": cid}, headers={"X-PMW-User": "dev"}
    ).status_code == 403


def test_preview_sql_translates_the_spec(backend):
    app, store = backend
    _user(store, "dev", developer=True)
    cid = _conn(store, assignments=["dev"])
    client = TestClient(app)
    r = client.post(
        "/api/projects/7/actions/preview-sql",
        json={"connectionId": cid, "spec": _spec(), "contextNode": "PAYMENT", "resolvedSteps": ["PAYMENT"]},
        headers={"X-PMW-User": "dev"},
    )
    assert r.status_code == 200
    sql = r.json()["sql"]
    assert "STEP IN ('PAYMENT')" in sql and "LIMIT 3" in sql and "ORDER BY EVENT_TIME DESC" in sql


def test_run_requires_a_live_connection(backend):
    app, store = backend
    _user(store, "dev", developer=True)
    cid = _conn(store, assignments=["dev"])
    client = TestClient(app)
    # Not connected to any database ⇒ the run gate returns 409 before touching data.
    r = client.post(
        "/api/projects/7/actions/does-not-exist/run",
        json={"connectionId": cid, "filter": {}, "contextNode": "A", "resolvedSteps": ["A"]},
        headers={"X-PMW-User": "dev"},
    )
    assert r.status_code == 409
