from datetime import date
from decimal import Decimal

from app.cari.models import HizmetKaydi
from app.extensions import db
from app.firmalar.models import Firma
from app.kiralama.models import Kiralama, KiralamaKalemi
from app.nakliyeler.models import Nakliye
from app.services.firma_services import FirmaService
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


def test_legacy_standalone_taseron_nakliye_gideri_cari_satirina_girer(app):
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
    )
    nakliye.hesapla_ve_guncelle()
    db.session.add(nakliye)
    db.session.flush()

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
    assert legacy_row["toplam"] == -3000.0
    assert taseron.bakiye_ozeti["net_bakiye_kdvli"] == Decimal("-3000.000000")


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
