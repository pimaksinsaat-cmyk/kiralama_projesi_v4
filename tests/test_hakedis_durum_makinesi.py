"""
Hakediş durum makinesi (FaturaService.hakedis_durumu_guncelle) birim testleri.
"""
import uuid
from datetime import date, time
from decimal import Decimal

import pytest

from app.cari.models import HizmetKaydi
from app.extensions import db
from app.fatura.models import Hakedis, HakedisKalemi
from app.filo.models import Ekipman
from app.firmalar.models import Firma
from app.kiralama.models import Kiralama, KiralamaKalemi
from app.services.base import ValidationError
from app.services.fatura_services import FaturaService
from app.subeler.models import Sube


def _unique_vergi_no():
    return f"T{uuid.uuid4().hex[:10]}"


def _seed_contract_with_hakedis():
    """Tek firma, şube, ekipman, kiralama, kalem ve taslak hakediş + hakediş kalemi."""
    sube = Sube(isim="Test Şube", is_active=True)
    db.session.add(sube)
    db.session.flush()

    firma = Firma(
        firma_adi="Test Müşteri A.Ş.",
        yetkili_adi="Yetkili",
        iletisim_bilgileri="Adres",
        vergi_dairesi="Test VD",
        vergi_no=_unique_vergi_no(),
        is_musteri=True,
        is_tedarikci=False,
    )
    db.session.add(firma)
    db.session.flush()

    ek = Ekipman(
        kod=f"TST-{firma.id}",
        yakit="Akülü",
        tipi="MAKAS",
        marka="M",
        model="X",
        seri_no=f"SN-{firma.id}",
        calisma_yuksekligi=10,
        kaldirma_kapasitesi=200,
        uretim_yili=2020,
        calisma_durumu="bosta",
        sube_id=sube.id,
    )
    db.session.add(ek)
    db.session.flush()

    kr = Kiralama(
        kiralama_form_no=f"PF-TEST-{firma.id}",
        firma_musteri_id=firma.id,
        kdv_orani=20,
    )
    db.session.add(kr)
    db.session.flush()

    bas = date(2026, 1, 1)
    bit = date(2026, 1, 10)
    kk = KiralamaKalemi(
        kiralama_id=kr.id,
        ekipman_id=ek.id,
        kiralama_baslangici=bas,
        kiralama_bitis=bit,
        kiralama_brm_fiyat=Decimal("100.00"),
        sonlandirildi=False,
        is_active=True,
    )
    db.session.add(kk)
    db.session.flush()

    hk = Hakedis(
        hakedis_no=f"HKD-TEST-{firma.id}",
        firma_id=firma.id,
        kiralama_id=kr.id,
        baslangic_tarihi=bas,
        bitis_tarihi=bit,
        duzenleme_tarihi=date.today(),
        duzenleme_saati=time(12, 0, 0),
        durum="taslak",
        is_faturalasti=False,
        genel_toplam=Decimal("1000.00"),
        toplam_matrah=Decimal("800.00"),
        toplam_kdv=Decimal("200.00"),
        toplam_tevkifat=Decimal("0"),
    )
    db.session.add(hk)
    db.session.flush()

    hkk = HakedisKalemi(
        hakedis_id=hk.id,
        kiralama_kalemi_id=kk.id,
        ekipman_id=ek.id,
        miktar=Decimal("10"),
        birim_fiyat=Decimal("100.00"),
        ara_toplam=Decimal("1000.00"),
        satir_toplami=Decimal("1000.00"),
    )
    db.session.add(hkk)
    db.session.commit()
    return hk, firma


def test_taslak_onaylandi_creates_hizmet_not_gib_flag(app):
    with app.app_context():
        hakedis, firma = _seed_contract_with_hakedis()
        hid = hakedis.id
        n_hizmet_before = HizmetKaydi.query.count()

        out = FaturaService.hakedis_durumu_guncelle(hid, "onaylandi", actor_id=1)

        assert out.durum == "onaylandi"
        assert out.is_faturalasti is False
        assert out.cari_hareket_id is not None

        assert HizmetKaydi.query.count() == n_hizmet_before + 1
        hz = db.session.get(HizmetKaydi, out.cari_hareket_id)
        assert hz is not None
        assert hz.firma_id == firma.id
        assert hz.yon == "giden"
        assert hz.is_deleted is False


def test_onaylandi_faturalasti_no_second_hizmet(app):
    with app.app_context():
        hakedis, _ = _seed_contract_with_hakedis()
        FaturaService.hakedis_durumu_guncelle(hakedis.id, "onaylandi", actor_id=1)
        n_after_onay = HizmetKaydi.query.count()

        out = FaturaService.hakedis_durumu_guncelle(hakedis.id, "faturalasti", actor_id=1)

        assert out.durum == "faturalasti"
        assert out.is_faturalasti is True
        assert HizmetKaydi.query.count() == n_after_onay


def test_taslak_iptal_no_hizmet(app):
    with app.app_context():
        hakedis, _ = _seed_contract_with_hakedis()
        n0 = HizmetKaydi.query.count()
        FaturaService.hakedis_durumu_guncelle(hakedis.id, "iptal", actor_id=1)
        h = db.session.get(Hakedis, hakedis.id)
        assert h.durum == "iptal"
        assert HizmetKaydi.query.count() == n0


def test_onaylandi_iptal_soft_deletes_hizmet(app):
    with app.app_context():
        hakedis, _ = _seed_contract_with_hakedis()
        FaturaService.hakedis_durumu_guncelle(hakedis.id, "onaylandi", actor_id=1)
        hk_id = hakedis.id
        cari_id = db.session.get(Hakedis, hk_id).cari_hareket_id

        FaturaService.hakedis_durumu_guncelle(hk_id, "iptal", actor_id=1)

        h = db.session.get(Hakedis, hk_id)
        assert h.durum == "iptal"
        assert h.cari_hareket_id is None
        hz = db.session.get(HizmetKaydi, cari_id)
        assert hz.is_deleted is True


def test_faturalasti_iptal_forbidden(app):
    with app.app_context():
        hakedis, _ = _seed_contract_with_hakedis()
        FaturaService.hakedis_durumu_guncelle(hakedis.id, "onaylandi", actor_id=1)
        FaturaService.hakedis_durumu_guncelle(hakedis.id, "faturalasti", actor_id=1)

        with pytest.raises(ValidationError, match="iptal"):
            FaturaService.hakedis_durumu_guncelle(hakedis.id, "iptal", actor_id=1)


def test_taslak_to_faturalasti_rejected(app):
    with app.app_context():
        hakedis, _ = _seed_contract_with_hakedis()
        with pytest.raises(ValidationError):
            FaturaService.hakedis_durumu_guncelle(hakedis.id, "faturalasti", actor_id=1)
