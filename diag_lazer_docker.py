import os
import sys
from datetime import date
from decimal import Decimal

root = "/app"
os.chdir(root)
sys.path.insert(0, root)

from app import create_app
from app.extensions import db
from app.firmalar.models import Firma
from app.nakliyeler.models import Nakliye
from app.kiralama.models import Kiralama, KiralamaKalemi
from app.services.firma_services import FirmaService
from sqlalchemy import or_
from sqlalchemy.orm import joinedload

app = create_app()

def dec(v):
    if v is None:
        return None
    try:
        return float(Decimal(str(v)))
    except Exception:
        return v

with app.app_context():
    firmalar = Firma.query.filter(
        or_(
            Firma.firma_adi.ilike("%lazer%"),
            Firma.firma_adi.ilike("%isi%"),
            Firma.firma_adi.ilike("%isı%"),
        )
    ).all()
    print("=== FIRMA MATCHES ===")
    print("count:", len(firmalar))
    for f in firmalar:
        bo = f.bakiye_ozeti or {}
        print({
            "id": f.id,
            "firma_adi": f.firma_adi,
            "cari_bakiye_kdvli": dec(f.cari_bakiye_kdvli),
            "bakiye": dec(f.bakiye),
            "net_bakiye_kdvli": dec(bo.get("net_bakiye_kdvli")),
        })

    target = None
    for f in firmalar:
        name = (f.firma_adi or "").upper()
        if "LAZER" in name and "IS" in name:
            target = f
            break
    if not target:
        for f in firmalar:
            if "LAZER" in (f.firma_adi or "").upper():
                target = f
                break
    if not target and firmalar:
        target = firmalar[0]

    if not target:
        print("NO TARGET FIRMA")
        sys.exit(0)

    print("\n=== TARGET FIRMA ===")
    bo = target.bakiye_ozeti or {}
    print("id", target.id)
    print("firma_adi", target.firma_adi)
    print("cari_bakiye_kdvli", dec(target.cari_bakiye_kdvli))
    print("bakiye", dec(target.bakiye))
    print("net_bakiye_kdvli", dec(bo.get("net_bakiye_kdvli")))
    for k, v in sorted(bo.items()):
        print(f"  bakiye_ozeti.{k} = {v}")

    nakliyeler = (
        Nakliye.query.filter(Nakliye.firma_id == target.id, Nakliye.is_active.is_(True))
        .order_by(Nakliye.id)
        .all()
    )
    print("\n=== NAKLIYE ROWS count=", len(nakliyeler), "===")
    for n in nakliyeler:
        print({
            "id": n.id,
            "kiralama_id": n.kiralama_id,
            "tutar": dec(n.tutar),
            "kdv_orani": n.kdv_orani,
            "tevkifat_orani": n.tevkifat_orani,
            "guzergah": (n.guzergah or "")[:80],
        })

    kir_ids = [k.id for k in Kiralama.query.filter_by(firma_musteri_id=target.id).all()]
    kalemler = []
    if kir_ids:
        kalemler = KiralamaKalemi.query.filter(
            KiralamaKalemi.kiralama_id.in_(kir_ids),
            KiralamaKalemi.is_active.is_(True),
        ).all()
    print("\n=== KALEMLER with nakliye_satis_tevkifat_oran ===")
    for k in kalemler:
        tev = k.nakliye_satis_tevkifat_oran
        if tev:
            print({"kalem_id": k.id, "kiralama_id": k.kiralama_id, "nakliye_satis_tevkifat_oran": tev})

    firma = (
        Firma.query.options(
            joinedload(Firma.kiralamalar).joinedload(Kiralama.kalemler),
            joinedload(Firma.kiralamalar).joinedload(Kiralama.nakliyeler),
        )
        .filter_by(id=target.id)
        .first()
    )
    rows = FirmaService.build_cari_rows(firma, date.today())
    nak_rows = [r for r in rows if r.get("islem_turu") == "nakliye"]
    print("\n=== build_cari_rows ===")
    print("row_count", len(rows))
    print("nakliye_row_count", len(nak_rows))
    nak_toplam_sum = sum(float(r.get("toplam") or 0) for r in nak_rows)
    all_toplam_sum = sum(float(r.get("toplam") or 0) for r in rows)
    for r in nak_rows:
        print({
            "nakliye_id": r.get("nakliye_id"),
            "matrah": r.get("matrah"),
            "kdv_orani": r.get("kdv_orani"),
            "kdv_tutar": r.get("kdv_tutar"),
            "tevkifat_str": r.get("tevkifat_str"),
            "toplam": r.get("toplam"),
        })
    print("sum nakliye toplam in cari rows:", round(nak_toplam_sum, 2))
    print("sum ALL row toplam (naive):", round(all_toplam_sum, 2))
    print("final_running_bakiye last row:", rows[-1].get("bakiye") if rows else None)

    null_tevk_but_kalem = []
    for n in nakliyeler:
        if not (n.tevkifat_orani or "").strip():
            for k in KiralamaKalemi.query.filter_by(kiralama_id=n.kiralama_id, is_active=True).all():
                if (k.nakliye_satis_tevkifat_oran or "").strip():
                    null_tevk_but_kalem.append((n.id, dec(n.tutar), n.kdv_orani, k.id, k.nakliye_satis_tevkifat_oran))
    print("\n=== nakliye tevkifat empty but kalem has tevkifat: count", len(null_tevk_but_kalem), "===")
    for item in null_tevk_but_kalem:
        print(item)

    from app.services.nakliye_services import _net_kdv_orani
    brut_sum = 0.0
    net_sum = 0.0
    for n in nakliyeler:
        t = float(n.tutar or 0)
        brut_kdv = float(n.kdv_orani or 0)
        brut_sum += t * (1 + brut_kdv/100)
        net_kdv = float(FirmaService._musteri_nakliye_kdv_orani(n) or 0)
        net_sum += t * (1 + net_kdv/100)
    print("\n=== NAKLIYE KDVLI TOTALS (active only) ===")
    print("brut (20% on each):", round(brut_sum, 2))
    print("build_cari _musteri_nakliye_kdv_orani:", round(net_sum, 2))
    print("delta brut-net:", round(brut_sum - net_sum, 2))
