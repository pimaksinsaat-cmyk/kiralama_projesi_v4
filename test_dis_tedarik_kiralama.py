@pytest.fixture(autouse=True)
def cleanup_test_firmalari():
    yield
    # Testte kullanılan firma adları
    from app.firmalar.models import Firma
    from app.kiralama.models import Kiralama, KiralamaKalemi
    from app.cari.models import HizmetKaydi
    from app.nakliyeler.models import Nakliye
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

import pytest
from app import create_app
from app.extensions import db
from app.firmalar.models import Firma
from app.cari.models import HizmetKaydi
from datetime import date, timedelta
from app.services.kiralama_services import KiralamaService

@pytest.fixture(scope="module")
def test_client():
    flask_app = create_app()
    testing_client = flask_app.test_client()
    ctx = flask_app.app_context()
    ctx.push()
    db.create_all()
    yield testing_client
    db.session.remove()
    db.drop_all()
    ctx.pop()


def test_dis_tedarik_kiralama_ve_nakliye(test_client):
    # 1. Test firması ve dış tedarikçi oluştur
    musteri = Firma(firma_adi="TEST FIRMASI", yetkili_adi="Yetkili", telefon="5551112233", eposta="test@firma.com", iletisim_bilgileri="Adres", vergi_dairesi="Test VD", vergi_no="9999999999", is_musteri=True, is_tedarikci=False)
    tedarikci = Firma(firma_adi="DIS TEDARIKCI", yetkili_adi="Tedarikci", telefon="5552223344", eposta="tedarikci@firma.com", iletisim_bilgileri="Tedarikci Adres", vergi_dairesi="Tedarikci VD", vergi_no="8888888888", is_musteri=False, is_tedarikci=True)
    nakliye_firmasi = Firma(firma_adi="NAKLIYE FIRMASI", yetkili_adi="Nakliye", telefon="5553334455", eposta="nakliye@firma.com", iletisim_bilgileri="Nakliye Adres", vergi_dairesi="Nakliye VD", vergi_no="7777777777", is_musteri=False, is_tedarikci=True)
    db.session.add_all([musteri, tedarikci, nakliye_firmasi])
    db.session.commit()

    # 2. Kiralama ve kalem verilerini dict olarak hazırla
    kiralama_data = {
        "kiralama_form_no": "KIR-001",
        "makine_calisma_adresi": "Test Adres",
        "kiralama_olusturma_tarihi": date.today(),
        "firma_musteri_id": musteri.id,
        "kdv_orani": 20
    }
    kalemler_data = [
        {
            "dis_tedarik_ekipman": 1,
            "harici_ekipman_tipi": "Ekskavatör",
            "harici_ekipman_marka": "CAT",
            "harici_ekipman_model": "320D",
            "harici_ekipman_seri_no": "SER123",
            "harici_ekipman_kaldirma_kapasitesi": 20,
            "harici_ekipman_calisma_yuksekligi": 5,
            "harici_ekipman_uretim_tarihi": 2020,
            "harici_ekipman_tedarikci_id": tedarikci.id,
            "kiralama_baslangici": date.today(),
            "kiralama_bitis": date.today() + timedelta(days=7),
            "kiralama_brm_fiyat": 1000,
            "kiralama_alis_fiyat": 800,
            "kiralama_alis_kdv": 18,
            "dis_tedarik_nakliye": 1,
            "is_oz_mal_nakliye": 0,
            "is_harici_nakliye": 1,
            "nakliye_satis_fiyat": 500,
            "nakliye_alis_fiyat": 400,
            "nakliye_alis_kdv": 20,
            "nakliye_satis_kdv": 20,
            "nakliye_tedarikci_id": nakliye_firmasi.id,
            "donus_nakliye_fatura_et": 0
        }
    ]

    # 3. Kiralama ve kalemi servis ile oluştur
    KiralamaService.create_kiralama_with_relations(kiralama_data, kalemler_data)

    # 4. HizmetKaydi ve cariler otomatik oluşmalı, kontrol et
    musteri_hizmet = HizmetKaydi.query.filter_by(firma_id=musteri.id).first()
    assert musteri_hizmet is not None
    assert musteri_hizmet.kdv_orani == 20 or musteri_hizmet.kdv_orani is not None
    assert musteri_hizmet.tutar == 1000
    tedarikci_hizmet = HizmetKaydi.query.filter_by(firma_id=tedarikci.id).first()
    assert tedarikci_hizmet is not None
    assert tedarikci_hizmet.kiralama_alis_kdv == 18 or tedarikci_hizmet.kdv_orani == 18
    assert tedarikci_hizmet.tutar == 800
    nakliye_hizmet = HizmetKaydi.query.filter_by(firma_id=nakliye_firmasi.id).first()
    assert nakliye_hizmet is not None
    assert nakliye_hizmet.nakliye_alis_kdv == 20 or nakliye_hizmet.kdv_orani == 20
    assert nakliye_hizmet.tutar == 400
    assert musteri_hizmet.kdv_orani == 20
    assert tedarikci_hizmet.kiralama_alis_kdv == 18 or tedarikci_hizmet.kdv_orani == 18
    assert nakliye_hizmet.nakliye_alis_kdv == 20 or nakliye_hizmet.kdv_orani == 20
    assert musteri_hizmet is not None
    assert tedarikci_hizmet is not None
    assert nakliye_hizmet is not None
