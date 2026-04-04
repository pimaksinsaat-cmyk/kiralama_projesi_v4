import os
from datetime import date, timedelta
from decimal import Decimal

import pytest
from flask import Flask

from app.extensions import db
from app.araclar.models import Arac  # noqa: F401
from app.cari.models import HizmetKaydi
from app.filo.models import Ekipman
from app.firmalar.models import Firma
from app.kiralama.models import KiralamaKalemi
from app.makinedegisim.models import MakineDegisim  # noqa: F401
from app.nakliyeler.models import Nakliye
from app.services.kiralama_services import KiralamaService
from app.services.makine_degisim_services import MakineDegisimService
from app.subeler.models import Sube  # noqa: F401


class TestConfig:
    SECRET_KEY = 'test-secret'
    SQLALCHEMY_DATABASE_URI = os.environ.get('TEST_DATABASE_URL') or 'sqlite:///:memory:'
    SQLALCHEMY_TRACK_MODIFICATIONS = False


@pytest.fixture()
def app_context():
    app = Flask(__name__)
    app.config.from_object(TestConfig)
    db.init_app(app)

    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


def create_firma(name, vergi_no, *, is_musteri=False, is_tedarikci=False):
    return Firma(
        firma_adi=name,
        yetkili_adi='Test Yetkili',
        telefon='5550000000',
        eposta=f'{vergi_no}@example.com',
        iletisim_bilgileri='Test adres',
        vergi_dairesi='Test VD',
        vergi_no=vergi_no,
        is_musteri=is_musteri,
        is_tedarikci=is_tedarikci,
    )


def create_ekipman(kod, seri_no):
    return Ekipman(
        kod=kod,
        yakit='Dizel',
        tipi='Platform',
        marka='JLG',
        model='450AJ',
        seri_no=seri_no,
        calisma_yuksekligi=16,
        kaldirma_kapasitesi=230,
        uretim_yili=2022,
        calisma_durumu='bosta',
    )


def test_swap_finans_kayitlari_iptalde_temizlenir(app_context):
    musteri = create_firma('SWAP MUSTERI', '9000000001', is_musteri=True)
    dis_tedarikci = create_firma('SWAP DIS TEDARIKCI', '9000000002', is_tedarikci=True)
    nakliye_tedarikci = create_firma('SWAP NAKLIYE TEDARIKCI', '9000000003', is_tedarikci=True)
    eski_makine = create_ekipman('SWAP-001', 'SERI-SWAP-001')

    db.session.add_all([musteri, dis_tedarikci, nakliye_tedarikci, eski_makine])
    db.session.commit()

    kiralama = KiralamaService.create_kiralama_with_relations(
        {
            'kiralama_form_no': 'SWAP-TEST-001',
            'makine_calisma_adresi': 'Test saha',
            'kiralama_olusturma_tarihi': date.today(),
            'firma_musteri_id': musteri.id,
            'kdv_orani': 20,
        },
        [
            {
                'ekipman_id': eski_makine.id,
                'kiralama_baslangici': date.today() - timedelta(days=2),
                'kiralama_bitis': date.today() + timedelta(days=5),
                'kiralama_brm_fiyat': Decimal('1000.00'),
                'kiralama_alis_fiyat': Decimal('0.00'),
                'nakliye_satis_fiyat': Decimal('0.00'),
                'nakliye_alis_fiyat': Decimal('0.00'),
                'donus_nakliye_fatura_et': 0,
                'dis_tedarik_ekipman': 0,
                'dis_tedarik_nakliye': 0,
            }
        ],
    )

    eski_kalem = KiralamaKalemi.query.filter_by(kiralama_id=kiralama.id, is_active=True).one()

    MakineDegisimService.degisim_uygula(
        eski_kalem.id,
        {
            'degisim_tarihi': date.today(),
            'neden': 'serviste',
            'yeni_ekipman_id': None,
            'kiralama_brm_fiyat': Decimal('1200.00'),
            'donus_sube_val': None,
            'is_dis_tedarik': True,
            'harici_ekipman_tedarikci_id': dis_tedarikci.id,
            'harici_marka': 'CAT',
            'harici_model': '320D',
            'harici_seri_no': 'HARICI-001',
            'harici_tipi': 'Ekskavator',
            'harici_kapasite': 20,
            'harici_yukseklik': 5,
            'harici_uretim_yili': 2021,
            'kiralama_alis_fiyat': Decimal('800.00'),
            'yeni_nakliye_ekle': True,
            'is_harici_nakliye': True,
            'nakliye_satis_fiyat': Decimal('500.00'),
            'nakliye_alis_fiyat': Decimal('400.00'),
            'nakliye_tedarikci_id': nakliye_tedarikci.id,
            'nakliye_araci_id': None,
        },
    )

    yeni_kalem = KiralamaKalemi.query.filter_by(parent_id=eski_kalem.id, is_active=True).one()
    swap_nakliye = Nakliye.query.filter(
        Nakliye.kiralama_id == kiralama.id,
        Nakliye.aciklama.like(f'Makine Değişim (Swap) Operasyonu [Ref:{yeni_kalem.id}]%')
    ).one()

    kira_gideri = HizmetKaydi.query.filter_by(
        firma_id=dis_tedarikci.id,
        ozel_id=yeni_kalem.id,
        yon='gelen',
    ).one()
    assert kira_gideri.aciklama == 'SWAP MUSTERI projesi CAT 320D makinesi kira bedeli'

    taseron_gideri = HizmetKaydi.query.filter_by(
        firma_id=nakliye_tedarikci.id,
        ozel_id=swap_nakliye.id,
        yon='gelen',
    ).one()
    assert taseron_gideri.tutar == Decimal('400.00')

    degisim_log = MakineDegisim.query.filter_by(yeni_kalem_id=yeni_kalem.id).one()
    assert degisim_log.swap_nakliye_id == swap_nakliye.id
    assert degisim_log.swap_taseron_hizmet_id == taseron_gideri.id
    assert degisim_log.swap_kira_hizmet_id == kira_gideri.id

    assert HizmetKaydi.query.filter_by(
        firma_id=dis_tedarikci.id,
        ozel_id=kiralama.id,
        yon='gelen',
    ).count() == 0

    swap_nakliye.aciklama = 'LEGACY METIN BOZULDU'
    db.session.commit()

    MakineDegisimService.iptal_et(eski_kalem.id)

    assert HizmetKaydi.query.filter_by(
        firma_id=dis_tedarikci.id,
        ozel_id=yeni_kalem.id,
        yon='gelen',
    ).count() == 0
    assert HizmetKaydi.query.filter_by(
        firma_id=nakliye_tedarikci.id,
        ozel_id=swap_nakliye.id,
        yon='gelen',
    ).count() == 0
    assert Nakliye.query.filter_by(id=swap_nakliye.id).count() == 0
    assert KiralamaKalemi.query.filter_by(id=eski_kalem.id, is_active=True).count() == 1


def test_swap_eski_kalem_tahakkuku_musteri_carisinde_korunur(app_context):
    musteri = create_firma('SWAP CARI MUSTERI', '9010000001', is_musteri=True)
    eski_makine = create_ekipman('SWAP-CARI-001', 'SERI-SWAP-CARI-001')
    yeni_makine = create_ekipman('SWAP-CARI-002', 'SERI-SWAP-CARI-002')

    db.session.add_all([musteri, eski_makine, yeni_makine])
    db.session.commit()

    kiralama = KiralamaService.create_kiralama_with_relations(
        {
            'kiralama_form_no': 'SWAP-CARI-001',
            'makine_calisma_adresi': 'Cari test saha',
            'kiralama_olusturma_tarihi': date.today(),
            'firma_musteri_id': musteri.id,
            'kdv_orani': 20,
        },
        [
            {
                'ekipman_id': eski_makine.id,
                'kiralama_baslangici': date.today() - timedelta(days=2),
                'kiralama_bitis': date.today() + timedelta(days=5),
                'kiralama_brm_fiyat': Decimal('1000.00'),
                'kiralama_alis_fiyat': Decimal('0.00'),
                'nakliye_satis_fiyat': Decimal('0.00'),
                'nakliye_alis_fiyat': Decimal('0.00'),
                'donus_nakliye_fatura_et': 0,
                'dis_tedarik_ekipman': 0,
                'dis_tedarik_nakliye': 0,
            }
        ],
    )

    eski_kalem = KiralamaKalemi.query.filter_by(kiralama_id=kiralama.id, is_active=True).one()

    MakineDegisimService.degisim_uygula(
        eski_kalem.id,
        {
            'degisim_tarihi': date.today(),
            'neden': 'serviste',
            'yeni_ekipman_id': yeni_makine.id,
            'kiralama_brm_fiyat': Decimal('1200.00'),
            'donus_sube_val': None,
            'is_dis_tedarik': False,
            'kiralama_alis_fiyat': Decimal('0.00'),
            'yeni_nakliye_ekle': False,
            'is_harici_nakliye': False,
            'nakliye_satis_fiyat': Decimal('0.00'),
            'nakliye_alis_fiyat': Decimal('0.00'),
            'nakliye_tedarikci_id': None,
            'nakliye_araci_id': None,
        },
    )

    bekleyen_bakiye = HizmetKaydi.query.filter_by(
        firma_id=musteri.id,
        ozel_id=kiralama.id,
        yon='giden',
    ).filter(HizmetKaydi.aciklama.like('Kiralama Bekleyen Bakiye%')).one()

    assert bekleyen_bakiye.tutar == Decimal('3200.00')