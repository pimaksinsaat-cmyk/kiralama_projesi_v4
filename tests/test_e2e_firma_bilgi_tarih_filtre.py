"""
E2E (HTTP): /firmalar/bilgi tarih süzgeci + dönem modu + devre dışı flag.
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


def _uniq_vergi() -> str:
    return f"TF{uuid.uuid4().hex[:10].upper()}"


def _uniq_kod() -> str:
    return f"TDF-{uuid.uuid4().hex[:8].upper()}"


def _login(client, user_id: int) -> None:
    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True


def _setup_data(app):
    """Dönemi filtrelebilecek kısa süreli kiralama ile firma oluşturur."""
    admin = User(username=f"bilgi_e2e_{uuid.uuid4().hex[:6]}", rol="admin")
    admin.set_password("pass123")
    db.session.add(admin)
    db.session.flush()

    sube = Sube(isim="TDF Sube", adres="Adr", yetkili_kisi="Y", telefon="0212-1111111")
    db.session.add(sube)
    db.session.flush()

    musteri = Firma(
        firma_adi=f"TDF Müşteri {uuid.uuid4().hex[:4]}",
        yetkili_adi="Y",
        iletisim_bilgileri="Adr",
        vergi_dairesi="İstanbul VD",
        vergi_no=_uniq_vergi(),
        is_musteri=True,
        is_tedarikci=False,
        bakiye=Decimal("0"),
        cari_borc_kdvli=Decimal("0"),
        cari_alacak_kdvli=Decimal("0"),
        cari_bakiye_kdvli=Decimal("0"),
    )
    db.session.add(musteri)
    db.session.flush()

    ekipman = Ekipman(
        kod=_uniq_kod(),
        yakit="Elektrik",
        tipi="MAKAS",
        marka="TF",
        model="M1",
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
        kiralama_form_no=f"TDF-{uuid.uuid4().hex[:6]}",
        firma_musteri_id=musteri.id,
        kdv_orani=20,
        kiralama_olusturma_tarihi=date(2026, 4, 1),
    )
    db.session.add(kiralama)
    db.session.flush()

    kalem = KiralamaKalemi(
        kiralama_id=kiralama.id,
        ekipman_id=ekipman.id,
        kiralama_baslangici=date(2026, 4, 10),
        kiralama_bitis=date(2026, 4, 30),
        kiralama_brm_fiyat=Decimal("100.00"),
        sonlandirildi=True,
        is_active=True,
    )
    db.session.add(kalem)
    db.session.commit()
    return admin.id, musteri.id


def test_bilgi_tarih_olmadan_tam_ekstre_basliklari(app, client):
    with app.app_context():
        admin_id, firma_id = _setup_data(app)

    _login(client, admin_id)
    r = client.get(f"/firmalar/bilgi/{firma_id}", follow_redirects=True)
    assert r.status_code == 200
    body = r.data.decode("utf-8", errors="replace")
    assert "Dönem Borç" not in body
    assert "Toplam Borç" in body


def test_bilgi_iki_tarih_parametresi_donem_modu_ve_filtre_disı(app, client):
    with app.app_context():
        admin_id, firma_id = _setup_data(app)

    _login(client, admin_id)
    r = client.get(
        f"/firmalar/bilgi/{firma_id}",
        query_string={
            "tab": "cari",
            "start_date": "2026-04-15",
            "end_date": "2026-04-25",
        },
        follow_redirects=True,
    )
    assert r.status_code == 200
    body = r.data.decode("utf-8", errors="replace")
    assert "Dönem Borç" in body
    assert "Dönem Alacak" in body
    assert "Dönem Bakiyesi" in body or "Dönem Bakiye" in body
    assert "Filtre dışı" in body


def test_bilgi_yazdir_aynı_tarih_parametleri_200(app, client):
    with app.app_context():
        admin_id, firma_id = _setup_data(app)

    _login(client, admin_id)
    r = client.get(
        f"/firmalar/bilgi/{firma_id}/yazdir",
        query_string={
            "tab": "cari",
            "start_date": "2026-04-15",
            "end_date": "2026-04-25",
        },
        follow_redirects=True,
    )
    assert r.status_code == 200
    body = r.data.decode("utf-8", errors="replace")
    assert "15.04.2026" in body and "25.04.2026" in body


def test_bilgi_cari_flag_kapalı_dönem_başlığı_yok(app, client):
    app.config["CARI_DONEM_FILTRESI_ENABLED"] = False
    with app.app_context():
        admin_id, firma_id = _setup_data(app)

    _login(client, admin_id)
    r = client.get(
        f"/firmalar/bilgi/{firma_id}",
        query_string={
            "tab": "cari",
            "start_date": "2026-04-15",
            "end_date": "2026-04-25",
        },
        follow_redirects=True,
    )
    assert r.status_code == 200
    assert "Dönem Borç".encode("utf-8") not in r.data
