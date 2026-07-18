from datetime import datetime, timedelta, timezone

from app.api.auth import issue_token_pair
from app.auth.models import User
from app.auth.session_security import new_session_token, utc_now
from app.extensions import db
from app.models.system_state import ApiRefreshRotation


def _create_user(username='jwt_user'):
    user = User(username=username, rol='admin')
    user.set_password('pass123')
    db.session.add(user)
    db.session.commit()
    return user


def _login(client, user):
    response = client.post(
        '/api/auth/login',
        json={'username': user.username, 'password': 'pass123'},
    )
    assert response.status_code == 200
    return response.get_json()['data']


def test_api_blueprint_is_protected_by_default(client, app):
    response = client.get('/api/dashboard')
    assert response.status_code == 401
    assert response.get_json()['ok'] is False


def test_refresh_rotation_grace_returns_same_pair(client, app):
    with app.app_context():
        user = _create_user()
        login_data = _login(client, user)
        headers = {'Authorization': f"Bearer {login_data['refresh_token']}"}

        first = client.post('/api/auth/refresh', headers=headers)
        second = client.post('/api/auth/refresh', headers=headers)

        assert first.status_code == 200
        assert second.status_code == 200
        assert first.get_json()['data'] == second.get_json()['data']

        new_access = first.get_json()['data']['access_token']
        me = client.get('/api/auth/me', headers={'Authorization': f'Bearer {new_access}'})
        assert me.status_code == 200


def test_old_refresh_is_rejected_after_grace(client, app):
    with app.app_context():
        user = _create_user('jwt_expired_grace')
        login_data = _login(client, user)
        headers = {'Authorization': f"Bearer {login_data['refresh_token']}"}
        assert client.post('/api/auth/refresh', headers=headers).status_code == 200

        rotation = ApiRefreshRotation.query.filter_by(user_id=user.id).one()
        rotation.grace_expires_at = utc_now() - timedelta(seconds=1)
        db.session.commit()

        retry = client.post('/api/auth/refresh', headers=headers)
        assert retry.status_code == 401


def test_refresh_token_cannot_be_used_as_access_token(client, app):
    with app.app_context():
        user = _create_user('jwt_wrong_type')
        login_data = _login(client, user)
        response = client.get(
            '/api/auth/me',
            headers={'Authorization': f"Bearer {login_data['refresh_token']}"},
        )
        assert response.status_code == 401


def test_access_token_clock_skew_leeway(client, app):
    with app.app_context():
        user = _create_user('jwt_leeway')
        session_token = new_session_token()
        user.active_session_token = session_token
        user.active_session_started_at = utc_now()
        user.active_session_seen_at = utc_now()
        db.session.commit()

        original_lifetime = app.config['API_ACCESS_TOKEN_SECONDS']
        app.config['API_ACCESS_TOKEN_SECONDS'] = 1
        try:
            within_leeway = issue_token_pair(
                user,
                session_token,
                issued_at=datetime.now(timezone.utc) - timedelta(seconds=5),
            )
            outside_leeway = issue_token_pair(
                user,
                session_token,
                issued_at=datetime.now(timezone.utc) - timedelta(seconds=20),
            )
        finally:
            app.config['API_ACCESS_TOKEN_SECONDS'] = original_lifetime

        accepted = client.get(
            '/api/auth/me',
            headers={'Authorization': f"Bearer {within_leeway['access_token']}"},
        )
        rejected = client.get(
            '/api/auth/me',
            headers={'Authorization': f"Bearer {outside_leeway['access_token']}"},
        )
        assert accepted.status_code == 200
        assert rejected.status_code == 401
