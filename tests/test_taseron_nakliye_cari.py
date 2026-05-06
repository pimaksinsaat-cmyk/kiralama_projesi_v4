from datetime import date
from decimal import Decimal
import importlib.util
from pathlib import Path

from app.cari.models import HizmetKaydi
from app.extensions import db
from app.firmalar.models import Firma
from app.kiralama.models import Kiralama, KiralamaKalemi
from app.nakliyeler.models import Nakliye
from app.services.firma_services import FirmaService
from app.services.nakliye_services import CariServis
from app.services.kiralama_services import KiralamaKalemiService


def _firma(name, *, is_musteri=True, is_tedarikci=False, vergi_no=None):
    return Firma(
        firma_adi=name,
        yetkili_adi="Yetkili",
        iletisim_bilgileri="Adres",
        vergi_dairesi="VD",
        vergi_no=vergi_no or name[:8].upper().ljust(10, "0"),
        is_musteri=is_musteri,
        is_tedarikci=is_tedarikci,
        is_active=True,
    )


def _load_normalization_migration():
    path = Path(__file__).resolve().parents[1] / "migrations" / "versions" / "u6v7w8x9y0z1_normalize_nakliye_taseron_hizmet_kaydi.py"
    spec = importlib.util.spec_from_file_location("nakliye_hizmet_normalization", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeAlembicOp:
    def __init__(self, connection):
        self.connection = connection

    def execute(self, sql):
        return self.connection.exec_driver_sql(sql)

    def get_bind(self):
        return self.connection


def test_legacy_standalone_taseron_nakliye_gideri_cari_satirina_girer(app):
    musteri = _firma("CAGDAS YAPI", vergi_no="1111111111")
    taseron = _firma("GEYLANI ERCAN", is_tedarikci=True, vergi_no="2222222222")
    baska_musteri = _firma("OBAYAPI", vergi_no="9999999999")
    db.session.add_all([musteri, taseron, baska_musteri])
    db.session.flush()

    nakliye = Nakliye(
        firma_id=musteri.id,
        tarih=date(2026, 3, 28),
        islem_tarihi=date(2026, 3, 28),
        guzergah="IKITELLI - AVCILAR",
        nakliye_tipi="taseron",
        taseron_firma_id=taseron.id,
        tutar=Decimal("3000.00"),
        taseron_maliyet=Decimal("2500.00"),
    )
    nakliye.hesapla_ve_guncelle()
    db.session.add(nakliye)
    db.session.flush()

    baska_kiralama = Kiralama(
        kiralama_form_no="PF-2026/0064",
        firma_musteri_id=baska_musteri.id,
        makine_calisma_adresi="BASKA IS",
        kdv_orani=20,
    )
    db.session.add(baska_kiralama)
    db.session.flush()
    id_cakisan_kalem = KiralamaKalemi(
        kiralama_id=baska_kiralama.id,
        kiralama_baslangici=date(2026, 3, 28),
        kiralama_bitis=date(2026, 3, 29),
        kiralama_brm_fiyat=Decimal("1000.00"),
        is_active=True,
    )
    db.session.add(id_cakisan_kalem)
    db.session.flush()
    assert id_cakisan_kalem.id == nakliye.id

    hizmet = HizmetKaydi(
        firma_id=taseron.id,
        ozel_id=nakliye.id,
        tarih=date(2026, 3, 28),
        islem_tarihi=date(2026, 3, 28),
        tutar=Decimal("2500.00"),
        yon="gelen",
        aciklama="Nakliye Taşeron Gideri: IKITELLI - AVCILAR ()",
        kdv_orani=20,
    )
    db.session.add(hizmet)
    db.session.commit()

    rows = FirmaService.build_cari_rows(taseron, date(2026, 3, 28))
    legacy_row = next(row for row in rows if row["id"] == hizmet.id)

    assert legacy_row["islem_turu"] == "nakliye_tedarik"
    assert legacy_row["nakliye_id"] == nakliye.id
    assert legacy_row["kiralama_id"] is None
    assert legacy_row["toplam"] == -3000.0
    assert taseron.bakiye_ozeti["net_bakiye_kdvli"] == Decimal("-3000.000000")


def test_canonical_standalone_taseron_nakliye_gideri_cari_satirina_girer(app):
    musteri = _firma("CAGDAS YAPI", vergi_no="1111111111")
    taseron = _firma("GEYLANI ERCAN", is_tedarikci=True, vergi_no="2222222222")
    db.session.add_all([musteri, taseron])
    db.session.flush()

    nakliye = Nakliye(
        firma_id=musteri.id,
        tarih=date(2026, 3, 28),
        islem_tarihi=date(2026, 3, 28),
        guzergah="IKITELLI - AVCILAR",
        nakliye_tipi="taseron",
        taseron_firma_id=taseron.id,
        tutar=Decimal("3000.00"),
        taseron_maliyet=Decimal("2500.00"),
        kdv_orani=20,
    )
    nakliye.hesapla_ve_guncelle()
    db.session.add(nakliye)
    db.session.flush()

    hizmet = HizmetKaydi(
        firma_id=taseron.id,
        nakliye_id=nakliye.id,
        tarih=date(2026, 3, 28),
        islem_tarihi=date(2026, 3, 28),
        tutar=Decimal("2500.00"),
        yon="gelen",
        aciklama="Nakliye Taşeron Gideri: IKITELLI - AVCILAR ()",
        nakliye_alis_kdv=20,
    )
    db.session.add(hizmet)
    db.session.commit()

    rows = FirmaService.build_cari_rows(taseron, date(2026, 3, 28))
    row = next(row for row in rows if row["id"] == hizmet.id)

    assert row["islem_turu"] == "nakliye_tedarik"
    assert row["nakliye_id"] == nakliye.id
    assert row["kiralama_id"] is None
    assert row["toplam"] == -3000.0
    assert taseron.bakiye_ozeti["net_bakiye_kdvli"] == Decimal("-3000.000000")


def test_migration_only_normalizes_legacy_standalone_nakliye_rows(app):
    musteri = _firma("MUSTERI", vergi_no="1111111111")
    taseron = _firma("TASERON", is_tedarikci=True, vergi_no="2222222222")
    db.session.add_all([musteri, taseron])
    db.session.flush()

    nakliye = Nakliye(
        firma_id=musteri.id,
        tarih=date(2026, 4, 1),
        guzergah="A - B",
        nakliye_tipi="taseron",
        taseron_firma_id=taseron.id,
        tutar=Decimal("1200.00"),
        taseron_maliyet=Decimal("1000.00"),
    )
    db.session.add(nakliye)
    db.session.flush()

    kiralama = Kiralama(
        kiralama_form_no="PF-2026/0099",
        firma_musteri_id=musteri.id,
        makine_calisma_adresi="SAHA",
        kdv_orani=20,
    )
    db.session.add(kiralama)
    db.session.flush()
    kalem = KiralamaKalemi(
        kiralama_id=kiralama.id,
        kiralama_baslangici=date(2026, 4, 1),
        kiralama_bitis=date(2026, 4, 2),
        kiralama_brm_fiyat=Decimal("1000.00"),
        is_active=True,
    )
    db.session.add(kalem)
    db.session.flush()
    assert kalem.id == nakliye.id

    legacy = HizmetKaydi(
        firma_id=taseron.id,
        ozel_id=nakliye.id,
        tarih=date(2026, 4, 1),
        tutar=Decimal("1000.00"),
        yon="gelen",
        aciklama="Nakliye Taşeron Gideri: A - B ()",
    )
    kalem_taseron = HizmetKaydi(
        firma_id=taseron.id,
        ozel_id=kalem.id,
        tarih=date(2026, 4, 1),
        tutar=Decimal("700.00"),
        yon="gelen",
        aciklama="Taşeron Nakliye Bedeli (PM31) - PF-2026/0099",
    )
    kalem_fark = HizmetKaydi(
        firma_id=musteri.id,
        ozel_id=kalem.id,
        tarih=date(2026, 4, 1),
        tutar=Decimal("200.00"),
        yon="giden",
        aciklama="Nakliye Farkı (PM31) - Form: PF-2026/0099",
    )
    db.session.add_all([legacy, kalem_taseron, kalem_fark])
    db.session.commit()

    migration = _load_normalization_migration()
    migration.op = _FakeAlembicOp(db.session.connection())
    migration.upgrade()
    db.session.expire_all()

    assert legacy.nakliye_id == nakliye.id
    assert legacy.ozel_id is None
    assert kalem_taseron.nakliye_id is None
    assert kalem_taseron.ozel_id == kalem.id
    assert kalem_fark.nakliye_id is None
    assert kalem_fark.ozel_id == kalem.id


def test_nakliye_cari_temizle_kalem_bazli_kayitlara_dokunmaz(app):
    musteri = _firma("MUSTERI", vergi_no="1111111111")
    taseron = _firma("TASERON", is_tedarikci=True, vergi_no="2222222222")
    db.session.add_all([musteri, taseron])
    db.session.flush()

    nakliye = Nakliye(firma_id=musteri.id, tarih=date(2026, 4, 1), guzergah="A - B")
    db.session.add(nakliye)
    db.session.flush()
    kiralama = Kiralama(kiralama_form_no="PF-2026/0100", firma_musteri_id=musteri.id, kdv_orani=20)
    db.session.add(kiralama)
    db.session.flush()
    kalem = KiralamaKalemi(
        kiralama_id=kiralama.id,
        kiralama_baslangici=date(2026, 4, 1),
        kiralama_bitis=date(2026, 4, 2),
        kiralama_brm_fiyat=Decimal("1000.00"),
    )
    db.session.add(kalem)
    db.session.flush()
    assert kalem.id == nakliye.id

    canonical = HizmetKaydi(
        firma_id=taseron.id,
        nakliye_id=nakliye.id,
        tarih=date(2026, 4, 1),
        tutar=Decimal("1000.00"),
        yon="gelen",
        aciklama="Nakliye Taşeron Gideri: A - B ()",
    )
    kalem_taseron = HizmetKaydi(
        firma_id=taseron.id,
        ozel_id=kalem.id,
        tarih=date(2026, 4, 1),
        tutar=Decimal("700.00"),
        yon="gelen",
        aciklama="Taşeron Nakliye Bedeli (PM31) - PF-2026/0100",
    )
    kalem_fark = HizmetKaydi(
        firma_id=musteri.id,
        ozel_id=kalem.id,
        tarih=date(2026, 4, 1),
        tutar=Decimal("200.00"),
        yon="giden",
        aciklama="Nakliye Farkı (PM31) - Form: PF-2026/0100",
    )
    db.session.add_all([canonical, kalem_taseron, kalem_fark])
    db.session.commit()

    canonical_id = canonical.id
    kalem_taseron_id = kalem_taseron.id
    kalem_fark_id = kalem_fark.id

    CariServis.nakliye_cari_temizle(nakliye.id)
    db.session.commit()

    assert db.session.get(HizmetKaydi, canonical_id) is None
    assert db.session.get(HizmetKaydi, kalem_taseron_id).ozel_id == kalem.id
    assert db.session.get(HizmetKaydi, kalem_fark_id).ozel_id == kalem.id


def test_taseron_maliyet_senkronize_et_legacy_satiri_normalize_eder(app):
    musteri = _firma("MUSTERI", vergi_no="1111111111")
    taseron = _firma("TASERON", is_tedarikci=True, vergi_no="2222222222")
    db.session.add_all([musteri, taseron])
    db.session.flush()

    nakliye = Nakliye(
        firma_id=musteri.id,
        tarih=date(2026, 4, 1),
        guzergah="A - B",
        nakliye_tipi="taseron",
        taseron_firma_id=taseron.id,
        tutar=Decimal("1500.00"),
        taseron_maliyet=Decimal("900.00"),
        taseron_kdv_orani=20,
    )
    db.session.add(nakliye)
    db.session.flush()
    legacy = HizmetKaydi(
        firma_id=taseron.id,
        ozel_id=nakliye.id,
        tarih=date(2026, 4, 1),
        tutar=Decimal("800.00"),
        yon="gelen",
        aciklama="Nakliye Taşeron Gideri: A - B ()",
    )
    db.session.add(legacy)
    db.session.commit()

    CariServis.taseron_maliyet_senkronize_et(nakliye)
    db.session.commit()

    kayitlar = HizmetKaydi.query.filter_by(yon="gelen").all()
    assert len(kayitlar) == 1
    assert kayitlar[0].id == legacy.id
    assert kayitlar[0].nakliye_id == nakliye.id
    assert kayitlar[0].ozel_id is None
    assert kayitlar[0].tutar == Decimal("900.00")


def test_taseron_maliyet_senkronize_et_yeni_kaydi_nakliye_id_ile_olusturur(app):
    musteri = _firma("MUSTERI", vergi_no="1111111111")
    taseron = _firma("TASERON", is_tedarikci=True, vergi_no="2222222222")
    db.session.add_all([musteri, taseron])
    db.session.flush()

    nakliye = Nakliye(
        firma_id=musteri.id,
        tarih=date(2026, 4, 1),
        guzergah="A - B",
        nakliye_tipi="taseron",
        taseron_firma_id=taseron.id,
        tutar=Decimal("1500.00"),
        taseron_maliyet=Decimal("900.00"),
        taseron_kdv_orani=20,
    )
    db.session.add(nakliye)
    db.session.flush()

    CariServis.taseron_maliyet_senkronize_et(nakliye)
    db.session.commit()

    hizmet = HizmetKaydi.query.filter_by(yon="gelen").one()
    assert hizmet.nakliye_id == nakliye.id
    assert hizmet.ozel_id is None
    assert hizmet.firma_id == taseron.id


def test_sonlandir_donus_taseron_giderini_idempotent_gunceller(app):
    musteri = _firma("PAK MEKANIK", vergi_no="3333333333")
    taseron = _firma("GEYLANI ERCAN", is_tedarikci=True, vergi_no="4444444444")
    db.session.add_all([musteri, taseron])
    db.session.flush()

    kiralama = Kiralama(
        kiralama_form_no="PF-2026/0073",
        firma_musteri_id=musteri.id,
        makine_calisma_adresi="ISTINYE PARK",
        kdv_orani=20,
    )
    db.session.add(kiralama)
    db.session.flush()

    kalem = KiralamaKalemi(
        kiralama_id=kiralama.id,
        kiralama_baslangici=date(2026, 4, 13),
        kiralama_bitis=date(2026, 5, 3),
        kiralama_brm_fiyat=Decimal("1000.00"),
        nakliye_satis_fiyat=Decimal("4000.00"),
        donus_nakliye_fatura_et=True,
        donus_nakliye_satis_fiyat=Decimal("2000.00"),
        is_harici_nakliye=True,
        is_oz_mal_nakliye=False,
        nakliye_tedarikci_id=taseron.id,
        nakliye_alis_fiyat=Decimal("1500.00"),
        sonlandirildi=False,
        is_active=True,
    )
    db.session.add(kalem)
    db.session.flush()

    eski_1 = HizmetKaydi(
        firma_id=taseron.id,
        tarih=date(2026, 5, 3),
        islem_tarihi=date(2026, 5, 3),
        tutar=Decimal("3000.00"),
        yon="gelen",
        fatura_no=kiralama.kiralama_form_no,
        ozel_id=kalem.id,
        aciklama="Dönüş Nakliye: PM31 - İkitelli",
        kdv_orani=20,
    )
    eski_2 = HizmetKaydi(
        firma_id=taseron.id,
        tarih=date(2026, 5, 3),
        islem_tarihi=date(2026, 5, 3),
        tutar=Decimal("1500.00"),
        yon="gelen",
        fatura_no=kiralama.kiralama_form_no,
        ozel_id=kalem.id,
        aciklama="Dönüş Nakliye: PM31 - İkitelli",
        kdv_orani=20,
    )
    gidis = HizmetKaydi(
        firma_id=taseron.id,
        tarih=date(2026, 4, 13),
        islem_tarihi=date(2026, 4, 13),
        tutar=Decimal("1500.00"),
        yon="gelen",
        fatura_no=kiralama.kiralama_form_no,
        ozel_id=kalem.id,
        aciklama="Taşeron Nakliye Bedeli (PM31) - PF-2026/0073",
        kdv_orani=20,
    )
    db.session.add_all([eski_1, eski_2, gidis])
    db.session.commit()

    KiralamaKalemiService.sonlandir(
        kalem.id,
        "2026-05-03",
        "tedarikci",
        is_harici_nakliye=True,
        nakliye_tedarikci_id=taseron.id,
        nakliye_alis_fiyat="1500.00",
        donus_nakliye_satis_fiyat="2000.00",
    )
    KiralamaKalemiService.sonlandir(
        kalem.id,
        "2026-05-03",
        "tedarikci",
        is_harici_nakliye=True,
        nakliye_tedarikci_id=taseron.id,
        nakliye_alis_fiyat="1500.00",
        donus_nakliye_satis_fiyat="2000.00",
    )

    aktif_donuslar = HizmetKaydi.query.filter(
        HizmetKaydi.firma_id == taseron.id,
        HizmetKaydi.fatura_no == "PF-2026/0073",
        HizmetKaydi.ozel_id == kalem.id,
        HizmetKaydi.yon == "gelen",
        HizmetKaydi.aciklama.like("Dönüş Nakliye:%"),
        HizmetKaydi.is_deleted == False,
    ).all()
    aktif_gidisler = HizmetKaydi.query.filter(
        HizmetKaydi.firma_id == taseron.id,
        HizmetKaydi.fatura_no == "PF-2026/0073",
        HizmetKaydi.ozel_id == kalem.id,
        HizmetKaydi.yon == "gelen",
        HizmetKaydi.aciklama.like("Taşeron Nakliye Bedeli%"),
        HizmetKaydi.is_deleted == False,
    ).all()

    assert len(aktif_donuslar) == 1
    assert aktif_donuslar[0].tutar == Decimal("1500.00")
    assert len(aktif_gidisler) == 1
