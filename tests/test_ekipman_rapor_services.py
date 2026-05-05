from datetime import date
from decimal import Decimal

from app.extensions import db
from app.filo.models import Ekipman
from app.firmalar.models import Firma
from app.kiralama.models import Kiralama, KiralamaKalemi
from app.services.ekipman_rapor_services import EkipmanRaporuService


def _create_rental_fixture(kod="PM 05", sonlandirildi=False):
    firma = Firma(
        firma_adi="Test Musteri",
        yetkili_adi="Yetkili",
        iletisim_bilgileri="Telefon",
        vergi_dairesi="Test",
        vergi_no=f"VN-{kod}",
    )
    ekipman = Ekipman(
        kod=kod,
        yakit="Elektrikli",
        tipi="Platform",
        marka="Pimaks",
        model="Test",
        seri_no=f"SN-{kod}",
        calisma_yuksekligi=10,
        kaldirma_kapasitesi=250,
        uretim_yili=2024,
        calisma_durumu="kirada" if not sonlandirildi else "bosta",
    )
    kiralama = Kiralama(
        kiralama_form_no=f"KF-{kod}",
        firma_musteri=firma,
        doviz_kuru_usd=Decimal("40"),
        doviz_kuru_eur=Decimal("45"),
    )
    kalem = KiralamaKalemi(
        kiralama=kiralama,
        ekipman=ekipman,
        kiralama_baslangici=date(2026, 4, 1),
        kiralama_bitis=date(2026, 4, 30),
        kiralama_brm_fiyat=Decimal("1000"),
        sonlandirildi=sonlandirildi,
        is_active=True,
    )
    db.session.add_all([firma, ekipman, kiralama, kalem])
    db.session.commit()
    return ekipman


def test_kiralama_detaylari_lists_active_rental_when_planned_end_is_before_range(app):
    ekipman = _create_rental_fixture()

    detaylar = EkipmanRaporuService.get_kiralama_detaylari(
        ekipman.id,
        date(2026, 5, 1),
        date(2026, 5, 2),
    )

    assert len(detaylar) == 1
    assert detaylar[0]["kiralama_no"] == "KF-PM 05"
    assert detaylar[0]["bitis_tarihi"] == date(2026, 5, 2)
    assert detaylar[0]["gun_sayisi"] == 2
    assert detaylar[0]["gelir_try"] == 2000


def test_kiralama_detaylari_excludes_closed_rental_before_range(app):
    ekipman = _create_rental_fixture(kod="PM 06", sonlandirildi=True)

    detaylar = EkipmanRaporuService.get_kiralama_detaylari(
        ekipman.id,
        date(2026, 5, 1),
        date(2026, 5, 2),
    )

    assert detaylar == []
