import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import create_app
from app.extensions import db
from app.araclar.models import Arac

app = create_app()

with app.app_context():
    test_araclar = Arac.query.filter(Arac.plaka.ilike('TEST%')).all()
    if not test_araclar:
        print("Silinecek test aracı bulunamadı.")
    else:
        print(f"Aşağıdaki test araçları silinecek:")
        for arac in test_araclar:
            print(f"- {arac.plaka} (id={arac.id})")
        onay = input("Devam etmek için 'EVET' yazın: ")
        if onay.strip().upper() != "EVET":
            print("İşlem iptal edildi.")
            sys.exit(0)
        for arac in test_araclar:
            try:
                db.session.delete(arac)
                db.session.commit()
                print(f"Silindi: {arac.plaka}")
            except Exception as e:
                db.session.rollback()
                print(f"Hata: {arac.plaka} silinemedi: {e}")
