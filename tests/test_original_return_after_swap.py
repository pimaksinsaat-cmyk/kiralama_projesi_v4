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
from app.services.firma_services import FirmaService
from app.services.ekipman_rapor_services import EkipmanRaporuService
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


def test_senaryo_pm01_pm02_pm10_cari_makine_arac_ve_nakliye_raporlari(app):
    with app.app_context():
        from app.services.makine_degisim_services import MakineDegisimService

        start = date(2026, 8, 1)
        finish = date(2026, 8, 13)
        customer = _firma('3A', customer=True)
        geylani = _firma('Geylani', supplier=True)
        oba = _firma('Oba', supplier=True)
        sube = Sube(isim='Test Depo', adres='Adres', yetkili_kisi='Yetkili', telefon='000')
        db.session.add(sube)
        db.session.flush()
        pm01 = _machine('PM 01', 'kirada')
        pm02 = _machine('PM 02')
        pm10 = _machine('PM 10')
        erj872 = _truck('34 ERJ 872')
        erj782 = _truck('34 ERJ 782')

        rental = Kiralama(
            kiralama_form_no=f'PF-3A-RETURN-{uuid.uuid4().hex[:6]}',
            firma_musteri_id=customer.id, kdv_orani=20, nakliye_modeli='sefer',
            kiralama_olusturma_tarihi=start,
        )
        db.session.add(rental)
        db.session.flush()
        first = KiralamaKalemi(
            kiralama_id=rental.id, ekipman_id=pm01.id,
            kiralama_baslangici=start, kiralama_bitis=date(2026, 8, 15),
            kiralama_brm_fiyat=Decimal('500'), is_active=True,
            sonlandirildi=False, chain_id=None,
        )
        db.session.add(first)
        db.session.flush()
        first.chain_id = first.id
        db.session.add(first)

        NakliyeSeferService.sync_kiralama(rental, [{
            'yon': 'gidis', 'cift_yon': True, 'tarih': start.isoformat(),
            'islem_tarihi': start.isoformat(), 'guzergah': 'Depo - 3A Saha',
            'nakliye_tipi': 'taseron', 'arac_id': None,
            'taseron_firma_id': geylani.id, 'taseron_maliyet': '2500',
            'taseron_kdv_orani': 20, 'taseron_tevkifat_orani': '',
            'kdv_orani': 20, 'tevkifat_orani': '2/10',
            'dagitimlar': [{'kiralama_kalemi_id': first.id, 'tutar': '6000'}],
        }])
        db.session.commit()

        MakineDegisimService.degisim_uygula(first.id, {
            'degisim_tarihi': date(2026, 8, 5), 'neden': 'serviste',
            'donus_sube_val': str(sube.id), 'kiralama_brm_fiyat': Decimal('500'),
            'yeni_ekipman_id': pm02.id, 'is_harici_nakliye': False,
            'nakliye_araci_id': erj872.id, 'nakliye_satis_fiyat': Decimal('0'),
            'nakliye_alis_fiyat': Decimal('0'), 'yeni_nakliye_ekle': True,
        })
        second = KiralamaKalemi.query.filter_by(parent_id=first.id, is_active=True).one()

        MakineDegisimService.degisim_uygula(second.id, {
            'degisim_tarihi': date(2026, 8, 10), 'neden': 'bosta',
            'donus_sube_val': str(sube.id), 'kiralama_brm_fiyat': Decimal('500'),
            'yeni_ekipman_id': pm10.id, 'is_harici_nakliye': True,
            'nakliye_tedarikci_id': oba.id, 'nakliye_satis_fiyat': Decimal('2500'),
            'nakliye_alis_fiyat': Decimal('2500'), 'nakliye_alis_kdv': 20,
            'yeni_nakliye_ekle': True,
        })
        third = KiralamaKalemi.query.filter_by(parent_id=second.id, is_active=True).one()

        KiralamaKalemiService.sonlandir(
            third.id, finish.isoformat(), str(sube.id),
            is_harici_nakliye=False, nakliye_araci_id=erj782.id,
        )

        swap = Nakliye.query.filter(
            Nakliye.kiralama_id == rental.id,
            Nakliye.yon == 'gidis',
            Nakliye.tutar == Decimal('2500'),
            Nakliye.taseron_firma_id == oba.id,
            Nakliye.is_deleted.is_(False),
            Nakliye.is_active.is_(True),
        ).one()
        assert swap.cift_yon is False

        donus = Nakliye.query.filter(
            Nakliye.kiralama_id == rental.id,
            Nakliye.yon == 'donus',
            Nakliye.is_deleted.is_(False),
            Nakliye.is_active.is_(True),
        ).one()
        assert donus.arac_id == erj782.id
        assert donus.tutar == Decimal('3000')
        assert NakliyeDagitim.query.filter_by(
            nakliye_id=donus.id, kiralama_kalemi_id=first.id,
            is_deleted=False, is_active=True,
        ).one().tutar == Decimal('3000')
        assert NakliyeDagitim.query.filter_by(
            nakliye_id=donus.id, kiralama_kalemi_id=third.id,
            is_deleted=False, is_active=True,
        ).count() == 0

        sales = HizmetKaydi.query.filter(
            HizmetKaydi.firma_id == customer.id,
            HizmetKaydi.kaynak == 'nakliye_dagitim_satis',
            HizmetKaydi.is_deleted.is_(False),
        ).all()
        assert sorted(Decimal(row.tutar) for row in sales) == [
            Decimal('2500'), Decimal('3000'), Decimal('3000'),
        ]

        rows = FirmaService.build_cari_rows(customer, finish)
        transport_base = sum(
            Decimal(str(row['matrah'])) for row in rows if row.get('islem_turu') == 'nakliye'
        )
        assert transport_base == Decimal('8500')
        assert sum(Decimal(str(row['toplam'])) for row in rows) == Decimal('17760')

        # Tedarikçi carileri: Geylani ve Oba'ya yalnızca 2.500 TL maliyet
        # seferleri oluşur; müşteri tevkifatı tedarikçi giderine taşınmaz.
        geylani_giderleri = HizmetKaydi.query.filter(
            HizmetKaydi.firma_id == geylani.id,
            HizmetKaydi.kaynak == 'nakliye_sefer_taseron_gider',
            HizmetKaydi.is_deleted.is_(False),
        ).all()
        oba_giderleri = HizmetKaydi.query.filter(
            HizmetKaydi.firma_id == oba.id,
            HizmetKaydi.kaynak == 'nakliye_sefer_taseron_gider',
            HizmetKaydi.is_deleted.is_(False),
        ).all()
        assert [Decimal(row.tutar) for row in geylani_giderleri] == [Decimal('2500')]
        assert [Decimal(row.tutar) for row in oba_giderleri] == [Decimal('2500')]
        for supplier in (geylani, oba):
            supplier_rows = FirmaService.build_cari_rows(supplier, finish)
            supplier_transport_rows = [
                row for row in supplier_rows if row.get('islem_turu') == 'nakliye_tedarik'
            ]
            assert sum(Decimal(str(row['matrah'])) for row in supplier_transport_rows) == Decimal('2500')
            assert sum(Decimal(str(row['toplam'])) for row in supplier_transport_rows) == Decimal('-3000')

        assert EkipmanRaporuService._calculate_kirlama_geliri(
            pm01.id, start, finish,
        ) == Decimal('2000')
        assert EkipmanRaporuService._calculate_kirlama_geliri(
            pm02.id, start, finish,
        ) == Decimal('2500')
        assert EkipmanRaporuService._calculate_kirlama_geliri(
            pm10.id, start, finish,
        ) == Decimal('2000')

        transport = RaporlamaService._calculate_transport_metrics(start, finish)
        erj872_row = next(row for row in transport['vehicle_rows'] if row['arac'] == '34 ERJ 872')
        erj782_row = next(row for row in transport['vehicle_rows'] if row['arac'] == '34 ERJ 782')
        assert erj872_row['gelir'] == 0
        assert erj872_row['net'] == 0
        assert erj782_row['gelir'] == 3000
        assert erj782_row['net'] == 3000
        assert sum(row['gelir'] for row in transport['vehicle_rows']) == 8500
        assert sum(row['maliyet'] for row in transport['vehicle_rows']) == 5000
        assert sum(row['net'] for row in transport['vehicle_rows']) == 3500

        active_seferler = Nakliye.query.filter(
            Nakliye.kiralama_id == rental.id,
            Nakliye.is_deleted.is_(False),
            Nakliye.is_active.is_(True),
        ).all()
        nakliye_stats = _nakliye_stats(active_seferler)
        assert nakliye_stats['ciro'] == Decimal('8500')
        assert nakliye_stats['maliyet'] == Decimal('5000')
        assert nakliye_stats['kar'] == Decimal('3500')
