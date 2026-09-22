"""Aggregates — collapse a connected set of steps into a Σ super-step.

Developer-only. Given a source project and a set of member steps, materialise:
  * a high-level project where each journey's member run is one Σ event, and
  * a detail project holding only the member steps' events (for drill-down),
into a chosen (possibly new) schema/connection, then record the Σ→detail link so the
app can offer drill-down.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..db.manager import DatabaseManager, current_db, current_user, friendly_error
from ..db.materialize import AggGroup, Target, materialize_aggregate, materialize_aggregate_set
from ..db.repository import ProcessRepository
from ..models import FilterSpec, SampleSet
from ..store.security import store as security_store

router = APIRouter(prefix="/api", tags=["aggregates"])


class _OutputTarget(BaseModel):
    name: str
    targetConnectionId: str = ""  # empty → the source connection
    targetSchema: str = ""  # empty → the target connection's own schema


class AggregateBody(BaseModel):
    connectionId: str  # source connection
    members: list[str]
    sigmaName: str = "Σ Aggregate"
    highLevel: _OutputTarget
    detail: _OutputTarget


# ── authorisation ────────────────────────────────────────────────────────────


def _require_developer() -> None:
    """Creating aggregates is limited to developers (and admins as superusers)."""
    username = current_user()
    user = security_store.get_user(username) if username else None
    if user is None or not user.is_enabled or not (user.is_admin or user.is_developer):
        raise HTTPException(
            status_code=403,
            detail="Designing aggregates is available to developers and administrators only.",
        )


def _require_assigned(connection_id: str) -> None:
    if not security_store.user_can_use((connection_id or "").strip(), current_user()):
        raise HTTPException(status_code=403, detail="This connection is not available to you.")


def _resolve(conn_id: str):
    conn = security_store.get_connection((conn_id or "").strip(), with_secrets=True)
    if conn is None:
        raise HTTPException(status_code=404, detail="Connection not found.")
    return conn


def _schema_of(body_schema: str, conn) -> str:
    schema = (body_schema or "").strip() or (conn.schema or "").strip()
    if not schema:
        raise HTTPException(status_code=400, detail="A target schema is required.")
    return schema


def _next_project_id_sync(connection, schema: str) -> int:
    """Next free SMALLINT PROJECT_ID on ``connection``'s ``schema`` (1 if PROJECTS is
    absent/empty). Runs in a worker thread — the driver calls are blocking."""
    from ..db.materialize import _open_conn
    from ..db.schema_ddl import _quote_ident

    raw, run = _open_conn(connection)
    try:
        try:
            run(f"OPEN SCHEMA {_quote_ident(schema)}")
            rows = run("SELECT COALESCE(MAX(PROJECT_ID), 0) FROM PROJECTS")
            mx = int(rows[0][0]) if rows and rows[0] and rows[0][0] is not None else 0
        except Exception:  # noqa: BLE001 — PROJECTS not provisioned yet → start at 1
            mx = 0
        return mx + 1
    finally:
        raw.close()


@router.post("/projects/{project_id}/aggregate")
async def create_aggregate(project_id: int, body: AggregateBody) -> dict[str, Any]:
    _require_developer()

    # The source and BOTH targets must be connections assigned to the caller (IDOR).
    _require_assigned(body.connectionId)
    hi_conn_id = (body.highLevel.targetConnectionId or body.connectionId).strip()
    det_conn_id = (body.detail.targetConnectionId or body.connectionId).strip()
    _require_assigned(hi_conn_id)
    _require_assigned(det_conn_id)

    members = {m.strip() for m in body.members if m and m.strip()}
    if len(members) < 2:
        raise HTTPException(status_code=400, detail="Select at least two connected steps to aggregate.")
    sigma = (body.sigmaName or "").strip() or "Σ Aggregate"
    if not body.highLevel.name.strip() or not body.detail.name.strip():
        raise HTTPException(status_code=400, detail="Both the high-level and detail project names are required.")

    src = _resolve(body.connectionId)
    hi_conn = _resolve(hi_conn_id)
    det_conn = _resolve(det_conn_id)

    # PROJECT_ID is a SMALLINT now: allocate the next free id on each target schema.
    # If the detail lands on the same connection+schema as the high-level, offset it by
    # one so the two don't collide. TITLE_SHORT marks the kind for the sidebar:
    # 'Σ…' = high-level (shown with a Σ badge), '#…' = detail (hidden until drilled).
    hi_schema = _schema_of(body.highLevel.targetSchema, hi_conn)
    det_schema = _schema_of(body.detail.targetSchema, det_conn)
    hi_id = await asyncio.to_thread(_next_project_id_sync, hi_conn, hi_schema)
    det_id = await asyncio.to_thread(_next_project_id_sync, det_conn, det_schema)
    if (det_conn.id, det_schema) == (hi_conn.id, hi_schema) and det_id == hi_id:
        det_id = hi_id + 1
    hi_pid, det_pid = hi_id, det_id
    hi_short, det_short = f"Σ{hi_id}", f"#{det_id}"

    try:
        await materialize_aggregate(
            source_connection=src,
            source_project_id=project_id,
            members=members,
            sigma=sigma,
            high_level=Target(hi_conn, hi_schema, True, hi_pid, body.highLevel.name.strip(), hi_short),
            detail=Target(det_conn, det_schema, True, det_pid, body.detail.name.strip(), det_short),
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 — a bad connection/schema is a 400, not a 500
        raise HTTPException(status_code=400, detail=f"Could not build the aggregate: {friendly_error(exc)}") from exc

    link = security_store.add_aggregate_link(
        {
            "connectionId": hi_conn.id,
            "projectId": hi_pid,
            "sigmaStep": sigma,
            "detailConnectionId": det_conn.id,
            "detailProjectId": det_pid,
        }
    )
    return {
        "highLevelProjectId": hi_pid,
        "highLevelConnectionId": hi_conn.id,
        "detailProjectId": det_pid,
        "detailConnectionId": det_conn.id,
        "sigmaStep": sigma,
        "link": link,
    }


class DrillBody(BaseModel):
    connectionId: str  # the high-level map's connection
    filter: FilterSpec = FilterSpec()  # the high-level view's current filter (date window etc.)


def _source_filter(f: FilterSpec) -> FilterSpec:
    """The subset of the high-level view's filter that maps IDENTICALLY onto the source
    project: the date window and META filters (both case-level, unaffected by aggregation).

    Everything else is deliberately dropped — the high-level map is a run-collapsed copy, so
    a journey's step count, total duration and score are all smaller there than in the
    original source. Carrying those bounds over would filter the source by measures it
    doesn't share, skewing the numbers (e.g. the high-level's shorter max-duration bound
    would wrongly exclude the source's longer journeys). Step-name filters (Σ …) don't exist
    in the source either."""
    return FilterSpec(
        fromDate=f.fromDate,
        toDate=f.toDate,
        meta1=f.meta1,
        meta2=f.meta2,
        meta3=f.meta3,
        sampleSet=SampleSet.original,
    )


async def _load_source_graph(conn, source_project_id: int, f: FilterSpec) -> tuple[Any, int]:
    """Load the ORIGINAL source project's process graph under the same (journey-level) filter
    as the high-level view, so the numbers match. Reuses the live session when it's already
    on that connection, else opens a headless one."""
    sf = _source_filter(f)
    active = current_db()
    if active.is_connected and active.active_profile_id == conn.id:
        r = ProcessRepository(active)
        r.active_sample_set = SampleSet.original
        return await r.load_graph(source_project_id, sf), await r.load_journey_count(source_project_id, sf)
    mgr = DatabaseManager(load_legacy_active=False)
    try:
        err = await mgr.connect_connection(conn)
        if err:
            raise HTTPException(status_code=400, detail=f"Could not open the source connection: {err}")
        r = ProcessRepository(mgr)
        r.active_sample_set = SampleSet.original
        return await r.load_graph(source_project_id, sf), await r.load_journey_count(source_project_id, sf)
    finally:
        await mgr.disconnect()


@router.post("/projects/{project_id}/aggregate-drill")
async def aggregate_drill(project_id: int, body: DrillBody) -> dict[str, Any]:
    """The ORIGINAL source project's process graph + each aggregate's member steps, so the
    app can expand a Σ node **in place** using the real, un-aggregated numbers (the same
    figures the non-aggregated flowchart shows). ``project_id`` is the high-level map."""
    _require_assigned(body.connectionId)
    aset = security_store.aggregate_set_by_high_level(body.connectionId, project_id)
    if aset is None:
        raise HTTPException(status_code=404, detail="No aggregate set found for this high-level map.")
    _require_assigned(aset["sourceConnectionId"])
    src = _resolve(aset["sourceConnectionId"])
    try:
        graph, journey_count = await _load_source_graph(src, aset["sourceProjectId"], body.filter)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Could not load the source map: {friendly_error(exc)}") from exc
    return {
        "graph": graph.model_dump(by_alias=True),
        "journeyCount": journey_count,
        "aggregates": [
            {"sigmaStep": a.get("sigmaStep", ""), "members": list(a.get("members") or [])}
            for a in (aset.get("aggregates") or [])
        ],
    }


@router.get("/projects/{project_id}/aggregates")
async def list_aggregates(project_id: int, connectionId: str = "") -> dict[str, Any]:
    """Aggregate links whose high-level project is this (connection, project) — feeds the
    app's Σ 'drill down'. Any user assigned to the connection may read them."""
    _require_assigned(connectionId)
    return {"aggregates": security_store.aggregates_for(connectionId, project_id)}


# ── multi-aggregate: one high-level map with several Σ steps, added to over time ──────


class _AggregateGroup(BaseModel):
    sigmaName: str = "Σ Aggregate"
    members: list[str]
    detail: _OutputTarget


class AggregateSetBody(BaseModel):
    connectionId: str  # source
    highLevel: _OutputTarget
    aggregates: list[_AggregateGroup]


class AddAggregatesBody(BaseModel):
    connectionId: str  # the HIGH-LEVEL connection (the set is identified by the HL project)
    aggregates: list[_AggregateGroup]


def _clean_members(raw: list[str]) -> set[str]:
    return {m.strip() for m in raw if m and m.strip()}


def _validate_groups(groups: list[_AggregateGroup], *, already: set[str]) -> list[set[str]]:
    """Each group needs ≥2 members and a name; member sets must be disjoint from each other
    and from ``already`` (steps used by existing aggregates on the same map)."""
    if not groups:
        raise HTTPException(status_code=400, detail="Add at least one aggregate.")
    seen = set(already)
    out: list[set[str]] = []
    for g in groups:
        members = _clean_members(g.members)
        if len(members) < 2:
            raise HTTPException(status_code=400, detail="Each aggregate needs at least two connected steps.")
        if not g.sigmaName.strip() or not g.detail.name.strip():
            raise HTTPException(status_code=400, detail="Every aggregate needs a Σ name and a detail project name.")
        clash = members & seen
        if clash:
            raise HTTPException(
                status_code=400,
                detail=f"A step can belong to only one aggregate — reused: {', '.join(sorted(clash))}.",
            )
        seen |= members
        out.append(members)
    return out


def _link_record(hi_conn_id: str, hi_pid: str, sigma: str, det_conn_id: str, det_pid: str) -> dict:
    return {
        "connectionId": hi_conn_id,
        "projectId": hi_pid,
        "sigmaStep": sigma,
        "detailConnectionId": det_conn_id,
        "detailProjectId": det_pid,
    }


@router.post("/projects/{project_id}/aggregate-set")
async def create_aggregate_set(project_id: int, body: AggregateSetBody) -> dict[str, Any]:
    """Create ONE high-level map for the source ``project_id`` collapsing several aggregate
    groups (a Σ step each), plus one detail project per group (each to its own target)."""
    _require_developer()
    _require_assigned(body.connectionId)

    if security_store.aggregate_set_by_source(body.connectionId, project_id) is not None:
        raise HTTPException(
            status_code=409,
            detail="This project already has a high-level map — add aggregates to it instead.",
        )
    if not body.highLevel.name.strip():
        raise HTTPException(status_code=400, detail="A high-level project name is required.")

    member_sets = _validate_groups(body.aggregates, already=set())

    src = _resolve(body.connectionId)
    hi_conn_id = (body.highLevel.targetConnectionId or body.connectionId).strip()
    _require_assigned(hi_conn_id)
    hi_conn = _resolve(hi_conn_id)

    # PROJECT_ID is a SMALLINT: allocate a unique next-free id per (connection, schema),
    # offsetting when several outputs land on the same schema. TITLE_SHORT marks the kind
    # ('Σ…' high-level, '#…' detail).
    allocated: dict[tuple[str, str], int] = {}

    async def _alloc(conn, schema: str) -> int:
        key = (conn.id, schema)
        if key in allocated:
            allocated[key] += 1
        else:
            allocated[key] = await asyncio.to_thread(_next_project_id_sync, conn, schema)
        return allocated[key]

    hi_schema = _schema_of(body.highLevel.targetSchema, hi_conn)
    hi_pid = await _alloc(hi_conn, hi_schema)
    hi_target = Target(hi_conn, hi_schema, True, hi_pid, body.highLevel.name.strip(), f"Σ{hi_pid}")

    groups: list[AggGroup] = []
    details: list[tuple[Target, frozenset[str]]] = []
    stored_aggs: list[dict] = []
    for g, members in zip(body.aggregates, member_sets):
        det_conn_id = (g.detail.targetConnectionId or body.connectionId).strip()
        _require_assigned(det_conn_id)
        det_conn = _resolve(det_conn_id)
        det_schema = _schema_of(g.detail.targetSchema, det_conn)
        det_pid = await _alloc(det_conn, det_schema)
        sigma = g.sigmaName.strip()
        groups.append(AggGroup(frozenset(members), sigma))
        details.append((Target(det_conn, det_schema, True, det_pid, g.detail.name.strip(), f"#{det_pid}"), frozenset(members)))
        stored_aggs.append({
            "sigmaStep": sigma, "members": sorted(members),
            "detailConnectionId": det_conn.id, "detailProjectId": det_pid,
            "detailSchema": det_schema, "detailTitle": g.detail.name.strip(),
        })

    try:
        await materialize_aggregate_set(
            source_connection=src, source_project_id=project_id,
            groups=groups, high_level=hi_target, details=details,
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Could not build the aggregates: {friendly_error(exc)}") from exc

    security_store.save_aggregate_set({
        "sourceConnectionId": body.connectionId, "sourceProjectId": project_id,
        "highLevelConnectionId": hi_conn.id, "highLevelProjectId": hi_pid,
        "highLevelSchema": hi_target.schema, "highLevelTitle": hi_target.title,
        "aggregates": stored_aggs,
    })
    for a in stored_aggs:
        security_store.add_aggregate_link(
            _link_record(hi_conn.id, hi_pid, a["sigmaStep"], a["detailConnectionId"], a["detailProjectId"])
        )
    return {
        "highLevelProjectId": hi_pid, "highLevelConnectionId": hi_conn.id,
        "aggregates": stored_aggs,
    }


@router.post("/projects/{project_id}/aggregate-set/add")
async def add_to_aggregate_set(project_id: int, body: AddAggregatesBody) -> dict[str, Any]:
    """Add one or more aggregates to the existing high-level map ``project_id`` (on
    ``connectionId``). Re-collapses the SOURCE with the union of all groups so the map stays
    one project, and writes only the new detail projects."""
    _require_developer()
    _require_assigned(body.connectionId)

    aset = security_store.aggregate_set_by_high_level(body.connectionId, project_id)
    if aset is None:
        raise HTTPException(status_code=404, detail="No aggregate set found for this high-level map.")

    existing = aset.get("aggregates") or []
    existing_members: set[str] = set()
    for a in existing:
        existing_members |= _clean_members(a.get("members") or [])
    new_member_sets = _validate_groups(body.aggregates, already=existing_members)

    src = _resolve(aset["sourceConnectionId"])
    _require_assigned(aset["sourceConnectionId"])
    hi_conn = _resolve(aset["highLevelConnectionId"])
    hi_pid = aset["highLevelProjectId"]
    hi_target = Target(hi_conn, aset["highLevelSchema"], True, hi_pid, aset["highLevelTitle"], f"Σ{hi_pid}")

    # New detail projects need fresh SMALLINT ids per (connection, schema).
    allocated: dict[tuple[str, str], int] = {}

    async def _alloc(conn, schema: str) -> int:
        key = (conn.id, schema)
        if key in allocated:
            allocated[key] += 1
        else:
            allocated[key] = await asyncio.to_thread(_next_project_id_sync, conn, schema)
        return allocated[key]

    # All groups (existing + new) drive the high-level collapse; only new details are written.
    groups: list[AggGroup] = [AggGroup(frozenset(_clean_members(a.get("members") or [])), a["sigmaStep"]) for a in existing]
    details: list[tuple[Target, frozenset[str]]] = []
    new_aggs: list[dict] = []
    for g, members in zip(body.aggregates, new_member_sets):
        det_conn_id = (g.detail.targetConnectionId or aset["sourceConnectionId"]).strip()
        _require_assigned(det_conn_id)
        det_conn = _resolve(det_conn_id)
        det_schema = _schema_of(g.detail.targetSchema, det_conn)
        det_pid = await _alloc(det_conn, det_schema)
        sigma = g.sigmaName.strip()
        groups.append(AggGroup(frozenset(members), sigma))
        details.append((Target(det_conn, det_schema, True, det_pid, g.detail.name.strip(), f"#{det_pid}"), frozenset(members)))
        new_aggs.append({
            "sigmaStep": sigma, "members": sorted(members),
            "detailConnectionId": det_conn.id, "detailProjectId": det_pid,
            "detailSchema": det_schema, "detailTitle": g.detail.name.strip(),
        })

    try:
        await materialize_aggregate_set(
            source_connection=src, source_project_id=aset["sourceProjectId"],
            groups=groups, high_level=hi_target, details=details,
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Could not add the aggregates: {friendly_error(exc)}") from exc

    aset["aggregates"] = existing + new_aggs
    security_store.save_aggregate_set(aset)
    for a in new_aggs:
        security_store.add_aggregate_link(
            _link_record(hi_conn.id, aset["highLevelProjectId"], a["sigmaStep"], a["detailConnectionId"], a["detailProjectId"])
        )
    return {
        "highLevelProjectId": aset["highLevelProjectId"], "highLevelConnectionId": hi_conn.id,
        "aggregates": new_aggs,
    }
