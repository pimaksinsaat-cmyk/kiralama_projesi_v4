from datetime import date
from decimal import Decimal
import uuid

from app.araclar.models import Arac
from app.cari.models import HizmetKaydi
from app.extensions import db
from app.firmalar.models import Firma
from app.filo.models import Ekipman
from app.kiralama.models import Kiralama, KiralamaKalemi
from app.nakliyeler.models import Nakliye, NakliyeDagitim
from app.nakliyeler.routes import _nakliye_stats
from app.services.ekipman_rapor_services import EkipmanRaporuService
from app.services.firma_services import FirmaService
from app.services.kiralama_services import KiralamaKalemiService
from app.services.nakliye_sefer_services import NakliyeSeferService
from app.services.raporlama_services import RaporlamaService
from app.subeler.models import Sube


def _firma(name, *, customer=False, supplier=False):
    row = Firma(
        firma_adi=f'{name}-{uuid.uuid4().hex[:6]}',
        yetkili_adi='Yetkili', iletisim_bilgileri='Adres', vergi_dairesi='VD',
        vergi_no=f'V-{uuid.uuid4().hex[:10]}',
        is_musteri=customer, is_tedarikci=supplier, bakiye=Decimal('0'),
    )
    db.session.add(row)
    db.session.flush()
    return row


def _machine(code, status='bosta'):
    row = Ekipman(
        kod=code, yakit='Diesel', tipi='Platform', marka='Test', model=code,
        seri_no=f'SN-{code}-{uuid.uuid4().hex[:5]}', calisma_yuksekligi=12,
        kaldirma_kapasitesi=2000, uretim_yili=2024, calisma_durumu=status,
        filoya_giris_tarihi=date(2026, 1, 1),
    )
    db.session.add(row)
    db.session.flush()
    return row


def _truck(plate):
    row = Arac(
        plaka=plate, arac_tipi='Kamyon', marka_model='Test', is_nakliye_araci=True,
    )
    db.session.add(row)
    db.session.flush()
    return row


def test_dynamic_two_machine_scenario_reports_all_financial_flows(app):
    with app.app_context():
        from app.services.makine_degisim_services import MakineDegisimService

        start = date(2026, 9, 1)
        pm30_finish = date(2026, 9, 6)  # 6 günlük kullanım, 7. gün iade süreci
        swap_date = date(2026, 9, 10)
        finish = date(2026, 9, 18)

        customer = _firma('Delta Yapı', customer=True)
        geylani = _firma('Geylani', supplier=True)
        yildiz = _firma('Yıldız', supplier=True)
        oba = _firma('Oba', supplier=True)
        sube = Sube(isim='Dinamik Sube', adres='Adres', yetkili_kisi='Yetkili', telefon='000')
        db.session.add(sube)
        db.session.flush()

        pm20 = _machine('PM20', 'kirada')
        pm21 = _machine('PM21')
        pm22 = _machine('PM22')
        pm30 = _machine('PM30', 'kirada')
        abc123 = _truck('34 ABC 123')
        abc456 = _truck('34 ABC 456')

        rental = Kiralama(
            kiralama_form_no=f'PF-DYNAMIC-{uuid.uuid4().hex[:6]}',
            firma_musteri_id=customer.id,
            kdv_orani=20,
            nakliye_modeli='sefer',
            kiralama_olusturma_tarihi=start,
        )
        db.session.add(rental)
        db.session.flush()

        pm20_line = KiralamaKalemi(
            kiralama_id=rental.id,
            ekipman_id=pm20.id,
            kiralama_baslangici=start,
            kiralama_bitis=date(2026, 9, 15),
            kiralama_brm_fiyat=Decimal('700'),
            is_active=True,
            sonlandirildi=False,
        )
        pm30_line = KiralamaKalemi(
            kiralama_id=rental.id,
            ekipman_id=pm30.id,
            kiralama_baslangici=start,
            kiralama_bitis=date(2026, 9, 10),
            kiralama_brm_fiyat=Decimal('900'),
            is_active=True,
            sonlandirildi=False,
        )
        db.session.add_all([pm20_line, pm30_line])
        db.session.flush()
        pm20_line.chain_id = pm20_line.id
        pm30_line.chain_id = pm30_line.id

        NakliyeSeferService.sync_kiralama(rental, [
            {
                'yon': 'gidis', 'cift_yon': True,
                'tarih': start.isoformat(), 'islem_tarihi': start.isoformat(),
                'guzergah': 'Depo - Delta Yapı PM20',
                'nakliye_tipi': 'taseron', 'arac_id': None,
                'taseron_firma_id': geylani.id, 'taseron_maliyet': '3000',
                'taseron_kdv_orani': 20, 'taseron_tevkifat_orani': '',
                'kdv_orani': 20, 'tevkifat_orani': '2/10',
                'dagitimlar': [{'kiralama_kalemi_id': pm20_line.id, 'tutar': '7000'}],
            },
            {
                'yon': 'gidis', 'cift_yon': False,
                'tarih': start.isoformat(), 'islem_tarihi': start.isoformat(),
                'guzergah': 'Depo - Delta Yapı PM30',
                'nakliye_tipi': 'taseron', 'arac_id': None,
                'taseron_firma_id': yildiz.id, 'taseron_maliyet': '1600',
                'taseron_kdv_orani': 20, 'taseron_tevkifat_orani': '',
                'kdv_orani': 20, 'tevkifat_orani': None,
                'dagitimlar': [{'kiralama_kalemi_id': pm30_line.id, 'tutar': '1800'}],
            },
        ])
        db.session.commit()

        # PM20 arıza yapar: PM21 öz mal araçla ücretsiz değişir.
        MakineDegisimService.degisim_uygula(pm20_line.id, {
            'degisim_tarihi': date(2026, 9, 4), 'neden': 'serviste',
            'donus_sube_val': str(sube.id), 'kiralama_brm_fiyat': Decimal('700'),
            'yeni_ekipman_id': pm21.id, 'is_harici_nakliye': False,
            'nakliye_araci_id': abc123.id,
            'nakliye_satis_fiyat': Decimal('0'), 'nakliye_alis_fiyat': Decimal('0'),
            'yeni_nakliye_ekle': True,
        })
        pm21_line = KiralamaKalemi.query.filter_by(
            parent_id=pm20_line.id, is_active=True,
        ).one()

        # PM30 altıncı gün sonunda erken iade edilir; dönüş Oba'ya ücretlidir.
        KiralamaKalemiService.sonlandir(
            pm30_line.id, pm30_finish.isoformat(), str(sube.id),
            is_harici_nakliye=True, nakliye_tedarikci_id=oba.id,
            nakliye_alis_fiyat=Decimal('1200'), donus_nakliye_alis_kdv=20,
            donus_nakliye_satis_fiyat=Decimal('1200'),
        )

        # PM21 müşteri talebiyle PM22 olur; bu değişim tek yön ücretlidir.
        MakineDegisimService.degisim_uygula(pm21_line.id, {
            'degisim_tarihi': swap_date, 'neden': 'bosta',
            'donus_sube_val': str(sube.id), 'kiralama_brm_fiyat': Decimal('700'),
            'yeni_ekipman_id': pm22.id, 'is_harici_nakliye': True,
            'nakliye_tedarikci_id': oba.id,
            'nakliye_satis_fiyat': Decimal('2200'), 'nakliye_alis_fiyat': Decimal('2200'),
            'nakliye_alis_kdv': 20, 'yeni_nakliye_ekle': True,
        })
        pm22_line = KiralamaKalemi.query.filter_by(
            parent_id=pm21_line.id, is_active=True,
        ).one()

        # PM20 zinciri üç gün uzatılır: PM22'nin planlı bitişi 15'ten 18'e alınır.
        pm22_line.kiralama_bitis = finish
        db.session.add(pm22_line)
        db.session.commit()

        KiralamaKalemiService.sonlandir(
            pm22_line.id, finish.isoformat(), str(sube.id),
            is_harici_nakliye=False, nakliye_araci_id=abc456.id,
        )

        active_seferler = Nakliye.query.filter(
            Nakliye.kiralama_id == rental.id,
            Nakliye.is_deleted.is_(False),
            Nakliye.is_active.is_(True),
        ).all()

        pm20_return = Nakliye.query.filter(
            Nakliye.kiralama_id == rental.id,
            Nakliye.yon == 'donus',
            Nakliye.arac_id == abc456.id,
            Nakliye.is_deleted.is_(False),
            Nakliye.is_active.is_(True),
        ).one()
        assert pm20_return.tutar == Decimal('3500')
        assert NakliyeDagitim.query.filter_by(
            nakliye_id=pm20_return.id,
            kiralama_kalemi_id=pm20_line.id,
            is_deleted=False,
            is_active=True,
        ).one().tutar == Decimal('3500')
        assert NakliyeDagitim.query.filter_by(
            nakliye_id=pm20_return.id,
            kiralama_kalemi_id=pm22_line.id,
            is_deleted=False,
            is_active=True,
        ).count() == 0

        pm30_return = Nakliye.query.filter(
            Nakliye.kiralama_id == rental.id,
            Nakliye.yon == 'donus',
            Nakliye.taseron_firma_id == oba.id,
            Nakliye.tutar == Decimal('1200'),
            Nakliye.is_deleted.is_(False),
            Nakliye.is_active.is_(True),
        ).one()
        assert pm30_return.tutar == Decimal('1200')

        swap_sefer = Nakliye.query.filter(
            Nakliye.kiralama_id == rental.id,
            Nakliye.yon == 'gidis',
            Nakliye.taseron_firma_id == oba.id,
            Nakliye.tutar == Decimal('2200'),
            Nakliye.is_deleted.is_(False),
            Nakliye.is_active.is_(True),
        ).one()
        assert swap_sefer.cift_yon is False

        # PM21 arıza nakliyesi ücretsizdir; müşteri satış carisine girmez.
        assert Nakliye.query.filter(
            Nakliye.kiralama_id == rental.id,
            Nakliye.arac_id == abc123.id,
            Nakliye.tutar == Decimal('0'),
            Nakliye.is_deleted.is_(False),
            Nakliye.is_active.is_(True),
        ).count() == 1

        customer_sales = HizmetKaydi.query.filter(
            HizmetKaydi.firma_id == customer.id,
            HizmetKaydi.kaynak == 'nakliye_dagitim_satis',
            HizmetKaydi.is_deleted.is_(False),
        ).all()
        assert sorted(Decimal(row.tutar) for row in customer_sales) == [
            Decimal('1200'), Decimal('1800'), Decimal('2200'),
            Decimal('3500'), Decimal('3500'),
        ]

        customer_rows = FirmaService.build_cari_rows(customer, finish)
        assert sum(
            Decimal(str(row['matrah']))
            for row in customer_rows
            if row.get('islem_turu') == 'kiralama'
        ) == Decimal('18000')
        assert sum(
            Decimal(str(row['matrah']))
            for row in customer_rows
            if row.get('islem_turu') == 'nakliye'
        ) == Decimal('12200')
        assert sum(Decimal(str(row['toplam'])) for row in customer_rows) == Decimal('35960')

        expected_supplier_rows = {
            geylani.id: (Decimal('3000'), Decimal('-3600')),
            yildiz.id: (Decimal('1600'), Decimal('-1920')),
            oba.id: (Decimal('3400'), Decimal('-4080')),
        }
        for supplier in (geylani, yildiz, oba):
            supplier_rows = FirmaService.build_cari_rows(supplier, finish)
            transport_rows = [
                row for row in supplier_rows
                if row.get('islem_turu') == 'nakliye_tedarik'
            ]
            expected_matrah, expected_total = expected_supplier_rows[supplier.id]
            assert sum(Decimal(str(row['matrah'])) for row in transport_rows) == expected_matrah
            assert sum(Decimal(str(row['toplam'])) for row in transport_rows) == expected_total

        machine_revenues = {
            pm20.id: EkipmanRaporuService._calculate_kirlama_geliri(pm20.id, start, finish),
            pm21.id: EkipmanRaporuService._calculate_kirlama_geliri(pm21.id, start, finish),
            pm22.id: EkipmanRaporuService._calculate_kirlama_geliri(pm22.id, start, finish),
            pm30.id: EkipmanRaporuService._calculate_kirlama_geliri(pm30.id, start, finish),
        }
        assert machine_revenues == {
            pm20.id: Decimal('2100'),
            pm21.id: Decimal('4200'),
            pm22.id: Decimal('6300'),
            pm30.id: Decimal('5400'),
        }

        transport = RaporlamaService._calculate_transport_metrics(start, finish)
        own_rows = {
            row['arac']: row
            for row in transport['vehicle_rows']
            if row['arac'] in {'34 ABC 123', '34 ABC 456'}
        }
        assert own_rows['34 ABC 123']['gelir'] == 0
        assert own_rows['34 ABC 123']['net'] == 0
        assert own_rows['34 ABC 456']['gelir'] == 3500
        assert own_rows['34 ABC 456']['net'] == 3500
        assert sum(row['gelir'] for row in transport['vehicle_rows']) == 12200
        assert sum(row['maliyet'] for row in transport['vehicle_rows']) == 8000
        assert sum(row['net'] for row in transport['vehicle_rows']) == 4200

        stats = _nakliye_stats(active_seferler)
        assert stats['ciro'] == Decimal('12200')
        assert stats['maliyet'] == Decimal('8000')
        assert stats['kar'] == Decimal('4200')
