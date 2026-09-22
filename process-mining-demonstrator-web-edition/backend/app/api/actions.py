"""Actions — saved, business-readable node-menu actions and their execution.

An action is authored on the Actions surface in a small DSL (parsed client-side to
the ``spec`` below), stored per (connection, project), and run from a node's context
menu in the app. The backend never receives raw SQL: it rebuilds a safe Exasol query
from the stored spec + the run-time context (the clicked node's resolved neighbour
set) + the chart's current FilterSpec, reusing repository.load_log_entries /
load_transitions.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..db.manager import DatabaseManager, current_db, current_user
from ..db.repository import ProcessRepository
from ..models import FilterSpec, SampleSet
from ..store.security import store as security_store
from .projects import repo, require_connection

router = APIRouter(prefix="/api", tags=["actions"])

ALLOWED_SELECTORS = {"THIS", "PREVIOUS", "FOLLOWING", "ALL_FOLLOWING", "ALL_PREVIOUS"}
# The transition-table metrics — the same set the chart offers (canonical tokens).
ALLOWED_METRICS = {"COUNT", "%JOURNEY%", "%OUTGOING%", "AVG TIME", "MIN TIME", "MAX TIME", "STD DEV"}

# Map a canonical action metric token → the flowchart's TransitionMetric label (the
# names the front-end FlowChart understands for switching the edge metric).
_FLOWCHART_METRIC_LABEL = {
    "COUNT": "Count",
    "%JOURNEY%": "Journey %",
    "%OUTGOING%": "Percentage",
    "AVG TIME": "Avg Time",
    "MIN TIME": "Min Time",
    "MAX TIME": "Max Time",
    "STD DEV": "Std Dev",
}


# ── spec model (mirrors src/actions/types.ts ActionSpec) ─────────────────────


class _FromModel(BaseModel):
    selectors: list[str] = []


class _ShowModel(BaseModel):
    kind: Literal["logEntries", "transitionTable", "flowchart"]
    limit: int = 1
    metrics: list[str] = []
    forLast: int | None = None


class _AvailabilityModel(BaseModel):
    allNodes: bool = False
    steps: list[str] = []


class _WhereModel(BaseModel):
    field: Literal["EVENT_ID"]
    op: Literal["in"]
    values: list[str] = []


class _TargetModel(BaseModel):
    connection: str = ""
    project: str = ""


class ActionSpecModel(BaseModel):
    availability: _AvailabilityModel
    show: _ShowModel
    from_: _FromModel = Field(alias="from")
    target: _TargetModel | None = None
    sort: Literal["ASC", "DESC"] | None = None
    where: _WhereModel | None = None

    model_config = {"populate_by_name": True}

    def validated(self) -> "ActionSpecModel":
        bad = [s for s in self.from_.selectors if s not in ALLOWED_SELECTORS]
        if bad:
            raise ValueError(f"Unknown node selector(s): {', '.join(bad)}")
        if self.show.kind == "transitionTable":
            bad_m = [m for m in self.show.metrics if m not in ALLOWED_METRICS]
            if bad_m:
                raise ValueError(f"Unknown transition metric(s): {', '.join(bad_m)}")
        if self.show.kind == "flowchart":
            if self.target is None or not self.target.connection.strip() or not self.target.project.strip():
                raise ValueError('SHOW FLOWCHART needs a FROM "<connection>::<project>" target.')
            bad_m = [m for m in self.show.metrics if m not in ALLOWED_METRICS]
            if bad_m:
                raise ValueError(f"Unknown flowchart metric(s): {', '.join(bad_m)}")
        return self


class ActionSaveBody(BaseModel):
    connectionId: str
    name: str = ""
    script: str = ""
    spec: ActionSpecModel
    enabled: bool = True


class ActionRunBody(BaseModel):
    connectionId: str
    filter: FilterSpec = FilterSpec()
    contextNode: str = ""
    resolvedSteps: list[str] = []


class ActionPreviewBody(ActionRunBody):
    spec: ActionSpecModel


# ── authorisation ────────────────────────────────────────────────────────────


def _require_actions_enabled() -> None:
    if not security_store.actions_enabled:
        raise HTTPException(status_code=403, detail="The Actions feature is disabled.")


def _require_run_role() -> None:
    """Running an action is open to every signed-in user except a plain standard
    user — i.e. power users, developers and admins."""
    username = current_user()
    user = security_store.get_user(username) if username else None
    if user is None or not user.is_enabled or not (
        user.is_admin or user.is_power or user.is_developer
    ):
        raise HTTPException(
            status_code=403,
            detail="Actions are available to power users, developers and administrators.",
        )


def _require_author_role() -> None:
    """Authoring actions is limited to developers and administrators."""
    username = current_user()
    user = security_store.get_user(username) if username else None
    if user is None or not user.is_enabled or not (user.is_admin or user.is_developer):
        raise HTTPException(
            status_code=403,
            detail="Actions are authored by developers and administrators only.",
        )


def _require_assigned_connection(connection_id: str) -> None:
    """The caller must be assigned to this connection — actions are keyed by
    (connection, project), so without this a role-holder could reach another
    customer's actions/data by passing its id (a cross-tenant IDOR)."""
    if not security_store.user_can_use((connection_id or "").strip(), current_user()):
        raise HTTPException(status_code=403, detail="This connection is not available to you.")


def _public_action(a: dict) -> dict:
    return {
        "id": a.get("id"),
        "name": a.get("name") or "",
        "script": a.get("script") or "",
        "spec": a.get("spec") or {},
        "enabled": bool(a.get("enabled", True)),
    }


# ── CRUD ─────────────────────────────────────────────────────────────────────


@router.get("/projects/{project_id}/actions")
async def list_actions(project_id: int, connectionId: str = "") -> dict[str, Any]:
    """The saved actions for this (connection, project). Available to any run-role
    user assigned to the connection — the app lists them in node context menus."""
    _require_actions_enabled()
    _require_run_role()
    _require_assigned_connection(connectionId)
    return {"actions": [_public_action(a) for a in security_store.actions_for(connectionId, project_id)]}


@router.post("/projects/{project_id}/actions")
async def create_action(project_id: int, body: ActionSaveBody) -> dict[str, Any]:
    _require_actions_enabled()
    _require_author_role()
    _require_assigned_connection(body.connectionId)
    try:
        spec = body.spec.validated()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    saved = security_store.upsert_action(
        body.connectionId,
        project_id,
        {
            "id": uuid.uuid4().hex,
            "name": body.name,
            "script": body.script,
            "spec": spec.model_dump(by_alias=True),
            "enabled": body.enabled,
            "author": current_user() or "",
        },
    )
    return _public_action(saved)


@router.put("/projects/{project_id}/actions/{action_id}")
async def update_action(project_id: int, action_id: str, body: ActionSaveBody) -> dict[str, Any]:
    _require_actions_enabled()
    _require_author_role()
    _require_assigned_connection(body.connectionId)
    existing = security_store.action_by_id(body.connectionId, project_id, action_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Action not found.")
    try:
        spec = body.spec.validated()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    saved = security_store.upsert_action(
        body.connectionId,
        project_id,
        {
            "id": action_id,
            "name": body.name,
            "script": body.script,
            "spec": spec.model_dump(by_alias=True),
            "enabled": body.enabled,
            "author": existing.get("author") or current_user() or "",
        },
    )
    return _public_action(saved)


@router.delete("/projects/{project_id}/actions/{action_id}")
async def delete_action(project_id: int, action_id: str, connectionId: str = "") -> dict[str, bool]:
    _require_actions_enabled()
    _require_author_role()
    _require_assigned_connection(connectionId)
    security_store.delete_action(connectionId, project_id, action_id)
    return {"ok": True}


# ── run ──────────────────────────────────────────────────────────────────────


async def _flowchart_from_repo(
    r: ProcessRepository,
    project_name: str,
    date_filter: FilterSpec,
    conn_name: str,
    metrics: list[str] | None = None,
) -> dict[str, Any]:
    """Resolve `project_name` (a title, or an id) on the repository's connection and load
    its process map + journey count, scoped to the given (date-only) filter."""
    projects = await r.load_projects()
    proj = (
        next((p for p in projects if p.title.strip() == project_name), None)
        or next((p for p in projects if p.title.strip().lower() == project_name.lower()), None)
        or next((p for p in projects if p.projectId == project_name), None)
    )
    if proj is None:
        raise HTTPException(status_code=404, detail=f'Project "{project_name}" not found on "{conn_name}".')
    graph = await r.load_graph(proj.projectId, date_filter)
    journey_count = await r.load_journey_count(proj.projectId, date_filter)
    date_scoped = True
    if journey_count == 0:
        # The source project's date window need not overlap the target project's data, so
        # a date-scoped query can come back empty. Fall back to the target's FULL range so
        # the map is never blank; the response flags that the date filter was dropped.
        full = FilterSpec(sampleSet=date_filter.sampleSet)
        full_graph = await r.load_graph(proj.projectId, full)
        full_count = await r.load_journey_count(proj.projectId, full)
        if full_count > 0:
            graph, journey_count, date_scoped = full_graph, full_count, False
    # Which edge metrics the panel may switch between (SHOW FLOWCHART … FOR …). Map the
    # canonical tokens to the FlowChart labels, dedup, and default to Count.
    labels: list[str] = []
    for tok in metrics or []:
        label = _FLOWCHART_METRIC_LABEL.get(tok)
        if label and label not in labels:
            labels.append(label)
    if not labels:
        labels = ["Count"]
    return {
        "kind": "flowchart",
        "columns": [],
        "rows": [],
        "graph": graph.model_dump(by_alias=True),
        "journeyCount": journey_count,
        "metric": labels[0],
        "metrics": labels,
        "title": proj.title or proj.projectId,
        "dateScoped": date_scoped,
    }


async def _run_flowchart(spec: ActionSpecModel, f: FilterSpec) -> dict[str, Any]:
    """SHOW FLOWCHART … FROM <connection>::<project>: load another project's process map,
    scoped to the current date range only. Reuses the live session when the target is the
    connection the user is already on, otherwise opens a dedicated headless session."""
    user = current_user()
    conn_name = (spec.target.connection if spec.target else "").strip()
    project_name = (spec.target.project if spec.target else "").strip()

    # Resolve the connection by name — only among the connections assigned to the caller.
    assigned = [c for c in security_store.list_connections() if security_store.user_can_use(c.id, user)]
    match = next((c for c in assigned if (c.name or "").strip() == conn_name), None) or next(
        (c for c in assigned if (c.name or "").strip().lower() == conn_name.lower()), None
    )
    if match is None:
        raise HTTPException(status_code=404, detail=f'Connection "{conn_name}" is not available to you.')

    # Full flowchart, limited to the current date window (all other filters are dropped —
    # the target project has its own steps). Always the ORIGINAL sample set: the source
    # chart's sample selection is meaningless for a different project, and the target may
    # only have original data.
    date_filter = FilterSpec(fromDate=f.fromDate, toDate=f.toDate, sampleSet=SampleSet.original)

    active = current_db()
    if active.is_connected and active.active_profile_id == match.id:
        r = ProcessRepository(active)
        r.active_sample_set = SampleSet.original
        return await _flowchart_from_repo(r, project_name, date_filter, conn_name, spec.show.metrics)

    # A different connection than the live session — open a disposable headless one.
    conn = security_store.get_connection(match.id, with_secrets=True)
    if conn is None:
        raise HTTPException(status_code=404, detail=f'Connection "{conn_name}" is not available to you.')
    mgr = DatabaseManager(load_legacy_active=False)
    try:
        err = await mgr.connect_connection(conn)
        if err:
            raise HTTPException(status_code=400, detail=f'Could not open "{conn_name}": {err}')
        r = ProcessRepository(mgr)
        r.active_sample_set = SampleSet.original
        return await _flowchart_from_repo(r, project_name, date_filter, conn_name, spec.show.metrics)
    finally:
        await mgr.disconnect()


async def _execute(project_id: int, spec: ActionSpecModel, body: ActionRunBody) -> dict[str, Any]:
    f = body.filter

    if spec.show.kind == "flowchart":
        return await _run_flowchart(spec, f)

    r = repo(f.sampleSet)
    steps = list(dict.fromkeys(s for s in body.resolvedSteps if s))  # dedupe, keep order

    if spec.show.kind == "logEntries":
        event_ids = spec.where.values if (spec.where and spec.where.field == "EVENT_ID") else None
        result = await r.load_log_entries(
            project_id,
            steps,
            f,
            event_ids=event_ids,
            limit=spec.show.limit,
            descending=spec.sort != "ASC",  # default DESC (most recent first)
        )
        return {
            "kind": "logEntries",
            "columns": result["columns"],
            "rows": result["rows"],
            "nodeCount": len(steps),
        }

    # transitionTable — transitions leaving the selected node set, guided by the filter.
    transitions = await r.load_transitions(project_id, f)
    selected = set(steps)
    picked = [t for t in transitions if t.fromStep in selected] if selected else []
    metrics = spec.show.metrics or ["COUNT"]

    # Journey total (denominator for %JOURNEY%) and per-source outgoing totals (for
    # %OUTGOING%) — computed once, only when the metric is actually requested.
    journey_count = await r.load_journey_count(project_id, f) if "%JOURNEY%" in metrics else 0
    out_totals: dict[str, int] = {}
    if "%OUTGOING%" in metrics:
        for t in transitions:  # over the whole DFG, not just the picked edges
            out_totals[t.fromStep] = out_totals.get(t.fromStep, 0) + t.occurrences

    def _round(v: float | None) -> float | None:
        return round(v, 1) if v is not None else None

    def _cell(t: Any, m: str) -> Any:
        if m == "COUNT":
            return t.occurrences
        if m == "%JOURNEY%":
            return round(t.occurrences / journey_count * 100, 1) if journey_count else None
        if m == "%OUTGOING%":
            total = out_totals.get(t.fromStep, 0)
            return round(t.occurrences / total * 100, 1) if total else None
        if m == "AVG TIME":
            return _round(t.avgSecs)
        if m == "MIN TIME":
            return _round(t.minSecs)
        if m == "MAX TIME":
            return _round(t.maxSecs)
        if m == "STD DEV":
            return _round(t.stdDevSecs)
        return None

    columns = ["FROM", "TO", *metrics]
    rows: list[list[Any]] = [
        [t.fromStep, t.toStep, *(_cell(t, m) for m in metrics)] for t in picked
    ]
    # Sort by the first metric column, descending (numeric values first).
    rows.sort(key=lambda x: x[2] if isinstance(x[2], (int, float)) else float("-inf"), reverse=True)
    return {"kind": "transitionTable", "columns": columns, "rows": rows, "nodeCount": len(steps)}


@router.post("/projects/{project_id}/actions/{action_id}/run")
async def run_action(project_id: int, action_id: str, body: ActionRunBody) -> dict[str, Any]:
    """Run a saved action against the connected database, scoped to the clicked
    node's resolved neighbour set and the chart's current filter."""
    _require_actions_enabled()
    _require_run_role()
    _require_assigned_connection(body.connectionId)
    require_connection()
    action = security_store.action_by_id(body.connectionId, project_id, action_id)
    if action is None or not action.get("enabled", True):
        raise HTTPException(status_code=404, detail="Action not found.")
    spec = ActionSpecModel.model_validate(action.get("spec") or {})
    return await _execute(project_id, spec, body)


@router.post("/projects/{project_id}/actions/preview-run")
async def preview_run_action(project_id: int, body: ActionPreviewBody) -> dict[str, Any]:
    """Run an unsaved spec — the Actions builder's Test panel. Author-role only."""
    _require_actions_enabled()
    _require_author_role()
    _require_assigned_connection(body.connectionId)
    require_connection()
    try:
        spec = body.spec.validated()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return await _execute(project_id, spec, body)


@router.post("/projects/{project_id}/actions/preview-sql")
async def preview_sql(project_id: int, body: ActionPreviewBody) -> dict[str, str]:
    """The Exasol SQL a spec would run — shown in the builder so authors can see the
    translation. Builds the string only (no execution), so it works without a live
    connection; an empty node set yields a placeholder."""
    _require_actions_enabled()
    _require_author_role()
    _require_assigned_connection(body.connectionId)
    try:
        spec = body.spec.validated()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    f = body.filter
    if spec.show.kind == "flowchart":
        tgt = spec.target
        where = f"{tgt.connection} :: {tgt.project}" if tgt else "(target)"
        return {
            "sql": (
                f"-- Loads the full process map of {where}\n"
                "-- in a separate panel, scoped to the chart's current date range.\n"
                "-- (No single query — the whole project's directly-follows graph is built.)"
            )
        }
    r = repo(f.sampleSet)
    steps = list(dict.fromkeys(s for s in body.resolvedSteps if s))
    if spec.show.kind == "logEntries":
        if not steps:
            return {"sql": "-- Select a node to preview the query for its resolved scope."}
        event_ids = spec.where.values if (spec.where and spec.where.field == "EVENT_ID") else None
        sql = r._log_entries_sql(
            project_id, steps, f, event_ids=event_ids, limit=spec.show.limit, descending=spec.sort != "ASC"
        )
        return {"sql": sql.strip()}
    filters = r._all_filters(project_id, f, date_only=False)
    return {"sql": r._live_transitions_sql(project_id, filters).strip()}
