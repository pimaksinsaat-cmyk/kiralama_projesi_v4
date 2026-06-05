import sys
sys.path.insert(0,"/app")
import os
os.chdir("/app")
from datetime import date
from decimal import Decimal
from app import create_app
from app.firmalar.models import Firma
from app.firmalar import routes as fr
from sqlalchemy.orm import joinedload
from app.kiralama.models import Kiralama

app = create_app()
with app.app_context():
    firma = Firma.query.options(
        joinedload(Firma.kiralamalar).joinedload(Kiralama.kalemler),
        joinedload(Firma.kiralamalar).joinedload(Kiralama.nakliyeler),
    ).get(60)
    today = date.today()
    rows = fr._build_cari_rows(firma, today)
    gb = rows[-1]["bakiye"] if rows else 0
    sum_net = fr._sum_cari_rows_net(rows)
    print("guncel from last row bakiye", gb)
    print("_sum_cari_rows_net", sum_net)
    print("cari_bakiye_kdvli", float(firma.cari_bakiye_kdvli))
    # simulate NULL tevkifat on nakliyeler
    from app.services.firma_services import FirmaService
    for kir in firma.kiralamalar:
        for n in kir.nakliyeler:
            saved = n.tevkifat_orani
            n.tevkifat_orani = None
    rows2 = FirmaService.build_cari_rows(firma, today)
    print("IF tevkifat_orani forced NULL: last bakiye", rows2[-1]["bakiye"])
    for r in rows2:
        if r.get("islem_turu")=="nakliye":
            print("  nak", r["nakliye_id"], r["kdv_orani"], r["toplam"])
