from datetime import date
from decimal import Decimal

from app.cari.models import HizmetKaydi
from app.extensions import db
from app.firmalar.models import Firma
from app.kiralama.models import Kiralama, KiralamaKalemi
from app.nakliyeler.models import Nakliye
from app.services.firma_services import FirmaService
from app.services.kiralama_services import KiralamaService


def _firma(name, *, is_musteri, is_tedarikci):
    return Firma(
        firma_adi=name,
        yetkili_adi="Yetkili",
        iletisim_bilgileri="Adres",
        vergi_dairesi="VD",
        vergi_no=f"{name[:8].upper():<10}".replace(" ", "0"),
        is_musteri=is_musteri,
        is_tedarikci=is_tedarikci,
        is_active=True,
    )


def test_external_transport_purchase_withholding_stays_on_supplier_cari(app):
    customer = _firma("TEV CUSTOMER", is_musteri=True, is_tedarikci=False)
    supplier = _firma("TEV SUPPLIER", is_musteri=False, is_tedarikci=True)
    db.session.add_all([customer, supplier])
    db.session.flush()

    kiralama = Kiralama(
        kiralama_form_no="PF-TEST-TEV-001",
        firma_musteri_id=customer.id,
        makine_calisma_adresi="Saha",
        kdv_orani=20,
    )
    db.session.add(kiralama)
    db.session.flush()
    kalem = KiralamaKalemi(
        kiralama_id=kiralama.id,
        kiralama_baslangici=date(2026, 8, 1),
        kiralama_bitis=date(2026, 8, 1),
        kiralama_brm_fiyat=Decimal("1000"),
        nakliye_satis_fiyat=Decimal("5000"),
        nakliye_satis_kdv=20,
        nakliye_alis_fiyat=Decimal("18000"),
        nakliye_alis_kdv=20,
        nakliye_alis_tevkifat_oran="2/10",
        nakliye_satis_tevkifat_oran=None,
        is_harici_nakliye=True,
        is_oz_mal_nakliye=False,
        nakliye_tedarikci_id=supplier.id,
    )
    db.session.add(kalem)
    db.session.flush()

    KiralamaService._create_nakliye_ve_cari(
        kiralama, kalem, "PM39", date(2026, 8, 1)
    )
    db.session.flush()
    nakliye = Nakliye.query.filter_by(kiralama_id=kiralama.id).one()
    customer_hizmet = HizmetKaydi.query.filter_by(
        nakliye_id=nakliye.id, yon="giden"
    ).first()
    assert customer_hizmet is None  # müşteri senkronu ayrı adımın sorumluluğunda

    supplier_hizmet = HizmetKaydi.query.filter_by(
        ozel_id=kalem.id, yon="gelen"
    ).one()
    assert supplier_hizmet.nakliye_alis_kdv == 16

    from app.services.nakliye_services import CariServis

    CariServis.musteri_nakliye_senkronize_et(nakliye)
    db.session.commit()
    customer_hizmet = HizmetKaydi.query.filter_by(
        nakliye_id=nakliye.id, yon="giden"
    ).one()
    assert customer_hizmet.kdv_orani == 20

    supplier_rows = FirmaService.build_cari_rows(supplier, date(2026, 8, 2))
    supplier_row = next(r for r in supplier_rows if r["id"] == supplier_hizmet.id)
    assert supplier_row["kdv_orani"] == 16
    assert supplier_row["toplam"] == -Decimal("20880")
