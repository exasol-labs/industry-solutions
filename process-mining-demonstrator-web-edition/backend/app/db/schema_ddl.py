"""Canonical process-mining schema — the single source of truth for the tables
the app reads and writes, and a helper that provisions them on demand.

The source tables (PROJECTS, JOURNEYS, STEPS, METAS) normally arrive with the
customer's data; NOTES is created lazily by the app. This module lets an operator
(an admin, or a power user from the app) create a *fresh* schema with the full,
empty table structure so process-mining data can be loaded into it — provided the
database account has the CREATE SCHEMA / CREATE TABLE privileges (which only a
database administrator can grant; the app cannot).

All statements use IF NOT EXISTS so provisioning is idempotent and never disturbs
an existing schema's data.
"""

from __future__ import annotations

import os

# A long, one-shot in-database sample build must not be cut off by the interactive
# 300 s socket-read timeout (pyexasol arms it once and never resets it per statement),
# which is why the same INSERT finishes in DBVisualizer but stalls/errors here. Give the
# build's own connection a generous read timeout (default 6 h; override with the env var).
_SAMPLE_SOCKET_TIMEOUT = int(os.environ.get("PMW_SAMPLE_SOCKET_TIMEOUT_SECS", str(6 * 3600)))

# Kept byte-for-byte in sync with ProcessRepository.ensure_notes_table (which
# imports this constant), so a provisioned NOTES table matches what the app uses.
NOTES_DDL = """
CREATE TABLE IF NOT EXISTS NOTES (
    ID              VARCHAR(36)   NOT NULL,
    PROJECT_ID      SMALLINT     NOT NULL,
    NOTES_DATE      TIMESTAMP     NOT NULL,
    EDITED_DATE     TIMESTAMP,
    NOTE_USER       VARCHAR(200)  DEFAULT '',
    NOTE            VARCHAR(100000) DEFAULT '',
    IS_SHARED       BOOLEAN       DEFAULT FALSE,
    EDITED_BY       VARCHAR(200)  DEFAULT '',
    IMPORTANCE      VARCHAR(20)   DEFAULT 'NORMAL',
    RESOLVED        BOOLEAN       DEFAULT FALSE,
    TITLE           VARCHAR(500)  DEFAULT '',
    TARGET_TYPE     VARCHAR(10)   DEFAULT 'node',
    TARGET_FROM     VARCHAR(500)  DEFAULT '',
    TARGET_TO       VARCHAR(500),
    FILTER_SNAPSHOT VARCHAR(4000),
    PRIMARY KEY (ID)
)
"""

_PROJECTS_DDL = """
CREATE TABLE IF NOT EXISTS PROJECTS (
    PROJECT_ID  SMALLINT      NOT NULL,
    TITLE       VARCHAR(100)  DEFAULT '',
    DESCRIPTION VARCHAR(2000) DEFAULT '',
    -- Human-readable short code (e.g. 'APF'); the PROJECT_ID is an allocated integer.
    -- A leading '#' marks an aggregate DETAIL project (hidden), 'Σ' a high-level one.
    TITLE_SHORT VARCHAR(10)   DEFAULT '',
    PRIMARY KEY (PROJECT_ID)
)
"""

# The event log: one row per (event, step). STEP_ID orders steps that share an
# EVENT_TIME. SAMPLE_SET tags rows copied into a sample ('ORIGINAL' = source data).
#
# DISTRIBUTE BY EVENT_ID co-locates every event of a journey on one cluster node,
# so the transition query's LEAD() OVER (PARTITION BY EVENT_ID ...) and every
# filter's GROUP BY EVENT_ID run node-local with no cross-node redistribution.
# EVENT_ID is high-cardinality, so rows spread evenly.
#
# PARTITION BY EVENT_TIME lets Exasol prune by date range — chiefly the
# "active in window" EVENT_ID selection behind the last-N-days default and the
# date filter. (The main scan still fetches whole journeys by EVENT_ID, which can
# span partitions, so pruning helps the ID selection more than the final scan.)
# The partition column must differ from the distribution column, which holds here
# (EVENT_TIME vs EVENT_ID). If EVENT_TIME cardinality is extreme, a day-truncated
# EVENT_DATE column would partition more coarsely — but that needs an extra column
# the data load must populate, so EVENT_TIME is the zero-ETL-change default.
#
# Existing tables are unaffected by IF NOT EXISTS — apply to those with
#   ALTER TABLE JOURNEYS DISTRIBUTE BY EVENT_ID;
#   ALTER TABLE JOURNEYS PARTITION  BY EVENT_TIME;
_JOURNEYS_DDL = """
CREATE TABLE IF NOT EXISTS JOURNEYS (
    PROJECT_ID SMALLINT     NOT NULL,
    -- EVENT_ID holds a 32-char MD5 hash (from _md5_id / the integration
    -- extractors), so a 16-byte HASHTYPE stores it exactly. HASHTYPE is a
    -- fixed-length binary type: joins, GROUP BY, DISTRIBUTE BY and the
    -- transition window run on 16 bytes instead of a 32-char string, which
    -- speeds up the whole DFG pipeline. Hex string literals convert implicitly,
    -- so inserts and `EVENT_ID = '<hex>'` comparisons keep working unchanged.
    EVENT_ID   HASHTYPE(16 BYTE) NOT NULL,
    STEP       VARCHAR(500)  NOT NULL,
    STEP_ID    DECIMAL(18,0),
    EVENT_TIME TIMESTAMP     NOT NULL,
    META_1     VARCHAR(1000),
    META_2     VARCHAR(1000),
    META_3     VARCHAR(1000),
    SAMPLE_SET VARCHAR(20)   DEFAULT 'ORIGINAL',
    DISTRIBUTE BY EVENT_ID,
    PARTITION BY EVENT_TIME
)
"""

# `CREATE TABLE IF NOT EXISTS` above sets the distribution on a NEW JOURNEYS, but is a
# no-op for one that already exists — e.g. a table that predates this change or was loaded
# by an external ETL. Provisioning enforces it with this ALTER, but only when EVENT_ID is
# not already the distribution key (the check below reads EXA_ALL_COLUMNS), so a
# re-provision is a genuine no-op and never triggers a needless (and costly) redistribution.
_JOURNEYS_DISTRIBUTE_SQL = "ALTER TABLE JOURNEYS DISTRIBUTE BY EVENT_ID"
_JOURNEYS_HAS_DIST_KEY_SQL = """
SELECT COUNT(*) FROM EXA_ALL_COLUMNS
WHERE COLUMN_SCHEMA = CURRENT_SCHEMA
  AND COLUMN_TABLE = 'JOURNEYS'
  AND COLUMN_NAME = 'EVENT_ID'
  AND COLUMN_IS_DISTRIBUTION_KEY = TRUE
"""

# Per-step presentation and scoring, edited from the app's Step editor.
_STEPS_DDL = """
CREATE TABLE IF NOT EXISTS STEPS (
    PROJECT_ID     SMALLINT     NOT NULL,
    STEP           VARCHAR(500)  NOT NULL,
    -- Stable integer activity id (unique per PROJECT_ID). JOURNEYS.STEP_ID carries
    -- the same value, so the transition query groups/joins/partitions on this
    -- integer and maps back to STEP names only in its final projection.
    STEP_ID        DECIMAL(18,0),
    DESCRIPTION    VARCHAR(2000) DEFAULT '',
    BG_COLOR       VARCHAR(30)   DEFAULT '',
    FG_COLOR       VARCHAR(30)   DEFAULT '',
    SCORE          DECIMAL(18,2),
    SHAPE          VARCHAR(50)   DEFAULT '',
    END_OF_PROCESS BOOLEAN       DEFAULT FALSE,
    BELONGS_TO     VARCHAR(500),
    PRIMARY KEY (PROJECT_ID, STEP)
)
"""

# Human-readable titles for the three META columns, per project.
_METAS_DDL = """
CREATE TABLE IF NOT EXISTS METAS (
    PROJECT_ID   SMALLINT    NOT NULL,
    META_1_TITLE VARCHAR(500) DEFAULT '',
    META_2_TITLE VARCHAR(500) DEFAULT '',
    META_3_TITLE VARCHAR(500) DEFAULT '',
    PRIMARY KEY (PROJECT_ID)
)
"""

# (name, DDL) in creation order. NOTES is included so a provisioned schema is
# immediately complete for both reads and the app's own writes.
PROCESS_MINING_TABLES: list[tuple[str, str]] = [
    ("PROJECTS", _PROJECTS_DDL),
    ("JOURNEYS", _JOURNEYS_DDL),
    ("STEPS", _STEPS_DDL),
    ("METAS", _METAS_DDL),
    ("NOTES", NOTES_DDL),
]

TABLE_NAMES: list[str] = [name for name, _ in PROCESS_MINING_TABLES]


# Optional pre-materialised directly-follows pairs (backlog item #3). Built on
# demand per connection; the transition query reads it instead of running the
# LEAD() window on every request. One row per consecutive step-pair, carrying the
# precomputed gap so the map's timing aggregates are pure MIN/MAX/AVG/STDDEV.
#
# Built with CREATE TABLE AS SELECT so every column INHERITS its type from
# JOURNEYS/STEPS — critically EVENT_ID, which varies by deployment (VARCHAR,
# HASHTYPE, DECIMAL, …). Hard-coding it (e.g. VARCHAR) breaks the read query:
# the semi-join `TRANSITIONS_RAW.EVENT_ID IN (SELECT JOURNEYS.EVENT_ID …)` then
# compares mismatched types and Exasol raises "Incomparable Types". Distribution
# is applied afterwards with ALTER (CTAS can't declare it inline).
MATERIALIZED_TRANSITIONS_TABLE = "TRANSITIONS_RAW"


def _quote_ident(name: str) -> str:
    """Quote an Exasol identifier, guarding against injection in the schema name."""
    return '"' + name.replace('"', '""') + '"'


async def rebuild_materialized_transitions(
    *,
    host: str,
    port: int,
    username: str,
    password: str,
    schema: str,
    use_tls: bool = False,
    cert_mode: str = "verify",
    fingerprint: str = "",
    min_rsa_bits: int = 2048,
) -> dict:
    """(Re)build ``TRANSITIONS_RAW`` in ``schema`` from its ``JOURNEYS`` table.

    Runs the expensive ``LEAD()`` pairing once and stores the result, so the
    per-request transition query can drop the window function. The fresh copy is
    built in a staging table alongside the live one and swapped in with a RENAME,
    so readers are never blocked by the build and only ever see a complete table
    (a sub-millisecond gap during the swap falls back to the live query).

    Returns ``{"ok", "error", "rows", "built_at"}`` — ``rows`` is the pair count,
    ``built_at`` an ISO-8601 UTC timestamp. Idempotent and safe to re-run.
    """
    import asyncio
    from datetime import datetime, timezone

    from ..models import DatabaseServer
    from .manager import DatabaseManager, friendly_error

    schema = (schema or "").strip()
    if not schema:
        return {"ok": False, "error": "A schema name is required.", "rows": 0, "built_at": None}

    server = DatabaseServer(
        id="materialize",
        host=host,
        port=port,
        username=username,
        useTLS=use_tls,
        certModeRaw=cert_mode,
        fingerprint=fingerprint,
        minRSAKeySizeBits=min_rsa_bits,
        **{"schema": ""},
    )
    mgr = DatabaseManager.__new__(DatabaseManager)  # no store side effects
    ident = _quote_ident(schema)
    final = MATERIALIZED_TRANSITIONS_TABLE
    stage = f"{final}_STAGE"

    def _run() -> int:
        conn = mgr._open(server, password)
        try:
            conn.execute(f"OPEN SCHEMA {ident}")
            # Build the fresh copy beside the live table so reads are unaffected.
            # CTAS ⇒ column types (esp. EVENT_ID) match JOURNEYS/STEPS exactly.
            conn.execute(
                f"""
                CREATE OR REPLACE TABLE {stage} AS
                SELECT PROJECT_ID, EVENT_ID, FROM_STEP_ID, TO_STEP_ID, FROM_TIME, TO_TIME,
                       SECONDS_BETWEEN(TO_TIME, FROM_TIME) AS DUR_SECS, SAMPLE_SET
                FROM (
                    -- Pairs are built on the integer STEP_ID (activity id); the read
                    -- query maps id → STEP name. This builds pairs for EVERY project +
                    -- sample set at once, so the window MUST partition by (PROJECT_ID,
                    -- SAMPLE_SET, EVENT_ID), not EVENT_ID alone: EVENT_ID is only unique
                    -- within one project and sample set (the same id recurs across
                    -- projects and in a sample's copy of ORIGINAL). The live query scopes
                    -- this by filtering to one project+sample before the LEAD.
                    SELECT PROJECT_ID, EVENT_ID, SAMPLE_SET,
                           STEP_ID    AS FROM_STEP_ID,
                           EVENT_TIME AS FROM_TIME,
                           LEAD(STEP_ID)    OVER (PARTITION BY PROJECT_ID, SAMPLE_SET, EVENT_ID ORDER BY EVENT_TIME, STEP_ID) AS TO_STEP_ID,
                           LEAD(EVENT_TIME) OVER (PARTITION BY PROJECT_ID, SAMPLE_SET, EVENT_ID ORDER BY EVENT_TIME, STEP_ID) AS TO_TIME
                    FROM JOURNEYS
                ) AS t
                WHERE TO_STEP_ID IS NOT NULL AND TO_TIME IS NOT NULL
                """
            )
            # Co-locate by EVENT_ID for the semi-join. Distribution is a pure
            # optimisation, so a failure here must not abort the rebuild.
            try:
                conn.execute(f"ALTER TABLE {stage} DISTRIBUTE BY EVENT_ID")
            except Exception:  # noqa: BLE001
                pass
            rows = conn.execute(f"SELECT COUNT(*) FROM {stage}").fetchval()
            # Swap the fresh copy in. DROP+RENAME leaves a sub-ms window with no
            # live table; the query layer falls back to the live LEAD() for that.
            conn.execute(f"DROP TABLE IF EXISTS {final}")
            conn.execute(f"RENAME TABLE {stage} TO {final}")
            conn.commit()
            return int(rows or 0)
        finally:
            conn.close()

    try:
        rows = await asyncio.to_thread(_run)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": friendly_error(exc), "rows": 0, "built_at": None}
    return {
        "ok": True,
        "error": None,
        "rows": rows,
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


# ── In-database sampling ──────────────────────────────────────────────────────
# Pick and materialise a sample slot entirely inside Exasol — no extract of every
# EVENT_ID to the app and no thousands of batched INSERTs. One INSERT … SELECT
# whose semi-join picks the journeys with pure SQL (window functions + RANDOM()).
# RANDOM() is taken once per journey (on the grouped/distinct rows) so the pick is
# unbiased w.r.t. journey length; temporal/path use clean proportional allocation
# (per-bucket share, surplus trimmed in random order — no ordering bias).

# The ORIGINAL-rows predicate, with an optional table alias.
def _orig_pred(alias: str = "") -> str:
    col = f"{alias}.SAMPLE_SET" if alias else "SAMPLE_SET"
    return f"({col} = 'ORIGINAL' OR {col} IS NULL)"


def _sample_chosen_ids_sql(project_id: int, count: int, method: str) -> str:
    """Subquery selecting ``count`` EVENT_IDs from ORIGINAL by ``method``
    ('random' | 'temporal' | 'pathDiverse')."""
    pid = int(project_id)
    n = int(count)
    orig = _orig_pred()
    if method == "random":
        return f"""
            SELECT EVENT_ID FROM (
              SELECT EVENT_ID, ROW_NUMBER() OVER (ORDER BY r) AS rn
              FROM (
                SELECT EVENT_ID, RANDOM() AS r
                FROM (
                  SELECT DISTINCT EVENT_ID FROM JOURNEYS
                  WHERE PROJECT_ID = {pid} AND {orig}
                )
              )
            ) WHERE rn <= {n}
        """
    if method == "temporal":
        bucket = "TO_CHAR(MIN(EVENT_TIME), 'YYYY-MM')"
    elif method == "pathDiverse":
        bucket = (
            "HASH_MD5(LISTAGG(CAST(STEP_ID AS VARCHAR(20)), '>') "
            "WITHIN GROUP (ORDER BY EVENT_TIME, STEP_ID))"
        )
    else:
        raise ValueError(f"unknown sampling method: {method!r}")
    # Proportional across buckets (calendar month, or journey variant), then a clean
    # random global cap to {N}.
    return f"""
        WITH jr AS (
          SELECT EVENT_ID, {bucket} AS bucket
          FROM JOURNEYS WHERE PROJECT_ID = {pid} AND {orig}
          GROUP BY EVENT_ID
        ),
        jrr AS (SELECT EVENT_ID, bucket, RANDOM() AS r FROM jr),
        sz  AS (SELECT bucket, COUNT(*) AS cnt FROM jr GROUP BY bucket),
        tot AS (SELECT COUNT(*) AS total FROM jr),
        ranked AS (
          SELECT jrr.EVENT_ID, jrr.r,
                 ROW_NUMBER() OVER (PARTITION BY jrr.bucket ORDER BY jrr.r) AS rn_bucket,
                 GREATEST(1, ROUND(sz.cnt / tot.total * {n})) AS share
          FROM jrr JOIN sz ON jrr.bucket = sz.bucket CROSS JOIN tot
        ),
        picked AS (SELECT EVENT_ID, r FROM ranked WHERE rn_bucket <= share)
        SELECT EVENT_ID FROM (
          SELECT EVENT_ID, ROW_NUMBER() OVER (ORDER BY r) AS grn FROM picked
        ) WHERE grn <= {n}
    """


def _sample_insert_sql(project_id: int, count: int, method: str, label: str) -> str:
    """The single INSERT … SELECT that copies the chosen journeys' ORIGINAL rows,
    tagged with the sample slot ``label`` (a SampleSet value, e.g. 'SAMPLE_1')."""
    pid = int(project_id)
    chosen = _sample_chosen_ids_sql(pid, count, method)
    return f"""
        INSERT INTO JOURNEYS
            (PROJECT_ID, EVENT_ID, STEP, STEP_ID, EVENT_TIME, META_1, META_2, META_3, SAMPLE_SET)
        SELECT j.PROJECT_ID, j.EVENT_ID, j.STEP, j.STEP_ID, j.EVENT_TIME,
               j.META_1, j.META_2, j.META_3, '{label}'
        FROM JOURNEYS j
        WHERE j.PROJECT_ID = {pid} AND {_orig_pred('j')}
          AND j.EVENT_ID IN ({chosen})
    """


async def build_sample_in_db(
    *,
    host: str,
    port: int,
    username: str,
    password: str,
    schema: str,
    project_id: str,
    count: int,
    method: str,
    sample_set,
    use_tls: bool = False,
    cert_mode: str = "verify",
    fingerprint: str = "",
    min_rsa_bits: int = 2048,
) -> dict:
    """(Re)build one sample slot for ``project_id`` inside ``schema`` with no app
    round-trip: DELETE the slot, then one INSERT … SELECT that picks ``count``
    journeys from ORIGINAL by ``method`` and copies their rows under the slot label.

    Runs on its own connection with the statement timeout lifted (the whole point —
    a set-based build survives where thousands of batched INSERTs time out).
    Returns ``{"ok", "error", "journeys"}`` (journeys = distinct EVENT_IDs written).
    """
    import asyncio

    from ..models import DatabaseServer
    from .manager import DatabaseManager, friendly_error

    if getattr(sample_set, "is_original", False):
        return {"ok": False, "error": "Cannot overwrite the original data.", "journeys": 0}
    schema = (schema or "").strip()
    if not schema:
        return {"ok": False, "error": "A schema name is required.", "journeys": 0}
    label = sample_set.value
    pid = int(project_id)

    server = DatabaseServer(
        id="sampling", host=host, port=port, username=username,
        useTLS=use_tls, certModeRaw=cert_mode, fingerprint=fingerprint,
        minRSAKeySizeBits=min_rsa_bits, **{"schema": ""},
    )
    mgr = DatabaseManager.__new__(DatabaseManager)  # no store side effects
    ident = _quote_ident(schema)
    insert_sql = _sample_insert_sql(pid, count, method, label)

    def _run() -> int:
        # Generous socket-read timeout so the long INSERT isn't cut off mid-run (the
        # difference from DBVisualizer); QUERY_TIMEOUT is also lifted below.
        conn = mgr._open(server, password, socket_timeout=_SAMPLE_SOCKET_TIMEOUT)
        try:
            conn.execute(f"OPEN SCHEMA {ident}")
            try:
                conn.execute("ALTER SESSION SET QUERY_TIMEOUT = 0")  # long, one-shot build
            except Exception:  # noqa: BLE001 — not fatal if the role can't set it
                pass
            # One explicit transaction for the whole build: the DELETE + INSERT commit
            # together (readers never see the slot half-empty) and there is exactly one
            # COMMIT, instead of pyexasol's per-statement autocommit. Rolled back on error.
            conn.set_autocommit(False)
            try:
                conn.execute(
                    f"DELETE FROM JOURNEYS WHERE PROJECT_ID = {pid} AND SAMPLE_SET = '{label}'"
                )
                conn.execute(insert_sql)
                written = conn.execute(
                    f"SELECT COUNT(DISTINCT EVENT_ID) FROM JOURNEYS "
                    f"WHERE PROJECT_ID = {pid} AND SAMPLE_SET = '{label}'"
                ).fetchval()
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            return int(written or 0)
        finally:
            conn.close()

    try:
        journeys = await asyncio.to_thread(_run)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": friendly_error(exc), "journeys": 0}
    return {"ok": True, "error": None, "journeys": journeys}


async def provision_process_mining_schema(
    *,
    host: str,
    port: int,
    username: str,
    password: str,
    schema: str,
    use_tls: bool = False,
    cert_mode: str = "verify",
    fingerprint: str = "",
    min_rsa_bits: int = 2048,
) -> dict:
    """Create ``schema`` (if absent) and every process-mining table inside it.

    Connects with the supplied credentials, so the account must hold CREATE SCHEMA
    and CREATE TABLE rights. Returns ``{"ok", "error", "created": [names]}`` — a
    friendly error string on failure, with ``created`` listing what was made before
    the failure. Idempotent: re-running against an existing schema is a no-op.
    """
    import asyncio

    from ..models import DatabaseServer
    from .manager import DatabaseManager, friendly_error

    schema = (schema or "").strip()
    if not schema:
        return {"ok": False, "error": "A schema name is required.", "created": []}

    # Connect WITHOUT opening the target schema — it may not exist yet.
    server = DatabaseServer(
        id="provision",
        host=host,
        port=port,
        username=username,
        useTLS=use_tls,
        certModeRaw=cert_mode,
        fingerprint=fingerprint,
        minRSAKeySizeBits=min_rsa_bits,
        **{"schema": ""},
    )
    mgr = DatabaseManager.__new__(DatabaseManager)  # no store side effects
    ident = _quote_ident(schema)
    created: list[str] = []

    def _run() -> None:
        conn = mgr._open(server, password)
        try:
            conn.execute(f"CREATE SCHEMA IF NOT EXISTS {ident}")
            created.append(f"schema {schema}")
            conn.execute(f"OPEN SCHEMA {ident}")
            for name, ddl in PROCESS_MINING_TABLES:
                conn.execute(ddl)
                created.append(name)
            # Enforce EVENT_ID distribution on a JOURNEYS that already existed (the CREATE
            # above skipped it). Guarded so a re-provision, an ETL-loaded table already
            # keyed on EVENT_ID, or a metadata view we can't read never redistributes or
            # aborts provisioning.
            try:
                if not conn.execute(_JOURNEYS_HAS_DIST_KEY_SQL).fetchval():
                    conn.execute(_JOURNEYS_DISTRIBUTE_SQL)
                    created.append("JOURNEYS distribution (EVENT_ID)")
            except Exception:  # noqa: BLE001 — best-effort; keep schema creation green
                pass
            conn.commit()
        finally:
            conn.close()

    try:
        await asyncio.to_thread(_run)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": friendly_error(exc), "created": created}
    return {"ok": True, "error": None, "created": created}


def _server_for(schema: str, *, host, port, username, use_tls, cert_mode, fingerprint, min_rsa_bits):
    """A throwaway DatabaseServer for a one-off admin query. Connects WITHOUT opening a
    schema (we OPEN SCHEMA explicitly), so it works even before provisioning."""
    from ..models import DatabaseServer

    return DatabaseServer(
        id="admin-query",
        host=host,
        port=port,
        username=username,
        useTLS=use_tls,
        certModeRaw=cert_mode,
        fingerprint=fingerprint,
        minRSAKeySizeBits=min_rsa_bits,
        **{"schema": ""},
    )


async def list_projects_with_counts(
    *,
    host: str,
    port: int,
    username: str,
    password: str,
    schema: str,
    use_tls: bool = False,
    cert_mode: str = "verify",
    fingerprint: str = "",
    min_rsa_bits: int = 2048,
) -> dict:
    """List the projects stored in ``schema`` with, for each, the number of journeys
    (distinct EVENT_ID) and events (rows) in its ORIGINAL data.

    Returns ``{"ok", "error", "projects": [{"projectId", "title", "titleShort",
    "journeys", "events", "lastEventAt"}]}`` (``lastEventAt`` = the newest EVENT_TIME
    as an ISO string, or null). Projects present in either PROJECTS or JOURNEYS are
    included, so a project shows even if one of the tables is missing a row for it.
    """
    import asyncio

    from .manager import DatabaseManager, friendly_error

    schema = (schema or "").strip()
    if not schema:
        return {"ok": False, "error": "A schema name is required.", "projects": []}

    server = _server_for(
        schema, host=host, port=port, username=username, use_tls=use_tls,
        cert_mode=cert_mode, fingerprint=fingerprint, min_rsa_bits=min_rsa_bits,
    )
    mgr = DatabaseManager.__new__(DatabaseManager)  # no store side effects
    ident = _quote_ident(schema)

    def _run() -> list[dict]:
        conn = mgr._open(server, password)
        try:
            conn.execute(f"OPEN SCHEMA {ident}")
            titles: dict[int, tuple[str, str]] = {}  # pid → (title, title_short)
            try:
                for row in conn.execute(
                    "SELECT PROJECT_ID, TITLE, TITLE_SHORT FROM PROJECTS"
                ).fetchall():
                    if row[0] is not None:
                        titles[int(row[0])] = (row[1] or "", row[2] or "")
            except Exception:  # noqa: BLE001 — PROJECTS may not exist yet
                pass
            # events, journeys, last-event-time (MAX(EVENT_TIME) — the newest row's
            # timestamp; lets a caller show "last activity" without its own query).
            aggs: dict[int, tuple[int, int, str | None]] = {}
            try:
                for row in conn.execute(
                    "SELECT PROJECT_ID, COUNT(*), COUNT(DISTINCT EVENT_ID), MAX(EVENT_TIME) "
                    "FROM JOURNEYS WHERE SAMPLE_SET = 'ORIGINAL' GROUP BY PROJECT_ID"
                ).fetchall():
                    if row[0] is not None:
                        last = row[3]
                        last_iso = (
                            last.isoformat() if hasattr(last, "isoformat")
                            else str(last) if last is not None else None
                        )
                        aggs[int(row[0])] = (int(row[1] or 0), int(row[2] or 0), last_iso)
            except Exception:  # noqa: BLE001 — JOURNEYS may not exist yet
                pass
            out: list[dict] = []
            for pid in sorted(set(titles) | set(aggs)):
                events, journeys, last_event = aggs.get(pid, (0, 0, None))
                title, short = titles.get(pid, ("", ""))
                out.append({
                    "projectId": pid,
                    "title": title or short or str(pid),
                    "titleShort": short,
                    "journeys": journeys,
                    "events": events,
                    "lastEventAt": last_event,
                })
            return out
        finally:
            conn.close()

    try:
        projects = await asyncio.to_thread(_run)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": friendly_error(exc), "projects": []}
    return {"ok": True, "error": None, "projects": projects}


# Every table that carries a PROJECT_ID, children before PROJECTS. TRANSITIONS_RAW is
# optional (built on demand); NOTES is created lazily — both may be absent.
_PROJECT_SCOPED_TABLES = [
    "JOURNEYS", "STEPS", "METAS", "NOTES", MATERIALIZED_TRANSITIONS_TABLE, "PROJECTS",
]


async def delete_project(
    *,
    project_id: str,
    host: str,
    port: int,
    username: str,
    password: str,
    schema: str,
    use_tls: bool = False,
    cert_mode: str = "verify",
    fingerprint: str = "",
    min_rsa_bits: int = 2048,
) -> dict:
    """Delete a project everywhere in ``schema``: remove its rows from every
    project-scoped table (PROJECTS, JOURNEYS, STEPS, METAS, NOTES, TRANSITIONS_RAW).

    Returns ``{"ok", "error", "events", "journeys", "tables": [cleared]}`` — the
    event/journey counts are what the project held before deletion. Tables that don't
    exist are skipped, not treated as an error.
    """
    import asyncio

    from .manager import DatabaseManager, friendly_error

    schema = (schema or "").strip()
    if not schema:
        return {"ok": False, "error": "A schema name is required."}
    try:
        pid_int = int(project_id)  # PROJECT_ID is a SMALLINT
    except (TypeError, ValueError):
        return {"ok": False, "error": "A valid (integer) project id is required."}

    server = _server_for(
        schema, host=host, port=port, username=username, use_tls=use_tls,
        cert_mode=cert_mode, fingerprint=fingerprint, min_rsa_bits=min_rsa_bits,
    )
    mgr = DatabaseManager.__new__(DatabaseManager)
    ident = _quote_ident(schema)
    # PROJECT_ID is an integer column — an unquoted, int-coerced literal (injection-safe).
    lit = str(pid_int)

    def _run() -> dict:
        conn = mgr._open(server, password)
        try:
            conn.execute(f"OPEN SCHEMA {ident}")
            events = journeys = 0
            try:
                row = conn.execute(
                    f"SELECT COUNT(*), COUNT(DISTINCT EVENT_ID) FROM JOURNEYS "
                    f"WHERE PROJECT_ID = {lit} AND SAMPLE_SET = 'ORIGINAL'"
                ).fetchall()
                if row:
                    events, journeys = int(row[0][0] or 0), int(row[0][1] or 0)
            except Exception:  # noqa: BLE001 — JOURNEYS may not exist
                pass
            cleared: list[str] = []
            for table in _PROJECT_SCOPED_TABLES:
                try:
                    conn.execute(f"DELETE FROM {table} WHERE PROJECT_ID = {lit}")
                    cleared.append(table)
                except Exception:  # noqa: BLE001 — table absent (NOTES / TRANSITIONS_RAW)
                    continue
            conn.commit()
            return {"events": events, "journeys": journeys, "tables": cleared}
        finally:
            conn.close()

    try:
        result = await asyncio.to_thread(_run)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": friendly_error(exc)}
    return {"ok": True, "error": None, **result}
