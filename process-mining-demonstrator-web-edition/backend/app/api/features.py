"""Notes, sampling, simulation, AI documentation and settings endpoints."""

from __future__ import annotations

import asyncio
import math
import time
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import log_events as logx
from ..config import DEFAULT_LLM_PROMPT
from ..db.manager import current_db, current_user
from ..models import (
    FilterSpec,
    HappyPath,
    ProcessGraph,
    ProcessNote,
    SampleSet,
    SamplingMethod,
    SimulationConfig,
    SimulationResult,
    StepInfo,
    TransitionMetric,
)
from ..services import docgen, llm as llm_service, report as report_service, simulation
from ..services.llm_config import resolve_llm
from ..services.analytics import (
    happy_path_conformance,
    path_diverse_sample,
    random_sample,
    temporal_stratified_sample,
)
from ..store.security import store as security_store
from ..store.settings import store
from .projects import repo, require_connection

router = APIRouter(prefix="/api", tags=["features"])


def _require_power() -> None:
    """Restrict an action to power users and administrators (the same bar as
    managing connections). Used for journey sampling, which rewrites the shared
    JOURNEYS table for everyone on the connection. Mirrors `connections._require_power`
    but reads the caller from the request ContextVar. When sign-in is disabled there
    is no user identity and every power feature is hidden client-side, so an absent
    user is likewise refused here (defence in depth against a direct API call)."""
    username = current_user()
    user = security_store.get_user(username) if username else None
    if user is None or not user.is_enabled or not (user.is_admin or user.is_power):
        raise HTTPException(
            status_code=403,
            detail="Journey sampling is available to power users and administrators only.",
        )


def _require_power_or_developer() -> None:
    """Restrict an action to power users, developers and administrators — the bar for
    editing the per-(connection, project) report analysis prompt from the app."""
    username = current_user()
    user = security_store.get_user(username) if username else None
    if user is None or not user.is_enabled or not (
        user.is_admin or user.is_power or user.is_developer
    ):
        raise HTTPException(
            status_code=403,
            detail="The report prompt is editable by power users, developers and administrators only.",
        )


def _require_assigned_connection(connection_id: str) -> None:
    """The caller must be assigned to this connection (the same gate `connect` uses). The
    report prompt/style are keyed by (connection, project); without this a role-holder could
    reach another customer's connection just by passing its id — a cross-tenant IDOR."""
    if not security_store.user_can_use((connection_id or "").strip(), current_user()):
        raise HTTPException(status_code=403, detail="This connection is not available to you.")


# ── Report analysis prompt (per connection + project) ────────────────────────


class ReportPromptBody(BaseModel):
    connectionId: str
    prompt: str = ""


@router.get("/projects/{project_id}/report-prompt")
async def get_report_prompt(project_id: int, connectionId: str = "") -> dict[str, str]:
    """The report analysis prompt stored for this (connection, project), or "" if none.
    Power/developer/admin only, and only for a connection assigned to the caller — it is the
    same prompt the admin Reporting tab manages."""
    _require_power_or_developer()
    _require_assigned_connection(connectionId)
    return {"prompt": security_store.report_prompt_for(connectionId, project_id) or ""}


@router.put("/projects/{project_id}/report-prompt")
async def put_report_prompt(project_id: int, body: ReportPromptBody) -> dict[str, str]:
    """Upsert the report analysis prompt for this (connection, project); an empty prompt
    clears it (the app's default template is then used)."""
    _require_power_or_developer()
    _require_assigned_connection(body.connectionId)
    try:
        security_store.set_report_prompt(body.connectionId, project_id, body.prompt)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"prompt": security_store.report_prompt_for(body.connectionId, project_id) or ""}


# ── Notes ────────────────────────────────────────────────────────────────────


def _note_display_name(username: str) -> str:
    """Badge label for a note author: the login user, shown as their real name
    (cn) when we have one. `display_name` is only ever populated from LDAP (the cn),
    so a non-empty value means "LDAP user, use the real name"; we don't gate on
    auth_source because the LDAP-refresh path never rewrites it."""
    if not username:
        return ""
    user = security_store.get_user(username)
    if user and user.display_name:
        return user.display_name
    return username


def _annotate_note(note: ProcessNote) -> ProcessNote:
    note.authorName = _note_display_name(note.username)
    note.lastEditedByName = _note_display_name(note.lastEditedBy)
    return note


@router.get("/projects/{project_id}/notes", response_model=list[ProcessNote])
async def list_notes(project_id: int) -> list[ProcessNote]:
    require_connection()
    r = repo()
    await r.ensure_notes_table()
    notes = await r.load_notes(project_id, current_user() or "")
    return [_annotate_note(n) for n in notes]


@router.put("/projects/{project_id}/notes", response_model=ProcessNote)
async def save_note(project_id: int, note: ProcessNote) -> ProcessNote:
    require_connection()
    r = repo()
    await r.ensure_notes_table()

    # The note author is the logged-in app user (X-PMW-User), NOT the shared
    # database connection user.
    author = current_user() or ""
    # Creation only. An existing note is an append-only thread — comments, resolved
    # and reclassification go through POST .../notes/{id}, so this PUT can never
    # rewrite an existing note's history (which would discard other users' comments).
    if await r.note_owner(note.id) is not None:
        raise HTTPException(
            status_code=409, detail="This note already exists — add a comment instead."
        )

    note.username = author
    note.lastEditedBy = ""
    await r.upsert_note(note, project_id, author)
    return _annotate_note(note)


class NoteUpdateBody(BaseModel):
    """Partial update of an existing note. `comment` (with an optional `title`) is
    added to the thread; `resolved` may be toggled by any viewer; importance/isShared
    are owner-only."""

    title: str = Field(default="", max_length=200)
    # Capped so one commenter can't fill a shared note's thread (and block everyone
    # else) or send an oversized body. Plenty for an annotation/comment.
    comment: str = Field(default="", max_length=4000)
    resolved: bool | None = None
    importance: str | None = None
    isShared: bool | None = None


@router.post("/projects/{project_id}/notes/{note_id}", response_model=ProcessNote)
async def update_note(project_id: int, note_id: str, body: NoteUpdateBody) -> ProcessNote:
    """Append a comment and/or toggle resolved on a note — allowed for anyone who
    can see it (author, a shared note, or an unowned one). Only the author may
    change importance or the shared flag. The existing history is never rewritten."""
    require_connection()
    r = repo()
    await r.ensure_notes_table()

    meta = await r.note_meta(note_id)
    if meta is None:
        raise HTTPException(status_code=404, detail="Note not found.")
    owner, is_shared = meta
    caller = current_user() or ""
    is_owner = (owner or "").upper() == caller.upper()
    if not (is_owner or is_shared or owner == ""):
        raise HTTPException(status_code=403, detail="You cannot access this note.")

    comment_block: str | None = None
    new_title = body.title.strip() or None
    if body.comment.strip():
        name = _note_display_name(caller) or caller or "unknown"
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        # The header carries the (optional) title, so each comment's title is visible
        # in the thread; the trailing blank line separates it from the older content
        # it is prepended in front of (newest on top).
        header = f"—— {new_title} · {name} · {stamp} ——" if new_title else f"—— {name} · {stamp} ——"
        comment_block = f"{header}\n{body.comment.strip()}\n\n"

    await r.update_note(
        note_id,
        project_id,
        edited_by=caller,
        comment_block=comment_block,
        # The note's title tracks the latest titled entry, so the overview heading
        # shows the most recent subject. Not owner-gated (part of the comment).
        title=new_title,
        resolved=body.resolved,
        # Note-level classification stays owner-only; a non-owner's values are ignored.
        importance=body.importance if is_owner else None,
        is_shared=body.isShared if is_owner else None,
    )

    note = await r.get_note(note_id, project_id)
    if note is None:
        raise HTTPException(status_code=404, detail="Note not found.")
    return _annotate_note(note)


@router.delete("/projects/{project_id}/notes/{note_id}")
async def delete_note(project_id: int, note_id: str) -> dict[str, bool]:
    require_connection()
    await repo().delete_note(note_id, project_id, current_user() or "")
    return {"ok": True}


# ── Sampling ─────────────────────────────────────────────────────────────────


class CreateSampleRequest(BaseModel):
    sampleSet: SampleSet
    count: int
    method: SamplingMethod


@router.get("/projects/{project_id}/samples")
async def sample_counts(project_id: int) -> dict[str, object]:
    require_connection()
    r = repo()
    await r.ensure_sample_set_column()
    counts = await r.load_sample_journey_counts(project_id)
    methods = {
        s.value: store.get(f"sampling.method.{s.value}.{project_id}")
        for s in (SampleSet.sample1, SampleSet.sample2, SampleSet.sample3)
    }
    return {"counts": counts, "methods": {k: v for k, v in methods.items() if v}}


@router.post("/projects/{project_id}/samples")
async def create_sample(project_id: int, request: CreateSampleRequest) -> dict[str, object]:
    require_connection()
    _require_power()
    if request.sampleSet.is_original:
        raise HTTPException(status_code=400, detail="Cannot overwrite the original data.")

    r = repo()
    await r.ensure_sample_set_column()

    # Per-connection opt-in: build the whole sample INSIDE the database — one
    # set-based INSERT … SELECT, no extract of every EVENT_ID to the app and no
    # thousands of batched re-inserts. Essential for very large logs (the app-side
    # path times out at ~500M events). Falls back to the app path when the flag is
    # off or the connection (with secrets) can't be resolved.
    db = current_db()
    conn = (
        security_store.get_connection(db.active_profile_id, with_secrets=True)
        if db.active_profile_id
        else None
    )
    use_indb = bool(conn and conn.use_indb_sampling)
    # One line that answers "why was sampling slow?": which path, and the exact inputs
    # to the decision. App-side (extract every id → pick → batched insert) is the slow
    # one on large logs; if this says app-side, the connection's flag isn't set.
    logx.info(
        f"Sampling path: {'in-database' if use_indb else 'app-side'} — "
        f"connection={db.active_profile_id!r}, resolved={conn is not None}, "
        f"flag={getattr(conn, 'use_indb_sampling', None)}, "
        f"count={request.count}, method={request.method.value}, slot={request.sampleSet.value}",
        operation="sampling",
    )
    if use_indb:
        from ..db.schema_ddl import build_sample_in_db

        started = time.perf_counter()
        result = await build_sample_in_db(
            host=conn.host, port=conn.port, username=conn.username,
            password=conn.password, schema=conn.schema,
            use_tls=conn.use_tls, cert_mode=conn.cert_mode,
            fingerprint=conn.fingerprint, min_rsa_bits=conn.min_rsa_bits,
            project_id=project_id, count=request.count,
            method=request.method.value, sample_set=request.sampleSet,
        )
        logx.info(
            f"In-database sampling: project={project_id} slot={request.sampleSet.value} "
            f"method={request.method.value} journeys={result.get('journeys', 0)} "
            f"seconds={time.perf_counter() - started:.1f} ok={result['ok']}",
            operation="sampling",
        )
        if not result["ok"]:
            raise HTTPException(
                status_code=502, detail=result["error"] or "In-database sampling failed."
            )
        if result["journeys"] == 0:
            raise HTTPException(
                status_code=404, detail="No journeys found in the original data."
            )
        store.set(
            f"sampling.method.{request.sampleSet.value}.{project_id}", request.method.value
        )
        counts = await r.load_sample_journey_counts(project_id)
        return {"counts": counts, "created": result["journeys"]}

    # App-side path (default): extract ids → pick in Python → batched re-insert.
    # The extract of every distinct EVENT_ID is what makes this slow on large logs,
    # even for a tiny sample — enable the connection's in-database flag to avoid it.
    await r.delete_sample(project_id, request.sampleSet)

    if request.method is SamplingMethod.random:
        ids = await r.load_all_event_ids_for_sampling(project_id)
        selected = random_sample(ids, request.count)
    elif request.method is SamplingMethod.temporal:
        pairs = await r.load_event_ids_with_start_times(project_id)
        selected = temporal_stratified_sample(pairs, request.count)
    else:
        pairs = await r.load_event_ids_with_paths(project_id)
        selected = path_diverse_sample(pairs, request.count)

    if not selected:
        raise HTTPException(
            status_code=404, detail="No journeys found in the original data."
        )

    await r.insert_sample_journeys(project_id, selected, request.sampleSet)
    store.set(
        f"sampling.method.{request.sampleSet.value}.{project_id}", request.method.value
    )
    counts = await r.load_sample_journey_counts(project_id)
    return {"counts": counts, "created": len(selected)}


@router.delete("/projects/{project_id}/samples/{sample_set}")
async def delete_sample(project_id: int, sample_set: SampleSet) -> dict[str, object]:
    require_connection()
    _require_power()
    r = repo()
    await r.delete_sample(project_id, sample_set)
    store.delete(f"sampling.method.{sample_set.value}.{project_id}")
    return {"counts": await r.load_sample_journey_counts(project_id)}


# ── Simulation ───────────────────────────────────────────────────────────────


class SimulateRequest(BaseModel):
    graph: ProcessGraph
    stepInfos: dict[str, StepInfo] = {}
    config: SimulationConfig = SimulationConfig()


# A run beyond this exhausts memory / crashes the process, so it is refused up
# front rather than attempted (the user reported ~200k journeys killing the app).
_MAX_SIM_JOURNEYS = 100_000
_MAX_SIM_STEPS = 10_000  # per-journey event cap
_MAX_SIM_EVENTS = 20_000_000  # ceiling on total events (journeys × steps per journey)
# Wall-clock ceiling for a single run — a slower run is abandoned (and logged)
# instead of hanging the request indefinitely.
_SIM_TIMEOUT_SECS = 120.0


@router.post("/simulate", response_model=SimulationResult)
async def simulate(request: SimulateRequest) -> SimulationResult:
    step_infos = request.stepInfos or request.graph.steps
    cfg = request.config
    count = cfg.journeyCount
    max_steps = cfg.maxStepsPerJourney
    # Guard against an oversized/degenerate run that would otherwise exhaust memory
    # or CPU and take the shared backend down for every user. The wall-clock timeout
    # can't cancel the worker thread once it's looping, so the size must be bounded
    # up front. journeyCount alone isn't enough: a cyclic graph with a huge
    # maxStepsPerJourney appends an event per step, so both dimensions — and their
    # product — need a ceiling. Non-finite inter-arrival (inf/nan) breaks timedelta.
    def _reject(msg: str) -> None:
        logx.warn(f"Simulation rejected: {msg}", operation="simulation")
        raise HTTPException(status_code=400, detail=msg)

    if count > _MAX_SIM_JOURNEYS:
        _reject(
            f"Too many journeys to simulate ({count:,}). "
            f"The maximum is {_MAX_SIM_JOURNEYS:,}."
        )
    if max_steps > _MAX_SIM_STEPS:
        _reject(
            f"maxStepsPerJourney ({max_steps:,}) exceeds the limit of {_MAX_SIM_STEPS:,}."
        )
    if count > 0 and max_steps > 0 and count * max_steps > _MAX_SIM_EVENTS:
        _reject(
            f"The requested run is too large ({count:,} journeys × {max_steps:,} steps). "
            f"Keep journeys × steps under {_MAX_SIM_EVENTS:,}."
        )
    if not math.isfinite(cfg.avgInterArrivalHours):
        _reject("avgInterArrivalHours must be a finite number.")
    # Run the CPU-bound simulation off the event loop, bounded by a timeout so a
    # pathological run surfaces as a logged error rather than a frozen request.
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(
                simulation.simulate, request.graph, step_infos, request.config
            ),
            timeout=_SIM_TIMEOUT_SECS,
        )
    except (asyncio.TimeoutError, TimeoutError):
        logx.error(
            f"Simulation timed out after {_SIM_TIMEOUT_SECS:g}s ({count} journeys)",
            operation="simulation",
        )
        raise HTTPException(
            status_code=504,
            detail=(
                f"Simulation timed out ({count:,} journeys). Try fewer journeys."
            ),
        ) from None
    except MemoryError:
        logx.error(
            f"Simulation ran out of memory ({count} journeys)",
            operation="simulation",
        )
        raise HTTPException(
            status_code=500,
            detail=(
                f"Simulation ran out of memory ({count:,} journeys). "
                "Try fewer journeys."
            ),
        ) from None
    except Exception as exc:  # noqa: BLE001
        # Log the exception detail server-side, but return a generic message so
        # internal errors don't leak to the client.
        logx.error(
            f"Simulation failed ({count} journeys): {exc.__class__.__name__}: {exc}",
            operation="simulation",
        )
        raise HTTPException(
            status_code=500, detail="Simulation failed. Please try again."
        ) from exc


# ── Happy-path conformance ───────────────────────────────────────────────────


class ConformanceRequest(BaseModel):
    filter: FilterSpec = FilterSpec()
    happyPaths: list[HappyPath] = []
    limit: int = 500


@router.post("/projects/{project_id}/conformance")
async def conformance(
    project_id: int, request: ConformanceRequest
) -> dict[str, float | None]:
    require_connection()
    r = repo(request.filter.sampleSet)
    try:
        variants = await r.load_journey_paths(project_id, request.filter, request.limit)
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    return {p.id: happy_path_conformance(p, variants) for p in request.happyPaths}


# ── AI supported documentation ───────────────────────────────────────────────


class DocumentationRequest(BaseModel):
    projectTitle: str
    filter: FilterSpec = FilterSpec()
    graph: ProcessGraph
    promptTemplate: str = DEFAULT_LLM_PROMPT
    targetNorms: dict[str, dict[str, float]] = {}
    targetMetric: TransitionMetric = TransitionMetric.count
    # Mirrors the Conformance view's "Norm is a minimum" toggle so the report's gap
    # analysis judges edges the same way the live view does.
    normIsMinimum: bool = False
    happyPaths: list[HappyPath] = []
    # The project's notes — rendered as a report chapter (open/resolved, by severity).
    notes: list[ProcessNote] = []
    # Identify the connection so the admin's per-(connection, project) report prompt is used.
    connectionId: str = ""
    # The Sankey the app already rendered — embedded verbatim (sanitised) in the report.
    sankeySvg: str = ""
    sankeyCaption: str = ""
    # For the report letterhead ("Prepared for …").
    preparedFor: str = ""


@router.post("/projects/{project_id}/documentation")
async def documentation(
    project_id: int, request: DocumentationRequest
) -> dict[str, object]:
    require_connection()

    # The report's per-(connection, project) prompt and style are keyed by the caller's
    # ACTIVE connection — never a client-supplied id — so a user can only ever pull the
    # prompt/style of a connection they are actually connected to (and thus assigned).
    conn_id = current_db().active_profile_id or ""

    # Resolve the effective LLM once, in one place: the active connection's own LLM
    # overrides the global default (admin → Reporting); both are read live from the store
    # so an edited model takes effect on the next report without a reconnect.
    resolved = resolve_llm(current_db())
    if not resolved.configured:
        raise HTTPException(
            status_code=400,
            detail=(
                "No LLM configured for reports. Set a default in the admin Reporting "
                "tab, or give this connection its own LLM."
            ),
        )
    llm_url, llm_key, llm_model = resolved.url, resolved.key, resolved.model

    r = repo(request.filter.sampleSet)

    # Python-computed sections — assembled AFTER the LLM, never sent to it.
    try:
        paths = await r.load_journey_paths(project_id, request.filter, 200)
    except TimeoutError:
        logx.warn(
            f"AI documentation: journey-paths query timed out (project {project_id})",
            operation="ai-doc",
        )
        paths = []
    _paths_html, paths_section = docgen.journey_paths_section(paths)

    conformance_md = docgen.conformance_section(
        request.graph, request.targetNorms, request.targetMetric, request.normIsMinimum
    )
    try:
        variants = await r.load_journey_paths(project_id, request.filter, 500)
    except TimeoutError:
        logx.warn(
            f"AI documentation: variants query timed out (project {project_id})",
            operation="ai-doc",
        )
        variants = []
    happy_md = docgen.happy_path_section(request.happyPaths, variants)

    # The LLM sees ONLY the transition table plus the analysis instruction (the admin's
    # per-(connection, project) prompt if defined, else the app's prompt template).
    instruction = (
        security_store.report_prompt_for(conn_id, project_id)
        or request.promptTemplate
        or DEFAULT_LLM_PROMPT
    )
    prompt = report_service.build_analysis_prompt(
        request.projectTitle, instruction, docgen.transitions_table(request.graph)
    )

    findings: dict | None = None
    error = None
    try:
        answer = await llm_service.chat(llm_url, llm_key, llm_model, prompt)
        findings = report_service.parse_findings(answer or "")
        if findings is None:
            # The model didn't return clean JSON — still show its prose as one section.
            findings = {
                "title": request.projectTitle or "Process Analysis",
                "subtitle": "",
                "executive_summary": [],
                "sections": [{"heading": "Analysis", "body": answer or ""}],
            }
    except llm_service.LLMError as exc:
        error = str(exc)
        logx.error(
            f"AI documentation LLM call failed (project {project_id}, "
            f"model {llm_model or '?'}): {exc}",
            operation="ai-doc",
        )

    # Assemble the styled, self-contained report HTML (only when the analysis succeeded). Each
    # topic is its own chapter — a big titled section that starts on a fresh page — and a
    # table of contents links to them (on screen and in the printed PDF).
    report_html = None
    # Style & Sections are per (connection, project) so one environment can brand reports
    # differently for each customer. A project with none configured uses the built-in theme.
    style = security_store.report_style_for(conn_id, project_id) or {
        "accent": "#4a3aa7",
        "orgName": "",
        "logo": "",
        "logoPos": "left",
        "logoScale": 1.0,
        "includeSankey": True,
        "includeHappyPath": True,
        "includeConformance": True,
    }
    if findings is not None:
        title, subtitle, exec_html, sections_html = report_service.findings_parts(findings)
        chapters: list[dict] = []
        if sections_html.strip():
            chapters.append({"id": "analysis", "title": "Analysis", "html": sections_html})

        # The client-supplied Sankey SVG is embedded as an <img> data URI (sanitised first),
        # so it can never execute script even though it is attacker-controllable.
        svg = report_service.svg_img(request.sankeySvg) if style.get("includeSankey", True) else ""
        if svg:
            cap = (
                f'<p class="caption">{report_service.md_inline(request.sankeyCaption)}</p>'
                if request.sankeyCaption
                else ""
            )
            chapters.append(
                {"id": "flow", "title": "Process flow", "html": f'<div class="diagram">{svg}</div>{cap}'}
            )

        # Conformance & Happy Path are pure markdown pipe tables (cells escaped by the
        # renderer) — they do NOT get raw-HTML passthrough, so a DB-derived step name that
        # breaks out of a table row can never inject markup. Only the Journey Paths section
        # emits a pre-built <table> of html.escape()'d cells and needs allow_raw_html.
        if style.get("includeConformance", True) and conformance_md.strip():
            chapters.append({
                "id": "conformance",
                "title": "Conformance – Gap Analysis",
                "html": report_service.md_to_html(report_service.strip_leading_heading(conformance_md)),
            })
        if style.get("includeHappyPath", True) and happy_md.strip():
            chapters.append({
                "id": "happy",
                "title": "Happy Path Conformance",
                "html": report_service.md_to_html(report_service.strip_leading_heading(happy_md)),
            })
        if paths_section.strip():
            chapters.append({
                "id": "journeys",
                "title": "Journey Paths",
                "html": report_service.md_to_html(report_service.strip_leading_heading(paths_section), allow_raw_html=True),
            })
        notes_html = docgen.notes_section(request.notes)
        if notes_html:
            chapters.append({"id": "notes", "title": "Notes", "html": notes_html})

        report_html = report_service.render_report(
            meta={
                "user": request.preparedFor,
                "source": "transition table underlying the process flow chart",
                "generatedAt": datetime.now().strftime("%d %b %Y"),
                "llm": f"{llm_model} · {resolved.label}" if llm_model else resolved.label,
            },
            style=style,
            title=title,
            subtitle=subtitle,
            exec_summary_html=exec_html,
            chapters=chapters,
        )

    return {
        "reportHtml": report_html,
        "findings": findings,
        "error": error,
        "prompt": prompt,
        "model": llm_model or None,
        "llmSource": resolved.source,
        "llmLabel": resolved.label,
        "generatedAt": datetime.now(),
        # Kept for backward compatibility with the current client while it migrates.
        "journeyPathsSummary": paths_section,
        "conformanceSummary": conformance_md,
        "happyPathSummary": happy_md,
    }


# ── Settings (the UserDefaults replacement) ──────────────────────────────────


class SettingsPatch(BaseModel):
    values: dict[str, object]


@router.get("/settings")
def get_settings() -> dict[str, object]:
    # App preferences are per-user; each user only sees their own namespace.
    values = store.all_user(current_user() or "")
    # Secrets are never echoed back through the settings channel (defensive — they
    # live in the encrypted vault / global namespace, not a user's).
    return {
        k: v
        for k, v in values.items()
        if not k.startswith("conn_pw_") and not k.startswith("llm_api_key_")
    }


@router.patch("/settings")
def patch_settings(patch: SettingsPatch) -> dict[str, bool]:
    user = current_user() or ""
    for key, value in patch.values.items():
        if key.startswith("conn_pw_") or key.startswith("llm_api_key_"):
            continue
        if value is None:
            store.delete_user(user, key)
        else:
            store.set_user(user, key, value)
    return {"ok": True}
