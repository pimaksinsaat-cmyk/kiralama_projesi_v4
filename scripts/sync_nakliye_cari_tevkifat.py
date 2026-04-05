"""
sync_nakliye_cari_tevkifat.py
-------------------------------
Mevcut tüm kiralama kayıtlarının cari hareketlerini yeni mantığa göre düzeltir:

  1. "Kiralama Bekleyen Bakiye" tutarından nakliyeyi çıkarır (sadece kira kalır).
  2. Her nakliye için HizmetKaydi'yi tevkifat uygulanmış net KDV ile yeniden yazar.

Çalıştırma:
  python scripts/sync_nakliye_cari_tevkifat.py
  python scripts/sync_nakliye_cari_tevkifat.py --dry-run   # Kayıt yazmadan raporlar
"""

import os
import sys
import argparse
from decimal import Decimal

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from app import create_app
from app.extensions import db
from app.kiralama.models import Kiralama
from app.nakliyeler.models import Nakliye
from app.cari.models import HizmetKaydi
from app.services.kiralama_services import KiralamaService
from app.services.nakliye_services import CariServis as NakliyeCariServis


def _net_kdv_orani(kdv_orani, tevkifat_str):
    if not tevkifat_str or not kdv_orani:
        return kdv_orani
    try:
        pay, payda = map(int, str(tevkifat_str).split('/'))
        return kdv_orani * (payda - pay) / payda
    except (ValueError, ZeroDivisionError):
        return kdv_orani


def main(dry_run=False):
    app = create_app()
    with app.app_context():
        mod = "[DRY-RUN]" if dry_run else "[UYGULA]"

        kiralamalar = Kiralama.query.order_by(Kiralama.id.asc()).all()
        print(f"{mod} Toplam kiralama: {len(kiralamalar)}")

        kir_ok = kir_fail = 0
        nak_guncellenen = nak_fail = 0

        for kiralama in kiralamalar:
            # ── 1. Bekleyen bakiyeyi yeniden hesapla (nakliyesiz) ──────────────
            try:
                if not dry_run:
                    KiralamaService.guncelle_cari_toplam(kiralama.id, auto_commit=False)
                kir_ok += 1
            except Exception as exc:
                db.session.rollback()
                kir_fail += 1
                print(f"  [HATA] Kiralama ID={kiralama.id} ({kiralama.kiralama_form_no}): {exc}")
                continue

            # ── 2. Bu kiralama'ya bağlı müşteri nakliyelerini senkronize et ────
            for nakliye in kiralama.nakliyeler:
                kdv_tam = (nakliye.kdv_orani or 0)
                tevkifat = nakliye.tevkifat_orani or ''
                net_kdv = _net_kdv_orani(kdv_tam, tevkifat)

                mevcut = HizmetKaydi.query.filter_by(
                    nakliye_id=nakliye.id, yon='giden'
                ).first()

                eski_kdv = getattr(mevcut, 'kdv_orani', None)

                print(
                    f"  Nakliye ID={nakliye.id} | Form={kiralama.kiralama_form_no} "
                    f"| tutar={nakliye.toplam_tutar} | kdv_tam=%{kdv_tam} "
                    f"| tevkifat={tevkifat or '-'} | net_kdv=%{net_kdv}"
                    + (f" | mevcut HK kdv_orani=%{eski_kdv} → %{net_kdv}" if mevcut else " | yeni HK oluşacak")
                )

                try:
                    if not dry_run:
                        NakliyeCariServis.musteri_nakliye_senkronize_et(nakliye)
                    nak_guncellenen += 1
                except Exception as exc:
                    db.session.rollback()
                    nak_fail += 1
                    print(f"    [HATA] Nakliye ID={nakliye.id}: {exc}")

        if not dry_run:
            try:
                db.session.commit()
                print(f"\n[OK] Commit başarılı.")
            except Exception as exc:
                db.session.rollback()
                print(f"\n[KRİTİK] Commit hatası: {exc}")
                return

        print(f"\n── ÖZET ──────────────────────────────────────")
        print(f"  Kiralama bekleyen bakiye güncellenen : {kir_ok}")
        print(f"  Kiralama güncelleme hatası           : {kir_fail}")
        print(f"  Nakliye HizmetKaydi güncellenen      : {nak_guncellenen}")
        print(f"  Nakliye güncelleme hatası             : {nak_fail}")
        if dry_run:
            print(f"\n  [DRY-RUN] Hiçbir kayıt değiştirilmedi.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Veritabanına yazmadan sadece raporlar."
    )
    args = parser.parse_args()
    main(dry_run=args.dry_run)
