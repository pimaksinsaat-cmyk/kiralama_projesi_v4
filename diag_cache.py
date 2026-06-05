import sys
sys.path.insert(0, "/app")
import os
os.chdir("/app")
from datetime import date
from app import create_app
from app.firmalar.models import Firma
from app.services.firma_services import FirmaService
from sqlalchemy.orm import joinedload
from app.kiralama.models import Kiralama

app = create_app()
with app.app_context():
    f = Firma.query.get(60)
    FirmaService.guncelle_firma_cari_cache(60)
    from app.extensions import db
    db.session.refresh(f)
    print("after cache refresh cari_bakiye_kdvli", float(f.cari_bakiye_kdvli))
    print("bakiye_ozeti net", f.bakiye_ozeti.get("net_bakiye_kdvli"))
    firma = Firma.query.options(
        joinedload(Firma.kiralamalar).joinedload(Kiralama.kalemler),
        joinedload(Firma.kiralamalar).joinedload(Kiralama.nakliyeler),
    ).get(60)
    rows = FirmaService.build_cari_rows(firma, date.today())
    print("last bakiye", rows[-1]["bakiye"])
    # simulate brut nakliye in build: what if tevkifat ignored
    brut_nak = 6 * 3000
    net_nak = 6 * 2900
    print("6 nakliye brut total", brut_nak, "net", net_nak, "diff", brut_nak-net_nak)
