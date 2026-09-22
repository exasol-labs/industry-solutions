"""Connection endpoints — list/connect the admin-defined connections assigned to a
user, power-user connection management, schema provisioning and demo generation."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .. import log_events as logx
from ..db.manager import check_llm_reachable, current_db, registry
from ..models import ConnectionStatus, LLMServer
from ..services import llm as llm_service
from ..store.security import store as security_store

router = APIRouter(prefix="/api", tags=["connections"])

# The GUI proxy injects the signed-in user here after validating the session; the
# backend trusts it for per-user connection filtering. When absent (sign-in not
# required), the user is unknown and every connection is visible.
USER_HEADER = "x-pmw-user"


def _request_user(request: Request) -> str | None:
    value = request.headers.get(USER_HEADER)
    return value.strip() if value and value.strip() else None


# ── admin-defined connections (assigned per user) ─────────────────────────────


@router.get("/connections")
def list_connections(request: Request) -> list[dict]:
    """Connections assigned to the signed-in user (secrets stripped)."""
    user = _request_user(request)
    # The exact connections chosen for each aggregate role. A connection is marked when it
    # IS an aggregate output (high-level or detail); it is *hideable* only when it is a
    # detail target and is neither a source nor a high-level connection — mirroring "a
    # high-level map is always visible; details may be hidden". Matching is by connection
    # id (not host/schema), so a normal connection to the same database/schema as a detail
    # project is never wrongly hidden.
    roles = security_store.aggregate_connection_roles()
    keep = roles["source"] | roles["high"]
    out: list[dict] = []
    for c in security_store.connections_for_user(user):
        d = c.user_public()
        d["hasAggregates"] = c.id in roles["high"] or c.id in roles["detail"]
        d["aggregateDetailOnly"] = c.id in roles["detail"] and c.id not in keep
        out.append(d)
    return out


@router.get("/portal")
async def portal_processes(request: Request) -> dict:
    """Every process (project) available to the signed-in user, grouped by the connection
    it lives in — powers the end-user launch page (/home). Assignment is the gate (exactly
    like /connect), so a plain user sees only their assigned connections. Fully
    failure-tolerant: a connection whose schema can't be read yields an ``error`` on that
    group, never a 500."""
    from ..db.schema_ddl import list_projects_with_counts

    user = _request_user(request)
    groups: list[dict] = []
    for c in security_store.connections_for_user(user):
        group = {"id": c.id, "name": c.name, "schema": c.schema, "projects": [], "error": None}
        conn = security_store.get_connection(c.id, with_secrets=True)
        if conn is None:
            group["error"] = "Connection not found."
            groups.append(group)
            continue
        result = await list_projects_with_counts(
            host=conn.host, port=conn.port, username=conn.username, password=conn.password,
            schema=conn.schema, use_tls=conn.use_tls, cert_mode=conn.cert_mode,
            fingerprint=conn.fingerprint, min_rsa_bits=conn.min_rsa_bits,
        )
        if result.get("ok"):
            group["projects"] = result.get("projects", [])
        else:
            group["error"] = result.get("error") or "Could not read the database."
        groups.append(group)
    return {"connections": groups}


@router.post("/connections/{conn_id}/connect", response_model=ConnectionStatus)
async def connect_connection(conn_id: str, request: Request) -> ConnectionStatus:
    user = _request_user(request)
    if not security_store.user_can_use(conn_id, user):
        raise HTTPException(status_code=403, detail="This connection is not available to you.")
    conn_def = security_store.get_connection(conn_id, with_secrets=True)
    if conn_def is None:
        raise HTTPException(status_code=404, detail="Connection not found.")
    mgr = current_db()  # this user's own connection
    # Route through the registry so a concurrent admin edit/delete of this
    # connection during the (slow) open aborts the freshly-opened session.
    error = await registry.connect(user, conn_def)
    return ConnectionStatus(
        isConnected=mgr.is_connected,
        isLLMReachable=mgr.is_llm_reachable,
        activeProfileId=mgr.active_profile_id,
        username=mgr.username,
        lastError=error,
    )


# ── power users: create & manage their own connections from the app ───────────
#
# A user with the 'power' role (or an admin) may define connections and assign
# them from the main application. Ownership is enforced: a power user manages only
# the connections they created; an admin manages all. The GUI proxy injects the
# trusted X-PMW-User header the checks below rely on.


def _request_user_obj(request: Request):
    username = _request_user(request)
    return security_store.get_user(username) if username else None


def _require_manager(request: Request):
    """A user allowed to manage connections from the app: an admin, a power user, or a
    developer. Ownership is still enforced per-connection by can_manage_connection."""
    user = _request_user_obj(request)
    if user is None or not user.is_enabled or not (
        user.is_admin or user.is_power or user.is_developer
    ):
        raise HTTPException(
            status_code=403, detail="You are not allowed to manage connections."
        )
    return user


class ManagedConnectionBody(BaseModel):
    id: str | None = None
    name: str
    comment: str = ""
    host: str = ""
    port: int = 8563
    username: str = ""
    schema_: str = Field(default="", alias="schema")
    useTLS: bool = False
    certModeRaw: str = "verify"
    fingerprint: str = ""
    minRSAKeySizeBits: int = 2048
    password: str | None = None  # omit to keep, "" to clear, value to set
    llmURL: str = ""
    llmModel: str = ""
    llmKey: str | None = None
    assignments: list[str] = []

    model_config = {"populate_by_name": True}


class ManagedAssignmentsBody(BaseModel):
    assignments: list[str]


class ManagedConnectionTestBody(BaseModel):
    host: str
    port: int = 8563
    username: str = ""
    password: str = ""
    schema_: str = Field(default="", alias="schema")
    useTLS: bool = False
    certModeRaw: str = "verify"
    fingerprint: str = ""
    minRSAKeySizeBits: int = 2048
    llmURL: str = ""
    llmKey: str = ""

    model_config = {"populate_by_name": True}


def _managed_payload(body: ManagedConnectionBody) -> dict:
    data: dict = {
        "id": body.id,
        "name": body.name,
        "comment": body.comment,
        "host": body.host,
        "port": body.port,
        "username": body.username,
        "schema": body.schema_,
        "useTLS": body.useTLS,
        "certModeRaw": body.certModeRaw,
        "fingerprint": body.fingerprint,
        "minRSAKeySizeBits": body.minRSAKeySizeBits,
        "llmURL": body.llmURL,
        "llmModel": body.llmModel,
        "assignments": body.assignments,
    }
    if body.password is not None:
        data["password"] = body.password
    if body.llmKey is not None:
        data["llmKey"] = body.llmKey
    return data


@router.get("/connections/manageable")
def list_manageable_connections(request: Request) -> list[dict]:
    """Connections the signed-in power user (or admin) may create / edit / assign."""
    user = _require_manager(request)
    conns = (
        security_store.list_connections()
        if user.is_admin
        else security_store.connections_owned_by(user.username)
    )
    return [c.admin_public() for c in conns]


@router.get("/assignable-users")
def list_assignable_users(request: Request) -> list[str]:
    """Enabled usernames a power user can assign a connection to."""
    _require_manager(request)
    return [u.username for u in security_store.list_users() if u.is_enabled]


@router.post("/connections")
async def upsert_managed_connection(body: ManagedConnectionBody, request: Request) -> dict:
    user = _require_manager(request)
    data = _managed_payload(body)
    if body.id:
        if not security_store.can_manage_connection(body.id, user.username):
            raise HTTPException(status_code=403, detail="You cannot edit this connection.")
    else:
        # New connection: the power user owns it and is auto-assigned so they can use it.
        data["owner"] = user.username
        data["assignments"] = list(dict.fromkeys([user.username, *(body.assignments or [])]))
    try:
        conn = security_store.upsert_connection(data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # Editing an existing connection may change host/credentials or drop assignees;
    # drop every live session on it so users re-establish against the new definition
    # (and re-pass the user_can_use gate) instead of keeping the stale one.
    if body.id:
        await registry.disconnect_connection(body.id)
    return conn.admin_public()


@router.delete("/connections/{conn_id}")
async def delete_managed_connection(conn_id: str, request: Request) -> dict:
    user = _require_manager(request)
    if not security_store.can_manage_connection(conn_id, user.username):
        raise HTTPException(status_code=403, detail="You cannot delete this connection.")
    # Drop every user whose live session is this connection before removing it.
    await registry.disconnect_connection(conn_id)
    security_store.delete_connection(conn_id)
    return {"ok": True}


class ProjectDeleteBody(BaseModel):
    projectId: int  # PROJECT_ID is a SMALLINT


def _managed_connection_secrets(conn_id: str, request: Request):
    """Return the manageable connection (with secrets) for a project op, or raise —
    the caller must be a manager AND own/administer this specific connection."""
    user = _require_manager(request)
    if not security_store.can_manage_connection(conn_id, user.username):
        raise HTTPException(status_code=403, detail="You cannot manage this connection.")
    conn = security_store.get_connection(conn_id, with_secrets=True)
    if conn is None:
        raise HTTPException(status_code=404, detail="Connection not found.")
    return user, conn


@router.get("/connections/{conn_id}/projects")
async def list_connection_projects(conn_id: str, request: Request) -> dict:
    """Projects stored in a manageable connection's schema, with journey/event counts."""
    _, conn = _managed_connection_secrets(conn_id, request)
    from ..db.schema_ddl import list_projects_with_counts

    return await list_projects_with_counts(
        host=conn.host, port=conn.port, username=conn.username, password=conn.password,
        schema=conn.schema, use_tls=conn.use_tls, cert_mode=conn.cert_mode,
        fingerprint=conn.fingerprint, min_rsa_bits=conn.min_rsa_bits,
    )


@router.post("/connections/{conn_id}/projects/delete")
async def delete_connection_project(
    conn_id: str, body: ProjectDeleteBody, request: Request
) -> dict:
    """Delete a project from a manageable connection's schema, clearing its rows from
    every project-scoped table (PROJECTS, JOURNEYS, STEPS, METAS, NOTES, TRANSITIONS_RAW)."""
    user, conn = _managed_connection_secrets(conn_id, request)
    from ..db.schema_ddl import delete_project

    result = await delete_project(
        project_id=body.projectId, host=conn.host, port=conn.port, username=conn.username,
        password=conn.password, schema=conn.schema, use_tls=conn.use_tls,
        cert_mode=conn.cert_mode, fingerprint=conn.fingerprint, min_rsa_bits=conn.min_rsa_bits,
    )
    logx.warn(
        f"{user.username} deleted project {body.projectId!r} from connection "
        f"{conn.name!r} ({conn_id}) — "
        + ("ok" if result.get("ok") else f"failed: {result.get('error')}"),
        username=user.username, operation="connection",
    )
    # If the caller's own active connection cached that project's steps, drop them.
    current_db().invalidate_steps()
    return result


@router.post("/connections/{conn_id}/assignments")
async def set_managed_assignments(
    conn_id: str, body: ManagedAssignmentsBody, request: Request
) -> dict:
    user = _require_manager(request)
    if not security_store.can_manage_connection(conn_id, user.username):
        raise HTTPException(status_code=403, detail="You cannot re-assign this connection.")
    try:
        security_store.set_assignments(conn_id, body.assignments)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    # Revocation must take effect immediately: drop live sessions so a user whose
    # assignment was just removed can't keep querying through a stale connection.
    await registry.disconnect_connection(conn_id)
    return {"ok": True}


@router.post("/connections/test")
async def test_managed_connection(
    body: ManagedConnectionTestBody, request: Request
) -> dict:
    _require_manager(request)
    from ..db.manager import test_db_connection

    db_error = await test_db_connection(
        host=body.host,
        port=body.port,
        username=body.username,
        password=body.password,
        schema=body.schema_,
        use_tls=body.useTLS,
        cert_mode=body.certModeRaw,
        fingerprint=body.fingerprint,
        min_rsa_bits=body.minRSAKeySizeBits,
    )
    llm_error: str | None = None
    llm_models: list[str] = []
    if body.llmURL.strip():
        llm = LLMServer(serverURL=body.llmURL, apiKey=body.llmKey)
        if await check_llm_reachable(llm):
            try:
                llm_models = await llm_service.list_models(body.llmURL, body.llmKey)
            except Exception as exc:  # noqa: BLE001
                llm_error = str(exc)
                logx.warn(
                    f"LLM server test failed — {body.llmURL}: {exc}",
                    operation="llm-test",
                )
        else:
            llm_error = "LLM server not reachable."  # check_llm_reachable logged the cause
    return {"dbError": db_error, "llmError": llm_error, "llmModels": llm_models}


@router.post("/connections/provision-schema")
async def provision_managed_schema(body: ManagedConnectionTestBody, request: Request) -> dict:
    """Create the process-mining schema + tables using the supplied credentials.

    Requires elevated database privileges (CREATE SCHEMA / CREATE TABLE) that only a
    database administrator can grant — the app cannot. Returns {ok, error, created}.
    """
    _require_manager(request)
    from ..db.schema_ddl import provision_process_mining_schema

    return await provision_process_mining_schema(
        host=body.host,
        port=body.port,
        username=body.username,
        password=body.password,
        schema=body.schema_,
        use_tls=body.useTLS,
        cert_mode=body.certModeRaw,
        fingerprint=body.fingerprint,
        min_rsa_bits=body.minRSAKeySizeBits,
    )


class DemoContentBody(ManagedConnectionTestBody):
    journeys: int = 500
    # "retail" (Online Bookstore) | "finance" (Credit Application) |
    # "transportation" (Flight Booking) — validated against demo_data.DATASETS.
    dataset: str = "retail"


@router.post("/connections/generate-demo")
async def generate_demo_content(body: DemoContentBody, request: Request) -> dict:
    """Provision the schema + tables and load a demo event log (retail or finance).

    Requires elevated database privileges (CREATE SCHEMA / CREATE TABLE / INSERT) that
    only a database administrator can grant — the app cannot. Returns
    {ok, error, journeys, project, dataset, message}.
    """
    _require_manager(request)
    from ..db.demo_data import generate_demo_content as _generate

    result = await _generate(
        dataset=body.dataset,
        host=body.host,
        port=body.port,
        username=body.username,
        password=body.password,
        schema=body.schema_,
        journeys=body.journeys,
        use_tls=body.useTLS,
        cert_mode=body.certModeRaw,
        fingerprint=body.fingerprint,
        min_rsa_bits=body.minRSAKeySizeBits,
    )
    # Demo generation writes STEPS on a throwaway connection; if the caller's active
    # connection already cached that project's steps, drop it so a reload re-reads.
    current_db().invalidate_steps()
    return result


# ── connect / disconnect / status ────────────────────────────────────────────


@router.post("/disconnect", response_model=ConnectionStatus)
async def disconnect() -> ConnectionStatus:
    mgr = current_db()
    await mgr.disconnect()
    return ConnectionStatus(activeProfileId=mgr.active_profile_id)


@router.get("/connection/status", response_model=ConnectionStatus)
def status() -> ConnectionStatus:
    mgr = current_db()
    return ConnectionStatus(
        isConnected=mgr.is_connected,
        isLLMReachable=mgr.is_llm_reachable,
        activeProfileId=mgr.active_profile_id,
        username=mgr.username,
        lastError=mgr.last_error,
    )
