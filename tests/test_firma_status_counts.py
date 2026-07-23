import uuid

from app.auth.models import User
from app.auth.session_security import (
    SESSION_LAST_PING_KEY,
    SESSION_TOKEN_KEY,
    new_session_token,
    utc_now,
)
from app.extensions import db
from app.firmalar.models import Firma
from app.services.firma_services import FirmaService


def _vergi_no():
    return f"FS{uuid.uuid4().hex[:10].upper()}"


def _firma(name, *, is_active=True, is_deleted=False):
    firma = Firma(
        firma_adi=name,
        yetkili_adi="Yetkili",
        iletisim_bilgileri="Adres",
        vergi_dairesi="Istanbul VD",
        vergi_no=_vergi_no(),
        is_musteri=True,
        is_tedarikci=False,
        is_active=is_active,
        is_deleted=is_deleted,
    )
    db.session.add(firma)
    return firma


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


def test_firma_status_counts_exclude_deleted_and_internal_firmalar(app):
    with app.app_context():
        _firma("Aktif Firma")
        _firma("Pasif Firma 1", is_active=False)
        _firma("Pasif Firma 2", is_active=False)
        _firma("Silinmis Firma", is_deleted=True)
        _firma("DAHİLİ İŞLEMLER")
        _firma("Dahili Kasa İşlemleri", is_active=False)
        db.session.commit()

        assert FirmaService.get_status_counts() == {
            "toplam_firma_sayisi": 3,
            "aktif_firma_sayisi": 1,
            "pasif_firma_sayisi": 2,
        }


def test_firmalar_index_renders_firma_status_counts(app, client):
    with app.app_context():
        _firma("Aktif Firma")
        _firma("Pasif Firma 1", is_active=False)
        _firma("Pasif Firma 2", is_active=False)
        db.session.commit()

        admin = User(username=f"firma_status_{uuid.uuid4().hex[:8]}", rol="admin")
        admin.set_password("pass123")
        db.session.add(admin)
        db.session.commit()
        _login_user(client, admin.id)

        response = client.get("/firmalar/")

        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert 'aria-label="Firma durum özetleri"' in html
        assert '<span class="label">Toplam</span>' in html
        assert '<span class="label">Aktif</span>' in html
        assert '<span class="label">Pasif</span>' in html
        assert '<span class="value">3 <small class="count-unit">ad</small></span>' in html
        assert '<span class="value">1 <small class="count-unit">ad</small></span>' in html
        assert '<span class="value">2 <small class="count-unit">ad</small></span>' in html
