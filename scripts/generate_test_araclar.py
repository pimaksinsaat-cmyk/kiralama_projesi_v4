import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import create_app
from app.extensions import db
from app.araclar.models import Arac
from app.subeler.models import Sube
from datetime import date
import random

app = create_app()

ARAC_TIPLERI = ["Çekici", "Kamyon", "Kasa", "Panelvan", "Minibüs", "Tır", "Pickup"]
MARKA_MODELLER = ["Ford Transit", "Mercedes Sprinter", "Renault Master", "Isuzu NPR", "MAN TGS", "BMC Procity", "Fiat Ducato"]

with app.app_context():
    subeler = Sube.query.filter_by(is_active=True).all()
    if not subeler:
        print("Hiç aktif şube yok!")
        exit(1)
    sube_ids = [s.id for s in subeler]
    for i in range(1, 41):
        plaka = f"TEST{80+i:02d}ARAÇ"
        try:
            if Arac.query.filter_by(plaka=plaka).first():
                print(f"Zaten var: {plaka}")
                continue
            arac = Arac(
                plaka=plaka,
                arac_tipi=random.choice(ARAC_TIPLERI),
                marka_model=random.choice(MARKA_MODELLER),
                sube_id=random.choice(sube_ids),
                muayene_tarihi=date(2026, 12, 31),
                sigorta_tarihi=date(2026, 12, 31),
                is_active=True
            )
            db.session.add(arac)
            db.session.commit()
            print(f"Eklendi: {plaka}")
        except Exception as e:
            db.session.rollback()
            print(f"HATA ({plaka}): {e}")
