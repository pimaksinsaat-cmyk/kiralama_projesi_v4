import sys, os
from datetime import date
from decimal import Decimal
root="/app"
os.chdir(root)
sys.path.insert(0, root)
from app import create_app
from app.firmalar.models import Firma
from app.services.firma_services import FirmaService
from sqlalchemy.orm import joinedload
from app.kiralama.models import Kiralama

app = create_app()
with app.app_context():
    firma = Firma.query.options(
        joinedload(Firma.kiralamalar).joinedload(Kiralama.kalemler),
        joinedload(Firma.kiralamalar).joinedload(Kiralama.nakliyeler),
    ).get(60)
    rows = FirmaService.build_cari_rows(firma, date.today())
    print("=== ALL cari rows toplam/bakiye ===")
    for r in rows:
        print(r.get("islem_turu"), r.get("id"), r.get("nakliye_id"), "toplam", r.get("toplam"), "bakiye", r.get("bakiye"))
    borc = sum(Decimal(str(r.get("toplam") or 0)) for r in rows if Decimal(str(r.get("toplam") or 0)) > 0)
    alacak = sum(Decimal(str(r.get("toplam") or 0)) for r in rows if Decimal(str(r.get("toplam") or 0)) < 0)
    print("borc_sum", borc, "alacak_sum", alacak, "net", borc+alacak)
