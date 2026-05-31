"""audit_kiralama_taseron_nakliye_odeme_cari.py denetim fonksiyonu testleri."""

from __future__ import annotations

import importlib.util
import sys
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path

from app.cari.models import HizmetKaydi, Kasa, Odeme
from app.extensions import db
from app.firmalar.models import Firma
from app.kiralama.models import Kiralama, KiralamaKalemi
from app.nakliyeler.models import Nakliye
from app.services.kiralama_services import KiralamaService

ROOT = Path(__file__).resolve().parents[1]
_AUDIT_PATH = ROOT / "scripts" / "audit_kiralama_taseron_nakliye_odeme_cari.py"
_spec = importlib.util.spec_from_file_location("audit_kiralama_mod", _AUDIT_PATH)
_audit_mod = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
sys.modules["audit_kiralama_mod"] = _audit_mod
_spec.loader.exec_module(_audit_mod)
run_audit = _audit_mod.run_audit


def _unique_vergi_no() -> str:
    return f"A{uuid.uuid4().hex[:9].upper()}"


def _firma(name: str, *, is_musteri=True, is_tedarikci=False):
    return Firma(
        firma_adi=name,
        yetkili_adi="Yetkili",
        iletisim_bilgileri="Adres",
        vergi_dairesi="VD",
        vergi_no=_unique_vergi_no(),
        is_musteri=is_musteri,
        is_tedarikci=is_tedarikci,
        bakiye=Decimal("0"),
    )


def _categories(result):
    return {f.category for f in result.findings}


def test_audit_dis_kiralama_amount_mismatch(app):
    today = date(2026, 5, 20)
    musteri = _firma("AUDIT MUSTERI")
    tedarikci = _firma("AUDIT TEDARIKCI", is_tedarikci=True)
    db.session.add_all([musteri, tedarikci])
    db.session.flush()

    kiralama = Kiralama(
        kiralama_form_no=f"PF-AUDIT-{uuid.uuid4().hex[:6]}",
        firma_musteri_id=musteri.id,
        kdv_orani=20,
    )
    db.session.add(kiralama)
    db.session.flush()

    kalem = KiralamaKalemi(
        kiralama_id=kiralama.id,
        is_dis_tedarik_ekipman=True,
        harici_ekipman_tedarikci_id=tedarikci.id,
        harici_ekipman_marka="Marka",
        harici_ekipman_model="Model",
        harici_ekipman_tipi="Platform",
        harici_ekipman_seri_no="SN-1",
        kiralama_baslangici=date(2026, 5, 1),
        kiralama_bitis=date(2026, 5, 10),
        kiralama_brm_fiyat=Decimal("1000.00"),
        kiralama_alis_fiyat=Decimal("500.00"),
        kiralama_alis_kdv=20,
        sonlandirildi=False,
        is_active=True,
    )
    db.session.add(kalem)
    db.session.flush()

    expected = KiralamaService._hesapla_bekleyen_alis_kalem_tutari(kalem, referans_tarih=today)
    wrong_amount = expected + Decimal("100.00")

    hizmet = HizmetKaydi(
        firma_id=tedarikci.id,
        tarih=today,
        islem_tarihi=kalem.kiralama_baslangici,
        tutar=wrong_amount,
        yon="gelen",
        fatura_no=kiralama.kiralama_form_no,
        ozel_id=kalem.id,
        aciklama="Dış Kiralama: Marka",
        kdv_orani=20,
        kiralama_alis_kdv=20,
    )
    db.session.add(hizmet)
    db.session.commit()

    result = run_audit(today=today, tolerance=Decimal("0.01"))
    assert "DIS_KIRALAMA_AMOUNT_MISMATCH" in _categories(result)
    assert any(f.entity_id == kalem.id for f in result.findings)


def test_audit_donus_taseron_cari_missing(app):
    musteri = _firma("AUDIT DONUS MUS")
    taseron = _firma("AUDIT DONUS TAS", is_tedarikci=True)
    db.session.add_all([musteri, taseron])
    db.session.flush()

    kiralama = Kiralama(
        kiralama_form_no=f"PF-DONUS-{uuid.uuid4().hex[:6]}",
        firma_musteri_id=musteri.id,
        makine_calisma_adresi="Saha",
        kdv_orani=20,
    )
    db.session.add(kiralama)
    db.session.flush()

    kalem = KiralamaKalemi(
        kiralama_id=kiralama.id,
        kiralama_baslangici=date(2026, 4, 1),
        kiralama_bitis=date(2026, 4, 10),
        kiralama_brm_fiyat=Decimal("1000.00"),
        donus_nakliye_satis_fiyat=Decimal("800.00"),
        sonlandirildi=True,
        donus_is_harici_nakliye=True,
        donus_nakliye_tedarikci_id=taseron.id,
        donus_nakliye_alis_fiyat=Decimal("600.00"),
        donus_nakliye_alis_kdv=20,
        is_active=True,
    )
    db.session.add(kalem)
    db.session.flush()

    donus_aciklama = f"Dönüş: {kiralama.kiralama_form_no} #{kalem.id}"
    sefer = Nakliye(
        kiralama_id=kiralama.id,
        firma_id=musteri.id,
        tarih=date(2026, 4, 10),
        islem_tarihi=date(2026, 4, 10),
        guzergah="Donus guzergah",
        tutar=Decimal("800.00"),
        kdv_orani=20,
        aciklama=donus_aciklama,
        nakliye_tipi="taseron",
        taseron_firma_id=taseron.id,
        taseron_maliyet=Decimal("600.00"),
        taseron_kdv_orani=20,
    )
    sefer.hesapla_ve_guncelle()
    db.session.add(sefer)
    db.session.commit()

    result = run_audit(today=date(2026, 5, 26), tolerance=Decimal("0.01"))
    assert "DONUS_NAKLIYE_TASERON_CARI_MISSING" in _categories(result)
    assert any(f.entity_id == kalem.id for f in result.findings)


def test_audit_firma_bakiye_cache_drift(app):
    firma = _firma("AUDIT CACHE FIRMA")
    db.session.add(firma)
    db.session.flush()

    hizmet = HizmetKaydi(
        firma_id=firma.id,
        tarih=date(2026, 5, 1),
        islem_tarihi=date(2026, 5, 1),
        tutar=Decimal("1000.00"),
        yon="giden",
        aciklama="Test fatura",
        kdv_orani=20,
    )
    db.session.add(hizmet)
    db.session.flush()

    firma.bakiye = Decimal("9999.00")
    db.session.add(firma)
    db.session.commit()

    result = run_audit(today=date(2026, 5, 26), tolerance=Decimal("0.01"))
    assert "FIRMA_BAKIYE_CACHE_DRIFT" in _categories(result)
    assert any(f.firma_id == firma.id for f in result.findings)


def test_audit_kasa_bakiye_cache_drift(app):
    kasa = Kasa(kasa_adi=f"Audit Kasa {uuid.uuid4().hex[:4]}", tipi="nakit", bakiye=Decimal("5000.00"))
    db.session.add(kasa)
    db.session.flush()

    dahili = _firma("DAHİLİ İŞLEMLER")
    if not Firma.query.filter_by(firma_adi="DAHİLİ İŞLEMLER").first():
        db.session.add(dahili)
        db.session.flush()
    else:
        dahili = Firma.query.filter_by(firma_adi="DAHİLİ İŞLEMLER").first()

    odeme = Odeme(
        firma_musteri_id=dahili.id,
        kasa_id=kasa.id,
        tarih=date(2026, 5, 1),
        islem_tarihi=date(2026, 5, 1),
        tutar=Decimal("100.00"),
        yon="tahsilat",
        aciklama="Test tahsilat",
    )
    db.session.add(odeme)
    db.session.commit()

    result = run_audit(today=date(2026, 5, 26), tolerance=Decimal("0.01"))
    assert "KASA_BAKIYE_CACHE_DRIFT" in _categories(result)
    assert any(f.entity_id == kasa.id for f in result.findings)
