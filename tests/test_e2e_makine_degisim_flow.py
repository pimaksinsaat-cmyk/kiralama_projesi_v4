from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from app.extensions import db
from app.filo.models import Ekipman, BakimKaydi
from app.firmalar.models import Firma
from app.kiralama.models import Kiralama, KiralamaKalemi
from app.nakliyeler.models import Nakliye, NakliyeDagitim
from app.araclar.models import Arac
from app.subeler.models import Sube
from app.services.nakliye_sefer_services import NakliyeSeferService


def _unique_kod() -> str:
    return f"KRL-{uuid.uuid4().hex[:8].upper()}"


def test_makine_degisim_uygula_ve_iptal_et(app):
    with app.app_context():
        musteri = Firma(
            firma_adi=f"Makine Swap Musteri {uuid.uuid4().hex[:4]}",
            yetkili_adi="Yetkili",
            iletisim_bilgileri="Adres",
            vergi_dairesi="Istanbul VD",
            vergi_no=f"T{uuid.uuid4().hex[:10].upper()}",
            is_musteri=True,
            is_tedarikci=False,
            bakiye=Decimal("0"),
        )
        db.session.add(musteri)

        sube = Sube(
            isim="E2E Swap Sube",
            adres="Adres",
            yetkili_kisi="Yetkili",
            telefon="0212-8000000",
        )
        db.session.add(sube)

        eski_makine = Ekipman(
            kod=_unique_kod(),
            yakit="Diesel",
            tipi="LIFT",
            marka="Brand Eski",
            model="M1",
            seri_no=f"SN-{uuid.uuid4().hex[:8]}",
            calisma_yuksekligi=15,
            kaldirma_kapasitesi=2500,
            uretim_yili=2024,
            calisma_durumu="kirada",
            sube_id=sube.id,
        )
        yeni_makine = Ekipman(
            kod=_unique_kod(),
            yakit="Diesel",
            tipi="LIFT",
            marka="Brand Yeni",
            model="Y1",
            seri_no=f"SN-{uuid.uuid4().hex[:8]}",
            calisma_yuksekligi=15,
            kaldirma_kapasitesi=3000,
            uretim_yili=2024,
            calisma_durumu="bosta",
            sube_id=sube.id,
        )
        db.session.add_all([eski_makine, yeni_makine])
        db.session.flush()

        kiralama = Kiralama(
            kiralama_form_no=f"PF-SWAP-{uuid.uuid4().hex[:6]}",
            firma_musteri_id=musteri.id,
            kdv_orani=20,
        )
        db.session.add(kiralama)
        db.session.flush()

        aktif_kalem = KiralamaKalemi(
            kiralama_id=kiralama.id,
            ekipman_id=eski_makine.id,
            kiralama_baslangici=date(2026, 5, 1),
            kiralama_bitis=date(2026, 5, 15),
            kiralama_brm_fiyat=Decimal("120.00"),
            sonlandirildi=False,
            is_active=True,
        )
        db.session.add(aktif_kalem)
        db.session.commit()

        from app.services.makine_degisim_services import MakineDegisimService

        data = {
            "degisim_tarihi": date(2026, 5, 10),
            "neden": "serviste",
            "donus_sube_val": "tedarikci",
            "kiralama_brm_fiyat": Decimal("150.00"),
            "yeni_ekipman_id": yeni_makine.id,
            "is_harici_nakliye": False,
            "nakliye_satis_fiyat": Decimal("0.00"),
            "nakliye_alis_fiyat": Decimal("0.00"),
            "nakliye_tedarikci_id": None,
        }

        MakineDegisimService.degisim_uygula(aktif_kalem.id, data)

        db.session.refresh(eski_makine)
        db.session.refresh(yeni_makine)

        assert eski_makine.calisma_durumu == "iade_edildi"
        assert yeni_makine.calisma_durumu == "kirada"

        bakim = BakimKaydi.query.filter_by(ekipman_id=eski_makine.id).first()
        assert bakim is not None
        assert bakim.bakim_tipi == "ariza"
        assert bakim.durum == "acik"

        aktif_yeni_kalem = KiralamaKalemi.query.filter_by(parent_id=aktif_kalem.id, is_active=True).first()
        assert aktif_yeni_kalem is not None
        assert aktif_yeni_kalem.ekipman_id == yeni_makine.id

        MakineDegisimService.iptal_et(aktif_kalem.id)

        db.session.refresh(eski_makine)
        db.session.refresh(yeni_makine)

        assert eski_makine.calisma_durumu == "kirada"
        assert yeni_makine.calisma_durumu == "bosta"
        assert KiralamaKalemi.query.get(aktif_yeni_kalem.id) is None
        assert BakimKaydi.query.filter_by(id=bakim.id).first() is None


def test_sefer_swap_propagates_cift_yon_and_recreates_return_on_cancel(app):
    with app.app_context():
        musteri = Firma(
            firma_adi=f'Swap Sefer Musteri {uuid.uuid4().hex[:4]}',
            yetkili_adi='Yetkili', iletisim_bilgileri='Adres',
            vergi_dairesi='VD', vergi_no=f'S{uuid.uuid4().hex[:10].upper()}',
            is_musteri=True, bakiye=Decimal('0'),
        )
        sube = Sube(
            isim='Swap Sefer Sube', adres='Adres', yetkili_kisi='Yetkili',
            telefon='0212-8000001',
        )
        eski_makine = Ekipman(
            kod=_unique_kod(), yakit='Diesel', tipi='LIFT', marka='Eski',
            model='M1', seri_no=f'SN-{uuid.uuid4().hex[:8]}',
            calisma_yuksekligi=15, kaldirma_kapasitesi=2500,
            uretim_yili=2024, calisma_durumu='kirada',
        )
        yeni_makine = Ekipman(
            kod=_unique_kod(), yakit='Diesel', tipi='LIFT', marka='Yeni',
            model='M2', seri_no=f'SN-{uuid.uuid4().hex[:8]}',
            calisma_yuksekligi=15, kaldirma_kapasitesi=3000,
            uretim_yili=2024, calisma_durumu='bosta',
        )
        arac = Arac(
            plaka=f'SW{uuid.uuid4().hex[:6].upper()}', arac_tipi='Kamyon',
            marka_model='Test', is_nakliye_araci=True,
        )
        db.session.add_all([musteri, sube, eski_makine, yeni_makine, arac])
        db.session.flush()
        kiralama = Kiralama(
            kiralama_form_no=f'PF-SWAP-SEFER-{uuid.uuid4().hex[:6]}',
            firma_musteri_id=musteri.id, kdv_orani=20,
            nakliye_modeli='sefer',
        )
        db.session.add(kiralama)
        db.session.flush()
        eski_kalem = KiralamaKalemi(
            kiralama_id=kiralama.id, ekipman_id=eski_makine.id,
            kiralama_baslangici=date(2026, 5, 1),
            kiralama_bitis=date(2026, 5, 15),
            kiralama_brm_fiyat=Decimal('120.00'),
            is_active=True, sonlandirildi=False,
        )
        db.session.add(eski_kalem)
        db.session.flush()
        NakliyeSeferService.sync_kiralama(kiralama, [{
            'yon': 'gidis', 'cift_yon': True,
            'tarih': '2026-05-01', 'islem_tarihi': '2026-05-01',
            'guzergah': 'Depo - Saha', 'nakliye_tipi': 'oz_mal',
            'arac_id': arac.id,
            'dagitimlar': [{'kiralama_kalemi_id': eski_kalem.id, 'tutar': '250'}],
        }])
        db.session.commit()

        from app.services.makine_degisim_services import MakineDegisimService
        MakineDegisimService.degisim_uygula(eski_kalem.id, {
            'degisim_tarihi': date(2026, 5, 10),
            'neden': 'bosta',
            'donus_sube_val': str(sube.id),
            'kiralama_brm_fiyat': Decimal('150.00'),
            'yeni_ekipman_id': yeni_makine.id,
            'is_harici_nakliye': False,
            'nakliye_araci_id': arac.id,
            'nakliye_satis_fiyat': Decimal('100.00'),
            'nakliye_alis_fiyat': Decimal('0.00'),
            'yeni_nakliye_ekle': True,
        })

        yeni_kalem = KiralamaKalemi.query.filter_by(
            parent_id=eski_kalem.id, is_active=True,
        ).one()
        swap_dagitim = NakliyeDagitim.query.filter_by(
            kiralama_kalemi_id=yeni_kalem.id,
            is_deleted=False,
            is_active=True,
        ).one()
        # Swap bedeli yalnızca değişim bacağıdır; ilk paketin dönüşü
        # zincirin asıl gidiş seferinde korunur.
        assert swap_dagitim.nakliye.cift_yon is False

        MakineDegisimService.iptal_et(eski_kalem.id)
        db.session.refresh(eski_kalem)
        donus = Nakliye.query.filter_by(kiralama_id=kiralama.id, yon='donus').filter(
            Nakliye.is_deleted.is_(False), Nakliye.is_active.is_(True),
        ).one()
        restored = NakliyeDagitim.query.filter_by(
            nakliye_id=donus.id,
            kiralama_kalemi_id=eski_kalem.id,
            is_deleted=False,
            is_active=True,
        ).one()
        assert restored.tutar == Decimal('125.00')
        assert eski_kalem.nakliye_satis_fiyat == Decimal('250.00')

        MakineDegisimService.degisim_uygula(eski_kalem.id, {
            'degisim_tarihi': date(2026, 5, 11),
            'neden': 'bosta',
            'donus_sube_val': str(sube.id),
            'kiralama_brm_fiyat': Decimal('150.00'),
            'yeni_ekipman_id': yeni_makine.id,
            'is_harici_nakliye': True,
            'nakliye_tedarikci_id': None,
            'nakliye_satis_fiyat': Decimal('0.00'),
            'nakliye_alis_fiyat': Decimal('0.00'),
        })
        ikinci_kalem = KiralamaKalemi.query.filter_by(
            parent_id=eski_kalem.id, is_active=True,
        ).one()
        assert NakliyeDagitim.query.filter_by(
            kiralama_kalemi_id=ikinci_kalem.id,
            is_deleted=False,
            is_active=True,
        ).count() == 0
