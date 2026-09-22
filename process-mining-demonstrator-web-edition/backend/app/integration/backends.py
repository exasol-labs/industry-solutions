"""Where the abstraction layer actually writes ingested records.

An :class:`IngestBackend` is the seam between the database-agnostic ingest API and a
concrete target database. Two implementations ship:

* :class:`InMemoryIngestBackend` — keeps tables in memory. The default for local
  development and the reference target for tests (no database required).
* :class:`SqlIngestBackend` — generates schema-qualified DDL/DML and runs it through
  a caller-supplied ``run_sql`` (the production path binds this to the user's Exasol
  connection). Identifiers are strictly validated and values defensively escaped.

Extractors never see a backend — they only see the :class:`~.contract.IngestSession`.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Callable, Mapping, Protocol, Sequence

from .contract import ColumnType, IngestError

# A conservative identifier grammar (letters, digits, underscore; not starting with a
# digit; ≤128 chars). Anything else is rejected rather than escaped, so a table or
# column name can never inject SQL.
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")

# Portable → Exasol column types.
_SQL_TYPE = {
    ColumnType.STRING: "VARCHAR(2000000)",
    ColumnType.INT: "DECIMAL(18,0)",
    ColumnType.SMALLINT: "SMALLINT",
    ColumnType.DECIMAL: "DECIMAL(36,6)",
    ColumnType.TIMESTAMP: "TIMESTAMP",
    ColumnType.BOOL: "BOOLEAN",
    # 16-byte HASHTYPE for MD5 ids; hex-string values convert on insert.
    ColumnType.HASH: "HASHTYPE(16 BYTE)",
}

_MAX_BATCH = 1000  # rows per INSERT statement

# Transaction bracket: how many rows are written before the layer commits. 0 means
# "one transaction for the whole import" (fully atomic, but the database holds the
# entire import open). The default keeps a large import from becoming one huge
# transaction while still committing far less often than per-statement autocommit.
DEFAULT_TRANSACTION_ROWS = 5000
MAX_TRANSACTION_ROWS = 1_000_000


def clamp_transaction_rows(value) -> int:
    """Normalise a user-supplied bracket size. Invalid → the default; 0 stays 0
    (single transaction); anything else is clamped to a sane range."""
    try:
        rows = int(value)
    except (TypeError, ValueError):
        return DEFAULT_TRANSACTION_ROWS
    if rows <= 0:
        return 0
    return max(_MAX_BATCH, min(rows, MAX_TRANSACTION_ROWS))


def valid_identifier(name: str) -> str:
    """Return ``name`` if it is a safe SQL identifier, else raise IngestError."""
    if not isinstance(name, str) or not _IDENT_RE.match(name):
        raise IngestError(f"Invalid SQL identifier: {name!r}")
    return name


class IngestBackend(Protocol):
    """Concrete write target for the abstraction layer."""

    def create_table(
        self, schema: str, table: str, columns: Mapping[str, ColumnType], keys: Sequence[str]
    ) -> None:
        ...

    def insert(
        self, schema: str, table: str, columns: Sequence[str], rows: Sequence[Sequence[Any]]
    ) -> int:
        ...

    def existing_keys(
        self, schema: str, table: str, key_columns: Sequence[str]
    ) -> set[tuple[str, ...]]:
        ...

    def existing_step_ids(self, schema: str) -> dict[str, int]:
        """Existing STEP name → STEP_ID for the schema's STEPS table (activity ids),
        so a re-import reuses ids. Empty when STEPS is absent or has no ids yet."""
        ...

    def existing_project_ids(self, schema: str) -> dict[str, int]:
        """Existing TITLE_SHORT code → PROJECT_ID for the schema's PROJECTS table, so an
        import can reuse a project's id (append) or allocate the next free one."""
        ...

    def commit(self) -> None:
        """Commit the work done since the last commit (end of a transaction bracket)."""
        ...

    def rollback(self) -> None:
        """Discard the uncommitted work of the current bracket (a failed run)."""
        ...


class InMemoryIngestBackend:
    """A dependency-free target: tables and rows live in dictionaries. Used for dev
    and as the tested reference implementation of the ingest semantics."""

    def __init__(self) -> None:
        # schema → table → {"columns": {name: type}, "rows": [ {col: value} ]}
        self.tables: dict[str, dict[str, dict[str, Any]]] = {}
        self.commits = 0
        self.rollbacks = 0

    def _table(self, schema: str, table: str) -> dict[str, Any] | None:
        return self.tables.get(schema, {}).get(table)

    def create_table(self, schema, table, columns, keys) -> None:
        valid_identifier(schema)
        valid_identifier(table)
        for col in columns:
            valid_identifier(col)
        existing = self._table(schema, table)
        if existing is None:
            self.tables.setdefault(schema, {})[table] = {
                "columns": dict(columns),
                "keys": list(keys),
                "rows": [],
            }

    def insert(self, schema, table, columns, rows) -> int:
        tbl = self._table(schema, table)
        if tbl is None:
            raise IngestError(f"Table {schema}.{table} was not defined.")
        for row in rows:
            tbl["rows"].append(dict(zip(columns, row)))
        return len(rows)

    def existing_keys(self, schema, table, key_columns):
        tbl = self._table(schema, table)
        if tbl is None:
            return set()
        return {
            tuple("" if r.get(k) is None else str(r.get(k)) for k in key_columns)
            for r in tbl["rows"]
        }

    def existing_step_ids(self, schema) -> dict[str, int]:
        tbl = self._table(schema, "STEPS")
        if tbl is None:
            return {}
        out: dict[str, int] = {}
        for r in tbl["rows"]:
            name, sid = r.get("STEP"), r.get("STEP_ID")
            if name is not None and sid is not None:
                try:
                    out[str(name)] = int(sid)
                except (TypeError, ValueError):
                    pass
        return out

    def existing_project_ids(self, schema) -> dict[str, int]:
        tbl = self._table(schema, "PROJECTS")
        if tbl is None:
            return {}
        out: dict[str, int] = {}
        for r in tbl["rows"]:
            short, pid = r.get("TITLE_SHORT"), r.get("PROJECT_ID")
            if short and pid is not None:
                try:
                    out[str(short)] = int(pid)
                except (TypeError, ValueError):
                    pass
        return out

    def commit(self) -> None:
        """No transactions in memory — recorded so tests can assert the bracketing."""
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


class SqlIngestBackend:
    """Generates schema-qualified SQL and runs it through ``run_sql`` (a synchronous
    callable returning the statement's rows — empty for DDL/DML). The production wiring
    binds ``run_sql`` to the user's Exasol connection; tests bind it to a recorder.

    Identifiers are validated (never escaped-and-hoped); values are rendered as
    strictly-escaped literals. Extractor code is trusted, but the layer still escapes
    defensively so a malformed source value can't corrupt a statement.
    """

    def __init__(
        self,
        run_sql: Callable[[str], Any],
        *,
        commit: Callable[[], None] | None = None,
        rollback: Callable[[], None] | None = None,
    ) -> None:
        self._run = run_sql
        # Supplied by the caller that owns the connection. Without them the backend
        # behaves as before (the driver's autocommit ends every statement), which is
        # what the tests that only record SQL expect.
        self._commit = commit
        self._rollback = rollback

    # ── DDL ───────────────────────────────────────────────────────────────────
    def create_table(self, schema, table, columns, keys) -> None:
        q = self._qualified(schema, table)
        cols = ", ".join(
            f'"{valid_identifier(name)}" {_SQL_TYPE[ctype]}' for name, ctype in columns.items()
        )
        self._run(f"CREATE TABLE IF NOT EXISTS {q} ({cols})")

    # ── DML ───────────────────────────────────────────────────────────────────
    def insert(self, schema, table, columns, rows) -> int:
        if not rows:
            return 0
        q = self._qualified(schema, table)
        col_list = ", ".join(f'"{valid_identifier(c)}"' for c in columns)
        written = 0
        for start in range(0, len(rows), _MAX_BATCH):
            batch = rows[start : start + _MAX_BATCH]
            values = ", ".join(
                "(" + ", ".join(_literal(v) for v in row) + ")" for row in batch
            )
            self._run(f"INSERT INTO {q} ({col_list}) VALUES {values}")
            written += len(batch)
        return written

    def existing_keys(self, schema, table, key_columns):
        """The set of existing key tuples in ``table`` (each value stringified). Used to
        create-if-missing metadata rows (projects, steps). Reads all keys — intended for
        small metadata tables, not fact tables."""
        q = self._qualified(schema, table)
        cols = ", ".join(f'"{valid_identifier(c)}"' for c in key_columns)
        rows = self._run(f"SELECT {cols} FROM {q}") or []
        return {tuple("" if v is None else str(v) for v in row) for row in rows}

    def existing_step_ids(self, schema) -> dict[str, int]:
        q = self._qualified(schema, "STEPS")
        try:
            rows = self._run(f"SELECT STEP, STEP_ID FROM {q} WHERE STEP_ID IS NOT NULL") or []
        except Exception:  # noqa: BLE001 — a pre-migration STEPS may lack the column
            return {}
        out: dict[str, int] = {}
        for name, sid in rows:
            try:
                out[str(name)] = int(sid)
            except (TypeError, ValueError):
                pass
        return out

    def existing_project_ids(self, schema) -> dict[str, int]:
        q = self._qualified(schema, "PROJECTS")
        try:
            rows = self._run(
                f"SELECT TITLE_SHORT, PROJECT_ID FROM {q} WHERE TITLE_SHORT IS NOT NULL"
            ) or []
        except Exception:  # noqa: BLE001 — PROJECTS absent / no TITLE_SHORT yet
            return {}
        out: dict[str, int] = {}
        for short, pid in rows:
            if short and pid is not None:
                try:
                    out[str(short)] = int(pid)
                except (TypeError, ValueError):
                    pass
        return out

    def commit(self) -> None:
        if self._commit is not None:
            self._commit()

    def rollback(self) -> None:
        if self._rollback is not None:
            self._rollback()

    @staticmethod
    def _qualified(schema: str, table: str) -> str:
        return f'"{valid_identifier(schema)}"."{valid_identifier(table)}"'


def _literal(value: Any) -> str:
    """Render a Python value as a safe SQL literal."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
            raise IngestError(f"Non-finite numeric value: {value!r}")
        return repr(value)
    if isinstance(value, datetime):
        return f"TIMESTAMP '{value.strftime('%Y-%m-%d %H:%M:%S.%f')[:23]}'"
    if isinstance(value, date):
        return f"DATE '{value.isoformat()}'"
    # Everything else is treated as text: double single-quotes, strip NULs.
    text = str(value).replace("\x00", "").replace("'", "''")
    return f"'{text}'"
