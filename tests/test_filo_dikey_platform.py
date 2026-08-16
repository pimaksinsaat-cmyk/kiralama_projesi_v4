"""Dikey Platform makine tipi: Filo form, API ve kiralama filtre regresyonu."""

from __future__ import annotations

import uuid
from datetime import date

from app.auth.models import User
from app.auth.session_security import (
    SESSION_LAST_PING_KEY,
    SESSION_TOKEN_KEY,
    new_session_token,
    utc_now,
)
from app.extensions import db
from app.filo.forms import EKIPMAN_TIPI_SECENEKLERI
from app.filo.models import Ekipman
from app.subeler.models import Sube


def _login_user(client, user_id: int) -> None:
    token = new_session_token()
    now = utc_now()
    user = db.session.get(User, user_id)
    user.active_session_token = token
    user.active_session_started_at = now
    user.active_session_seen_at = now
    db.session.commit()

    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True
        session[SESSION_TOKEN_KEY] = token
        session[SESSION_LAST_PING_KEY] = now.isoformat()


def _auth_headers(client, username: str, password: str = "pass123"):
    response = client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200
    token = response.get_json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_dikey_platform_in_ekipman_tipi_secenekleri():
    assert ("DIKEY PLATFORM", "Dikey Platform") in EKIPMAN_TIPI_SECENEKLERI


def test_filo_ekle_get_shows_dikey_platform_and_post_persists(app, client):
    with app.app_context():
        admin = User(username=f"dikey_admin_{uuid.uuid4().hex[:6]}", rol="admin")
        admin.set_password("pass123")
        db.session.add(admin)
        db.session.flush()

        sube = Sube(
            isim="Dikey Platform Sube",
            adres="Adres",
            yetkili_kisi="Yetkili",
            telefon="0212",
        )
        db.session.add(sube)
        db.session.commit()

        admin_id = admin.id
        sube_id = sube.id
        username = admin.username

    _login_user(client, admin_id)

    get_response = client.get("/filo/ekle")
    assert get_response.status_code == 200
    html = get_response.get_data(as_text=True)
    assert "Dikey Platform" in html
    assert 'value="DIKEY PLATFORM"' in html

    kod = f"DP-{uuid.uuid4().hex[:6].upper()}"
    post_response = client.post(
        "/filo/ekle",
        data={
            "kod": kod,
            "tipi": "DIKEY PLATFORM",
            "marka": "Genie",
            "model": "GR-20",
            "seri_no": f"SN-{uuid.uuid4().hex[:8]}",
            "uretim_yili": "2024",
            "calisma_yuksekligi": "8",
            "kaldirma_kapasitesi": "227",
            "filoya_giris_tarihi": date(2026, 1, 15).isoformat(),
            "yakit": "Akülü",
            "sube_id": str(sube_id),
            "para_birimi": "TRY",
            "calisma_durumu": "bosta",
            "submit": "Kaydet",
        },
        follow_redirects=False,
    )
    assert post_response.status_code in (302, 303)

    with app.app_context():
        ekipman = Ekipman.query.filter_by(kod=kod).one()
        assert ekipman.tipi == "DIKEY PLATFORM"
        ekipman_id = ekipman.id

    filter_response = client.get(
        f"/kiralama/api/ekipman-filtrele?sube_id={sube_id}&tip=DIKEY%20PLATFORM"
    )
    assert filter_response.status_code == 200
    filter_payload = filter_response.get_json()
    assert filter_payload["success"] is True
    assert any(kod in item["label"] for item in filter_payload["data"])

    filo_index = client.get("/filo/index")
    assert filo_index.status_code == 200
    assert "DIKEY PLATFORM" in filo_index.get_data(as_text=True)

    # Web login holds the single active session; clear it before JWT login (else 409).
    with app.app_context():
        user = db.session.get(User, admin_id)
        user.active_session_token = None
        user.active_session_started_at = None
        user.active_session_seen_at = None
        db.session.commit()

    headers = _auth_headers(client, username)
    api_response = client.get("/api/filo?tip=DIKEY%20PLATFORM", headers=headers)
    assert api_response.status_code == 200
    api_payload = api_response.get_json()
    assert api_payload["ok"] is True
    assert any(item["id"] == ekipman_id for item in api_payload["data"]["items"])
