from __future__ import annotations

import uuid
from decimal import Decimal

from app.auth.models import User
from app.auth.session_security import (
    SESSION_LAST_PING_KEY,
    SESSION_TOKEN_KEY,
    new_session_token,
    utc_now,
)
from app.cari.models import HizmetKaydi
from app.extensions import db
from app.filo.models import Ekipman
from app.firmalar.models import Firma
from app.kiralama.models import Kiralama
from app.nakliyeler.models import Nakliye
from app.teklifler.models import Teklif


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


def _make_admin():
    admin = User(username=f"teklif_admin_{uuid.uuid4().hex[:6]}", rol="admin")
    admin.set_password("pass123")
    db.session.add(admin)
    db.session.flush()
    return admin


def _teklif_post_data(**overrides):
    data = {
        "teklif_no": "TEK-2026-0001",
        "teklif_tarihi": "2026-05-03",
        "gecerlilik_tarihi": "",
        "durum": "taslak",
        "kdv_orani": "20",
        "notlar": "",
        "musteri_tipi": "aday",
        "firma_musteri_id": "0",
        "aday_firma_adi": f"Aday Musteri {uuid.uuid4().hex[:6]}",
        "aday_yetkili_adi": "",
        "aday_telefon": "",
        "aday_eposta": "",
        "aday_adres": "",
        "aday_not": "",
        "kalemler-0-id": "",
        "kalemler-0-ekipman_id": "0",
        "kalemler-0-makine_tipi": "Makasli Platform",
        "kalemler-0-marka_model": "12m",
        "kalemler-0-calisma_yuksekligi": "12",
        "kalemler-0-kaldirma_kapasitesi": "320",
        "kalemler-0-adet": "1",
        "kalemler-0-calisacagi_konum": "Istanbul Santiye",
        "kalemler-0-baslangic_tarihi": "2026-05-04",
        "kalemler-0-bitis_tarihi": "2026-05-06",
        "kalemler-0-fiyat_tipi": "gunluk",
        "kalemler-0-gunluk_fiyat": "1000",
        "kalemler-0-nakliye_yon": "tek_yon",
        "kalemler-0-nakliye_fiyati": "500",
        "kalemler-0-satir_notu": "",
    }
    data.update(overrides)
    return data


def test_teklif_menu_and_new_button_render(app, client):
    with app.app_context():
        admin = _make_admin()
        db.session.add(Ekipman(
            kod=f"TEK-FILO-{uuid.uuid4().hex[:6]}",
            yakit="Elektrik",
            tipi="Makasli Platform",
            marka="Genie",
            model="GS-3246",
            seri_no=f"SN-{uuid.uuid4().hex[:8]}",
            calisma_yuksekligi=12,
            kaldirma_kapasitesi=320,
            uretim_yili=2024,
            calisma_durumu="bosta",
        ))
        db.session.commit()
        admin_id = admin.id

    _login_user(client, admin_id)

    response = client.get("/teklifler/")
    assert response.status_code == 200
    assert b"/teklifler/ekle" in response.data
    assert "Teklifler".encode("utf-8") in response.data

    form_response = client.get("/teklifler/ekle")
    assert form_response.status_code == 200
    assert "Aday Firma Adı".encode("utf-8") in form_response.data
    assert "Makasli Platform".encode("utf-8") in form_response.data
    assert "GS-3246".encode("utf-8") in form_response.data


def test_aday_musteri_minimum_bilgiyle_teklif_olusturur_ve_operasyon_kaydi_uretmez(app, client):
    with app.app_context():
        admin = _make_admin()
        db.session.commit()
        admin_id = admin.id
        firma_count = Firma.query.count()
        kiralama_count = Kiralama.query.count()
        nakliye_count = Nakliye.query.count()
        hizmet_count = HizmetKaydi.query.count()

    _login_user(client, admin_id)

    response = client.post("/teklifler/ekle", data=_teklif_post_data(), follow_redirects=False)
    assert response.status_code == 302

    with app.app_context():
        teklif = Teklif.query.filter_by(teklif_no="TEK-2026-0001").one()
        assert teklif.aday_firma_adi
        assert teklif.firma_musteri_id is None
        assert teklif.kalemler[0].makine_tipi == "Makasli Platform"
        assert teklif.kalemler[0].satir_toplami == Decimal("3500.00")
        assert Firma.query.count() == firma_count
        assert Kiralama.query.count() == kiralama_count
        assert Nakliye.query.count() == nakliye_count
        assert HizmetKaydi.query.count() == hizmet_count

def test_teklif_arama_aday_yetkili_adini_kapsar(app, client):
    with app.app_context():
        admin = _make_admin()
        db.session.commit()
        admin_id = admin.id

    _login_user(client, admin_id)

    response = client.post(
        "/teklifler/ekle",
        data=_teklif_post_data(
            teklif_no="TEK-2026-YETKILI",
            aday_yetkili_adi="YetkiliArama",
        ),
        follow_redirects=False,
    )
    assert response.status_code == 302

    search_response = client.get("/teklifler/?q=YetkiliArama")
    assert search_response.status_code == 200
    assert b"TEK-2026-YETKILI" in search_response.data


def test_aylik_fiyat_30_gun_uzerinden_oransal_hesaplanir(app, client):
    with app.app_context():
        admin = _make_admin()
        db.session.commit()
        admin_id = admin.id

    _login_user(client, admin_id)

    response = client.post(
        "/teklifler/ekle",
        data=_teklif_post_data(
            teklif_no="TEK-2026-AYLIK",
            **{
                "kalemler-0-baslangic_tarihi": "2026-05-01",
                "kalemler-0-bitis_tarihi": "2026-05-15",
                "kalemler-0-fiyat_tipi": "aylik",
                "kalemler-0-gunluk_fiyat": "30000",
                "kalemler-0-nakliye_yon": "tek_yon",
                "kalemler-0-nakliye_fiyati": "1000",
            },
        ),
        follow_redirects=False,
    )
    assert response.status_code == 302

    with app.app_context():
        teklif = Teklif.query.filter_by(teklif_no="TEK-2026-AYLIK").one()
        assert teklif.kalemler[0].fiyat_tipi == "aylik"
        assert teklif.kalemler[0].satir_toplami == Decimal("16000.00")


def test_cift_yon_nakliye_satir_toplaminda_iki_kat_hesaplanir(app, client):
    with app.app_context():
        admin = _make_admin()
        db.session.commit()
        admin_id = admin.id

    _login_user(client, admin_id)

    response = client.post(
        "/teklifler/ekle",
        data=_teklif_post_data(
            teklif_no="TEK-2026-CIFTNAK",
            **{
                "kalemler-0-nakliye_yon": "cift_yon",
                "kalemler-0-nakliye_fiyati": "500",
            },
        ),
        follow_redirects=False,
    )
    assert response.status_code == 302

    with app.app_context():
        teklif = Teklif.query.filter_by(teklif_no="TEK-2026-CIFTNAK").one()
        assert teklif.kalemler[0].nakliye_yon == "cift_yon"
        assert teklif.kalemler[0].satir_toplami == Decimal("4000.00")


def test_aday_teklif_firmaya_aktarilirken_resmi_bilgiler_tamamlanir(app, client):
    with app.app_context():
        admin = _make_admin()
        teklif = Teklif(
            teklif_no="TEK-2026-0002",
            aday_firma_adi="Aktarilacak Aday",
            aday_telefon="05550000000",
            durum="kabul_edildi",
            kdv_orani=20,
        )
        db.session.add_all([admin, teklif])
        db.session.commit()
        admin_id = admin.id
        teklif_id = teklif.id

    _login_user(client, admin_id)

    response = client.post(
        f"/teklifler/firmaya-aktar/{teklif_id}",
        data={
            "firma_adi": "Aktarilacak Aday",
            "yetkili_adi": "Yetkili",
            "telefon": "05550000000",
            "eposta": "",
            "iletisim_bilgileri": "Adres bilgisi",
            "vergi_dairesi": "Test VD",
            "vergi_no": f"V{uuid.uuid4().hex[:10]}",
        },
        follow_redirects=False,
    )
    assert response.status_code == 302

    with app.app_context():
        teklif = Teklif.query.get(teklif_id)
        assert teklif.firma_musteri_id is not None
        assert teklif.firma_musteri.firma_adi == "Aktarilacak Aday"
