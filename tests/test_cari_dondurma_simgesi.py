from datetime import date, timedelta
from decimal import Decimal

from app.extensions import db
from app.filo.models import Ekipman
from app.firmalar.models import Firma
from app.kiralama.models import Kiralama, KiralamaKalemi, KiralamaKalemDondurma
from app.subeler.models import Sube
from app.services.firma_services import FirmaService
from app.services.kiralama_services import KiralamaService


def _firma(name, *, is_musteri=True, is_tedarikci=False, vergi_no=None):
    return Firma(
        firma_adi=name,
        yetkili_adi="Yetkili",
        iletisim_bilgileri="Adres",
        vergi_dairesi="VD",
        vergi_no=vergi_no or name[:10].upper().ljust(10, "0"),
        is_musteri=is_musteri,
        is_tedarikci=is_tedarikci,
        is_active=True,
    )


def _ekipman(kod, sube):
    return Ekipman(
        kod=kod,
        yakit="Elektrik",
        tipi="Platform",
        marka="Pimaks",
        model="Model",
        seri_no=f"SN-{kod}",
        calisma_yuksekligi=15,
        kaldirma_kapasitesi=250,
        uretim_yili=2024,
        calisma_durumu="bosta",
        sube_id=sube.id,
    )


def _kiralama_kurulumu(*, harici=False, tedarikci=None):
    musteri = _firma("EMIN FIL", vergi_no="DONDUR0001")
    sube = Sube(isim="Merkez")
    db.session.add_all([musteri, sube])
    db.session.flush()

    kiralama = Kiralama(
        kiralama_form_no="PF-2026/0140",
        firma_musteri_id=musteri.id,
        makine_calisma_adresi="Saha",
        kdv_orani=20,
    )
    db.session.add(kiralama)
    db.session.flush()

    if harici:
        kalem = KiralamaKalemi(
            kiralama_id=kiralama.id,
            is_dis_tedarik_ekipman=True,
            harici_ekipman_marka="HAULOTTE",
            harici_ekipman_model="HA15IP",
            harici_ekipman_tedarikci_id=tedarikci.id if tedarikci else None,
            kiralama_baslangici=date(2026, 6, 1),
            kiralama_bitis=date(2026, 6, 30),
            kiralama_brm_fiyat=Decimal("1000.00"),
            kiralama_alis_fiyat=Decimal("800.00"),
            kiralama_alis_kdv=20,
        )
    else:
        pm29 = _ekipman("PM29", sube)
        db.session.add(pm29)
        db.session.flush()
        kalem = KiralamaKalemi(
            kiralama_id=kiralama.id,
            ekipman_id=pm29.id,
            kiralama_baslangici=date(2026, 6, 1),
            kiralama_bitis=date(2026, 6, 30),
            kiralama_brm_fiyat=Decimal("1000.00"),
        )

    db.session.add(kalem)
    db.session.flush()
    return musteri, tedarikci, kalem


def _dondurma_ekle(kalem, bas, bit, *, tedarikci_alis_dondur=False):
    muaf = (bit - bas).days + 1
    kayit = KiralamaKalemDondurma(
        kalem_id=kalem.id,
        baslangic_tarihi=bas,
        bitis_tarihi=bit,
        muaf_gun_sayisi=muaf,
        tedarikci_alis_dondur=tedarikci_alis_dondur,
    )
    db.session.add(kayit)
    db.session.commit()
    return kayit


def _kiralama_row(rows, kalem_id):
    matches = [
        r for r in rows
        if r.get("islem_turu") == "kiralama" and r.get("id") == kalem_id
    ]
    assert len(matches) == 1
    return matches[0]


def _harici_row(rows, kalem_id):
    matches = [
        r for r in rows
        if r.get("islem_turu") == "harici_kiralama" and r.get("id") == kalem_id
    ]
    assert len(matches) == 1
    return matches[0]


def test_kalem_dondurma_aktif_mi_referans_aralikta(app):
    musteri, _, kalem = _kiralama_kurulumu()
    _dondurma_ekle(kalem, date(2026, 6, 10), date(2026, 6, 14))

    assert KiralamaService.kalem_dondurma_aktif_mi(kalem, date(2026, 6, 12)) is True
    assert KiralamaService.kalem_dondurma_aktif_mi(kalem, date(2026, 6, 10)) is True
    assert KiralamaService.kalem_dondurma_aktif_mi(kalem, date(2026, 6, 14)) is True


def test_kalem_dondurma_aktif_mi_dondurma_bittikten_sonra(app):
    musteri, _, kalem = _kiralama_kurulumu()
    _dondurma_ekle(kalem, date(2026, 6, 10), date(2026, 6, 14))

    assert KiralamaService.kalem_dondurma_aktif_mi(kalem, date(2026, 6, 15)) is False


def test_build_cari_rows_kiralama_dondurma_aktif_bayragi(app):
    musteri, _, kalem = _kiralama_kurulumu()
    _dondurma_ekle(kalem, date(2026, 6, 10), date(2026, 6, 14))

    musteri = db.session.get(Firma, musteri.id)
    rows_aktif = FirmaService.build_cari_rows(musteri, date(2026, 6, 12))
    row = _kiralama_row(rows_aktif, kalem.id)
    assert row["dondurma_aktif"] is True

    rows_bitmis = FirmaService.build_cari_rows(musteri, date(2026, 6, 15))
    row = _kiralama_row(rows_bitmis, kalem.id)
    assert row["dondurma_aktif"] is False


def test_build_cari_rows_harici_tedarik_dondurma_sadece_alis_tarafi(app):
    tedarikci = _firma("TASERON TEDARIK", is_musteri=False, is_tedarikci=True, vergi_no="DONDUR0002")
    db.session.add(tedarikci)
    db.session.flush()

    musteri, tedarikci, kalem = _kiralama_kurulumu(harici=True, tedarikci=tedarikci)
    _dondurma_ekle(kalem, date(2026, 6, 10), date(2026, 6, 14), tedarikci_alis_dondur=False)

    tedarikci = db.session.get(Firma, tedarikci.id)
    rows = FirmaService.build_cari_rows(tedarikci, date(2026, 6, 12))
    row = _harici_row(rows, kalem.id)
    assert row["dondurma_aktif"] is False


def test_build_cari_rows_harici_tedarik_alis_dondurma_aktif(app):
    tedarikci = _firma("TASERON TEDARIK 2", is_musteri=False, is_tedarikci=True, vergi_no="DONDUR0003")
    db.session.add(tedarikci)
    db.session.flush()

    musteri, tedarikci, kalem = _kiralama_kurulumu(harici=True, tedarikci=tedarikci)
    _dondurma_ekle(kalem, date(2026, 6, 10), date(2026, 6, 14), tedarikci_alis_dondur=True)

    tedarikci = db.session.get(Firma, tedarikci.id)
    rows_aktif = FirmaService.build_cari_rows(tedarikci, date(2026, 6, 12))
    row = _harici_row(rows_aktif, kalem.id)
    assert row["dondurma_aktif"] is True

    rows_bitmis = FirmaService.build_cari_rows(tedarikci, date(2026, 6, 15))
    row = _harici_row(rows_bitmis, kalem.id)
    assert row["dondurma_aktif"] is False
