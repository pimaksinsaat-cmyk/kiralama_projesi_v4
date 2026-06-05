from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from app.extensions import db
from app.filo.models import Ekipman, BakimKaydi
from app.firmalar.models import Firma
from app.kiralama.models import Kiralama, KiralamaKalemi
from app.subeler.models import Sube


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
