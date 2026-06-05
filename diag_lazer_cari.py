import os
import sys
from datetime import date
from decimal import Decimal

drive = next(p for p in os.listdir(r"C:\Users\cuney") if p.startswith("Drive"))
root = os.path.join(r"C:\Users\cuney", drive, "kiralama_projesi_v4")
os.chdir(root)
sys.path.insert(0, root)

from app import create_app
from app.extensions import db
from app.firmalar.models import Firma
from app.nakliyeler.models import Nakliye
from app.kiralama.models import Kiralama, KiralamaKalemi
from app.services.firma_services import FirmaService
from sqlalchemy import or_

app = create_app()

def dec(v):
    if v is None:
        return None
    return float(v) if not isinstance(v, (int, float)) else float(Decimal(str(v)))

with app.app_context():
    patterns = ["%LAZER%", "%Lazer%", "%ISI%", "%Isı%", "%ISI%"]
    q = Firma.query.filter(
        or_(
            Firma.firma_adi.ilike("%lazer%"),
            Firma.firma_adi.ilike("%isi%"),
            Firma.firma_adi.ilike("%isı%"),
        )
    )
    firmalar = q.all()
    print("=== FIRMA MATCHES ===")
    print("count:", len(firmalar))
    for f in firmalar:
        bo = f.bakiye_ozeti or {}
        net = bo.get("net_bakiye_kdvli")
        print({
            "id": f.id,
            "firma_adi": f.firma_adi,
            "cari_bakiye_kdvli": dec(f.cari_bakiye_kdvli),
            "bakiye": dec(f.bakiye),
            "net_bakiye_kdvli": dec(net) if net is not None else None,
            "bakiye_ozeti_keys": list(bo.keys()) if bo else [],
        })

    target = None
    for f in firmalar:
        name = (f.firma_adi or "").upper()
        if "LAZER" in name and ("ISI" in name or "ISI" in name.replace("I", "I")):
            target = f
            break
    if not target and firmalar:
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
    print("full bakiye_ozeti", {k: dec(v) if isinstance(v, (Decimal, int, float)) or (isinstance(v, str) and v.replace('.','',1).isdigit()) else v for k,v in bo.items()})

    nakliyeler = (
        Nakliye.query.filter(Nakliye.firma_id == target.id, Nakliye.is_active.is_(True))
        .order_by(Nakliye.id)
        .all()
    )
    print("\n=== NAKLIYE ROWS (firma_id) count=", len(nakliyeler), "===")
    for n in nakliyeler:
        print({
            "id": n.id,
            "kiralama_id": n.kiralama_id,
            "tutar": dec(n.tutar),
            "kdv_orani": n.kdv_orani,
            "tevkifat_orani": repr(n.tevkifat_orani),
            "guzergah": (n.guzergah or "")[:60],
        })

    # kalemler with nakliye tevkifat on kiralama for this musteri
    kir_ids = [k.id for k in Kiralama.query.filter_by(firma_musteri_id=target.id).all()]
    kalemler = []
    if kir_ids:
        kalemler = KiralamaKalemi.query.filter(
            KiralamaKalemi.kiralama_id.in_(kir_ids),
            KiralamaKalemi.is_active.is_(True),
        ).all()
    print("\n=== KALEM nakliye_satis_tevkifat_oran (musteri kiralamalari) count=", len(kalemler), "===")
    for k in kalemler:
        if k.nakliye_satis_tevkifat_oran or k.nakliye_satis_fiyat or k.nakliye_satis_kdv:
            print({
                "kalem_id": k.id,
                "kiralama_id": k.kiralama_id,
                "nakliye_satis_tevkifat_oran": repr(k.nakliye_satis_tevkifat_oran),
                "nakliye_satis_fiyat": dec(getattr(k, "nakliye_satis_fiyat", None)),
            })

    # reload firma with relationships for build_cari_rows
    from sqlalchemy.orm import joinedload
    firma = (
        Firma.query.options(
            joinedload(Firma.kiralamalar).joinedload(Kiralama.kalemler),
            joinedload(Firma.kiralamalar).joinedload(Kiralama.nakliyeler),
        )
        .filter_by(id=target.id)
        .first()
    )
    rows = FirmaService.build_cari_rows(firma, date.today())
    toplam_sum = sum(float(r.get("toplam") or 0) for r in rows if r.get("islem_turu") in ("kiralama", "nakliye", "fatura", "tahsilat", "odeme") or True)
    # better: last bakiye in rows
    last_bakiye = rows[-1].get("bakiye") if rows else None
    nak_rows = [r for r in rows if r.get("islem_turu") == "nakliye"]
    print("\n=== build_cari_rows ===")
    print("row_count", len(rows))
    print("nakliye_row_count", len(nak_rows))
    for r in nak_rows:
        print({
            "nakliye_id": r.get("nakliye_id"),
            "matrah": r.get("matrah"),
            "kdv_orani": r.get("kdv_orani"),
            "kdv_tutar": r.get("kdv_tutar"),
            "tevkifat_str": r.get("tevkifat_str"),
            "toplam": r.get("toplam"),
        })
    print("final_running_bakiye (last row):", last_bakiye)
    # sum all toplam for debit rows only - check canonical
    from app.services.cari_services import _sync_firma_bakiye
    print("cari_bakiye_kdvli (DB before recompute):", dec(target.cari_bakiye_kdvli))

    null_tevk_but_kalem = []
    for n in nakliyeler:
        if not (n.tevkifat_orani or "").strip():
            # find kalem via kiralama
            kir = Kiralama.query.get(n.kiralama_id) if n.kiralama_id else None
            if kir:
                for k in KiralamaKalemi.query.filter_by(kiralama_id=kir.id, is_active=True).all():
                    if (k.nakliye_satis_tevkifat_oran or "").strip():
                        null_tevk_but_kalem.append((n.id, n.tutar, k.id, k.nakliye_satis_tevkifat_oran))
    print("\n=== nakliye tevkifat NULL but kalem has tevkifat count=", len(null_tevk_but_kalem), "===")
    for item in null_tevk_but_kalem:
        print(item)

    # hypothetical correct toplam if kalem tevkifat applied
    from app.services.nakliye_services import _net_kdv_orani
    alt_sum = 0.0
    for n in nakliyeler:
        t = float(n.tutar or 0)
        tev = n.tevkifat_orani or ""
        if not tev.strip() and n.kiralama_id:
            for k in KiralamaKalemi.query.filter_by(kiralama_id=n.kiralama_id, is_active=True).all():
                if (k.nakliye_satis_tevkifat_oran or "").strip():
                    tev = k.nakliye_satis_tevkifat_oran
                    break
        kdv = float(_net_kdv_orani(n.kdv_orani or 0, tev) or 0)
        alt_sum += t * (1 + kdv/100)
    print("sum nakliye KDVli if tevkifat from nakliye OR kalem fallback:", round(alt_sum, 2))
    brut_sum = sum(float(n.tutar or 0) * (1 + float(n.kdv_orani or 0)/100) for n in nakliyeler)
    print("sum nakliye KDVli brut (nakliye.kdv_orani only, tevkifat ignored):", round(brut_sum, 2))
