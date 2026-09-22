"""Compute-backend connection API tests — per-user filtering and the connect gate.

Drives the real backend FastAPI app (`app.main`) with an isolated security store.
The GUI proxy injects a trusted ``X-PMW-User`` header after validating the session;
these tests supply that header directly and confirm the backend only exposes and
connects the connections assigned to that user. The actual Exasol connect is
stubbed so no database is needed.
"""

from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def backend(tmp_path, monkeypatch):
    """A TestClient over the compute backend, wired to a throwaway security store."""
    monkeypatch.setenv("PMW_DATA_DIR", str(tmp_path))

    # Reload the config + security stack, then the app modules that bind to them.
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
    import app.main as main

    importlib.reload(main)

    return main.app, security_mod.store, manager.db


def _make_conn(store, **overrides):
    data = {
        "name": "Prod",
        "host": "db.example.com",
        "port": 8563,
        "username": "svc",
        "schema": "MINING",
        "password": "s3cret",
        "llmURL": "https://llm.example.com/v1",
        "llmModel": "gpt-4o",
        "llmKey": "sk-abc",
        "assignments": ["alice"],
    }
    data.update(overrides)
    return store.upsert_connection(data)


# ── Listing / per-user filtering ──────────────────────────────────────────────


def test_list_returns_only_assigned_and_strips_secrets(backend):
    app, store, _ = backend
    store.create_user("alice", "pw", is_admin=False)
    store.create_user("bob", "pw", is_admin=False)
    conn = _make_conn(store, assignments=["alice"])
    client = TestClient(app)

    alice = client.get("/api/connections", headers={"X-PMW-User": "alice"}).json()
    assert [c["id"] for c in alice] == [conn.id]
    # user_public exposes no secrets and no assignment list.
    entry = alice[0]
    assert entry["hasLLM"] is True and entry["llmURL"] == "https://llm.example.com/v1"
    assert "password" not in entry and "assignments" not in entry
    assert "s3cret" not in str(entry) and "sk-abc" not in str(entry)

    # bob has nothing assigned.
    assert client.get("/api/connections", headers={"X-PMW-User": "bob"}).json() == []


def test_list_without_user_header_returns_all(backend):
    app, store, _ = backend
    store.create_user("alice", "pw", is_admin=False)
    conn = _make_conn(store, assignments=["alice"])
    client = TestClient(app)
    # No header ⇒ sign-in disabled ⇒ every connection is visible.
    listed = client.get("/api/connections").json()
    assert [c["id"] for c in listed] == [conn.id]


# ── End-user launch page: /api/portal ─────────────────────────────────────────


def test_portal_groups_the_users_processes_by_connection(backend, monkeypatch):
    import app.db.schema_ddl as schema_ddl

    app, store, _ = backend
    store.create_user("alice", "pw", is_admin=False)
    store.create_user("bob", "pw", is_admin=False)
    a1 = _make_conn(store, name="Prod", schema="MINING", assignments=["alice"])
    a2 = _make_conn(store, name="Sandbox", schema="SBX", assignments=["alice"])
    _make_conn(store, name="Bob only", assignments=["bob"])  # must not leak to alice

    async def fake_counts(**kwargs):
        # A distinct project list per schema; the SBX schema fails to read.
        if kwargs["schema"] == "MINING":
            return {"ok": True, "error": None, "projects": [
                {"projectId": 1, "title": "Bookstore", "titleShort": "BOOK",
                 "journeys": 10, "events": 40, "lastEventAt": "2026-09-14T10:00:00"},
            ]}
        return {"ok": False, "error": "schema unreachable", "projects": []}

    monkeypatch.setattr(schema_ddl, "list_projects_with_counts", fake_counts)

    data = TestClient(app).get("/api/portal", headers={"X-PMW-User": "alice"}).json()
    groups = {g["name"]: g for g in data["connections"]}
    # Only alice's two connections; bob's is absent.
    assert set(groups) == {"Prod", "Sandbox"}
    assert groups["Prod"]["projects"][0]["title"] == "Bookstore"
    assert groups["Prod"]["error"] is None
    # A connection that can't be read yields a per-group error, never a 500.
    assert groups["Sandbox"]["projects"] == []
    assert groups["Sandbox"]["error"] == "schema unreachable"


def test_portal_is_empty_for_a_user_with_no_connections(backend):
    app, store, _ = backend
    store.create_user("carol", "pw", is_admin=False)
    data = TestClient(app).get("/api/portal", headers={"X-PMW-User": "carol"}).json()
    assert data == {"connections": []}


# ── Connect authorization gate ────────────────────────────────────────────────


def test_connect_forbidden_for_unassigned_user(backend):
    app, store, db = backend
    store.create_user("alice", "pw", is_admin=False)
    store.create_user("bob", "pw", is_admin=False)
    conn = _make_conn(store, assignments=["alice"])
    client = TestClient(app)

    called = False

    async def _fake_connect(conn_def):
        nonlocal called
        called = True
        return None

    db.connect_connection = _fake_connect  # type: ignore[method-assign]

    resp = client.post(
        f"/api/connections/{conn.id}/connect", headers={"X-PMW-User": "bob"}
    )
    assert resp.status_code == 403
    assert called is False  # the gate short-circuits before any DB work


def test_connect_allowed_for_assigned_user(backend, monkeypatch):
    import app.db.manager as manager

    app, store, _ = backend
    store.create_user("alice", "pw", is_admin=False)
    conn = _make_conn(store, assignments=["alice"])
    client = TestClient(app)

    received: dict = {}

    async def _fake_connect(self, conn_def):  # patched on the class → per-user managers
        received["id"] = conn_def.id
        received["password"] = conn_def.password  # backend receives decrypted secret
        self.is_connected = True
        self.is_llm_reachable = True
        self.active_profile_id = conn_def.id
        return None

    monkeypatch.setattr(manager.DatabaseManager, "connect_connection", _fake_connect)

    resp = client.post(
        f"/api/connections/{conn.id}/connect", headers={"X-PMW-User": "alice"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["isConnected"] is True
    assert body["activeProfileId"] == conn.id
    assert received == {"id": conn.id, "password": "s3cret"}


def test_connections_are_isolated_per_user(backend, monkeypatch):
    """Once alice connects, bob (a different user) does NOT see her live session —
    the core fix for cross-user data exposure."""
    import app.db.manager as manager

    app, store, _ = backend
    store.create_user("alice", "pw", is_admin=False)
    store.create_user("bob", "pw", is_admin=False)
    conn = _make_conn(store, assignments=["alice", "bob"])
    client = TestClient(app)

    async def _fake_connect(self, conn_def):
        self.is_connected = True
        self.active_profile_id = conn_def.id
        return None

    monkeypatch.setattr(manager.DatabaseManager, "connect_connection", _fake_connect)

    # alice connects.
    assert (
        client.post(
            f"/api/connections/{conn.id}/connect", headers={"X-PMW-User": "alice"}
        ).json()["isConnected"]
        is True
    )

    # bob, who never connected, sees no connection (would be True with a shared global).
    bob = client.get("/api/connection/status", headers={"X-PMW-User": "bob"}).json()
    assert bob["isConnected"] is False and bob["activeProfileId"] is None
    # alice still has hers.
    alice = client.get("/api/connection/status", headers={"X-PMW-User": "alice"}).json()
    assert alice["isConnected"] is True and alice["activeProfileId"] == conn.id


def test_connect_missing_connection_is_404(backend):
    app, store, db = backend
    client = TestClient(app)
    # No user header ⇒ open access passes the gate, but the id does not exist.
    resp = client.post("/api/connections/does-not-exist/connect")
    assert resp.status_code == 404


# ── power users: manage & assign connections from the app ─────────────────────


def _power(store, username="pat"):
    store.create_user(username, "pw", is_admin=False)
    store.set_power(username, True)
    return username


def _developer(store, username="dev"):
    store.create_user(username, "pw", is_admin=False)
    store.set_developer(username, True)
    return username


def test_manageable_requires_power(backend):
    app, store, _ = backend
    store.create_user("alice", "pw", is_admin=False)
    client = TestClient(app)
    # A plain user cannot reach the management surface.
    assert (
        client.get(
            "/api/connections/manageable", headers={"X-PMW-User": "alice"}
        ).status_code
        == 403
    )
    assert (
        client.get(
            "/api/assignable-users", headers={"X-PMW-User": "alice"}
        ).status_code
        == 403
    )


def test_power_creates_owns_and_autoassigns(backend):
    app, store, _ = backend
    pat = _power(store)
    store.create_user("bob", "pw", is_admin=False)
    client = TestClient(app)

    resp = client.post(
        "/api/connections",
        headers={"X-PMW-User": pat},
        json={
            "name": "Pat's DB",
            "host": "db",
            "port": 8563,
            "username": "svc",
            "schema": "S",
            "password": "s3cret",
            "assignments": ["bob"],
        },
    )
    assert resp.status_code == 200
    created = resp.json()
    assert created["owner"] == pat
    # The creator is auto-assigned so they can use the connection immediately.
    assert set(created["assignments"]) == {pat, "bob"}
    assert "s3cret" not in str(created) and created["hasPassword"] is True

    # It shows up in the owner's manageable list, and the owner can connect to it.
    manageable = client.get(
        "/api/connections/manageable", headers={"X-PMW-User": pat}
    ).json()
    assert [c["id"] for c in manageable] == [created["id"]]
    assigned = client.get("/api/connections", headers={"X-PMW-User": pat}).json()
    assert created["id"] in [c["id"] for c in assigned]


def test_power_cannot_edit_or_delete_others_connection(backend):
    app, store, _ = backend
    pat = _power(store)
    quinn = _power(store, "quinn")
    # A connection owned by quinn.
    conn = _make_conn(store, owner="quinn", assignments=["quinn"])
    client = TestClient(app)

    # pat may not edit quinn's connection…
    edit = client.post(
        "/api/connections",
        headers={"X-PMW-User": pat},
        json={"id": conn.id, "name": "hijack", "host": "x"},
    )
    assert edit.status_code == 403
    # …nor delete it…
    assert (
        client.delete(
            f"/api/connections/{conn.id}", headers={"X-PMW-User": pat}
        ).status_code
        == 403
    )
    # …nor re-assign it.
    assert (
        client.post(
            f"/api/connections/{conn.id}/assignments",
            headers={"X-PMW-User": pat},
            json={"assignments": ["pat"]},
        ).status_code
        == 403
    )
    # pat's manageable list stays empty.
    assert (
        client.get(
            "/api/connections/manageable", headers={"X-PMW-User": pat}
        ).json()
        == []
    )


def test_admin_manages_all_connections(backend):
    app, store, _ = backend
    store.create_user("admin", "pw", is_admin=True)
    pat = _power(store)
    conn = _make_conn(store, owner=pat, assignments=[pat])
    client = TestClient(app)

    # An admin sees every connection in the management surface…
    manageable = client.get(
        "/api/connections/manageable", headers={"X-PMW-User": "admin"}
    ).json()
    assert conn.id in [c["id"] for c in manageable]
    # …and may edit one they do not own.
    resp = client.post(
        "/api/connections",
        headers={"X-PMW-User": "admin"},
        json={"id": conn.id, "name": "renamed", "host": conn.host},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "renamed"
    # Ownership is immutable across an edit.
    assert store.get_connection(conn.id).owner == pat


def test_power_edit_and_delete_own_connection(backend):
    app, store, db = backend
    pat = _power(store)
    client = TestClient(app)
    created = client.post(
        "/api/connections",
        headers={"X-PMW-User": pat},
        json={"name": "mine", "host": "db"},
    ).json()

    # Edit keeps ownership and applies the change.
    edited = client.post(
        "/api/connections",
        headers={"X-PMW-User": pat},
        json={"id": created["id"], "name": "mine-2", "host": "db2"},
    ).json()
    assert edited["owner"] == pat and edited["name"] == "mine-2"

    # Delete removes it from the owner's manageable list.
    assert (
        client.delete(
            f"/api/connections/{created['id']}", headers={"X-PMW-User": pat}
        ).status_code
        == 200
    )
    assert (
        client.get(
            "/api/connections/manageable", headers={"X-PMW-User": pat}
        ).json()
        == []
    )


def test_assignable_users_lists_only_enabled(backend):
    app, store, _ = backend
    pat = _power(store)
    store.create_user("bob", "pw", is_admin=False)
    store.create_user("carol", "pw", is_admin=False)
    store.set_enabled("carol", False)
    client = TestClient(app)

    users = client.get(
        "/api/assignable-users", headers={"X-PMW-User": pat}
    ).json()
    assert "bob" in users and pat in users and "carol" not in users


# ── Schema provisioning (power) ───────────────────────────────────────────────


def test_provision_schema_requires_power(backend):
    app, store, _ = backend
    store.create_user("alice", "pw", is_admin=False)
    client = TestClient(app)
    resp = client.post(
        "/api/connections/provision-schema",
        headers={"X-PMW-User": "alice"},
        json={"host": "db", "schema": "PM"},
    )
    assert resp.status_code == 403


def test_provision_schema_power_user_invokes_provisioner(backend, monkeypatch):
    app, store, _ = backend
    pat = _power(store)
    import app.db.schema_ddl as ddl

    seen: dict = {}

    async def _fake(**kwargs):
        seen.update(kwargs)
        return {"ok": True, "error": None, "created": ["schema PM", "PROJECTS", "NOTES"]}

    monkeypatch.setattr(ddl, "provision_process_mining_schema", _fake)
    client = TestClient(app)
    resp = client.post(
        "/api/connections/provision-schema",
        headers={"X-PMW-User": pat},
        json={"host": "db", "port": 8563, "username": "u", "password": "pw", "schema": "PM"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["created"] == ["schema PM", "PROJECTS", "NOTES"]
    # The entered credentials + schema reach the provisioner.
    assert seen["schema"] == "PM" and seen["host"] == "db" and seen["password"] == "pw"


# ── Demo content generation (power) ───────────────────────────────────────────


def test_generate_demo_requires_power(backend):
    app, store, _ = backend
    store.create_user("alice", "pw", is_admin=False)
    client = TestClient(app)
    resp = client.post(
        "/api/connections/generate-demo",
        headers={"X-PMW-User": "alice"},
        json={"host": "db", "schema": "PM", "journeys": 100},
    )
    assert resp.status_code == 403


def test_generate_demo_power_user_invokes_generator(backend, monkeypatch):
    app, store, _ = backend
    pat = _power(store)
    import app.db.demo_data as demo

    seen: dict = {}

    async def _fake(**kwargs):
        seen.update(kwargs)
        return {"ok": True, "error": None, "journeys": kwargs["journeys"], "project": "x"}

    monkeypatch.setattr(demo, "generate_demo_content", _fake)
    client = TestClient(app)

    # Default dataset is retail.
    resp = client.post(
        "/api/connections/generate-demo",
        headers={"X-PMW-User": pat},
        json={"host": "db", "username": "u", "password": "pw", "schema": "PM", "journeys": 250},
    )
    assert resp.status_code == 200 and resp.json()["journeys"] == 250
    assert seen["dataset"] == "retail" and seen["schema"] == "PM" and seen["journeys"] == 250

    # The finance dataset is selectable.
    resp = client.post(
        "/api/connections/generate-demo",
        headers={"X-PMW-User": pat},
        json={"host": "db", "password": "pw", "schema": "PM", "journeys": 100, "dataset": "finance"},
    )
    assert resp.status_code == 200 and seen["dataset"] == "finance"

    # …and the transportation (flight booking) dataset.
    resp = client.post(
        "/api/connections/generate-demo",
        headers={"X-PMW-User": pat},
        json={"host": "db", "password": "pw", "schema": "PM", "journeys": 50, "dataset": "transportation"},
    )
    assert resp.status_code == 200 and seen["dataset"] == "transportation"


def test_legacy_db_password_endpoint_is_removed(backend):
    """The plaintext-password disclosure route must no longer exist (any authed
    user could previously read a stored DB password from the legacy store)."""
    app, _, _ = backend
    client = TestClient(app)
    resp = client.get("/api/servers/db/anything/password")
    assert resp.status_code == 404  # route gone
    # The route table itself carries no such path.
    paths = {r.path for r in app.routes if hasattr(r, "path")}
    assert "/api/servers/db/{server_id}/password" not in paths


def test_settings_are_isolated_per_user(backend):
    """App preferences are namespaced per user — one user's /settings never leak
    into another's, and a fresh user starts empty."""
    app, _, _ = backend
    client = TestClient(app)

    client.patch(
        "/api/settings", json={"values": {"kpi.order": "a,b,c"}},
        headers={"X-PMW-User": "alice"},
    )
    client.patch(
        "/api/settings", json={"values": {"kpi.order": "x,y,z"}},
        headers={"X-PMW-User": "bob"},
    )

    alice = client.get("/api/settings", headers={"X-PMW-User": "alice"}).json()
    bob = client.get("/api/settings", headers={"X-PMW-User": "bob"}).json()
    assert alice.get("kpi.order") == "a,b,c"
    assert bob.get("kpi.order") == "x,y,z"

    # A user who never saved anything sees nothing (fresh on first access).
    carol = client.get("/api/settings", headers={"X-PMW-User": "carol"}).json()
    assert "kpi.order" not in carol


def test_reassignment_disconnects_live_sessions(backend, monkeypatch):
    """Revoking/altering an assignment must drop live sessions immediately so a
    user whose access was removed can't keep querying through a stale connection."""
    import app.db.manager as manager

    app, store, _ = backend
    pat = _power(store)
    store.create_user("bob", "pw", is_admin=False)
    conn = _make_conn(store, owner=pat, assignments=[pat, "bob"])

    calls: list[str] = []

    async def _rec(conn_id):
        calls.append(conn_id)

    monkeypatch.setattr(manager.registry, "disconnect_connection", _rec)
    client = TestClient(app)

    r = client.post(
        f"/api/connections/{conn.id}/assignments",
        headers={"X-PMW-User": pat},
        json={"assignments": [pat]},  # bob revoked
    )
    assert r.status_code == 200
    assert calls == [conn.id]


def test_editing_connection_disconnects_live_sessions(backend, monkeypatch):
    import app.db.manager as manager

    app, store, _ = backend
    pat = _power(store)
    conn = _make_conn(store, owner=pat, assignments=[pat])

    calls: list[str] = []

    async def _rec(conn_id):
        calls.append(conn_id)

    monkeypatch.setattr(manager.registry, "disconnect_connection", _rec)
    client = TestClient(app)

    r = client.post(
        "/api/connections",
        headers={"X-PMW-User": pat},
        json={
            "id": conn.id,
            "name": "Pat's DB (moved)",
            "host": "new-host",  # host change → live sessions must be dropped
            "port": 8563,
            "username": "svc",
            "schema": "S",
            "assignments": [pat],
        },
    )
    assert r.status_code == 200
    assert calls == [conn.id]


def test_sampling_guard_requires_power_role(backend):
    """Journey sampling is restricted to power users and admins; a regular user (or
    no signed-in identity) is refused at the backend, not just hidden in the UI."""
    import importlib

    import app.api.features as features
    import app.db.manager as manager
    from fastapi import HTTPException

    _, store, _ = backend
    importlib.reload(features)  # bind to the fixture's reloaded manager + security store

    store.create_user("reg", "pw", is_admin=False)
    store.create_user("power_u", "pw", is_admin=False)
    store.set_power("power_u", True)
    store.create_user("adm", "pw", is_admin=True)

    def guard(username):
        tok = manager.set_current_user(username)
        try:
            features._require_power()
        finally:
            manager.reset_current_user(tok)

    for blocked in ("reg", None):  # regular user and sign-in-disabled both refused
        with pytest.raises(HTTPException) as ei:
            guard(blocked)
        assert ei.value.status_code == 403
    guard("power_u")  # power user — no raise
    guard("adm")  # admin — no raise


def test_registry_lowercases_username(backend):
    """A username arriving in varying case maps to ONE manager/Exasol session."""
    import app.db.manager as manager

    reg = manager.ConnectionRegistry()
    assert reg.for_user("Alice") is reg.for_user("alice")
    assert reg.for_user("BOB") is reg.for_user("bob")
    assert reg.for_user("Alice") is not reg.for_user("bob")


def test_registry_does_not_merge_unicode_distinct_users(backend):
    """ASCII-only lowercasing must match the store's SQLite LOWER() identity — a
    Unicode casefold would map store-DISTINCT names (e.g. 'ß'→'ss') onto one
    manager, sharing an Exasol session across users (cross-user data leak)."""
    import app.db.manager as manager

    reg = manager.ConnectionRegistry()
    # 'ßuser'.casefold() == 'ssuser', but SQLite LOWER keeps them distinct accounts.
    assert reg.for_user("ßuser") is not reg.for_user("ssuser")
    # Kelvin sign (U+212A) lower()s to 'k' but is a distinct account under LOWER().
    assert reg.for_user("Kelvin") is not reg.for_user("kelvin")


def test_registry_connect_aborts_on_concurrent_revocation(backend, monkeypatch):
    """If the connection is revoked (edited/deleted) while its open is in flight,
    the freshly-opened session is dropped and an error returned — closing the race
    where disconnect_connection snapshots the manager before its session exists."""
    import asyncio

    import app.db.manager as manager

    reg = manager.ConnectionRegistry()

    class _ConnDef:
        id = "c-1"
        password = "x"

    dropped = {"n": 0}

    async def _fake_connect(self, conn_def):
        # An admin revokes THIS connection mid-open (before active_profile_id is set,
        # so the snapshot in disconnect_connection can't see this manager yet).
        await reg.disconnect_connection(conn_def.id)
        self.is_connected = True
        self.active_profile_id = conn_def.id
        return None

    async def _fake_disconnect(self):
        dropped["n"] += 1
        self.is_connected = False

    monkeypatch.setattr(manager.DatabaseManager, "connect_connection", _fake_connect)
    monkeypatch.setattr(manager.DatabaseManager, "disconnect", _fake_disconnect)

    err = asyncio.run(reg.connect("alice", _ConnDef()))
    assert err is not None and "reconnect" in err.lower()
    assert dropped["n"] >= 1  # the session opened during the revocation was dropped


# ── project management (power / developer / admin) ────────────────────────────


def test_developer_manages_projects_on_owned_connection(backend, monkeypatch):
    """A developer owns the connections they create and may list/delete their
    projects — the endpoints connect via the stored credentials (stubbed here)."""
    app, store, _ = backend
    dev = _developer(store)
    client = TestClient(app)

    created = client.post(
        "/api/connections",
        headers={"X-PMW-User": dev},
        json={"name": "Dev DB", "host": "db", "port": 8563, "username": "svc",
              "schema": "S", "password": "s3cret"},
    ).json()
    assert created["owner"] == dev  # developer-owned → manageable

    import app.db.schema_ddl as ddl

    async def _fake_list(**kw):
        assert kw["schema"] == "S" and kw["password"] == "s3cret"
        return {"ok": True, "error": None,
                "projects": [{"projectId": 1, "title": "Proj 1", "journeys": 3, "events": 9}]}

    async def _fake_delete(**kw):
        assert kw["project_id"] == 1
        return {"ok": True, "error": None, "events": 9, "journeys": 3, "tables": ["JOURNEYS", "PROJECTS"]}

    monkeypatch.setattr(ddl, "list_projects_with_counts", _fake_list)
    monkeypatch.setattr(ddl, "delete_project", _fake_delete)

    listed = client.get(f"/api/connections/{created['id']}/projects", headers={"X-PMW-User": dev})
    assert listed.status_code == 200
    assert listed.json()["projects"][0]["projectId"] == 1

    deleted = client.post(
        f"/api/connections/{created['id']}/projects/delete",
        headers={"X-PMW-User": dev}, json={"projectId": 1},
    )
    assert deleted.status_code == 200 and deleted.json()["events"] == 9


def test_projects_forbidden_for_non_manager_or_non_owner(backend):
    app, store, _ = backend
    _developer(store, "dev")
    store.create_user("alice", "pw", is_admin=False)  # plain user
    conn = _make_conn(store, owner="someone-else", assignments=["alice"])
    client = TestClient(app)

    # A plain user is not a manager at all.
    assert client.get(
        f"/api/connections/{conn.id}/projects", headers={"X-PMW-User": "alice"}
    ).status_code == 403
    # A developer who doesn't OWN this connection can't manage its projects.
    assert client.get(
        f"/api/connections/{conn.id}/projects", headers={"X-PMW-User": "dev"}
    ).status_code == 403
    assert client.post(
        f"/api/connections/{conn.id}/projects/delete",
        headers={"X-PMW-User": "dev"}, json={"projectId": 1},
    ).status_code == 403
