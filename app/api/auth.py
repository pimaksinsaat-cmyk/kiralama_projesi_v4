from datetime import datetime, timedelta, timezone
from functools import wraps
from uuid import uuid4

import jwt
from flask import current_app, g, jsonify, request

from app.auth.models import User
from app.auth.session_security import account_is_active, utc_now
from app.extensions import db


def _jwt_secret():
    return current_app.config.get('API_JWT_SECRET_KEY') or current_app.config['SECRET_KEY']


def _aware_utc(value=None):
    value = value or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).replace(microsecond=0)


def _naive_utc(value=None):
    return _aware_utc(value).replace(tzinfo=None)


def _claims(user_id, session_token, token_type, issued_at, jti):
    lifetime_key = 'API_ACCESS_TOKEN_SECONDS' if token_type == 'access' else 'API_REFRESH_TOKEN_SECONDS'
    return {
        'sub': str(user_id),
        'type': token_type,
        'session_token': session_token,
        'iat': issued_at,
        'exp': issued_at + timedelta(seconds=current_app.config[lifetime_key]),
        'iss': current_app.config['API_JWT_ISSUER'],
        'aud': current_app.config['API_JWT_AUDIENCE'],
        'jti': jti,
    }


def issue_token_pair(user, session_token, *, issued_at=None, access_jti=None, refresh_jti=None):
    issued_at = _aware_utc(issued_at)
    access_jti = access_jti or uuid4().hex
    refresh_jti = refresh_jti or uuid4().hex
    access_token = jwt.encode(
        _claims(user.id, session_token, 'access', issued_at, access_jti),
        _jwt_secret(),
        algorithm='HS256',
    )
    refresh_token = jwt.encode(
        _claims(user.id, session_token, 'refresh', issued_at, refresh_jti),
        _jwt_secret(),
        algorithm='HS256',
    )
    return {
        'access_token': access_token,
        'refresh_token': refresh_token,
        'token_type': 'Bearer',
        'access_expires_in': current_app.config['API_ACCESS_TOKEN_SECONDS'],
        'refresh_expires_in': current_app.config['API_REFRESH_TOKEN_SECONDS'],
        '_issued_at': _naive_utc(issued_at),
        '_access_jti': access_jti,
        '_refresh_jti': refresh_jti,
    }


def public_token_payload(pair):
    return {key: value for key, value in pair.items() if not key.startswith('_')}


def decode_token(token, expected_type):
    try:
        payload = jwt.decode(
            token,
            _jwt_secret(),
            algorithms=['HS256'],
            audience=current_app.config['API_JWT_AUDIENCE'],
            issuer=current_app.config['API_JWT_ISSUER'],
            leeway=current_app.config['API_JWT_LEEWAY_SECONDS'],
            options={'require': ['sub', 'type', 'session_token', 'iat', 'exp', 'iss', 'aud', 'jti']},
        )
    except jwt.ExpiredSignatureError:
        return None, 'Oturum suresi doldu. Lutfen tekrar giris yapin.'
    except jwt.PyJWTError:
        return None, 'Gecersiz oturum anahtari.'

    if payload.get('type') != expected_type:
        return None, 'Gecersiz token turu.'
    return payload, None


def bearer_token():
    auth_header = request.headers.get('Authorization', '')
    prefix = 'Bearer '
    if not auth_header.startswith(prefix):
        return None
    return auth_header[len(prefix):].strip() or None


def authenticate_request():
    token = bearer_token()
    if not token:
        return None, None, 'Oturum acmaniz gerekiyor.'
    payload, error = decode_token(token, 'access')
    if error:
        return None, None, error
    try:
        user_id = int(payload['sub'])
    except (TypeError, ValueError):
        return None, None, 'Gecersiz oturum anahtari.'

    user = db.session.get(User, user_id)
    if not user:
        return None, None, 'Kullanici bulunamadi veya pasif.'
    if not account_is_active(user):
        user.active_session_token = None
        user.active_session_started_at = None
        user.active_session_seen_at = None
        db.session.commit()
        return None, None, 'Kullanici bulunamadi veya pasif.'
    if user.active_session_token != payload.get('session_token'):
        return None, None, 'Oturumunuz sonlandi. Lutfen tekrar giris yapin.'

    now = utc_now()
    if user.active_session_seen_at is None or now - user.active_session_seen_at >= timedelta(seconds=60):
        user.active_session_seen_at = now
        db.session.commit()
    return user, payload, None


def protect_api_request():
    if request.method == 'OPTIONS' or request.endpoint in {'api.login', 'api.refresh'}:
        return None
    user, payload, error = authenticate_request()
    if error:
        return jsonify({'ok': False, 'message': error}), 401
    g.api_user = user
    g.api_token_payload = payload
    return None


def token_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if getattr(g, 'api_user', None) is None:
            response = protect_api_request()
            if response is not None:
                return response
        return view(*args, **kwargs)

    return wrapped
