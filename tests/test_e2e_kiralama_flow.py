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
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from app.auth.models import User
from app.auth.session_security import (
    SESSION_LAST_PING_KEY,
    SESSION_TOKEN_KEY,
    new_session_token,
    utc_now,
)
from app.extensions import db
from app.cari.models import HizmetKaydi
from app.filo.models import Ekipman
from app.firmalar.models import Firma
from app.kiralama.models import Kiralama, KiralamaKalemi
from app.nakliyeler.models import Nakliye
from app.services.kiralama_services import KiralamaService
from app.services.base import ValidationError
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


def test_kiralama_sil_requires_password(app, client):
    with app.app_context():
        admin = User(username=f"kiralama_del_{uuid.uuid4().hex[:6]}", rol="admin")
        admin.set_password("pass123")
        db.session.add(admin)
        db.session.flush()

        musteri = Firma(
            firma_adi=f"Kiralama Sil E2E {uuid.uuid4().hex[:4]}",
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

        kiralama = Kiralama(
            kiralama_form_no=f"PF-DEL-{uuid.uuid4().hex[:6]}",
            firma_musteri_id=musteri.id,
            kdv_orani=20,
        )
        db.session.add(kiralama)
        db.session.commit()

        admin_id = admin.id
        kiralama_id = kiralama.id

    _login_user(client, admin_id)

    json_headers = {"X-Requested-With": "XMLHttpRequest", "Accept": "application/json"}

    missing_response = client.post(
        f"/kiralama/sil/{kiralama_id}?format=json",
        headers=json_headers,
    )
    assert missing_response.status_code == 400
    missing_payload = missing_response.get_json()
    assert missing_payload["ok"] is False
    assert "şifrenizi doğrulamanız gerekir" in missing_payload["message"]

    with app.app_context():
        assert db.session.get(Kiralama, kiralama_id) is not None

    wrong_response = client.post(
        f"/kiralama/sil/{kiralama_id}?format=json",
        data={"delete_confirm_password": "wrong"},
        headers=json_headers,
    )
    assert wrong_response.status_code == 400
    wrong_payload = wrong_response.get_json()
    assert wrong_payload["ok"] is False
    assert "şifrenizi doğrulamanız gerekir" in wrong_payload["message"]

    with app.app_context():
        assert db.session.get(Kiralama, kiralama_id) is not None

    ok_response = client.post(
        f"/kiralama/sil/{kiralama_id}?format=json",
        data={"delete_confirm_password": "pass123"},
        headers=json_headers,
    )
    assert ok_response.status_code == 200
    ok_payload = ok_response.get_json()
    assert ok_payload["ok"] is True

    with app.app_context():
        deleted = db.session.get(Kiralama, kiralama_id)
        assert deleted is not None
        assert deleted.is_deleted is True


def test_kiralama_sil_ve_geri_al_json(app, client):
    with app.app_context():
        admin = User(username=f"kiralama_undo_{uuid.uuid4().hex[:6]}", rol="admin")
        admin.set_password("pass123")
        db.session.add(admin)
        db.session.flush()

        musteri = Firma(
            firma_adi=f"Kiralama Undo E2E {uuid.uuid4().hex[:4]}",
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

        form_no = f"PF-UNDO-{uuid.uuid4().hex[:6]}"
        kiralama = Kiralama(
            kiralama_form_no=form_no,
            firma_musteri_id=musteri.id,
            kdv_orani=20,
        )
        db.session.add(kiralama)
        db.session.commit()

        admin_id = admin.id
        kiralama_id = kiralama.id

    _login_user(client, admin_id)

    delete_response = client.post(
        f"/kiralama/sil/{kiralama_id}?format=json",
        data={"delete_confirm_password": "pass123"},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert delete_response.status_code == 200
    delete_payload = delete_response.get_json()
    assert delete_payload["ok"] is True
    assert delete_payload["form_no"] == form_no
    assert delete_payload["undo_seconds"] == KiralamaService.UNDO_WINDOW_SECONDS

    with app.app_context():
        soft_deleted = db.session.get(Kiralama, kiralama_id)
        assert soft_deleted is not None
        assert soft_deleted.is_deleted is True

    restore_response = client.post(
        f"/kiralama/geri-al/{kiralama_id}?format=json",
        headers={
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json",
        },
    )
    assert restore_response.status_code == 200
    restore_payload = restore_response.get_json()
    assert restore_payload["ok"] is True
    assert restore_payload["form_no"] == form_no

    with app.app_context():
        restored = db.session.get(Kiralama, kiralama_id)
        assert restored is not None
        assert restored.is_deleted is False
        assert restored.is_active is True

    list_response = client.get("/kiralama/")
    assert list_response.status_code == 200
    assert form_no.encode("utf-8") in list_response.data


def test_kiralama_restore_expired_window(app):
    with app.app_context():
        musteri = Firma(
            firma_adi=f"Kiralama Expire {uuid.uuid4().hex[:4]}",
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

        kiralama = Kiralama(
            kiralama_form_no=f"PF-EXP-{uuid.uuid4().hex[:6]}",
            firma_musteri_id=musteri.id,
            kdv_orani=20,
            is_deleted=True,
            is_active=False,
            deleted_at=datetime.now(timezone.utc) - timedelta(seconds=120),
        )
        db.session.add(kiralama)
        db.session.commit()
        kiralama_id = kiralama.id

        snapshot = {
            "kiralama_id": kiralama_id,
            "actor_id": None,
            "created_at": (
                datetime.now(timezone.utc) - timedelta(seconds=180)
            ).isoformat(),
            "expires_at": (
                datetime.now(timezone.utc) - timedelta(seconds=60)
            ).isoformat(),
            "kiralama": {
                "is_deleted": False,
                "is_active": True,
                "deleted_at": None,
                "deleted_by_id": None,
            },
            "kalemler": {},
            "nakliyeler": {},
            "hizmetler": {},
            "ekipmanlar": {},
        }

        try:
            KiralamaService.restore_with_relations(kiralama_id, snapshot=snapshot)
            assert False, "Expected ValidationError for expired undo window"
        except ValidationError as exc:
            assert "Geri alma suresi doldu" in str(exc)


def test_kiralama_delete_csrf_required_when_enabled(app, client):
    with app.app_context():
        admin = User(username=f"kiralama_csrf_{uuid.uuid4().hex[:6]}", rol="admin")
        admin.set_password("pass123")
        db.session.add(admin)
        db.session.flush()

        musteri = Firma(
            firma_adi=f"Kiralama CSRF {uuid.uuid4().hex[:4]}",
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

        kiralama = Kiralama(
            kiralama_form_no=f"PF-CSRF-{uuid.uuid4().hex[:6]}",
            firma_musteri_id=musteri.id,
            kdv_orani=20,
        )
        db.session.add(kiralama)
        db.session.commit()
        admin_id = admin.id
        kiralama_id = kiralama.id

    _login_user(client, admin_id)
    app.config["WTF_CSRF_ENABLED"] = True
    try:
        response = client.post(
            f"/kiralama/sil/{kiralama_id}?format=json",
            data={"delete_confirm_password": "pass123"},
            headers={"X-Requested-With": "XMLHttpRequest", "Accept": "application/json"},
        )
        assert response.status_code == 400
        payload = response.get_json()
        assert payload["ok"] is False
        assert "G" in payload["message"]
    finally:
        app.config["WTF_CSRF_ENABLED"] = False


def test_kiralama_delete_restore_syncs_nakliye_hizmet_and_firma_balances(app):
    with app.app_context():
        musteri = Firma(
            firma_adi=f"Kiralama Cari Musteri {uuid.uuid4().hex[:4]}",
            yetkili_adi="Yetkili",
            iletisim_bilgileri="Adres",
            vergi_dairesi="Istanbul VD",
            vergi_no=_unique_vergi_no(),
            is_musteri=True,
            is_tedarikci=False,
            bakiye=Decimal("0"),
        )
        taseron = Firma(
            firma_adi=f"Kiralama Cari Taseron {uuid.uuid4().hex[:4]}",
            yetkili_adi="Yetkili",
            iletisim_bilgileri="Adres",
            vergi_dairesi="Istanbul VD",
            vergi_no=_unique_vergi_no(),
            is_musteri=False,
            is_tedarikci=True,
            bakiye=Decimal("0"),
        )
        db.session.add_all([musteri, taseron])
        db.session.flush()

        form_no = f"PF-CARI-{uuid.uuid4().hex[:6]}"
        kiralama = Kiralama(
            kiralama_form_no=form_no,
            firma_musteri_id=musteri.id,
            kdv_orani=20,
        )
        db.session.add(kiralama)
        db.session.flush()

        kalem = KiralamaKalemi(
            kiralama_id=kiralama.id,
            kiralama_baslangici=date(2026, 5, 1),
            kiralama_bitis=date(2026, 5, 5),
            kiralama_brm_fiyat=Decimal("100.00"),
            sonlandirildi=False,
            is_active=True,
        )
        db.session.add(kalem)
        db.session.flush()

        nakliye = Nakliye(
            kiralama_id=kiralama.id,
            firma_id=musteri.id,
            tarih=date(2026, 5, 1),
            islem_tarihi=date(2026, 5, 1),
            guzergah="Test guzergah",
            tutar=Decimal("50.00"),
            toplam_tutar=Decimal("50.00"),
            kdv_orani=0,
            nakliye_tipi="taseron",
            taseron_firma_id=taseron.id,
            taseron_maliyet=Decimal("30.00"),
            taseron_kdv_orani=0,
        )
        db.session.add(nakliye)
        db.session.flush()

        bekleyen = HizmetKaydi(
            firma_id=musteri.id,
            tarih=date(2026, 5, 1),
            islem_tarihi=date(2026, 5, 1),
            tutar=Decimal("100.00"),
            yon="giden",
            fatura_no=form_no,
            ozel_id=kiralama.id,
            aciklama="Kiralama Bekleyen Bakiye",
            kdv_orani=0,
        )
        nakliye_musteri = HizmetKaydi(
            firma_id=musteri.id,
            nakliye_id=nakliye.id,
            tarih=date(2026, 5, 1),
            islem_tarihi=date(2026, 5, 1),
            tutar=Decimal("50.00"),
            yon="giden",
            aciklama="Nakliye Hizmeti",
            kdv_orani=0,
        )
        nakliye_taseron = HizmetKaydi(
            firma_id=taseron.id,
            nakliye_id=nakliye.id,
            tarih=date(2026, 5, 1),
            islem_tarihi=date(2026, 5, 1),
            tutar=Decimal("30.00"),
            yon="gelen",
            aciklama="Nakliye Taseron Gideri",
            kdv_orani=0,
            nakliye_alis_kdv=0,
        )
        db.session.add_all([bekleyen, nakliye_musteri, nakliye_taseron])
        db.session.commit()

        snapshot = KiralamaService.delete_with_relations(kiralama.id)

        db.session.refresh(musteri)
        db.session.refresh(taseron)
        assert db.session.get(HizmetKaydi, bekleyen.id).is_deleted is True
        assert db.session.get(HizmetKaydi, nakliye_musteri.id).is_deleted is True
        assert db.session.get(HizmetKaydi, nakliye_taseron.id).is_deleted is True
        assert db.session.get(Nakliye, nakliye.id).is_active is False
        assert musteri.bakiye == Decimal("0.00")
        assert taseron.bakiye == Decimal("0.00")

        KiralamaService.restore_with_relations(kiralama.id, snapshot=snapshot)

        db.session.refresh(musteri)
        db.session.refresh(taseron)
        assert db.session.get(HizmetKaydi, bekleyen.id).is_deleted is False
        assert db.session.get(HizmetKaydi, nakliye_musteri.id).is_deleted is False
        assert db.session.get(HizmetKaydi, nakliye_taseron.id).is_deleted is False
        assert db.session.get(Nakliye, nakliye.id).is_active is True
        assert musteri.bakiye == musteri.bakiye_ozeti["net_bakiye"]
        assert taseron.bakiye == taseron.bakiye_ozeti["net_bakiye"]
        assert musteri.bakiye > Decimal("0.00")
        assert taseron.bakiye == Decimal("-30.00")


def test_kiralama_delete_restore_syncs_supplier_taseron_vade(app):
    with app.app_context():
        musteri = Firma(
            firma_adi=f"Kiralama Cari Musteri Vade {uuid.uuid4().hex[:4]}",
            yetkili_adi="Yetkili",
            iletisim_bilgileri="Adres",
            vergi_dairesi="Istanbul VD",
            vergi_no=_unique_vergi_no(),
            is_musteri=True,
            is_tedarikci=False,
            bakiye=Decimal("0"),
        )
        tedarikci = Firma(
            firma_adi=f"Kiralama Cari Tedarikci {uuid.uuid4().hex[:4]}",
            yetkili_adi="Yetkili",
            iletisim_bilgileri="Adres",
            vergi_dairesi="Istanbul VD",
            vergi_no=_unique_vergi_no(),
            is_musteri=False,
            is_tedarikci=True,
            bakiye=Decimal("0"),
        )
        taseron = Firma(
            firma_adi=f"Kiralama Cari Taseron Vade {uuid.uuid4().hex[:4]}",
            yetkili_adi="Yetkili",
            iletisim_bilgileri="Adres",
            vergi_dairesi="Istanbul VD",
            vergi_no=_unique_vergi_no(),
            is_musteri=False,
            is_tedarikci=True,
            bakiye=Decimal("0"),
        )
        db.session.add_all([musteri, tedarikci, taseron])
        db.session.flush()

        form_no = f"PF-CARI-VADE-{uuid.uuid4().hex[:6]}"
        kiralama = Kiralama(
            kiralama_form_no=form_no,
            firma_musteri_id=musteri.id,
            kdv_orani=20,
        )
        db.session.add(kiralama)
        db.session.flush()

        kalem = KiralamaKalemi(
            kiralama_id=kiralama.id,
            kiralama_baslangici=date(2026, 5, 1),
            kiralama_bitis=date(2026, 5, 5),
            kiralama_brm_fiyat=Decimal("100.00"),
            sonlandirildi=False,
            is_active=True,
        )
        db.session.add(kalem)
        db.session.flush()

        nakliye = Nakliye(
            kiralama_id=kiralama.id,
            firma_id=musteri.id,
            tarih=date(2026, 5, 1),
            islem_tarihi=date(2026, 5, 1),
            guzergah="Tedarikçi nakliye",
            tutar=Decimal("120.00"),
            toplam_tutar=Decimal("120.00"),
            kdv_orani=0,
            nakliye_tipi="taseron",
            taseron_firma_id=taseron.id,
            taseron_maliyet=Decimal("90.00"),
            taseron_kdv_orani=0,
            cari_islendi_mi=True,
        )
        db.session.add(nakliye)
        db.session.flush()

        tedarikci_hizmet = HizmetKaydi(
            firma_id=tedarikci.id,
            tarih=date(2026, 5, 1),
            islem_tarihi=date(2026, 5, 1),
            tutar=Decimal("85.00"),
            yon="gelen",
            fatura_no=form_no,
            ozel_id=kiralama.id,
            aciklama="Tedarikçi kira bedeli",
            kdv_orani=0,
            vade_tarihi=date(2026, 6, 1),
        )
        taseron_hizmet = HizmetKaydi(
            firma_id=taseron.id,
            nakliye_id=nakliye.id,
            tarih=date(2026, 5, 1),
            islem_tarihi=date(2026, 5, 1),
            tutar=Decimal("90.00"),
            yon="gelen",
            aciklama="Taseron gideri",
            kdv_orani=0,
            vade_tarihi=date(2026, 6, 1),
            nakliye_alis_kdv=0,
        )
        db.session.add_all([tedarikci_hizmet, taseron_hizmet])
        db.session.commit()

        snapshot = KiralamaService.delete_with_relations(kiralama.id)

        db.session.refresh(tedarikci)
        db.session.refresh(taseron)
        assert db.session.get(HizmetKaydi, tedarikci_hizmet.id).is_deleted is True
        assert db.session.get(HizmetKaydi, taseron_hizmet.id).is_deleted is True
        assert db.session.get(Nakliye, nakliye.id).is_active is False
        assert tedarikci.bakiye == Decimal("0.00")
        assert taseron.bakiye == Decimal("0.00")

        KiralamaService.restore_with_relations(kiralama.id, snapshot=snapshot)

        db.session.refresh(tedarikci)
        db.session.refresh(taseron)
        restored_tedarikci_hizmet = db.session.get(HizmetKaydi, tedarikci_hizmet.id)
        restored_taseron_hizmet = db.session.get(HizmetKaydi, taseron_hizmet.id)
        assert restored_tedarikci_hizmet is not None
        assert restored_taseron_hizmet is not None
        assert restored_tedarikci_hizmet.is_deleted is False
        assert restored_taseron_hizmet.is_deleted is False
        assert restored_tedarikci_hizmet.vade_tarihi == date(2026, 6, 1)
        assert restored_taseron_hizmet.vade_tarihi == date(2026, 6, 1)
        assert tedarikci.bakiye == tedarikci.bakiye_ozeti["net_bakiye"]
        assert taseron.bakiye == taseron.bakiye_ozeti["net_bakiye"]


def test_kiralama_restore_preserves_passive_records_and_machine_state(app):
    with app.app_context():
        musteri = Firma(
            firma_adi=f"Kiralama Passive {uuid.uuid4().hex[:4]}",
            yetkili_adi="Yetkili",
            iletisim_bilgileri="Adres",
            vergi_dairesi="Istanbul VD",
            vergi_no=_unique_vergi_no(),
            is_musteri=True,
            is_tedarikci=False,
            bakiye=Decimal("0"),
        )
        ekipman = Ekipman(
            kod=_unique_kod(),
            yakit="Elektrik",
            tipi="MAKAS",
            marka="E2E Marka",
            model="E2E Model",
            seri_no=f"SN-{uuid.uuid4().hex[:8]}",
            calisma_yuksekligi=12,
            kaldirma_kapasitesi=2500,
            uretim_yili=2024,
            calisma_durumu="kirada",
        )
        db.session.add_all([musteri, ekipman])
        db.session.flush()

        kiralama = Kiralama(
            kiralama_form_no=f"PF-PASS-{uuid.uuid4().hex[:6]}",
            firma_musteri_id=musteri.id,
            kdv_orani=20,
        )
        db.session.add(kiralama)
        db.session.flush()

        aktif_kalem = KiralamaKalemi(
            kiralama_id=kiralama.id,
            ekipman_id=ekipman.id,
            kiralama_baslangici=date(2026, 6, 1),
            kiralama_bitis=date(2026, 6, 10),
            kiralama_brm_fiyat=Decimal("100.00"),
            sonlandirildi=False,
            is_active=True,
        )
        pasif_kalem = KiralamaKalemi(
            kiralama_id=kiralama.id,
            kiralama_baslangici=date(2026, 5, 1),
            kiralama_bitis=date(2026, 5, 10),
            kiralama_brm_fiyat=Decimal("100.00"),
            sonlandirildi=True,
            is_active=False,
        )
        db.session.add_all([aktif_kalem, pasif_kalem])
        db.session.flush()

        pasif_nakliye = Nakliye(
            kiralama_id=kiralama.id,
            firma_id=musteri.id,
            tarih=date(2026, 5, 1),
            islem_tarihi=date(2026, 5, 1),
            guzergah="Pasif guzergah",
            tutar=Decimal("0.00"),
            toplam_tutar=Decimal("0.00"),
            is_active=False,
        )
        db.session.add(pasif_nakliye)
        db.session.commit()

        snapshot = KiralamaService.delete_with_relations(kiralama.id)
        db.session.refresh(ekipman)
        assert ekipman.calisma_durumu == "bosta"

        KiralamaService.restore_with_relations(kiralama.id, snapshot=snapshot)
        db.session.refresh(ekipman)
        assert db.session.get(KiralamaKalemi, aktif_kalem.id).is_active is True
        assert db.session.get(KiralamaKalemi, pasif_kalem.id).is_active is False
        assert db.session.get(Nakliye, pasif_nakliye.id).is_active is False
        assert ekipman.calisma_durumu == "kirada"


def test_kiralama_restore_rejects_machine_conflict(app):
    with app.app_context():
        musteri = Firma(
            firma_adi=f"Kiralama Conflict {uuid.uuid4().hex[:4]}",
            yetkili_adi="Yetkili",
            iletisim_bilgileri="Adres",
            vergi_dairesi="Istanbul VD",
            vergi_no=_unique_vergi_no(),
            is_musteri=True,
            is_tedarikci=False,
            bakiye=Decimal("0"),
        )
        ekipman = Ekipman(
            kod=_unique_kod(),
            yakit="Elektrik",
            tipi="MAKAS",
            marka="E2E Marka",
            model="E2E Model",
            seri_no=f"SN-{uuid.uuid4().hex[:8]}",
            calisma_yuksekligi=12,
            kaldirma_kapasitesi=2500,
            uretim_yili=2024,
            calisma_durumu="kirada",
        )
        db.session.add_all([musteri, ekipman])
        db.session.flush()

        kiralama = Kiralama(
            kiralama_form_no=f"PF-CONF-{uuid.uuid4().hex[:6]}",
            firma_musteri_id=musteri.id,
            kdv_orani=20,
        )
        db.session.add(kiralama)
        db.session.flush()
        kalem = KiralamaKalemi(
            kiralama_id=kiralama.id,
            ekipman_id=ekipman.id,
            kiralama_baslangici=date(2026, 7, 1),
            kiralama_bitis=date(2026, 7, 10),
            kiralama_brm_fiyat=Decimal("100.00"),
            sonlandirildi=False,
            is_active=True,
        )
        db.session.add(kalem)
        db.session.commit()

        snapshot = KiralamaService.delete_with_relations(kiralama.id)

        baska_kiralama = Kiralama(
            kiralama_form_no=f"PF-CONF-OTHER-{uuid.uuid4().hex[:6]}",
            firma_musteri_id=musteri.id,
            kdv_orani=20,
        )
        db.session.add(baska_kiralama)
        db.session.flush()
        db.session.add(KiralamaKalemi(
            kiralama_id=baska_kiralama.id,
            ekipman_id=ekipman.id,
            kiralama_baslangici=date(2026, 7, 2),
            kiralama_bitis=date(2026, 7, 11),
            kiralama_brm_fiyat=Decimal("100.00"),
            sonlandirildi=False,
            is_active=True,
        ))
        db.session.commit()

        try:
            KiralamaService.restore_with_relations(kiralama.id, snapshot=snapshot)
            assert False, "Expected ValidationError for machine conflict"
        except ValidationError as exc:
            assert "Geri" in str(exc)


def test_financial_edit_password_verify_endpoint(app, client):
    with app.app_context():
        user = User(username=f"financial_verify_{uuid.uuid4().hex[:6]}", rol="user")
        user.set_password("pass123")
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    _login_user(client, user_id)

    missing_response = client.post("/kiralama/api/financial-edit-password/verify", data={"password": ""})
    assert missing_response.status_code == 200
    assert missing_response.get_json()["success"] is False

    wrong_response = client.post("/kiralama/api/financial-edit-password/verify", data={"password": "wrong"})
    assert wrong_response.status_code == 200
    assert wrong_response.get_json()["success"] is False

    correct_response = client.post("/kiralama/api/financial-edit-password/verify", data={"password": "pass123"})
    assert correct_response.status_code == 200
    assert correct_response.get_json()["success"] is True
