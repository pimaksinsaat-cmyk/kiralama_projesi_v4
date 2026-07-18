from datetime import date
from decimal import Decimal

from app.extensions import db
from app.firmalar.models import Firma
from app.firmalar.routes import _filter_kiralamalar_bilgi
from app.kiralama.models import Kiralama, KiralamaKalemi
from app.services.firma_services import FirmaService


def _firma(name):
    return Firma(
        firma_adi=name,
        yetkili_adi="Yetkili",
        iletisim_bilgileri="Adres",
        vergi_dairesi="VD",
        vergi_no=f"V-{name}",
        is_musteri=True,
        is_tedarikci=False,
        is_active=True,
    )


def _kiralama(firma, form_no, *, deleted=False):
    kiralama = Kiralama(
        kiralama_form_no=form_no,
        firma_musteri_id=firma.id,
        kiralama_olusturma_tarihi=date(2026, 6, 30),
        kdv_orani=20,
        is_active=not deleted,
        is_deleted=deleted,
    )
    db.session.add(kiralama)
    db.session.flush()
    db.session.add(
        KiralamaKalemi(
            kiralama_id=kiralama.id,
            kiralama_baslangici=date(2026, 6, 30),
            kiralama_bitis=date(2026, 6, 30),
            kiralama_brm_fiyat=Decimal("1000.00"),
            is_active=not deleted,
            is_deleted=deleted,
        )
    )
    return kiralama


def test_soft_deleted_kiralama_firma_listesi_ve_cariden_cikar(app):
    with app.app_context():
        firma = _firma("Soft Delete Cari Test")
        db.session.add(firma)
        db.session.flush()
        aktif = _kiralama(firma, "PF-TEST/AKTIF")
        silinen = _kiralama(firma, "PF-TEST/SILINEN", deleted=True)
        db.session.commit()
        db.session.expire_all()

        rows = FirmaService.build_cari_rows(firma, date(2026, 7, 1))
        form_nolari = {row.get("form_no") for row in rows}
        assert "PF-TEST/AKTIF" in form_nolari
        assert "PF-TEST/SILINEN" not in form_nolari
        assert not any(row.get("kiralama_id") == silinen.id for row in rows)

        listed, *_ = _filter_kiralamalar_bilgi(
            firma,
            "2026-06-01",
            "2026-07-01",
        )
        assert [item.id for item in listed] == [aktif.id]
