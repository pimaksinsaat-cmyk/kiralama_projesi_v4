from datetime import date
from decimal import Decimal
import uuid

import pytest

from app.araclar.models import Arac
from app.cari.models import HizmetKaydi
from app.extensions import db
from app.filo.models import Ekipman
from app.firmalar.models import Firma
from app.kiralama.models import Kiralama, KiralamaKalemi
from app.nakliyeler.models import Nakliye, NakliyeDagitim
from app.services.base import ValidationError
from app.services.kiralama_services import KiralamaKalemiService, KiralamaService
from app.services.nakliye_sefer_services import NakliyeSeferService
from app.services.nakliye_guzergah_services import (
    NAKLIYE_GUZERGAH_MAX_LENGTH,
    build_nakliye_guzergah,
)
from app.subeler.models import Sube


def _firma(name, customer=False, supplier=False):
    firma = Firma(
        firma_adi=f'{name}-{uuid.uuid4().hex[:6]}',
        yetkili_adi='Yetkili',
        iletisim_bilgileri='Test adres',
        vergi_dairesi='Test VD',
        vergi_no=f'TEST-{uuid.uuid4().hex[:12]}',
        is_musteri=customer,
        is_tedarikci=supplier,
        bakiye=Decimal('0'),
    )
    db.session.add(firma)
    db.session.flush()
    return firma


def _rental(count=2):
    customer = _firma('Müşteri', customer=True)
    rental = Kiralama(
        kiralama_form_no=f'PF-TEST-{uuid.uuid4().hex[:8]}',
        firma_musteri_id=customer.id,
        kdv_orani=20,
    )
    db.session.add(rental)
    db.session.flush()
    lines = []
    for _ in range(count):
        line = KiralamaKalemi(
            kiralama_id=rental.id,
            kiralama_baslangici=date(2026, 8, 6),
            kiralama_bitis=date(2026, 8, 20),
            kiralama_brm_fiyat=Decimal('100'),
        )
        db.session.add(line)
        lines.append(line)
    db.session.flush()
    return rental, lines


def _arac():
    arac = Arac(
        plaka=f'T{uuid.uuid4().hex[:8]}',
        arac_tipi='Kamyon',
        marka_model='Test',
        is_nakliye_araci=True,
    )
    db.session.add(arac)
    db.session.flush()
    return arac


def _ekipman(code, sube=None):
    ekipman = Ekipman(
        kod=f'{code}-{uuid.uuid4().hex[:6]}',
        yakit='Elektrik',
        tipi='MAKAS',
        marka='Test Marka',
        model='Test Model',
        seri_no=f'SN-{uuid.uuid4().hex[:10]}',
        calisma_yuksekligi=12,
        kaldirma_kapasitesi=250,
        uretim_yili=2025,
        calisma_durumu='bosta',
        sube_id=sube.id if sube else None,
    )
    db.session.add(ekipman)
    db.session.flush()
    return ekipman


def _payload(lines, amount1='0', amount2='1000', yon='gidis', date_value='2026-08-06', arac_id=None):
    if arac_id is None:
        arac_id = _arac().id
    return [{
        'sefer_uuid': str(uuid.uuid4()),
        'yon': yon,
        'tarih': date_value,
        'islem_tarihi': date_value,
        'guzergah': 'Depo - Saha',
        'nakliye_tipi': 'oz_mal',
        'arac_id': arac_id,
        'taseron_maliyet': '0',
        'dagitimlar': [
            {'kiralama_kalemi_id': lines[0].id, 'tutar': amount1},
            {'kiralama_kalemi_id': lines[1].id, 'tutar': amount2},
        ],
    }]


def _single_payload(line, guzergah, arac_id=None):
    return [{
        'sefer_uuid': str(uuid.uuid4()),
        'yon': 'gidis',
        'tarih': '2026-08-06',
        'islem_tarihi': '2026-08-06',
        'guzergah': guzergah,
        'nakliye_tipi': 'oz_mal',
        'arac_id': arac_id or _arac().id,
        'taseron_maliyet': '0',
        'dagitimlar': [{'kiralama_kalemi_id': line.id, 'tutar': '100'}],
    }]


def test_automatic_route_is_compact_normalized_and_bounded():
    route = build_nakliye_guzergah(
        '  ZOOMLION   ZS1012HD  ',
        'Çok uzun çıkış ' * 80,
        'Çok uzun varış ' * 80,
    )

    assert route.startswith('ZOOMLION ZS1012HD: ')
    assert '  ' not in route
    assert ' → ' in route
    assert len(route) <= NAKLIYE_GUZERGAH_MAX_LENGTH


def test_manual_route_accepts_500_and_rejects_501_before_flush(app):
    with app.app_context():
        rental, lines = _rental(count=1)
        NakliyeSeferService.sync_kiralama(rental, _single_payload(lines[0], 'A' * 500))
        db.session.flush()
        assert Nakliye.query.filter_by(kiralama_id=rental.id).one().guzergah == 'A' * 500

        other_rental, other_lines = _rental(count=1)
        with pytest.raises(ValidationError, match='en fazla 500 karakter'):
            NakliyeSeferService.sync_kiralama(
                other_rental,
                _single_payload(other_lines[0], 'B' * 501),
            )


def test_long_customer_return_route_is_compact_and_does_not_repeat_customer(app):
    with app.app_context():
        rental, lines = _rental(count=1)
        line = lines[0]
        rental.nakliye_modeli = 'sefer'
        customer_name = (
            'HALİL ERDOĞAN VE YAĞIZ İNŞAAT MAKİNE TAAH SAN VE TİC LTD ŞTİ '
            'ADİ ORTAKLIĞI'
        )
        rental.firma_musteri.firma_adi = customer_name
        rental.makine_calisma_adresi = customer_name
        vehicle = _arac()
        line.donus_nakliye_araci_id = vehicle.id

        NakliyeSeferService.sync_kiralama(
            rental,
            _single_payload(line, 'Mevcut 187 karakterlik legacy güzergâh', vehicle.id),
        )
        return_trip = KiralamaKalemiService._create_donus_nakliye_seferi(
            line,
            'ZOOMLION ZS1012HD',
            customer_name,
            customer_name,
            'Tedarikçiye İade',
            Decimal('3000.00'),
            allocation_kalem=line,
        )
        db.session.flush()

        assert return_trip.guzergah == (
            f'ZOOMLION ZS1012HD: {customer_name} → Tedarikçiye İade'
        )
        assert return_trip.guzergah.count(customer_name) == 1
        assert len(return_trip.guzergah) <= NAKLIYE_GUZERGAH_MAX_LENGTH


def test_zero_allocation_is_operational_but_not_customer_cari(app):
    with app.app_context():
        rental, lines = _rental()
        NakliyeSeferService.sync_kiralama(rental, _payload(lines))
        db.session.commit()
        sefer = Nakliye.query.filter_by(kiralama_id=rental.id, yon='gidis').one()
        assert sefer.tutar == Decimal('1000.00')
        assert NakliyeDagitim.query.filter_by(nakliye_id=sefer.id).count() == 2
        assert HizmetKaydi.query.filter_by(nakliye_dagitim_id=sefer.dagitimlar[0].id).filter(
            HizmetKaydi.is_deleted.is_(False)
        ).count() == 0
        assert HizmetKaydi.query.filter_by(nakliye_dagitim_id=sefer.dagitimlar[1].id).filter(
            HizmetKaydi.is_deleted.is_(False)
        ).one().tutar == Decimal('1000.00')


def test_legacy_conversion_sync_preserves_customer_financial_fields_and_zero_row(app):
    with app.app_context():
        rental, lines = _rental()
        rental.nakliye_modeli = 'sefer'
        sefer = Nakliye(
            kiralama_id=rental.id,
            firma_id=rental.firma_musteri_id,
            yon='gidis',
            tarih=date(2026, 8, 6),
            islem_tarihi=date(2026, 8, 6),
            guzergah='Legacy rota',
            nakliye_tipi='oz_mal',
            arac_id=_arac().id,
            tutar=Decimal('1500.00'),
            kdv_orani=20,
            gecis_kaynagi='legacy_kiralama_v1',
        )
        db.session.add(sefer)
        db.session.flush()
        dagitim_ucretli = NakliyeDagitim(
            nakliye_id=sefer.id,
            kiralama_kalemi_id=lines[0].id,
            tutar=Decimal('1500.00'),
        )
        dagitim_sifir = NakliyeDagitim(
            nakliye_id=sefer.id,
            kiralama_kalemi_id=lines[1].id,
            tutar=Decimal('0.00'),
        )
        db.session.add_all([dagitim_ucretli, dagitim_sifir])
        db.session.flush()

        ucretli = HizmetKaydi(
            firma_id=rental.firma_musteri_id,
            nakliye_id=sefer.id,
            nakliye_dagitim_id=dagitim_ucretli.id,
            kiralama_kalemi_id=lines[0].id,
            kaynak='nakliye_dagitim_satis',
            yon='giden',
            tarih=date(2026, 7, 1),
            islem_tarihi=date(2026, 7, 2),
            tutar=Decimal('1500.00'),
            kdv_orani=16,
            fatura_no='PF-LEGACY-001',
            aciklama='Korunan legacy müşteri nakliyesi',
        )
        sifir = HizmetKaydi(
            firma_id=rental.firma_musteri_id,
            nakliye_id=sefer.id,
            nakliye_dagitim_id=dagitim_sifir.id,
            kiralama_kalemi_id=lines[1].id,
            kaynak='nakliye_dagitim_satis',
            yon='giden',
            tarih=date(2026, 7, 3),
            islem_tarihi=date(2026, 7, 4),
            tutar=Decimal('0.00'),
            kdv_orani=8,
            aciklama='Korunan sıfır legacy müşteri nakliyesi',
        )
        db.session.add_all([ucretli, sifir])
        db.session.commit()

        NakliyeSeferService.sync_active_cari(rental)
        db.session.flush()

        assert ucretli.tutar == Decimal('1500.00')
        assert ucretli.kdv_orani == 16
        assert ucretli.fatura_no == 'PF-LEGACY-001'
        assert ucretli.tarih == date(2026, 7, 1)
        assert ucretli.islem_tarihi == date(2026, 7, 2)
        assert sifir.is_deleted is False
        assert sifir.is_active is True
        assert sifir.kdv_orani == 8
        assert sifir.tarih == date(2026, 7, 3)
        assert sifir.islem_tarihi == date(2026, 7, 4)


def test_remove_kalem_allocations_preserves_shared_sefer_and_soft_deletes_cari(app):
    with app.app_context():
        rental, lines = _rental()
        NakliyeSeferService.sync_kiralama(rental, _payload(lines, amount1='0', amount2='1000'))
        NakliyeSeferService.sync_kiralama(
            rental,
            _payload(lines, amount1='250', amount2='500', yon='donus', date_value='2026-08-11'),
            allow_new_donus=True,
        )
        db.session.commit()

        NakliyeSeferService.remove_kalem_allocations(rental, [lines[0].id])
        db.session.commit()

        gidis, donus = Nakliye.query.filter_by(kiralama_id=rental.id).order_by(Nakliye.id).all()
        assert gidis.tutar == Decimal('1000.00')
        assert donus.tutar == Decimal('500.00')
        assert all(
            d.is_deleted is True
            for sefer in (gidis, donus)
            for d in sefer.dagitimlar
            if d.kiralama_kalemi_id == lines[0].id
        )
        assert all(
            d.is_deleted is False and d.is_active is True
            for sefer in (gidis, donus)
            for d in sefer.dagitimlar
            if d.kiralama_kalemi_id == lines[1].id
        )
        assert HizmetKaydi.query.filter_by(
            kiralama_kalemi_id=lines[1].id,
            kaynak='nakliye_dagitim_satis',
        ).filter(HizmetKaydi.is_deleted.is_(False)).count() == 2
        assert HizmetKaydi.query.filter_by(
            kiralama_kalemi_id=lines[0].id,
            kaynak='nakliye_dagitim_satis',
        ).filter(HizmetKaydi.is_deleted.is_(False)).count() == 0


def test_cancel_termination_removes_only_line_allocations_in_sefer_model(app):
    with app.app_context():
        rental, lines = _rental()
        NakliyeSeferService.sync_kiralama(rental, _payload(lines, amount1='250', amount2='750'))
        NakliyeSeferService.sync_kiralama(
            rental,
            _payload(lines, amount1='100', amount2='400', yon='donus', date_value='2026-08-11'),
            allow_new_donus=True,
        )
        lines[0].sonlandirildi = True
        db.session.commit()

        KiralamaKalemiService.iptal_et_sonlandirma(lines[0].id)
        db.session.refresh(lines[0])

        assert lines[0].sonlandirildi is False
        donus = Nakliye.query.filter_by(kiralama_id=rental.id, yon='donus').one()
        assert donus.is_active is True
        assert donus.tutar == Decimal('400.00')
        gidis = Nakliye.query.filter_by(kiralama_id=rental.id, yon='gidis').one()
        assert gidis.tutar == Decimal('1000.00')
        assert all(
            d.is_deleted is True
            for d in donus.dagitimlar
            if d.kiralama_kalemi_id == lines[0].id
        )


def test_sonlandir_on_sefer_model_keeps_gidis_and_writes_donus_allocation(app):
    with app.app_context():
        from app.subeler.models import Sube

        rental, lines = _rental()
        arac = _arac()
        NakliyeSeferService.sync_kiralama(
            rental, _payload(lines, amount1='250', amount2='750', arac_id=arac.id)
        )
        db.session.commit()
        sube = Sube(
            isim=f"Donus Sube {uuid.uuid4().hex[:4]}",
            adres="Test Adres",
            yetkili_kisi="Test Yetkili",
            telefon="0212-3333333",
        )
        db.session.add(sube)
        db.session.flush()

        KiralamaKalemiService.sonlandir(
            lines[0].id,
            '2026-08-20',
            str(sube.id),
            is_harici_nakliye=False,
            nakliye_araci_id=arac.id,
            donus_nakliye_satis_fiyat='100',
        )

        gidis = Nakliye.query.filter_by(kiralama_id=rental.id, yon='gidis').one()
        assert gidis.tutar == Decimal('1000.00')
        donus = Nakliye.query.filter_by(kiralama_id=rental.id, yon='donus').one()
        assert donus.yon == 'donus'
        assert donus.is_deleted is False
        own = [
            d for d in donus.dagitimlar
            if d.kiralama_kalemi_id == lines[0].id and not d.is_deleted
        ]
        assert len(own) == 1
        assert own[0].tutar == Decimal('100.00')
        assert all(
            d.kiralama_kalemi_id != lines[1].id or d.is_deleted
            for d in donus.dagitimlar
        )

        KiralamaKalemiService.iptal_et_sonlandirma(lines[0].id)
        db.session.refresh(lines[0])
        assert lines[0].sonlandirildi is False
        gidis = Nakliye.query.filter_by(kiralama_id=rental.id, yon='gidis').one()
        assert gidis.tutar == Decimal('1000.00')
        assert gidis.is_deleted is False
        donus = Nakliye.query.filter_by(kiralama_id=rental.id, yon='donus').first()
        if donus and not donus.is_deleted:
            assert all(
                d.is_deleted is True
                for d in donus.dagitimlar
                if d.kiralama_kalemi_id == lines[0].id
            )


def test_sefer_modeli_payload_reads_existing_sefer_and_shared_allocations(app):
    with app.app_context():
        rental, lines = _rental()
        original_uuid = str(uuid.uuid4())
        NakliyeSeferService.sync_kiralama(rental, [{
            'sefer_uuid': original_uuid,
            'yon': 'gidis',
            'tarih': '2026-08-06',
            'islem_tarihi': '2026-08-06',
            'guzergah': 'Depo - Saha',
            'nakliye_tipi': 'oz_mal',
            'arac_id': _arac().id,
            'dagitimlar': [
                {'kiralama_kalemi_id': lines[0].id, 'tutar': '0'},
                {'kiralama_kalemi_id': lines[1].id, 'tutar': '1000'},
            ],
        }])
        db.session.commit()
        sefer = Nakliye.query.filter_by(kiralama_id=rental.id, yon='gidis').one()

        payload = NakliyeSeferService.sefer_modeli_payload(rental)

        assert len(payload) == 1
        assert payload[0]['id'] == sefer.id
        assert payload[0]['sefer_uuid'] == original_uuid
        assert {item['kiralama_kalemi_id'] for item in payload[0]['dagitimlar']} == {lines[0].id, lines[1].id}
        assert {item['tutar'] for item in payload[0]['dagitimlar']} == {'0', '1000.00'}


def test_one_gidis_and_one_donus_per_line_and_duplicate_is_rejected(app):
    with app.app_context():
        rental, lines = _rental()
        NakliyeSeferService.sync_kiralama(rental, _payload(lines))
        NakliyeSeferService.sync_kiralama(
            rental, _payload(lines, amount1='0', amount2='500', yon='donus', date_value='2026-08-11'),
            allow_new_donus=True,
        )
        db.session.commit()
        assert Nakliye.query.filter_by(kiralama_id=rental.id).count() == 2
        with pytest.raises(ValidationError):
            NakliyeSeferService.sync_kiralama(rental, _payload(lines, amount1='1', amount2='2'))


def test_faturali_distribution_cannot_be_changed(app):
    with app.app_context():
        rental, lines = _rental()
        NakliyeSeferService.sync_kiralama(rental, _payload(lines))
        db.session.commit()
        service = HizmetKaydi.query.filter_by(kaynak='nakliye_dagitim_satis').one()
        service.fatura_no = 'EF-TEST-1'
        db.session.commit()
        existing = Nakliye.query.filter_by(kiralama_id=rental.id, yon='gidis').one()
        changed = _payload(lines)
        changed[0]['id'] = existing.id
        changed[0]['dagitimlar'][1]['tutar'] = '2000'
        with pytest.raises(ValidationError):
            NakliyeSeferService.sync_kiralama(rental, changed)


def test_archived_sefer_can_be_replaced_by_same_direction_in_one_save(app):
    with app.app_context():
        rental, lines = _rental()
        NakliyeSeferService.sync_kiralama(rental, _payload(lines))
        db.session.commit()
        old = Nakliye.query.filter_by(kiralama_id=rental.id, yon='gidis').one()

        replacement = _payload(lines, amount1='10', amount2='20')
        NakliyeSeferService.sync_kiralama(rental, replacement, archive_ids=[old.id])
        db.session.commit()

        assert old.is_deleted is True
        active = Nakliye.query.filter_by(kiralama_id=rental.id, yon='gidis').filter(
            Nakliye.is_deleted.is_(False), Nakliye.is_active.is_(True)
        ).one()
        assert active.id != old.id
        assert active.tutar == Decimal('30.00')


def test_sync_kiralama_writes_allocation_total_to_kalem_nakliye_satis(app):
    with app.app_context():
        rental, lines = _rental()
        NakliyeSeferService.sync_kiralama(rental, _payload(lines, amount1='250', amount2='1000'))
        NakliyeSeferService.sync_kiralama(
            rental, _payload(lines, amount1='50', amount2='400', yon='donus', date_value='2026-08-11'),
            allow_new_donus=True,
        )
        db.session.commit()
        db.session.refresh(lines[0])
        db.session.refresh(lines[1])
        assert lines[0].nakliye_satis_fiyat == Decimal('300.00')
        assert lines[1].nakliye_satis_fiyat == Decimal('1400.00')
        assert lines[0].donus_nakliye_fatura_et is True
        assert lines[1].donus_nakliye_fatura_et is True


def test_oz_mal_sefer_requires_arac(app):
    with app.app_context():
        rental, lines = _rental()
        payload = _payload(lines)
        payload[0]['arac_id'] = None
        with pytest.raises(ValidationError, match='araç'):
            NakliyeSeferService.sync_kiralama(rental, payload)


def test_taseron_sefer_requires_firma(app):
    with app.app_context():
        rental, lines = _rental()
        payload = _payload(lines)
        payload[0]['nakliye_tipi'] = 'taseron'
        payload[0]['arac_id'] = None
        payload[0]['taseron_firma_id'] = 0
        with pytest.raises(ValidationError, match='firma'):
            NakliyeSeferService.sync_kiralama(rental, payload)


def test_cift_yon_package_is_not_doubled_and_real_donus_replaces_planned_share(app):
    with app.app_context():
        rental, lines = _rental()
        payload = _payload(lines, amount1='100', amount2='200')
        payload[0]['cift_yon'] = True
        NakliyeSeferService.sync_kiralama(rental, payload)
        db.session.commit()
        db.session.refresh(lines[0])
        db.session.refresh(lines[1])
        assert lines[0].nakliye_satis_fiyat == Decimal('100.00')
        assert lines[1].nakliye_satis_fiyat == Decimal('200.00')
        assert lines[0].donus_nakliye_fatura_et is True

        NakliyeSeferService.sync_kiralama(
            rental, _payload(lines, amount1='30', amount2='50', yon='donus', date_value='2026-08-11'),
            allow_new_donus=True,
        )
        db.session.commit()
        db.session.refresh(lines[0])
        db.session.refresh(lines[1])
        assert lines[0].nakliye_satis_fiyat == Decimal('80.00')
        assert lines[1].nakliye_satis_fiyat == Decimal('150.00')


def test_zero_real_donus_does_not_fall_back_to_planned_and_parent_must_be_active(app):
    with app.app_context():
        rental, lines = _rental()
        gidis = _payload(lines, amount1='100', amount2='200')
        gidis[0]['cift_yon'] = True
        NakliyeSeferService.sync_kiralama(rental, gidis)
        NakliyeSeferService.sync_kiralama(
            rental,
            _payload(lines, amount1='0', amount2='50', yon='donus', date_value='2026-08-11'),
            allow_new_donus=True,
        )
        db.session.commit()

        db.session.refresh(lines[0])
        assert NakliyeSeferService.has_aktif_donus(lines[0]) is True
        assert lines[0].nakliye_satis_fiyat == Decimal('50.00')
        assert lines[0].donus_nakliye_fatura_et is True

        donus = Nakliye.query.filter_by(kiralama_id=rental.id, yon='donus').one()
        donus.is_deleted = True
        donus.is_active = False
        db.session.commit()
        db.session.expire(lines[0], ['nakliye_dagitimlari'])

        assert NakliyeSeferService.has_aktif_donus(lines[0]) is False
        assert NakliyeSeferService.kalem_satis_tutari(lines[0]) == Decimal('100.00')


def test_bordemir_senaryosu_cari_ve_nakliye_listesi_6000_paketini_bolerek_gosterir(app):
    with app.app_context():
        rental, lines = _rental()
        geylani = _firma('Geylani', supplier=True)
        gidis_arac = _arac()
        donus_arac = _arac()

        gidis_payload = _payload(lines, amount1='6000', amount2='0', arac_id=gidis_arac.id)
        gidis_payload[0].update({
            'cift_yon': True,
            'nakliye_tipi': 'taseron',
            'arac_id': None,
            'taseron_firma_id': geylani.id,
            'taseron_maliyet': '2500',
        })
        NakliyeSeferService.sync_kiralama(rental, gidis_payload)
        db.session.commit()

        gidis = Nakliye.query.filter_by(kiralama_id=rental.id, yon='gidis').one()
        gidis_satis = HizmetKaydi.query.filter_by(
            nakliye_id=gidis.id,
            kaynak='nakliye_dagitim_satis',
            kiralama_kalemi_id=lines[0].id,
            is_deleted=False,
        ).one()
        assert gidis_satis.tutar == Decimal('6000.00')
        assert HizmetKaydi.query.filter_by(
            nakliye_id=gidis.id,
            kaynak='nakliye_sefer_taseron_gider',
            is_deleted=False,
        ).one().tutar == Decimal('2500.00')

        donus_payload = _payload(
            lines,
            amount1='3000',
            amount2='0',
            yon='donus',
            date_value='2026-08-20',
            arac_id=donus_arac.id,
        )
        NakliyeSeferService.sync_kiralama(rental, donus_payload, allow_new_donus=True)
        KiralamaService.guncelle_cari_toplam(rental.id, auto_commit=False)
        db.session.commit()

        db.session.refresh(lines[0])
        assert lines[0].nakliye_satis_fiyat == Decimal('6000.00')
        gidis_satis = db.session.get(HizmetKaydi, gidis_satis.id)
        assert gidis_satis.tutar == Decimal('3000.00')

        donus = Nakliye.query.filter_by(kiralama_id=rental.id, yon='donus').one()
        donus_satis = HizmetKaydi.query.filter_by(
            nakliye_id=donus.id,
            kaynak='nakliye_dagitim_satis',
            kiralama_kalemi_id=lines[0].id,
            is_deleted=False,
        ).one()
        assert donus_satis.tutar == Decimal('3000.00')
        assert HizmetKaydi.query.filter_by(
            firma_id=rental.firma_musteri_id,
            kaynak='nakliye_dagitim_satis',
            kiralama_kalemi_id=lines[0].id,
            is_deleted=False,
        ).with_entities(db.func.sum(HizmetKaydi.tutar)).scalar() == Decimal('6000.00')

        from app.services.nakliye_services import nakliye_satis_kdv_bilgisi
        assert nakliye_satis_kdv_bilgisi(gidis)['matrah'] == 3000.0
        assert nakliye_satis_kdv_bilgisi(donus)['matrah'] == 3000.0

        from app.nakliyeler.routes import _nakliye_stats
        stats = _nakliye_stats([gidis, donus])
        assert stats['ciro'] == Decimal('6000.00')
        assert stats['maliyet'] == Decimal('2500.00')
        assert stats['kar'] == Decimal('3500.00')


def test_soft_deleted_distribution_is_revived_instead_of_duplicated(app):
    with app.app_context():
        rental, lines = _rental()
        payload = _payload(lines, amount1='250', amount2='750')
        NakliyeSeferService.sync_kiralama(rental, payload)
        db.session.commit()

        sefer = Nakliye.query.filter_by(kiralama_id=rental.id, yon='gidis').one()
        dagitim = NakliyeDagitim.query.filter_by(
            nakliye_id=sefer.id,
            kiralama_kalemi_id=lines[0].id,
        ).one()
        dagitim.is_deleted = True
        dagitim.is_active = False
        dagitim.deleted_by_id = 987
        db.session.commit()
        dagitim_id = dagitim.id

        payload[0]['id'] = sefer.id
        NakliyeSeferService.sync_kiralama(rental, payload)
        db.session.commit()

        aktif = NakliyeDagitim.query.filter_by(
            nakliye_id=sefer.id,
            kiralama_kalemi_id=lines[0].id,
            is_deleted=False,
            is_active=True,
        ).one()
        assert aktif.id == dagitim_id
        assert aktif.deleted_by_id is None
        assert NakliyeDagitim.query.filter_by(
            nakliye_id=sefer.id,
            kiralama_kalemi_id=lines[0].id,
        ).count() == 1


def test_guncelle_cari_toplam_does_not_replace_sefer_distribution_cari(app):
    with app.app_context():
        rental, lines = _rental()
        NakliyeSeferService.sync_kiralama(rental, _payload(lines, amount1='125', amount2='875'))
        db.session.commit()
        sefer = Nakliye.query.filter_by(kiralama_id=rental.id, yon='gidis').one()
        distribution_service = HizmetKaydi.query.filter_by(
            nakliye_id=sefer.id,
            kaynak='nakliye_dagitim_satis',
            kiralama_kalemi_id=lines[0].id,
        ).one()
        distribution_service.tutar = Decimal('999.00')
        db.session.commit()

        KiralamaService.guncelle_cari_toplam(rental.id, auto_commit=False)
        db.session.refresh(distribution_service)

        assert distribution_service.tutar == Decimal('125.00')
        assert HizmetKaydi.query.filter_by(
            nakliye_id=sefer.id,
            kaynak='musteri_nakliye',
            is_deleted=False,
        ).count() == 0


def test_taseron_sefer_alis_tevkifat_writes_net_kdv_on_gider(app):
    with app.app_context():
        rental, lines = _rental()
        taseron = _firma('Taşeron', supplier=True)
        payload = _payload(lines, amount1='0', amount2='1000')
        payload[0]['nakliye_tipi'] = 'taseron'
        payload[0]['arac_id'] = None
        payload[0]['taseron_firma_id'] = taseron.id
        payload[0]['taseron_maliyet'] = '500'
        payload[0]['taseron_kdv_orani'] = 20
        payload[0]['taseron_tevkifat_orani'] = '2/10'
        NakliyeSeferService.sync_kiralama(rental, payload)
        db.session.commit()
        sefer = Nakliye.query.filter_by(kiralama_id=rental.id).one()
        gider = HizmetKaydi.query.filter_by(
            nakliye_id=sefer.id,
            kaynak='nakliye_sefer_taseron_gider',
            is_deleted=False,
        ).one()
        assert sefer.taseron_tevkifat_orani == '2/10'
        assert gider.kdv_orani == 16
        assert gider.tutar == Decimal('500.00')


def test_cift_yon_sonlandirma_writes_only_sefer_taseron_gider(app):
    with app.app_context():
        rental, lines = _rental(count=1)
        taseron = _firma('Dönüş Taşeron', supplier=True)
        arac = _arac()
        payload = [{
            'yon': 'gidis',
            'cift_yon': True,
            'tarih': '2026-08-06',
            'islem_tarihi': '2026-08-06',
            'guzergah': 'Depo - Saha',
            'nakliye_tipi': 'oz_mal',
            'arac_id': arac.id,
            'dagitimlar': [{'kiralama_kalemi_id': lines[0].id, 'tutar': '250'}],
        }]
        NakliyeSeferService.sync_kiralama(rental, payload)
        db.session.commit()

        from app.subeler.models import Sube
        sube = Sube(
            isim='Dönüş Sube', adres='Adres', yetkili_kisi='Yetkili', telefon='0212-0000000',
        )
        db.session.add(sube)
        db.session.flush()
        KiralamaKalemiService.sonlandir(
            lines[0].id,
            '2026-08-20',
            str(sube.id),
            is_harici_nakliye=True,
            nakliye_tedarikci_id=taseron.id,
            nakliye_alis_fiyat='75',
            donus_nakliye_alis_kdv=20,
            donus_nakliye_satis_fiyat='100',
        )

        donus = Nakliye.query.filter_by(kiralama_id=rental.id, yon='donus').one()
        assert HizmetKaydi.query.filter_by(
            nakliye_id=donus.id,
            kaynak='nakliye_sefer_taseron_gider',
            is_deleted=False,
        ).count() == 1
        assert HizmetKaydi.query.filter(
            HizmetKaydi.ozel_id == lines[0].id,
            HizmetKaydi.aciklama.like('Dönüş Nakliye:%'),
            HizmetKaydi.is_deleted.is_(False),
        ).count() == 0


def test_kiralama_form_cannot_create_new_donus_sefer(app):
    with app.app_context():
        rental, lines = _rental()
        NakliyeSeferService.sync_kiralama(rental, _payload(lines))
        with pytest.raises(ValidationError, match='sonlandırma'):
            NakliyeSeferService.sync_kiralama(
                rental, _payload(lines, yon='donus', date_value='2026-08-11')
            )


def test_oz_mal_sefer_stores_arac_plaka_not_dropdown_label(app):
    with app.app_context():
        rental, lines = _rental()
        arac = Arac(
            plaka='34ERJ782',
            arac_tipi='kayar kasa',
            marka_model='Test',
            is_nakliye_araci=True,
        )
        db.session.add(arac)
        db.session.flush()
        payload = _payload(lines, arac_id=arac.id)
        payload[0]['plaka'] = '34ERJ782 - kayar kasa'
        NakliyeSeferService.sync_kiralama(rental, payload)
        db.session.commit()
        sefer = Nakliye.query.filter_by(kiralama_id=rental.id).one()
        assert sefer.plaka == '34ERJ782'
        assert len(sefer.plaka) <= 20
        assert sefer.plaka != payload[0]['plaka']


def test_oz_mal_sync_does_not_change_unrelated_nakliye_plaka(app):
    with app.app_context():
        rental, lines = _rental()
        other_customer = _firma('Diğer', customer=True)
        leftover = Nakliye(
            firma_id=other_customer.id,
            guzergah='Eski sefer',
            plaka='34ESKIPLAKA',
            nakliye_tipi='oz_mal',
            tutar=Decimal('10.00'),
            toplam_tutar=Decimal('10.00'),
        )
        db.session.add(leftover)
        db.session.flush()
        leftover_id = leftover.id
        NakliyeSeferService.sync_kiralama(rental, _payload(lines))
        db.session.commit()
        db.session.refresh(leftover)
        assert leftover.id == leftover_id
        assert leftover.plaka == '34ESKIPLAKA'


def test_taseron_sefer_keeps_submitted_plaka(app):
    with app.app_context():
        rental, lines = _rental()
        taseron = _firma('Taşeron', supplier=True)
        payload = _payload(lines)
        payload[0]['nakliye_tipi'] = 'taseron'
        payload[0]['arac_id'] = None
        payload[0]['taseron_firma_id'] = taseron.id
        payload[0]['plaka'] = '34TSR123'
        NakliyeSeferService.sync_kiralama(rental, payload)
        db.session.commit()
        sefer = Nakliye.query.filter_by(kiralama_id=rental.id).one()
        assert sefer.plaka == '34TSR123'
        assert sefer.taseron_firma_id == taseron.id


def test_sefer_sync_mirrors_only_active_gidis_vehicle(app):
    with app.app_context():
        rental, lines = _rental()
        gidis_arac = _arac()
        donus_arac = _arac()

        gidis_payload = _payload(lines, arac_id=gidis_arac.id)
        NakliyeSeferService.sync_kiralama(rental, gidis_payload)
        db.session.commit()
        assert {line.nakliye_araci_id for line in lines} == {gidis_arac.id}

        donus_payload = _payload(
            lines,
            yon='donus',
            date_value='2026-08-11',
            arac_id=donus_arac.id,
        )
        NakliyeSeferService.sync_kiralama(
            rental,
            donus_payload,
            allow_new_donus=True,
        )
        db.session.commit()
        assert {line.nakliye_araci_id for line in lines} == {gidis_arac.id}

        gidis = Nakliye.query.filter_by(kiralama_id=rental.id, yon='gidis').one()
        changed_payload = _payload(lines, arac_id=donus_arac.id)
        changed_payload[0]['id'] = gidis.id
        NakliyeSeferService.sync_kiralama(rental, changed_payload)
        db.session.commit()
        db.session.refresh(gidis)
        assert {line.nakliye_araci_id for line in lines} == {donus_arac.id}
        assert gidis.plaka == donus_arac.plaka


def test_existing_taseron_manual_plaka_is_preserved_when_form_omits_it(app):
    with app.app_context():
        rental, lines = _rental()
        taseron = _firma('Taseron', supplier=True)
        payload = _payload(lines)
        payload[0].update({
            'nakliye_tipi': 'taseron',
            'arac_id': None,
            'taseron_firma_id': taseron.id,
            'plaka': '34TSR456',
        })
        NakliyeSeferService.sync_kiralama(rental, payload)
        db.session.commit()
        sefer = Nakliye.query.filter_by(kiralama_id=rental.id).one()

        edited = _payload(lines)
        edited[0].update({
            'id': sefer.id,
            'nakliye_tipi': 'taseron',
            'arac_id': None,
            'taseron_firma_id': taseron.id,
            'plaka': '',
        })
        NakliyeSeferService.sync_kiralama(rental, edited)
        db.session.commit()
        db.session.refresh(sefer)
        assert sefer.plaka == '34TSR456'


def _kalem_form_data(kalem, **overrides):
    data = {
        'id': kalem.id,
        'kiralama_baslangici': kalem.kiralama_baslangici.isoformat(),
        'kiralama_bitis': kalem.kiralama_bitis.isoformat(),
        'kiralama_brm_fiyat': str(kalem.kiralama_brm_fiyat or 0),
        'kiralama_alis_fiyat': str(kalem.kiralama_alis_fiyat or 0),
        'nakliye_satis_fiyat': str(kalem.nakliye_satis_fiyat or 0),
        'nakliye_alis_fiyat': str(kalem.nakliye_alis_fiyat or 0),
        'dis_tedarik_ekipman': 1 if kalem.is_dis_tedarik_ekipman else 0,
        'ekipman_id': kalem.ekipman_id or 0,
        'dis_tedarik_nakliye': 1 if kalem.is_harici_nakliye else 0,
        'nakliye_araci_id': kalem.nakliye_araci_id or 0,
        'nakliye_tedarikci_id': kalem.nakliye_tedarikci_id or 0,
        'donus_nakliye_fatura_et': 1 if kalem.donus_nakliye_fatura_et else 0,
    }
    data.update(overrides)
    return data


def _sefer_form_payload(sefer, allocations):
    return [{
        'id': sefer.id,
        'sefer_uuid': sefer.sefer_uuid,
        'yon': sefer.yon,
        'tarih': sefer.tarih.isoformat(),
        'islem_tarihi': (sefer.islem_tarihi or sefer.tarih).isoformat(),
        'guzergah': sefer.guzergah,
        'nakliye_tipi': sefer.nakliye_tipi,
        'arac_id': sefer.arac_id,
        'taseron_firma_id': sefer.taseron_firma_id,
        'dagitimlar': allocations,
    }]


def test_update_adds_kalem_with_temp_allocation_after_collection_loaded(app):
    with app.app_context():
        rental, lines = _rental()
        NakliyeSeferService.sync_kiralama(rental, _payload(lines, amount1='100', amount2='200'))
        db.session.commit()
        rental = db.session.get(Kiralama, rental.id)
        assert len(rental.kalemler) == 2
        sefer = Nakliye.query.filter_by(kiralama_id=rental.id, yon='gidis').one()

        new_row = {
            '_temp_id': 'tmp-yeni-kalem',
            'kiralama_baslangici': '2026-08-06',
            'kiralama_bitis': '2026-08-20',
            'kiralama_brm_fiyat': '80',
            'kiralama_alis_fiyat': '0',
            'nakliye_satis_fiyat': '50',
            'nakliye_alis_fiyat': '0',
            'dis_tedarik_ekipman': 0,
            'ekipman_id': 0,
            'dis_tedarik_nakliye': 0,
        }
        stale_payload = _sefer_form_payload(sefer, [
            {'kiralama_kalemi_id': lines[0].id, 'tutar': '100'},
            {'kiralama_kalemi_id': lines[1].id, 'tutar': '200'},
            {'kiralama_kalemi_id': 0, 'kalem_temp_id': 'tmp-yeni-kalem', 'tutar': '50'},
        ])
        KiralamaService.update_kiralama_with_relations(
            rental.id,
            {},
            [_kalem_form_data(lines[0]), _kalem_form_data(lines[1]), new_row],
            nakliye_seferleri=stale_payload,
        )
        kalem_ids = {
            k.id for k in KiralamaKalemi.query.filter_by(kiralama_id=rental.id).filter(
                KiralamaKalemi.is_deleted.is_(False)
            ).all()
        }
        assert len(kalem_ids) == 3
        active_allocs = NakliyeDagitim.query.filter_by(nakliye_id=sefer.id).filter(
            NakliyeDagitim.is_deleted.is_(False)
        ).all()
        assert {d.kiralama_kalemi_id for d in active_allocs} == kalem_ids


def test_update_drops_stale_allocation_for_removed_kalem(app):
    with app.app_context():
        rental, lines = _rental()
        NakliyeSeferService.sync_kiralama(rental, _payload(lines, amount1='100', amount2='200'))
        db.session.commit()
        sefer = Nakliye.query.filter_by(kiralama_id=rental.id, yon='gidis').one()
        stale_payload = _sefer_form_payload(sefer, [
            {'kiralama_kalemi_id': lines[0].id, 'tutar': '100'},
            {'kiralama_kalemi_id': lines[1].id, 'tutar': '200'},
        ])
        KiralamaService.update_kiralama_with_relations(
            rental.id,
            {},
            [_kalem_form_data(lines[1])],
            nakliye_seferleri=stale_payload,
        )
        db.session.refresh(sefer)
        assert sefer.is_deleted is False
        active_allocs = NakliyeDagitim.query.filter_by(nakliye_id=sefer.id).filter(
            NakliyeDagitim.is_deleted.is_(False)
        ).all()
        assert {d.kiralama_kalemi_id for d in active_allocs} == {lines[1].id}
        removed = db.session.get(KiralamaKalemi, lines[0].id)
        assert removed.is_deleted is True


def test_update_archives_sefer_when_its_only_kalem_is_removed(app):
    with app.app_context():
        rental, lines = _rental()
        payload = _payload(lines, amount1='150', amount2='0')
        payload[0]['dagitimlar'] = [{'kiralama_kalemi_id': lines[0].id, 'tutar': '150'}]
        NakliyeSeferService.sync_kiralama(rental, payload)
        db.session.commit()
        sefer = Nakliye.query.filter_by(kiralama_id=rental.id, yon='gidis').one()
        stale_payload = _sefer_form_payload(sefer, [
            {'kiralama_kalemi_id': lines[0].id, 'tutar': '150'},
        ])
        KiralamaService.update_kiralama_with_relations(
            rental.id,
            {},
            [_kalem_form_data(lines[1])],
            nakliye_seferleri=stale_payload,
        )
        db.session.refresh(sefer)
        assert sefer.is_deleted is True
        remaining = KiralamaKalemi.query.filter_by(kiralama_id=rental.id).filter(
            KiralamaKalemi.is_deleted.is_(False)
        ).all()
        assert [k.id for k in remaining] == [lines[1].id]


def test_create_sefer_model_restores_legacy_gidis_texts_from_first_allocation(app):
    with app.app_context():
        customer = _firma('ACR', customer=True)
        sube = Sube(isim='İkitelli', adres='Depo')
        db.session.add(sube)
        db.session.flush()
        first_equipment = _ekipman('PM04', sube)
        second_equipment = _ekipman('PM05', sube)
        arac = _arac()
        form_no = f'PF-TEST-{uuid.uuid4().hex[:8]}'

        created = KiralamaService.create_kiralama_with_relations(
            {
                'kiralama_form_no': form_no,
                'makine_calisma_adresi': 'Şantiye A',
                'firma_musteri_id': customer.id,
                'kdv_orani': 20,
            },
            [
                {
                    '_temp_id': 'kalem-pm04',
                    'ekipman_id': first_equipment.id,
                    'kiralama_baslangici': '2026-09-01',
                    'kiralama_bitis': '2026-09-30',
                    'kiralama_brm_fiyat': '100',
                },
                {
                    '_temp_id': 'kalem-pm05',
                    'ekipman_id': second_equipment.id,
                    'kiralama_baslangici': '2026-09-01',
                    'kiralama_bitis': '2026-09-30',
                    'kiralama_brm_fiyat': '100',
                },
            ],
            nakliye_seferleri=[{
                'yon': 'gidis',
                'tarih': '2026-09-01',
                'islem_tarihi': '2026-09-01',
                'guzergah': 'Kiralama gidişi',
                'aciklama': '   ',
                'nakliye_tipi': 'oz_mal',
                'arac_id': arac.id,
                'dagitimlar': [
                    {'kalem_temp_id': 'kalem-pm05', 'tutar': '200'},
                    {'kalem_temp_id': 'kalem-pm04', 'tutar': '100'},
                ],
            }],
        )

        sefer = Nakliye.query.filter_by(kiralama_id=created.id, yon='gidis').one()
        first_line = next(k for k in created.kalemler if k.ekipman_id == second_equipment.id)
        assert sefer.guzergah == (
            f"{second_equipment.kod}: {sube.isim} şubesi → Şantiye A"
        )
        assert sefer.aciklama == f'Gidiş: {form_no} #{first_line.id}'
        assert Nakliye.query.filter_by(kiralama_id=created.id).count() == 1


def test_create_sefer_model_uses_branchless_fallback_and_preserves_custom_text(app):
    with app.app_context():
        customer = _firma('Müşteri', customer=True)
        equipment = _ekipman('PM06')
        arac = _arac()
        rental, lines = _rental(count=2)
        rental.firma_musteri_id = customer.id
        rental.makine_calisma_adresi = 'Saha B'
        lines[0].ekipman_id = equipment.id
        payload = _payload(lines, amount1='125', amount2='0', arac_id=arac.id)
        payload[0]['dagitimlar'] = [{'kiralama_kalemi_id': lines[0].id, 'tutar': '125'}]
        payload[0]['guzergah'] = 'Kiralama gidişi'
        payload[0]['aciklama'] = ''

        NakliyeSeferService.sync_kiralama(
            rental,
            payload,
            apply_legacy_gidis_defaults=True,
        )
        sefer = Nakliye.query.filter_by(kiralama_id=rental.id).one()
        assert sefer.guzergah == (
            f'{equipment.kod}: Bilinmeyen çıkış → Saha B'
        )
        assert sefer.aciklama == f'Gidiş: {rental.kiralama_form_no} #{lines[0].id}'

        custom_rental, custom_lines = _rental(count=2)
        custom_payload = _payload(custom_lines, amount1='75', amount2='0', arac_id=arac.id)
        custom_payload[0]['dagitimlar'] = [
            {'kiralama_kalemi_id': custom_lines[0].id, 'tutar': '75'}
        ]
        custom_payload[0]['guzergah'] = 'Özel depo - özel saha'
        custom_payload[0]['aciklama'] = 'Kullanıcı notu'
        NakliyeSeferService.sync_kiralama(
            custom_rental,
            custom_payload,
            apply_legacy_gidis_defaults=True,
        )
        custom_sefer = Nakliye.query.filter_by(kiralama_id=custom_rental.id).one()
        assert custom_sefer.guzergah == 'Özel depo - özel saha'
        assert custom_sefer.aciklama == 'Kullanıcı notu'

        external_rental, external_lines = _rental(count=2)
        external_rental.firma_musteri_id = customer.id
        external_rental.makine_calisma_adresi = 'Harici saha'
        external_lines[0].is_dis_tedarik_ekipman = True
        external_lines[0].harici_ekipman_marka = 'Zoomlion'
        external_lines[0].harici_ekipman_model = 'ZS0407'
        external_lines[0].harici_ekipman_seri_no = 'EXT-01'
        external_payload = _payload(
            external_lines, amount1='90', amount2='0', arac_id=arac.id,
        )
        external_payload[0]['dagitimlar'] = [
            {'kiralama_kalemi_id': external_lines[0].id, 'tutar': '90'}
        ]
        external_payload[0]['guzergah'] = 'Kiralama gidişi'
        external_payload[0]['aciklama'] = ''
        NakliyeSeferService.sync_kiralama(
            external_rental,
            external_payload,
            apply_legacy_gidis_defaults=True,
        )
        external_sefer = Nakliye.query.filter_by(kiralama_id=external_rental.id).one()
        assert external_sefer.guzergah == (
            'Zoomlion ZS0407 EXT-01: Bilinmeyen çıkış → Harici saha'
        )


def test_regular_sefer_sync_does_not_backfill_existing_generic_text(app):
    with app.app_context():
        rental, lines = _rental(count=2)
        payload = _payload(lines, amount1='100', amount2='0')
        payload[0]['dagitimlar'] = [{'kiralama_kalemi_id': lines[0].id, 'tutar': '100'}]
        payload[0]['guzergah'] = 'Kiralama gidişi'
        payload[0]['aciklama'] = ''

        NakliyeSeferService.sync_kiralama(rental, payload)
        sefer = Nakliye.query.filter_by(kiralama_id=rental.id).one()
        assert sefer.guzergah == 'Kiralama gidişi'
        assert sefer.aciklama is None


def test_taseron_sefer_service_uses_legacy_supplier_description(app):
    with app.app_context():
        rental, lines = _rental(count=2)
        sube = Sube(isim='İkitelli', adres='Depo')
        db.session.add(sube)
        db.session.flush()
        equipment = _ekipman('PM31', sube)
        lines[0].ekipman_id = equipment.id
        supplier = _firma('Nakliye Taşeronu', supplier=True)
        payload = _payload(lines, amount1='1000', amount2='0')
        payload[0].update({
            'nakliye_tipi': 'taseron',
            'arac_id': None,
            'taseron_firma_id': supplier.id,
            'taseron_maliyet': '750',
            'taseron_kdv_orani': 20,
            'dagitimlar': [
                {'kiralama_kalemi_id': lines[0].id, 'tutar': '1000'},
            ],
        })

        NakliyeSeferService.sync_kiralama(rental, payload)
        hizmet = HizmetKaydi.query.filter_by(
            kaynak='nakliye_sefer_taseron_gider',
            firma_id=supplier.id,
            is_deleted=False,
        ).one()

        assert hizmet.kiralama_kalemi_id == lines[0].id
        assert hizmet.fatura_no is None
        assert hizmet.aciklama == (
            f'Taşeron Nakliye Bedeli ({equipment.kod}) - {rental.kiralama_form_no}'
        )
