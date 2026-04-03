from app import create_app
from app.extensions import db
from app.firmalar.models import Firma
from app.kiralama.models import Kiralama, KiralamaKalemi
from app.cari.models import HizmetKaydi
from app.nakliyeler.models import Nakliye

def sil_test_kayitlari():
    app = create_app()
    with app.app_context():
        test_firma_adlari = ["TEST FIRMASI", "DIS TEDARIKCI", "NAKLIYE FIRMASI"]
        for ad in test_firma_adlari:
            firma = Firma.query.filter_by(firma_adi=ad).first()
            if firma:
                # İlişkili kiralama ve kalemleri sil
                for kiralama in getattr(firma, 'kiralamalar', []):
                    for kalem in getattr(kiralama, 'kalemler', []):
                        HizmetKaydi.query.filter_by(ozel_id=kalem.id).delete()
                        KiralamaKalemi.query.filter_by(id=kalem.id).delete()
                    Nakliye.query.filter_by(kiralama_id=kiralama.id).delete()
                    Kiralama.query.filter_by(id=kiralama.id).delete()
                # Firma carilerini sil
                HizmetKaydi.query.filter_by(firma_id=firma.id).delete()
                # Firma kaydını sil
                Firma.query.filter_by(id=firma.id).delete()
        db.session.commit()
        print("Test kayıtları silindi.")

if __name__ == "__main__":
    sil_test_kayitlari()
