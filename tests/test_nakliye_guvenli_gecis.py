from datetime import date
from decimal import Decimal
import json
from pathlib import Path
import sys
import uuid

import pytest

from app.cari.models import HizmetKaydi
from app.extensions import db
from app.firmalar.models import Firma
from app.kiralama.models import Kiralama, KiralamaKalemi
from app.nakliyeler.models import (
    Nakliye,
    NakliyeDagitim,
    NakliyeGecisIslemi,
    NakliyeGecisKaydi,
)
from app.services.base import ValidationError
from app.services.firma_services import FirmaService
from app.services.nakliye_gecis_services import CariSnapshotService, GuvenliNakliyeGecisService
from app.services.nakliye_gecis_services import TaseronCariBaglantiOnarimService
from app.services.nakliye_sefer_services import NakliyeSeferService


def _refresh_firma_cache(firma):
    ozet = firma.bakiye_ozeti
    firma.bakiye = ozet['net_bakiye']
    FirmaService.guncelle_firma_cari_cache(firma.id, auto_commit=False)
    db.session.add(firma)
    db.session.commit()


def _legacy_rental(*, amount=Decimal('1250.00'), with_trip=True):
    firma = Firma(
        firma_adi=f'Güvenli Geçiş {uuid.uuid4().hex[:6]}',
        yetkili_adi='Yetkili',
        iletisim_bilgileri='Adres',
        vergi_dairesi='VD',
        vergi_no=f'GG-{uuid.uuid4().hex[:12]}',
        is_musteri=True,
        bakiye=amount if with_trip else Decimal('0.00'),
    )
    db.session.add(firma)
    db.session.flush()
    rental = Kiralama(
        kiralama_form_no=f'PF-GG-{uuid.uuid4().hex[:8]}',
        firma_musteri_id=firma.id,
        kdv_orani=20,
        nakliye_modeli='legacy',
    )
    db.session.add(rental)
    db.session.flush()
    line = KiralamaKalemi(
        kiralama_id=rental.id,
        kiralama_baslangici=date(2026, 1, 1),
        kiralama_bitis=date(2026, 1, 10),
        kiralama_brm_fiyat=Decimal('100.00'),
        nakliye_satis_fiyat=amount,
    )
    db.session.add(line)
    db.session.flush()
    if not with_trip:
        db.session.commit()
        return rental, line, None, None
    trip = Nakliye(
        kiralama_id=rental.id,
        firma_id=firma.id,
        tarih=date(2026, 1, 1),
        guzergah='Depo - saha',
        tutar=amount,
        toplam_tutar=amount,
        kdv_orani=20,
        aciklama=f'Gidiş: {rental.kiralama_form_no} #{line.id}',
    )
    db.session.add(trip)
    db.session.flush()
    service = HizmetKaydi(
        firma_id=firma.id,
        nakliye_id=trip.id,
        tarih=trip.tarih,
        tutar=amount,
        yon='giden',
        kaynak='musteri_nakliye',
        aciklama='Eski müşteri nakliye hareketi',
        kdv_orani=20,
    )
    db.session.add(service)
    db.session.commit()
    return rental, line, trip, service


def test_safe_conversion_preserves_financial_rows_and_is_idempotent(app):
    with app.app_context():
        rental, line, trip, service = _legacy_rental()
        service_id = service.id
        before = CariSnapshotService.create_snapshot()

        run_id = str(uuid.uuid4())
        run = GuvenliNakliyeGecisService.apply(before, run_uuid=run_id)
        after = CariSnapshotService.create_snapshot()
        report = CariSnapshotService.compare(before, after)

        assert report['ok'] is True
        assert report['hata_sayisi'] == 0
        assert report['beklenen_degisiklik_sayisi'] == 1
        assert HizmetKaydi.query.count() == 1
        assert db.session.get(HizmetKaydi, service_id).tutar == Decimal('1250.00')
        assert NakliyeDagitim.query.filter_by(nakliye_id=trip.id).one().kiralama_kalemi_id == line.id
        assert db.session.get(Kiralama, rental.id).nakliye_modeli == 'sefer'
        assert NakliyeGecisKaydi.query.filter_by(nakliye_id=trip.id).count() == 1

        same_run = GuvenliNakliyeGecisService.apply(before, run_uuid=run_id)
        assert same_run.id == run.id
        assert NakliyeDagitim.query.filter_by(nakliye_id=trip.id).count() == 1
        assert HizmetKaydi.query.count() == 1


def test_conversion_does_not_create_zero_trip_for_rental_without_transport(app):
    with app.app_context():
        rental, _line, _trip, _service = _legacy_rental(with_trip=False)
        before = CariSnapshotService.create_snapshot()
        GuvenliNakliyeGecisService.apply(before, run_uuid=str(uuid.uuid4()))
        assert Nakliye.query.filter_by(kiralama_id=rental.id).count() == 0
        assert db.session.get(Kiralama, rental.id).nakliye_modeli == 'sefer'


def test_invoiced_converted_trip_cannot_change_amount_or_be_archived(app):
    with app.app_context():
        rental, line, trip, service = _legacy_rental()
        service.fatura_no = 'FAT-001'
        db.session.commit()
        before = CariSnapshotService.create_snapshot()
        GuvenliNakliyeGecisService.apply(before, run_uuid=str(uuid.uuid4()))
        payload = NakliyeSeferService.sefer_modeli_payload(rental)
        payload[0]['dagitimlar'][0]['tutar'] = '1300.00'
        with pytest.raises(ValidationError, match='Faturalı sefer'):
            NakliyeSeferService.sync_kiralama(rental, payload)
        with pytest.raises(ValidationError, match='arşivlenemez'):
            NakliyeSeferService.sync_kiralama(
                rental, [], archive_ids=[trip.id]
            )


def _add_legacy_supplier(rental, line, trip, *, direction='gidis'):
    supplier = Firma(
        firma_adi=f'Taşeron {uuid.uuid4().hex[:6]}',
        yetkili_adi='Yetkili',
        iletisim_bilgileri='Adres',
        vergi_dairesi='VD',
        vergi_no=f'TS-{uuid.uuid4().hex[:12]}',
        is_musteri=False,
        is_tedarikci=True,
    )
    db.session.add(supplier)
    db.session.flush()
    trip.nakliye_tipi = 'taseron'
    trip.taseron_firma_id = supplier.id
    trip.taseron_maliyet = Decimal('900.00')
    trip.yon = direction
    service = HizmetKaydi(
        firma_id=supplier.id,
        ozel_id=line.id,
        tarih=date(2026, 1, 2),
        islem_tarihi=date(2026, 1, 3),
        tutar=Decimal('900.00'),
        yon='gelen',
        kaynak='donus_nakliye' if direction == 'donus' else 'taseron_nakliye',
        fatura_no=rental.kiralama_form_no,
        aciklama=(
            f'Dönüş Nakliye: {rental.kiralama_form_no}'
            if direction == 'donus'
            else f'Taşeron Nakliye Bedeli - {rental.kiralama_form_no}'
        ),
        kdv_orani=18,
    )
    db.session.add(service)
    db.session.commit()
    return supplier, service


@pytest.mark.parametrize('direction', ['gidis', 'donus'])
def test_conversion_adopts_legacy_supplier_identity_and_preserves_financial_fields(
    app, direction,
):
    with app.app_context():
        rental, line, trip, _customer = _legacy_rental()
        supplier, legacy = _add_legacy_supplier(
            rental, line, trip, direction=direction,
        )
        legacy_id = legacy.id
        protected = {
            'firma_id': supplier.id,
            'tutar': legacy.tutar,
            'tarih': legacy.tarih,
            'islem_tarihi': legacy.islem_tarihi,
            'fatura_no': legacy.fatura_no,
            'ozel_id': legacy.ozel_id,
            'aciklama': legacy.aciklama,
            'kdv_orani': legacy.kdv_orani,
        }
        before = CariSnapshotService.create_snapshot()

        GuvenliNakliyeGecisService.apply(before, run_uuid=str(uuid.uuid4()))

        adopted = db.session.get(HizmetKaydi, legacy_id)
        assert HizmetKaydi.query.filter_by(firma_id=supplier.id).count() == 1
        assert adopted.nakliye_id == trip.id
        assert adopted.nakliye_dagitim_id is None
        assert adopted.kiralama_kalemi_id == line.id
        assert adopted.kaynak == 'nakliye_sefer_taseron_gider'
        for field, value in protected.items():
            assert getattr(adopted, field) == value
        assert NakliyeGecisKaydi.query.filter_by(
            hizmet_kaydi_id=legacy_id, durum='taseron_baglandi',
        ).count() == 1


def test_runtime_sync_adopts_unique_legacy_supplier_without_creating_row(app):
    with app.app_context():
        rental, line, trip, _customer = _legacy_rental()
        _supplier, legacy = _add_legacy_supplier(rental, line, trip)
        trip.yon = 'gidis'
        rental.nakliye_modeli = 'sefer'
        db.session.add(NakliyeDagitim(
            nakliye_id=trip.id,
            kiralama_kalemi_id=line.id,
            tutar=trip.tutar,
        ))
        db.session.commit()
        before_count = HizmetKaydi.query.count()

        NakliyeSeferService._sync_taseron_service(trip, rental)
        db.session.commit()

        assert HizmetKaydi.query.count() == before_count
        assert db.session.get(HizmetKaydi, legacy.id).nakliye_id == trip.id


def test_repair_keeps_old_id_and_soft_deletes_safe_duplicate(app):
    with app.app_context():
        rental, line, trip, _customer = _legacy_rental()
        supplier, legacy = _add_legacy_supplier(rental, line, trip)
        rental.nakliye_modeli = 'sefer'
        trip.yon = 'gidis'
        allocation = NakliyeDagitim(
            nakliye_id=trip.id,
            kiralama_kalemi_id=line.id,
            tutar=trip.tutar,
        )
        duplicate = HizmetKaydi(
            firma_id=supplier.id,
            nakliye_id=trip.id,
            tutar=legacy.tutar,
            tarih=trip.tarih,
            yon='gelen',
            kaynak='nakliye_sefer_taseron_gider',
            fatura_no=None,
            aciklama='Sonradan oluşan mükerrer',
        )
        db.session.add_all([allocation, duplicate])
        db.session.commit()
        _refresh_firma_cache(supplier)
        preflight = TaseronCariBaglantiOnarimService.preflight()
        assert preflight['ok'] is True
        assert preflight['eslesme_sayisi'] == 1
        assert preflight['mukerrer_temizleme_sayisi'] == 1
        snapshot = CariSnapshotService.create_snapshot()

        TaseronCariBaglantiOnarimService.apply(
            run_uuid=str(uuid.uuid4()),
            expected_snapshot_sha256=snapshot['sha256'],
        )

        assert db.session.get(HizmetKaydi, legacy.id).nakliye_id == trip.id
        assert db.session.get(HizmetKaydi, legacy.id).is_deleted is False
        assert db.session.get(HizmetKaydi, duplicate.id).is_deleted is True
        assert NakliyeGecisKaydi.query.filter_by(
            hizmet_kaydi_id=duplicate.id, durum='mukerrer_pasif',
        ).count() == 1
        rerun = TaseronCariBaglantiOnarimService.preflight()
        assert rerun['ok'] is True
        assert rerun['zaten_bagli_sayisi'] == 1
        assert rerun['mukerrer_temizleme_sayisi'] == 0


def test_repair_blocks_invoiced_duplicate(app):
    with app.app_context():
        rental, line, trip, _customer = _legacy_rental()
        supplier, legacy = _add_legacy_supplier(rental, line, trip)
        rental.nakliye_modeli = 'sefer'
        trip.yon = 'gidis'
        db.session.add(NakliyeDagitim(
            nakliye_id=trip.id,
            kiralama_kalemi_id=line.id,
            tutar=trip.tutar,
        ))
        db.session.add(HizmetKaydi(
            firma_id=supplier.id,
            nakliye_id=trip.id,
            tutar=legacy.tutar,
            tarih=trip.tarih,
            yon='gelen',
            kaynak='nakliye_sefer_taseron_gider',
            fatura_no='FAT-TEHLIKELI',
        ))
        db.session.commit()

        report = TaseronCariBaglantiOnarimService.preflight()
        assert report['ok'] is False
        assert 'otomatik kapatılamaz' in report['engeller'][0]['hata']


def test_preflight_only_scans_legacy_rentals(app):
    with app.app_context():
        converted, _line, converted_trip, _service = _legacy_rental()
        converted.nakliye_modeli = 'sefer'
        converted_trip.cift_yon = True
        legacy, _line2, legacy_trip, _service2 = _legacy_rental()
        db.session.commit()

        report = GuvenliNakliyeGecisService.preflight()

        assert report['ok'] is True
        assert {row['kiralama_id'] for row in report['kararlar']} == {legacy.id}
        assert {row['nakliye_id'] for row in report['kararlar']} == {legacy_trip.id}


def test_conversion_soft_deletes_safe_supplier_collision_and_keeps_old_id(app):
    with app.app_context():
        rental, line, trip, _customer = _legacy_rental()
        supplier, legacy = _add_legacy_supplier(rental, line, trip)
        duplicate = HizmetKaydi(
            firma_id=supplier.id,
            nakliye_id=trip.id,
            tutar=legacy.tutar,
            tarih=trip.tarih,
            yon='gelen',
            kaynak='nakliye_sefer_taseron_gider',
        )
        db.session.add(duplicate)
        db.session.commit()
        _refresh_firma_cache(supplier)
        before = CariSnapshotService.create_snapshot()

        report = GuvenliNakliyeGecisService.preflight()
        assert report['ok'] is True
        assert report['otomatik_onarimlar'][0] == {
            'kiralama_id': rental.id,
            'nakliye_id': trip.id,
            'korunacak_hizmet_kaydi_id': legacy.id,
            'pasife_alinacak_hizmet_kaydi_id': duplicate.id,
        }

        run = GuvenliNakliyeGecisService.apply(
            before, run_uuid=str(uuid.uuid4()),
        )

        assert run.durum == 'donusturuldu_mutabakat_bekliyor', run.rapor_json
        assert db.session.get(HizmetKaydi, legacy.id).nakliye_id == trip.id
        assert db.session.get(HizmetKaydi, duplicate.id).is_deleted is True
        assert db.session.get(HizmetKaydi, duplicate.id).is_active is False
        refreshed_supplier = db.session.get(Firma, supplier.id)
        assert refreshed_supplier.bakiye == Decimal('-900.00')
        assert refreshed_supplier.cari_borc_kdvli == Decimal('0.00')
        assert refreshed_supplier.cari_alacak_kdvli == Decimal('1062.00')
        assert refreshed_supplier.cari_bakiye_kdvli == Decimal('-1062.00')


def test_unsafe_supplier_collision_blocks_only_its_rental(app):
    with app.app_context():
        blocked, line, trip, _customer = _legacy_rental()
        supplier, legacy = _add_legacy_supplier(blocked, line, trip)
        unsafe = HizmetKaydi(
            firma_id=supplier.id,
            nakliye_id=trip.id,
            tutar=legacy.tutar,
            tarih=trip.tarih,
            yon='gelen',
            kaynak='nakliye_sefer_taseron_gider',
            fatura_no='FAT-ENGEL',
        )
        db.session.add(unsafe)
        other, _line2, _trip2, _service2 = _legacy_rental()
        db.session.commit()
        before = CariSnapshotService.create_snapshot()

        run = GuvenliNakliyeGecisService.apply(
            before, run_uuid=str(uuid.uuid4()),
        )

        assert run.durum == 'kismi_basarisiz'
        assert db.session.get(Kiralama, blocked.id).nakliye_modeli == 'legacy'
        assert db.session.get(Kiralama, other.id).nakliye_modeli == 'sefer'
        blocker = json.loads(run.rapor_json)['engeller'][0]
        assert str(legacy.id) in blocker['hata']
        assert str(unsafe.id) in blocker['hata']


def test_failed_rental_rolls_back_and_same_run_resumes_with_accumulated_counts(
    app, monkeypatch,
):
    with app.app_context():
        first, _line1, _trip1, first_service = _legacy_rental()
        second, _line2, _trip2, _service2 = _legacy_rental()
        before = CariSnapshotService.create_snapshot()
        run_uuid = str(uuid.uuid4())
        original_compare = CariSnapshotService.compare.__func__
        state = {'failed': False}

        def fail_first_changed_snapshot(cls, old, new):
            result = original_compare(cls, old, new)
            if result['beklenen_degisiklik_sayisi'] and not state['failed']:
                state['failed'] = True
                return {
                    **result,
                    'ok': False,
                    'hata_sayisi': 1,
                    'hatalar': [{'hata': 'test_mutabakat_hatasi'}],
                }
            return result

        monkeypatch.setattr(
            CariSnapshotService, 'compare', classmethod(fail_first_changed_snapshot),
        )
        first_run = GuvenliNakliyeGecisService.apply(before, run_uuid=run_uuid)
        assert first_run.durum == 'kismi_basarisiz'
        assert first_run.donusturulen_kiralama_sayisi == 1
        assert db.session.get(Kiralama, first.id).nakliye_modeli == 'legacy'
        assert db.session.get(HizmetKaydi, first_service.id).kaynak == 'musteri_nakliye'
        assert db.session.get(Kiralama, second.id).nakliye_modeli == 'sefer'

        resumed = GuvenliNakliyeGecisService.apply(before, run_uuid=run_uuid)
        assert resumed.durum == 'donusturuldu_mutabakat_bekliyor'
        assert resumed.donusturulen_kiralama_sayisi == 2
        assert resumed.donusturulen_sefer_sayisi == 2
        assert db.session.get(Kiralama, first.id).nakliye_modeli == 'sefer'


def test_preflight_blocks_customer_amount_mismatch_and_double_direction(app):
    with app.app_context():
        mismatch, _line1, trip1, service1 = _legacy_rental()
        service1.tutar = Decimal('1249.99')
        double, _line2, trip2, _service2 = _legacy_rental()
        trip2.cift_yon = True
        db.session.commit()

        report = GuvenliNakliyeGecisService.preflight()

        errors = {row['kiralama_id']: row['hata'] for row in report['engeller']}
        assert 'uyuşmuyor' in errors[mismatch.id]
        assert 'çift yönlü' in errors[double.id]


def test_inactive_transport_does_not_take_direction_slot_or_distribution(app):
    with app.app_context():
        rental, line, active_trip, _service = _legacy_rental()
        inactive_trip = Nakliye(
            kiralama_id=rental.id,
            firma_id=rental.firma_musteri_id,
            tarih=date(2026, 1, 1),
            guzergah='Pasif sefer',
            tutar=Decimal('100.00'),
            toplam_tutar=Decimal('100.00'),
            yon='gidis',
            aciklama=f'Gidiş: {rental.kiralama_form_no} #{line.id}',
            is_active=False,
        )
        db.session.add(inactive_trip)
        db.session.commit()
        before = CariSnapshotService.create_snapshot()

        GuvenliNakliyeGecisService.apply(before, run_uuid=str(uuid.uuid4()))

        assert NakliyeDagitim.query.filter_by(nakliye_id=active_trip.id).count() == 1
        assert NakliyeDagitim.query.filter_by(nakliye_id=inactive_trip.id).count() == 0


def test_repair_verification_failure_rolls_back_changes(app, monkeypatch):
    with app.app_context():
        rental, line, trip, _customer = _legacy_rental()
        supplier, legacy = _add_legacy_supplier(rental, line, trip)
        rental.nakliye_modeli = 'sefer'
        trip.yon = 'gidis'
        duplicate = HizmetKaydi(
            firma_id=supplier.id,
            nakliye_id=trip.id,
            tutar=legacy.tutar,
            tarih=trip.tarih,
            yon='gelen',
            kaynak='nakliye_sefer_taseron_gider',
        )
        db.session.add_all([
            NakliyeDagitim(
                nakliye_id=trip.id,
                kiralama_kalemi_id=line.id,
                tutar=trip.tutar,
            ),
            duplicate,
        ])
        db.session.commit()
        _refresh_firma_cache(supplier)
        snapshot = CariSnapshotService.create_snapshot()
        run_uuid = str(uuid.uuid4())

        monkeypatch.setattr(
            CariSnapshotService,
            'compare',
            classmethod(lambda cls, old, new: {
                'ok': False,
                'hatalar': [{'hata': 'beklenmeyen_firma_farki'}],
            }),
        )
        run, report = TaseronCariBaglantiOnarimService.apply(
            run_uuid=run_uuid,
            expected_snapshot_sha256=snapshot['sha256'],
        )

        db.session.expire_all()
        assert run.durum == 'kismi_basarisiz'
        assert 'beklenmeyen_firma_farki' in report['islem_hatalari'][0]['hata']
        assert db.session.get(HizmetKaydi, legacy.id).nakliye_id is None
        assert db.session.get(HizmetKaydi, duplicate.id).is_deleted is False
        assert NakliyeGecisIslemi.query.filter_by(run_uuid=run_uuid).one().durum == 'kismi_basarisiz'


def test_partial_conversion_resumes_with_new_run_id_and_keeps_counts(
    app, monkeypatch,
):
    with app.app_context():
        first, _line1, _trip1, _service1 = _legacy_rental()
        second, _line2, _trip2, _service2 = _legacy_rental()
        before = CariSnapshotService.create_snapshot()
        original_compare = CariSnapshotService.compare.__func__
        state = {'failed': False}

        def fail_first_changed_snapshot(cls, old, new):
            result = original_compare(cls, old, new)
            if result['beklenen_degisiklik_sayisi'] and not state['failed']:
                state['failed'] = True
                return {
                    **result,
                    'ok': False,
                    'hata_sayisi': 1,
                    'hatalar': [{'hata': 'ilk_run_test_hatasi'}],
                }
            return result

        monkeypatch.setattr(
            CariSnapshotService, 'compare', classmethod(fail_first_changed_snapshot),
        )
        first_run = GuvenliNakliyeGecisService.apply(
            before, run_uuid=str(uuid.uuid4()),
        )
        assert first_run.durum == 'kismi_basarisiz'
        assert first_run.donusturulen_kiralama_sayisi == 1

        resumed = GuvenliNakliyeGecisService.apply(
            before, run_uuid=str(uuid.uuid4()),
        )
        assert resumed.durum == 'donusturuldu_mutabakat_bekliyor'
        assert resumed.donusturulen_kiralama_sayisi == 2
        assert resumed.donusturulen_sefer_sayisi == 2
        assert db.session.get(Kiralama, first.id).nakliye_modeli == 'sefer'
        assert db.session.get(Kiralama, second.id).nakliye_modeli == 'sefer'


def test_repair_processes_good_trip_while_other_trip_is_blocked(app):
    with app.app_context():
        blocked, blocked_line, blocked_trip, _customer1 = _legacy_rental()
        _blocked_supplier, blocked_legacy = _add_legacy_supplier(
            blocked, blocked_line, blocked_trip,
        )
        blocked.nakliye_modeli = 'sefer'
        blocked_trip.yon = 'gidis'
        db.session.add_all([
            NakliyeDagitim(
                nakliye_id=blocked_trip.id,
                kiralama_kalemi_id=blocked_line.id,
                tutar=blocked_trip.tutar,
            ),
            NakliyeDagitim(
                nakliye_id=blocked_trip.id,
                kiralama_kalemi_id=blocked_line.id,
                tutar=Decimal('0.00'),
            ),
        ])

        good, good_line, good_trip, _customer2 = _legacy_rental()
        good_supplier, good_legacy = _add_legacy_supplier(
            good, good_line, good_trip,
        )
        good.nakliye_modeli = 'sefer'
        good_trip.yon = 'gidis'
        good_duplicate = HizmetKaydi(
            firma_id=good_supplier.id,
            nakliye_id=good_trip.id,
            tutar=good_legacy.tutar,
            tarih=good_trip.tarih,
            yon='gelen',
            kaynak='nakliye_sefer_taseron_gider',
        )
        db.session.add_all([
            NakliyeDagitim(
                nakliye_id=good_trip.id,
                kiralama_kalemi_id=good_line.id,
                tutar=good_trip.tutar,
            ),
            good_duplicate,
        ])
        db.session.commit()
        _refresh_firma_cache(good_supplier)
        snapshot = CariSnapshotService.create_snapshot()

        run, report = TaseronCariBaglantiOnarimService.apply(
            run_uuid=str(uuid.uuid4()),
            expected_snapshot_sha256=snapshot['sha256'],
        )

        assert run.durum == 'kismi_basarisiz'
        assert report['engeller'][0]['nakliye_id'] == blocked_trip.id
        assert db.session.get(HizmetKaydi, blocked_legacy.id).nakliye_id is None
        assert db.session.get(HizmetKaydi, good_legacy.id).nakliye_id == good_trip.id
        assert db.session.get(HizmetKaydi, good_duplicate.id).is_deleted is True


def test_preflight_blocks_second_incoming_service_from_other_source(app):
    with app.app_context():
        rental, line, trip, _customer = _legacy_rental()
        _supplier, legacy = _add_legacy_supplier(rental, line, trip)
        other = HizmetKaydi(
            firma_id=legacy.firma_id,
            nakliye_id=trip.id,
            tutar=legacy.tutar,
            tarih=trip.tarih,
            yon='gelen',
            kaynak='manuel_taseron_gideri',
        )
        db.session.add(other)
        db.session.commit()

        report = GuvenliNakliyeGecisService.preflight()

        assert report['ok'] is False
        error = report['engeller'][0]['hata']
        assert str(legacy.id) in error
        assert str(other.id) in error


def test_cli_reports_preflight_blockers_and_partial_apply(
    app, monkeypatch, tmp_path, capsys,
):
    import scripts.migrate_kiralama_nakliye_sefer as migration_script

    with app.app_context():
        blocked, _line1, blocked_trip, _service1 = _legacy_rental()
        blocked_trip.cift_yon = True
        _good, _line2, _trip2, _service2 = _legacy_rental()
        db.session.commit()
        before = CariSnapshotService.create_snapshot()
        before_path = Path(tmp_path) / 'before.json'
        before_path.write_text(json.dumps(before), encoding='utf-8')

        monkeypatch.setattr(migration_script, 'create_app', lambda: app)
        preflight_path = Path(tmp_path) / 'preflight.json'
        monkeypatch.setattr(sys, 'argv', [
            'migrate_kiralama_nakliye_sefer.py',
            'preflight', '--output', str(preflight_path),
        ])
        assert migration_script.main() == 2
        preflight_output = capsys.readouterr().out
        assert 'Karar: 1' in preflight_output
        assert 'engel: 1' in preflight_output

        monkeypatch.setattr(sys, 'argv', [
            'migrate_kiralama_nakliye_sefer.py',
            'apply', '--before', str(before_path),
            '--run-id', str(uuid.uuid4()),
            '--output-dir', str(Path(tmp_path) / 'apply'),
        ])
        assert migration_script.main() == 3
        apply_output = capsys.readouterr().out
        assert 'Dönüşen kiralama: 1' in apply_output
        assert 'Engel: 1' in apply_output
        assert 'Mutabakat hatası: 0' in apply_output
        assert 'Kısmi başarı: mutabakat hatası 0' in apply_output
