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
from app.cari.models import HizmetKaydi
from app.extensions import db
from app.filo.models import Ekipman
from app.firmalar.models import Firma
from app.kiralama.models import Kiralama
from app.kiralama.models import KiralamaKalemi
from app.nakliyeler.models import Nakliye
from app.teklifler.models import Teklif, TeklifKalemi


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


def test_teklif_harici_ekipman_ve_nakliye_tedarikcisi_kaydeder_cariyi_etkilemez(app, client):
    with app.app_context():
        admin = _make_admin()
        supplier = Firma(
            firma_adi=f'Teklif Tedarikci {uuid.uuid4().hex[:6]}',
            yetkili_adi='Yetkili',
            iletisim_bilgileri='Adres',
            vergi_dairesi='VD',
            vergi_no=f'TED{uuid.uuid4().hex[:10].upper()}',
            is_musteri=False,
            is_tedarikci=True,
            bakiye=Decimal('125.00'),
        )
        db.session.add(supplier)
        db.session.commit()
        admin_id = admin.id
        supplier_id = supplier.id
        firma_count = Firma.query.count()
        kiralama_count = Kiralama.query.count()
        nakliye_count = Nakliye.query.count()
        hizmet_count = HizmetKaydi.query.count()
        bakiye_before = supplier.bakiye

    _login_user(client, admin_id)
    response = client.post(
        '/teklifler/ekle',
        data=_teklif_post_data(
            teklif_no='TEK-2026-HARICI',
            **{
                'kalemler-0-is_dis_tedarik_ekipman': 'y',
                'kalemler-0-ekipman_id': '0',
                'kalemler-0-harici_ekipman_tedarikci_id': str(supplier_id),
                'kalemler-0-harici_ekipman_seri_no': 'HARICI-SN-01',
                'kalemler-0-is_harici_nakliye': 'y',
                'kalemler-0-nakliye_tedarikci_id': str(supplier_id),
            },
        ),
        follow_redirects=False,
    )
    assert response.status_code == 302
    detail_response = client.get(response.headers['Location'])
    assert detail_response.status_code == 200
    assert 'HARICI-SN-01' in detail_response.data.decode('utf-8')

    with app.app_context():
        teklif = Teklif.query.filter_by(teklif_no='TEK-2026-HARICI').one()
        kalem = teklif.kalemler[0]
        supplier = db.session.get(Firma, supplier_id)
        assert kalem.is_dis_tedarik_ekipman is True
        assert kalem.harici_ekipman_tedarikci_id == supplier_id
        assert kalem.harici_ekipman_seri_no == 'HARICI-SN-01'
        assert kalem.is_harici_nakliye is True
        assert kalem.nakliye_tedarikci_id == supplier_id
        assert Firma.query.count() == firma_count
        assert Kiralama.query.count() == kiralama_count
        assert Nakliye.query.count() == nakliye_count
        assert HizmetKaydi.query.count() == hizmet_count
        assert supplier.bakiye == bakiye_before


def test_teklif_formu_tum_makineleri_ve_kirada_makinenin_musaitlik_planini_gosterir(app, client):
    with app.app_context():
        admin = _make_admin()
        musteri = Firma(
            firma_adi=f'Teklif Musteri {uuid.uuid4().hex[:6]}',
            yetkili_adi='Yetkili',
            iletisim_bilgileri='Adres',
            vergi_dairesi='VD',
            vergi_no=f'MUS{uuid.uuid4().hex[:10].upper()}',
            is_musteri=True,
        )
        kirada = Ekipman(
            kod=f'KIRADA-{uuid.uuid4().hex[:6]}', yakit='Elektrik', tipi='Platform', marka='Marka', model='Kirada',
            seri_no=f'SN-{uuid.uuid4().hex[:8]}', calisma_yuksekligi=12, kaldirma_kapasitesi=300,
            uretim_yili=2024, calisma_durumu='kirada',
        )
        serviste = Ekipman(
            kod=f'SERVIS-{uuid.uuid4().hex[:6]}', yakit='Dizel', tipi='Forklift', marka='Marka', model='Serviste',
            seri_no=f'SN-{uuid.uuid4().hex[:8]}', calisma_yuksekligi=5, kaldirma_kapasitesi=1000,
            uretim_yili=2023, calisma_durumu='serviste',
        )
        db.session.add_all([musteri, kirada, serviste])
        db.session.flush()
        rental = Kiralama(
            kiralama_form_no=f'KIR-TEK-{uuid.uuid4().hex[:6]}',
            firma_musteri_id=musteri.id,
            kiralama_olusturma_tarihi=date(2026, 6, 1),
        )
        db.session.add(rental)
        db.session.flush()
        db.session.add(KiralamaKalemi(
            kiralama_id=rental.id,
            ekipman_id=kirada.id,
            kiralama_baslangici=date(2026, 6, 1),
            kiralama_bitis=date(2026, 6, 14),
            kiralama_brm_fiyat=Decimal('1000.00'),
            is_active=True,
            sonlandirildi=False,
        ))
        db.session.commit()
        admin_id = admin.id
        kirada_kod = kirada.kod
        serviste_kod = serviste.kod

    _login_user(client, admin_id)
    response = client.get('/teklifler/ekle')
    assert response.status_code == 200
    html = response.data.decode('utf-8')
    assert kirada_kod in html
    assert 'Kirada - Müsaitlik planı: 14.06.2026' in html
    assert serviste_kod in html
    assert 'Serviste - Müsaitlik planı: belirtilmemiş' in html
    assert 'js-harici-ekipman-tedarikci' in html


def test_teklif_duzenle_mevcut_pasif_silinmis_ekipman_ve_tedarikciyi_secenekte_tutar(app, client):
    with app.app_context():
        admin = _make_admin()
        supplier = Firma(
            firma_adi=f'Silinmis Tedarikci {uuid.uuid4().hex[:6]}',
            yetkili_adi='Yetkili',
            iletisim_bilgileri='Adres',
            vergi_dairesi='VD',
            vergi_no=f'SIL{uuid.uuid4().hex[:10].upper()}',
            is_musteri=False,
            is_tedarikci=True,
            is_active=False,
            is_deleted=True,
        )
        machine = Ekipman(
            kod=f'PASIF-{uuid.uuid4().hex[:6]}', yakit='Dizel', tipi='Platform', marka='Marka', model='Arsiv',
            seri_no=f'SN-{uuid.uuid4().hex[:8]}', calisma_yuksekligi=10, kaldirma_kapasitesi=250,
            uretim_yili=2022, calisma_durumu='iade_edildi', is_active=False, is_deleted=True,
        )
        teklif = Teklif(teklif_no=f'TEK-2026-PASIF-{uuid.uuid4().hex[:4]}', aday_firma_adi='Aday', durum='taslak', kdv_orani=20)
        db.session.add_all([supplier, machine, teklif])
        db.session.flush()
        db.session.add_all([
            TeklifKalemi(
                teklif_id=teklif.id,
                ekipman_id=machine.id,
                makine_tipi='Platform',
                marka_model='Arsiv',
                gunluk_fiyat=Decimal('100.00'),
                adet=1,
            ),
            TeklifKalemi(
                teklif_id=teklif.id,
                is_dis_tedarik_ekipman=True,
                harici_ekipman_tedarikci_id=supplier.id,
                harici_ekipman_seri_no='SIL-SN-01',
                makine_tipi='Forklift',
                marka_model='Arsiv Model',
                gunluk_fiyat=Decimal('100.00'),
                adet=1,
            ),
        ])
        db.session.commit()
        admin_id = admin.id
        teklif_id = teklif.id
        supplier_name = supplier.firma_adi
        machine_code = machine.kod

    _login_user(client, admin_id)
    response = client.get(f'/teklifler/duzelt/{teklif_id}')
    assert response.status_code == 200
    html = response.data.decode('utf-8')
    assert machine_code in html
    assert '(İade Edildi - Müsaitlik planı: belirtilmemiş) (Silinmiş)' in html
    assert f'{supplier_name} (Silinmiş)' in html
    assert 'Serviste - Müsaitlik planı' not in html


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
