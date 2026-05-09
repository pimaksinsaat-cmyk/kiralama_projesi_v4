from datetime import datetime, timedelta, timezone
import secrets

from flask import session
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.extensions import db


SESSION_TOKEN_KEY = "active_session_token"
SESSION_LAST_PING_KEY = "active_session_last_ping"
SESSION_TIMEOUT = timedelta(minutes=30)
SESSION_PING_THROTTLE = timedelta(seconds=120)


def utc_now():
    return datetime.now(timezone.utc)


def as_utc(value):
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def new_session_token():
    return secrets.token_urlsafe(32)


def has_recent_active_session(user, now=None):
    seen_at = as_utc(getattr(user, "active_session_seen_at", None))
    if not getattr(user, "active_session_token", None) or seen_at is None:
        return False
    return (now or utc_now()) - seen_at < SESSION_TIMEOUT


def set_active_session(user, token=None, now=None):
    token = token or new_session_token()
    now = now or utc_now()
    user.active_session_token = token
    user.active_session_started_at = now
    user.active_session_seen_at = now
    session[SESSION_TOKEN_KEY] = token
    session[SESSION_LAST_PING_KEY] = now.isoformat()
    return token


def clear_active_session(user):
    user.active_session_token = None
    user.active_session_started_at = None
    user.active_session_seen_at = None


def clear_session_keys():
    session.pop(SESSION_TOKEN_KEY, None)
    session.pop(SESSION_LAST_PING_KEY, None)


def session_token_matches(user):
    token = session.get(SESSION_TOKEN_KEY)
    return bool(token and token == getattr(user, "active_session_token", None))


def account_is_active(user):
    try:
        value = db.session.execute(
            text('SELECT is_active FROM "user" WHERE id = :user_id'),
            {"user_id": user.id},
        ).scalar_one_or_none()
    except SQLAlchemyError:
        db.session.rollback()
        return True
    if value is None:
        return True
    return bool(value)


def should_touch_seen_at(now=None):
    now = now or utc_now()
    raw_last_ping = session.get(SESSION_LAST_PING_KEY)
    if not raw_last_ping:
        return True
    try:
        last_ping = as_utc(datetime.fromisoformat(raw_last_ping))
    except (TypeError, ValueError):
        return True
    return now - last_ping >= SESSION_PING_THROTTLE


def mark_seen(user, now=None):
    now = now or utc_now()
    user.active_session_seen_at = now
    session[SESSION_LAST_PING_KEY] = now.isoformat()
