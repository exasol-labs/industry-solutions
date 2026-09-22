"""Concrete extractors that plug into the abstraction layer.

``FileExtractor`` is the first one: it reads a File source and pushes the parsed events
into the target schema's ``JOURNEYS`` table (normalising the timestamp), through the
:class:`~.contract.IngestSession` it is handed. It handles three data *formats*:

* **text** (``.log``/``.txt`` …) — unstructured: each line is one record and every field
  is captured with a **regex** (the original behaviour);
* **json** — semi-structured: a top-level array *or* JSONL/NDJSON; each record is a JSON
  object and every field is located by a **JSON path** (``user.id``);
* **xml** — semi-structured: each record is a repeating element and every field is located
  by an **XPath-subset** selector (``payload@id``).

Whatever the format, each record yields a ``{field name → value}`` dict that the shared
role/compound logic (:meth:`FileExtractor._row_from_values`) maps onto JOURNEYS columns —
so id/step/timestamp/meta handling, MD5 pseudonymisation and compound steps are identical
across formats.
"""

from __future__ import annotations

import hashlib
import json
import re
import zlib
from datetime import datetime

# User-authored regexes are applied to every line, so a catastrophic-backtracking
# pattern must not be able to hang the process. The `regex` module supports a wall-clock
# timeout per match; fall back to stdlib `re` (no timeout available) if it is missing.
try:  # pragma: no cover - exercised by whichever branch the environment provides
    import regex as _rx

    _MATCH_TIMEOUT_SECS = 0.25
    _MATCH_KW = {"timeout": _MATCH_TIMEOUT_SECS}
except ImportError:  # pragma: no cover
    _rx = re
    _MATCH_KW = {}

from .compound import CompoundRules
from .contract import ColumnType, ExtractResult, ExtractorInfo, IngestError, IngestSession
from .files import FORMAT_JSON, FORMAT_TEXT, FORMAT_XML, count_lines, iter_lines
from .parsing import TIMESTAMP_TARGET, analyze_timestamp
from .structured import json_path, scalar, xml_value

# The columns we populate (see backend/app/db/schema_ddl.py).
_JOURNEYS_COLUMNS = {
    "PROJECT_ID": ColumnType.SMALLINT,
    "EVENT_ID": ColumnType.HASH,  # 32-char MD5 → HASHTYPE(16 BYTE) in the DB
    "STEP": ColumnType.STRING,
    "STEP_ID": ColumnType.INT,
    "EVENT_TIME": ColumnType.TIMESTAMP,
    "META_1": ColumnType.STRING,
    "META_2": ColumnType.STRING,
    "META_3": ColumnType.STRING,
    "SAMPLE_SET": ColumnType.STRING,
}
_PROJECTS_COLUMNS = {
    "PROJECT_ID": ColumnType.SMALLINT,
    "TITLE": ColumnType.STRING,
    "DESCRIPTION": ColumnType.STRING,
    "TITLE_SHORT": ColumnType.STRING,
}
_STEPS_COLUMNS = {
    "PROJECT_ID": ColumnType.SMALLINT,
    "STEP": ColumnType.STRING,
    "STEP_ID": ColumnType.INT,  # stable activity id; JOURNEYS.STEP_ID carries the same value
    "DESCRIPTION": ColumnType.STRING,
    "BG_COLOR": ColumnType.STRING,
    "FG_COLOR": ColumnType.STRING,
    "SCORE": ColumnType.DECIMAL,
    "SHAPE": ColumnType.STRING,
    "END_OF_PROCESS": ColumnType.BOOL,
    "BELONGS_TO": ColumnType.STRING,
}
_METAS_COLUMNS = {
    "PROJECT_ID": ColumnType.SMALLINT,
    "META_1_TITLE": ColumnType.STRING,
    "META_2_TITLE": ColumnType.STRING,
    "META_3_TITLE": ColumnType.STRING,
}
_BATCH = 500

# Auto-created steps get a colour + a shape picked deterministically per step name
# (from the shapes the mining app predefines — see StepEditor SHAPES), a white
# foreground and a zero score (so they show but don't skew scoring).
_STEP_PALETTE = [
    "#4a90d9", "#7ed321", "#f5a623", "#bd10e0", "#50e3c2",
    "#e0245e", "#9013fe", "#417505", "#d0021b", "#8b572a",
]
_STEP_SHAPES = ["stadium", "round", "hex", "circle"]


def _step_color(step: str) -> str:
    # crc32 gives a stable, well-distributed index (unlike hash(), which is salted).
    return _STEP_PALETTE[zlib.crc32(step.encode("utf-8")) % len(_STEP_PALETTE)]


def _step_shape(step: str) -> str:
    # Offset the seed so shape and colour don't correlate.
    return _STEP_SHAPES[zlib.crc32(b"shape:" + step.encode("utf-8")) % len(_STEP_SHAPES)]


def _md5(value: str) -> str:
    """Hex MD5 digest — used to pseudonymise EVENT_ID before it's written to JOURNEYS."""
    return hashlib.md5(value.encode("utf-8")).hexdigest()

# The extractor id used both for the registry entry and per-run instances.
FILE_EXTRACTOR_ID = "file"


def file_extractor_info() -> ExtractorInfo:
    return ExtractorInfo(
        id=FILE_EXTRACTOR_ID,
        name="File",
        version="1.0",
        description="Reads a File source line by line and writes JOURNEYS events using "
        "the linked source type's regexes.",
    )


class FileExtractor:
    """A configured run over one File source. ``fields`` is the source type's extraction
    spec (a list of ``{name, role, regex|path}``); ``project_id`` fills JOURNEYS.PROJECT_ID.

    ``fmt`` selects how a record's field values are located: ``"text"`` (regex per line),
    ``"json"`` (JSON path per object) or ``"xml"`` (XPath-subset per element). The record
    source varies with format and trigger — see :meth:`_raw_records`.
    """

    info = file_extractor_info()

    def __init__(
        self,
        *,
        path: str,
        encoding: str,
        fields: list[dict],
        project_id: str,  # the TITLE_SHORT code the user typed; the int PROJECT_ID is allocated
        fmt: str = FORMAT_TEXT,
        record_path: str = "",
        lines: list[str] | None = None,
        line_stream=None,
        line_total: int | None = None,
        records=None,
        record_total: int | None = None,
        compound: list[dict] | None = None,
    ) -> None:
        self._path = path
        self._encoding = encoding or "utf-8"
        self._title_short = project_id  # the human code; PROJECT_ID is allocated in run()
        self._project_id: int | None = None
        self._fmt = fmt if fmt in (FORMAT_TEXT, FORMAT_JSON, FORMAT_XML) else FORMAT_TEXT
        self._record_path = record_path or ""
        # Incremental (watchdog) mode: when ``lines`` is given, those exact lines are
        # extracted instead of reading the whole file — the caller has already read only
        # the newly-appended lines from the file's checkpoint offset. For a JSONL source
        # each line is one JSON object; for text each line is one record.
        self._lines = lines
        # Streaming delta mode (manual run): an iterable that yields all appended lines,
        # draining the file to EOF in bounded chunks (see files.DeltaReader). Kept
        # separate from ``lines`` so its length is never taken (it is a generator).
        self._line_stream = line_stream
        self._line_total = line_total
        # Whole-file structured mode: an already-parsed iterable of records — JSON objects
        # (a top-level array) or XML elements (the repeating record element).
        self._records = records
        self._record_total = record_total

        # ── field → value locators, unified across formats ─────────────────────
        # Every field yields a value by NAME, so id/step/timestamp/meta selection and
        # compound rules all read one ``{name: value}`` dict regardless of format.
        self._named: list[tuple[str, object]] = []
        for f in fields:
            name = str(f.get("name") or "").strip()
            if not name:
                continue
            if self._fmt == FORMAT_TEXT:
                locator = self._compile(f.get("regex", ""))
            else:
                locator = str(f.get("path") or "").strip()
            self._named.append((name, locator))

        def _first_name(role: str) -> str:
            for f in fields:
                if f.get("role") == role and str(f.get("name") or "").strip():
                    return str(f["name"]).strip()
            return ""

        self._ts_name = _first_name("timestamp")
        self._id_name = _first_name("id")
        self._step_name = _first_name("step")
        meta_fields = [
            f for f in fields if f.get("role") == "meta" and str(f.get("name") or "").strip()
        ][:3]
        self._meta_names = [str(f["name"]).strip() for f in meta_fields]
        # Business names for META_1..3 — only the explicitly-given titles (a METAS row
        # is written only when at least one is set).
        self._meta_titles = [(f.get("title") or "").strip() for f in meta_fields]
        # Compound steps (optional): rules that derive the final STEP from several field
        # values. Every named field — including "aux" helper fields that are extracted
        # but written to no column — is available to them.
        self._compound = CompoundRules(compound)
        self._seen_steps: set[str] = set()
        # Stable per-project activity ids (STEP name → int). Seeded from existing
        # STEPS in run(); new names get the next id. JOURNEYS.STEP_ID and
        # STEPS.STEP_ID both carry this id so the transition query groups on it.
        self._step_ids: dict[str, int] = {}
        self._next_step_id: int = 1

    @staticmethod
    def _compile(pattern: str):
        try:
            return _rx.compile(pattern)
        except Exception:  # noqa: BLE001 — any bad pattern simply yields no matches
            return None

    @staticmethod
    def _capture(rx, line: str) -> str | None:
        if rx is None:
            return None
        try:
            m = rx.search(line, **_MATCH_KW)
        except TimeoutError:
            # Catastrophic backtracking on this line. The regexes come from the user's
            # source type and run against every line of the log (and inside the
            # watchdog's background loop) — and CPython's `re` does NOT release the GIL,
            # so an unbounded match would freeze the whole backend process, not just
            # this worker. Skip the line instead; it is counted as unparseable.
            return None
        if not m:
            return None
        return m.group(1) if m.groups() else m.group(0)

    def _values(self, record) -> dict[str, str | None]:
        """The ``{field name → value}`` map for one record, by the configured format.

        text: each field's regex is searched in the line. json: each field's path is
        resolved in the object. xml: each field's selector is resolved in the element.
        A record that isn't the shape the format expects (e.g. a non-object JSONL line)
        yields an empty map, so it is counted as unparseable and skipped.
        """
        if self._fmt == FORMAT_TEXT:
            return {name: self._capture(loc, record) for name, loc in self._named}
        if self._fmt == FORMAT_JSON:
            if not isinstance(record, dict):
                return {}
            return {name: scalar(json_path(record, loc)) for name, loc in self._named}
        # XML
        return {name: xml_value(record, loc) for name, loc in self._named}

    def _line_source(self):
        """The line iterable for a text/JSONL run: a streaming delta drain (manual run),
        the exact lines the watchdog handed us, or a whole-file read."""
        if self._line_stream is not None:
            return self._line_stream, (self._line_total or 0)
        if self._lines is not None:
            return self._lines, len(self._lines)
        return iter_lines(self._path, self._encoding), count_lines(self._path, self._encoding)

    def _raw_records(self):
        """Yield the run's raw records (and a total for the progress bar).

        * text — the source lines (strings);
        * json — either an already-parsed array/whole-file iterable of objects, or, in
          byte-delta (JSONL) mode, one ``json.loads`` per appended line (unparseable
          lines pass through as ``None`` so they're counted as skipped, never crash);
        * xml — the repeating record elements handed in by the caller.
        """
        if self._fmt == FORMAT_XML:
            records = self._records if self._records is not None else []
            total = self._record_total
            if total is None:
                try:
                    total = len(records)
                except TypeError:
                    total = 0
            return records, total
        if self._fmt == FORMAT_JSON and self._records is not None:
            records = self._records
            total = self._record_total
            if total is None:
                try:
                    total = len(records)
                except TypeError:
                    total = 0
            return records, total
        source, total = self._line_source()
        if self._fmt == FORMAT_JSON:
            return self._json_lines(source), total
        return source, total

    @staticmethod
    def _json_lines(lines):
        """Parse each JSONL line into an object; unparseable lines yield ``None``."""
        for line in lines:
            text = line.strip() if isinstance(line, str) else line
            if not text:
                continue
            try:
                yield json.loads(text)
            except (TypeError, ValueError):
                yield None

    def run(self, session: IngestSession) -> ExtractResult:
        session.define_table("JOURNEYS", _JOURNEYS_COLUMNS, keys=["PROJECT_ID", "EVENT_ID", "STEP"])
        session.define_table("PROJECTS", _PROJECTS_COLUMNS, keys=["PROJECT_ID"])
        session.define_table("STEPS", _STEPS_COLUMNS, keys=["PROJECT_ID", "STEP"])

        # Seed the activity-id map from any steps this project already has, so a
        # re-import reuses their ids; new step names continue from the max.
        self._step_ids = session.existing_step_ids()
        self._next_step_id = max(self._step_ids.values(), default=0) + 1

        # Resolve the target project id: reuse the existing project with this TITLE_SHORT
        # code (append), else allocate the next free SMALLINT. PROJECT_ID is an integer now.
        existing_projects = session.existing_project_ids()
        self._project_id = existing_projects.get(
            self._title_short, max(existing_projects.values(), default=0) + 1
        )

        source, total = self._raw_records()
        session.log(
            f"reading {self._path} [{self._fmt}] → {session.schema}.JOURNEYS "
            f"(project {self._project_id})"
        )
        session.progress(0, total or 0)

        batch: list[dict] = []
        written = 0
        skipped = 0
        processed = 0
        for record in source:
            processed += 1
            row = self._row_from_values(self._values(record)) if record is not None else None
            if row is None:
                skipped += 1
            else:
                batch.append(row)
                if len(batch) >= _BATCH:
                    written += session.push("JOURNEYS", batch)
                    batch = []
            if processed % 200 == 0:
                session.progress(processed)
        if batch:
            written += session.push("JOURNEYS", batch)
        session.progress(processed)

        session.log(f"pushed {written} events, skipped {skipped} unparseable line(s)")
        # Make sure the project + its meta titles exist and every step seen is defined.
        project_created = self._ensure_project(session)
        self._ensure_metas(session)
        steps_created = self._ensure_steps(session)

        detail = f"{written} events written, {skipped} skipped"
        if steps_created:
            detail += f", {steps_created} new step(s)"
        if project_created:
            detail += ", project created"
        return ExtractResult(
            records=written, skipped=skipped,
            tables=("JOURNEYS", "PROJECTS", "STEPS", "METAS"), detail=detail,
        )

    def _ensure_project(self, session: IngestSession) -> bool:
        """Create the PROJECTS row for this run's project id if it isn't there yet."""
        if (str(self._project_id),) in session.existing_keys("PROJECTS", ["PROJECT_ID"]):
            return False
        session.push("PROJECTS", [{
            "PROJECT_ID": self._project_id, "TITLE": self._title_short,
            "DESCRIPTION": "", "TITLE_SHORT": self._title_short,
        }])
        session.log(f"created project {self._title_short!r} (id {self._project_id})")
        return True

    def _ensure_metas(self, session: IngestSession) -> bool:
        """Create the METAS row (the META_1..3 business names) for this project if it
        isn't there yet. Skipped when no meta business names are configured."""
        titles = (self._meta_titles + ["", "", ""])[:3]
        if not any(titles):
            return False
        session.define_table("METAS", _METAS_COLUMNS, keys=["PROJECT_ID"])
        if (str(self._project_id),) in session.existing_keys("METAS", ["PROJECT_ID"]):
            return False
        session.push("METAS", [{
            "PROJECT_ID": self._project_id,
            "META_1_TITLE": titles[0], "META_2_TITLE": titles[1], "META_3_TITLE": titles[2],
        }])
        session.log(f"created meta titles: {', '.join(t for t in titles if t)}")
        return True

    def _activity_id(self, step: str) -> int:
        """Stable integer id for a step name, allocating the next id on first sight."""
        sid = self._step_ids.get(step)
        if sid is None:
            sid = self._next_step_id
            self._step_ids[step] = sid
            self._next_step_id += 1
        return sid

    def _ensure_steps(self, session: IngestSession) -> int:
        """Create a STEPS definition (shape + colour, zero score) for every step seen
        that doesn't already exist for this project. Returns how many were created."""
        existing = session.existing_keys("STEPS", ["PROJECT_ID", "STEP"])
        new = [s for s in sorted(self._seen_steps) if (str(self._project_id), s) not in existing]
        if not new:
            return 0
        session.push("STEPS", [{
            "PROJECT_ID": self._project_id, "STEP": s, "STEP_ID": self._activity_id(s),
            "DESCRIPTION": "",
            "BG_COLOR": _step_color(s), "FG_COLOR": "#ffffff", "SCORE": 0,
            "SHAPE": _step_shape(s), "END_OF_PROCESS": False, "BELONGS_TO": None,
        } for s in new])
        session.log(f"created {len(new)} new step(s): {', '.join(new)}")
        return len(new)

    def _row_from_values(self, values: dict[str, str | None]) -> dict | None:
        """Map one record's extracted ``{name: value}`` onto a JOURNEYS row (or ``None``
        when the record lacks the case id / step / timestamp a journey event needs).

        Shared by every format — the only per-format work (regex vs JSON path vs XPath)
        already happened in :meth:`_values`.
        """
        event_id = values.get(self._id_name) if self._id_name else None
        step = values.get(self._step_name) if self._step_name else None
        ts_raw = values.get(self._ts_name) if self._ts_name else None
        # A journey event needs at least a case id, a step and a time.
        if not (event_id and step and ts_raw):
            return None
        event_time = self._to_datetime(ts_raw)
        if event_time is None:
            return None
        # Compound steps: when rules are configured, the final STEP may be derived from
        # several fields at once (e.g. step "login" + status "200" → "login successful").
        # The plain step value stands whenever no rule matches, so rules are additive.
        if self._compound:
            step = self._compound.derive(values) or step
        self._seen_steps.add(step)
        metas = [values.get(n) for n in self._meta_names]
        metas += [None] * (3 - len(metas))
        return {
            "PROJECT_ID": self._project_id,
            # EVENT_ID is pseudonymised: the raw case id (which may be a login/user id)
            # is never written in the clear — only its MD5 digest lands in JOURNEYS.
            "EVENT_ID": _md5(event_id),
            "STEP": step,
            "STEP_ID": self._activity_id(step),
            "EVENT_TIME": event_time,
            "META_1": metas[0],
            "META_2": metas[1],
            "META_3": metas[2],
            "SAMPLE_SET": "ORIGINAL",
        }

    @staticmethod
    def _to_datetime(value: str) -> datetime | None:
        normalized = analyze_timestamp(value).get("normalized")
        if not normalized:
            return None
        try:
            return datetime.strptime(normalized, TIMESTAMP_TARGET)
        except ValueError:
            return None


class _FileExtractorDescriptor:
    """Registry-only entry so ``/extractors`` lists the File extractor. Actual runs use a
    per-run configured :class:`FileExtractor`, not this stub."""

    info = file_extractor_info()

    def run(self, session: IngestSession) -> ExtractResult:  # noqa: ARG002
        raise IngestError("The File extractor is run per source, not from the registry.")


def register_builtin_extractors(layer) -> None:
    """Register the built-in extractor descriptors on ``layer`` (idempotent)."""
    if layer.get(FILE_EXTRACTOR_ID) is None:
        layer.register(_FileExtractorDescriptor())
