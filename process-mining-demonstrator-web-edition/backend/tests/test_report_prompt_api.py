"""App-backend report-prompt endpoints: role-gated editing of the per-(connection,
project) report analysis prompt (the same mapping the admin Reporting tab manages)."""

from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def backend(tmp_path, monkeypatch):
    """A TestClient over the compute backend, wired to a throwaway security store."""
    monkeypatch.setenv("PMW_DATA_DIR", str(tmp_path))
    import app.config as config

    importlib.reload(config)
    import app.store.crypto as crypto

    importlib.reload(crypto)
    import app.services.certs  # noqa: F401 — reloaded transitively by security

    import app.store.security as security_mod

    importlib.reload(security_mod)
    import app.db.manager as manager

    importlib.reload(manager)
    import app.api.connections as connections_api

    importlib.reload(connections_api)
    import app.api.features as features_api

    importlib.reload(features_api)
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
    """A connection assigned to the given users; returns its id."""
    return store.upsert_connection({
        "name": "Cust", "host": "db.example.com", "port": 8563, "username": "svc",
        "schema": "MINING", "password": "s3cret", "llmURL": "", "llmModel": "", "llmKey": "",
        "assignments": assignments,
    }).id


def test_power_user_can_edit_prompt_per_connection_and_project(backend):
    app, store = backend
    _user(store, "pat", power=True)
    cid = _conn(store, assignments=["pat"])
    client = TestClient(app)
    H = {"X-PMW-User": "pat"}

    # None configured yet → empty.
    r = client.get("/api/projects/7/report-prompt", params={"connectionId": cid}, headers=H)
    assert r.status_code == 200 and r.json() == {"prompt": ""}

    # Save, then read back — keyed by BOTH connection and project.
    r = client.put(
        "/api/projects/7/report-prompt",
        json={"connectionId": cid, "prompt": "Find the outliers"},
        headers=H,
    )
    assert r.status_code == 200 and r.json()["prompt"] == "Find the outliers"
    assert store.report_prompt_for(cid, 7) == "Find the outliers"

    # Empty prompt clears the mapping.
    client.put("/api/projects/7/report-prompt", json={"connectionId": cid, "prompt": ""}, headers=H)
    assert store.report_prompt_for(cid, 7) is None


def test_developer_can_edit_prompt(backend):
    app, store = backend
    _user(store, "dev", developer=True)
    cid = _conn(store, assignments=["dev"])
    client = TestClient(app)
    r = client.put(
        "/api/projects/7/report-prompt",
        json={"connectionId": cid, "prompt": "Developer prompt"},
        headers={"X-PMW-User": "dev"},
    )
    assert r.status_code == 200 and store.report_prompt_for(cid, 7) == "Developer prompt"


def test_cannot_reach_a_connection_not_assigned_to_the_caller(backend):
    """The IDOR guard: a role-holder may not read or write the prompt of a connection
    they are not assigned to — even with a valid power/developer role."""
    app, store = backend
    _user(store, "pat", power=True)  # assigned to conn A only
    _user(store, "eve", power=True)  # assigned to nothing
    cid = _conn(store, assignments=["pat"])
    client = TestClient(app)

    # eve (power, but not assigned) cannot read or write conn A's prompt.
    assert client.get(
        "/api/projects/7/report-prompt", params={"connectionId": cid}, headers={"X-PMW-User": "eve"}
    ).status_code == 403
    assert client.put(
        "/api/projects/7/report-prompt",
        json={"connectionId": cid, "prompt": "pwned"},
        headers={"X-PMW-User": "eve"},
    ).status_code == 403
    assert store.report_prompt_for(cid, 7) is None


def test_regular_user_is_forbidden(backend):
    app, store = backend
    _user(store, "reg")  # neither power, developer nor admin
    cid = _conn(store, assignments=["reg"])
    client = TestClient(app)
    H = {"X-PMW-User": "reg"}
    assert client.get("/api/projects/7/report-prompt", params={"connectionId": cid}, headers=H).status_code == 403
    assert client.put(
        "/api/projects/7/report-prompt",
        json={"connectionId": cid, "prompt": "nope"},
        headers=H,
    ).status_code == 403
    assert store.report_prompt_for(cid, 7) is None


def test_no_user_is_forbidden(backend):
    app, _ = backend
    client = TestClient(app)  # no X-PMW-User header → sign-in disabled → refused
    assert client.get("/api/projects/7/report-prompt", params={"connectionId": "c1"}).status_code == 403
