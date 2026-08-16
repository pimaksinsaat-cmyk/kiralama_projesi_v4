from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from app.cari.models import HizmetKaydi
from app.extensions import db
from app.filo.models import Ekipman
from app.firmalar.models import Firma
from app.kiralama.models import Kiralama, KiralamaKalemi
from app.nakliyeler.models import Nakliye
from app.services.kiralama_services import KiralamaKalemiService
from app.subeler.models import Sube


def _unique_vergi_no() -> str:
    return f"DONUS{uuid.uuid4().hex[:8].upper()}"


def _firma(ad: str, *, musteri: bool = False, tedarikci: bool = False) -> Firma:
    firma = Firma(
        firma_adi=f"{ad} {uuid.uuid4().hex[:4]}",
        yetkili_adi="Yetkili",
        iletisim_bilgileri="Adres",
        vergi_dairesi="Istanbul VD",
        vergi_no=_unique_vergi_no(),
        is_musteri=musteri,
        is_tedarikci=tedarikci,
        bakiye=Decimal("0"),
    )
    db.session.add(firma)
    db.session.flush()
    return firma


def _seed_kiralama(*, gidis_taseron: Firma | None = None) -> tuple[Kiralama, KiralamaKalemi, Sube]:
    sube = Sube(
        isim=f"Donus Sube {uuid.uuid4().hex[:4]}",
        adres="Test Adres",
        yetkili_kisi="Test Yetkili",
        telefon="0212-3333333",
    )
    db.session.add(sube)
    db.session.flush()

    musteri = _firma("Donus Musteri", musteri=True)
    ekipman = Ekipman(
        kod=f"DN-{uuid.uuid4().hex[:6].upper()}",
        yakit="Elektrik",
        tipi="MAKAS",
        marka="Test Marka",
        model="Test Model",
        seri_no=f"SN-{uuid.uuid4().hex[:8]}",
        calisma_yuksekligi=12,
        kaldirma_kapasitesi=2500,
        uretim_yili=2024,
        calisma_durumu="kirada",
        sube_id=sube.id,
    )
    db.session.add(ekipman)
    db.session.flush()

    kiralama = Kiralama(
        kiralama_form_no=f"PF-DONUS-{uuid.uuid4().hex[:6]}",
        firma_musteri_id=musteri.id,
        kdv_orani=20,
    )
    db.session.add(kiralama)
    db.session.flush()

    kalem = KiralamaKalemi(
        kiralama_id=kiralama.id,
        ekipman_id=ekipman.id,
        kiralama_baslangici=date(2026, 5, 18),
        kiralama_bitis=date(2026, 6, 6),
        kiralama_brm_fiyat=Decimal("650.00"),
        nakliye_satis_fiyat=Decimal("5000.00"),
        donus_nakliye_fatura_et=True,
        is_harici_nakliye=gidis_taseron is not None,
        nakliye_tedarikci_id=gidis_taseron.id if gidis_taseron else None,
        nakliye_alis_fiyat=Decimal("1000.00") if gidis_taseron else Decimal("0.00"),
        nakliye_alis_kdv=20 if gidis_taseron else None,
        sonlandirildi=False,
        is_active=True,
    )
    db.session.add(kalem)
    db.session.commit()
    return kiralama, kalem, sube


def test_sifir_donus_satis_fark_degildir_gorunur_sifir_satir_olusturur(app):
    with app.app_context():
        kiralama, kalem, sube = _seed_kiralama()

        KiralamaKalemiService.sonlandir(
            kalem.id,
            "2026-06-06",
            str(sube.id),
            is_harici_nakliye=False,
            donus_nakliye_satis_fiyat="0",
        )

        assert HizmetKaydi.query.filter(
            HizmetKaydi.ozel_id == kalem.id,
            HizmetKaydi.aciklama.like("Nakliye Farkı%"),
            HizmetKaydi.is_deleted == False,
        ).count() == 0

        sifir_satir = HizmetKaydi.query.filter(
            HizmetKaydi.ozel_id == kalem.id,
            HizmetKaydi.nakliye_id.is_(None),
            HizmetKaydi.firma_id == kiralama.firma_musteri_id,
            HizmetKaydi.yon == "giden",
            HizmetKaydi.aciklama.like("Dönüş Nakliye (%"),
            HizmetKaydi.is_deleted == False,
        ).one()
        assert sifir_satir.tutar == Decimal("0.00")

        donus_sefer = Nakliye.query.filter(
            Nakliye.kiralama_id == kiralama.id,
            Nakliye.aciklama == f"Dönüş: {kiralama.kiralama_form_no} #{kalem.id}",
        ).one()
        assert donus_sefer.tutar == Decimal("0.00")


def test_donus_taseronu_gidis_taseronundan_bagimsiz_cariye_islenir(app):
    with app.app_context():
        gidis_taseron = _firma("Gidis Taseron", tedarikci=True)
        donus_taseron = _firma("Donus Taseron", tedarikci=True)
        kiralama, kalem, sube = _seed_kiralama(gidis_taseron=gidis_taseron)

        KiralamaKalemiService.sonlandir(
            kalem.id,
            "2026-06-06",
            str(sube.id),
            is_harici_nakliye=True,
            nakliye_tedarikci_id=donus_taseron.id,
            nakliye_alis_fiyat="2500",
            donus_nakliye_alis_kdv="20",
            donus_nakliye_satis_fiyat="3500",
        )

        donus_taseron_kaydi = HizmetKaydi.query.filter(
            HizmetKaydi.ozel_id == kalem.id,
            HizmetKaydi.firma_id == donus_taseron.id,
            HizmetKaydi.yon == "gelen",
            HizmetKaydi.aciklama.like("Dönüş Nakliye:%"),
            HizmetKaydi.is_deleted == False,
        ).one()
        assert donus_taseron_kaydi.tutar == Decimal("2500.00")

        assert HizmetKaydi.query.filter(
            HizmetKaydi.ozel_id == kalem.id,
            HizmetKaydi.firma_id == gidis_taseron.id,
            HizmetKaydi.aciklama.like("Dönüş Nakliye:%"),
            HizmetKaydi.is_deleted == False,
        ).count() == 0

        donus_sefer = Nakliye.query.filter(
            Nakliye.kiralama_id == kiralama.id,
            Nakliye.aciklama == f"Dönüş: {kiralama.kiralama_form_no} #{kalem.id}",
        ).one()
        assert donus_sefer.tutar == Decimal("3500.00")
        assert donus_sefer.taseron_firma_id == donus_taseron.id
        assert donus_sefer.taseron_maliyet == Decimal("2500.00")


def _kalem_update_payload(kalem: KiralamaKalemi, *, nakliye_satis_fiyat) -> dict:
    return {
        "id": kalem.id,
        "ekipman_id": kalem.ekipman_id,
        "dis_tedarik_ekipman": 0,
        "kiralama_baslangici": kalem.kiralama_baslangici.isoformat(),
        "kiralama_bitis": kalem.kiralama_bitis.isoformat(),
        "kiralama_brm_fiyat": str(kalem.kiralama_brm_fiyat),
        "kiralama_alis_fiyat": str(kalem.kiralama_alis_fiyat or 0),
        "nakliye_satis_fiyat": str(nakliye_satis_fiyat),
        "donus_nakliye_fatura_et": 1 if kalem.donus_nakliye_fatura_et else 0,
        "dis_tedarik_nakliye": 1 if kalem.is_harici_nakliye else 0,
        "nakliye_alis_fiyat": str(kalem.nakliye_alis_fiyat or 0),
        "nakliye_tedarikci_id": kalem.nakliye_tedarikci_id or 0,
        "nakliye_araci_id": kalem.nakliye_araci_id or 0,
        "donus_is_harici_nakliye": 1 if kalem.donus_is_harici_nakliye else 0,
        "donus_nakliye_tedarikci_id": kalem.donus_nakliye_tedarikci_id or 0,
        "donus_nakliye_alis_fiyat": str(kalem.donus_nakliye_alis_fiyat or 0),
        "donus_nakliye_alis_kdv": kalem.donus_nakliye_alis_kdv,
        "donus_nakliye_araci_id": kalem.donus_nakliye_araci_id or 0,
        "nakliye_satis_kdv": kalem.nakliye_satis_kdv,
        "nakliye_alis_kdv": kalem.nakliye_alis_kdv,
    }


def _aktif_donus_sefer(kiralama: Kiralama, kalem: KiralamaKalemi) -> Nakliye:
    return Nakliye.active_query().filter(
        Nakliye.kiralama_id == kiralama.id,
        Nakliye.aciklama == f"Dönüş: {kiralama.kiralama_form_no} #{kalem.id}",
    ).one()


def _aktif_gidis_sefer(kiralama: Kiralama, kalem: KiralamaKalemi) -> Nakliye:
    return Nakliye.active_query().filter(
        Nakliye.kiralama_id == kiralama.id,
        Nakliye.aciklama == f"Gidiş: {kiralama.kiralama_form_no} #{kalem.id}",
    ).one()


def test_varsayilan_iade_donus_satis_override_none_birakir(app):
    """Varsayılan yarı fiyat iadede dondurulmaz; sefer yine yarı tutarı yazar."""
    with app.app_context():
        from app.services.kiralama_services import KiralamaService

        kiralama, kalem, sube = _seed_kiralama()
        # Toplam 5000 → planlanan dönüş 2500
        KiralamaKalemiService.sonlandir(
            kalem.id,
            "2026-06-06",
            str(sube.id),
            is_harici_nakliye=False,
            donus_nakliye_satis_fiyat="2500",
        )

        db.session.refresh(kalem)
        assert kalem.donus_nakliye_satis_fiyat is None
        assert KiralamaService._get_donus_nakliye_satis(kalem) == Decimal("2500.00")

        donus_sefer = _aktif_donus_sefer(kiralama, kalem)
        assert donus_sefer.tutar == Decimal("2500.00")


def test_sifreli_edit_eski_yari_snapshot_donusu_gunceller(app):
    """Eski yarı freeze + nakliye artışı → override temizlenir, gidiş/dönüş yeni yarı olur."""
    with app.app_context():
        from app.services.kiralama_services import KiralamaService

        kiralama, kalem, sube = _seed_kiralama()
        KiralamaKalemiService.sonlandir(
            kalem.id,
            "2026-06-06",
            str(sube.id),
            is_harici_nakliye=False,
            donus_nakliye_satis_fiyat="2500",
        )

        # Legacy davranış simülasyonu: varsayılan yarı dondurulmuş
        kalem.donus_nakliye_satis_fiyat = Decimal("2500.00")
        db.session.commit()

        KiralamaService.update_kiralama_with_relations(
            kiralama.id,
            {},
            [_kalem_update_payload(kalem, nakliye_satis_fiyat="7250.00")],
        )

        db.session.refresh(kalem)
        assert kalem.nakliye_satis_fiyat == Decimal("7250.00")
        assert kalem.donus_nakliye_satis_fiyat is None
        assert KiralamaService._get_donus_nakliye_satis(kalem) == Decimal("3625.00")

        gidis = _aktif_gidis_sefer(kiralama, kalem)
        donus = _aktif_donus_sefer(kiralama, kalem)
        assert gidis.tutar == Decimal("3625.00")
        assert donus.tutar == Decimal("3625.00")

        # Eski dönüş soft-delete edilmiş olmalı
        eski_sayisi = Nakliye.query.filter(
            Nakliye.kiralama_id == kiralama.id,
            Nakliye.aciklama == f"Dönüş: {kiralama.kiralama_form_no} #{kalem.id}",
            Nakliye.is_deleted == True,
        ).count()
        assert eski_sayisi >= 1


def test_sifreli_edit_bilincli_donus_override_korunur(app):
    """Bilinçli farklı dönüş fiyatı, form nakliye artınca değişmez."""
    with app.app_context():
        from app.services.kiralama_services import KiralamaService

        kiralama, kalem, sube = _seed_kiralama()
        KiralamaKalemiService.sonlandir(
            kalem.id,
            "2026-06-06",
            str(sube.id),
            is_harici_nakliye=False,
            donus_nakliye_satis_fiyat="3500",
        )

        db.session.refresh(kalem)
        assert kalem.donus_nakliye_satis_fiyat == Decimal("3500.00")

        KiralamaService.update_kiralama_with_relations(
            kiralama.id,
            {},
            [_kalem_update_payload(kalem, nakliye_satis_fiyat="7250.00")],
        )

        db.session.refresh(kalem)
        assert kalem.donus_nakliye_satis_fiyat == Decimal("3500.00")
        assert _aktif_donus_sefer(kiralama, kalem).tutar == Decimal("3500.00")
        assert _aktif_gidis_sefer(kiralama, kalem).tutar == Decimal("3625.00")


def test_iade_iptal_override_temizler_tekrar_iade_yeni_yari_kullanir(app):
    with app.app_context():
        from app.services.kiralama_services import KiralamaService

        kiralama, kalem, sube = _seed_kiralama()
        KiralamaKalemiService.sonlandir(
            kalem.id,
            "2026-06-06",
            str(sube.id),
            is_harici_nakliye=False,
            donus_nakliye_satis_fiyat="3500",
        )
        db.session.refresh(kalem)
        assert kalem.donus_nakliye_satis_fiyat == Decimal("3500.00")

        KiralamaKalemiService.iptal_et_sonlandirma(kalem.id)
        db.session.refresh(kalem)
        assert kalem.donus_nakliye_satis_fiyat is None
        assert kalem.sonlandirildi is False

        kalem.nakliye_satis_fiyat = Decimal("7250.00")
        db.session.commit()

        KiralamaKalemiService.sonlandir(
            kalem.id,
            "2026-06-06",
            str(sube.id),
            is_harici_nakliye=False,
            donus_nakliye_satis_fiyat="3625",
        )
        db.session.refresh(kalem)
        assert kalem.donus_nakliye_satis_fiyat is None
        assert KiralamaService._get_donus_nakliye_satis(kalem) == Decimal("3625.00")
        assert _aktif_donus_sefer(kiralama, kalem).tutar == Decimal("3625.00")


def test_sonlandir_checkbox_kapali_varsayilan_override_olusturmaz(app):
    with app.app_context():
        kiralama, kalem, sube = _seed_kiralama()
        KiralamaKalemiService.sonlandir(
            kalem.id,
            "2026-06-06",
            str(sube.id),
            is_harici_nakliye=False,
            donus_nakliye_satis_fiyat="2500",
            donus_satis_override=False,
        )
        db.session.refresh(kalem)
        assert kalem.donus_nakliye_satis_fiyat is None
        assert _aktif_donus_sefer(kiralama, kalem).tutar == Decimal("2500.00")


def test_sonlandir_checkbox_acik_sifir_override_korunur(app):
    with app.app_context():
        _kiralama, kalem, sube = _seed_kiralama()
        KiralamaKalemiService.sonlandir(
            kalem.id,
            "2026-06-06",
            str(sube.id),
            is_harici_nakliye=False,
            donus_nakliye_satis_fiyat="0",
            donus_satis_override=True,
        )
        db.session.refresh(kalem)
        assert kalem.donus_nakliye_satis_fiyat == Decimal("0.00")


def test_sonlandir_fiyat_gonderilmeden_eski_override_temizlenir(app):
    with app.app_context():
        _kiralama, kalem, sube = _seed_kiralama()
        kalem.donus_nakliye_satis_fiyat = Decimal("3500.00")
        db.session.commit()

        KiralamaKalemiService.sonlandir(
            kalem.id,
            "2026-06-06",
            str(sube.id),
            is_harici_nakliye=False,
            donus_nakliye_satis_fiyat=None,
            donus_satis_override=None,
        )
        db.session.refresh(kalem)
        assert kalem.donus_nakliye_satis_fiyat is None


def test_eep_senaryosu_sifreli_edit_sonrasi_donus_3625(app):
    """Toplam 7250 (tek yön 3625) → gidiş ve dönüş seferi 3625."""
    with app.app_context():
        from app.services.kiralama_services import KiralamaService

        kiralama, kalem, sube = _seed_kiralama()
        kalem.nakliye_satis_fiyat = Decimal("6000.00")
        db.session.commit()

        KiralamaKalemiService.sonlandir(
            kalem.id,
            "2026-06-06",
            str(sube.id),
            is_harici_nakliye=False,
            donus_nakliye_satis_fiyat="3000",
            donus_satis_override=False,
        )
        # Legacy freeze simülasyonu
        kalem.donus_nakliye_satis_fiyat = Decimal("3000.00")
        db.session.commit()

        KiralamaService.update_kiralama_with_relations(
            kiralama.id,
            {},
            [_kalem_update_payload(kalem, nakliye_satis_fiyat="7250.00")],
        )
        db.session.refresh(kalem)
        assert kalem.donus_nakliye_satis_fiyat is None
        assert _aktif_gidis_sefer(kiralama, kalem).tutar == Decimal("3625.00")
        assert _aktif_donus_sefer(kiralama, kalem).tutar == Decimal("3625.00")


def test_normalize_script_yari_esitleri_temizler_digerlerini_korur(app):
    with app.app_context():
        from scripts.repair_donus_nakliye_override_snapshots import _classify

        kiralama, kalem, _sube = _seed_kiralama()
        kalem.donus_nakliye_satis_fiyat = Decimal("2500.00")  # half of 5000
        db.session.flush()
        kind, _info = _classify(kalem)
        assert kind == "normalize"

        kalem.donus_nakliye_satis_fiyat = Decimal("3500.00")
        db.session.flush()
        kind, _info = _classify(kalem)
        assert kind == "intentional"

        kalem.donus_nakliye_fatura_et = False
        kalem.donus_nakliye_satis_fiyat = Decimal("1200.00")
        db.session.flush()
        kind, _info = _classify(kalem)
        assert kind == "one_way_extra"

        kalem.donus_nakliye_fatura_et = True
        kalem.donus_nakliye_satis_fiyat = Decimal("0.00")
        db.session.flush()
        kind, _info = _classify(kalem)
        assert kind == "zero_manual"


def test_line_payload_etkin_ve_override_ayri(app):
    with app.app_context():
        from app.api.kiralama_payload import line_payload

        _kiralama, kalem, _sube = _seed_kiralama()
        kalem.donus_nakliye_satis_fiyat = None
        payload = line_payload(kalem)
        assert payload["return_transport_sale_price"] == Decimal("2500.00")
        assert payload["return_transport_sale_price_override"] is None

        kalem.donus_nakliye_satis_fiyat = Decimal("3500.00")
        payload = line_payload(kalem)
        assert payload["return_transport_sale_price"] == Decimal("3500.00")
        assert payload["return_transport_sale_price_override"] == Decimal("3500.00")


def test_line_to_service_donus_satis_fiyati_alir():
    from app.api.kiralama_payload import line_to_service

    mapped = line_to_service({
        "return_transport_sale_price": 0,
        "donus_satis_override": True,
        "return_transport_invoice": True,
    })
    assert mapped["donus_nakliye_satis_fiyat"] == 0
    assert mapped["donus_satis_override"] is True
    assert mapped["donus_nakliye_fatura_et"] == 1


def _login_session(client, user_id: int) -> None:
    from app.auth.models import User
    from app.auth.session_security import (
        SESSION_LAST_PING_KEY,
        SESSION_TOKEN_KEY,
        new_session_token,
        utc_now,
    )

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


def test_detay_modal_tek_yon_ek_donus_gosterir(app, client):
    with app.app_context():
        from app.auth.models import User

        kiralama, kalem, sube = _seed_kiralama()
        kalem.donus_nakliye_fatura_et = False
        kalem.donus_nakliye_satis_fiyat = Decimal("1800.00")
        kalem.sonlandirildi = True
        user = User(username=f"detay_{uuid.uuid4().hex[:6]}", rol="admin")
        user.set_password("pass123")
        db.session.add(user)
        db.session.commit()
        kiralama_id = kiralama.id
        user_id = user.id

    _login_session(client, user_id)
    response = client.get(f"/kiralama/detay/{kiralama_id}")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Dönüş nakliyesi ek" in html
    assert "1.800,00" in html


def test_web_sonlandir_route_override_flag_gonderir(app, client):
    with app.app_context():
        from app.auth.models import User

        _kiralama, kalem, sube = _seed_kiralama()
        user = User(username=f"web_{uuid.uuid4().hex[:6]}", rol="admin")
        user.set_password("pass123")
        db.session.add(user)
        db.session.commit()
        kalem_id = kalem.id
        sube_id = sube.id
        user_id = user.id

    _login_session(client, user_id)
    response = client.post(
        "/kiralama/kalem/sonlandir",
        data={
            "kalem_id": kalem_id,
            "bitis_tarihi": "2026-06-06",
            "donus_sube_id": str(sube_id),
            "donus_nakliye_satis_fiyat": "2500",
            "donus_satis_override": "0",
        },
        follow_redirects=False,
    )
    assert response.status_code in (302, 200)
    with app.app_context():
        kalem = db.session.get(KiralamaKalemi, kalem_id)
        assert kalem.sonlandirildi is True
        assert kalem.donus_nakliye_satis_fiyat is None


def test_filo_formunda_donus_satis_override_hidden_var():
    from pathlib import Path

    html = Path("app/templates/filo/index.html").read_text(encoding="utf-8")
    assert 'name="donus_satis_override"' in html
    assert "donusSatisOverrideHidden" in html
