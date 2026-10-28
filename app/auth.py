"""Admin login: Argon2id password hashes, server-side sessions, CSRF tokens, login throttling and an audit trail.

Browser sessions use a random id in a `__Host-` cookie (Secure, HttpOnly, SameSite=Strict, Path=/, no Domain); only its
SHA-256 is stored. State-changing requests made with a session must carry the session's CSRF token in X-CSRF-Token and
an Origin equal to the admin site's own origin. Scripts may instead use the X-Admin-Token machine token (no cookie, so no
CSRF exposure). Accounts are created on the server with `python -m app admin-user add <name>`; there is no sign-up.
"""
from __future__ import annotations

import os

import hashlib
import hmac
import secrets
from datetime import timedelta
from urllib.parse import urlsplit

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from psycopg.types.json import Jsonb

from . import db
from .config import settings

COOKIE = "__Host-dcm_admin"
PRE_COOKIE = "__Host-dcm_pre"           # pre-login CSRF (double submit on the login form)
IDLE = timedelta(minutes=30)
ABSOLUTE = timedelta(hours=8)
FAIL_WINDOW = timedelta(minutes=15)
FAILS_PER_ACCOUNT = 5
FAILS_PER_ADDRESS = 20

_hasher = PasswordHasher()               # Argon2id with the library's current recommended parameters
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))   # keeps unknown-user logins as slow as real ones


def hash_password(password: str) -> str:
    minimum = int(os.getenv("ADMIN_PASSWORD_MIN", "12"))     # in-house deployments may lower it in .env
    if len(password) < minimum:
        raise ValueError(f"use at least {minimum} characters")
    return _hasher.hash(password)


def _sha(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


# ---- accounts ------------------------------------------------------------------------------------
def add_user(username: str, password: str) -> None:
    with db.tx() as c:
        c.execute("""INSERT INTO admin_users (username, password_hash) VALUES (%s, %s)
                     ON CONFLICT (username) DO UPDATE SET password_hash = EXCLUDED.password_hash,
                       disabled = false, password_changed_at = now()""", (username, hash_password(password)))
        # a password reset ends every existing session of that account
        c.execute("DELETE FROM admin_sessions WHERE user_id = (SELECT id FROM admin_users WHERE username = %s)",
                  (username,))


def disable_user(username: str) -> None:
    with db.tx() as c:
        c.execute("UPDATE admin_users SET disabled = true WHERE username = %s", (username,))
        c.execute("DELETE FROM admin_sessions WHERE user_id = (SELECT id FROM admin_users WHERE username = %s)",
                  (username,))


def throttled(username: str, ip: str) -> bool:
    with db.connect() as c:
        rows = {r["key"]: r["n"] for r in c.execute(
            """SELECT key, count(*) n FROM admin_login_failures WHERE key = ANY(%s) AND at > now() - %s
               GROUP BY key""", ([f"user:{username.lower()}", f"ip:{ip}"], FAIL_WINDOW))}
    return rows.get(f"user:{username.lower()}", 0) >= FAILS_PER_ACCOUNT or rows.get(f"ip:{ip}", 0) >= FAILS_PER_ADDRESS


def check_password(username: str, password: str, ip: str) -> int | None:
    """User id on success. Failures are recorded for throttling; unknown users cost the same time as known ones."""
    with db.connect() as c:
        user = c.execute("SELECT id, password_hash, disabled FROM admin_users WHERE lower(username) = lower(%s)",
                         (username,)).fetchone()
    ok = False
    try:
        ok = _hasher.verify(user["password_hash"] if user else _DUMMY_HASH, password) and bool(user) \
            and not user["disabled"]
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        ok = False
    with db.tx() as c:
        if ok:
            c.execute("DELETE FROM admin_login_failures WHERE key = %s", (f"user:{username.lower()}",))
        else:
            c.execute("INSERT INTO admin_login_failures (key) VALUES (%s), (%s)", (f"user:{username.lower()}", f"ip:{ip}"))
            c.execute("DELETE FROM admin_login_failures WHERE at < now() - interval '1 day'")
    return user["id"] if ok else None


# ---- sessions ------------------------------------------------------------------------------------
def create_session(user_id: int, ip: str, user_agent: str) -> tuple[str, str]:
    raw, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    with db.tx() as c:
        c.execute("""INSERT INTO admin_sessions (id_hash, user_id, csrf_token, expires_at, ip, user_agent)
                     VALUES (%s, %s, %s, now() + %s, %s, %s)""",
                  (_sha(raw), user_id, csrf, ABSOLUTE, ip, (user_agent or "")[:300]))
        c.execute("DELETE FROM admin_sessions WHERE expires_at < now() OR last_seen < now() - %s", (IDLE,))
    return raw, csrf


def session(raw: str | None) -> dict | None:
    """The live session for a cookie value (idle 30 min, absolute 8 h), refreshing its idle timer."""
    if not raw:
        return None
    with db.tx() as c:
        row = c.execute(
            """UPDATE admin_sessions s SET last_seen = now() FROM admin_users u
               WHERE s.id_hash = %s AND u.id = s.user_id AND NOT u.disabled
                 AND s.expires_at > now() AND s.last_seen > now() - %s
               RETURNING s.id_hash, s.csrf_token, u.username""", (_sha(raw), IDLE)).fetchone()
    return row


def end_session(raw: str | None) -> None:
    if raw:
        with db.tx() as c:
            c.execute("DELETE FROM admin_sessions WHERE id_hash = %s", (_sha(raw),))


# ---- request checks -------------------------------------------------------------------------------
def machine_token_ok(token: str | None) -> bool:
    return bool(settings.admin_token and token and hmac.compare_digest(token, settings.admin_token))


def same_origin(origin: str | None, host: str | None) -> bool:
    """A state-changing browser request must come from this admin site's own page."""
    return bool(origin and host and urlsplit(origin).netloc == host)


def csrf_ok(sess: dict, header: str | None) -> bool:
    return bool(header) and hmac.compare_digest(header, sess["csrf_token"])


def audit(actor: str, action: str, detail: dict | None = None, ip: str | None = None) -> None:
    with db.tx() as c:
        c.execute("INSERT INTO admin_audit (actor, action, detail, ip) VALUES (%s, %s, %s, %s)",
                  (actor, action, Jsonb(detail or {}), ip))
