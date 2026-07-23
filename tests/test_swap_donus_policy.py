from datetime import date
from decimal import Decimal
import uuid

from app.cari.models import HizmetKaydi
from app.extensions import db
from app.firmalar.models import Firma
from app.kiralama.models import Kiralama, KiralamaKalemi
from app.makinedegisim.models import MakineDegisim
from app.nakliyeler.models import Nakliye
from app.services.kiralama_services import KiralamaService


def _policy_fixture():
    firma = Firma(
        firma_adi=f"Swap Policy {uuid.uuid4().hex[:8]}",
        yetkili_adi="Yetkili",
        iletisim_bilgileri="Adres",
        vergi_dairesi="Test VD",
        vergi_no=f"P{uuid.uuid4().hex[:10].upper()}",
        is_musteri=True,
        is_tedarikci=False,
    )
    db.session.add(firma)
    db.session.flush()
    kiralama = Kiralama(
        kiralama_form_no=f"PF-POLICY-{uuid.uuid4().hex[:8]}",
        firma_musteri_id=firma.id,
        kdv_orani=20,
    )
    db.session.add(kiralama)
    db.session.flush()
    eski = KiralamaKalemi(
        kiralama_id=kiralama.id,
        kiralama_baslangici=date.today(),
        kiralama_bitis=date.today(),
        kiralama_brm_fiyat=Decimal("100.00"),
        is_active=False,
        sonlandirildi=True,
    )
    yeni = KiralamaKalemi(
        kiralama_id=kiralama.id,
        parent_id=None,
        kiralama_baslangici=date.today(),
        kiralama_bitis=date.today() + __import__('datetime').timedelta(days=10),
        kiralama_brm_fiyat=Decimal("100.00"),
        is_active=True,
        sonlandirildi=False,
    )
    db.session.add_all([eski, yeni])
    db.session.flush()
    return firma, kiralama, eski, yeni


def _add_donus(firma, kiralama, kalem, tutar):
    sefer = Nakliye(
        kiralama_id=kiralama.id,
        firma_id=firma.id,
        tarih=date.today(),
        islem_tarihi=date.today(),
        guzergah="Dönüş güzergahı",
        tutar=tutar,
        aciklama=f"Dönüş: {kiralama.kiralama_form_no} #{kalem.id}",
        nakliye_tipi="oz_mal",
        is_active=True,
    )
    db.session.add(sefer)
    db.session.flush()
    cari = HizmetKaydi(
        firma_id=firma.id,
        nakliye_id=sefer.id,
        tarih=date.today(),
        islem_tarihi=date.today(),
        tutar=tutar,
        yon="giden",
        ozel_id=kalem.id,
        aciklama="Nakliye Hizmeti: dönüş",
        kaynak="musteri_nakliye",
    )
    db.session.add(cari)
    db.session.flush()
    return sefer, cari


def test_serviste_swap_without_fee_soft_deletes_old_donus(app):
    with app.app_context():
        firma, kiralama, eski, yeni = _policy_fixture()
        swap = MakineDegisim(
            kiralama_id=kiralama.id,
            eski_kalem_id=eski.id,
            yeni_kalem_id=yeni.id,
            neden="serviste",
        )
        db.session.add(swap)
        sefer, cari = _add_donus(firma, kiralama, eski, Decimal("1500.00"))
        db.session.commit()

        KiralamaService.reconcile_swap_donus_nakliye(
            eski,
            neden="serviste",
            explicit_sales=Decimal("0.00"),
        )
        db.session.commit()

        assert sefer.is_active is False
        assert cari.is_deleted is True
        assert cari.is_active is False


def test_bosta_swap_preserves_existing_customer_return_fee(app):
    with app.app_context():
        firma, kiralama, eski, yeni = _policy_fixture()
        swap = MakineDegisim(
            kiralama_id=kiralama.id,
            eski_kalem_id=eski.id,
            yeni_kalem_id=yeni.id,
            neden="bosta",
        )
        db.session.add(swap)
        sefer, cari = _add_donus(firma, kiralama, eski, Decimal("2500.00"))
        db.session.commit()

        KiralamaService.reconcile_swap_donus_nakliye(
            eski,
            neden="bosta",
            explicit_sales=Decimal("0.00"),
        )
        db.session.commit()

        assert sefer.is_active is True
        assert cari.is_deleted is False


def test_serviste_positive_swap_fee_overrides_free_reason(app):
    with app.app_context():
        firma, kiralama, eski, yeni = _policy_fixture()
        swap = MakineDegisim(
            kiralama_id=kiralama.id,
            eski_kalem_id=eski.id,
            yeni_kalem_id=yeni.id,
            neden="serviste",
        )
        db.session.add(swap)
        sefer, cari = _add_donus(firma, kiralama, eski, Decimal("1500.00"))
        db.session.commit()

        KiralamaService.reconcile_swap_donus_nakliye(
            eski,
            neden="serviste",
            explicit_sales=Decimal("2000.00"),
        )
        db.session.commit()

        # Eski dönüş hareketi kapanır; pozitif ücret yeni swap seferi tarafından
        # oluşturulacağından aynı kalem için çift müşteri hareketi kalmaz.
        assert sefer.is_active is False
        assert cari.is_deleted is True
