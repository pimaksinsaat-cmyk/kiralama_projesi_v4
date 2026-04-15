"""
Kiralama modulu icin E2E testi (hakediş disi).

Akis:
1) Test verisi olustur (admin, sube, musteri, ekipman, kiralama, kalem)
2) Session uzerinden giris simule et
3) Kiralama liste ekranini dogrula
4) Ekipman filtre API sonucunu dogrula
5) Kiralama kalemi bitis tarihini endpoint uzerinden guncelle ve DB'de dogrula
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
    return f"KRL-{uuid.uuid4().hex[:8].upper()}"


def _login_user(client, user_id: int) -> None:
    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True


def test_e2e_kiralama_liste_filtre_ve_tarih_guncelle(app, client):
    with app.app_context():
        admin = User(username=f"kiralama_admin_{uuid.uuid4().hex[:6]}", rol="admin")
        admin.set_password("pass123")
        db.session.add(admin)
        db.session.flush()

        sube = Sube(
            isim="Kiralama E2E Sube",
            adres="E2E Adres",
            yetkili_kisi="E2E Yetkili",
            telefon="0212-1111111",
        )
        db.session.add(sube)
        db.session.flush()

        musteri = Firma(
            firma_adi=f"Kiralama E2E Musteri {uuid.uuid4().hex[:4]}",
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
            calisma_yuksekligi=12,
            kaldirma_kapasitesi=2500,
            uretim_yili=2024,
            calisma_durumu="bosta",
            sube_id=sube.id,
        )
        db.session.add(ekipman)
        db.session.flush()

        kiralama_form_no = f"PF-E2E-{uuid.uuid4().hex[:6]}"
        kiralama = Kiralama(
            kiralama_form_no=kiralama_form_no,
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
        kalem_id = kalem.id

    _login_user(client, admin_id)

    list_response = client.get("/kiralama/index")
    assert list_response.status_code == 200
    assert kiralama_form_no.encode("utf-8") in list_response.data

    filter_response = client.get(f"/kiralama/api/ekipman-filtrele?sube_id={sube_id}&tip=MAKAS")
    assert filter_response.status_code == 200
    payload = filter_response.get_json()
    assert payload is not None
    assert payload["success"] is True
    assert payload["count"] >= 1
    assert any(ekipman_kod in item["label"] for item in payload["data"])

    new_end_date = "2026-05-10"
    update_response = client.post(
        "/kiralama/kalem/tarih_guncelle",
        data={"kalem_id": kalem_id, "yeni_bitis_tarihi": new_end_date},
        follow_redirects=False,
    )
    assert update_response.status_code in (302, 303)

    with app.app_context():
        updated_kalem = db.session.get(KiralamaKalemi, kalem_id)
        assert updated_kalem is not None
        assert updated_kalem.kiralama_bitis == date(2026, 5, 10)
