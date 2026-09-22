"""Project data endpoints — bootstrap, filtered graphs, statistics, journeys."""

from __future__ import annotations

import hashlib
import time
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ..db.manager import current_db
from ..db.repository import ProcessRepository
from ..models import (
    DurationStats,
    FilterSpec,
    GraphResponse,
    JourneyPath,
    ProcessGraph,
    Project,
    ProjectBootstrap,
    SampleSet,
    StatisticsResponse,
    StepInfo,
    TimeGranularity,
)
from ..services.analytics import ab_similarity, apply_goodness_coverage
from ..store.security import store as security_store
from ..store.settings import store as settings_store

router = APIRouter(prefix="/api", tags=["projects"])


def repo(sample_set: SampleSet = SampleSet.original) -> ProcessRepository:
    # The current request's user resolves to their own DatabaseManager, so data
    # never crosses between users (see manager.current_db / main.UserContextMiddleware).
    db = current_db()
    # Reflect the connection's *current* materialised-transitions setting on every
    # request, so an admin toggling it takes effect on the next reload without the
    # user having to reconnect (the flag was otherwise captured only at connect).
    if db.active_profile_id:
        conn = security_store.get_connection(db.active_profile_id)
        if conn is not None:
            db.use_materialized_transitions = conn.use_materialized_transitions
    r = ProcessRepository(db)
    r.active_sample_set = sample_set
    return r


def require_connection() -> None:
    db = current_db()
    # A socket the network/DB dropped after idle leaves is_connected False, but the
    # manager still knows how to reopen it and will self-heal on the next query — so
    # don't 409 (which forces a manual reconnect); let the query through to reconnect.
    if not (db.is_connected or db.can_reconnect):
        raise HTTPException(status_code=409, detail="Not connected to a database.")


class GraphRequest(BaseModel):
    filter: FilterSpec = FilterSpec()
    totalJourneyCount: int | None = None
    includeGoodness: bool = True
    includeVariants: bool = False
    variantLimit: int = 500


class GraphResult(GraphResponse):
    variants: list[JourneyPath] = []


class StatisticsRequest(BaseModel):
    filter: FilterSpec = FilterSpec()
    routeLimit: int = 500
    totalJourneyCount: int | None = None


class SimilarityRequest(BaseModel):
    variantsA: list[JourneyPath]
    variantsB: list[JourneyPath]
    graphA: ProcessGraph
    graphB: ProcessGraph


class StepUpdate(BaseModel):
    bgColor: str
    fgColor: str
    score: int | None = None
    shape: str = "stadium"
    belongsTo: str | None = None
    description: str | None = None


class NearestDayRequest(BaseModel):
    day: datetime
    sampleSet: SampleSet = SampleSet.original


# ── projects & bootstrap ─────────────────────────────────────────────────────


@router.get("/projects", response_model=list[Project])
async def list_projects() -> list[Project]:
    require_connection()
    return await repo().load_projects()


@router.get("/projects/{project_id}/bootstrap", response_model=ProjectBootstrap)
async def bootstrap(
    project_id: int, sampleSet: SampleSet = SampleSet.original
) -> ProjectBootstrap:
    """Everything AppViewModel.selectProject() loaded before the first graph."""
    require_connection()
    r = repo(sampleSet)

    projects = await r.load_projects()
    project = next((p for p in projects if p.projectId == project_id), None)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    # All four filter-slider ranges (date / step-count / journey-time / score) in
    # one scan instead of four separate round trips (they serialise on the single
    # per-user connection).
    b = await r.load_project_bounds(project_id)
    min_date, max_date = b.date_min, b.date_max
    initial_to = max_date
    initial_from = (max_date - timedelta(days=30)) if max_date else None
    step_min, step_max = b.step_min, b.step_max
    time_min, time_max = b.time_min, b.time_max
    score_min, score_max = b.score_min, b.score_max

    all_steps = await r.load_all_step_names(project_id)
    all_step_infos = await r.load_steps(project_id)

    t1, t2, t3 = await r.load_meta_titles(project_id)
    # DISTINCT values for the configured META columns in one round trip, not up to 3.
    wanted = [c for c, t in (("META_1", t1), ("META_2", t2), ("META_3", t3)) if t]
    meta_vals = await r.load_meta_values_multi(project_id, wanted)
    meta1 = meta_vals.get("META_1", [])
    meta2 = meta_vals.get("META_2", [])
    meta3 = meta_vals.get("META_3", [])

    await r.ensure_sample_set_column()
    sample_counts = await r.load_sample_journey_counts(project_id)
    # Persisted sampling strategy per sample set (so the sidebar badges reload).
    sample_methods = {
        s.value: settings_store.get(f"sampling.method.{s.value}.{project_id}")
        for s in (SampleSet.sample1, SampleSet.sample2, SampleSet.sample3)
    }
    sample_methods = {k: v for k, v in sample_methods.items() if v}

    # The total always counts ORIGINAL rows so it never reflects a sample's size.
    original = repo(SampleSet.original)
    total = await original.load_journey_count(project_id, FilterSpec())

    return ProjectBootstrap(
        project=project,
        allSteps=all_steps,
        allStepInfos=all_step_infos,
        meta1Title=t1,
        meta2Title=t2,
        meta3Title=t3,
        meta1Values=meta1,
        meta2Values=meta2,
        meta3Values=meta3,
        totalJourneyCount=total,
        minDate=min_date,
        maxDate=max_date,
        initialFromDate=initial_from,
        initialToDate=initial_to,
        stepCountMin=step_min,
        stepCountMax=step_max,
        journeyTimeBoundsMin=time_min,
        journeyTimeBoundsMax=time_max,
        scoreBoundsMin=score_min,
        scoreBoundsMax=score_max,
        sampleCounts=sample_counts,
        sampleMethods=sample_methods,
    )


# ── filtered graph ───────────────────────────────────────────────────────────


@router.post("/projects/{project_id}/graph", response_model=GraphResult)
async def load_graph(project_id: int, request: GraphRequest) -> GraphResult:
    """One round trip for everything a chart panel shows: graph, journey count,
    duration KPIs, process goodness and (optionally) the variant list."""
    require_connection()
    f = request.filter
    r = repo(f.sampleSet)

    # Wall-clock of the DB work behind this reload — shown to the user under the
    # chart. Covers the map + KPI queries (the operation they waited for), not the
    # optional variant list below.
    started = time.perf_counter()

    graph = await r.load_graph(project_id, f)
    count = await r.load_journey_count(project_id, f)
    durations = await r.load_journey_duration_stats(project_id, f)

    goodness: float | None = None
    if request.includeGoodness:
        result = await r.load_process_goodness(project_id, f)
        if result is not None:
            raw, filtered_count = result
            goodness = apply_goodness_coverage(
                raw, filtered_count, request.totalJourneyCount
            )

    query_ms = round((time.perf_counter() - started) * 1000.0, 1)

    variants: list[JourneyPath] = []
    if request.includeVariants:
        try:
            variants = await r.load_journey_paths(project_id, f, request.variantLimit)
        except TimeoutError:
            variants = []

    return GraphResult(
        processGraph=graph,
        journeyCount=count,
        durations=durations,
        processGoodness=goodness,
        transitionsMode=r.last_transitions_mode,
        queryMs=query_ms,
        variants=variants,
    )


@router.post("/projects/{project_id}/journey-paths", response_model=list[JourneyPath])
async def journey_paths(
    project_id: int, request: GraphRequest
) -> list[JourneyPath]:
    require_connection()
    r = repo(request.filter.sampleSet)
    try:
        return await r.load_journey_paths(project_id, request.filter, request.variantLimit)
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc


@router.post("/similarity")
def similarity(request: SimilarityRequest) -> dict[str, float | None]:
    return {
        "score": ab_similarity(
            request.variantsA, request.variantsB, request.graphA, request.graphB
        )
    }


# ── statistics ───────────────────────────────────────────────────────────────


@router.post("/projects/{project_id}/statistics", response_model=StatisticsResponse)
async def statistics(project_id: int, request: StatisticsRequest) -> StatisticsResponse:
    require_connection()
    f = request.filter
    r = repo(f.sampleSet)

    count = await r.load_journey_count(project_id, f)

    total = request.totalJourneyCount
    if total is None:
        total = await repo(SampleSet.original).load_journey_count(project_id, FilterSpec())

    granularity = (
        TimeGranularity.auto(f.fromDate, f.toDate)
        if f.fromDate and f.toDate
        else TimeGranularity.month
    )
    time_series = await r.load_journey_time_series(project_id, f, granularity)
    durations = await r.load_journey_duration_stats(project_id, f)
    buckets = await r.load_duration_buckets(project_id, f)
    graph = await r.load_graph(project_id, f)

    try:
        paths = await r.load_journey_paths(project_id, f, request.routeLimit)
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc

    return StatisticsResponse(
        paths=paths,
        durationBuckets=buckets,
        timeSeries=time_series,
        timeGranularity=granularity,
        processGraph=graph,
        journeyCount=count,
        totalJourneyCount=total,
        durations=durations,
        isTruncated=len(paths) >= request.routeLimit,
    )


# ── individual journeys ──────────────────────────────────────────────────────


@router.get("/projects/{project_id}/event-ids", response_model=list[str])
async def event_ids(
    project_id: int,
    prefix: str = Query(""),
    limit: int = 10,
    sampleSet: SampleSet = SampleSet.original,
) -> list[str]:
    require_connection()
    if len(prefix) < 2:
        return []
    return await repo(sampleSet).load_event_id_suggestions(project_id, prefix, limit)


class NodeMetasRequest(BaseModel):
    step: str
    sampleSet: SampleSet = SampleSet.original


@router.post("/projects/{project_id}/node-metas")
async def node_metas(project_id: int, request: NodeMetasRequest) -> dict:
    """The META_1/2/3 values that occur on one node's (step's) events — the values the node
    "Meta Infos" panel offers, scoped to that node. Each entry is
    ``{value, time, count}``: the value, the date/time it was last seen, and how many of
    the node's events carry it."""
    require_connection()
    vals = await repo(request.sampleSet).load_node_meta_values(project_id, request.step)
    return {"meta1": vals["META_1"], "meta2": vals["META_2"], "meta3": vals["META_3"]}


@router.get("/projects/{project_id}/journey")
async def journey(
    project_id: int,
    eventId: str,
    sampleSet: SampleSet = SampleSet.original,
) -> dict[str, object]:
    """Loads one journey. Non-hash input is MD5-hashed first, matching the Swift
    behaviour where EVENT_ID holds the hash of a source identifier."""
    require_connection()
    raw = eventId.strip()
    if not raw:
        raise HTTPException(status_code=400, detail="Event ID is required")
    is_md5 = len(raw) == 32 and all(c in "0123456789abcdefABCDEF" for c in raw)
    resolved = raw if is_md5 else hashlib.md5(raw.encode("utf-8")).hexdigest()

    r = repo(sampleSet)
    graph = await r.load_journey_graph(project_id, resolved)
    info = await r.load_journey_info(project_id, resolved)
    sequence = await r.load_journey_sequence(project_id, resolved)
    return {
        "queriedEventId": resolved,
        "processGraph": graph.model_dump(by_alias=True),
        # The raw ordered trace (loops unrolled), for the sequential swimlane view.
        "sequence": sequence,
        "journeyCount": 0 if not graph.transitions else 1,
        **{k: v for k, v in info.items()},
    }


# ── step editor ──────────────────────────────────────────────────────────────


@router.put("/projects/{project_id}/steps/{step}")
async def update_step(
    project_id: int, step: str, payload: StepUpdate
) -> dict[str, object]:
    require_connection()
    r = repo()
    await r.update_step(
        project_id,
        step,
        bg_color=payload.bgColor,
        fg_color=payload.fgColor,
        score=payload.score,
        shape=payload.shape,
        belongs_to=payload.belongsTo,
        description=payload.description,
    )
    score_min, score_max = await r.load_score_bounds(project_id)
    steps = await r.load_steps(project_id)
    return {
        "scoreBoundsMin": score_min,
        "scoreBoundsMax": score_max,
        "allStepInfos": {k: v.model_dump(by_alias=True) for k, v in steps.items()},
    }


@router.post("/projects/{project_id}/nearest-day")
async def nearest_day(
    project_id: int, request: NearestDayRequest
) -> dict[str, datetime | None]:
    require_connection()
    found = await repo(request.sampleSet).find_nearest_day_with_data(
        request.day, project_id
    )
    return {"date": found}
