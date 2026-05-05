from datetime import date
from decimal import Decimal

from app.extensions import db
from app.filo.models import BakimKaydi, Ekipman
from app.filo.forms import EkipmanForm
from app.firmalar.models import Firma
from app.kiralama.models import Kiralama, KiralamaKalemi
from app.services.ekipman_rapor_services import EkipmanRaporuService
from app.services.raporlama_services import RaporlamaService


def _create_machine(kod, filoya_giris_tarihi, calisma_durumu="bosta"):
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
        calisma_durumu=calisma_durumu,
        filoya_giris_tarihi=filoya_giris_tarihi,
        is_active=True,
    )
    db.session.add(ekipman)
    db.session.commit()
    return ekipman


def _add_rental(ekipman, start_date, end_date, price="1000"):
    firma = Firma(
        firma_adi=f"Test Musteri {ekipman.kod}",
        yetkili_adi="Yetkili",
        iletisim_bilgileri="Telefon",
        vergi_dairesi="Test",
        vergi_no=f"VN-{ekipman.kod}",
    )
    kiralama = Kiralama(
        kiralama_form_no=f"KF-{ekipman.kod}",
        firma_musteri=firma,
        kdv_orani=20,
    )
    kalem = KiralamaKalemi(
        kiralama=kiralama,
        ekipman=ekipman,
        kiralama_baslangici=start_date,
        kiralama_bitis=end_date,
        kiralama_brm_fiyat=Decimal(price),
        sonlandirildi=False,
        is_active=True,
    )
    db.session.add_all([firma, kiralama, kalem])
    db.session.commit()
    return kalem


def test_machine_utilization_available_days_start_at_filoya_giris_tarihi(app):
    ekipman = _create_machine("PM-RP-01", date(2026, 4, 1))
    _add_rental(ekipman, date(2026, 4, 1), date(2026, 4, 15))

    metrics, totals = RaporlamaService._calculate_machine_metrics(
        [ekipman],
        date(2026, 1, 1),
        date(2026, 12, 31),
    )

    assert metrics[ekipman.id]["available_days"] == 275
    assert metrics[ekipman.id]["work_days"] == 15
    assert round(metrics[ekipman.id]["utilization_pct"], 2) == round(15 / 275 * 100, 2)
    assert totals["available_days"] == 275
    assert totals["work_days"] == 15


def test_machine_utilization_is_zero_when_report_ends_before_filoya_giris_tarihi(app):
    ekipman = _create_machine("PM-RP-02", date(2026, 4, 1))
    _add_rental(ekipman, date(2026, 2, 1), date(2026, 2, 15))

    metrics, totals = RaporlamaService._calculate_machine_metrics(
        [ekipman],
        date(2026, 1, 1),
        date(2026, 3, 31),
    )

    assert metrics[ekipman.id]["available_days"] == 0
    assert metrics[ekipman.id]["work_days"] == 0
    assert metrics[ekipman.id]["utilization_pct"] == 0.0
    assert totals["available_days"] == 0
    assert totals["work_days"] == 0


def test_service_status_counts_as_active_and_service_days_do_not_reduce_availability(app):
    ekipman = _create_machine("PM-RP-03", date(2026, 1, 1), calisma_durumu="serviste")
    _add_rental(ekipman, date(2026, 1, 10), date(2026, 1, 14))
    db.session.add(
        BakimKaydi(
            ekipman=ekipman,
            tarih=date(2026, 1, 20),
            bakim_tipi="ariza",
            servis_tipi="ic_servis",
            durum="acik",
        )
    )
    db.session.commit()

    metrics, totals = RaporlamaService._calculate_machine_metrics(
        [ekipman],
        date(2026, 1, 1),
        date(2026, 1, 31),
    )

    assert totals["machine_count"] == 1
    assert metrics[ekipman.id]["available_days"] == 31
    assert metrics[ekipman.id]["work_days"] == 5
    assert round(metrics[ekipman.id]["utilization_pct"], 2) == round(5 / 31 * 100, 2)


def test_ekipman_form_requires_filoya_giris_tarihi(app):
    with app.test_request_context(method="POST", data={
        "kod": "PM-RP-04",
        "tipi": "MAKAS",
        "marka": "Pimaks",
        "model": "Test",
        "seri_no": "SN-PM-RP-04",
        "uretim_yili": "2024",
        "calisma_yuksekligi": "10",
        "kaldirma_kapasitesi": "250",
        "yakit": "Dizel",
        "sube_id": "1",
        "para_birimi": "TRY",
    }):
        form = EkipmanForm()
        form.sube_id.choices = [(1, "Merkez")]

        assert not form.validate()
        assert "filoya_giris_tarihi" in form.errors


def test_finansal_ozet_uses_filoya_giris_tarihi_as_temin_tarihi(app):
    ekipman = _create_machine("PM-RP-05", date(2026, 3, 15))

    ozet = EkipmanRaporuService.get_finansal_ozet(
        ekipman.id,
        date(2026, 1, 1),
        date(2026, 12, 31),
    )

    assert ozet["temin_tarihi"] == date(2026, 3, 15)
