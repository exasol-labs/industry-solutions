"""Administrative interface — runs on its own port (default 8090).

Owns TLS/certificate management for the main app and the user allow-list. Guarded
by an admin session cookie; seeded with Administrator / Administrator on first run.
"""

from __future__ import annotations

import asyncio
import base64
import datetime
import json
import logging
import os
import signal
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # local `pages` module
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from fastapi import Depends, FastAPI, Form, HTTPException, Request, Response  # noqa: E402
from fastapi.responses import (  # noqa: E402
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
)
from pydantic import BaseModel, Field  # noqa: E402

import pages  # noqa: E402
from app.config import (  # noqa: E402
    ADMIN_PID_PATH,
    ADMIN_SESSION_TTL_SECS,
    SESSION_MAX_LIFETIME_SECS,
    BACKUPS_DIR,
    DEFAULT_ADMIN_USERNAME,
    FRONTEND_HTTPS_PORT,
    FRONTEND_PORT,
    GUI_PID_PATH,
    INTEGRATION_HTTPS_PORT,
    INTEGRATION_PID_PATH,
    INTEGRATION_PORT,
    ACTIONS_HTTPS_PORT,
    ACTIONS_PID_PATH,
    ACTIONS_PORT,
    SINK_PID_PATH,
    SINK_POOL_SIZE,
    MCP_HTTPS_PORT,
    MCP_PID_PATH,
    MCP_PORT,
)
from app import licensing  # noqa: E402
from app import log_events as logx  # noqa: E402
from app import timeutil  # noqa: E402
from app.db.manager import db as legacy_db  # noqa: E402 — settings-backed backup state
from app.services import backup as backup_service, cron, mfa, passkey  # noqa: E402
from app.services.login_throttle import LoginThrottle  # noqa: E402
from app.services.certs import CertError  # noqa: E402
from app.store.logs import LEVELS, set_display_timezone, store as log_store  # noqa: E402
from app.store.crypto import read_session, sign_session  # noqa: E402
from app.store.security import User, store  # noqa: E402
from app.web_security import install_security_headers  # noqa: E402

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s"
)

# ── Scheduled backups ─────────────────────────────────────────────────────────
# An in-process scheduler writes encrypted backups on a cron schedule while the
# admin server is running. It lives here (not the compute backend) because backups
# are an admin capability and this process runs continuously. Config + the (Fernet-
# encrypted) password live in the security store; files land in BACKUPS_DIR.

_scheduler_log = logging.getLogger("backup-scheduler")


def _display_zone():
    """The admin's configured display timezone (or None = server-local)."""
    return timeutil.resolve_zone(store.display_timezone)


def _apply_display_timezone() -> None:
    """Push the configured display timezone into the log store so the viewer and the
    exported .log render in it. Called at startup and whenever the setting changes."""
    set_display_timezone(_display_zone())


def _prune_backups(keep: int) -> None:
    """Keep only the newest `keep` scheduled-backup files (timestamped names sort
    chronologically), so the backups directory can't grow without bound."""
    files = sorted(BACKUPS_DIR.glob("pmw-backup-*.json"))
    for stale in (files[:-keep] if keep > 0 else files):
        try:
            stale.unlink()
        except OSError:
            pass  # best effort


def _write_scheduled_backup(trigger: str, password: str | None = None) -> dict:
    """Create one encrypted backup file from the current schedule config. Records
    and returns a status dict. Raises on an unexpected failure (after recording it).
    `password` overrides the stored password when given (e.g. a manual run with a
    just-typed, not-yet-saved password); None uses the stored one."""
    sched = store.backup_schedule()
    if password is None:
        password = store.backup_schedule_password()
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    now = now_utc.astimezone(_display_zone())  # display-tz wall clock (or server-local)
    stamp = now_utc.isoformat(timespec="seconds")  # UTC-aware; the UI renders it in-zone
    if not password:
        status = {"at": stamp, "ok": False, "trigger": trigger,
                  "error": "No backup password is set."}
        store.set_backup_schedule_status(status)
        return status
    try:
        payload = backup_service.export_payload(
            legacy_db,
            include_passwords=sched["includePasswords"],
            include_username=sched["includeUsername"],
            include_llm_api_key=sched["includeLlmKey"],
        )
        data = backup_service.encrypt(backup_service.encode(payload), password)
        BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
        # Microseconds keep successive files unique (scheduled runs are ≥1 min apart,
        # but "Run now" can fire several within a second); the timestamp prefix keeps
        # the names sorting chronologically for retention pruning.
        name = f"pmw-backup-{now.strftime('%Y%m%d-%H%M%S')}-{now.microsecond:06d}.json"
        (BACKUPS_DIR / name).write_bytes(data)
        _prune_backups(sched["retention"])
    except Exception as exc:  # noqa: BLE001
        status = {"at": stamp, "ok": False, "trigger": trigger, "error": str(exc)}
        store.set_backup_schedule_status(status)
        logx.error(f"scheduled backup failed ({trigger}): {exc}", operation="backup", tag=logx.TAG_BACKUP)
        raise
    status = {"at": stamp, "ok": True, "trigger": trigger, "file": name, "bytes": len(data)}
    store.set_backup_schedule_status(status)
    logx.usage(f"automatic backup written: {name} ({trigger})", operation="backup", tag=logx.TAG_BACKUP)
    return status


async def _backup_scheduler() -> None:
    """Once per minute, fire a backup if the configured cron matches and automatic
    backups are enabled with a password. Ticks every 15 s but acts at most once per
    minute (deduped on the minute-truncated clock)."""
    last_minute = None
    while True:
        try:
            # Match the cron against the configured display zone's wall clock, so
            # "daily at 02:00" means 02:00 in the admin's timezone. A tuple key
            # dedupes per minute without comparing aware/naive datetimes.
            now = datetime.datetime.now(_display_zone()).replace(second=0, microsecond=0)
            key = (now.year, now.month, now.day, now.hour, now.minute)
            if key != last_minute:
                last_minute = key
                sched = store.backup_schedule()
                if (sched["enabled"] and sched["hasPassword"]
                        and cron.matches(sched["cron"], now)):
                    await asyncio.to_thread(_write_scheduled_backup, "schedule")
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — a bad tick must never kill the loop
            _scheduler_log.exception("backup scheduler tick failed")
        await asyncio.sleep(15)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    _apply_display_timezone()  # render logs in the configured zone from startup
    # Re-created cleanly on every TLS restart (the launcher re-runs the lifespan).
    task = asyncio.create_task(_backup_scheduler())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title="Process Mining - Administration",
    version="1.0.0",
    lifespan=_lifespan,
)
install_security_headers(app)
_apply_display_timezone()  # apply at import too (log rendering works before serving)

COOKIE = "pmw_admin"

logx.install_request_logging(app, lambda r: _current_user(r))


# ── session helpers ───────────────────────────────────────────────────────────


_SESSION_AUDIENCE = "admin"  # this cookie is only valid for the admin interface


def _issue_session(username: str, issued_at: int | None = None) -> str:
    # Embed the user's session epoch so logout (which bumps it) invalidates this
    # token — otherwise the stateless Fernet token would stay valid until its TTL.
    # The audience ("a") binds the token to THIS interface: admin and app tokens
    # are signed with the same Fernet key, so without it an app session cookie
    # would be structurally valid here (and vice-versa). "iat" is the ORIGINAL
    # sign-in time, carried through every re-issue, so the sliding idle window
    # cannot keep one session (or a captured cookie) alive forever.
    payload = {
        "u": username,
        "e": store.session_epoch(username),
        "a": _SESSION_AUDIENCE,
        "iat": int(issued_at if issued_at is not None else time.time()),
    }
    return sign_session(json.dumps(payload).encode("utf-8"))


def _session_issued_at(request: Request) -> int | None:
    """The original sign-in time from the current cookie, so a refresh preserves it."""
    token = request.cookies.get(COOKIE)
    if not token:
        return None
    raw = read_session(token, _admin_session_ttl())
    if raw is None:
        return None
    try:
        value = json.loads(raw).get("iat")
        return int(value) if value is not None else None
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


def _admin_session_ttl() -> int:
    """Cookie lifetime = the admin idle timeout when set (a sliding window,
    re-issued on activity), else the absolute 8h fallback."""
    mins = store.admin_idle_timeout_mins
    return mins * 60 if mins > 0 else ADMIN_SESSION_TTL_SECS


def _current_user(request: Request) -> User | None:
    token = request.cookies.get(COOKIE)
    if not token:
        return None
    raw = read_session(token, _admin_session_ttl())
    if raw is None:
        return None
    try:
        data = json.loads(raw)
        username = data["u"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return None
    if data.get("a") != _SESSION_AUDIENCE:
        return None  # an app session cookie is not accepted here
    # Absolute lifetime cap — see _issue_session. Tokens minted before this existed
    # carry no "iat" and are refused (one re-login).
    issued_at = data.get("iat")
    if not isinstance(issued_at, int):
        return None
    if time.time() - issued_at > SESSION_MAX_LIFETIME_SECS:
        return None
    user = store.get_user(username)
    if not (user and user.is_admin and user.is_enabled):
        return None
    # Reject tokens issued before the user's last logout (stale epoch).
    if data.get("e") != user.session_epoch:
        return None
    return user


def require_admin(request: Request) -> User:
    user = _current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def _set_cookie(
    response: Response, request: Request, username: str, *, keep_issued_at: bool = False
) -> None:
    # A refresh (keep_issued_at) carries the original "iat" forward so the absolute
    # lifetime keeps counting from the real sign-in; a fresh sign-in starts a new one.
    issued_at = _session_issued_at(request) if keep_issued_at else None
    response.set_cookie(
        COOKIE,
        _issue_session(username, issued_at),
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        max_age=_admin_session_ttl(),
        path="/",
    )


# ── Passkey (WebAuthn) sign-in — an alternative to the password ───────────────


def _pk_rp_and_origins(request: Request):
    host = request.url.hostname or "localhost"
    origin = request.headers.get("origin") or f"{request.url.scheme}://{request.url.netloc}"
    return passkey.resolve_rp(host, origin)


def _set_pk_challenge(response: Response, request: Request, token: str) -> None:
    response.set_cookie(
        passkey.CHALLENGE_COOKIE, token, httponly=True, samesite="lax",
        secure=request.url.scheme == "https",
        max_age=passkey.CHALLENGE_TTL_SECS, path="/",
    )


class PasskeyLoginBody(BaseModel):
    username: str = ""


@app.post("/login/passkey/begin")
def passkey_login_begin(body: PasskeyLoginBody, request: Request):
    username = (body.username or "").strip()
    # Same two lookups for any username, so timing can't distinguish existing from
    # nonexistent accounts (see the app begin endpoint).
    user = store.get_user(username) if username else None
    ids = store.credential_ids_for(username) if username else []
    eligible = (user is not None and user.is_admin and user.is_enabled
                and user.passkey_allowed and bool(ids))
    # Enumeration-resistant: the response is identical whether or not the account
    # exists, is an admin, or has a passkey. Eligible → real credential ids; else a
    # stable decoy that can never verify. No 403/200 oracle for username probing.
    allow_ids = ids if eligible else passkey.decoy_allow_ids(username)
    cookie_username = user.username if eligible else username
    rp_id, _ = _pk_rp_and_origins(request)
    options_json, challenge = passkey.authentication_options(rp_id=rp_id, allow_ids=allow_ids)
    response = Response(content=options_json, media_type="application/json")
    _set_pk_challenge(
        response, request,
        passkey.make_challenge_cookie(challenge=challenge, username=cookie_username, kind="auth", aud="admin"),
    )
    return response


@app.post("/login/passkey/finish")
async def passkey_login_finish(request: Request):
    ip = _client_ip(request)
    retry = _login_retry_after(ip)
    if retry > 0:
        raise HTTPException(status_code=429, detail="Too many attempts. Try again shortly.")
    try:
        data = await request.json()
    except json.JSONDecodeError:
        data = {}
    ch = passkey.read_challenge_cookie(
        request.cookies.get(passkey.CHALLENGE_COOKIE) or "", kind="auth", aud="admin"
    )
    credential = data.get("credential")
    cred_id = credential.get("id") if isinstance(credential, dict) else None
    row = store.get_credential(cred_id) if cred_id else None
    user = store.get_user(row["username"]) if row else None
    rp_id, origins = _pk_rp_and_origins(request)
    ok = False
    if (ch is not None and row is not None and user is not None and user.is_admin
            and user.is_enabled and user.passkey_allowed
            and (row["username"] or "").lower() == (ch["username"] or "").lower()):
        try:
            new_count = passkey.verify_authentication(
                credential=credential, challenge=ch["challenge"], rp_id=rp_id,
                origins=origins, public_key=row["public_key"], sign_count=row["sign_count"],
            )
            store.set_credential_sign_count(cred_id, new_count)
            ok = True
        except Exception as exc:  # noqa: BLE001
            logx.warn(f"admin passkey verification failed: {exc}", request=request, operation="login")
    if not ok:
        _record_login_failure_ip(ip)
        r = JSONResponse({"detail": "Passkey sign-in failed."}, status_code=401)
        r.delete_cookie(passkey.CHALLENGE_COOKIE, path="/")
        return r
    _login_ip_failures.pop(ip, None)
    logx.usage(f"admin {user.username} signed in with a passkey", request=request,
               username=user.username, operation="login")
    response = JSONResponse({"ok": True})
    response.delete_cookie(passkey.CHALLENGE_COOKIE, path="/")
    _set_cookie(response, request, user.username)
    return response


@app.post("/api/passkey/register/begin")
def passkey_register_begin(request: Request, user: User = Depends(require_admin)):
    if not user.passkey_allowed:
        raise HTTPException(status_code=403, detail="Passkeys are not enabled for your account.")
    rp_id, _ = _pk_rp_and_origins(request)
    options_json, challenge = passkey.registration_options(
        rp_id=rp_id, username=user.username, display_name=user.display_name or user.username,
        existing_ids=store.credential_ids_for(user.username),
    )
    response = Response(content=options_json, media_type="application/json")
    _set_pk_challenge(
        response, request,
        passkey.make_challenge_cookie(challenge=challenge, username=user.username, kind="reg", aud="admin"),
    )
    return response


@app.post("/api/passkey/register/finish")
async def passkey_register_finish(request: Request, user: User = Depends(require_admin)):
    if not user.passkey_allowed:
        raise HTTPException(status_code=403, detail="Passkeys are not enabled for your account.")
    try:
        data = await request.json()
    except json.JSONDecodeError:
        data = {}
    ch = passkey.read_challenge_cookie(
        request.cookies.get(passkey.CHALLENGE_COOKIE) or "", kind="reg", aud="admin"
    )
    if ch is None or (ch["username"] or "").lower() != user.username.lower():
        raise HTTPException(status_code=400, detail="Passkey challenge expired. Try again.")
    rp_id, origins = _pk_rp_and_origins(request)
    try:
        cred = passkey.verify_registration(
            credential=data.get("credential"), challenge=ch["challenge"], rp_id=rp_id, origins=origins,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Could not register passkey: {exc}") from exc
    store.add_credential(
        user.username, credential_id=cred["credential_id"], public_key=cred["public_key"],
        sign_count=cred["sign_count"], transports=str(data.get("transports") or ""),
        name=str(data.get("name") or "").strip()[:60],
    )
    logx.usage(f"admin {user.username} registered a passkey", request=request,
               username=user.username, operation="login")
    r = JSONResponse({"ok": True})
    r.delete_cookie(passkey.CHALLENGE_COOKIE, path="/")
    return r


@app.get("/api/passkey/credentials")
def passkey_list_credentials(user: User = Depends(require_admin)):
    return {"passkeyAllowed": user.passkey_allowed, "credentials": store.list_credentials(user.username)}


@app.delete("/api/passkey/credentials/{cred_id}")
def passkey_delete_credential(cred_id: str, user: User = Depends(require_admin)):
    store.delete_credential(cred_id, user.username)
    return {"ok": True}


# ── Two-factor (TOTP) — the admin's own enrolment ────────────────────────────


def _set_mfa_setup(response: Response, request: Request, token: str) -> None:
    response.set_cookie(
        mfa.SETUP_COOKIE, token, httponly=True, samesite="lax",
        secure=request.url.scheme == "https", max_age=mfa.SETUP_TTL_SECS, path="/",
    )


@app.get("/api/mfa/status")
def mfa_status(user: User = Depends(require_admin)):
    return {
        "mfaAllowed": user.mfa_allowed,
        "enabled": user.mfa_enabled,
        "recoveryRemaining": store.recovery_codes_remaining(user.username),
    }


@app.post("/api/mfa/setup/begin")
def mfa_setup_begin(request: Request, user: User = Depends(require_admin)):
    if not user.mfa_allowed:
        raise HTTPException(status_code=403, detail="Two-factor is not enabled for your account.")
    secret = mfa.new_secret()
    uri = mfa.provisioning_uri(secret=secret, username=user.username)
    response = JSONResponse({"secret": secret, "otpauthUri": uri, "qrSvg": mfa.qr_svg(uri)})
    _set_mfa_setup(response, request, mfa.make_setup_cookie(
        username=user.username, secret=secret, aud="admin"))
    return response


@app.post("/api/mfa/setup/finish")
async def mfa_setup_finish(request: Request, user: User = Depends(require_admin)):
    if not user.mfa_allowed:
        raise HTTPException(status_code=403, detail="Two-factor is not enabled for your account.")
    try:
        data = await request.json()
    except json.JSONDecodeError:
        data = {}
    secret = mfa.read_setup_cookie(
        request.cookies.get(mfa.SETUP_COOKIE) or "", username=user.username, aud="admin")
    if secret is None:
        raise HTTPException(status_code=400, detail="Setup expired. Start again.")
    if not mfa.verify_code(secret, str(data.get("code") or "")):
        raise HTTPException(status_code=400, detail="That code didn't match. Try again.")
    store.set_totp_secret(user.username, secret)
    codes = mfa.generate_recovery_codes()
    store.set_recovery_codes(user.username, codes)
    logx.usage(f"admin {user.username} enabled two-factor authentication", request=request,
               username=user.username, operation="login")
    r = JSONResponse({"recoveryCodes": codes})
    r.delete_cookie(mfa.SETUP_COOKIE, path="/")
    return r


@app.post("/api/mfa/recovery/regenerate")
def mfa_recovery_regenerate(user: User = Depends(require_admin)):
    if not user.mfa_enabled:
        raise HTTPException(status_code=400, detail="Two-factor isn't set up.")
    codes = mfa.generate_recovery_codes()
    store.set_recovery_codes(user.username, codes)
    logx.usage(f"admin {user.username} regenerated 2FA recovery codes", operation="login",
               username=user.username)
    return {"recoveryCodes": codes}


class MfaDisableBody(BaseModel):
    code: str = ""


@app.post("/api/mfa/disable")
def mfa_disable(request: Request, body: MfaDisableBody, user: User = Depends(require_admin)):
    # Re-authenticate the downgrade: turning off the second factor requires the
    # current code (or a recovery code), so a hijacked session alone can't strip it.
    # Throttled per-IP so that re-auth can't itself be brute-forced from a session.
    ip = _client_ip(request)
    if _login_retry_after(ip) > 0:
        raise HTTPException(status_code=429, detail="Too many attempts. Try again shortly.")
    secret = store.get_totp_secret(user.username)
    if secret is None:
        raise HTTPException(status_code=400, detail="Two-factor isn't set up.")
    if not (mfa.verify_code(secret, body.code)
            or store.consume_recovery_code(user.username, body.code)):
        _record_login_failure_ip(ip)
        raise HTTPException(
            status_code=401,
            detail="Enter your current authentication code to turn off two-factor.")
    _login_throttle.clear(ip)
    store.clear_mfa(user.username)
    logx.usage(f"admin {user.username} disabled two-factor authentication", operation="login",
               username=user.username)
    return {"ok": True}


# ── pages ─────────────────────────────────────────────────────────────────────


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    user = _current_user(request)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    logx.usage(
        "admin dashboard opened",
        request=request,
        username=user.username,
        operation="page",
    )
    return HTMLResponse(
        pages.dashboard_page(user.username, FRONTEND_PORT, FRONTEND_HTTPS_PORT)
    )


def _login_bg_css() -> str:
    """CSS `background` value for the admin sign-in page from the Customize tab,
    or "" to keep the theme default. Stored values are already validated by the
    security store; the guards here are defence-in-depth before CSS injection."""
    appearance = store.login_appearance()
    kind = appearance.get("type")
    if kind == "color":
        color = appearance.get("color", "")
        if (
            color.startswith("#")
            and len(color) == 7
            and all(c in "0123456789abcdefABCDEF" for c in color[1:])
        ):
            return color
    elif kind == "image":
        image = appearance.get("image", "")
        if image.startswith("data:image/") and '"' not in image:
            return f'var(--l-grouped) url("{image}") center / cover no-repeat'
    return ""


@app.get("/login", response_class=HTMLResponse)
def login_get(request: Request, inactivity: bool = False):
    if _current_user(request) is not None:
        return RedirectResponse("/", status_code=303)
    return HTMLResponse(pages.login_page(inactivity=inactivity, bg_css=_login_bg_css()))


# Brief cache so the login screen doesn't re-probe the directory on every load.
_DIR_STATUS_TTL = 20.0
_dir_status: dict = {"at": 0.0, "value": None}


@app.get("/api/directory-status")
async def api_directory_status() -> Response:
    """Whether a directory (LDAP) server is configured and currently reachable.

    Unauthenticated, for the login screen's availability LED — mirrors the main app's
    ``/auth/directory-status``. Reports ``configured: false`` when no directory is set
    up (the client then shows nothing); reachability is the cached service-bind probe,
    run off the event loop so a slow server never blocks the page.
    """
    if not store.ldap_enabled or not store.ldap_show_status_on_login:
        return JSONResponse({"configured": False, "available": False})

    now = time.monotonic()
    cached = _dir_status["value"]
    if cached is not None and now - _dir_status["at"] < _DIR_STATUS_TTL:
        return JSONResponse(cached)

    from app.services.ldap_auth import test_settings

    settings = store.ldap_settings()
    try:
        result = await asyncio.to_thread(test_settings, settings)
        available = bool(result.get("ok"))
    except Exception:  # a probe must never break the login screen
        available = False
    value = {"configured": True, "available": available}
    _dir_status.update(at=now, value=value)
    return JSONResponse(value)


# ── Per-IP admin-login throttle ─────────────────────────────────────────────
# Shared implementation (app + admin) in app.services.login_throttle. The thin
# module-level aliases below preserve this file's long-standing internal API.
_login_throttle = LoginThrottle()
_login_ip_failures = _login_throttle.fails  # same dict object (used by tests)
_LOGIN_IP_MAX = _login_throttle.max_fails
_LOGIN_IP_MAX_TRACKED = _login_throttle.max_tracked
_client_ip = LoginThrottle.client_ip
_login_retry_after = _login_throttle.retry_after
_record_login_failure_ip = _login_throttle.record_failure


@app.post("/login", response_class=HTMLResponse)
def login_post(request: Request, username: str = Form(...), password: str = Form(...)):
    ip = _client_ip(request)
    retry_after = _login_retry_after(ip)
    if retry_after > 0:
        wait = int(retry_after) + 1
        logx.warn(
            f"admin sign-in throttled for {ip} ({wait}s remaining)",
            request=request,
            username=username,
            operation="login",
        )
        return HTMLResponse(
            pages.login_page(
                f"Too many failed attempts. Try again in about {wait} seconds.",
                bg_css=_login_bg_css(),
            ),
            status_code=429,
            headers={"Retry-After": str(wait)},
        )
    # Local accounts always work (break-glass). Directory accounts may sign in here
    # only when the admin explicitly enabled it in the Directory tab — and, either way,
    # the panel is admins only, so a valid non-admin is refused. A directory user must
    # first be promoted to admin (Users tab) before they can get in.
    if store.ldap_admin_login_enabled:
        user = store.authenticate_app(username, password)  # local first, then directory
    else:
        user = store.authenticate(username, password)  # local-only
    if user is None or not user.is_admin:
        _record_login_failure_ip(ip)
        logx.warn(
            f"failed admin sign-in for username {username!r}",
            request=request,
            username=username,
            operation="login",
        )
        message = store.login_block_message(username, password) or (
            "Invalid credentials, or the account is not an administrator."
        )
        return HTMLResponse(
            pages.login_page(message, bg_css=_login_bg_css()), status_code=401
        )
    # Two-factor: password verified, but a TOTP-enrolled admin must also enter a
    # code. Don't clear the IP throttle or issue the session yet — hold a signed
    # "password ok" cookie and render the code step.
    if store.mfa_active(user.username):
        response = HTMLResponse(pages.login_page(mfa_step=True, bg_css=_login_bg_css()))
        response.set_cookie(
            mfa.PENDING_COOKIE,
            mfa.make_pending_cookie(username=user.username, aud="admin"),
            httponly=True, samesite="lax",
            secure=request.url.scheme == "https",
            max_age=mfa.PENDING_TTL_SECS, path="/",
        )
        return response
    # Two-factor is required for this admin but not yet configured — force enrolment
    # before any session is issued. Generate a secret, render the QR, and hold it in
    # the setup cookie (+ the password-ok pending cookie) for /login/mfa-setup.
    if store.mfa_setup_required(user.username):
        secret = mfa.new_secret()
        uri = mfa.provisioning_uri(secret=secret, username=user.username)
        response = HTMLResponse(pages.login_page(
            mfa_setup=True, mfa_qr=mfa.qr_svg(uri), bg_css=_login_bg_css()))
        secure = request.url.scheme == "https"
        response.set_cookie(
            mfa.PENDING_COOKIE, mfa.make_pending_cookie(username=user.username, aud="admin"),
            httponly=True, samesite="lax", secure=secure, max_age=mfa.PENDING_TTL_SECS, path="/")
        response.set_cookie(
            mfa.SETUP_COOKIE,
            mfa.make_setup_cookie(username=user.username, secret=secret, aud="admin"),
            httponly=True, samesite="lax", secure=secure, max_age=mfa.SETUP_TTL_SECS, path="/")
        return response
    _login_ip_failures.pop(ip, None)  # clear the throttle on a successful sign-in
    logx.usage(
        f"admin {user.username} signed in to the admin interface",
        request=request,
        username=user.username,
        operation="login",
    )
    response = RedirectResponse("/", status_code=303)
    _set_cookie(response, request, user.username)
    return response


@app.post("/login/mfa", response_class=HTMLResponse)
def login_mfa(request: Request, code: str = Form("")):
    """Step 2 of admin sign-in: verify the TOTP (or a recovery code) against the
    pending cookie, then issue the admin session."""
    ip = _client_ip(request)
    if _login_retry_after(ip) > 0:
        return HTMLResponse(
            pages.login_page("Too many failed attempts. Try again shortly.",
                             bg_css=_login_bg_css()),
            status_code=429)
    username = mfa.read_pending_cookie(request.cookies.get(mfa.PENDING_COOKIE) or "", aud="admin")
    user = store.get_user(username) if username else None
    secret = store.get_totp_secret(username) if username else None
    if user is None or not user.is_admin or not user.is_enabled or secret is None:
        r = HTMLResponse(
            pages.login_page("Your sign-in session expired. Please start again.",
                             bg_css=_login_bg_css()),
            status_code=401)
        r.delete_cookie(mfa.PENDING_COOKIE, path="/")
        return r
    ok = mfa.verify_code(secret, code) or store.consume_recovery_code(user.username, code)
    if not ok:
        # A wrong code is throttled per-IP only — NOT counted toward account lockout,
        # so a mistyped/expired code can never disable the account (the password was
        # already proven in step 1).
        _record_login_failure_ip(ip)
        logx.warn(f"failed admin 2FA for {user.username!r}", request=request,
                  username=user.username, operation="login")
        r = HTMLResponse(
            pages.login_page("Incorrect code. Try again.", mfa_step=True,
                             bg_css=_login_bg_css()),
            status_code=401)
        # Keep the pending cookie so the user can retry the code without re-entering
        # their password.
        r.set_cookie(
            mfa.PENDING_COOKIE, mfa.make_pending_cookie(username=user.username, aud="admin"),
            httponly=True, samesite="lax", secure=request.url.scheme == "https",
            max_age=mfa.PENDING_TTL_SECS, path="/",
        )
        return r
    _login_ip_failures.pop(ip, None)
    store.reset_login_failures(user.username)
    logx.usage(f"admin {user.username} signed in to the admin interface with 2FA",
               request=request, username=user.username, operation="login")
    response = RedirectResponse("/", status_code=303)
    response.delete_cookie(mfa.PENDING_COOKIE, path="/")
    _set_cookie(response, request, user.username)
    return response


@app.post("/login/mfa-setup", response_class=HTMLResponse)
def login_mfa_setup(request: Request, code: str = Form("")):
    """Mandatory-enrolment step: confirm a code against the setup cookie's secret,
    store it + recovery codes, then issue the admin session and show the codes once."""
    ip = _client_ip(request)
    secure = request.url.scheme == "https"
    if _login_retry_after(ip) > 0:
        return HTMLResponse(
            pages.login_page("Too many failed attempts. Try again shortly.",
                             bg_css=_login_bg_css()),
            status_code=429)
    username = mfa.read_pending_cookie(request.cookies.get(mfa.PENDING_COOKIE) or "", aud="admin")
    user = store.get_user(username) if username else None
    secret = mfa.read_setup_cookie(
        request.cookies.get(mfa.SETUP_COOKIE) or "", username=username or "", aud="admin")
    if (user is None or not user.is_admin or not user.is_enabled
            or not store.mfa_setup_required(user.username) or secret is None):
        r = HTMLResponse(
            pages.login_page("Your sign-in session expired. Please start again.",
                             bg_css=_login_bg_css()),
            status_code=401)
        r.delete_cookie(mfa.PENDING_COOKIE, path="/")
        r.delete_cookie(mfa.SETUP_COOKIE, path="/")
        return r
    if not mfa.verify_code(secret, code):
        _record_login_failure_ip(ip)
        # Re-render the same QR (secret preserved in the setup cookie); keep cookies.
        uri = mfa.provisioning_uri(secret=secret, username=user.username)
        r = HTMLResponse(
            pages.login_page("That code didn't match. Try again.", mfa_setup=True,
                             mfa_qr=mfa.qr_svg(uri), bg_css=_login_bg_css()),
            status_code=401)
        r.set_cookie(
            mfa.PENDING_COOKIE, mfa.make_pending_cookie(username=user.username, aud="admin"),
            httponly=True, samesite="lax", secure=secure, max_age=mfa.PENDING_TTL_SECS, path="/")
        r.set_cookie(
            mfa.SETUP_COOKIE, mfa.make_setup_cookie(username=user.username, secret=secret, aud="admin"),
            httponly=True, samesite="lax", secure=secure, max_age=mfa.SETUP_TTL_SECS, path="/")
        return r
    # Enrolment confirmed → persist the secret + recovery codes, sign in, show codes once.
    store.set_totp_secret(user.username, secret)
    codes = mfa.generate_recovery_codes()
    store.set_recovery_codes(user.username, codes)
    _login_ip_failures.pop(ip, None)
    store.reset_login_failures(user.username)
    logx.usage(f"admin {user.username} set up two-factor at sign-in and signed in",
               request=request, username=user.username, operation="login")
    response = HTMLResponse(pages.login_page(recovery_codes=codes, bg_css=_login_bg_css()))
    response.delete_cookie(mfa.PENDING_COOKIE, path="/")
    response.delete_cookie(mfa.SETUP_COOKIE, path="/")
    _set_cookie(response, request, user.username)  # session issued; "Continue" → /
    return response


@app.post("/logout")
def logout(request: Request):
    user = _current_user(request)
    logx.usage(
        f"admin {user.username if user else 'unknown'} signed out",
        request=request,
        username=user.username if user else "",
        operation="logout",
    )
    if user is not None:
        # Invalidate this user's outstanding session tokens server-side (not just
        # the cookie) so a captured token can't be replayed after logout.
        store.bump_session_epoch(user.username)
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(COOKIE, path="/")
    return response


# ── API: session / self ───────────────────────────────────────────────────────


class PasswordBody(BaseModel):
    password: str


@app.get("/api/session")
def api_session(request: Request, response: Response, user: User = Depends(require_admin)):
    # Polling this on activity slides the admin idle window (re-issues the cookie).
    _set_cookie(response, request, user.username, keep_issued_at=True)
    return {
        "username": user.username,
        "isAdmin": user.is_admin,
        "defaultPasswordActive": store.default_admin_password_active,
        "requireLogin": store.require_login,
        "idleTimeoutMins": store.idle_timeout_mins,
        "adminIdleTimeoutMins": store.admin_idle_timeout_mins,
        "maxFailedLogins": store.max_failed_logins,
        "displayTimezone": store.display_timezone,
        "builtinAdmin": DEFAULT_ADMIN_USERNAME,
        "license": licensing.evaluate().public(),
    }


class RequireLoginBody(BaseModel):
    requireLogin: bool


@app.post("/api/access/require-login")
def api_require_login(body: RequireLoginBody, user: User = Depends(require_admin)):
    store.set_require_login(body.requireLogin)
    return {"ok": True, "requireLogin": store.require_login}


class IdleTimeoutBody(BaseModel):
    minutes: int


@app.post("/api/access/idle-timeout")
def api_idle_timeout(body: IdleTimeoutBody, user: User = Depends(require_admin)):
    store.set_idle_timeout_mins(body.minutes)
    return {"ok": True, "idleTimeoutMins": store.idle_timeout_mins}


@app.post("/api/access/admin-idle-timeout")
def api_admin_idle_timeout(body: IdleTimeoutBody, user: User = Depends(require_admin)):
    """Idle timeout for the admin interface itself — separate from the app's."""
    store.set_admin_idle_timeout_mins(body.minutes)
    return {"ok": True, "adminIdleTimeoutMins": store.admin_idle_timeout_mins}


class TimezoneBody(BaseModel):
    timezone: str = ""  # IANA name, or "" for the server's local zone


@app.post("/api/access/timezone")
def api_set_timezone(body: TimezoneBody, user: User = Depends(require_admin)):
    tz = (body.timezone or "").strip()
    if not timeutil.is_valid_zone(tz):
        raise HTTPException(status_code=400, detail=f"Unknown timezone: {tz!r}")
    store.set_display_timezone(tz)
    _apply_display_timezone()  # take effect immediately (logs, backups, schedule)
    logx.usage(
        f"admin {user.username} set the display timezone to {tz or 'server-local'}",
        username=user.username, operation="config",
    )
    return {"ok": True, "displayTimezone": store.display_timezone}


class MaxFailedLoginsBody(BaseModel):
    count: int


@app.post("/api/access/max-failed-logins")
def api_max_failed_logins(body: MaxFailedLoginsBody, user: User = Depends(require_admin)):
    store.set_max_failed_logins(body.count)
    logx.usage(
        f"admin {user.username} set the failed-sign-in lockout to "
        f"{store.max_failed_logins or 'off'}",
        username=user.username,
        operation="config",
    )
    return {"ok": True, "maxFailedLogins": store.max_failed_logins}


# ── License ─────────────────────────────────────────────────────────────────────


class LicenseUploadBody(BaseModel):
    content: str  # base64-encoded license.json bytes


# A signed license is a few hundred bytes; this cap just stops an absurd upload.
_MAX_LICENSE_B64 = 100_000


@app.get("/api/license")
def api_license(user: User = Depends(require_admin)):
    return licensing.evaluate().public()


@app.post("/api/license")
def api_license_upload(body: LicenseUploadBody, user: User = Depends(require_admin)):
    if len(body.content) > _MAX_LICENSE_B64:
        raise HTTPException(status_code=413, detail="License file is too large.")
    try:
        raw = base64.b64decode(body.content)
    except ValueError as exc:  # binascii.Error is a ValueError subclass
        raise HTTPException(status_code=400, detail="Invalid file content.") from exc

    status = licensing.install(raw)
    if status.state in ("invalid", "missing"):
        # Forged/corrupt/unparseable — nothing was stored.
        logx.warn(
            f"admin {user.username} uploaded a license that was rejected: {status.message}",
            username=user.username,
            operation="license",
        )
        raise HTTPException(status_code=400, detail=status.message)

    logx.usage(
        f"admin {user.username} installed a license — {status.message}",
        username=user.username,
        operation="license",
    )
    return {"ok": True, "license": status.public()}


@app.delete("/api/license")
def api_license_delete(user: User = Depends(require_admin)):
    removed = licensing.uninstall()
    if removed:
        logx.usage(
            f"admin {user.username} removed the installed license — the backend "
            "drops to Demo Mode",
            username=user.username,
            operation="license",
        )
    return {"ok": True, "removed": removed, "license": licensing.evaluate().public()}


# ── Logging ───────────────────────────────────────────────────────────────────


_LOG_PAGE_SIZES = (10, 25, 50, 100)


@app.get("/api/logs")
def api_logs(
    request: Request,
    level: str = "",
    severities: str = "",
    clientIp: str = "",
    operation: str = "",
    tag: str = "",
    search: str = "",
    page: int = 1,
    perPage: int = 25,
    user: User = Depends(require_admin),
):
    sev_list = [s for s in severities.split(",") if s] if severities else None
    filt = dict(
        level=level or None,
        severities=sev_list,
        client_ip=clientIp,
        operation=operation,
        tag=tag,
        search=search,
    )
    per_page = perPage if perPage in _LOG_PAGE_SIZES else 25
    # The filter (incl. search) spans the whole log; paging only slices the view.
    total = log_store.count(**filt)
    pages = max(1, (total + per_page - 1) // per_page)
    page = min(max(1, page), pages)
    entries = log_store.query(**filt, limit=per_page, offset=(page - 1) * per_page)
    return {
        "entries": entries,
        "total": total,
        "page": page,
        "perPage": per_page,
        "pages": pages,
        "config": log_store.config(),
        "operations": log_store.operations(),
        "tags": log_store.tags(),
        "severities": list(LEVELS),
    }


class LogConfigBody(BaseModel):
    level: str | None = None
    maxBytes: int | None = None


@app.post("/api/logs/config")
def api_logs_config(body: LogConfigBody, user: User = Depends(require_admin)):
    if body.level is not None:
        log_store.set_level(body.level)
    if body.maxBytes is not None:
        log_store.set_max_bytes(body.maxBytes)
    logx.info(
        f"admin {user.username} updated logging config "
        f"(level={log_store.level}, maxBytes={log_store.max_bytes})",
        username=user.username,
        operation="config",
    )
    return {"ok": True, "config": log_store.config()}


@app.post("/api/logs/clear")
def api_logs_clear(user: User = Depends(require_admin)):
    log_store.clear()
    logx.warn(
        f"admin {user.username} cleared the live log",
        username=user.username,
        operation="config",
    )
    return {"ok": True}


@app.get("/api/logs/download")
def api_logs_download(
    level: str = "",
    severities: str = "",
    clientIp: str = "",
    operation: str = "",
    tag: str = "",
    search: str = "",
    user: User = Depends(require_admin),
):
    sev_list = [s for s in severities.split(",") if s] if severities else None
    text = log_store.render(
        level=level or None,
        severities=sev_list,
        client_ip=clientIp,
        operation=operation,
        tag=tag,
        search=search,
        limit=5000,
    )
    return PlainTextResponse(
        text,
        headers={"Content-Disposition": 'attachment; filename="pmw-log.log"'},
    )


# ── Backup / restore (moved here from the app's left panel) ───────────────────


class BackupExportBody(BaseModel):
    includePasswords: bool = False
    includeUsername: bool = True
    includeLlmApiKey: bool = False
    password: str = ""
    # Fall back to the stored automatic-backup password when no password is typed
    # (the unified Backup card shares one password field for downloads + schedule).
    useStoredPassword: bool = False


class BackupInspectBody(BaseModel):
    content: str  # base64-encoded file bytes
    password: str = ""


class BackupRestoreBody(BackupInspectBody):
    options: dict[str, bool] = {}


# A real backup is well under this; the cap stops an oversized upload from being
# base64-decoded / decrypted / JSON-parsed into several full in-memory copies.
_MAX_BACKUP_B64 = 25_000_000  # ~18 MB decoded


def _decode_backup(body: BackupInspectBody) -> dict:
    if len(body.content) > _MAX_BACKUP_B64:
        raise HTTPException(status_code=413, detail="Backup file is too large.")
    try:
        raw = base64.b64decode(body.content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid file content.") from exc
    if backup_service.is_encrypted(raw):
        if not body.password:
            # 400 (a client error), NOT 401 — the admin fetch helper redirects to
            # /login on any 401, which would bounce the page instead of prompting
            # for the encryption password.
            raise HTTPException(
                status_code=400,
                detail="This backup is encrypted — enter its password and Inspect again.",
            )
        try:
            raw = backup_service.decrypt(raw, body.password)
        except backup_service.BackupError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=400, detail="The backup file format is invalid or corrupted."
        ) from exc


def _export_desc(body: BackupExportBody, encrypted: bool) -> str:
    inc = []
    if body.includeUsername:
        inc.append("usernames")
    if body.includePasswords:
        inc.append("passwords")
    if body.includeLlmApiKey:
        inc.append("LLM keys")
    return (
        f"includes: {', '.join(inc) or 'none'}; "
        f"{'encrypted' if encrypted else 'PLAINTEXT'}"
    )


def _restore_opts_desc(options: dict[str, bool]) -> str:
    if not options:
        return "all (default)"
    enabled = [k for k, v in options.items() if v]
    return ", ".join(enabled) if enabled else "none"


@app.post("/api/backup/export")
def api_backup_export(
    body: BackupExportBody, request: Request, user: User = Depends(require_admin)
):
    password = body.password or (
        store.backup_schedule_password() if body.useStoredPassword else ""
    )
    try:
        payload = backup_service.export_payload(
            legacy_db,
            include_passwords=body.includePasswords,
            include_username=body.includeUsername,
            include_llm_api_key=body.includeLlmApiKey,
        )
        data = backup_service.encode(payload)
        if password:
            data = backup_service.encrypt(data, password)
    except Exception as exc:  # noqa: BLE001
        logx.error(
            f"admin {user.username} backup export failed: {exc}",
            request=request, username=user.username, operation="backup", tag=logx.TAG_BACKUP,
        )
        raise
    logx.usage(
        f"admin {user.username} exported a settings backup — {_export_desc(body, bool(password))}",
        request=request, username=user.username, operation="backup", tag=logx.TAG_BACKUP,
    )
    stamp = datetime.datetime.now().strftime("%Y-%m-%d")
    return Response(
        content=data,
        media_type="application/json",
        headers={
            "Content-Disposition": (
                f'attachment; filename="ProcessMining-Backup-{stamp}.json"'
            )
        },
    )


@app.post("/api/backup/inspect")
def api_backup_inspect(
    body: BackupInspectBody, request: Request, user: User = Depends(require_admin)
):
    try:
        payload = _decode_backup(body)
    except HTTPException as exc:
        logx.warn(
            f"admin {user.username} backup inspect failed: {exc.detail}",
            request=request, username=user.username, operation="backup", tag=logx.TAG_BACKUP,
        )
        raise
    logx.usage(
        f"admin {user.username} inspected a backup file",
        request=request, username=user.username, operation="backup", tag=logx.TAG_BACKUP,
    )
    return backup_service.summarize(payload)


@app.post("/api/backup/restore")
def api_backup_restore(
    body: BackupRestoreBody, request: Request, user: User = Depends(require_admin)
):
    try:
        payload = _decode_backup(body)
    except HTTPException as exc:
        logx.warn(
            f"admin {user.username} backup restore failed (decode): {exc.detail}",
            request=request, username=user.username, operation="backup", tag=logx.TAG_BACKUP,
        )
        raise
    try:
        backup_service.restore(legacy_db, payload, body.options)
    except Exception as exc:  # noqa: BLE001
        logx.error(
            f"admin {user.username} backup restore failed: {exc}",
            request=request, username=user.username, operation="backup", tag=logx.TAG_BACKUP,
        )
        raise
    logx.warn(
        f"admin {user.username} restored a settings backup — options: "
        f"{_restore_opts_desc(body.options)}",
        request=request, username=user.username, operation="backup", tag=logx.TAG_BACKUP,
    )
    return {"ok": True}


# ── API: scheduled backups ──────────────────────────────────────────────────


class BackupScheduleBody(BaseModel):
    enabled: bool
    cron: str
    retention: int = 30
    includePasswords: bool = True
    includeUsername: bool = True
    includeLlmKey: bool = True
    # Omit to keep the stored password, "" to clear it, a value to set it.
    password: str | None = None


@app.get("/api/backup/schedule")
def api_backup_schedule_get(user: User = Depends(require_admin)):
    return store.backup_schedule()


@app.post("/api/backup/schedule")
def api_backup_schedule_set(
    body: BackupScheduleBody, request: Request, user: User = Depends(require_admin)
):
    try:
        cron.validate(body.cron)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid schedule: {exc}") from None
    # Enabling requires a password (either provided now or already stored).
    if body.enabled and not (body.password or store.backup_schedule()["hasPassword"]):
        raise HTTPException(
            status_code=400,
            detail="Set a backup password before enabling automatic backups.",
        )
    store.set_backup_schedule(body.model_dump(exclude_none=True))
    logx.usage(
        f"admin {user.username} updated the backup schedule "
        f"(enabled={body.enabled}, cron={body.cron!r})",
        request=request, username=user.username, operation="backup", tag=logx.TAG_BACKUP,
    )
    return store.backup_schedule()


class RunNowBody(BaseModel):
    password: str = ""  # a just-typed password; falls back to the stored one


@app.post("/api/backup/run-now")
async def api_backup_run_now(
    request: Request, body: RunNowBody | None = None, user: User = Depends(require_admin)
):
    password = (body.password.strip() if body and body.password else "") or (
        store.backup_schedule_password()
    )
    if not password:
        raise HTTPException(status_code=400, detail="Set a backup password first.")
    try:
        status = await asyncio.to_thread(_write_scheduled_backup, "manual", password)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Backup failed: {exc}") from exc
    if not status.get("ok"):
        raise HTTPException(status_code=400, detail=status.get("error", "Backup failed."))
    logx.usage(
        f"admin {user.username} ran a manual scheduled backup → {status.get('file')}",
        request=request, username=user.username, operation="backup", tag=logx.TAG_BACKUP,
    )
    return status


@app.post("/api/self/password")
def api_self_password(body: PasswordBody, request: Request, user: User = Depends(require_admin)):
    try:
        store.set_password(user.username, body.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # set_password bumps the session epoch, which invalidates every outstanding token
    # (that is the point — a stolen cookie must die with the old password). Re-issue a
    # cookie for THIS session so the admin who just changed their own password isn't
    # signed out; every other session for them is now dead.
    response = JSONResponse({"ok": True})
    _set_cookie(response, request, user.username, keep_issued_at=True)
    logx.info(
        f"admin {user.username} changed their password — other sessions invalidated",
        request=request, username=user.username, operation="config",
    )
    return response


# ── API: users ────────────────────────────────────────────────────────────────


class NewUserBody(BaseModel):
    username: str
    password: str
    isAdmin: bool = False


class EnabledBody(BaseModel):
    enabled: bool


class AdminBody(BaseModel):
    isAdmin: bool


class PowerBody(BaseModel):
    isPower: bool


@app.get("/api/users")
def api_users(user: User = Depends(require_admin)):
    return [u.public() for u in store.list_users()]


@app.post("/api/users")
def api_create_user(body: NewUserBody, user: User = Depends(require_admin)):
    try:
        return store.create_user(body.username, body.password, body.isAdmin).public()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/users/{username}/enabled")
def api_set_enabled(username: str, body: EnabledBody, user: User = Depends(require_admin)):
    try:
        store.set_enabled(username, body.enabled)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True}


@app.post("/api/users/{username}/admin")
def api_set_admin(username: str, body: AdminBody, user: User = Depends(require_admin)):
    try:
        store.set_admin(username, body.isAdmin)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True}


@app.post("/api/users/{username}/power")
def api_set_power(username: str, body: PowerBody, user: User = Depends(require_admin)):
    try:
        store.set_power(username, body.isPower)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True}


class DeveloperBody(BaseModel):
    isDeveloper: bool


@app.post("/api/users/{username}/developer")
def api_set_developer(username: str, body: DeveloperBody, user: User = Depends(require_admin)):
    try:
        store.set_developer(username, body.isDeveloper)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    logx.usage(
        f"admin {user.username} {'granted' if body.isDeveloper else 'revoked'} "
        f"the Developer role for {username!r}",
        username=user.username, operation="config",
    )
    return {"ok": True}


class PasskeyAllowedBody(BaseModel):
    allowed: bool


@app.post("/api/users/{username}/passkey-allowed")
def api_set_passkey_allowed(
    username: str, body: PasskeyAllowedBody, user: User = Depends(require_admin)
):
    try:
        store.set_passkey_allowed(username, body.allowed)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    logx.usage(
        f"admin {user.username} {'allowed' if body.allowed else 'disallowed'} "
        f"passkeys for {username!r}",
        username=user.username, operation="config",
    )
    return {"ok": True}


@app.post("/api/access/passkey-all")
def api_set_passkey_allowed_all(
    body: PasskeyAllowedBody, user: User = Depends(require_admin)
):
    store.set_passkey_allowed_all(body.allowed)
    logx.usage(
        f"admin {user.username} {'allowed' if body.allowed else 'disallowed'} "
        f"passkeys for all users",
        username=user.username, operation="config",
    )
    return {"ok": True}


class MfaAllowedBody(BaseModel):
    allowed: bool


@app.post("/api/users/{username}/mfa-allowed")
def api_set_mfa_allowed(
    username: str, body: MfaAllowedBody, user: User = Depends(require_admin)
):
    try:
        store.set_mfa_allowed(username, body.allowed)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    logx.usage(
        f"admin {user.username} {'allowed' if body.allowed else 'disallowed'} "
        f"two-factor for {username!r}",
        username=user.username, operation="config",
    )
    return {"ok": True}


@app.post("/api/access/mfa-all")
def api_set_mfa_allowed_all(
    body: MfaAllowedBody, user: User = Depends(require_admin)
):
    store.set_mfa_allowed_all(body.allowed)
    logx.usage(
        f"admin {user.username} {'allowed' if body.allowed else 'disallowed'} "
        f"two-factor for all users",
        username=user.username, operation="config",
    )
    return {"ok": True}


@app.post("/api/users/{username}/password")
def api_set_user_password(
    username: str, body: PasswordBody, user: User = Depends(require_admin)
):
    if store.get_user(username) is None:
        raise HTTPException(status_code=404, detail="No such user.")
    try:
        store.set_password(username, body.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True}


@app.delete("/api/users/{username}")
def api_delete_user(username: str, user: User = Depends(require_admin)):
    try:
        store.delete_user(username)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True}


# ── API: TLS & certificates ───────────────────────────────────────────────────


class TlsModeBody(BaseModel):
    mode: str


class GenerateBody(BaseModel):
    name: str = ""
    commonName: str
    sans: list[str] = []
    days: int = 825
    keySize: int = 2048
    activate: bool = False


# A real PEM cert+key pair is a few KB; cap the fields (like the license/backup
# uploads) so a multi-hundred-MB "PEM" can't be decoded/parsed into memory.
_MAX_PEM_CHARS = 200_000


class UploadBody(BaseModel):
    name: str = ""
    certPem: str = Field(max_length=_MAX_PEM_CHARS)
    keyPem: str = Field(max_length=_MAX_PEM_CHARS)
    activate: bool = False


@app.get("/api/tls")
def api_tls(user: User = Depends(require_admin)):
    return {
        "mode": store.tls_mode,
        "activeCertId": store.active_cert_id,
        "plan": store.tls_plan(),
        "certs": [c.public() for c in store.list_certificates()],
    }


@app.post("/api/tls/mode")
def api_tls_mode(body: TlsModeBody, user: User = Depends(require_admin)):
    try:
        store.set_tls_mode(body.mode)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "plan": store.tls_plan()}


@app.post("/api/certs/generate")
def api_generate_cert(body: GenerateBody, user: User = Depends(require_admin)):
    try:
        cert = store.generate_certificate(
            name=body.name,
            common_name=body.commonName,
            sans=body.sans,
            days=body.days,
            key_size=body.keySize,
        )
    except (CertError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if body.activate:
        store.activate_certificate(cert.id)
    logx.info(
        f"admin {user.username} generated TLS certificate {cert.name!r} "
        f"(CN={body.commonName})" + (" and activated it" if body.activate else ""),
        username=user.username,
        operation="tls",
    )
    return cert.public()


@app.post("/api/certs/upload")
def api_upload_cert(body: UploadBody, user: User = Depends(require_admin)):
    try:
        cert = store.upload_certificate(
            name=body.name, cert_pem=body.certPem, key_pem=body.keyPem
        )
    except (CertError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if body.activate:
        store.activate_certificate(cert.id)
    logx.info(
        f"admin {user.username} uploaded TLS certificate {cert.name!r}"
        + (" and activated it" if body.activate else ""),
        username=user.username,
        operation="tls",
    )
    return cert.public()


@app.post("/api/certs/{cert_id}/activate")
def api_activate_cert(cert_id: str, user: User = Depends(require_admin)):
    try:
        store.activate_certificate(cert_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    cert = store.get_certificate(cert_id)
    logx.info(
        f"admin {user.username} activated TLS certificate "
        f"{(cert.name if cert else cert_id)!r}",
        username=user.username,
        operation="tls",
    )
    return {"ok": True}


@app.delete("/api/certs/{cert_id}")
def api_delete_cert(cert_id: str, user: User = Depends(require_admin)):
    cert = store.get_certificate(cert_id)
    store.delete_certificate(cert_id)
    logx.warn(
        f"admin {user.username} deleted TLS certificate "
        f"{(cert.name if cert else cert_id)!r}",
        username=user.username,
        operation="tls",
    )
    return {"ok": True}


@app.get("/api/certs/{cert_id}/download")
def api_download_cert(cert_id: str, user: User = Depends(require_admin)):
    pem = store.certificate_pem(cert_id)
    if pem is None:
        raise HTTPException(status_code=404, detail="No such certificate.")
    cert = store.get_certificate(cert_id)
    filename = (cert.name if cert else "certificate").replace(" ", "_") + ".crt"
    return PlainTextResponse(
        pem,
        media_type="application/x-pem-file",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── API: restart the GUI server ───────────────────────────────────────────────


def _signal_launcher(pid_path) -> int:
    """SIGHUP the launcher named by its PID file so it rebinds its listeners.
    Returns the PID; raises HTTPException on any problem."""
    if not pid_path.exists():
        raise HTTPException(
            status_code=409,
            detail=(
                "The app server is not managed by the launcher (no PID file). "
                "Start it with ./run.sh, then try again."
            ),
        )
    try:
        pid = int(pid_path.read_text().strip())
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=500, detail="Invalid PID file.") from exc
    try:
        os.kill(pid, 0)  # probe: is the process alive?
    except ProcessLookupError as exc:
        raise HTTPException(
            status_code=409, detail="The app server process is not running."
        ) from exc
    except PermissionError:
        pass  # alive but owned by another user — signalling may still work
    try:
        os.kill(pid, signal.SIGHUP)
    except OSError as exc:
        raise HTTPException(
            status_code=500, detail=f"Could not signal the app server: {exc}"
        ) from exc
    return pid


@app.post("/api/restart")
def api_restart(user: User = Depends(require_admin)):
    """Signal the GUI *and* admin launchers (SIGHUP) to rebind their listeners with
    the current TLS plan — applying a mode or certificate change without a terminal.

    The admin interface follows the same TLS mode, so it restarts itself too: this
    request's connection may drop and, if the mode changed, the admin moves to a
    different scheme/port — reconnect there if this page stops responding."""
    logx.info(
        f"admin {user.username} restarted the app + admin servers",
        username=user.username,
        operation="restart",
    )
    gui_pid = _signal_launcher(GUI_PID_PATH)
    # The integration console follows the same TLS plan; rebind it too (best-effort —
    # it may not be running). Signal it before our own admin launcher.
    integration_pid: int | None = None
    if INTEGRATION_PID_PATH.exists():
        try:
            integration_pid = int(INTEGRATION_PID_PATH.read_text().strip())
            os.kill(integration_pid, signal.SIGHUP)
        except (ValueError, OSError):
            integration_pid = None
    # The Actions surface follows the same TLS plan; rebind it too (best-effort).
    actions_pid: int | None = None
    if ACTIONS_PID_PATH.exists():
        try:
            actions_pid = int(ACTIONS_PID_PATH.read_text().strip())
            os.kill(actions_pid, signal.SIGHUP)
        except (ValueError, OSError):
            actions_pid = None
    # The API Server - Event Receiver supervisor, best-effort — rebinds all sink listeners.
    sink_pid: int | None = None
    if SINK_PID_PATH.exists():
        try:
            sink_pid = int(SINK_PID_PATH.read_text().strip())
            os.kill(sink_pid, signal.SIGHUP)
        except (ValueError, OSError):
            sink_pid = None
    # Restart the admin launcher too, best-effort: signalling our own launcher tears
    # down this very listener, so don't fail the request if the response races it.
    admin_pid: int | None = None
    if ADMIN_PID_PATH.exists():
        try:
            admin_pid = int(ADMIN_PID_PATH.read_text().strip())
            os.kill(admin_pid, signal.SIGHUP)
        except (ValueError, OSError):
            admin_pid = None
    return {
        "ok": True,
        "pid": gui_pid,
        "integrationPid": integration_pid,
        "actionsPid": actions_pid,
        "sinkPid": sink_pid,
        "adminPid": admin_pid,
    }


# ── API: integration / data-source console ────────────────────────────────────


class IntegrationEnabledBody(BaseModel):
    enabled: bool


@app.get("/api/integration")
def api_integration_status(user: User = Depends(require_admin)):
    """State of the integration console surface: whether it's enabled, its ports and
    whether its launcher is currently running (best-effort, from the PID file)."""
    return {
        "enabled": store.integration_enabled,
        "httpPort": INTEGRATION_PORT,
        "httpsPort": INTEGRATION_HTTPS_PORT,
        "running": INTEGRATION_PID_PATH.exists(),
    }


@app.post("/api/integration/enabled")
def api_set_integration_enabled(
    body: IntegrationEnabledBody, user: User = Depends(require_admin)
):
    store.set_integration_enabled(body.enabled)
    logx.usage(
        f"admin {user.username} {'enabled' if body.enabled else 'disabled'} "
        f"the integration console",
        username=user.username, operation="config",
    )
    return {"ok": True, "enabled": store.integration_enabled}


class ActionsEnabledBody(BaseModel):
    enabled: bool


@app.get("/api/actions")
def api_actions_status(user: User = Depends(require_admin)):
    """State of the Actions feature: whether it's enabled, the Actions surface ports and
    whether its launcher is currently running (best-effort, from the PID file)."""
    return {
        "enabled": store.actions_enabled,
        "httpPort": ACTIONS_PORT,
        "httpsPort": ACTIONS_HTTPS_PORT,
        "running": ACTIONS_PID_PATH.exists(),
    }


@app.post("/api/actions/enabled")
def api_set_actions_enabled(
    body: ActionsEnabledBody, user: User = Depends(require_admin)
):
    store.set_actions_enabled(body.enabled)
    logx.usage(
        f"admin {user.username} {'enabled' if body.enabled else 'disabled'} "
        f"the Actions feature",
        username=user.username, operation="config",
    )
    return {"ok": True, "enabled": store.actions_enabled}


class SinkEnabledBody(BaseModel):
    enabled: bool


@app.get("/api/sink")
def api_sink_status(user: User = Depends(require_admin)):
    """State of the API Server - Event Receiver module: whether it's enabled, the size of the
    port pool, how many sinks are configured, and whether the supervisor is running."""
    return {
        "enabled": store.sink_enabled,
        "poolSize": SINK_POOL_SIZE,
        "sinkCount": len(store.list_all_sinks()),
        "running": SINK_PID_PATH.exists(),
    }


@app.post("/api/sink/enabled")
def api_set_sink_enabled(body: SinkEnabledBody, user: User = Depends(require_admin)):
    store.set_sink_enabled(body.enabled)
    logx.usage(
        f"admin {user.username} {'enabled' if body.enabled else 'disabled'} "
        f"the API Server - Event Receiver module",
        username=user.username, operation="config",
    )
    return {"ok": True, "enabled": store.sink_enabled}


# ── API: MCP server ───────────────────────────────────────────────────────────


class McpEnabledBody(BaseModel):
    enabled: bool


class McpSettingsBody(BaseModel):
    issuer: str = ""
    jwksUri: str = ""
    audience: str = ""
    requiredGroup: str = ""
    usernameClaim: str = "preferred_username"


@app.get("/api/mcp")
def api_mcp_status(user: User = Depends(require_admin)):
    """State of the MCP query server: whether it's enabled, its ports, whether its
    launcher is running (best-effort from the PID file), and its OAuth/Authentik
    settings (no secrets are stored — offline JWKS validation needs only public values)."""
    return {
        "enabled": store.mcp_enabled,
        "httpPort": MCP_PORT,
        "httpsPort": MCP_HTTPS_PORT,
        "running": MCP_PID_PATH.exists(),
        "settings": store.mcp_settings(),
    }


@app.post("/api/mcp/enabled")
def api_set_mcp_enabled(body: McpEnabledBody, user: User = Depends(require_admin)):
    store.set_mcp_enabled(body.enabled)
    logx.usage(
        f"admin {user.username} {'enabled' if body.enabled else 'disabled'} the MCP server",
        username=user.username, operation="config",
    )
    return {"ok": True, "enabled": store.mcp_enabled}


@app.post("/api/mcp/settings")
def api_set_mcp_settings(body: McpSettingsBody, user: User = Depends(require_admin)):
    store.set_mcp_settings(body.model_dump())
    logx.usage(
        f"admin {user.username} updated the MCP server settings",
        username=user.username, operation="config",
    )
    return {"ok": True, "settings": store.mcp_settings()}


@app.post("/api/mcp/test")
async def api_test_mcp(body: McpSettingsBody, user: User = Depends(require_admin)):
    """Validate the Authentik settings without saving: fetch the issuer's OpenID
    discovery document and confirm a JWKS endpoint is reachable. Never leaks the raw
    upstream error to non-admins (this route is admin-only, so full detail is fine)."""
    import httpx

    issuer = (body.issuer or "").rstrip("/")
    if not issuer:
        return {"ok": False, "error": "Enter the Authentik issuer URL first."}
    disco = f"{issuer}/.well-known/openid-configuration"
    try:
        async with httpx.AsyncClient(timeout=8.0, verify=False) as client:
            r = await client.get(disco)
            r.raise_for_status()
            meta = r.json()
            jwks_uri = body.jwksUri or meta.get("jwks_uri", "")
            jr = await client.get(jwks_uri)
            jr.raise_for_status()
            keys = jr.json().get("keys", [])
        return {
            "ok": True,
            "issuer": meta.get("issuer", issuer),
            "jwksUri": jwks_uri,
            "keyCount": len(keys),
            "authorizationEndpoint": meta.get("authorization_endpoint", ""),
        }
    except Exception as exc:  # noqa: BLE001 — admin-only route, detail is helpful
        return {"ok": False, "error": f"Could not reach Authentik at {disco}: {exc}"}


# ── API: connections (admin-defined, assigned to users) ───────────────────────


class ConnectionBody(BaseModel):
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
    useMaterializedTransitions: bool = False
    useInDbSampling: bool = False

    model_config = {"populate_by_name": True}


class AssignmentsBody(BaseModel):
    assignments: list[str]


class ConnectionTestBody(BaseModel):
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
    buildTransitions: bool = False  # provision only: also build TRANSITIONS_RAW

    model_config = {"populate_by_name": True}


def _connection_payload(body: ConnectionBody) -> dict:
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
        "useMaterializedTransitions": body.useMaterializedTransitions,
        "useInDbSampling": body.useInDbSampling,
    }
    # Only forward secrets that were explicitly provided (None ⇒ keep existing).
    if body.password is not None:
        data["password"] = body.password
    if body.llmKey is not None:
        data["llmKey"] = body.llmKey
    return data


@app.get("/api/connections")
def api_connections(user: User = Depends(require_admin)):
    out = []
    for c in store.list_connections():
        d = c.admin_public()
        d["materialization"] = store.materialization_status(c.id)
        d["rebuildTokenSet"] = store.rebuild_token_set(c.id)
        out.append(d)
    return out


@app.post("/api/connections")
def api_upsert_connection(body: ConnectionBody, user: User = Depends(require_admin)):
    existed = bool(body.id) and store.get_connection(body.id) is not None
    try:
        conn = store.upsert_connection(_connection_payload(body))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    logx.info(
        f"admin {user.username} {'updated' if existed else 'created'} database "
        f"connection {conn.name!r} ({conn.id})",
        username=user.username,
        operation="connection",
    )
    return conn.admin_public()


@app.post("/api/connections/{conn_id}/assignments")
def api_set_assignments(
    conn_id: str, body: AssignmentsBody, user: User = Depends(require_admin)
):
    try:
        store.set_assignments(conn_id, body.assignments)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    logx.info(
        f"admin {user.username} set the user assignments for connection {conn_id} "
        f"({len(body.assignments)} user(s))",
        username=user.username,
        operation="connection",
    )
    return {"ok": True}


@app.delete("/api/connections/{conn_id}")
def api_delete_connection(conn_id: str, user: User = Depends(require_admin)):
    conn = store.get_connection(conn_id)
    store.delete_connection(conn_id)
    logx.warn(
        f"admin {user.username} deleted database connection "
        f"{(conn.name if conn else conn_id)!r} ({conn_id})",
        username=user.username,
        operation="connection",
    )
    return {"ok": True}


@app.post("/api/connections/test")
async def api_test_connection(body: ConnectionTestBody, user: User = Depends(require_admin)):
    from app.db.manager import check_llm_reachable, test_db_connection
    from app.models import LLMServer
    from app.services import llm as llm_service

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
    logx.info(
        f"admin {user.username} tested a database connection to "
        f"{body.host}:{body.port} — {'ok' if not db_error else f'failed: {db_error}'}",
        username=user.username,
        operation="connection",
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
        logx.info(
            f"admin {user.username} tested an LLM server at {body.llmURL} — "
            f"{'ok' if not llm_error else f'failed: {llm_error}'}"
            + (f" ({len(llm_models)} models)" if llm_models else ""),
            username=user.username,
            operation="llm-test",
        )

    return {"dbError": db_error, "llmError": llm_error, "llmModels": llm_models}


@app.post("/api/connections/provision-schema")
async def api_provision_schema(body: ConnectionTestBody, user: User = Depends(require_admin)):
    """Create the process-mining schema + tables using the supplied credentials.

    Requires elevated database privileges (CREATE SCHEMA / CREATE TABLE) that only a
    database administrator can grant — the app cannot.
    """
    from app.db.schema_ddl import (
        provision_process_mining_schema,
        rebuild_materialized_transitions,
    )

    result = await provision_process_mining_schema(
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
    # Optionally seed the pre-materialised transitions table straight away (empty
    # until JOURNEYS is loaded, but the structure exists and the flag can be used).
    if result.get("ok") and body.buildTransitions:
        result["materialization"] = await rebuild_materialized_transitions(
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
    return result


# ── pre-materialised transitions: rebuild + per-connection API token ──────────

# In-process guards for the rebuild endpoint (it lives only on this single admin
# process). Prevent two rebuilds of one connection at once (they'd race on the
# staging-table swap), and throttle token-triggered rebuilds so a leaked token
# can't hammer the customer database.
_REBUILD_TOKEN_COOLDOWN_SECS = 60
_rebuild_in_progress: set[str] = set()
_rebuild_last_token_run: dict[str, float] = {}


def _rebuild_authorized(request: Request, conn_id: str) -> str | None:
    """Authorise a rebuild of ``conn_id`` by EITHER an admin session OR that
    connection's bearer rebuild token. Returns an actor label to log, or None if
    unauthorised. A token only ever authorises its own connection."""
    user = _current_user(request)
    if user is not None:
        return user.username
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        if store.verify_rebuild_token(conn_id, token):
            return "api-token"
    return None


@app.post("/api/connections/{conn_id}/rebuild-transitions")
async def api_rebuild_transitions(conn_id: str, request: Request):
    """(Re)build TRANSITIONS_RAW for a stored connection. Auth: admin session or
    `Authorization: Bearer <the connection's rebuild-token>`. Uses the stored
    credentials, so the caller never handles them."""
    actor = _rebuild_authorized(request, conn_id)
    if actor is None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    conn = store.get_connection(conn_id, with_secrets=True)
    if conn is None:
        raise HTTPException(status_code=404, detail="No such connection.")

    # Never overlap rebuilds of the same connection (staging-swap race).
    if conn_id in _rebuild_in_progress:
        raise HTTPException(
            status_code=409, detail="A rebuild is already running for this connection."
        )
    # Throttle automated (token) callers; admins may force a rebuild anytime.
    if actor == "api-token":
        wait = _REBUILD_TOKEN_COOLDOWN_SECS - (
            time.time() - _rebuild_last_token_run.get(conn_id, 0.0)
        )
        if wait > 0:
            raise HTTPException(
                status_code=429,
                detail=f"Rebuild throttled — try again in {max(1, round(wait))}s.",
            )
        _rebuild_last_token_run[conn_id] = time.time()

    from app.db.schema_ddl import rebuild_materialized_transitions

    _rebuild_in_progress.add(conn_id)
    try:
        result = await rebuild_materialized_transitions(
            host=conn.host,
            port=conn.port,
            username=conn.username,
            password=conn.password,
            schema=conn.schema,
            use_tls=conn.use_tls,
            cert_mode=conn.cert_mode,
            fingerprint=conn.fingerprint,
            min_rsa_bits=conn.min_rsa_bits,
        )
    finally:
        _rebuild_in_progress.discard(conn_id)

    store.set_materialization_status(
        conn_id,
        {
            "ok": result["ok"],
            "rows": result["rows"],
            "built_at": result["built_at"],
            "error": result["error"],
        },
    )
    logx.info(
        f"{actor} rebuilt materialised transitions for connection {conn.name!r} "
        f"({conn_id}) — "
        + (f"ok, {result['rows']} pairs" if result["ok"] else f"failed: {result['error']}"),
        username=actor,
        operation="materialize",
    )
    return result


@app.post("/api/connections/{conn_id}/rebuild-token")
def api_rebuild_token_generate(conn_id: str, user: User = Depends(require_admin)):
    """Generate (or rotate) this connection's rebuild token. Returned in plaintext
    ONCE — only its hash is stored, so it cannot be shown again."""
    if store.get_connection(conn_id) is None:
        raise HTTPException(status_code=404, detail="No such connection.")
    token = store.generate_rebuild_token(conn_id)
    logx.warn(
        f"admin {user.username} generated a rebuild API token for connection {conn_id}",
        username=user.username,
        operation="materialize",
    )
    return {"token": token}


@app.delete("/api/connections/{conn_id}/rebuild-token")
def api_rebuild_token_clear(conn_id: str, user: User = Depends(require_admin)):
    store.clear_rebuild_token(conn_id)
    logx.warn(
        f"admin {user.username} revoked the rebuild API token for connection {conn_id}",
        username=user.username,
        operation="materialize",
    )
    return {"ok": True}


# ── projects stored in a connection's schema ──────────────────────────────────


class ProjectDeleteBody(BaseModel):
    projectId: str = Field(min_length=1, max_length=100)


@app.get("/api/connections/{conn_id}/projects")
async def api_list_projects(conn_id: str, user: User = Depends(require_admin)):
    """List the projects stored in a connection's schema with their journey/event
    counts. Uses the stored credentials, so the admin never handles them."""
    conn = store.get_connection(conn_id, with_secrets=True)
    if conn is None:
        raise HTTPException(status_code=404, detail="No such connection.")

    from app.db.schema_ddl import list_projects_with_counts

    return await list_projects_with_counts(
        host=conn.host, port=conn.port, username=conn.username, password=conn.password,
        schema=conn.schema, use_tls=conn.use_tls, cert_mode=conn.cert_mode,
        fingerprint=conn.fingerprint, min_rsa_bits=conn.min_rsa_bits,
    )


@app.post("/api/connections/{conn_id}/projects/delete")
async def api_delete_project(conn_id: str, body: ProjectDeleteBody, user: User = Depends(require_admin)):
    """Delete a project from a connection's schema, clearing its rows from every
    project-scoped table (PROJECTS, JOURNEYS, STEPS, METAS, NOTES, TRANSITIONS_RAW)."""
    conn = store.get_connection(conn_id, with_secrets=True)
    if conn is None:
        raise HTTPException(status_code=404, detail="No such connection.")

    from app.db.schema_ddl import delete_project

    result = await delete_project(
        project_id=body.projectId, host=conn.host, port=conn.port, username=conn.username,
        password=conn.password, schema=conn.schema, use_tls=conn.use_tls,
        cert_mode=conn.cert_mode, fingerprint=conn.fingerprint, min_rsa_bits=conn.min_rsa_bits,
    )
    logx.warn(
        f"admin {user.username} deleted project {body.projectId!r} from connection "
        f"{conn.name!r} ({conn_id}) — "
        + ("ok" if result.get("ok") else f"failed: {result.get('error')}"),
        username=user.username,
        operation="connection",
    )
    return result


# ── LDAP / directory ──────────────────────────────────────────────────────────


class LdapConfigBody(BaseModel):
    enabled: bool = False
    serverURI: str = ""
    startTLS: bool = False
    verifyCert: bool = True
    caCert: str = ""
    bindDN: str = ""
    bindPassword: str | None = None  # omit to keep, "" to clear, value to set
    baseDN: str = ""
    userFilter: str = "(uid={username})"
    loginAttr: str = "uid"
    emailAttr: str = "mail"
    displayAttr: str = "cn"
    adminLoginEnabled: bool = False
    showStatusOnLogin: bool = True


class LdapTestBody(LdapConfigBody):
    testUsername: str = ""
    testPassword: str = ""


def _ldap_payload(body: LdapConfigBody) -> dict:
    data: dict = {
        "enabled": body.enabled,
        "serverURI": body.serverURI,
        "startTLS": body.startTLS,
        "verifyCert": body.verifyCert,
        "caCert": body.caCert,
        "bindDN": body.bindDN,
        "baseDN": body.baseDN,
        "userFilter": body.userFilter,
        "loginAttr": body.loginAttr,
        "emailAttr": body.emailAttr,
        "displayAttr": body.displayAttr,
        "adminLoginEnabled": body.adminLoginEnabled,
        "showStatusOnLogin": body.showStatusOnLogin,
    }
    if body.bindPassword is not None:
        data["bindPassword"] = body.bindPassword
    return data


@app.get("/api/ldap")
def api_ldap(user: User = Depends(require_admin)):
    return store.ldap_admin_public()


@app.post("/api/ldap")
def api_save_ldap(body: LdapConfigBody, user: User = Depends(require_admin)):
    store.set_ldap_config(_ldap_payload(body))
    logx.info(
        f"admin {user.username} saved the directory (LDAP) configuration — "
        f"enabled={body.enabled}, server={body.serverURI or '—'}, "
        f"admin-login={body.adminLoginEnabled}",
        username=user.username,
        operation="ldap",
    )
    return store.ldap_admin_public()


@app.post("/api/ldap/test")
def api_test_ldap(body: LdapTestBody, user: User = Depends(require_admin)):
    from app.services.ldap_auth import LdapSettings, test_settings

    # Test the *submitted* settings; fall back to the stored bind password when the
    # field was left blank (so testing an already-saved config needs no re-typing).
    bind_password = body.bindPassword
    if bind_password is None:
        bind_password = store.ldap_settings().bind_password
    settings = LdapSettings(
        enabled=body.enabled,
        server_uri=body.serverURI,
        start_tls=body.startTLS,
        verify_cert=body.verifyCert,
        ca_cert=body.caCert,
        bind_dn=body.bindDN,
        bind_password=bind_password or "",
        base_dn=body.baseDN,
        user_filter=body.userFilter or "(uid={username})",
        login_attr=body.loginAttr or "uid",
        email_attr=body.emailAttr or "mail",
        display_attr=body.displayAttr or "cn",
    )
    result = test_settings(settings, body.testUsername, body.testPassword)
    if body.testUsername:
        ok = bool(result.get("userOk"))
        logx.info(
            f"admin {user.username} tested a directory account login for "
            f"{body.testUsername!r} — {'success' if ok else 'failed'}",
            username=user.username,
            operation="ldap",
        )
    else:
        ok = bool(result.get("ok"))
        logx.info(
            f"admin {user.username} tested the directory server connection "
            f"({body.serverURI or 'no URI'}) — {'reachable' if ok else 'failed'}",
            username=user.username,
            operation="ldap",
        )
    return result


class CustomizeLoginBody(BaseModel):
    type: str
    color: str = ""
    image: str | None = None


@app.get("/api/customize/login")
def api_customize_login(user: User = Depends(require_admin)):
    return store.login_appearance()


@app.post("/api/customize/login")
def api_save_customize_login(
    body: CustomizeLoginBody, user: User = Depends(require_admin)
):
    try:
        appearance = store.set_login_appearance(
            type=body.type, color=body.color, image=body.image
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    detail = {
        "color": f"a solid colour ({appearance['color']})",
        "image": "an uploaded background image",
        "default": "the default theme colour",
    }.get(appearance["type"], appearance["type"])
    logx.info(
        f"admin {user.username} changed the login page background to {detail}",
        username=user.username,
        operation="customize",
    )
    return appearance


# ── Reporting (AI report LLM + style + per-connection/project prompts) ──────────


class ReportConfigBody(BaseModel):
    """The report LLM only — shared by all projects."""
    llmUrl: str = ""
    llmModel: str = ""
    llmKey: str | None = None  # None → keep the stored key; "" → clear it


class ReportStyleBody(BaseModel):
    """Style & Sections for one (connection, project). `logo` None keeps the stored logo."""
    connectionId: str
    projectId: str
    accent: str = ""
    orgName: str = ""
    logo: str | None = None
    logoPos: str = "left"
    logoScale: float = 1.0
    includeSankey: bool = True
    includeHappyPath: bool = True
    includeConformance: bool = True


@app.get("/api/reporting/config")
def api_reporting_config(user: User = Depends(require_admin)):
    return store.report_config()  # never leaks the key


@app.post("/api/reporting/config")
def api_save_reporting_config(body: ReportConfigBody, user: User = Depends(require_admin)):
    cfg = store.set_report_config(
        llm_url=body.llmUrl, llm_model=body.llmModel, llm_key=body.llmKey
    )
    logx.info(
        f"admin {user.username} updated the report LLM",
        username=user.username,
        operation="reporting",
    )
    return cfg


@app.get("/api/reporting/styles")
def api_reporting_styles(user: User = Depends(require_admin)):
    """Every configured project style (logo omitted — see /api/reporting/style)."""
    return store.report_styles()


@app.get("/api/reporting/style")
def api_reporting_style(
    connectionId: str, projectId: str, user: User = Depends(require_admin)
):
    """The full style (incl. logo) for one (connection, project), or null when unset."""
    return store.report_style_for(connectionId, projectId)


@app.post("/api/reporting/style")
def api_save_reporting_style(body: ReportStyleBody, user: User = Depends(require_admin)):
    try:
        rows = store.set_report_style(
            body.connectionId,
            body.projectId,
            accent=body.accent,
            org_name=body.orgName,
            logo=body.logo,
            logo_pos=body.logoPos,
            logo_scale=body.logoScale,
            include_sankey=body.includeSankey,
            include_happy_path=body.includeHappyPath,
            include_conformance=body.includeConformance,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    logx.info(
        f"admin {user.username} updated report style for {body.connectionId}/{body.projectId}",
        username=user.username,
        operation="reporting",
    )
    return rows


@app.delete("/api/reporting/style")
def api_delete_reporting_style(
    connectionId: str, projectId: str, user: User = Depends(require_admin)
):
    rows = store.delete_report_style(connectionId, projectId)
    logx.info(
        f"admin {user.username} removed report style for {connectionId}/{projectId}",
        username=user.username,
        operation="reporting",
    )
    return rows


class ReportLLMTestBody(BaseModel):
    llmUrl: str
    llmKey: str = ""


@app.post("/api/reporting/test-llm")
async def api_reporting_test_llm(
    body: ReportLLMTestBody, user: User = Depends(require_admin)
):
    from app.db.manager import check_llm_reachable
    from app.models import LLMServer
    from app.services import llm as llm_service

    # A blank key means "use the stored one" — so Test works without re-typing the secret.
    key = body.llmKey if body.llmKey.strip() else store.report_config(with_secret=True).get("llmKey", "")
    error: str | None = None
    models: list[str] = []
    if body.llmUrl.strip():
        llm = LLMServer(serverURL=body.llmUrl, apiKey=key)
        if await check_llm_reachable(llm):
            try:
                models = await llm_service.list_models(body.llmUrl, key)
            except Exception as exc:  # noqa: BLE001
                error = str(exc)
        else:
            error = "LLM server not reachable."
    else:
        error = "Enter an LLM server URL first."
    logx.info(
        f"admin {user.username} tested the report LLM at {body.llmUrl} — "
        f"{'ok' if not error else f'failed: {error}'}",
        username=user.username,
        operation="llm-test",
    )
    return {"error": error, "models": models}


@app.get("/api/reporting/projects/{connection_id}")
async def api_reporting_projects(connection_id: str, user: User = Depends(require_admin)):
    """The projects in a connection's database, for the prompt-linking dropdown. Returns
    {error, projects:[{projectId, title}]} — title for display, projectId for linkage."""
    from app.db.schema_ddl import list_projects_with_counts

    conn = store.get_connection(connection_id, with_secrets=True)
    if conn is None:
        raise HTTPException(status_code=404, detail="Unknown connection")
    res = await list_projects_with_counts(
        host=conn.host,
        port=conn.port,
        username=conn.username,
        password=conn.password,
        schema=conn.schema,
        use_tls=conn.use_tls,
        cert_mode=conn.cert_mode,
        fingerprint=conn.fingerprint,
        min_rsa_bits=conn.min_rsa_bits,
    )
    return {
        "error": None if res.get("ok") else res.get("error"),
        "projects": [
            {"projectId": p["projectId"], "title": p.get("title") or p["projectId"]}
            for p in res.get("projects", [])
        ],
    }


@app.get("/api/reporting/prompts")
def api_reporting_prompts(user: User = Depends(require_admin)):
    return store.report_prompts()


class ReportPromptBody(BaseModel):
    connectionId: str
    projectId: str
    prompt: str = ""


@app.post("/api/reporting/prompts")
def api_save_reporting_prompt(body: ReportPromptBody, user: User = Depends(require_admin)):
    try:
        rows = store.set_report_prompt(body.connectionId, body.projectId, body.prompt)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    logx.info(
        f"admin {user.username} {'removed' if not body.prompt.strip() else 'saved'} a "
        f"report prompt for connection {body.connectionId} / project {body.projectId}",
        username=user.username,
        operation="reporting",
    )
    return rows


@app.get("/health")
def health():
    return JSONResponse({"status": "ok"})
