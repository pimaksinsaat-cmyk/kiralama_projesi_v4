import argparse
from datetime import date
from decimal import Decimal
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import create_app
from app.cari.models import HizmetKaydi
from app.extensions import db
from app.kiralama.models import KiralamaKalemi
from app.services.kiralama_services import KiralamaService


def _is_dis_kiralama_aciklama():
    return db.or_(
        HizmetKaydi.aciklama.like("Dış Kiralama%"),
        HizmetKaydi.aciklama.like("Dis Kiralama%"),
    )


def _dis_kiralama_kayitlari(kalem):
    return HizmetKaydi.query.filter(
        HizmetKaydi.ozel_id == kalem.id,
        HizmetKaydi.firma_id == kalem.harici_ekipman_tedarikci_id,
        HizmetKaydi.yon == "gelen",
        HizmetKaydi.is_deleted == False,
        _is_dis_kiralama_aciklama(),
    ).order_by(HizmetKaydi.id.asc()).all()


def _legacy_dis_kiralama_kayitlari(kalem):
    form_no = kalem.kiralama.kiralama_form_no if kalem.kiralama else None
    if not form_no:
        return []
    return HizmetKaydi.query.filter(
        HizmetKaydi.ozel_id.is_(None),
        HizmetKaydi.firma_id == kalem.harici_ekipman_tedarikci_id,
        HizmetKaydi.fatura_no == form_no,
        HizmetKaydi.yon == "gelen",
        HizmetKaydi.is_deleted == False,
        _is_dis_kiralama_aciklama(),
    ).order_by(HizmetKaydi.id.asc()).all()


def _create_dis_kiralama_kaydi(kalem, expected):
    makine_adi = kalem.harici_ekipman_marka or "Dış Ekipman"
    return HizmetKaydi(
        firma_id=kalem.harici_ekipman_tedarikci_id,
        tarih=kalem.kiralama_baslangici or (kalem.kiralama.kiralama_olusturma_tarihi if kalem.kiralama else None) or date.today(),
        islem_tarihi=kalem.kiralama_baslangici,
        tutar=expected,
        yon="gelen",
        fatura_no=kalem.kiralama.kiralama_form_no if kalem.kiralama else None,
        ozel_id=kalem.id,
        aciklama=f"Dış Kiralama (Güncelleme): {makine_adi}",
        kdv_orani=kalem.kiralama_alis_kdv,
        kiralama_alis_kdv=kalem.kiralama_alis_kdv,
        nakliye_alis_kdv=kalem.nakliye_alis_kdv,
    )


def main():
    parser = argparse.ArgumentParser(
        description="Dis tedarik kiralama cari kayitlarini kalem suresine gore duzeltir."
    )
    parser.add_argument("--dry-run", action="store_true", help="Sadece raporla, DB'ye yazma.")
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        kalemler = KiralamaKalemi.query.filter(
            KiralamaKalemi.is_dis_tedarik_ekipman == True,
            KiralamaKalemi.harici_ekipman_tedarikci_id.isnot(None),
            KiralamaKalemi.harici_ekipman_tedarikci_id > 0,
            KiralamaKalemi.is_active == True,
            KiralamaKalemi.is_deleted == False,
        ).order_by(KiralamaKalemi.id.asc()).all()

        checked = updated = missing = unchanged = linked = created = 0
        for kalem in kalemler:
            expected = KiralamaService._hesapla_bekleyen_alis_kalem_tutari(kalem)
            kayitlar = _dis_kiralama_kayitlari(kalem)
            checked += 1

            if not kayitlar:
                form_no = kalem.kiralama.kiralama_form_no if kalem.kiralama else "-"
                legacy_kayitlar = _legacy_dis_kiralama_kayitlari(kalem)
                if legacy_kayitlar:
                    for kayit in legacy_kayitlar:
                        print(f"LINK hizmet={kayit.id} kalem={kalem.id} form={form_no}")
                        if not args.dry_run:
                            kayit.ozel_id = kalem.id
                            kayit.islem_tarihi = kalem.kiralama_baslangici or kayit.islem_tarihi
                            db.session.add(kayit)
                        linked += 1
                    kayitlar = legacy_kayitlar
                else:
                    print(f"CREATE kalem={kalem.id} form={form_no} expected={expected}")
                    if not args.dry_run:
                        db.session.add(_create_dis_kiralama_kaydi(kalem, expected))
                    created += 1
                    missing += 1
                    continue

            for kayit in kayitlar:
                current = Decimal(str(kayit.tutar or 0))
                if current == expected:
                    unchanged += 1
                    continue

                form_no = kalem.kiralama.kiralama_form_no if kalem.kiralama else kayit.fatura_no
                print(
                    f"UPDATE hizmet={kayit.id} kalem={kalem.id} form={form_no} "
                    f"{current} -> {expected}"
                )
                if not args.dry_run:
                    kayit.tutar = expected
                    kayit.islem_tarihi = kalem.kiralama_baslangici or kayit.islem_tarihi
                    kayit.kdv_orani = kalem.kiralama_alis_kdv
                    kayit.kiralama_alis_kdv = kalem.kiralama_alis_kdv
                    kayit.nakliye_alis_kdv = kalem.nakliye_alis_kdv
                    db.session.add(kayit)
                updated += 1

        if args.dry_run:
            db.session.rollback()
        else:
            db.session.commit()

        print(f"Kontrol edilen dis tedarik kalemi: {checked}")
        print(f"Guncellenecek/guncellenen hizmet kaydi: {updated}")
        print(f"Linklenecek/linklenen legacy hizmet kaydi: {linked}")
        print(f"Olusturulacak/olusturulan hizmet kaydi: {created}")
        print(f"Degismeyen hizmet kaydi: {unchanged}")
        print(f"Hizmet kaydi bulunamayan kalem: {missing}")
        print("Mod:", "dry-run" if args.dry_run else "write")


if __name__ == "__main__":
    main()
