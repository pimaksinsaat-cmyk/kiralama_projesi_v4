from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from app.cari.models import HizmetKaydi
from app.extensions import db
from app.filo.models import Ekipman
from app.firmalar.models import Firma
from app.kiralama.models import Kiralama, KiralamaKalemi
from app.nakliyeler.models import Nakliye
from app.services.kiralama_services import KiralamaKalemiService
from app.subeler.models import Sube


def _unique_vergi_no() -> str:
    return f"DONUS{uuid.uuid4().hex[:8].upper()}"


def _firma(ad: str, *, musteri: bool = False, tedarikci: bool = False) -> Firma:
    firma = Firma(
        firma_adi=f"{ad} {uuid.uuid4().hex[:4]}",
        yetkili_adi="Yetkili",
        iletisim_bilgileri="Adres",
        vergi_dairesi="Istanbul VD",
        vergi_no=_unique_vergi_no(),
        is_musteri=musteri,
        is_tedarikci=tedarikci,
        bakiye=Decimal("0"),
    )
    db.session.add(firma)
    db.session.flush()
    return firma


def _seed_kiralama(*, gidis_taseron: Firma | None = None) -> tuple[Kiralama, KiralamaKalemi, Sube]:
    sube = Sube(
        isim=f"Donus Sube {uuid.uuid4().hex[:4]}",
        adres="Test Adres",
        yetkili_kisi="Test Yetkili",
        telefon="0212-3333333",
    )
    db.session.add(sube)
    db.session.flush()

    musteri = _firma("Donus Musteri", musteri=True)
    ekipman = Ekipman(
        kod=f"DN-{uuid.uuid4().hex[:6].upper()}",
        yakit="Elektrik",
        tipi="MAKAS",
        marka="Test Marka",
        model="Test Model",
        seri_no=f"SN-{uuid.uuid4().hex[:8]}",
        calisma_yuksekligi=12,
        kaldirma_kapasitesi=2500,
        uretim_yili=2024,
        calisma_durumu="kirada",
        sube_id=sube.id,
    )
    db.session.add(ekipman)
    db.session.flush()

    kiralama = Kiralama(
        kiralama_form_no=f"PF-DONUS-{uuid.uuid4().hex[:6]}",
        firma_musteri_id=musteri.id,
        kdv_orani=20,
    )
    db.session.add(kiralama)
    db.session.flush()

    kalem = KiralamaKalemi(
        kiralama_id=kiralama.id,
        ekipman_id=ekipman.id,
        kiralama_baslangici=date(2026, 5, 18),
        kiralama_bitis=date(2026, 6, 6),
        kiralama_brm_fiyat=Decimal("650.00"),
        nakliye_satis_fiyat=Decimal("5000.00"),
        donus_nakliye_fatura_et=True,
        is_harici_nakliye=gidis_taseron is not None,
        nakliye_tedarikci_id=gidis_taseron.id if gidis_taseron else None,
        nakliye_alis_fiyat=Decimal("1000.00") if gidis_taseron else Decimal("0.00"),
        nakliye_alis_kdv=20 if gidis_taseron else None,
        sonlandirildi=False,
        is_active=True,
    )
    db.session.add(kalem)
    db.session.commit()
    return kiralama, kalem, sube


def test_sifir_donus_satis_fark_degildir_gorunur_sifir_satir_olusturur(app):
    with app.app_context():
        kiralama, kalem, sube = _seed_kiralama()

        KiralamaKalemiService.sonlandir(
            kalem.id,
            "2026-06-06",
            str(sube.id),
            is_harici_nakliye=False,
            donus_nakliye_satis_fiyat="0",
        )

        assert HizmetKaydi.query.filter(
            HizmetKaydi.ozel_id == kalem.id,
            HizmetKaydi.aciklama.like("Nakliye Farkı%"),
            HizmetKaydi.is_deleted == False,
        ).count() == 0

        sifir_satir = HizmetKaydi.query.filter(
            HizmetKaydi.ozel_id == kalem.id,
            HizmetKaydi.nakliye_id.is_(None),
            HizmetKaydi.firma_id == kiralama.firma_musteri_id,
            HizmetKaydi.yon == "giden",
            HizmetKaydi.aciklama.like("Dönüş Nakliye (%"),
            HizmetKaydi.is_deleted == False,
        ).one()
        assert sifir_satir.tutar == Decimal("0.00")

        donus_sefer = Nakliye.query.filter(
            Nakliye.kiralama_id == kiralama.id,
            Nakliye.aciklama == f"Dönüş: {kiralama.kiralama_form_no} #{kalem.id}",
        ).one()
        assert donus_sefer.tutar == Decimal("0.00")


def test_donus_taseronu_gidis_taseronundan_bagimsiz_cariye_islenir(app):
    with app.app_context():
        gidis_taseron = _firma("Gidis Taseron", tedarikci=True)
        donus_taseron = _firma("Donus Taseron", tedarikci=True)
        kiralama, kalem, sube = _seed_kiralama(gidis_taseron=gidis_taseron)

        KiralamaKalemiService.sonlandir(
            kalem.id,
            "2026-06-06",
            str(sube.id),
            is_harici_nakliye=True,
            nakliye_tedarikci_id=donus_taseron.id,
            nakliye_alis_fiyat="2500",
            donus_nakliye_alis_kdv="20",
            donus_nakliye_satis_fiyat="3500",
        )

        donus_taseron_kaydi = HizmetKaydi.query.filter(
            HizmetKaydi.ozel_id == kalem.id,
            HizmetKaydi.firma_id == donus_taseron.id,
            HizmetKaydi.yon == "gelen",
            HizmetKaydi.aciklama.like("Dönüş Nakliye:%"),
            HizmetKaydi.is_deleted == False,
        ).one()
        assert donus_taseron_kaydi.tutar == Decimal("2500.00")

        assert HizmetKaydi.query.filter(
            HizmetKaydi.ozel_id == kalem.id,
            HizmetKaydi.firma_id == gidis_taseron.id,
            HizmetKaydi.aciklama.like("Dönüş Nakliye:%"),
            HizmetKaydi.is_deleted == False,
        ).count() == 0

        donus_sefer = Nakliye.query.filter(
            Nakliye.kiralama_id == kiralama.id,
            Nakliye.aciklama == f"Dönüş: {kiralama.kiralama_form_no} #{kalem.id}",
        ).one()
        assert donus_sefer.tutar == Decimal("3500.00")
        assert donus_sefer.taseron_firma_id == donus_taseron.id
        assert donus_sefer.taseron_maliyet == Decimal("2500.00")
