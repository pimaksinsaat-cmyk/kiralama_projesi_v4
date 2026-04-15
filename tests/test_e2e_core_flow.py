"""
E2E smoke testi: temel is akislarinin endpoint seviyesinde dogrulanmasi.

Senaryo:
1) Admin kullanici + test verileri olusturulur.
2) Kullanici oturumu test_client session ile acilir.
3) /filo/index sayfasi render edilir ve ekipman kodu gorulur.
4) /subeler/<id>/makineler JSON endpoint'i dogrulanir.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from app.auth.models import User
from app.extensions import db
from app.filo.models import Ekipman
from app.firmalar.models import Firma
from app.kiralama.models import Kiralama, KiralamaKalemi
from app.subeler.models import Sube


def _unique_vergi_no() -> str:
    return f"T{uuid.uuid4().hex[:10].upper()}"


def _unique_kod() -> str:
    return f"E2E-{uuid.uuid4().hex[:8].upper()}"


def _login_user(client, user_id: int) -> None:
    # Flask-Login session alanlari.
    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True


def test_e2e_filo_ve_sube_makineleri(app, client):
    with app.app_context():
        admin = User(username=f"e2e_admin_{uuid.uuid4().hex[:6]}", rol="admin")
        admin.set_password("pass123")
        db.session.add(admin)
        db.session.flush()

        sube = Sube(isim="E2E Sube", adres="E2E Adres", yetkili_kisi="E2E Yetkili", telefon="0212-0000000")
        db.session.add(sube)
        db.session.flush()

        musteri = Firma(
            firma_adi=f"E2E Musteri {uuid.uuid4().hex[:4]}",
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

        ekipman_kod = _unique_kod()
        ekipman = Ekipman(
            kod=ekipman_kod,
            yakit="Elektrik",
            tipi="MAKAS",
            marka="E2E Marka",
            model="E2E Model",
            seri_no=f"SN-{uuid.uuid4().hex[:8]}",
            calisma_yuksekligi=10,
            kaldirma_kapasitesi=2000,
            uretim_yili=2023,
            calisma_durumu="bosta",
            sube_id=sube.id,
        )
        db.session.add(ekipman)
        db.session.flush()

        kiralama = Kiralama(
            kiralama_form_no=f"PF-E2E-{uuid.uuid4().hex[:6]}",
            firma_musteri_id=musteri.id,
            kdv_orani=20,
        )
        db.session.add(kiralama)
        db.session.flush()

        kalem = KiralamaKalemi(
            kiralama_id=kiralama.id,
            ekipman_id=ekipman.id,
            kiralama_baslangici=date(2026, 4, 14),
            kiralama_bitis=date(2026, 4, 30),
            kiralama_brm_fiyat=Decimal("1000.00"),
            sonlandirildi=False,
            is_active=True,
        )
        db.session.add(kalem)
        db.session.commit()
        admin_id = admin.id
        sube_id = sube.id
        ekipman_id = ekipman.id

    _login_user(client, admin_id)

    filo_response = client.get("/filo/index")
    assert filo_response.status_code == 200
    assert ekipman_kod.encode("utf-8") in filo_response.data

    sube_response = client.get(f"/subeler/{sube_id}/makineler")
    assert sube_response.status_code == 200
    payload = sube_response.get_json()
    assert payload is not None
    assert payload["sube_id"] == sube_id
    assert payload["bosta_sayisi"] >= 1
    assert any(item["kod"] == ekipman_kod for item in payload["bosta"])

    with app.app_context():
        db_ekipman = Ekipman.query.filter_by(id=ekipman_id).first()
        assert db_ekipman is not None
        assert db_ekipman.calisma_durumu == "bosta"
