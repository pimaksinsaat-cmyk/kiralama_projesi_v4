from datetime import timedelta

from app.auth.models import User
from app.auth.session_security import (
    SESSION_LAST_PING_KEY,
    SESSION_TOKEN_KEY,
    utc_now,
)
from app.extensions import db


def _create_user(username="single_user", password="secret123", rol="user"):
    user = User(username=username, rol=rol)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return user.id


def _login(client, username="single_user", password="secret123", follow_redirects=False):
    return client.post(
        "/auth/login",
        data={"username": username, "password": password, "beni_hatirla": "y"},
        follow_redirects=follow_redirects,
    )


def test_login_sets_secure_single_session_fields(app, client):
    user_id = _create_user()

    response = _login(client)

    assert response.status_code == 302
    user = db.session.get(User, user_id)
    assert user.active_session_token
    assert len(user.active_session_token) >= 32
    assert user.active_session_started_at is not None
    assert user.active_session_seen_at is not None

    with client.session_transaction() as sess:
        assert sess[SESSION_TOKEN_KEY] == user.active_session_token
        assert "_remember" not in sess


def test_second_login_is_rejected_while_user_is_active(app, client):
    _create_user()
    first_response = _login(client)
    assert first_response.status_code == 302

    second_client = app.test_client()
    second_response = _login(second_client)

    assert second_response.status_code == 200
    assert "aktif" in second_response.get_data(as_text=True).lower()


def test_logout_clears_active_session_and_allows_login_again(app, client):
    user_id = _create_user()
    _login(client)

    logout_response = client.get("/auth/logout")

    assert logout_response.status_code == 302
    user = db.session.get(User, user_id)
    assert user.active_session_token is None
    assert user.active_session_started_at is None
    assert user.active_session_seen_at is None

    second_client = app.test_client()
    second_response = _login(second_client)
    assert second_response.status_code == 302


def test_expired_active_session_allows_new_login(app, client):
    user_id = _create_user()
    _login(client)

    user = db.session.get(User, user_id)
    old_token = user.active_session_token
    user.active_session_seen_at = utc_now() - timedelta(minutes=31)
    db.session.commit()

    second_client = app.test_client()
    second_response = _login(second_client)

    assert second_response.status_code == 302
    db.session.refresh(user)
    assert user.active_session_token
    assert user.active_session_token != old_token


def test_mismatched_session_token_is_logged_out(app, client):
    _create_user()
    _login(client)

    with client.session_transaction() as sess:
        sess[SESSION_TOKEN_KEY] = "wrong-token"

    response = client.get("/")

    assert response.status_code == 302
    assert "/auth/login" in response.headers["Location"]


def test_seen_at_is_not_updated_before_120_seconds(app, client):
    user_id = _create_user()
    _login(client)

    user = db.session.get(User, user_id)
    original_seen_at = user.active_session_seen_at
    with client.session_transaction() as sess:
        sess[SESSION_LAST_PING_KEY] = utc_now().isoformat()

    response = client.get("/")

    assert response.status_code == 200
    db.session.refresh(user)
    assert user.active_session_seen_at == original_seen_at


def test_seen_at_updates_after_120_seconds(app, client):
    user_id = _create_user()
    _login(client)

    user = db.session.get(User, user_id)
    original_seen_at = user.active_session_seen_at
    with client.session_transaction() as sess:
        sess[SESSION_LAST_PING_KEY] = (utc_now() - timedelta(seconds=121)).isoformat()

    response = client.get("/")

    assert response.status_code == 200
    db.session.refresh(user)
    assert user.active_session_seen_at > original_seen_at


def test_password_change_invalidates_target_user_session(app, client):
    user_id = _create_user()
    admin_id = _create_user(username="admin_for_session", password="adminpass", rol="admin")
    _login(client, username="single_user", password="secret123")

    admin_client = app.test_client()
    _login(admin_client, username="admin_for_session", password="adminpass")
    response = admin_client.post(
        f"/auth/admin/kullanici/sifre/{user_id}",
        data={"yeni_sifre": "newsecret123"},
    )

    assert response.status_code == 302
    user = db.session.get(User, user_id)
    assert user.active_session_token is None

    admin = db.session.get(User, admin_id)
    assert admin.active_session_token is not None
