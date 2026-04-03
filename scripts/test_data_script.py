# coding: utf-8
"""
Test verisi ekleme, silme ve toplu güncelleme scripti.
Kullanım:
  python test_data_script.py ekle  # Test verilerini ekler
  python test_data_script.py sil   # Sadece test verilerini siler
  python test_data_script.py guncelle # Tüm TEST FIRMASI kiralamalarına 100 TL ücret yazar
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import create_app
from app.extensions import db
from app.firmalar.models import Firma
from app.kiralama.models import Kiralama, KiralamaKalemi
from app.nakliyeler.models import Nakliye
from app.filo.models import Ekipman
from app.cari.models import Odeme, HizmetKaydi
from datetime import date, timedelta

app = create_app()

TEST_FIRMA_ADI = "TEST FIRMASI"


def ekle():
    with app.app_context():
        # 1 adet test firması ekle
        firma = Firma.query.filter_by(firma_adi=TEST_FIRMA_ADI).first()
        if not firma:
            firma = Firma(
                firma_adi=TEST_FIRMA_ADI,
                yetkili_adi="Test Yetkili",
                telefon="5551112233",
                eposta="test@firma.com",
                iletisim_bilgileri="Test adres",
                vergi_dairesi="Test VD",
                vergi_no="9999999999",
                is_musteri=True,
                is_tedarikci=True,
                sozlesme_no="TEST-2026-001",
                sozlesme_tarihi=date.today(),
            )
            db.session.add(firma)
            db.session.commit()
            print(f"Eklendi: {firma.firma_adi}")
        else:
            print(f"Zaten var: {firma.firma_adi}")
        # 35 kiralama ekle
        for i in range(1, 36):
            kiralama = Kiralama(
                kiralama_form_no=f"TEST-KIR-{i:03d}",
                makine_calisma_adresi=f"Test adres {i}",
                kiralama_olusturma_tarihi=date.today(),
                firma_musteri_id=firma.id
            )
            db.session.add(kiralama)
            db.session.commit()
            print(f"Kiralama eklendi: {kiralama.kiralama_form_no}")

            # Her kiralama için 1 KiralamaKalemi ekle
            kalem = KiralamaKalemi(
                kiralama_id=kiralama.id,
                kiralama_baslangici=date.today(),
                kiralama_bitis=date.today() + timedelta(days=7),
                kiralama_brm_fiyat=100
            )
            db.session.add(kalem)
            db.session.commit()
            print(f"  -> KiralamaKalemi eklendi: {kalem.id}")


def sil():
    with app.app_context():
        # Hem 'TEST FIRMASI' hem de 'TEST_FIRMA_' ile başlayan firmaları bul
        test_firmalar = Firma.query.filter(
            (Firma.firma_adi.ilike(f"{TEST_FIRMA_ADI}%")) |
            (Firma.firma_adi.ilike("TEST_FIRMA_%"))
        ).all()
        if not test_firmalar:
            print("Silinecek test firması bulunamadı.")
            return
        print("Aşağıdaki test firmaları ve ilişkili tüm veriler silinecek:")
        for f in test_firmalar:
            print(f"- {f.firma_adi} (id={f.id})")
        onay = input("Devam etmek için 'EVET' yazın: ")
        if onay.strip().upper() != "EVET":
            print("İşlem iptal edildi.")
            return
        for firma in test_firmalar:
            try:
                for kiralama in Kiralama.query.filter_by(firma_musteri_id=firma.id).all():
                    KiralamaKalemi.query.filter_by(kiralama_id=kiralama.id).delete()
                    db.session.delete(kiralama)
                Nakliye.query.filter_by(firma_id=firma.id).delete()
                Ekipman.query.filter_by(firma_tedarikci_id=firma.id).delete()
                Odeme.query.filter_by(firma_musteri_id=firma.id).delete()
                HizmetKaydi.query.filter_by(firma_id=firma.id).delete()
                db.session.delete(firma)
                db.session.commit()
                print(f"Silindi: {firma.firma_adi}")
            except Exception as e:
                db.session.rollback()
                print(f"Hata: {firma.firma_adi} silinemedi: {e}")

def guncelle():
    with app.app_context():
        firma = Firma.query.filter_by(firma_adi=TEST_FIRMA_ADI).first()
        if not firma:
            print("Test firması bulunamadı.")
            return
        kiralamalar = Kiralama.query.filter_by(firma_musteri_id=firma.id).all()
        if not kiralamalar:
            print("Test firmasına ait kiralama yok.")
            return
        toplam = 0
        for kiralama in kiralamalar:
            for kalem in kiralama.kalemler:
                kalem.kiralama_brm_fiyat = 100
                toplam += 1
        db.session.commit()
        print(f"{toplam} kiralama kalemine 100 TL fiyat yazıldı.")


def toplu_firma_kiralama_nakliye():
    """
    35 farklı firma ekler, her birine 100 TL'lik kiralama kalemi ve 50 TL'lik nakliye ekler.
    """
    with app.app_context():
        # Öz mal bir ekipman bul veya oluştur
        from app.filo.models import Ekipman
        ekipman = Ekipman.query.filter_by(firma_tedarikci_id=None).first()
        if not ekipman:
            ekipman = Ekipman(
                kod="OZMAL-TEST-001",
                yakit="Dizel",
                tipi="Manlift",
                marka="TestMarka",
                model="T100",
                seri_no="OZMAL-TEST-001",
                calisma_yuksekligi=10,
                kaldirma_kapasitesi=200,
                agirlik=1000,
                ic_mekan_uygun=True,
                arazi_tipi_uygun=True,
                genislik=2.0,
                uzunluk=5.0,
                kapali_yukseklik=2.5,
                uretim_yili=2020,
                calisma_durumu="bosta",
                giris_maliyeti=100000,
                para_birimi="TRY",
                is_active=True
            )
            db.session.add(ekipman)
            db.session.commit()
            print(f"Oluşturuldu: Öz mal ekipman {ekipman.id}")

        for i in range(1, 36):
            firma_adi = f"TEST_FIRMA_{i:02d}"
            firma = Firma.query.filter_by(firma_adi=firma_adi).first()
            if not firma:
                firma = Firma(
                    firma_adi=firma_adi,
                    yetkili_adi=f"Yetkili {i}",
                    telefon=f"555000{i:03d}",
                    eposta=f"test{i}@firma.com",
                    iletisim_bilgileri=f"Test adres {i}",
                    vergi_dairesi="Test VD",
                    vergi_no=f"99999{i:04d}",
                    is_musteri=True,
                    is_tedarikci=True,
                    sozlesme_no=f"TEST-2026-{i:03d}",
                    sozlesme_tarihi=date.today(),
                )
                db.session.add(firma)
                db.session.commit()
                print(f"Eklendi: {firma.firma_adi}")
            else:
                print(f"Zaten var: {firma.firma_adi}")

            kiralama = Kiralama(
                kiralama_form_no=f"TEST-KIR-{i:03d}",
                makine_calisma_adresi=f"Test adres {i}",
                kiralama_olusturma_tarihi=date.today(),
                firma_musteri_id=firma.id
            )
            db.session.add(kiralama)
            db.session.commit()
            print(f"Kiralama eklendi: {kiralama.kiralama_form_no}")

            kalem = KiralamaKalemi(
                kiralama_id=kiralama.id,
                ekipman_id=ekipman.id,
                kiralama_baslangici=date.today(),
                kiralama_bitis=date.today() + timedelta(days=7),
                kiralama_brm_fiyat=100,
                is_oz_mal_nakliye=True,
                nakliye_satis_fiyat=50
            )
            db.session.add(kalem)
            db.session.commit()
            print(f"  -> KiralamaKalemi eklendi: {kalem.id}")
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Kullanım: python test_data_script.py [ekle|sil|guncelle|toplu_firma]")
        sys.exit(1)
    komut = sys.argv[1]
    if komut == "ekle":
        ekle()
    elif komut == "sil":
        sil()
    elif komut == "guncelle":
        guncelle()
    elif komut == "toplu_firma":
        toplu_firma_kiralama_nakliye()
    else:
        print("Bilinmeyen komut.")
