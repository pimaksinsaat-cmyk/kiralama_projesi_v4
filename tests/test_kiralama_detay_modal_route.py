"""Kiralama detay modal AJAX endpoint regresyon testleri."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from app.auth.models import User
from app.auth.session_security import (
    SESSION_LAST_PING_KEY,
    SESSION_TOKEN_KEY,
    new_session_token,
    utc_now,
)
from app.extensions import db
from app.filo.models import Ekipman
from app.firmalar.models import Firma
from app.kiralama.models import Kiralama, KiralamaKalemi
from app.subeler.models import Sube


def _unique_vergi_no() -> str:
    return f"T{uuid.uuid4().hex[:10].upper()}"


def _unique_kod() -> str:
    return f"KRL-{uuid.uuid4().hex[:8].upper()}"


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


def _seed_kiralama(*, is_deleted: bool = False) -> tuple[int, int, str]:
    admin = User(username=f"detay_admin_{uuid.uuid4().hex[:6]}", rol="admin")
    admin.set_password("pass123")
    db.session.add(admin)
    db.session.flush()

    sube = Sube(
        isim="Detay Modal Sube",
        adres="Test Adres",
        yetkili_kisi="Test Yetkili",
        telefon="0212-2222222",
    )
    db.session.add(sube)
    db.session.flush()

    musteri = Firma(
        firma_adi=f"Detay Modal Musteri {uuid.uuid4().hex[:4]}",
        yetkili_adi="Yetkili",
        iletisim_bilgileri="Adres",
        vergi_dairesi="Istanbul VD",
        vergi_no=_unique_vergi_no(),
        is_musteri=True,
        is_tedarikci=False,
        bakiye=Decimal("0"),
    )
    db.session.add(musteri)
    db.session.flush()

    ekipman = Ekipman(
        kod=_unique_kod(),
        yakit="Elektrik",
        tipi="MAKAS",
        marka="Test Marka",
        model="Test Model",
        seri_no=f"SN-{uuid.uuid4().hex[:8]}",
        calisma_yuksekligi=12,
        kaldirma_kapasitesi=2500,
        uretim_yili=2024,
        calisma_durumu="bosta",
        sube_id=sube.id,
    )
    db.session.add(ekipman)
    db.session.flush()

    kiralama_form_no = f"PF-DETAY-{uuid.uuid4().hex[:6]}"
    kiralama = Kiralama(
        kiralama_form_no=kiralama_form_no,
        firma_musteri_id=musteri.id,
        kdv_orani=20,
        is_deleted=is_deleted,
    )
    db.session.add(kiralama)
    db.session.flush()

    kalem = KiralamaKalemi(
        kiralama_id=kiralama.id,
        ekipman_id=ekipman.id,
        kiralama_baslangici=date(2026, 4, 1),
        kiralama_bitis=date(2026, 4, 30),
        kiralama_brm_fiyat=Decimal("1000.00"),
        sonlandirildi=False,
        is_active=True,
    )
    db.session.add(kalem)
    db.session.commit()

    return admin.id, kiralama.id, kiralama_form_no


def test_detay_modal_returns_html_for_active_kiralama(app, client):
    with app.app_context():
        admin_id, kiralama_id, kiralama_form_no = _seed_kiralama()

    _login_user(client, admin_id)

    response = client.get(f"/kiralama/detay/{kiralama_id}")

    assert response.status_code == 200
    assert kiralama_form_no.encode("utf-8") in response.data
    assert b"Kalemler" in response.data


def test_detay_modal_returns_404_for_deleted_kiralama(app, client):
    with app.app_context():
        admin_id, kiralama_id, _ = _seed_kiralama(is_deleted=True)

    _login_user(client, admin_id)

    response = client.get(f"/kiralama/detay/{kiralama_id}")

    assert response.status_code == 404
