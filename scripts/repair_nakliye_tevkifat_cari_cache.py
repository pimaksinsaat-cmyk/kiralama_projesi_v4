"""Tevkifatlı nakliye satışları için firma cari cache ve bakiye yenileme.

Kod düzeltmesi sonrası build_cari_rows artık tevkifat açıkken net KDV kullanır.
Bu script etkilenen müşteri firmalarının cari_bakiye_kdvli ve bakiye alanlarını günceller.
"""
from app import create_app
from app.extensions import db
from app.firmalar.models import Firma
from app.nakliyeler.models import Nakliye
from app.services.cari_services import _sync_firma_bakiye
from app.services.firma_services import FirmaService
from app.services.nakliye_services import CariServis
from sqlalchemy import distinct


def main():
    app = create_app()
    with app.app_context():
        firma_ids = [
            row[0]
            for row in db.session.query(distinct(Nakliye.firma_id))
            .filter(
                Nakliye.is_active.is_(True),
                Nakliye.tevkifat_orani.isnot(None),
                Nakliye.tevkifat_orani != '',
            )
            .all()
        ]

        print(f"Tevkifatlı aktif nakliye kaydı olan firma sayısı: {len(firma_ids)}")

        ok = 0
        fail = 0
        for firma_id in firma_ids:
            firma = db.session.get(Firma, firma_id)
            if not firma:
                continue
            try:
                nakliyeler = Nakliye.query.filter(
                    Nakliye.firma_id == firma_id,
                    Nakliye.is_active.is_(True),
                    Nakliye.tevkifat_orani.isnot(None),
                    Nakliye.tevkifat_orani != '',
                ).all()
                for nakliye in nakliyeler:
                    nakliye.hesapla_ve_guncelle()
                    CariServis.musteri_nakliye_senkronize_et(nakliye)
                db.session.flush()
                FirmaService.guncelle_firma_cari_cache(firma_id, auto_commit=False)
                _sync_firma_bakiye(firma_id)
                ok += 1
                print(f"[OK] firma_id={firma_id} {firma.firma_adi} cari_bakiye_kdvli={firma.cari_bakiye_kdvli}")
            except Exception as exc:
                db.session.rollback()
                fail += 1
                print(f"[HATA] firma_id={firma_id}: {exc}")

        print(f"Basarili: {ok}, Hatali: {fail}")


if __name__ == "__main__":
    main()
