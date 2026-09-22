"""Security store — users, TLS certificates and TLS mode.

Backed by a dedicated SQLite database (`data/security.sqlite3`) so it is cleanly
separable from the app's settings and can be read by every process (the admin
service manages it; the GUI launcher reads the TLS mode; the future login flow
will authenticate against the users table).

Private keys are encrypted at rest with the shared Fernet key. Passwords are
scrypt-hashed and never stored reversibly.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import sqlite3
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..config import (
    ACTIVE_CERT_PATH,
    ACTIVE_KEY_PATH,
    APP_VERSION,
    DEFAULT_ADMIN_PASSWORD,
    DEFAULT_ADMIN_USERNAME,
    SECURITY_DB_PATH,
    SINK_SOURCE_KIND,
)
from ..services import certs as cert_service
from .crypto import (
    decrypt_text,
    encrypt_text,
    hash_password,
    recovery_code_pepper,
    verify_password,
    write_private_file,
)

log = logging.getLogger("security-store")

# A throwaway hash so `authenticate` can run one scrypt verification even when the
# username doesn't exist — equalising response time against username enumeration.
_DUMMY_HASH = hash_password("pmw-nonexistent-account")

TLS_OFF = "off"
TLS_OPTIONAL = "optional"
TLS_REQUIRED = "required"
_TLS_MODES = {TLS_OFF, TLS_OPTIONAL, TLS_REQUIRED}

# Lock an account after this many consecutive failed sign-ins when the admin has
# not configured a value. A secure-by-default: fresh installs get a lockout even
# before anyone visits the Users tab. An admin can still set 0 (= never lock).
# How a connection verifies the database server's TLS certificate. Anything outside
# this set is stored as "verify": an unrecognised value (a typo, a trailing space, a
# legacy or restored row) must never silently mean "no verification".
_CERT_MODES = ("verify", "fingerprint", "insecure")


def _valid_cert_mode(value) -> str:
    mode = str(value or "verify").strip().lower()
    return mode if mode in _CERT_MODES else "verify"


_DEFAULT_MAX_FAILED_LOGINS = 3
# A lockout auto-expires after this long (0 = never, admin must re-enable). Keeps the
# brute-force brake while denying an unauthenticated attacker a permanent
# account-disable primitive against any username they know.
_DEFAULT_LOCKOUT_MINUTES = 15

# How many scheduled-backup files to retain (newest-first) when none is configured.
_DEFAULT_BACKUP_RETENTION = 30

# ── Login-page appearance (admin "Customize" tab) ───────────────────────────
# Applies to both the app and admin sign-in pages. "default" keeps each page's
# existing theme colour; "color" paints a solid colour; "image" uses an uploaded
# background image (stored inline as a data: URI).
LOGIN_BG_DEFAULT = "default"
LOGIN_BG_COLOR = "color"
LOGIN_BG_IMAGE = "image"
_LOGIN_BG_TYPES = {LOGIN_BG_DEFAULT, LOGIN_BG_COLOR, LOGIN_BG_IMAGE}
_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
# data:image/<png|jpeg|gif|webp|svg+xml>;base64,<standard base64>
_DATA_IMAGE_RE = re.compile(
    r"^data:image/(png|jpe?g|gif|webp|svg\+xml);base64,[A-Za-z0-9+/]+={0,2}$"
)
# Cap the stored data URI so a background image can't bloat the settings DB or a
# backup export. base64 inflates the source by ~4/3, so a 3 MB source image (the
# admin UI's file-size limit) becomes ~4.19 MB of characters; keep this above that
# with headroom, otherwise images the UI accepts fail to save on the server.
_MAX_LOGIN_IMAGE_CHARS = 4_400_000

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    username      TEXT PRIMARY KEY,
    password_hash TEXT NOT NULL,
    is_admin      INTEGER NOT NULL DEFAULT 0,
    is_enabled    INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL,
    last_login    TEXT
);
CREATE TABLE IF NOT EXISTS certificates (
    id             TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    cert_pem       TEXT NOT NULL,
    key_enc        TEXT NOT NULL,
    subject        TEXT,
    issuer         TEXT,
    not_before     TEXT,
    not_after      TEXT,
    sans           TEXT,
    is_self_signed INTEGER NOT NULL DEFAULT 0,
    created_at     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS security_config (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS credentials (
    id            TEXT PRIMARY KEY,
    username      TEXT NOT NULL,
    credential_id TEXT NOT NULL UNIQUE,
    public_key    TEXT NOT NULL,
    sign_count    INTEGER NOT NULL DEFAULT 0,
    transports    TEXT NOT NULL DEFAULT '',
    name          TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS mfa_recovery_codes (
    id         TEXT PRIMARY KEY,
    username   TEXT NOT NULL,
    code_hash  TEXT NOT NULL,
    used_at    TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS connections (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    comment       TEXT DEFAULT '',
    host          TEXT DEFAULT '',
    port          INTEGER DEFAULT 8563,
    username      TEXT DEFAULT '',
    db_schema     TEXT DEFAULT '',
    use_tls       INTEGER DEFAULT 0,
    cert_mode     TEXT DEFAULT 'verify',
    fingerprint   TEXT DEFAULT '',
    min_rsa_bits  INTEGER DEFAULT 2048,
    password_enc  TEXT DEFAULT '',
    llm_url       TEXT DEFAULT '',
    llm_model     TEXT DEFAULT '',
    llm_key_enc   TEXT DEFAULT '',
    owner         TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS connection_assignments (
    connection_id TEXT NOT NULL,
    username      TEXT NOT NULL,
    PRIMARY KEY (connection_id, username)
);
-- Integration console: a user's source-type definitions — a name plus an extraction
-- spec (an example log + the timestamp/step/id/meta regexes) stored as JSON in config.
CREATE TABLE IF NOT EXISTS source_types (
    id          TEXT PRIMARY KEY,
    owner       TEXT NOT NULL,
    name        TEXT NOT NULL,
    config      TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL
);
-- Integration console: a user's data sources — a name, a kind ("file", and future
-- kinds like a database or an API) and kind-specific settings stored as JSON in config.
CREATE TABLE IF NOT EXISTS sources (
    id          TEXT PRIMARY KEY,
    owner       TEXT NOT NULL,
    name        TEXT NOT NULL,
    kind        TEXT NOT NULL DEFAULT 'file',
    config      TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL
);
-- Integration console: the watchdog's read checkpoint per source file, so an
-- incremental import only picks up newly-appended lines. `byte_offset` is how far the
-- file has been consumed; `size`/`signature` detect truncation or rotation (a shrunk
-- file or a changed head resets the offset). `records` is the running total imported.
CREATE TABLE IF NOT EXISTS source_checkpoints (
    source_id   TEXT PRIMARY KEY,
    byte_offset INTEGER NOT NULL DEFAULT 0,
    size        INTEGER NOT NULL DEFAULT 0,
    signature   TEXT NOT NULL DEFAULT '',
    records     INTEGER NOT NULL DEFAULT 0,
    updated_at  TEXT NOT NULL DEFAULT '',
    last_error  TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS ldap_config (
    id                INTEGER PRIMARY KEY CHECK (id = 1),
    enabled           INTEGER NOT NULL DEFAULT 0,
    server_uri        TEXT NOT NULL DEFAULT '',
    start_tls         INTEGER NOT NULL DEFAULT 0,
    verify_cert       INTEGER NOT NULL DEFAULT 1,
    ca_cert           TEXT NOT NULL DEFAULT '',
    bind_dn           TEXT NOT NULL DEFAULT '',
    bind_password_enc TEXT NOT NULL DEFAULT '',
    base_dn           TEXT NOT NULL DEFAULT '',
    user_filter       TEXT NOT NULL DEFAULT '(uid={username})',
    login_attr        TEXT NOT NULL DEFAULT 'uid',
    email_attr        TEXT NOT NULL DEFAULT 'mail',
    display_attr      TEXT NOT NULL DEFAULT 'cn',
    admin_login_enabled INTEGER NOT NULL DEFAULT 0,
    show_status_on_login INTEGER NOT NULL DEFAULT 1,
    updated_at        TEXT NOT NULL DEFAULT ''
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class User:
    username: str
    is_admin: bool
    is_enabled: bool
    created_at: str
    last_login: str | None = None
    auth_source: str = "local"  # 'local' | 'ldap'
    email: str = ""
    display_name: str = ""
    is_power: bool = False  # may create/manage their own DB connections from the app
    is_developer: bool = False  # may enter the integration/data-source console (admin-gated)
    passkey_allowed: bool = False  # may enrol + sign in with a passkey (admin-gated)
    mfa_allowed: bool = False  # may enrol TOTP two-factor auth (admin-gated)
    mfa_enabled: bool = False  # has a confirmed TOTP secret (derived, not a column)
    failed_logins: int = 0
    login_locked: bool = False  # disabled by the failed-sign-in lockout
    session_epoch: int = 0  # bumped on logout; stale-epoch tokens are rejected

    def public(self) -> dict:
        return {
            "username": self.username,
            "isAdmin": self.is_admin,
            "isEnabled": self.is_enabled,
            "failedLogins": self.failed_logins,
            "loginLocked": self.login_locked,
            "createdAt": self.created_at,
            "lastLogin": self.last_login,
            "authSource": self.auth_source,
            "email": self.email,
            "displayName": self.display_name,
            "isPower": self.is_power,
            "isDeveloper": self.is_developer,
            "passkeyAllowed": self.passkey_allowed,
            "mfaAllowed": self.mfa_allowed,
            "mfaEnabled": self.mfa_enabled,
        }


@dataclass
class Certificate:
    id: str
    name: str
    subject: str
    issuer: str
    not_before: str
    not_after: str
    sans: list[str] = field(default_factory=list)
    is_self_signed: bool = False
    created_at: str = ""

    def public(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "subject": self.subject,
            "issuer": self.issuer,
            "notBefore": self.not_before,
            "notAfter": self.not_after,
            "sans": self.sans,
            "isSelfSigned": self.is_self_signed,
            "createdAt": self.created_at,
        }


@dataclass
class SourceType:
    """A user's source-type definition for the integration console: a name plus an
    extraction spec (an example log line + the timestamp/step/id/meta regexes), stored
    as JSON in `config`."""

    id: str
    owner: str
    name: str
    config: str
    created_at: str

    def public(self) -> dict:
        # `config` holds the extraction spec as JSON: {sample, fields:[{name,role,regex,…}]}.
        spec: dict = {}
        if self.config:
            try:
                parsed = json.loads(self.config)
                if isinstance(parsed, dict):
                    spec = parsed
            except (json.JSONDecodeError, TypeError):
                spec = {}
        fields = spec.get("fields")
        # Optional compound-step rules (absent for a source type that doesn't use them).
        compound = spec.get("compound")
        # Data format: "text" (regex, the default for pre-existing specs), or the
        # semi-structured "json"/"xml" that locate fields by a path instead of a regex.
        fmt = spec.get("format")
        return {
            "id": self.id,
            "owner": self.owner,
            "name": self.name,
            "sample": spec.get("sample", ""),
            "format": fmt if fmt in ("text", "json", "xml") else "text",
            # XML only: the repeating element that is one record (relative to the root).
            "recordPath": spec.get("recordPath", ""),
            "fields": fields if isinstance(fields, list) else [],
            "compound": compound if isinstance(compound, list) else [],
            "createdAt": self.created_at,
        }


@dataclass
class Source:
    """A user's data source for the integration console: a name, a kind ("file" for
    now) and kind-specific settings (JSON in `config`) — deliberately generic so new
    source kinds slot in without a schema change."""

    id: str
    owner: str
    name: str
    kind: str
    config: str
    created_at: str

    def public(self) -> dict:
        cfg: dict = {}
        if self.config:
            try:
                parsed = json.loads(self.config)
                if isinstance(parsed, dict):
                    cfg = parsed
            except (json.JSONDecodeError, TypeError):
                cfg = {}
        return {
            "id": self.id,
            "owner": self.owner,
            "name": self.name,
            "kind": self.kind,
            "config": cfg,
            "createdAt": self.created_at,
        }


@dataclass
class Connection:
    """An admin-defined server connection (Exasol + optional LLM) with the set of
    usernames it is assigned to. Secret fields hold decrypted values only when the
    row was read for connecting; the serialisers below never leak them."""

    id: str
    name: str
    comment: str = ""
    host: str = ""
    port: int = 8563
    username: str = ""
    schema: str = ""
    use_tls: bool = False
    cert_mode: str = "verify"
    fingerprint: str = ""
    min_rsa_bits: int = 2048
    password: str = ""
    llm_url: str = ""
    llm_model: str = ""
    llm_api_key: str = ""
    assignments: list[str] = field(default_factory=list)
    has_password: bool = False
    has_llm_key: bool = False
    owner: str = ""  # power user who created it from the app; '' = admin-defined
    created_at: str = ""
    use_materialized_transitions: bool = False
    use_indb_sampling: bool = False

    @property
    def has_llm(self) -> bool:
        return bool(self.llm_url.strip())

    def admin_public(self) -> dict:
        """Full definition for the admin UI — assignments included, secrets not."""
        return {
            "id": self.id,
            "name": self.name,
            "comment": self.comment,
            "host": self.host,
            "port": self.port,
            "username": self.username,
            "schema": self.schema,
            "useTLS": self.use_tls,
            "certModeRaw": self.cert_mode,
            "fingerprint": self.fingerprint,
            "minRSAKeySizeBits": self.min_rsa_bits,
            "hasPassword": self.has_password,
            "llmURL": self.llm_url,
            "llmModel": self.llm_model,
            "hasLLMKey": self.has_llm_key,
            "assignments": self.assignments,
            "owner": self.owner,
            "createdAt": self.created_at,
            "useMaterializedTransitions": self.use_materialized_transitions,
            "useInDbSampling": self.use_indb_sampling,
        }

    def user_public(self) -> dict:
        """What a signed-in user may see about a connection assigned to them."""
        return {
            "id": self.id,
            "name": self.name,
            "comment": self.comment,
            "host": self.host,
            "port": self.port,
            "schema": self.schema,
            "hasLLM": self.has_llm,
            "llmURL": self.llm_url if self.has_llm else None,
        }


class SecurityStore:
    def __init__(self, path=SECURITY_DB_PATH) -> None:
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        # WAL improves concurrency between the admin (writer) and backend (reader);
        # busy_timeout makes a cross-process writer retry instead of failing a write
        # immediately with SQLITE_BUSY (e.g. a dropped record_login_failure count).
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.executescript(_SCHEMA)
        self._migrate()
        self._conn.commit()
        self._bootstrap()
        # Recovery valve: set PMW_RESET_LOCKOUTS=1 and restart to clear every
        # failed-sign-in lockout (e.g. if the sole admin locked themselves out).
        if os.environ.get("PMW_RESET_LOCKOUTS", "").strip().lower() in (
            "1", "true", "yes", "on"
        ):
            with self._lock:
                self._conn.execute(
                    "UPDATE users SET login_locked = 0, failed_logins = 0, "
                    "is_enabled = 1 WHERE login_locked = 1"
                )
                self._conn.commit()
            log.warning("PMW_RESET_LOCKOUTS set — cleared all failed-sign-in lockouts.")

    def _migrate(self) -> None:
        """Add columns introduced after the initial release to existing databases."""
        cols = {
            r["name"] for r in self._conn.execute("PRAGMA table_info(users)").fetchall()
        }
        for name, ddl in (
            ("auth_source", "auth_source TEXT NOT NULL DEFAULT 'local'"),
            ("email", "email TEXT NOT NULL DEFAULT ''"),
            ("display_name", "display_name TEXT NOT NULL DEFAULT ''"),
            ("is_power", "is_power INTEGER NOT NULL DEFAULT 0"),
            # Admin-gated permission to enter the integration / data-source console.
            ("is_developer", "is_developer INTEGER NOT NULL DEFAULT 0"),
            # Admin-gated permission to enrol and sign in with a passkey (WebAuthn).
            ("passkey_allowed", "passkey_allowed INTEGER NOT NULL DEFAULT 0"),
            # Admin-gated permission to enrol TOTP two-factor auth; the encrypted
            # secret (empty until the user confirms enrolment).
            ("mfa_allowed", "mfa_allowed INTEGER NOT NULL DEFAULT 0"),
            ("totp_secret_enc", "totp_secret_enc TEXT NOT NULL DEFAULT ''"),
            # Failed-sign-in lockout (admin-configurable threshold).
            ("failed_logins", "failed_logins INTEGER NOT NULL DEFAULT 0"),
            ("login_locked", "login_locked INTEGER NOT NULL DEFAULT 0"),
            # When the lockout was applied — a lockout auto-expires after
            # `lockout_minutes`, so an unauthenticated attacker cannot permanently
            # disable a known account by sending a few bad passwords.
            ("login_locked_at", "login_locked_at TEXT NOT NULL DEFAULT ''"),
            # Bumped on logout to invalidate that user's outstanding session tokens.
            ("session_epoch", "session_epoch INTEGER NOT NULL DEFAULT 0"),
        ):
            if name not in cols:
                self._conn.execute(f"ALTER TABLE users ADD COLUMN {ddl}")
        # Connections gained an owner (the power user who created them; '' = admin).
        conn_cols = {
            r["name"] for r in self._conn.execute("PRAGMA table_info(connections)").fetchall()
        }
        if "owner" not in conn_cols:
            self._conn.execute("ALTER TABLE connections ADD COLUMN owner TEXT NOT NULL DEFAULT ''")
        # Opt-in to reading transitions from the pre-materialised TRANSITIONS_RAW
        # table instead of the live LEAD() query (falls back if it isn't built).
        if "use_materialized_transitions" not in conn_cols:
            self._conn.execute(
                "ALTER TABLE connections ADD COLUMN "
                "use_materialized_transitions INTEGER NOT NULL DEFAULT 0"
            )
        # Opt-in to building sample sets entirely inside the database (one set-based
        # INSERT … SELECT) instead of extracting ids to the app and re-inserting —
        # needed for very large logs where the round-trip times out.
        if "use_indb_sampling" not in conn_cols:
            self._conn.execute(
                "ALTER TABLE connections ADD COLUMN "
                "use_indb_sampling INTEGER NOT NULL DEFAULT 0"
            )
        # Directory sign-in to the admin interface is an explicit opt-in (default off).
        ldap_cols = {
            r["name"] for r in self._conn.execute("PRAGMA table_info(ldap_config)").fetchall()
        }
        if "admin_login_enabled" not in ldap_cols:
            self._conn.execute(
                "ALTER TABLE ldap_config ADD COLUMN admin_login_enabled INTEGER NOT NULL DEFAULT 0"
            )
        # Whether the login panels show the "Authentication Server" availability LED. Defaults
        # to on (1) so existing installs keep their current behaviour; admins can hide it.
        if "show_status_on_login" not in ldap_cols:
            self._conn.execute(
                "ALTER TABLE ldap_config ADD COLUMN show_status_on_login INTEGER NOT NULL DEFAULT 1"
            )
        # The former "connectors" table was renamed to "source_types" (a source type is
        # a name + extraction spec; the old source/source_type columns are dropped).
        # Carry over any existing definitions, then remove the old table.
        table_names = {
            r["name"] for r in self._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        if "connectors" in table_names:
            self._conn.execute(
                "INSERT OR IGNORE INTO source_types (id, owner, name, config, created_at) "
                "SELECT id, owner, name, config, created_at FROM connectors"
            )
            self._conn.execute("DROP TABLE connectors")

    # ── bootstrap ─────────────────────────────────────────────────────────────

    def _bootstrap(self) -> None:
        """Seed the default administrator and default TLS mode on first run."""
        with self._lock:
            count = self._conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            if count == 0:
                self._conn.execute(
                    "INSERT INTO users (username, password_hash, is_admin, is_enabled, created_at) "
                    "VALUES (?, ?, 1, 1, ?)",
                    (DEFAULT_ADMIN_USERNAME, hash_password(DEFAULT_ADMIN_PASSWORD), _now()),
                )
            if count == 0:
                # Track that the bootstrap admin still uses its default password.
                self._set_config("default_admin_active", "1")
            if self._get_config("tls_mode") is None:
                self._set_config("tls_mode", TLS_OFF)
            if self._get_config("require_login") is None:
                # Multi-user default: the main app requires sign-in.
                self._set_config("require_login", "1")
            self._conn.commit()

    @property
    def default_admin_password_active(self) -> bool:
        with self._lock:
            return self._get_config("default_admin_active") == "1"

    @property
    def require_login(self) -> bool:
        with self._lock:
            return self._get_config("require_login") != "0"

    def set_require_login(self, required: bool) -> None:
        with self._lock:
            self._set_config("require_login", "1" if required else "0")
            self._conn.commit()

    @property
    def integration_enabled(self) -> bool:
        """Whether the integration / data-source console surface is served. On by
        default; the admin can disable it (the surface then shows a disabled page)."""
        with self._lock:
            return self._get_config("integration_enabled") != "0"

    def set_integration_enabled(self, enabled: bool) -> None:
        with self._lock:
            self._set_config("integration_enabled", "1" if enabled else "0")
            self._conn.commit()

    @property
    def actions_enabled(self) -> bool:
        """Whether the Actions feature is available: the Actions authoring surface is
        served and the main app offers the node-menu "Actions" submenu. Opt-in, so
        OFF by default until an admin turns it on."""
        with self._lock:
            return self._get_config("actions_enabled") == "1"

    def set_actions_enabled(self, enabled: bool) -> None:
        with self._lock:
            self._set_config("actions_enabled", "1" if enabled else "0")
            self._conn.commit()

    @property
    def sink_enabled(self) -> bool:
        """Whether the API Server - Event Receiver module is available: the per-sink ingestion
        servers accept posts. Opt-in, so OFF by default until an admin turns it on."""
        with self._lock:
            return self._get_config("sink_enabled") == "1"

    def set_sink_enabled(self, enabled: bool) -> None:
        with self._lock:
            self._set_config("sink_enabled", "1" if enabled else "0")
            self._conn.commit()

    # ── MCP server ──────────────────────────────────────────────────────────
    # Config lives in the key-value security_config table (no secrets: offline JWKS
    # validation needs only public settings). `mcp_username_claim` names the JWT claim
    # (e.g. preferred_username / email) matched — case-insensitively — to an enabled
    # Process Mining user, whose connection assignments then gate what may be queried.
    _MCP_KEYS = ("issuer", "jwksUri", "audience", "requiredGroup", "usernameClaim")

    @property
    def mcp_enabled(self) -> bool:
        """Whether the MCP query server accepts requests. Opt-in, OFF by default."""
        with self._lock:
            return self._get_config("mcp_enabled") == "1"

    def set_mcp_enabled(self, enabled: bool) -> None:
        with self._lock:
            self._set_config("mcp_enabled", "1" if enabled else "0")
            self._conn.commit()

    def mcp_settings(self) -> dict:
        """The MCP OAuth/Authentik settings (no secrets). Missing values default to ''
        except usernameClaim, which defaults to 'preferred_username'."""
        with self._lock:
            out = {k: (self._get_config(f"mcp_{k}") or "") for k in self._MCP_KEYS}
        if not out["usernameClaim"]:
            out["usernameClaim"] = "preferred_username"
        return out

    def set_mcp_settings(self, data: dict) -> None:
        with self._lock:
            for k in self._MCP_KEYS:
                if k in data:
                    self._set_config(f"mcp_{k}", str(data.get(k) or "").strip())
            self._conn.commit()

    @property
    def idle_timeout_mins(self) -> int:
        """Auto sign-out after this many minutes of inactivity (0 = never)."""
        with self._lock:
            try:
                return max(0, int(self._get_config("idle_timeout_mins") or 0))
            except (TypeError, ValueError):
                return 0

    def set_idle_timeout_mins(self, minutes: int) -> None:
        minutes = max(0, int(minutes))
        with self._lock:
            self._set_config("idle_timeout_mins", str(minutes))
            self._conn.commit()

    @property
    def admin_idle_timeout_mins(self) -> int:
        """Auto sign-out of the *admin interface* after N minutes idle (0 = never).
        Configured separately from the main app's idle timeout."""
        with self._lock:
            try:
                return max(0, int(self._get_config("admin_idle_timeout_mins") or 0))
            except (TypeError, ValueError):
                return 0

    def set_admin_idle_timeout_mins(self, minutes: int) -> None:
        minutes = max(0, int(minutes))
        with self._lock:
            self._set_config("admin_idle_timeout_mins", str(minutes))
            self._conn.commit()

    # ── failed-sign-in lockout ────────────────────────────────────────────────

    @property
    def max_failed_logins(self) -> int:
        """Disable an account after this many consecutive failed sign-ins
        (0 = never lock). Applies to every account, including the Administrator.
        Unset (fresh install) → the secure default; an explicit 0 keeps it off."""
        with self._lock:
            raw = self._get_config("max_failed_logins")
        if raw is None:
            return _DEFAULT_MAX_FAILED_LOGINS
        try:
            return max(0, int(raw))
        except (TypeError, ValueError):
            return _DEFAULT_MAX_FAILED_LOGINS

    def set_max_failed_logins(self, count: int) -> None:
        with self._lock:
            self._set_config("max_failed_logins", str(max(0, int(count))))
            self._conn.commit()

    @property
    def lockout_minutes(self) -> int:
        """How long a failed-sign-in lockout lasts before it auto-expires
        (0 = until an administrator re-enables the account).

        A permanent lockout is a denial-of-service an *unauthenticated* attacker can
        trigger at will: a few bad passwords against a known username disables the
        account. Auto-expiry keeps the brute-force protection (the attacker still can't
        guess faster than one window per `max_failed_logins` tries) without handing out
        a free account-disable primitive."""
        with self._lock:
            raw = self._get_config("lockout_minutes")
        if raw is None:
            return _DEFAULT_LOCKOUT_MINUTES
        try:
            return max(0, int(raw))
        except (TypeError, ValueError):
            return _DEFAULT_LOCKOUT_MINUTES

    def set_lockout_minutes(self, minutes: int) -> None:
        with self._lock:
            self._set_config("lockout_minutes", str(max(0, int(minutes))))
            self._conn.commit()

    def _clear_expired_lockout(self, username: str) -> None:
        """Re-enable an account whose failed-sign-in lockout has aged out. No-op for an
        account an administrator disabled by hand (login_locked = 0)."""
        minutes = self.lockout_minutes
        if minutes <= 0:
            return
        with self._lock:
            row = self._conn.execute(
                "SELECT login_locked, login_locked_at FROM users "
                "WHERE LOWER(username) = LOWER(?)",
                (username,),
            ).fetchone()
            if row is None or not row["login_locked"]:
                return
            stamp = row["login_locked_at"] or ""
            if stamp:
                try:
                    locked_at = datetime.fromisoformat(stamp)
                except ValueError:
                    locked_at = None
                if locked_at is not None:
                    if locked_at.tzinfo is None:
                        locked_at = locked_at.replace(tzinfo=timezone.utc)
                    age = (datetime.now(timezone.utc) - locked_at).total_seconds()
                    if age < minutes * 60:
                        return  # still inside the lockout window
            self._conn.execute(
                "UPDATE users SET is_enabled = 1, login_locked = 0, failed_logins = 0, "
                "login_locked_at = '' WHERE LOWER(username) = LOWER(?)",
                (username,),
            )
            self._conn.commit()

    @property
    def display_timezone(self) -> str:
        """IANA zone name for server-rendered timestamps (logs, backups). Empty
        means the server's own local zone (the historical behaviour)."""
        with self._lock:
            return self._get_config("display_timezone") or ""

    def set_display_timezone(self, name: str) -> None:
        with self._lock:
            self._set_config("display_timezone", (name or "").strip())
            self._conn.commit()

    def record_login_failure(self, username: str) -> bool:
        """Count a failed sign-in; lock (disable) the account once it reaches the
        configured threshold. Returns True if this failure locked it.

        The built-in Administrator is counted but NEVER auto-locked: it's the sole
        break-glass recovery account, so letting an unauthenticated attacker who
        knows its name disable it (3 bad POSTs) would be a denial-of-service. Its
        brute-force protection is instead the per-IP login throttle plus scrypt
        cost; a real admin can still disable a *rogue* extra admin the normal way."""
        threshold = self.max_failed_logins
        with self._lock:
            row = self._conn.execute(
                "SELECT failed_logins FROM users WHERE LOWER(username) = LOWER(?)",
                (username,),
            ).fetchone()
            if row is None:
                return False
            count = int(row["failed_logins"] or 0) + 1
            locked = (
                threshold > 0
                and count >= threshold
                and not self._is_builtin_admin(username)
            )
            self._conn.execute(
                "UPDATE users SET failed_logins = ?, "
                "is_enabled = CASE WHEN ? THEN 0 ELSE is_enabled END, "
                "login_locked = CASE WHEN ? THEN 1 ELSE login_locked END, "
                # Stamp WHEN it locked so the lockout can auto-expire.
                "login_locked_at = CASE WHEN ? THEN ? ELSE login_locked_at END "
                "WHERE LOWER(username) = LOWER(?)",
                (count, int(locked), int(locked), int(locked), _now(), username),
            )
            self._conn.commit()
        if locked:  # logged outside the store lock (the log store has its own lock)
            from .. import log_events as logx

            logx.warn(
                f"account {username!r} locked (disabled) after {count} failed "
                f"sign-in attempts",
                username=username,
                operation="login",
            )
        return locked

    def reset_login_failures(self, username: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE users SET failed_logins = 0, login_locked = 0 "
                "WHERE LOWER(username) = LOWER(?)",
                (username,),
            )
            self._conn.commit()

    # ── Scheduled backups ───────────────────────────────────────────────────
    # Config for the admin's automatic-backup scheduler, kept as security_config
    # rows. The encryption password is stored ENCRYPTED at rest (Fernet) so an
    # unattended backup can run; it is never returned to the client — only a
    # `hasPassword` flag is exposed, matching the connection/LDAP secret pattern.

    def backup_schedule(self) -> dict:
        """Public view of the scheduled-backup config (no password, only hasPassword)."""
        with self._lock:
            enabled = self._get_config("backup_sched_enabled") == "1"
            cron = self._get_config("backup_sched_cron") or "0 2 * * *"
            retention_raw = self._get_config("backup_sched_retention")
            inc_pw = self._get_config("backup_sched_inc_passwords") != "0"
            inc_user = self._get_config("backup_sched_inc_username") != "0"
            inc_llm = self._get_config("backup_sched_inc_llm") != "0"
            has_pw = bool(self._get_config("backup_sched_password_enc"))
            status_raw = self._get_config("backup_sched_status")
        try:
            retention = max(1, int(retention_raw)) if retention_raw else _DEFAULT_BACKUP_RETENTION
        except (TypeError, ValueError):
            retention = _DEFAULT_BACKUP_RETENTION
        try:
            status = json.loads(status_raw) if status_raw else None
        except (TypeError, ValueError):
            status = None
        return {
            "enabled": enabled,
            "cron": cron,
            "retention": retention,
            "includePasswords": inc_pw,
            "includeUsername": inc_user,
            "includeLlmKey": inc_llm,
            "hasPassword": has_pw,
            "status": status,
        }

    def set_backup_schedule(self, data: dict) -> None:
        """Update the config. The password uses the standard secret pattern: a
        present non-empty value is stored encrypted, an empty string clears it, and
        omitting the key keeps the existing value."""
        with self._lock:
            if "enabled" in data:
                self._set_config("backup_sched_enabled", "1" if data["enabled"] else "0")
            if "cron" in data:
                self._set_config("backup_sched_cron", str(data["cron"]))
            if "retention" in data:
                self._set_config("backup_sched_retention", str(max(1, int(data["retention"]))))
            for key, col in (
                ("includePasswords", "backup_sched_inc_passwords"),
                ("includeUsername", "backup_sched_inc_username"),
                ("includeLlmKey", "backup_sched_inc_llm"),
            ):
                if key in data:
                    self._set_config(col, "1" if data[key] else "0")
            if "password" in data:
                pw = data["password"] or ""
                self._set_config(
                    "backup_sched_password_enc", encrypt_text(pw) if pw else ""
                )
            self._conn.commit()

    def backup_schedule_password(self) -> str:
        """Decrypted backup password for the scheduler (empty string if unset)."""
        with self._lock:
            enc = self._get_config("backup_sched_password_enc")
        return decrypt_text(enc) if enc else ""

    def set_backup_schedule_status(self, status: dict) -> None:
        """Record the outcome of the most recent scheduled/manual backup run."""
        with self._lock:
            self._set_config("backup_sched_status", json.dumps(status))
            self._conn.commit()

    def session_epoch(self, username: str) -> int:
        """Current session epoch for a user (0 if unknown). Embedded in freshly
        issued session tokens; a token whose epoch is stale is no longer valid."""
        with self._lock:
            row = self._conn.execute(
                "SELECT session_epoch FROM users WHERE LOWER(username) = LOWER(?)",
                (username,),
            ).fetchone()
        return int(row["session_epoch"]) if row else 0

    def bump_session_epoch(self, username: str) -> None:
        """Invalidate every outstanding session token for a user (used on logout).
        Because tokens are stateless and re-minted on each request, revoking by
        epoch is the only way to also kill a token captured earlier in the session."""
        with self._lock:
            self._conn.execute(
                "UPDATE users SET session_epoch = session_epoch + 1 "
                "WHERE LOWER(username) = LOWER(?)",
                (username,),
            )
            self._conn.commit()

    def login_block_message(self, username: str, password: str = "") -> str | None:
        """A message to show the user when their account is disabled/locked, or None
        for a plain bad-credentials failure (so we don't reveal account existence).

        The explanation is released ONLY when the supplied password is correct.
        Otherwise "This account has been locked…" vs. the generic message is an
        oracle: anyone could confirm an account exists (and, combined with the
        lockout, deliberately trip it) without knowing any credential. A user who
        types their real password still gets the helpful reason.
        """
        user = self.get_user(username)
        if user is None or user.is_enabled:
            return None
        with self._lock:
            row = self._conn.execute(
                "SELECT password_hash FROM users WHERE LOWER(username) = LOWER(?)",
                (username,),
            ).fetchone()
        # Always run one scrypt check so timing doesn't distinguish the branches.
        if not verify_password(password, row["password_hash"] if row else _DUMMY_HASH):
            return None
        if user.login_locked:
            return (
                "This account has been locked after too many failed sign-in "
                "attempts. Contact an administrator."
            )
        return "This account has been disabled. Contact an administrator."

    # ── LDAP / directory ──────────────────────────────────────────────────────

    def _ldap_row(self) -> sqlite3.Row | None:
        return self._conn.execute("SELECT * FROM ldap_config WHERE id = 1").fetchone()

    @property
    def ldap_enabled(self) -> bool:
        with self._lock:
            row = self._ldap_row()
        return bool(row and row["enabled"])

    def ldap_admin_public(self) -> dict:
        """LDAP settings for the admin UI — the bind password is never returned."""
        with self._lock:
            row = self._ldap_row()
        if row is None:
            return {
                "enabled": False,
                "serverURI": "",
                "startTLS": False,
                "verifyCert": True,
                "caCert": "",
                "bindDN": "",
                "hasBindPassword": False,
                "baseDN": "",
                "userFilter": "(uid={username})",
                "loginAttr": "uid",
                "emailAttr": "mail",
                "displayAttr": "cn",
                "adminLoginEnabled": False,
                "showStatusOnLogin": True,
            }
        return {
            "enabled": bool(row["enabled"]),
            "serverURI": row["server_uri"],
            "startTLS": bool(row["start_tls"]),
            "verifyCert": bool(row["verify_cert"]),
            "caCert": row["ca_cert"],
            "bindDN": row["bind_dn"],
            "hasBindPassword": bool(row["bind_password_enc"]),
            "baseDN": row["base_dn"],
            "userFilter": row["user_filter"],
            "loginAttr": row["login_attr"],
            "emailAttr": row["email_attr"],
            "displayAttr": row["display_attr"],
            "adminLoginEnabled": self._row_flag(row, "admin_login_enabled"),
            "showStatusOnLogin": self._row_flag(row, "show_status_on_login", default=True),
        }

    @property
    def ldap_admin_login_enabled(self) -> bool:
        """Whether directory accounts may sign in to the admin interface (opt-in).

        Requires the directory to be enabled at all; admin rights are still enforced
        separately (a directory user must be promoted to admin to get in)."""
        with self._lock:
            row = self._ldap_row()
        return bool(row and row["enabled"] and self._row_flag(row, "admin_login_enabled"))

    @staticmethod
    def _row_flag(row: sqlite3.Row, name: str, default: bool = False) -> bool:
        """Read an optional boolean column that may predate a migration."""
        return bool(row[name]) if name in row.keys() else default

    @property
    def ldap_show_status_on_login(self) -> bool:
        """Whether the login panels show the directory-server availability LED.

        Only meaningful when a directory is configured; defaults to on so the LED
        keeps appearing unless an admin turns it off."""
        with self._lock:
            row = self._ldap_row()
        return self._row_flag(row, "show_status_on_login", default=True) if row else True

    def ldap_settings(self):
        """Build the LdapSettings used for authentication (bind password decrypted)."""
        from ..services.ldap_auth import LdapSettings

        with self._lock:
            row = self._ldap_row()
        if row is None:
            return LdapSettings()
        return LdapSettings(
            enabled=bool(row["enabled"]),
            server_uri=row["server_uri"],
            start_tls=bool(row["start_tls"]),
            verify_cert=bool(row["verify_cert"]),
            ca_cert=row["ca_cert"],
            bind_dn=row["bind_dn"],
            bind_password=decrypt_text(row["bind_password_enc"]) if row["bind_password_enc"] else "",
            base_dn=row["base_dn"],
            user_filter=row["user_filter"] or "(uid={username})",
            login_attr=row["login_attr"] or "uid",
            email_attr=row["email_attr"] or "mail",
            display_attr=row["display_attr"] or "cn",
        )

    def set_ldap_config(self, data: dict) -> None:
        """Upsert the single LDAP config row. The bind password follows the same
        secret rule as connections: pass ``bindPassword`` to set it, omit to keep
        the stored value, or pass an empty string to clear it."""
        with self._lock:
            existing = self._ldap_row()
            if "bindPassword" in data:
                pw = data["bindPassword"] or ""
                bind_enc = encrypt_text(pw) if pw else ""
            else:
                bind_enc = existing["bind_password_enc"] if existing else ""
            self._conn.execute(
                """
                INSERT INTO ldap_config
                    (id, enabled, server_uri, start_tls, verify_cert, ca_cert, bind_dn,
                     bind_password_enc, base_dn, user_filter, login_attr, email_attr,
                     display_attr, admin_login_enabled, show_status_on_login, updated_at)
                VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    enabled=excluded.enabled, server_uri=excluded.server_uri,
                    start_tls=excluded.start_tls, verify_cert=excluded.verify_cert,
                    ca_cert=excluded.ca_cert, bind_dn=excluded.bind_dn,
                    bind_password_enc=excluded.bind_password_enc, base_dn=excluded.base_dn,
                    user_filter=excluded.user_filter, login_attr=excluded.login_attr,
                    email_attr=excluded.email_attr, display_attr=excluded.display_attr,
                    admin_login_enabled=excluded.admin_login_enabled,
                    show_status_on_login=excluded.show_status_on_login,
                    updated_at=excluded.updated_at
                """,
                (
                    int(bool(data.get("enabled"))),
                    (data.get("serverURI") or "").strip(),
                    int(bool(data.get("startTLS"))),
                    int(bool(data.get("verifyCert", True))),
                    data.get("caCert") or "",
                    (data.get("bindDN") or "").strip(),
                    bind_enc,
                    (data.get("baseDN") or "").strip(),
                    (data.get("userFilter") or "(uid={username})").strip(),
                    (data.get("loginAttr") or "uid").strip(),
                    (data.get("emailAttr") or "mail").strip(),
                    (data.get("displayAttr") or "cn").strip(),
                    int(bool(data.get("adminLoginEnabled"))),
                    int(bool(data.get("showStatusOnLogin", True))),
                    _now(),
                ),
            )
            self._conn.commit()

    def provision_ldap_user(self, username: str, email: str = "", display_name: str = "") -> User:
        """Create (or refresh) the local record for a directory user on login.

        Directory users have no local password; their admin/enabled flags and DB
        connection assignments still live here, so a row must exist locally.
        """
        username = username.strip()
        existing = self.get_user(username)
        with self._lock:
            if existing is None:
                self._conn.execute(
                    "INSERT INTO users (username, password_hash, is_admin, is_enabled, "
                    "created_at, auth_source, email, display_name) "
                    "VALUES (?, '', 0, 1, ?, 'ldap', ?, ?)",
                    (username, _now(), email, display_name),
                )
            else:
                # Keep the directory-sourced attributes fresh; never touch role/enabled.
                self._conn.execute(
                    "UPDATE users SET email = ?, display_name = ? "
                    "WHERE LOWER(username) = LOWER(?)",
                    (email, display_name, username),
                )
            self._conn.commit()
        return self.get_user(username)  # type: ignore[return-value]

    # ── config ────────────────────────────────────────────────────────────────

    def _get_config(self, key: str) -> str | None:
        row = self._conn.execute(
            "SELECT value FROM security_config WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else None

    def _set_config(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT INTO security_config (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )

    @property
    def tls_mode(self) -> str:
        with self._lock:
            return self._get_config("tls_mode") or TLS_OFF

    def set_tls_mode(self, mode: str) -> None:
        if mode not in _TLS_MODES:
            raise ValueError(f"Unknown TLS mode {mode!r}")
        with self._lock:
            self._set_config("tls_mode", mode)
            self._conn.commit()
        self._materialise_active_cert()

    @property
    def active_cert_id(self) -> str | None:
        with self._lock:
            return self._get_config("active_cert_id")

    # ── per-connection rebuild token ────────────────────────────────────────
    # A high-entropy bearer token that lets an external scheduler (cron/ETL)
    # trigger a rebuild of ONE connection after loading its JOURNEYS, without an
    # admin session. Scoped per connection so a leaked token can only rebuild that
    # connection. Only the SHA-256 hash is stored; the plaintext is shown once.

    @staticmethod
    def _rebuild_token_key(conn_id: str) -> str:
        return f"rebuild_token:{conn_id}"

    def generate_rebuild_token(self, conn_id: str) -> str:
        """Create (or rotate) this connection's rebuild token; return plaintext ONCE."""
        token = secrets.token_urlsafe(32)
        digest = hashlib.sha256(token.encode()).hexdigest()
        with self._lock:
            self._set_config(self._rebuild_token_key(conn_id), digest)
            self._conn.commit()
        return token

    def clear_rebuild_token(self, conn_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "DELETE FROM security_config WHERE key = ?",
                (self._rebuild_token_key(conn_id),),
            )
            self._conn.commit()

    def rebuild_token_set(self, conn_id: str) -> bool:
        with self._lock:
            return bool(self._get_config(self._rebuild_token_key(conn_id)))

    def verify_rebuild_token(self, conn_id: str, token: str) -> bool:
        """Constant-time check of a token against THIS connection's stored hash."""
        if not token:
            return False
        with self._lock:
            stored = self._get_config(self._rebuild_token_key(conn_id))
        if not stored:
            return False
        presented = hashlib.sha256(token.encode()).hexdigest()
        return hmac.compare_digest(stored, presented)

    # ── per-connection materialisation status (for the admin display) ───────

    def materialization_status(self, conn_id: str) -> dict | None:
        """Last rebuild outcome for a connection: {ok, rows, built_at, error}."""
        with self._lock:
            raw = self._get_config(f"matview:{conn_id}")
        if not raw:
            return None
        try:
            return json.loads(raw)
        except (ValueError, TypeError):
            return None

    def set_materialization_status(self, conn_id: str, status: dict) -> None:
        with self._lock:
            self._set_config(f"matview:{conn_id}", json.dumps(status))
            self._conn.commit()

    # ── login-page appearance ───────────────────────────────────────────────

    def login_appearance(self) -> dict:
        """Background chosen in the admin Customize tab, applied to both sign-in
        pages. `type` is default|color|image; only the field for the active type
        is meaningful."""
        with self._lock:
            bg_type = self._get_config("login_bg_type") or LOGIN_BG_DEFAULT
            if bg_type not in _LOGIN_BG_TYPES:
                bg_type = LOGIN_BG_DEFAULT
            return {
                "type": bg_type,
                "color": self._get_config("login_bg_color") or "",
                "image": self._get_config("login_bg_image") or "",
                # Release label shown on every sign-in panel (from the VERSION file).
                "version": APP_VERSION,
            }

    def set_login_appearance(
        self, *, type: str, color: str = "", image: str | None = None
    ) -> dict:
        """Persist the login background. Validates every field so the stored
        values are always safe to inject into CSS (no injection / no bloat).
        Raises ValueError on bad input. Returns the stored appearance."""
        if type not in _LOGIN_BG_TYPES:
            raise ValueError(f"Unknown login background type {type!r}")

        # Validate ANY supplied value up front, not just the one matching `type`,
        # so a non-active field can never persist an unvalidated (CSS-unsafe)
        # value — even though the render side re-checks before injecting.
        color = (color or "").strip()
        if color and not _HEX_COLOR_RE.match(color):
            raise ValueError("Color must be a #rrggbb hex value")
        if image is not None:
            image = image.strip()
            if image:
                if len(image) > _MAX_LOGIN_IMAGE_CHARS:
                    raise ValueError("Image is too large (max ~3 MB)")
                if not _DATA_IMAGE_RE.match(image):
                    raise ValueError(
                        "Background image must be a PNG, JPEG, GIF, WebP or SVG"
                    )

        if type == LOGIN_BG_COLOR and not color:
            raise ValueError("Color must be a #rrggbb hex value")
        if type == LOGIN_BG_IMAGE:
            # No new upload → the already-stored image must itself be valid.
            candidate = image if image else (self._get_config("login_bg_image") or "")
            if not candidate:
                raise ValueError("Choose a background image first")
            if len(candidate) > _MAX_LOGIN_IMAGE_CHARS or not _DATA_IMAGE_RE.match(
                candidate
            ):
                raise ValueError("Choose a valid background image first")

        with self._lock:
            self._set_config("login_bg_type", type)
            if color:
                self._set_config("login_bg_color", color)
            if image:
                self._set_config("login_bg_image", image)
            self._conn.commit()
        return self.login_appearance()

    # ── AI reporting (admin "Reporting" tab) ────────────────────────────────────
    #
    # The high-gloss AI report uses its OWN LLM (separate from the per-connection LLM the
    # app queries for the interactive documentation), a small style theme, and a library of
    # analysis prompts keyed by (connection, project). All admin-owned, stored here so the
    # compute backend — which shares this security.sqlite3 — can read them when it builds a
    # report. The report LLM key is encrypted at rest, like the connection LLM keys.

    def report_config(self, *, with_secret: bool = False) -> dict:
        """The report LLM, shared by all projects. Style & Sections are per (connection,
        project) — see `report_style_for` / `set_report_style`. `with_secret` includes the
        decrypted API key (backend use only); the admin channel never returns it."""
        with self._lock:
            key_enc = self._get_config("report_llm_key_enc") or ""
            cfg = {
                "llmUrl": self._get_config("report_llm_url") or "",
                "llmModel": self._get_config("report_llm_model") or "",
                "hasLlmKey": bool(key_enc),
            }
            if with_secret:
                cfg["llmKey"] = decrypt_text(key_enc) if key_enc else ""
            return cfg

    def set_report_config(
        self, *, llm_url: str = "", llm_model: str = "", llm_key: str | None = None
    ) -> dict:
        """Persist the report LLM. A `llm_key` of None leaves the stored key unchanged
        (blank clears it)."""
        with self._lock:
            self._set_config("report_llm_url", (llm_url or "").strip())
            self._set_config("report_llm_model", (llm_model or "").strip())
            if llm_key is not None:
                self._set_config(
                    "report_llm_key_enc", encrypt_text(llm_key) if llm_key.strip() else ""
                )
            self._conn.commit()
        return self.report_config()

    # ── per-project report style ("Style & Sections") ──────────────────────────
    # A service provider runs one environment for many customers, so the report look
    # (accent, letterhead, logo, position, which sections to include) is stored PER
    # (connection, project) — matching the analysis-prompt keying. A project with no
    # style configured falls back to a plain built-in theme (see DEFAULT_REPORT_STYLE).

    def _validate_style_bits(self, accent: str, logo: str | None) -> None:
        if accent and not _HEX_COLOR_RE.match(accent):
            raise ValueError("Accent must be a #rrggbb hex value")
        if logo:
            if len(logo) > _MAX_LOGIN_IMAGE_CHARS:
                raise ValueError("Logo is too large (max ~3 MB)")
            if not _DATA_IMAGE_RE.match(logo):
                raise ValueError("Logo must be a PNG, JPEG, GIF, WebP or SVG data URL")

    def _report_styles_raw(self) -> list[dict]:
        with self._lock:
            raw = self._get_config("report_styles")
        try:
            data = json.loads(raw) if raw else []
        except json.JSONDecodeError:
            data = []
        return data if isinstance(data, list) else []

    def report_styles(self) -> list[dict]:
        """Every configured project style, one row per (connection, project). The heavy
        logo data URI is omitted here (replaced by `hasLogo`) so the list stays small;
        use `report_style_for` to fetch the full entry incl. the logo."""
        out = []
        for r in self._report_styles_raw():
            out.append({
                "connectionId": r.get("connectionId") or "",
                "projectId": r.get("projectId") or "",
                "accent": r.get("accent") or "#4a3aa7",
                "orgName": r.get("orgName") or "",
                "logoPos": "right" if r.get("logoPos") == "right" else "left",
                "logoScale": self._clamp_logo_scale(r.get("logoScale", 1.0)),
                "hasLogo": bool(r.get("logo")),
                "includeSankey": r.get("includeSankey", True),
                "includeHappyPath": r.get("includeHappyPath", True),
                "includeConformance": r.get("includeConformance", True),
            })
        return out

    @staticmethod
    def _clamp_logo_scale(value: object) -> float:
        """Logo size multiplier, clamped to [0.5, 2.0]; defaults to 1.0 on bad input."""
        try:
            return round(min(2.0, max(0.5, float(value))), 2)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 1.0

    def report_style_for(self, connection_id: str, project_id: str) -> dict | None:
        """The full style (incl. logo) for this (connection, project), or None when the
        project has none configured."""
        for r in self._report_styles_raw():
            if r.get("connectionId") == connection_id and r.get("projectId") == project_id:
                return {
                    "accent": r.get("accent") or "#4a3aa7",
                    "orgName": r.get("orgName") or "",
                    "logo": r.get("logo") or "",
                    "logoPos": "right" if r.get("logoPos") == "right" else "left",
                    "logoScale": self._clamp_logo_scale(r.get("logoScale", 1.0)),
                    "includeSankey": r.get("includeSankey", True),
                    "includeHappyPath": r.get("includeHappyPath", True),
                    "includeConformance": r.get("includeConformance", True),
                }
        return None

    def set_report_style(
        self,
        connection_id: str,
        project_id: str,
        *,
        accent: str = "",
        org_name: str = "",
        logo: str | None = None,
        logo_pos: str = "left",
        logo_scale: float = 1.0,
        include_sankey: bool = True,
        include_happy_path: bool = True,
        include_conformance: bool = True,
    ) -> list[dict]:
        """Upsert the Style & Sections for one (connection, project). A `logo` of None
        keeps that project's stored logo; "" clears it. Validates accent + logo."""
        connection_id = (connection_id or "").strip()
        project_id = project_id
        if not connection_id or not project_id:
            raise ValueError("A connection and a project are required")
        accent = (accent or "").strip()
        if logo is not None:
            logo = logo.strip()
        self._validate_style_bits(accent, logo)
        rows = self._report_styles_raw()
        existing = next(
            (r for r in rows
             if r.get("connectionId") == connection_id and r.get("projectId") == project_id),
            None,
        )
        entry = {
            "connectionId": connection_id,
            "projectId": project_id,
            "accent": accent or "#4a3aa7",
            "orgName": (org_name or "").strip()[:120],
            "logo": logo if logo is not None else ((existing or {}).get("logo") or ""),
            "logoPos": "right" if str(logo_pos).lower() == "right" else "left",
            "logoScale": self._clamp_logo_scale(logo_scale),
            "includeSankey": bool(include_sankey),
            "includeHappyPath": bool(include_happy_path),
            "includeConformance": bool(include_conformance),
        }
        rows = [r for r in rows
                if not (r.get("connectionId") == connection_id and r.get("projectId") == project_id)]
        rows.append(entry)
        with self._lock:
            self._set_config("report_styles", json.dumps(rows))
            self._conn.commit()
        return self.report_styles()

    def delete_report_style(self, connection_id: str, project_id: str) -> list[dict]:
        """Remove the style for one (connection, project); the project reverts to the
        built-in default theme."""
        rows = [
            r for r in self._report_styles_raw()
            if not (r.get("connectionId") == connection_id and r.get("projectId") == project_id)
        ]
        with self._lock:
            self._set_config("report_styles", json.dumps(rows))
            self._conn.commit()
        return self.report_styles()

    def report_prompts(self) -> list[dict]:
        """The analysis-prompt library: [{connectionId, projectId, prompt}], each prompt
        the instruction the report LLM follows for that (connection, project)."""
        with self._lock:
            raw = self._get_config("report_prompts")
        try:
            data = json.loads(raw) if raw else []
        except json.JSONDecodeError:
            data = []
        return data if isinstance(data, list) else []

    def set_report_prompt(self, connection_id: str, project_id: str, prompt: str) -> list[dict]:
        """Upsert one (connection, project) → prompt mapping. An empty prompt removes it."""
        connection_id = (connection_id or "").strip()
        project_id = project_id
        prompt = (prompt or "").strip()
        if not connection_id or not project_id:
            raise ValueError("A connection and a project are required")
        rows = [
            r
            for r in self.report_prompts()
            if not (r.get("connectionId") == connection_id and r.get("projectId") == project_id)
        ]
        if prompt:
            rows.append({"connectionId": connection_id, "projectId": project_id, "prompt": prompt[:8000]})
        with self._lock:
            self._set_config("report_prompts", json.dumps(rows))
            self._conn.commit()
        return rows

    def report_prompt_for(self, connection_id: str, project_id: str) -> str | None:
        """The stored analysis prompt for this (connection, project), or None."""
        for r in self.report_prompts():
            if r.get("connectionId") == connection_id and r.get("projectId") == project_id:
                return r.get("prompt") or None
        return None

    # ── Actions (saved node-menu actions, per connection + project) ─────────────

    def _actions_raw(self) -> list[dict]:
        with self._lock:
            raw = self._get_config("actions")
        try:
            data = json.loads(raw) if raw else []
        except json.JSONDecodeError:
            data = []
        return data if isinstance(data, list) else []

    def actions_for(self, connection_id: str, project_id: str) -> list[dict]:
        """The saved actions for this (connection, project), in insertion order."""
        cid, pid = (connection_id or "").strip(), project_id
        return [
            dict(r)
            for r in self._actions_raw()
            if r.get("connectionId") == cid and r.get("projectId") == pid
        ]

    def action_by_id(self, connection_id: str, project_id: str, action_id: str) -> dict | None:
        for r in self.actions_for(connection_id, project_id):
            if r.get("id") == action_id:
                return r
        return None

    def upsert_action(self, connection_id: str, project_id: str, action: dict) -> dict:
        """Create or replace one saved action, keyed by (connection, project, id). The
        caller supplies the id (a fresh uuid on create, the existing id on update)."""
        cid, pid = (connection_id or "").strip(), project_id
        aid = (action.get("id") or "").strip()
        if not cid or not pid:
            raise ValueError("A connection and a project are required")
        if not aid:
            raise ValueError("An action id is required")
        existing = self.action_by_id(cid, pid, aid)
        now = _now()
        record = {
            "id": aid,
            "connectionId": cid,
            "projectId": pid,
            "name": (action.get("name") or "").strip()[:200],
            "script": (action.get("script") or "")[:20000],
            "spec": action.get("spec") or {},
            "enabled": bool(action.get("enabled", True)),
            "author": (action.get("author") or "").strip(),
            "createdAt": (existing or {}).get("createdAt") or now,
            "updatedAt": now,
        }
        rows = [
            r
            for r in self._actions_raw()
            if not (
                r.get("id") == aid
                and r.get("connectionId") == cid
                and r.get("projectId") == pid
            )
        ]
        rows.append(record)
        with self._lock:
            self._set_config("actions", json.dumps(rows))
            self._conn.commit()
        return record

    def delete_action(self, connection_id: str, project_id: str, action_id: str) -> None:
        cid, pid = (connection_id or "").strip(), project_id
        rows = [
            r
            for r in self._actions_raw()
            if not (
                r.get("id") == action_id
                and r.get("connectionId") == cid
                and r.get("projectId") == pid
            )
        ]
        with self._lock:
            self._set_config("actions", json.dumps(rows))
            self._conn.commit()

    # ── Aggregate links (Σ super-step → detail project, per (connection, project)) ──

    def _aggregates_raw(self) -> list[dict]:
        with self._lock:
            raw = self._get_config("aggregates")
        try:
            data = json.loads(raw) if raw else []
        except json.JSONDecodeError:
            data = []
        return data if isinstance(data, list) else []

    def aggregates_for(self, connection_id: str, project_id: int) -> list[dict]:
        """Aggregate links whose HIGH-LEVEL project is this (connection, project) — used
        by the app to offer 'drill down' on a Σ step.

        Falls back to deriving the links from the aggregate SET whose high-level map is
        this (connection, project) when no explicit link rows exist — so drill-down
        works even for aggregates whose link write didn't land (e.g. an older build) and
        without a manual re-create."""
        cid, pid = (connection_id or "").strip(), project_id
        direct = [
            dict(r)
            for r in self._aggregates_raw()
            if r.get("connectionId") == cid and r.get("projectId") == pid
        ]
        if direct:
            return direct
        aset = self.aggregate_set_by_high_level(cid, pid)
        if not aset:
            return []
        return [
            {
                "connectionId": cid,
                "projectId": pid,
                "sigmaStep": a.get("sigmaStep", ""),
                "detailConnectionId": a.get("detailConnectionId", ""),
                "detailProjectId": a.get("detailProjectId"),
            }
            for a in (aset.get("aggregates") or [])
            if a.get("sigmaStep")
        ]

    def add_aggregate_link(self, link: dict) -> dict:
        """Record a Σ step's drill-down target. Keyed by (connectionId, projectId, sigmaStep)
        where connectionId/projectId identify the HIGH-LEVEL project holding the Σ node."""
        cid = (link.get("connectionId") or "").strip()
        pid = link.get("projectId")  # PROJECT_ID is a SMALLINT (int) — stored as-is
        sigma = (link.get("sigmaStep") or "").strip()
        record = {
            "connectionId": cid,
            "projectId": pid,
            "sigmaStep": sigma,
            "detailConnectionId": (link.get("detailConnectionId") or "").strip(),
            # detailProjectId is an int PROJECT_ID — keep it as-is (never .strip(): that
            # would raise AttributeError on the int and leave the Σ node with no drill link).
            "detailProjectId": link.get("detailProjectId"),
            "createdAt": _now(),
        }
        rows = [
            r
            for r in self._aggregates_raw()
            if not (
                r.get("connectionId") == cid
                and r.get("projectId") == pid
                and r.get("sigmaStep") == sigma
            )
        ]
        rows.append(record)
        with self._lock:
            self._set_config("aggregates", json.dumps(rows))
            self._conn.commit()
        return record

    # ── Aggregate sets (the full definition per source project, for re-materialising) ──
    #
    # A set is the source ref + the high-level target + a list of aggregates (each with its
    # members and its own detail target). Keyed uniquely by the SOURCE (connection, project)
    # — one high-level map per source. Stored alongside the per-Σ drill links above so the
    # app can offer 'add another aggregate' later (re-collapse the source with the union).

    def _aggregate_sets_raw(self) -> list[dict]:
        with self._lock:
            raw = self._get_config("aggregate_sets")
        try:
            data = json.loads(raw) if raw else []
        except json.JSONDecodeError:
            data = []
        return data if isinstance(data, list) else []

    def aggregate_set_by_source(self, connection_id: str, project_id: int) -> dict | None:
        cid, pid = (connection_id or "").strip(), project_id
        for r in self._aggregate_sets_raw():
            if r.get("sourceConnectionId") == cid and r.get("sourceProjectId") == pid:
                return dict(r)
        return None

    def aggregate_set_by_high_level(self, connection_id: str, project_id: int) -> dict | None:
        cid, pid = (connection_id or "").strip(), project_id
        for r in self._aggregate_sets_raw():
            if r.get("highLevelConnectionId") == cid and r.get("highLevelProjectId") == pid:
                return dict(r)
        return None

    def aggregate_connection_roles(self) -> dict[str, set[str]]:
        """The specific CONNECTION IDS chosen for each role across all stored aggregate
        sets: ``source`` (the original), ``high`` (the high-level Σ map) and ``detail``
        (the drill-down targets). A connection used SOLELY as a detail target is hideable;
        one that is also a source or high-level connection is not (mirroring 'a high-level
        map is always visible; details may be hidden').

        Matching is by the exact connection picked for the aggregate — NOT by (host,
        schema) — so a *different*, normal connection that merely points at the same
        database/schema as a detail project is never wrongly hidden. (Detail *projects*
        are still hidden per-project via their '#'-prefixed TITLE_SHORT.)"""
        src: set[str] = set()
        high: set[str] = set()
        detail: set[str] = set()
        for s in self._aggregate_sets_raw():
            if cid := (s.get("sourceConnectionId") or "").strip():
                src.add(cid)
            if cid := (s.get("highLevelConnectionId") or "").strip():
                high.add(cid)
            for a in s.get("aggregates") or []:
                if cid := (a.get("detailConnectionId") or "").strip():
                    detail.add(cid)
        return {"source": src, "high": high, "detail": detail}

    def save_aggregate_set(self, record: dict) -> dict:
        """Upsert an aggregate set, keyed by its source (connection, project)."""
        cid = (record.get("sourceConnectionId") or "").strip()
        pid = record.get("sourceProjectId")  # PROJECT_ID is a SMALLINT (int)
        now = _now()
        existing = self.aggregate_set_by_source(cid, pid)
        record = dict(record)
        record["sourceConnectionId"] = cid
        record["sourceProjectId"] = pid
        record["createdAt"] = (existing or {}).get("createdAt", now)
        record["updatedAt"] = now
        rows = [
            r
            for r in self._aggregate_sets_raw()
            if not (r.get("sourceConnectionId") == cid and r.get("sourceProjectId") == pid)
        ]
        rows.append(record)
        with self._lock:
            self._set_config("aggregate_sets", json.dumps(rows))
            self._conn.commit()
        return record

    # ── users ─────────────────────────────────────────────────────────────────

    def _row_to_user(self, row: sqlite3.Row) -> User:
        keys = row.keys()
        return User(
            username=row["username"],
            is_admin=bool(row["is_admin"]),
            is_enabled=bool(row["is_enabled"]),
            created_at=row["created_at"],
            last_login=row["last_login"],
            auth_source=(row["auth_source"] if "auth_source" in keys else "local") or "local",
            email=(row["email"] if "email" in keys else "") or "",
            display_name=(row["display_name"] if "display_name" in keys else "") or "",
            is_power=bool(row["is_power"]) if "is_power" in keys else False,
            is_developer=bool(row["is_developer"]) if "is_developer" in keys else False,
            passkey_allowed=bool(row["passkey_allowed"]) if "passkey_allowed" in keys else False,
            mfa_allowed=bool(row["mfa_allowed"]) if "mfa_allowed" in keys else False,
            mfa_enabled=bool(row["totp_secret_enc"]) if "totp_secret_enc" in keys else False,
            failed_logins=int(row["failed_logins"]) if "failed_logins" in keys else 0,
            login_locked=bool(row["login_locked"]) if "login_locked" in keys else False,
            session_epoch=int(row["session_epoch"]) if "session_epoch" in keys else 0,
        )

    def list_users(self) -> list[User]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM users ORDER BY LOWER(username)"
            ).fetchall()
        return [self._row_to_user(r) for r in rows]

    def get_user(self, username: str) -> User | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM users WHERE LOWER(username) = LOWER(?)", (username,)
            ).fetchone()
        return self._row_to_user(row) if row else None

    def create_user(self, username: str, password: str, is_admin: bool) -> User:
        username = username.strip()
        if not username:
            raise ValueError("Username is required.")
        if not password:
            raise ValueError("Password is required.")
        if self.get_user(username) is not None:
            raise ValueError(f"A user named {username!r} already exists.")
        with self._lock:
            self._conn.execute(
                "INSERT INTO users (username, password_hash, is_admin, is_enabled, created_at) "
                "VALUES (?, ?, ?, 1, ?)",
                (username, hash_password(password), int(is_admin), _now()),
            )
            self._conn.commit()
        return self.get_user(username)  # type: ignore[return-value]

    def set_password(self, username: str, password: str) -> None:
        if not password:
            raise ValueError("Password is required.")
        with self._lock:
            self._conn.execute(
                # Bump the session epoch in the same statement: a password change must
                # invalidate every outstanding token. Otherwise the standard response to
                # a stolen cookie ("reset the password") does nothing — the thief's
                # session keeps working, and because tokens are re-minted on every
                # request it can be kept alive indefinitely. The caller re-issues a
                # cookie for the *current* session where that is the right UX
                # (self-service change), so only OTHER sessions are dropped.
                "UPDATE users SET password_hash = ?, session_epoch = session_epoch + 1 "
                "WHERE LOWER(username) = LOWER(?)",
                (hash_password(password), username),
            )
            # Changing the bootstrap admin's password clears the default-password flag.
            if username.lower() == DEFAULT_ADMIN_USERNAME.lower():
                self._conn.execute(
                    "DELETE FROM security_config WHERE key = 'default_admin_active'"
                )
            self._conn.commit()

    def set_enabled(self, username: str, enabled: bool) -> None:
        user = self.get_user(username)
        if user is None:
            raise ValueError("No such user.")
        if not enabled and self._is_builtin_admin(username):
            raise ValueError("The built-in Administrator account cannot be disabled.")
        if not enabled and user.is_admin:
            self._guard_last_admin(exclude=username)
        with self._lock:
            # Re-enabling also clears any failed-sign-in lockout (and its counter).
            if enabled:
                self._conn.execute(
                    "UPDATE users SET is_enabled = 1, login_locked = 0, "
                    "failed_logins = 0 WHERE LOWER(username) = LOWER(?)",
                    (username,),
                )
            else:
                self._conn.execute(
                    "UPDATE users SET is_enabled = 0 WHERE LOWER(username) = LOWER(?)",
                    (username,),
                )
            self._conn.commit()

    def set_admin(self, username: str, is_admin: bool) -> None:
        user = self.get_user(username)
        if user is None:
            raise ValueError("No such user.")
        if not is_admin and self._is_builtin_admin(username):
            raise ValueError(
                "The built-in Administrator account must remain an administrator."
            )
        if not is_admin and user.is_admin:
            self._guard_last_admin(exclude=username)
        with self._lock:
            self._conn.execute(
                "UPDATE users SET is_admin = ? WHERE LOWER(username) = LOWER(?)",
                (int(is_admin), username),
            )
            self._conn.commit()

    def set_power(self, username: str, is_power: bool) -> None:
        """Grant/revoke the 'power' role — may create & manage their own connections."""
        if self.get_user(username) is None:
            raise ValueError("No such user.")
        with self._lock:
            self._conn.execute(
                "UPDATE users SET is_power = ? WHERE LOWER(username) = LOWER(?)",
                (int(is_power), username),
            )
            self._conn.commit()

    def set_developer(self, username: str, is_developer: bool) -> None:
        """Grant/revoke the 'developer' role — may enter the integration console."""
        if self.get_user(username) is None:
            raise ValueError("No such user.")
        with self._lock:
            self._conn.execute(
                "UPDATE users SET is_developer = ? WHERE LOWER(username) = LOWER(?)",
                (int(is_developer), username),
            )
            self._conn.commit()

    def set_passkey_allowed(self, username: str, allowed: bool) -> None:
        """Grant/revoke a user's permission to enrol and sign in with a passkey."""
        if self.get_user(username) is None:
            raise ValueError("No such user.")
        with self._lock:
            self._conn.execute(
                "UPDATE users SET passkey_allowed = ? WHERE LOWER(username) = LOWER(?)",
                (int(allowed), username),
            )
            self._conn.commit()

    def set_passkey_allowed_all(self, allowed: bool) -> None:
        """Master toggle — allow/deny passkeys for every user at once."""
        with self._lock:
            self._conn.execute("UPDATE users SET passkey_allowed = ?", (int(allowed),))
            self._conn.commit()

    # ── Two-factor authentication (TOTP) ────────────────────────────────────
    # An admin allows a user to enrol; the user confirms a code, which stores the
    # secret (encrypted at rest) and a set of one-time recovery codes (hashed).
    # `mfa_active` — the login gate — is allowed AND enrolled, so revoking the
    # permission relaxes the second factor rather than locking the user out.

    def set_mfa_allowed(self, username: str, allowed: bool) -> None:
        """Grant/revoke a user's permission to enrol two-factor authentication."""
        if self.get_user(username) is None:
            raise ValueError("No such user.")
        with self._lock:
            self._conn.execute(
                "UPDATE users SET mfa_allowed = ? WHERE LOWER(username) = LOWER(?)",
                (int(allowed), username),
            )
            self._conn.commit()

    def set_mfa_allowed_all(self, allowed: bool) -> None:
        """Master toggle — allow/deny two-factor enrolment for every user at once."""
        with self._lock:
            self._conn.execute("UPDATE users SET mfa_allowed = ?", (int(allowed),))
            self._conn.commit()

    def set_totp_secret(self, username: str, secret: str) -> None:
        """Store (encrypted) a confirmed TOTP secret for the user."""
        if self.get_user(username) is None:
            raise ValueError("No such user.")
        enc = encrypt_text(secret) if secret else ""
        with self._lock:
            self._conn.execute(
                "UPDATE users SET totp_secret_enc = ? WHERE LOWER(username) = LOWER(?)",
                (enc, username),
            )
            self._conn.commit()

    def get_totp_secret(self, username: str) -> str | None:
        """Return the user's decrypted TOTP secret, or None if not enrolled."""
        with self._lock:
            row = self._conn.execute(
                "SELECT totp_secret_enc FROM users WHERE LOWER(username) = LOWER(?)",
                (username,),
            ).fetchone()
        if not row or not row["totp_secret_enc"]:
            return None
        try:
            return decrypt_text(row["totp_secret_enc"])
        except Exception:  # noqa: BLE001 — a corrupt/rotated key means "not usable"
            return None

    def mfa_active(self, username: str) -> bool:
        """The login gate: the user is both allowed AND enrolled."""
        user = self.get_user(username)
        return bool(user and user.mfa_allowed and user.mfa_enabled)

    def mfa_setup_required(self, username: str) -> bool:
        """Allowed to use two-factor but not yet enrolled — enabling 2FA for a user
        makes it MANDATORY, so they must set it up before a session is issued rather
        than sign in with the password alone."""
        user = self.get_user(username)
        return bool(user and user.mfa_allowed and not user.mfa_enabled)

    def clear_mfa(self, username: str) -> None:
        """Turn two-factor off for the user: drop the secret and recovery codes."""
        with self._lock:
            self._conn.execute(
                "UPDATE users SET totp_secret_enc = '' WHERE LOWER(username) = LOWER(?)",
                (username,),
            )
            self._conn.execute(
                "DELETE FROM mfa_recovery_codes WHERE LOWER(username) = LOWER(?)", (username,)
            )
            self._conn.commit()

    @staticmethod
    def _recovery_hash(code: str) -> str:
        """Recovery codes are high-entropy, so a fast salted SHA-256 is sufficient
        (unlike low-entropy passwords, which need a slow KDF)."""
        norm = code.replace("-", "").replace(" ", "").upper()
        return hashlib.sha256((recovery_code_pepper() + norm).encode("utf-8")).hexdigest()

    def set_recovery_codes(self, username: str, codes: list[str]) -> None:
        """Replace the user's recovery codes with hashes of the supplied set."""
        with self._lock:
            self._conn.execute(
                "DELETE FROM mfa_recovery_codes WHERE LOWER(username) = LOWER(?)", (username,)
            )
            self._conn.executemany(
                "INSERT INTO mfa_recovery_codes (id, username, code_hash, used_at, created_at) "
                "VALUES (?, ?, ?, NULL, ?)",
                [(str(uuid.uuid4()), username, self._recovery_hash(c), _now()) for c in codes],
            )
            self._conn.commit()

    def consume_recovery_code(self, username: str, code: str) -> bool:
        """Mark a matching unused recovery code as used. Returns True on success."""
        target = self._recovery_hash(code)
        with self._lock:
            row = self._conn.execute(
                "SELECT id FROM mfa_recovery_codes WHERE LOWER(username) = LOWER(?) "
                "AND code_hash = ? AND used_at IS NULL",
                (username, target),
            ).fetchone()
            if row is None:
                return False
            self._conn.execute(
                "UPDATE mfa_recovery_codes SET used_at = ? WHERE id = ?", (_now(), row["id"])
            )
            self._conn.commit()
            return True

    def recovery_codes_remaining(self, username: str) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM mfa_recovery_codes "
                "WHERE LOWER(username) = LOWER(?) AND used_at IS NULL",
                (username,),
            ).fetchone()
        return int(row["n"]) if row else 0

    def delete_user(self, username: str) -> None:
        user = self.get_user(username)
        if user is None:
            return
        if self._is_builtin_admin(username):
            raise ValueError("The built-in Administrator account cannot be deleted.")
        if user.is_admin:
            self._guard_last_admin(exclude=username)
        with self._lock:
            self._conn.execute(
                "DELETE FROM users WHERE LOWER(username) = LOWER(?)", (username,)
            )
            self._conn.execute(
                "DELETE FROM credentials WHERE LOWER(username) = LOWER(?)", (username,)
            )
            self._conn.execute(
                "DELETE FROM mfa_recovery_codes WHERE LOWER(username) = LOWER(?)", (username,)
            )
            self._conn.commit()

    # ── Passkey (WebAuthn) credentials ──────────────────────────────────────
    # Public keys aren't secret, but the sign counter guards against cloned-
    # authenticator replay. Keyed on username (case-insensitive), so both local
    # and directory users can own credentials.

    def add_credential(
        self,
        username: str,
        *,
        credential_id: str,
        public_key: str,
        sign_count: int,
        transports: str = "",
        name: str = "",
    ) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO credentials (id, username, credential_id, public_key, "
                "sign_count, transports, name, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), username, credential_id, public_key,
                 int(sign_count), transports, name, _now()),
            )
            self._conn.commit()

    def list_credentials(self, username: str) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM credentials WHERE LOWER(username) = LOWER(?) "
                "ORDER BY created_at",
                (username,),
            ).fetchall()
        return [self._cred_public(r) for r in rows]

    def get_credential(self, credential_id: str) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(
                "SELECT * FROM credentials WHERE credential_id = ?", (credential_id,)
            ).fetchone()

    def credential_ids_for(self, username: str) -> list[str]:
        """Raw credential_id (base64url) strings for a user — for allowCredentials
        (login) and exclude_credentials (registration)."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT credential_id FROM credentials WHERE LOWER(username) = LOWER(?)",
                (username,),
            ).fetchall()
        return [r["credential_id"] for r in rows]

    def set_credential_sign_count(self, credential_id: str, count: int) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE credentials SET sign_count = ? WHERE credential_id = ?",
                (int(count), credential_id),
            )
            self._conn.commit()

    def delete_credential(self, cred_id: str, username: str) -> bool:
        """Remove one of a user's credentials (owner-scoped). Returns True if removed."""
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM credentials WHERE id = ? AND LOWER(username) = LOWER(?)",
                (cred_id, username),
            )
            self._conn.commit()
            return cur.rowcount > 0

    @staticmethod
    def _cred_public(row: sqlite3.Row) -> dict:
        return {
            "id": row["id"],
            "name": row["name"] or "",
            "createdAt": row["created_at"],
            "transports": row["transports"] or "",
        }

    def _is_builtin_admin(self, username: str) -> bool:
        """The seeded default administrator, protected from disable / demote."""
        return username.strip().lower() == DEFAULT_ADMIN_USERNAME.lower()

    def _guard_last_admin(self, exclude: str) -> None:
        """Refuse an operation that would leave no enabled administrator."""
        remaining = [
            u
            for u in self.list_users()
            if u.is_admin
            and u.is_enabled
            and u.username.lower() != exclude.lower()
        ]
        if not remaining:
            raise ValueError(
                "This would leave no enabled administrator. Promote or enable "
                "another admin first."
            )

    def authenticate(self, username: str, password: str) -> User | None:
        """Return the user on a successful, enabled login; None otherwise.

        A failed sign-in on an enabled account is counted and can lock the account
        (see max_failed_logins); a success clears the counter. One scrypt check runs
        even when the account is missing, so timing doesn't reveal its existence.
        """
        # An aged-out lockout is lifted before the attempt, so a locked-out user can
        # simply try again after the window instead of needing an administrator.
        self._clear_expired_lockout(username)
        user = self.get_user(username)
        with self._lock:
            row = self._conn.execute(
                "SELECT password_hash FROM users WHERE LOWER(username) = LOWER(?)",
                (username,),
            ).fetchone()
        password_ok = verify_password(
            password, row["password_hash"] if row is not None else _DUMMY_HASH
        )
        if user is None or row is None:
            return None
        if not password_ok:
            # Count local-password failures only; directory users have no local
            # password (a local check always "fails" for them and is authenticated
            # via LDAP separately), and an already-disabled account isn't re-counted.
            if user.is_enabled and user.auth_source != "ldap":
                self.record_login_failure(username)
            return None
        if not user.is_enabled:
            return None  # correct password, but the account is disabled / locked
        self.reset_login_failures(username)
        with self._lock:
            self._conn.execute(
                "UPDATE users SET last_login = ? WHERE LOWER(username) = LOWER(?)",
                (_now(), username),
            )
            self._conn.commit()
        return user

    def authenticate_app(self, username: str, password: str) -> User | None:
        """Authenticate a *main-app* sign-in: local accounts first (always, so a
        local admin stays a break-glass account), then the directory when enabled.

        Admin rights are never granted from LDAP — a JIT-provisioned directory user
        is a plain, enabled user until an admin promotes them locally.
        """
        local = self.authenticate(username, password)
        if local is not None:
            return local

        if not self.ldap_enabled:
            return None

        from ..services.ldap_auth import LdapError, authenticate as ldap_authenticate

        try:
            dir_user = ldap_authenticate(self.ldap_settings(), username, password)
        except LdapError as exc:
            log.warning("LDAP authentication error for %r: %s", username, exc)
            return None
        if dir_user is None:
            return None

        # A directory identity must never bind onto a LOCAL account (the break-glass
        # admin, a local power user, …) that merely shares its name: merging would
        # hand the directory user that local account's role and DB-connection
        # assignments. Only ever merge onto a row that is itself directory-sourced.
        # (A directory user an admin has locally promoted keeps auth_source='ldap',
        # so legitimate promoted accounts are unaffected.)
        #
        # Normalise the directory username with the SAME strip() that
        # provision_ldap_user applies, and use that single value for both the
        # refusal check and provisioning — otherwise a directory name like
        # "Administrator " (trailing space) would slip past a raw-name check yet be
        # trimmed onto the local Administrator when provisioned.
        canonical = dir_user.username.strip()
        if not canonical:
            return None
        existing = self.get_user(canonical)
        if existing is not None and existing.auth_source != "ldap":
            log.warning(
                "LDAP sign-in for %r refused: a local (non-directory) account with "
                "that name already exists",
                canonical,
            )
            return None

        user = self.provision_ldap_user(
            canonical, email=dir_user.email, display_name=dir_user.display_name
        )
        if not user.is_enabled:
            return None  # an admin has blocked this directory account locally
        with self._lock:
            self._conn.execute(
                "UPDATE users SET last_login = ? WHERE LOWER(username) = LOWER(?)",
                (_now(), user.username),
            )
            self._conn.commit()
        return self.get_user(user.username)

    # ── certificates ──────────────────────────────────────────────────────────

    def _row_to_cert(self, row: sqlite3.Row) -> Certificate:
        return Certificate(
            id=row["id"],
            name=row["name"],
            subject=row["subject"] or "",
            issuer=row["issuer"] or "",
            not_before=row["not_before"] or "",
            not_after=row["not_after"] or "",
            sans=(row["sans"] or "").split(",") if row["sans"] else [],
            is_self_signed=bool(row["is_self_signed"]),
            created_at=row["created_at"],
        )

    def list_certificates(self) -> list[Certificate]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM certificates ORDER BY created_at DESC"
            ).fetchall()
        return [self._row_to_cert(r) for r in rows]

    def get_certificate(self, cert_id: str) -> Certificate | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM certificates WHERE id = ?", (cert_id,)
            ).fetchone()
        return self._row_to_cert(row) if row else None

    def certificate_pem(self, cert_id: str) -> str | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT cert_pem FROM certificates WHERE id = ?", (cert_id,)
            ).fetchone()
        return row["cert_pem"] if row else None

    def _store_certificate(
        self, name: str, cert_pem: str, key_pem: str, info: cert_service.CertInfo
    ) -> Certificate:
        cert_id = str(uuid.uuid4())
        with self._lock:
            self._conn.execute(
                "INSERT INTO certificates "
                "(id, name, cert_pem, key_enc, subject, issuer, not_before, not_after, "
                " sans, is_self_signed, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    cert_id,
                    name.strip() or "certificate",
                    cert_pem,
                    encrypt_text(key_pem),
                    info.subject,
                    info.issuer,
                    info.not_before,
                    info.not_after,
                    ",".join(info.sans),
                    int(info.is_self_signed),
                    _now(),
                ),
            )
            self._conn.commit()
        return self.get_certificate(cert_id)  # type: ignore[return-value]

    def generate_certificate(
        self, *, name: str, common_name: str, sans: list[str], days: int, key_size: int
    ) -> Certificate:
        cert_pem, key_pem = cert_service.generate_self_signed(
            common_name=common_name, sans=sans, days=days, key_size=key_size
        )
        info = cert_service.inspect(cert_pem)
        return self._store_certificate(name, cert_pem, key_pem, info)

    def upload_certificate(
        self, *, name: str, cert_pem: str, key_pem: str
    ) -> Certificate:
        info = cert_service.validate_pair(cert_pem, key_pem)
        return self._store_certificate(name, cert_pem, key_pem, info)

    def activate_certificate(self, cert_id: str) -> None:
        if self.get_certificate(cert_id) is None:
            raise ValueError("No such certificate.")
        with self._lock:
            self._set_config("active_cert_id", cert_id)
            self._conn.commit()
        self._materialise_active_cert()

    def delete_certificate(self, cert_id: str) -> None:
        with self._lock:
            if self._get_config("active_cert_id") == cert_id:
                self._conn.execute(
                    "DELETE FROM security_config WHERE key = 'active_cert_id'"
                )
            self._conn.execute("DELETE FROM certificates WHERE id = ?", (cert_id,))
            self._conn.commit()
        self._materialise_active_cert()

    def _materialise_active_cert(self) -> None:
        """Write (or clear) the active certificate on disk for the TLS listener."""
        with self._lock:
            cert_id = self._get_config("active_cert_id")
            row = (
                self._conn.execute(
                    "SELECT cert_pem, key_enc FROM certificates WHERE id = ?",
                    (cert_id,),
                ).fetchone()
                if cert_id
                else None
            )
        if row is None:
            ACTIVE_CERT_PATH.unlink(missing_ok=True)
            ACTIVE_KEY_PATH.unlink(missing_ok=True)
            return
        ACTIVE_CERT_PATH.write_text(row["cert_pem"], encoding="utf-8")
        ACTIVE_CERT_PATH.chmod(0o600)
        # The private key is written 0600-from-birth (no world-readable window).
        write_private_file(ACTIVE_KEY_PATH, decrypt_text(row["key_enc"]))

    # ── connections & assignments ────────────────────────────────────────────

    def _row_to_connection(self, row: sqlite3.Row, *, with_secrets: bool) -> Connection:
        assignments = [
            r["username"]
            for r in self._conn.execute(
                "SELECT username FROM connection_assignments WHERE connection_id = ? "
                "ORDER BY LOWER(username)",
                (row["id"],),
            ).fetchall()
        ]
        return Connection(
            id=row["id"],
            name=row["name"],
            comment=row["comment"] or "",
            host=row["host"] or "",
            port=row["port"] or 8563,
            username=row["username"] or "",
            schema=row["db_schema"] or "",
            use_tls=bool(row["use_tls"]),
            cert_mode=row["cert_mode"] or "verify",
            fingerprint=row["fingerprint"] or "",
            min_rsa_bits=row["min_rsa_bits"] or 2048,
            password=decrypt_text(row["password_enc"]) if with_secrets and row["password_enc"] else "",
            llm_url=row["llm_url"] or "",
            llm_model=row["llm_model"] or "",
            llm_api_key=decrypt_text(row["llm_key_enc"]) if with_secrets and row["llm_key_enc"] else "",
            assignments=assignments,
            has_password=bool(row["password_enc"]),
            has_llm_key=bool(row["llm_key_enc"]),
            owner=(row["owner"] if "owner" in row.keys() else "") or "",
            created_at=row["created_at"],
            use_materialized_transitions=bool(
                row["use_materialized_transitions"]
                if "use_materialized_transitions" in row.keys()
                else 0
            ),
            use_indb_sampling=bool(
                row["use_indb_sampling"] if "use_indb_sampling" in row.keys() else 0
            ),
        )

    def list_connections(self) -> list[Connection]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM connections ORDER BY LOWER(name)"
            ).fetchall()
            return [self._row_to_connection(r, with_secrets=False) for r in rows]

    def connections_for_user(self, username: str | None) -> list[Connection]:
        """Connections assigned to `username`. When `username` is None (sign-in not
        required), every connection is visible."""
        with self._lock:
            if username is None:
                rows = self._conn.execute(
                    "SELECT * FROM connections ORDER BY LOWER(name)"
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT c.* FROM connections c "
                    "JOIN connection_assignments a ON a.connection_id = c.id "
                    "WHERE LOWER(a.username) = LOWER(?) ORDER BY LOWER(c.name)",
                    (username,),
                ).fetchall()
            return [self._row_to_connection(r, with_secrets=False) for r in rows]

    def get_connection(self, conn_id: str, *, with_secrets: bool = False) -> Connection | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM connections WHERE id = ?", (conn_id,)
            ).fetchone()
            return self._row_to_connection(row, with_secrets=with_secrets) if row else None

    def user_can_use(self, conn_id: str, username: str | None) -> bool:
        if username is None:
            return True
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM connection_assignments "
                "WHERE connection_id = ? AND LOWER(username) = LOWER(?)",
                (conn_id, username),
            ).fetchone()
        return row is not None

    def connections_owned_by(self, username: str) -> list[Connection]:
        """Connections a power user created and may edit/delete/re-assign."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM connections WHERE LOWER(owner) = LOWER(?) ORDER BY LOWER(name)",
                (username,),
            ).fetchall()
            return [self._row_to_connection(r, with_secrets=False) for r in rows]

    def can_manage_connection(self, conn_id: str, username: str | None) -> bool:
        """True if `username` may edit/delete/re-assign the connection: an admin,
        or the power user / developer who owns it."""
        user = self.get_user(username) if username else None
        if user is None or not user.is_enabled:
            return False
        if user.is_admin:
            return True
        conn = self.get_connection(conn_id)
        return (
            (user.is_power or user.is_developer)
            and conn is not None
            and conn.owner.strip().lower() == user.username.lower()
        )

    def upsert_connection(self, data: dict) -> Connection:
        """Create or update a connection. `data` uses the admin_public field names.
        Secrets are only written when present: pass ``password`` / ``llmKey`` to set
        them, omit to keep the stored value, or pass an empty string to clear."""
        conn_id = data.get("id") or str(uuid.uuid4())
        with self._lock:
            existing = self._conn.execute(
                "SELECT password_enc, llm_key_enc FROM connections WHERE id = ?",
                (conn_id,),
            ).fetchone()

            if "password" in data:
                pw = data["password"] or ""
                password_enc = encrypt_text(pw) if pw else ""
            else:
                password_enc = existing["password_enc"] if existing else ""

            if "llmKey" in data:
                key = data["llmKey"] or ""
                llm_key_enc = encrypt_text(key) if key else ""
            else:
                llm_key_enc = existing["llm_key_enc"] if existing else ""

            self._conn.execute(
                """
                INSERT INTO connections
                    (id, name, comment, host, port, username, db_schema, use_tls,
                     cert_mode, fingerprint, min_rsa_bits, password_enc,
                     llm_url, llm_model, llm_key_enc, owner,
                     use_materialized_transitions, use_indb_sampling, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name, comment=excluded.comment, host=excluded.host,
                    port=excluded.port, username=excluded.username, db_schema=excluded.db_schema,
                    use_tls=excluded.use_tls, cert_mode=excluded.cert_mode,
                    fingerprint=excluded.fingerprint, min_rsa_bits=excluded.min_rsa_bits,
                    password_enc=excluded.password_enc, llm_url=excluded.llm_url,
                    llm_model=excluded.llm_model, llm_key_enc=excluded.llm_key_enc,
                    use_materialized_transitions=excluded.use_materialized_transitions,
                    use_indb_sampling=excluded.use_indb_sampling
                """,
                (
                    conn_id,
                    (data.get("name") or "").strip() or "Connection",
                    data.get("comment") or "",
                    data.get("host") or "",
                    int(data.get("port") or 8563),
                    data.get("username") or "",
                    data.get("schema") or "",
                    int(bool(data.get("useTLS"))),
                    _valid_cert_mode(data.get("certModeRaw")),
                    data.get("fingerprint") or "",
                    int(data.get("minRSAKeySizeBits") or 2048),
                    password_enc,
                    data.get("llmURL") or "",
                    data.get("llmModel") or "",
                    llm_key_enc,
                    (data.get("owner") or "").strip(),  # only applied on INSERT (immutable after)
                    int(bool(data.get("useMaterializedTransitions"))),
                    int(bool(data.get("useInDbSampling"))),
                    _now(),
                ),
            )
            if "assignments" in data:
                self._conn.execute(
                    "DELETE FROM connection_assignments WHERE connection_id = ?", (conn_id,)
                )
                for user in dict.fromkeys(data["assignments"] or []):
                    if self.get_user(user) is not None:
                        self._conn.execute(
                            "INSERT OR IGNORE INTO connection_assignments (connection_id, username) "
                            "VALUES (?, ?)",
                            (conn_id, user),
                        )
            self._conn.commit()
        return self.get_connection(conn_id)  # type: ignore[return-value]

    def set_assignments(self, conn_id: str, usernames: list[str]) -> None:
        if self.get_connection(conn_id) is None:
            raise ValueError("No such connection.")
        with self._lock:
            self._conn.execute(
                "DELETE FROM connection_assignments WHERE connection_id = ?", (conn_id,)
            )
            for user in dict.fromkeys(usernames):
                if self.get_user(user) is not None:
                    self._conn.execute(
                        "INSERT OR IGNORE INTO connection_assignments (connection_id, username) "
                        "VALUES (?, ?)",
                        (conn_id, user),
                    )
            self._conn.commit()

    def delete_connection(self, conn_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "DELETE FROM connection_assignments WHERE connection_id = ?", (conn_id,)
            )
            self._conn.execute("DELETE FROM connections WHERE id = ?", (conn_id,))
            # Drop the connection's rebuild token + materialisation status too.
            self._conn.execute(
                "DELETE FROM security_config WHERE key = ? OR key = ?",
                (self._rebuild_token_key(conn_id), f"matview:{conn_id}"),
            )
            self._conn.commit()

    # ── integration source types (per-user extraction definitions) ────────────

    @staticmethod
    def _row_to_source_type(row: sqlite3.Row) -> SourceType:
        return SourceType(
            id=row["id"], owner=row["owner"], name=row["name"],
            config=row["config"], created_at=row["created_at"],
        )

    def list_source_types(self, owner: str | None) -> list[SourceType]:
        """The source types owned by `owner` (case-insensitive), newest first."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM source_types WHERE LOWER(owner) = LOWER(?) "
                "ORDER BY created_at DESC, LOWER(name)",
                (owner or "",),
            ).fetchall()
            return [self._row_to_source_type(r) for r in rows]

    def add_source_type(self, owner: str, *, name: str, config: str = "") -> SourceType:
        source_type = SourceType(
            id=uuid.uuid4().hex, owner=owner or "", name=name.strip() or "(unnamed)",
            config=config, created_at=_now(),
        )
        with self._lock:
            self._conn.execute(
                "INSERT INTO source_types (id, owner, name, config, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (source_type.id, source_type.owner, source_type.name,
                 source_type.config, source_type.created_at),
            )
            self._conn.commit()
        return source_type

    def delete_source_type(self, source_type_id: str, owner: str | None) -> bool:
        """Delete a source type, but only if it belongs to `owner`. Returns True if a
        row was removed."""
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM source_types WHERE id = ? AND LOWER(owner) = LOWER(?)",
                (source_type_id, owner or ""),
            )
            self._conn.commit()
            return cur.rowcount > 0

    def update_source_type(
        self, source_type_id: str, owner: str | None, *, name: str, config: str = ""
    ) -> SourceType | None:
        """Update an owner's source type (name / extraction spec). Returns the updated
        source type, or None if it doesn't exist / isn't owned by `owner`."""
        with self._lock:
            cur = self._conn.execute(
                "UPDATE source_types SET name = ?, config = ? "
                "WHERE id = ? AND LOWER(owner) = LOWER(?)",
                (name.strip() or "(unnamed)", config, source_type_id, owner or ""),
            )
            self._conn.commit()
            if cur.rowcount == 0:
                return None
            row = self._conn.execute(
                "SELECT * FROM source_types WHERE id = ?", (source_type_id,)
            ).fetchone()
            return self._row_to_source_type(row) if row else None

    # ── integration data sources (per-user, generic kind + config) ────────────

    @staticmethod
    def _row_to_source(row: sqlite3.Row) -> Source:
        return Source(
            id=row["id"], owner=row["owner"], name=row["name"], kind=row["kind"],
            config=row["config"], created_at=row["created_at"],
        )

    def list_sources(self, owner: str | None) -> list[Source]:
        """The data sources owned by `owner` (case-insensitive), newest first."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM sources WHERE LOWER(owner) = LOWER(?) "
                "ORDER BY created_at DESC, LOWER(name)",
                (owner or "",),
            ).fetchall()
            return [self._row_to_source(r) for r in rows]

    def add_source(self, owner: str, *, name: str, kind: str, config: str = "") -> Source:
        source = Source(
            id=uuid.uuid4().hex, owner=owner or "", name=name.strip() or "(unnamed)",
            kind=kind.strip() or "file", config=config, created_at=_now(),
        )
        with self._lock:
            self._conn.execute(
                "INSERT INTO sources (id, owner, name, kind, config, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (source.id, source.owner, source.name, source.kind, source.config,
                 source.created_at),
            )
            self._conn.commit()
        return source

    def delete_source(self, source_id: str, owner: str | None) -> bool:
        """Delete a source, but only if it belongs to `owner`. Returns True if removed."""
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM sources WHERE id = ? AND LOWER(owner) = LOWER(?)",
                (source_id, owner or ""),
            )
            if cur.rowcount > 0:
                self._conn.execute(
                    "DELETE FROM source_checkpoints WHERE source_id = ?", (source_id,)
                )
            self._conn.commit()
            return cur.rowcount > 0

    def update_source(
        self, source_id: str, owner: str | None, *, name: str, kind: str, config: str = ""
    ) -> Source | None:
        """Update an owner's source (name / kind / settings). Returns the updated source,
        or None if it doesn't exist / isn't owned by `owner`."""
        with self._lock:
            cur = self._conn.execute(
                "UPDATE sources SET name = ?, kind = ?, config = ? "
                "WHERE id = ? AND LOWER(owner) = LOWER(?)",
                (name.strip() or "(unnamed)", kind.strip() or "file", config,
                 source_id, owner or ""),
            )
            self._conn.commit()
            if cur.rowcount == 0:
                return None
            row = self._conn.execute(
                "SELECT * FROM sources WHERE id = ?", (source_id,)
            ).fetchone()
            return self._row_to_source(row) if row else None

    def list_all_sources(self) -> list[Source]:
        """Every source across all owners — used by the background watchdog."""
        with self._lock:
            rows = self._conn.execute("SELECT * FROM sources").fetchall()
            return [self._row_to_source(r) for r in rows]

    def list_all_sinks(self) -> list[Source]:
        """Every API Server - Event Receiver across all owners — the sink supervisor binds one
        ingestion server per row (see app.sink_launcher)."""
        return [s for s in self.list_all_sources() if s.kind == SINK_SOURCE_KIND]

    # ── watchdog read checkpoints (per source file) ───────────────────────────

    def get_source_checkpoint(self, source_id: str) -> dict | None:
        """The watchdog's read checkpoint for a source, or None if it has never run."""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM source_checkpoints WHERE source_id = ?", (source_id,)
            ).fetchone()
        if row is None:
            return None
        return {
            "byteOffset": row["byte_offset"],
            "size": row["size"],
            "signature": row["signature"],
            "records": row["records"],
            "updatedAt": row["updated_at"],
            "lastError": row["last_error"] or None,
        }

    def set_source_checkpoint(
        self,
        source_id: str,
        *,
        byte_offset: int,
        size: int,
        signature: str,
        records: int,
        last_error: str = "",
    ) -> None:
        """Persist the watchdog's read position for a source (upsert)."""
        with self._lock:
            self._conn.execute(
                "INSERT INTO source_checkpoints "
                "(source_id, byte_offset, size, signature, records, updated_at, last_error) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(source_id) DO UPDATE SET "
                "byte_offset = excluded.byte_offset, size = excluded.size, "
                "signature = excluded.signature, records = excluded.records, "
                "updated_at = excluded.updated_at, last_error = excluded.last_error",
                (source_id, int(byte_offset), int(size), signature, int(records),
                 _now(), last_error or ""),
            )
            self._conn.commit()

    def delete_source_checkpoint(self, source_id: str) -> None:
        """Forget a source's read position (a fresh import re-reads from the start)."""
        with self._lock:
            self._conn.execute(
                "DELETE FROM source_checkpoints WHERE source_id = ?", (source_id,)
            )
            self._conn.commit()

    # ── effective TLS plan (read by the GUI launcher) ─────────────────────────

    def tls_plan(self) -> dict:
        """Describe how the GUI server should bind, given the current config."""
        mode = self.tls_mode
        self._materialise_active_cert()  # keep disk in sync on read
        has_cert = ACTIVE_CERT_PATH.exists() and ACTIVE_KEY_PATH.exists()
        return {
            "mode": mode,
            "hasActiveCert": has_cert,
            "http": mode in (TLS_OFF, TLS_OPTIONAL) or not has_cert,
            "https": mode in (TLS_OPTIONAL, TLS_REQUIRED) and has_cert,
            "certPath": str(ACTIVE_CERT_PATH) if has_cert else None,
            "keyPath": str(ACTIVE_KEY_PATH) if has_cert else None,
        }


store = SecurityStore()
