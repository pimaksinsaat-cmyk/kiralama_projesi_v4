import uuid
from decimal import Decimal

import pytest

from app.auth.models import User
from app.auth.session_security import (
    SESSION_LAST_PING_KEY,
    SESSION_TOKEN_KEY,
    new_session_token,
    utc_now,
)
from app.extensions import db
from app.firmalar.models import Firma
from app.services.base import ValidationError
from app.services.firma_services import FirmaService


def _vergi_no():
    return f"VN{uuid.uuid4().hex[:10].upper()}"


def _create_firma(name, vergi_no=None):
    firma = Firma(
        firma_adi=name,
        yetkili_adi="Yetkili",
        iletisim_bilgileri="Adres",
        vergi_dairesi="Istanbul VD",
        vergi_no=vergi_no or _vergi_no(),
        is_musteri=True,
        is_tedarikci=False,
        bakiye=Decimal("0"),
    )
    db.session.add(firma)
    db.session.flush()
    return firma


def _create_admin():
    admin = User(username=f"admin_{uuid.uuid4().hex[:8]}", rol="admin")
    admin.set_password("pass123")
    db.session.add(admin)
    db.session.flush()
    return admin


def _login_user(client, user_id):
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


def test_firma_update_allows_own_vergi_no(app):
    with app.app_context():
        firma = _create_firma("Firma A")
        db.session.commit()

        FirmaService.update(firma.id, {"vergi_no": firma.vergi_no})

        assert db.session.get(Firma, firma.id).vergi_no == firma.vergi_no


def test_firma_update_rejects_another_firmas_vergi_no(app):
    with app.app_context():
        firma = _create_firma("Firma A")
        other = _create_firma("Firma B")
        original_vergi_no = firma.vergi_no
        db.session.commit()

        with pytest.raises(ValidationError, match="vergi"):
            FirmaService.update(firma.id, {"vergi_no": other.vergi_no})

        assert db.session.get(Firma, firma.id).vergi_no == original_vergi_no


def test_firma_update_rejects_trimmed_duplicate_vergi_no(app):
    with app.app_context():
        firma = _create_firma("Firma A")
        other = _create_firma("Firma B")
        original_vergi_no = firma.vergi_no
        db.session.commit()

        with pytest.raises(ValidationError, match="vergi"):
            FirmaService.update(firma.id, {"vergi_no": f"  {other.vergi_no}  "})

        assert db.session.get(Firma, firma.id).vergi_no == original_vergi_no


def test_firma_duzelt_post_rejects_duplicate_vergi_no(app, client):
    with app.app_context():
        admin = _create_admin()
        firma = _create_firma("Firma A")
        other = _create_firma("Firma B")
        original_vergi_no = firma.vergi_no
        db.session.commit()

        _login_user(client, admin.id)
        response = client.post(
            f"/firmalar/duzelt/{firma.id}",
            data={
                "firma_adi": firma.firma_adi,
                "yetkili_adi": firma.yetkili_adi,
                "telefon": firma.telefon or "",
                "eposta": firma.eposta or "",
                "iletisim_bilgileri": firma.iletisim_bilgileri,
                "vergi_dairesi": firma.vergi_dairesi,
                "vergi_no": other.vergi_no,
                "genel_sozlesme_no": firma.sozlesme_no or "",
                "sozlesme_rev_no": firma.sozlesme_rev_no or 0,
                "sozlesme_tarihi": "",
                "is_musteri": "y",
            },
            follow_redirects=True,
        )

        assert response.status_code == 200
        assert b"vergi numaras" in response.data
        assert db.session.get(Firma, firma.id).vergi_no == original_vergi_no
