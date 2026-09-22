"""MCP server — JSON-RPC dispatch, auth guardrails and the read-only tool wiring.

The module lives outside the `app` package (mcp/server.py, a sibling surface), so it is
loaded by path. Auth and DB access are exercised with monkeypatched store methods — no
Authentik and no Exasol needed.
"""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
from datetime import datetime
from types import SimpleNamespace

import pytest

_PATH = Path(__file__).resolve().parents[2] / "mcp" / "server.py"
_spec = importlib.util.spec_from_file_location("mcp_server", _PATH)
mcp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mcp)


def _run(coro):
    return asyncio.run(coro)


class _Req:
    """Minimal stand-in for a Starlette Request (only what _authenticate reads)."""

    def __init__(self, headers=None):
        self.headers = headers or {}
        self.base_url = "https://host:8493/"


USER = SimpleNamespace(username="alice", is_enabled=True)


# ── JSON-RPC dispatch (no user/DB needed) ─────────────────────────────────────


def test_initialize_reports_capabilities_and_server_info():
    out = _run(mcp._dispatch({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}, USER))
    assert out["result"]["serverInfo"]["name"] == "process-mining"
    assert "tools" in out["result"]["capabilities"]


def test_tools_list_exposes_the_read_only_tools():
    out = _run(mcp._dispatch({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, USER))
    names = {t["name"] for t in out["result"]["tools"]}
    assert {"list_connections", "get_process_map", "get_variants", "get_metadata"} <= names
    # Every tool advertises an object input schema.
    assert all(t["inputSchema"]["type"] == "object" for t in out["result"]["tools"])


def test_notification_returns_no_response():
    assert _run(mcp._dispatch({"jsonrpc": "2.0", "method": "notifications/initialized"}, USER)) is None


def test_unknown_method_and_unknown_tool_are_errors():
    m = _run(mcp._dispatch({"jsonrpc": "2.0", "id": 3, "method": "does/not/exist"}, USER))
    assert m["error"]["code"] == -32601
    t = _run(mcp._dispatch(
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "nope"}}, USER))
    assert t["error"]["code"] == -32602


def test_tools_call_list_connections(monkeypatch):
    conns = [SimpleNamespace(id="c1", name="Prod", schema="PM", comment="")]
    monkeypatch.setattr(mcp.store, "connections_for_user", lambda username: conns)
    out = _run(mcp._dispatch(
        {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
         "params": {"name": "list_connections", "arguments": {}}}, USER))
    assert out["result"]["isError"] is False
    import json
    payload = json.loads(out["result"]["content"][0]["text"])
    assert payload == [{"id": "c1", "name": "Prod", "schema": "PM", "comment": ""}]


# ── filter helpers ────────────────────────────────────────────────────────────


def test_filter_spec_builds_from_arguments():
    spec = mcp._filter_spec({"sampleSet": "SAMPLE_1", "includedSteps": ["A"], "meta1": "x"})
    assert spec.sampleSet.value == "SAMPLE_1"
    assert spec.includedSteps == ["A"] and spec.meta1 == "x"


def test_bad_sample_set_is_a_tool_error():
    with pytest.raises(mcp.ToolError):
        mcp._sample_of({"sampleSet": "BOGUS"})


# ── authentication guardrails ─────────────────────────────────────────────────


def test_auth_requires_configured_oauth(monkeypatch):
    monkeypatch.setattr(mcp.store, "mcp_settings", lambda: {
        "issuer": "", "jwksUri": "", "audience": "", "requiredGroup": "", "usernameClaim": "preferred_username"})
    with pytest.raises(mcp.AuthError) as ei:
        _run(mcp._authenticate(_Req()))
    assert ei.value.status == 503


def test_auth_challenges_when_no_bearer(monkeypatch):
    monkeypatch.setattr(mcp.store, "mcp_settings", lambda: {
        "issuer": "https://a/", "jwksUri": "https://a/jwks", "audience": "",
        "requiredGroup": "", "usernameClaim": "preferred_username"})
    with pytest.raises(mcp.AuthError) as ei:
        _run(mcp._authenticate(_Req(headers={})))
    assert ei.value.status == 401 and ei.value.challenge is True


# ── list_projects across connections, with counts ─────────────────────────────


class _FakeRepo:
    """Stands in for ProcessRepository for the two tools that only read projects."""

    def __init__(self, projects, counts=None):
        self._projects, self._counts = projects, counts or {}

    async def load_projects(self):
        return list(self._projects)

    async def load_journey_count(self, project_id, spec):
        return self._counts.get(str(project_id), 0)


def _patch_repo(monkeypatch, repos: dict):
    """Map connection id -> _FakeRepo (or an Exception to raise on open)."""

    class _Ctx:
        def __init__(self, username, connection_id, sample):
            self.connection_id = connection_id

        async def __aenter__(self):
            found = repos[self.connection_id]
            if isinstance(found, Exception):
                raise found
            return found

        async def __aexit__(self, *exc):
            return None

    monkeypatch.setattr(mcp, "_Repo", _Ctx)


def _call(name, arguments, user=USER):
    """Returns (result, payload) — payload is the decoded JSON, or the error text
    when the tool reported isError (that content is a message, not JSON)."""
    import json

    out = _run(mcp._dispatch(
        {"jsonrpc": "2.0", "id": 9, "method": "tools/call",
         "params": {"name": name, "arguments": arguments}}, user))
    result = out["result"]
    text = result["content"][0]["text"]
    return result, (text if result["isError"] else json.loads(text))


def test_tools_list_exposes_find_journeys_and_an_optional_connection_id():
    out = _run(mcp._dispatch({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, USER))
    tools = {t["name"]: t for t in out["result"]["tools"]}
    assert "find_journeys" in tools
    # list_projects now spans connections, so connectionId is no longer required.
    assert "required" not in tools["list_projects"]
    assert "includeCounts" in tools["list_projects"]["inputSchema"]["properties"]


def test_list_projects_spans_every_connection_and_tags_each_project(monkeypatch):
    monkeypatch.setattr(mcp.store, "connections_for_user", lambda username: [
        SimpleNamespace(id="c1", name="Air Travel", schema="PM", comment=""),
        SimpleNamespace(id="c2", name="Sandbox", schema="PM_S", comment=""),
    ])
    _patch_repo(monkeypatch, {
        "c1": _FakeRepo([{"projectId": 1, "title": "Flights"}], {"1": 500}),
        "c2": _FakeRepo([{"projectId": 2, "title": "Agents"}], {"2": 17}),
    })
    _, payload = _call("list_projects", {"includeCounts": True})
    assert [(p["connectionName"], p["title"], p["journeyCount"]) for p in payload] == [
        ("Air Travel", "Flights", 500), ("Sandbox", "Agents", 17)]


def test_list_projects_omits_counts_unless_asked(monkeypatch):
    monkeypatch.setattr(mcp.store, "connections_for_user", lambda username: [
        SimpleNamespace(id="c1", name="Air Travel", schema="PM", comment="")])
    _patch_repo(monkeypatch, {"c1": _FakeRepo([{"projectId": 1, "title": "Flights"}])})
    _, payload = _call("list_projects", {})
    assert "journeyCount" not in payload[0] and payload[0]["connectionId"] == "c1"


def test_list_projects_degrades_one_unreachable_connection(monkeypatch):
    monkeypatch.setattr(mcp.store, "connections_for_user", lambda username: [
        SimpleNamespace(id="c1", name="Air Travel", schema="PM", comment=""),
        SimpleNamespace(id="c2", name="Offline", schema="PM_S", comment=""),
    ])
    _patch_repo(monkeypatch, {
        "c1": _FakeRepo([{"projectId": 1, "title": "Flights"}]),
        "c2": mcp.ToolError("Could not open the database connection: timeout"),
    })
    result, payload = _call("list_projects", {})
    # The reachable connection still answers; the broken one reports itself.
    assert result["isError"] is False
    assert payload[0]["title"] == "Flights"
    assert payload[1]["connectionName"] == "Offline" and "timeout" in payload[1]["error"]


def test_list_projects_rejects_a_connection_not_assigned_to_the_user(monkeypatch):
    monkeypatch.setattr(mcp.store, "connections_for_user", lambda username: [
        SimpleNamespace(id="c1", name="Air Travel", schema="PM", comment="")])
    result, message = _call("list_projects", {"connectionId": "c9"})
    assert result["isError"] is True and "not assigned to you" in message


# ── find_journeys ─────────────────────────────────────────────────────────────


class _JourneyRepo:
    def __init__(self):
        self.kwargs = None

    async def load_journeys(self, project_id, spec, **kwargs):
        self.kwargs = kwargs
        return [{
            "eventId": "8c46773b2f8e81d3627fd7e43b14192e",
            "startDate": datetime(2024, 4, 21, 4, 36, 9),
            "endDate": datetime(2024, 4, 21, 4, 55, 3),
            "durationSecs": 1134.0, "stepCount": 5,
            "meta1": "Manage Booking", "meta2": "ANA", "meta3": "No Payment",
            "path": None,
        }]

    async def load_meta_titles(self, project_id):
        return ("Journey Type", "Airline", "Payment Method")


def test_find_journeys_labels_meta_by_title_and_returns_ids_get_journey_accepts(monkeypatch):
    repo = _JourneyRepo()
    _patch_repo(monkeypatch, {"c1": repo})
    _, payload = _call("find_journeys", {"connectionId": "c1", "projectId": 1})
    assert payload[0]["meta"]["Airline"] == "ANA"
    assert payload[0]["eventId"] == "8c46773b2f8e81d3627fd7e43b14192e"
    assert payload[0]["durationSecs"] == 1134.0
    assert "path" not in payload[0]  # omitted rather than null when not requested
    # Defaults: slowest first, a small page.
    assert repo.kwargs["order_by"] == "DURATION_DESC" and repo.kwargs["limit"] == 20


def test_find_journeys_passes_bounds_through_and_caps_the_limit(monkeypatch):
    repo = _JourneyRepo()
    _patch_repo(monkeypatch, {"c1": repo})
    _call("find_journeys", {"connectionId": "c1", "projectId": 1, "limit": 99_999,
                            "minDurationSecs": 600, "minSteps": 3, "includePath": True,
                            "orderBy": "STEPS_DESC"})
    assert repo.kwargs["limit"] == mcp.MCP_MAX_ROWS
    assert repo.kwargs["min_duration_secs"] == 600 and repo.kwargs["min_steps"] == 3
    assert repo.kwargs["include_path"] is True and repo.kwargs["order_by"] == "STEPS_DESC"


def test_find_journeys_rejects_an_unknown_order(monkeypatch):
    _patch_repo(monkeypatch, {"c1": _JourneyRepo()})
    result, message = _call("find_journeys", {"connectionId": "c1", "projectId": 1,
                                              "orderBy": "COST_DESC"})
    assert result["isError"] is True and "Unknown orderBy" in message
