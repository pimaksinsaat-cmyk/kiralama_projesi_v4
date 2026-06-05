import sys, os
root="/app"
os.chdir(root)
sys.path.insert(0, root)
from app import create_app
from app.nakliyeler.models import Nakliye

app = create_app()
with app.app_context():
    all_n = Nakliye.query.filter_by(firma_id=60).order_by(Nakliye.id).all()
    print("ALL nakliye (incl inactive)", len(all_n))
    for n in all_n:
        print(n.id, "active", n.is_active, "tutar", float(n.tutar or 0), "kdv", n.kdv_orani, "tev", repr(n.tevkifat_orani))
    nulls = [n for n in all_n if not (n.tevkifat_orani or "").strip()]
    print("null tevkifat count", len(nulls))
