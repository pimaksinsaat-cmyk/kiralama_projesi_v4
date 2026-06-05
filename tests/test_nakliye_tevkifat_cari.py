from datetime import date
from decimal import Decimal

from app.extensions import db
from app.firmalar.models import Firma
from app.kiralama.models import Kiralama
from app.nakliyeler.models import Nakliye
from app.services.cari_services import _sync_firma_bakiye
from app.services.firma_services import FirmaService
from app.services.nakliye_services import CariServis


def _firma(name, *, vergi_no):
    return Firma(
        firma_adi=name,
        yetkili_adi="Yetkili",
        iletisim_bilgileri="Adres",
        vergi_dairesi="VD",
        vergi_no=vergi_no,
        is_musteri=True,
        is_tedarikci=False,
        is_active=True,
    )


def _kiralama(musteri, form_no):
    return Kiralama(
        firma_musteri_id=musteri.id,
        kiralama_form_no=form_no,
        kiralama_olusturma_tarihi=date(2026, 1, 12),
        kdv_orani=20,
    )


def _nakliye(musteri, kiralama, *, tutar, kdv_orani=20, tevkifat_orani=None):
    return Nakliye(
        firma_id=musteri.id,
        kiralama_id=kiralama.id,
        tarih=date(2026, 1, 12),
        islem_tarihi=date(2026, 1, 12),
        guzergah="Sube goturuldu",
        tutar=Decimal(str(tutar)),
        kdv_orani=kdv_orani,
        tevkifat_orani=tevkifat_orani,
        nakliye_tipi="oz_mal",
        is_active=True,
    )


def _nakliye_row(rows, nakliye_id):
    matches = [r for r in rows if r.get("nakliye_id") == nakliye_id]
    assert len(matches) == 1, f"Beklenen tek nakliye satırı, bulunan: {len(matches)}"
    return matches[0]


def test_build_cari_rows_nakliye_tevkifat_kapali_brut_kdv(app):
    musteri = _firma("TEVKIFATSIZ MUSTERI", vergi_no="TEVKIF0001")
    db.session.add(musteri)
    db.session.flush()

    kiralama = _kiralama(musteri, "PF-2026/0991")
    db.session.add(kiralama)
    db.session.flush()

    nakliye = _nakliye(musteri, kiralama, tutar=1000, tevkifat_orani=None)
    db.session.add(nakliye)
    db.session.flush()
    nakliye.hesapla_ve_guncelle()

    CariServis.musteri_nakliye_senkronize_et(nakliye)
    db.session.commit()

    rows = FirmaService.build_cari_rows(musteri, date(2026, 6, 1))
    row = _nakliye_row(rows, nakliye.id)

    assert row["kdv_orani"] == 20
    assert row["toplam"] == 1200.0


def test_build_cari_rows_nakliye_tevkifat_acik_net_kdv(app):
    musteri = _firma("TEVKIFATLI MUSTERI", vergi_no="TEVKIF0002")
    db.session.add(musteri)
    db.session.flush()

    kiralama = _kiralama(musteri, "PF-2026/0992")
    db.session.add(kiralama)
    db.session.flush()

    nakliye = _nakliye(musteri, kiralama, tutar=1000, tevkifat_orani="2/10")
    db.session.add(nakliye)
    db.session.flush()
    nakliye.hesapla_ve_guncelle()

    CariServis.musteri_nakliye_senkronize_et(nakliye)
    db.session.commit()

    rows = FirmaService.build_cari_rows(musteri, date(2026, 6, 1))
    row = _nakliye_row(rows, nakliye.id)

    assert row["kdv_orani"] == 16
    assert row["toplam"] == 1160.0
    assert row["tevkifat_str"] == "2/10"


def test_bakiye_ozeti_ve_cache_tevkifatli_nakliye_ile_uyumlu(app):
    musteri = _firma("TEVKIFAT CACHE MUSTERI", vergi_no="TEVKIF0003")
    db.session.add(musteri)
    db.session.flush()

    kiralama = _kiralama(musteri, "PF-2026/0993")
    db.session.add(kiralama)
    db.session.flush()

    nakliye = _nakliye(musteri, kiralama, tutar=1000, tevkifat_orani="2/10")
    db.session.add(nakliye)
    db.session.flush()
    nakliye.hesapla_ve_guncelle()

    CariServis.musteri_nakliye_senkronize_et(nakliye)
    db.session.commit()

    _sync_firma_bakiye(musteri.id)
    db.session.refresh(musteri)

    assert musteri.cari_bakiye_kdvli == Decimal("1160.00")
    assert musteri.bakiye_ozeti["net_bakiye_kdvli"] == Decimal("1160.000000")
