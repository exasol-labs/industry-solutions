"""Pydantic mirrors of Models.swift / ChartState.swift.

Field names use the same camelCase spelling as the Swift `Codable` types so that
JSON produced here can be read by the Swift app (and by backups taken from it).
"""

from __future__ import annotations

import math
import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Swift's Int.max / Int.min, used as "no bound" sentinels in filters.
INT_MAX = 9223372036854775807
INT_MIN = -9223372036854775808


def new_id() -> str:
    """Uppercase UUID string — matches Swift's `UUID().uuidString`."""
    return str(uuid.uuid4()).upper()


class Base(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


# ── Servers & connection profiles ─────────────────────────────────────────────


class DatabaseServer(Base):
    id: str = Field(default_factory=new_id)
    name: str = ""
    comment: str = ""
    host: str = ""
    port: int = 8563
    username: str = ""
    schema_: str = Field(default="", alias="schema")
    useTLS: bool = False
    certModeRaw: str = "verify"
    fingerprint: str = ""
    minRSAKeySizeBits: int = 2048


class LLMServer(Base):
    id: str = Field(default_factory=new_id)
    name: str = ""
    comment: str = ""
    serverURL: str = ""
    apiKey: str = ""
    model: str = ""


class ConnectionProfile(Base):
    id: str = Field(default_factory=new_id)
    name: str = ""
    comment: str = ""
    databaseServerId: str | None = None
    llmServerId: str | None = None


# ── Core process-mining value types ───────────────────────────────────────────


class Project(Base):
    projectId: int  # PROJECT_ID is a SMALLINT (an allocated integer)
    title: str
    description: str = ""
    titleShort: str = ""  # human-readable code; '#'-prefix = aggregate detail, 'Σ' = high-level


class StepInfo(Base):
    step: str
    description: str = ""
    bgColor: str = "blue"
    fgColor: str = "white"
    score: int | None = None
    shape: str = "stadium"
    endOfProcess: bool = False
    belongsTo: str | None = None
    eventTime: datetime | None = None


class ProcessTransition(Base):
    fromStep: str
    toStep: str
    occurrences: int
    avgSecs: float | None = None
    medianSecs: float | None = None
    minSecs: float | None = None
    maxSecs: float | None = None
    stdDevSecs: float | None = None

    @property
    def id(self) -> str:
        return f"{self.fromStep}->{self.toStep}"

    def metric_value(self, metric: "TransitionMetric") -> float | None:
        if metric is TransitionMetric.count:
            return float(self.occurrences)
        return {
            TransitionMetric.avgTime: self.avgSecs,
            TransitionMetric.medianTime: self.medianSecs,
            TransitionMetric.minTime: self.minSecs,
            TransitionMetric.maxTime: self.maxSecs,
            TransitionMetric.stdDev: self.stdDevSecs,
        }[metric]


class ProcessGraph(Base):
    steps: dict[str, StepInfo] = Field(default_factory=dict)
    transitions: list[ProcessTransition] = Field(default_factory=list)

    @property
    def max_occurrences(self) -> int:
        return max((t.occurrences for t in self.transitions), default=1)

    def max_value(self, metric: "TransitionMetric") -> float:
        vals = [v for t in self.transitions if (v := t.metric_value(metric)) is not None]
        return max(vals, default=1.0)


class JourneyPath(Base):
    path: str
    journeyCount: int
    stepCount: int
    totalScore: int

    @property
    def aggregatedScore(self) -> int:
        return self.totalScore * self.journeyCount


class DurationBucket(Base):
    label: str
    count: int


class JourneyTimePoint(Base):
    date: datetime
    count: int


# ── Enums ─────────────────────────────────────────────────────────────────────


class TransitionMetric(str, Enum):
    count = "Count"
    avgTime = "Avg Time"
    medianTime = "Median Time"
    minTime = "Min Time"
    maxTime = "Max Time"
    stdDev = "Std Dev"

    @property
    def is_time_based(self) -> bool:
        return self is not TransitionMetric.count


class TimeGranularity(str, Enum):
    day = "day"
    week = "week"
    month = "month"

    @staticmethod
    def auto(frm: datetime, to: datetime) -> "TimeGranularity":
        days = (to - frm).days
        if days <= 14:
            return TimeGranularity.day
        if days <= 90:
            return TimeGranularity.week
        return TimeGranularity.month

    @property
    def label(self) -> str:
        return {"day": "Daily", "week": "Weekly", "month": "Monthly"}[self.value]


class SampleSet(str, Enum):
    original = "ORIGINAL"
    sample1 = "SAMPLE_1"
    sample2 = "SAMPLE_2"
    sample3 = "SAMPLE_3"

    @property
    def is_original(self) -> bool:
        return self is SampleSet.original

    def sql_fragment(self, alias: str | None = None) -> str:
        col = f"{alias}.SAMPLE_SET" if alias else "SAMPLE_SET"
        if self.is_original:
            return f"({col} = 'ORIGINAL' OR {col} IS NULL)"
        return f"{col} = '{self.value}'"


class SamplingMethod(str, Enum):
    random = "random"
    temporal = "temporal"
    pathDiverse = "pathDiverse"


# ── Filters, presets, happy paths, notes ──────────────────────────────────────


class FilterSpec(Base):
    """The filter arguments every repository query accepts."""

    fromDate: datetime | None = None
    toDate: datetime | None = None
    includedSteps: list[str] = Field(default_factory=list)
    excludedSteps: list[str] = Field(default_factory=list)
    meta1: str = ""
    meta2: str = ""
    meta3: str = ""
    # List-based META value include/exclude (from the node "Meta Infos" panel), mirroring
    # includedSteps/excludedSteps: a journey is kept when it has ≥1 event whose META_n is
    # in the included set, and none whose META_n is in the excluded set.
    includedMeta1: list[str] = Field(default_factory=list)
    excludedMeta1: list[str] = Field(default_factory=list)
    includedMeta2: list[str] = Field(default_factory=list)
    excludedMeta2: list[str] = Field(default_factory=list)
    includedMeta3: list[str] = Field(default_factory=list)
    excludedMeta3: list[str] = Field(default_factory=list)
    minSteps: int = 0
    maxSteps: int = INT_MAX
    minJourneyTime: int = 0
    maxJourneyTime: int = INT_MAX
    minScore: int = INT_MIN
    maxScore: int = INT_MAX
    sampleSet: SampleSet = SampleSet.original


class FilterGroup(Base):
    id: str = Field(default_factory=new_id)
    name: str
    fromDate: datetime
    toDate: datetime
    includedSteps: list[str] = Field(default_factory=list)
    excludedSteps: list[str] = Field(default_factory=list)
    meta1: str = ""
    meta2: str = ""
    meta3: str = ""
    includedMeta1: list[str] = Field(default_factory=list)
    excludedMeta1: list[str] = Field(default_factory=list)
    includedMeta2: list[str] = Field(default_factory=list)
    excludedMeta2: list[str] = Field(default_factory=list)
    includedMeta3: list[str] = Field(default_factory=list)
    excludedMeta3: list[str] = Field(default_factory=list)
    minSteps: int = 0
    maxSteps: int = INT_MAX
    minJourneyTime: int = 0
    maxJourneyTime: int = INT_MAX
    minScore: int = INT_MIN
    maxScore: int = INT_MAX


class HappyPathNode(Base):
    """One node in a Happy Path's series-parallel sequence. A node is a single
    STEP when `branches` is empty (and `step` is set), or a SPLIT when `branches`
    is non-empty — each inner list is one alternative sub-path (itself a node list,
    hence nesting). Steps that follow a split node in the same list are the shared
    "after-rejoin" continuation."""

    id: str = Field(default_factory=new_id)
    step: str = ""
    label: str = ""  # optional name for the split (the fork)
    rejoinLabel: str = ""  # optional name for the point where its branches rejoin
    branches: list[list["HappyPathNode"]] = Field(default_factory=list)


class HappyPath(Base):
    id: str = Field(default_factory=new_id)
    name: str
    nodes: list[HappyPathNode] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _migrate_legacy(cls, data: Any) -> Any:
        """Accept the legacy flat shape ({steps, branches}) and fold it into
        `nodes`: the trunk becomes step nodes, and any non-empty branches become a
        single trailing split. Enumerates to exactly the old trunk+branch routes, so
        conformance scores are unchanged. New payloads (with `nodes`) pass through."""
        if isinstance(data, dict) and "nodes" not in data and (
            "steps" in data or "branches" in data
        ):
            nodes: list[dict] = [{"step": s} for s in (data.get("steps") or [])]
            live = [b for b in (data.get("branches") or []) if (b or {}).get("steps")]
            if live:
                nodes.append(
                    {"branches": [[{"step": s} for s in b["steps"]] for b in live]}
                )
            data = {k: v for k, v in data.items() if k not in ("steps", "branches")}
            data["nodes"] = nodes
        return data


HappyPathNode.model_rebuild()  # resolve the recursive forward reference


class FilterSnapshot(Base):
    fromDate: datetime
    toDate: datetime
    includedSteps: list[str] = Field(default_factory=list)
    excludedSteps: list[str] = Field(default_factory=list)
    meta1: str = ""
    meta2: str = ""
    meta3: str = ""
    minSteps: int = 0
    maxSteps: int = INT_MAX
    minJourneyTime: int = 0
    maxJourneyTime: int = INT_MAX
    minScore: int = INT_MIN
    maxScore: int = INT_MAX


class NoteTarget(Base):
    """Mirrors the Swift `NoteTarget` enum in its encoded form."""

    type: str = "node"  # "node" | "edge"
    value: str | None = None  # node name
    from_: str | None = Field(default=None, alias="from")
    to: str | None = None

    @property
    def is_node(self) -> bool:
        return self.type != "edge"

    @property
    def display_name(self) -> str:
        if self.is_node:
            return self.value or ""
        return f"{self.from_} → {self.to}"


# Note importance levels, lowest → highest. NORMAL is the default.
NOTE_IMPORTANCE = ("NORMAL", "INFO", "IMPORTANT", "URGENT")


def normalize_importance(value: object) -> str:
    v = value.upper() if isinstance(value, str) else ""
    return v if v in NOTE_IMPORTANCE else "NORMAL"


class ProcessNote(Base):
    id: str = Field(default_factory=new_id)
    title: str = ""  # short subject; on a thread it is the latest entry's title
    text: str = ""
    createdAt: datetime = Field(default_factory=datetime.now)
    editedAt: datetime | None = None
    target: NoteTarget
    filterSnapshot: FilterSnapshot
    username: str = ""  # login user (stable identity — used for ownership/filtering)
    lastEditedBy: str = ""
    isShared: bool = False
    importance: str = "NORMAL"  # one of NOTE_IMPORTANCE
    resolved: bool = False  # the note/issue has been marked resolved
    # Display labels resolved by the API on read: an LDAP user's real name (cn),
    # otherwise the login username. Not persisted; ignored on write.
    authorName: str = ""
    lastEditedByName: str = ""


# ── Simulation ────────────────────────────────────────────────────────────────


class SimulationConfig(Base):
    journeyCount: int = 200
    startDate: datetime = Field(default_factory=datetime.now)
    avgInterArrivalHours: float = 2.0
    excludedSteps: list[str] = Field(default_factory=list)
    requiredSteps: list[str] = Field(default_factory=list)
    maxStepsPerJourney: int = 60


class SimulatedEvent(Base):
    journeyId: str
    step: str
    timestamp: datetime


class SimulationVariant(Base):
    path: str
    count: int
    percentage: float
    avgCycleTimeSecs: float


class SimulationResult(Base):
    runId: str = Field(default_factory=new_id)
    events: list[SimulatedEvent] = Field(default_factory=list)
    variants: list[SimulationVariant] = Field(default_factory=list)
    cycleTimes: list[float] = Field(default_factory=list)
    simProcessGraph: ProcessGraph = Field(default_factory=ProcessGraph)
    totalJourneys: int = 0
    avgCycleTimeSecs: float = 0.0
    minCycleTimeSecs: float = 0.0
    maxCycleTimeSecs: float = 0.0
    stdDevCycleTimeSecs: float = 0.0


# ── Aggregate responses ───────────────────────────────────────────────────────


class DurationStats(Base):
    minSecs: float | None = None
    avgSecs: float | None = None
    medianSecs: float | None = None
    stdDevSecs: float | None = None
    maxSecs: float | None = None


class GraphResponse(Base):
    """Everything a chart panel needs for one filter state."""

    processGraph: ProcessGraph
    journeyCount: int | None = None
    durations: DurationStats = Field(default_factory=DurationStats)
    processGoodness: float | None = None
    # How the transitions were computed: 'materialized' (TRANSITIONS_RAW) or 'live'.
    transitionsMode: str | None = None
    # Server-side wall-clock of the DB queries behind this reload, in milliseconds.
    queryMs: float | None = None


class ProjectBootstrap(Base):
    project: Project
    allSteps: list[str] = Field(default_factory=list)
    allStepInfos: dict[str, StepInfo] = Field(default_factory=dict)
    meta1Title: str | None = None
    meta2Title: str | None = None
    meta3Title: str | None = None
    meta1Values: list[str] = Field(default_factory=list)
    meta2Values: list[str] = Field(default_factory=list)
    meta3Values: list[str] = Field(default_factory=list)
    totalJourneyCount: int | None = None
    minDate: datetime | None = None
    maxDate: datetime | None = None
    initialFromDate: datetime | None = None
    initialToDate: datetime | None = None
    stepCountMin: int = 1
    stepCountMax: int = 100
    journeyTimeBoundsMin: int = 0
    journeyTimeBoundsMax: int = 0
    scoreBoundsMin: int = 0
    scoreBoundsMax: int = 0
    sampleCounts: dict[str, int] = Field(default_factory=dict)
    # Per-sample-set sampling strategy ('random' | 'temporal' | 'pathDiverse'),
    # persisted so the sidebar badges survive a reload.
    sampleMethods: dict[str, str] = Field(default_factory=dict)


class StatisticsResponse(Base):
    paths: list[JourneyPath] = Field(default_factory=list)
    durationBuckets: list[DurationBucket] = Field(default_factory=list)
    timeSeries: list[JourneyTimePoint] = Field(default_factory=list)
    timeGranularity: TimeGranularity = TimeGranularity.month
    processGraph: ProcessGraph = Field(default_factory=ProcessGraph)
    journeyCount: int | None = None
    totalJourneyCount: int | None = None
    durations: DurationStats = Field(default_factory=DurationStats)
    isTruncated: bool = False


class ConnectionStatus(Base):
    isConnected: bool = False
    isLLMReachable: bool = False
    activeProfileId: str | None = None
    username: str = ""
    lastError: str | None = None


def is_finite(x: float | None) -> bool:
    return x is not None and math.isfinite(x)


def coerce_json(value: Any) -> Any:
    """Best-effort conversion of DB driver values into JSON-safe primitives."""
    if isinstance(value, datetime):
        return value.isoformat()
    return value
