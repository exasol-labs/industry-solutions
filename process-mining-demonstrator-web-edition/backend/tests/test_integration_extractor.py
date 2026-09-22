"""FileExtractor: reads a File source line by line, applies a source type's regexes and
pushes normalised JOURNEYS rows through the abstraction layer (in-memory target here)."""

from __future__ import annotations

import asyncio
import hashlib
import importlib
from datetime import datetime

import pytest


def _md5(value: str) -> str:
    return hashlib.md5(value.encode("utf-8")).hexdigest()


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("PMW_INTEGRATION_FILES_DIR", str(tmp_path / "files"))
    monkeypatch.delenv("PMW_INTEGRATION_ALLOW_ANY_PATH", raising=False)
    import app.config as config

    importlib.reload(config)
    import app.integration.files as files_mod

    importlib.reload(files_mod)
    import app.integration.extractors as extractors_mod

    importlib.reload(extractors_mod)
    from app.integration import AbstractionLayer, InMemoryIngestBackend

    return config, extractors_mod, AbstractionLayer, InMemoryIngestBackend


FIELDS = [
    {"name": "timestamp", "role": "timestamp",
     "regex": r"\[(\d{2}/[A-Za-z]{3}/\d{4}:\d{2}:\d{2}:\d{2} [+-]\d{4})\]"},
    {"name": "event_id", "role": "id", "regex": r"userId=(\d+)"},
    {"name": "step", "role": "step", "regex": r'"[A-Z]+ /shop/([a-z]+)'},
    {"name": "bookId", "role": "meta", "regex": r"bookId=(B-\d+)"},
]

LINE_A = ('10.0.0.1 - - [09/Jan/2015:19:12:14 +0000] 15233 '
          '"GET /shop/view?userId=20253471&bookId=B-1001 HTTP/1.1" 200 8241 "-" "UA"')
LINE_B = ('10.0.0.2 - - [09/Jan/2015:19:12:52 +0000] 7994 '
          '"POST /shop/basket?userId=44189320&bookId=B-3003 HTTP/1.1" 200 341 "-" "UA"')
GARBAGE = "this line has no timestamp, id or step"


def test_file_extractor_writes_normalised_journeys_rows(env):
    config, extractors_mod, AbstractionLayer, InMemoryIngestBackend = env
    (config.INTEGRATION_FILES_DIR / "access.log").write_text(
        "\n".join([LINE_A, GARBAGE, LINE_B]) + "\n"
    )

    layer = AbstractionLayer()
    mem = InMemoryIngestBackend()
    extractor = extractors_mod.FileExtractor(
        path="access.log", encoding="utf-8", fields=FIELDS, project_id="RETAIL",
    )
    result = asyncio.run(layer.run(user="dev", extractor=extractor, backend=mem, schema="MINING"))

    assert result.records == 2  # the garbage line is skipped
    rows = mem.tables["MINING"]["JOURNEYS"]["rows"]
    assert len(rows) == 2

    a = rows[0]
    assert a["PROJECT_ID"] == 1  # allocated SMALLINT
    # EVENT_ID is the MD5 digest of the raw case id, never the raw value itself.
    assert a["EVENT_ID"] == _md5("20253471")
    assert a["STEP"] == "view"
    assert a["META_1"] == "B-1001"
    assert a["SAMPLE_SET"] == "ORIGINAL"
    # EVENT_TIME is a real datetime, normalised from the Apache/CLF timestamp.
    assert a["EVENT_TIME"] == datetime(2015, 1, 9, 19, 12, 14)

    assert rows[1]["EVENT_ID"] == _md5("44189320") and rows[1]["STEP"] == "basket"


def test_file_extractor_status_and_detail(env):
    config, extractors_mod, AbstractionLayer, InMemoryIngestBackend = env
    (config.INTEGRATION_FILES_DIR / "access.log").write_text(LINE_A + "\n")
    layer = AbstractionLayer()
    extractor = extractors_mod.FileExtractor(
        path="access.log", encoding="utf-8", fields=FIELDS, project_id="P",
    )
    asyncio.run(layer.run(user="dev", extractor=extractor, backend=InMemoryIngestBackend(), schema="S"))
    st = layer.status_for("dev").public()
    assert st["state"] == "completed"
    # 1 event + its project row + 1 new step definition were all pushed.
    assert st["recordsPushed"] == 3
    assert set(st["tablesTouched"]) == {"JOURNEYS", "PROJECTS", "STEPS"}


def test_run_reports_progress_totals(env):
    config, extractors_mod, AbstractionLayer, InMemoryIngestBackend = env
    # Three non-blank lines (blank lines aren't counted toward the total).
    (config.INTEGRATION_FILES_DIR / "access.log").write_text(
        "\n".join([LINE_A, LINE_B, "", GARBAGE]) + "\n"
    )
    layer = AbstractionLayer()
    ext = extractors_mod.FileExtractor(path="access.log", encoding="utf-8", fields=FIELDS, project_id="P")
    asyncio.run(layer.run(user="dev", extractor=ext, backend=InMemoryIngestBackend(), schema="S"))
    st = layer.status_for("dev").public()
    # The progress denominator counts every non-blank line; done reaches the total.
    assert st["recordsTotal"] == 3
    assert st["recordsDone"] == 3


def test_incremental_lines_mode_only_extracts_the_given_lines(env):
    """The watchdog hands the extractor just the newly-appended lines (not the whole
    file); only those become JOURNEYS rows."""
    config, extractors_mod, AbstractionLayer, InMemoryIngestBackend = env
    # The file on disk has more, but we only pass ONE new line.
    (config.INTEGRATION_FILES_DIR / "access.log").write_text("\n".join([LINE_A, LINE_B]) + "\n")
    mem = InMemoryIngestBackend()
    ext = extractors_mod.FileExtractor(
        path="access.log", encoding="utf-8", fields=FIELDS, project_id="P", lines=[LINE_B],
    )
    result = asyncio.run(AbstractionLayer().run(user="dev", extractor=ext, backend=mem, schema="S"))
    rows = mem.tables["S"]["JOURNEYS"]["rows"]
    assert result.records == 1 and len(rows) == 1
    assert rows[0]["EVENT_ID"] == _md5("44189320") and rows[0]["STEP"] == "basket"


def test_run_records_origin_for_the_pipeline_canvas(env):
    config, extractors_mod, AbstractionLayer, InMemoryIngestBackend = env
    (config.INTEGRATION_FILES_DIR / "access.log").write_text(LINE_A + "\n")
    layer = AbstractionLayer()
    ext = extractors_mod.FileExtractor(path="access.log", encoding="utf-8", fields=FIELDS, project_id="P")
    asyncio.run(layer.run(
        user="dev", extractor=ext, backend=InMemoryIngestBackend(), schema="S",
        connection_id="c1", connection_name="Prod DB",
        source_name="Access log", source_type_name="Apache log",
    ))
    st = layer.status_for("dev").public()
    # The origin is surfaced so the console's live pipeline can label its nodes.
    assert st["sourceName"] == "Access log"
    assert st["sourceTypeName"] == "Apache log"
    assert st["connectionName"] == "Prod DB"


def test_file_extractor_rejects_paths_outside_sandbox(env):
    config, extractors_mod, AbstractionLayer, InMemoryIngestBackend = env
    from app.integration.files import FileAccessError

    layer = AbstractionLayer()
    extractor = extractors_mod.FileExtractor(
        path="/etc/passwd", encoding="utf-8", fields=FIELDS, project_id="P",
    )
    with pytest.raises(FileAccessError):
        asyncio.run(layer.run(user="dev", extractor=extractor, backend=InMemoryIngestBackend(), schema="S"))


def test_run_creates_project_and_step_definitions(env):
    config, extractors_mod, AbstractionLayer, InMemoryIngestBackend = env
    (config.INTEGRATION_FILES_DIR / "access.log").write_text("\n".join([LINE_A, LINE_B]) + "\n")
    mem = InMemoryIngestBackend()
    ext = extractors_mod.FileExtractor(path="access.log", encoding="utf-8", fields=FIELDS, project_id="RETAIL")
    asyncio.run(AbstractionLayer().run(user="dev", extractor=ext, backend=mem, schema="MINING"))

    # The project row is created.
    assert mem.tables["MINING"]["PROJECTS"]["rows"] == [
        {"PROJECT_ID": 1, "TITLE": "RETAIL", "DESCRIPTION": "", "TITLE_SHORT": "RETAIL"}]
    # One STEPS definition per distinct step, with a shape + colour + zero score.
    steps = {r["STEP"]: r for r in mem.tables["MINING"]["STEPS"]["rows"]}
    assert set(steps) == {"view", "basket"}  # LINE_A → view, LINE_B → basket
    for r in steps.values():
        assert r["SCORE"] == 0
        assert r["SHAPE"] in {"stadium", "round", "hex", "circle"}
        assert r["BG_COLOR"].startswith("#") and r["FG_COLOR"] == "#ffffff"
        assert r["END_OF_PROCESS"] is False


def test_existing_project_and_steps_are_not_recreated(env):
    config, extractors_mod, AbstractionLayer, InMemoryIngestBackend = env
    (config.INTEGRATION_FILES_DIR / "access.log").write_text(LINE_A + "\n")  # step "view"
    mem = InMemoryIngestBackend()
    mem.create_table("MINING", "PROJECTS", extractors_mod._PROJECTS_COLUMNS, ["PROJECT_ID"])
    mem.insert("MINING", "PROJECTS", ["PROJECT_ID", "TITLE_SHORT"], [[1, "RETAIL"]])
    mem.create_table("MINING", "STEPS", extractors_mod._STEPS_COLUMNS, ["PROJECT_ID", "STEP"])
    mem.insert("MINING", "STEPS", ["PROJECT_ID", "STEP"], [[1, "view"]])

    ext = extractors_mod.FileExtractor(path="access.log", encoding="utf-8", fields=FIELDS, project_id="RETAIL")
    res = asyncio.run(AbstractionLayer().run(user="dev", extractor=ext, backend=mem, schema="MINING"))
    assert "new step" not in res.detail and "project created" not in res.detail
    assert len(mem.tables["MINING"]["STEPS"]["rows"]) == 1
    assert len(mem.tables["MINING"]["PROJECTS"]["rows"]) == 1


def test_run_creates_meta_titles(env):
    config, extractors_mod, AbstractionLayer, InMemoryIngestBackend = env
    (config.INTEGRATION_FILES_DIR / "access.log").write_text(LINE_A + "\n")
    fields = FIELDS + []  # FIELDS' meta is bookId; give it a business name
    fields = [{**f, "title": "Book ID"} if f.get("role") == "meta" else f for f in FIELDS]
    mem = InMemoryIngestBackend()
    ext = extractors_mod.FileExtractor(path="access.log", encoding="utf-8", fields=fields, project_id="RETAIL")
    asyncio.run(AbstractionLayer().run(user="dev", extractor=ext, backend=mem, schema="MINING"))
    assert mem.tables["MINING"]["METAS"]["rows"] == [{
        "PROJECT_ID": 1, "META_1_TITLE": "Book ID", "META_2_TITLE": "", "META_3_TITLE": "",
    }]


def test_catastrophic_regex_cannot_hang_the_extractor(env):
    """Source-type regexes are user-authored and run against EVERY line — including
    inside the watchdog's background loop. CPython's `re` does not release the GIL, so
    an unbounded match would freeze the whole backend process, not just one worker."""
    import time as _time

    config, extractors_mod, AbstractionLayer, InMemoryIngestBackend = env
    evil = [
        {"name": "timestamp", "role": "timestamp", "regex": r"(a+)+$"},
        {"name": "event_id", "role": "id", "regex": r"userId=(\d+)"},
        {"name": "step", "role": "step", "regex": r"step=(\w+)"},
    ]
    line = "userId=1 step=x " + "a" * 60 + "!"
    (config.INTEGRATION_FILES_DIR / "evil.log").write_text(line + "\n")

    ext = extractors_mod.FileExtractor(
        path="evil.log", encoding="utf-8", fields=evil, project_id="P",
    )
    started = _time.perf_counter()
    result = asyncio.run(
        AbstractionLayer().run(user="dev", extractor=ext, backend=InMemoryIngestBackend(), schema="S")
    )
    elapsed = _time.perf_counter() - started
    # The line is skipped (no timestamp captured) rather than hanging the process.
    assert result.records == 0
    assert elapsed < 10, f"extraction took {elapsed:.1f}s — the match was not bounded"
