from datetime import date
from decimal import Decimal

from app.extensions import db
from app.filo.models import BakimKaydi, Ekipman
from app.filo.forms import EkipmanForm
from app.firmalar.models import Firma
from app.kiralama.models import Kiralama, KiralamaKalemi
from app.personel.models import Personel, PersonelMaasDonemi
from app.services.ekipman_rapor_services import EkipmanRaporuService
from app.services.raporlama_services import RaporlamaService
from app.subeler.models import Sube, SubeGideri, SubeSabitGiderDonemi


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


def _add_external_rental(start_date, end_date, form_no="HK-001", satis="1200", alis="800"):
    firma = Firma(
        firma_adi=f"Harici Musteri {form_no}",
        yetkili_adi="Yetkili",
        iletisim_bilgileri="Telefon",
        vergi_dairesi="Test",
        vergi_no=f"VN-{form_no}",
    )
    tedarikci = Firma(
        firma_adi=f"Tedarikci {form_no}",
        yetkili_adi="Yetkili",
        iletisim_bilgileri="Telefon",
        vergi_dairesi="Test",
        vergi_no=f"VT-{form_no}",
        is_tedarikci=True,
    )
    kiralama = Kiralama(
        kiralama_form_no=form_no,
        firma_musteri=firma,
        kdv_orani=20,
    )
    kalem = KiralamaKalemi(
        kiralama=kiralama,
        is_dis_tedarik_ekipman=True,
        harici_ekipman_tipi="Platform",
        harici_ekipman_marka="JLG",
        harici_ekipman_model="600S",
        harici_tedarikci=tedarikci,
        kiralama_baslangici=start_date,
        kiralama_bitis=end_date,
        kiralama_brm_fiyat=Decimal(satis),
        kiralama_alis_fiyat=Decimal(alis),
        sonlandirildi=False,
        is_active=True,
    )
    db.session.add_all([firma, tedarikci, kiralama, kalem])
    db.session.commit()
    return kalem


def test_external_rental_metrics_rows_match_count_and_include_form_no(app):
    _add_external_rental(date(2026, 3, 1), date(2026, 3, 10), form_no="HK-RP-01")
    _add_external_rental(date(2026, 3, 15), date(2026, 3, 20), form_no="HK-RP-02")

    metrics = RaporlamaService._calculate_external_rental_metrics(
        date(2026, 3, 1),
        date(2026, 3, 31),
    )

    assert metrics["count"] == 2
    assert len(metrics["rows"]) == metrics["count"]
    form_nos = {row["form_no"] for row in metrics["rows"]}
    assert form_nos == {"HK-RP-01", "HK-RP-02"}
    assert {row["kiralama_form_no"] for row in metrics["rows"]} == form_nos
    assert all(row["kiralama_id"] for row in metrics["rows"])
    assert metrics["total_revenue"] == sum(row["toplam_gelir"] for row in metrics["rows"])
    assert metrics["total_cost"] == sum(row["toplam_odeme"] for row in metrics["rows"])


def test_external_rental_metrics_excludes_non_overlapping_period(app):
    _add_external_rental(date(2026, 1, 1), date(2026, 1, 15), form_no="HK-RP-OLD")

    metrics = RaporlamaService._calculate_external_rental_metrics(
        date(2026, 6, 1),
        date(2026, 6, 30),
    )

    assert metrics["count"] == 0
    assert metrics["rows"] == []


def test_today_range_allocates_branch_period_expenses_for_one_day(app, monkeypatch):
    monkeypatch.setattr("app.services.raporlama_services._bugun", lambda: date(2026, 6, 9))

    sube = Sube(isim="Merkez")
    personel = Personel(ad="Test", soyad="Personel", sube=sube)
    db.session.add_all([sube, personel])
    db.session.flush()

    db.session.add_all([
        PersonelMaasDonemi(
            personel_id=personel.id,
            sube_id=sube.id,
            baslangic_tarihi=date(2026, 6, 1),
            aylik_maas=Decimal("30000"),
        ),
        SubeSabitGiderDonemi(
            sube_id=sube.id,
            kategori="kira",
            baslangic_tarihi=date(2026, 6, 1),
            aylik_tutar=Decimal("3000"),
            periyot_tipi="ay",
            periyot_degeri=1,
        ),
        SubeGideri(
            sube_id=sube.id,
            tarih=date(2026, 6, 9),
            kategori="diger",
            tutar=Decimal("50"),
        ),
    ])
    db.session.commit()

    rows = RaporlamaService._calculate_monthly_revenue_series(
        date(2026, 6, 9),
        date(2026, 6, 9),
        sube_id=sube.id,
        ekipman_ids=[],
    )

    assert len(rows) == 1
    assert rows[0]["manuel_sube_gideri"] == 50
    assert rows[0]["personel_gideri"] == 1000
    assert rows[0]["sabit_gideri"] == 100
    assert rows[0]["sube_gideri"] == 1150
