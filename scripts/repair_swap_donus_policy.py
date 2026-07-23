"""Swap nedeni politikasina aykiri stale donus nakliye audit/onarmaci.

Varsayilan mod read-only dry-run'dir. --apply yalnizca serviste/periyodik
swaplarin aktif donus seferlerini ve bagli cari kayitlarini soft-delete eder.
Musteri talebi (bosta) kayitlari korunur.
"""

import argparse

from app import create_app
from app.extensions import db
from app.kiralama.models import KiralamaKalemi
from app.services.kiralama_services import KiralamaService


FREE_REASONS = {'serviste', 'periyodik', 'bakimda'}


def _active_donus_seferi(kalem):
    from app.nakliyeler.models import Nakliye

    if not kalem.kiralama:
        return None
    return Nakliye.query.filter(
        Nakliye.kiralama_id == kalem.kiralama_id,
        Nakliye.aciklama == f"Dönüş: {kalem.kiralama.kiralama_form_no} #{kalem.id}",
        Nakliye.is_active == True,
    ).first()


def main(apply=False):
    app = create_app()
    with app.app_context():
        adaylar = []
        korunacaklar = []
        belirsizler = []
        for kalem in KiralamaKalemi.query.filter(
            KiralamaKalemi.is_deleted == False,
        ).all():
            sefer = _active_donus_seferi(kalem)
            if not sefer:
                continue
            neden = KiralamaService._swap_reason_for_kalem(kalem)
            if neden in FREE_REASONS:
                adaylar.append((kalem, sefer, neden))
            elif neden == 'bosta':
                korunacaklar.append((kalem, sefer, neden))
            else:
                belirsizler.append((kalem, sefer, neden or 'NO_SWAP'))

        print(f"bedelsiz_swap_stale_sayisi={len(adaylar)}")
        print(f"musteri_talebi_korunan_sayisi={len(korunacaklar)}")
        print(f"belirsiz_legacy_sayisi={len(belirsizler)}")
        for kalem, sefer, neden in adaylar:
            print(
                f"TEMIZLENECEK form={kalem.kiralama.kiralama_form_no} "
                f"kalem={kalem.id} nakliye={sefer.id} tutar={sefer.tutar} neden={neden}"
            )
        for kalem, sefer, neden in korunacaklar:
            if sefer.tutar and sefer.tutar > 0:
                print(
                    f"KORUNACAK form={kalem.kiralama.kiralama_form_no} "
                    f"kalem={kalem.id} nakliye={sefer.id} tutar={sefer.tutar} neden={neden}"
                )

        if not apply:
            db.session.rollback()
            return

        affected_firma_ids = set()
        affected_kiralama_ids = set()
        cleaned = 0
        for kalem, sefer, _neden in adaylar:
            affected_firma_ids.add(kalem.kiralama.firma_musteri_id)
            affected_kiralama_ids.add(kalem.kiralama_id)
            cleaned += KiralamaService._soft_delete_donus_nakliye_artifacts(kalem)

        for kiralama_id in affected_kiralama_ids:
            KiralamaService.guncelle_cari_toplam(
                kiralama_id,
                auto_commit=False,
                sync_firma_cache=False,
            )
        KiralamaService.sync_firma_caches(affected_firma_ids, auto_commit=False)
        db.session.commit()
        print(f"soft_delete_sayisi={cleaned}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    main(apply=args.apply)
