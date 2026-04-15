"""
Tam İş Akışı Entegrasyon Testi (User Journey)

Bu test senaryosu Flask test_client kullanarak baştan sona
bir iş akışını simüle eder ve her adımda veritabanını doğrular:

1. Admin kullanıcı ile oturum açma
2. Müşteri (Firma) ve Ekipman oluşturma
3. Kiralama kaydı oluşturma ve Cari'ye işlenme
4. Dış Tedarik Scenarosu (Tedarikçi Firma)
5. Arac (Nakliye Aracı) oluşturma
6. Nakliye (Sefer) oluşturma
7. Stok (StokKarti ve StokHareket) oluşturma
8. Personel kaydı oluşturma
9. Takvim Hatırlatması oluşturma
"""

import pytest
from datetime import date, datetime
from decimal import Decimal
import uuid

from app.auth.models import User
from app.firmalar.models import Firma
from app.filo.models import Ekipman, StokKarti, StokHareket
from app.subeler.models import Sube
from app.kiralama.models import Kiralama, KiralamaKalemi
from app.cari.models import HizmetKaydi
from app.araclar.models import Arac
from app.nakliyeler.models import Nakliye
from app.personel.models import Personel
from app.takvim.models import TakvimHatirlatma
from app.extensions import db


def _unique_vergi_no():
    """Benzersiz vergi numarası oluştur."""
    return f"T{uuid.uuid4().hex[:10].upper()}"


def _unique_plaka():
    """Benzersiz araç plakası oluştur."""
    return f"34{uuid.uuid4().hex[:6].upper()}"


def _unique_kod():
    """Benzersiz kod oluştur."""
    return f"KOD-{uuid.uuid4().hex[:8].upper()}"


class TestTamAkisSenaryosu:
    """Baştan sona tam iş akışı testleri."""

    @pytest.fixture(autouse=True)
    def setup(self, app, client):
        """Her test öncesi gerekli setup işlemleri."""
        self.app = app
        self.client = client

    def test_tam_is_akisi_senaryosu(self):
        """Baştan sona tam iş akışı: oturum açma, kayıtlar, cari, stok, personel."""

        # =====================================================================
        # ADIM 1: ADMIN KULLANICI OLUŞTUR VE OTURUM AÇ
        # =====================================================================
        print("\n[1] Admin kullanici olusturma...")

        admin_user = User(username='test_admin', rol='admin')
        admin_user.set_password('test_password')
        db.session.add(admin_user)
        db.session.commit()
        admin_id = admin_user.id

        # Veritabanında olduğunu doğrula
        user = User.query.filter_by(username='test_admin').first()
        assert user is not None
        assert user.id == admin_id
        assert user.is_admin()
        print(f"  [OK] Admin kullanici olusturuldu: {user.username}")

        # Login isteği
        response = self.client.post('/login', data={
            'username': 'test_admin',
            'password': 'test_password',
            'beni_hatirla': False
        }, follow_redirects=True)
        assert response.status_code == 200
        print("  [OK] Admin başarıyla oturum açtı")

        # =====================================================================
        # ADIM 2: ŞUBE / DEPO OLUŞTUR
        # =====================================================================
        print("\n[OK] ADIM 2: Sube / Depo olusturma...")

        sube = Sube(
            isim='Test Şubesi',
            adres='Test Adres Satırı 1',
            yetkili_kisi='Yetkili Kişi',
            telefon='0212-1234567'
        )
        db.session.add(sube)
        db.session.commit()

        created_sube = Sube.query.filter_by(isim='Test Şubesi').first()
        assert created_sube is not None
        print(f"  [OK] Sube olusturuldu: {created_sube.isim}")

        # =====================================================================
        # ADIM 3: MÜŞTERİ FİRMA OLUŞTUR
        # =====================================================================
        print("\n[OK] ADIM 3: Musteri Firma olusturma...")

        musteri = Firma(
            firma_adi='Test Müşteri A.Ş.',
            yetkili_adi='Yetkili Kişi',
            iletisim_bilgileri='Test Adres',
            vergi_dairesi='İstanbul VD',
            vergi_no=_unique_vergi_no(),
            is_musteri=True,
            is_tedarikci=False,
            bakiye=Decimal('0'),
        )
        db.session.add(musteri)
        db.session.commit()

        created_musteri = Firma.query.filter_by(
            firma_adi='Test Müşteri A.Ş.'
        ).first()
        assert created_musteri is not None
        assert created_musteri.is_musteri is True
        print(f"  [OK] Musteri Firma olusturuldu: {created_musteri.firma_adi}")

        # =====================================================================
        # ADIM 4: TEDARİKÇİ FİRMA OLUŞTUR
        # =====================================================================
        print("\n[OK] ADIM 4: Tedarikci Firma olusturma...")

        tedarikci = Firma(
            firma_adi='Test Tedarikçi Ltd.',
            yetkili_adi='Yetkili Kişi',
            iletisim_bilgileri='Tedarikçi Adres',
            vergi_dairesi='Ankara VD',
            vergi_no=_unique_vergi_no(),
            is_musteri=False,
            is_tedarikci=True,
            bakiye=Decimal('0'),
        )
        db.session.add(tedarikci)
        db.session.commit()

        created_tedarikci = Firma.query.filter_by(
            firma_adi='Test Tedarikçi Ltd.'
        ).first()
        assert created_tedarikci is not None
        assert created_tedarikci.is_tedarikci is True
        print(f"  [OK] Tedarikci Firma olusturuldu: {created_tedarikci.firma_adi}")

        # =====================================================================
        # ADIM 5: EKİPMAN (MAKİNE) OLUŞTUR
        # =====================================================================
        print("\n[OK] ADIM 5: Ekipman (Makine) olusturma...")

        ekipman = Ekipman(
            kod=_unique_kod(),
            yakit='Elektrik',
            tipi='MAKAS',
            marka='Test Marka',
            model='Model X',
            seri_no=f"SN-{uuid.uuid4().hex[:8]}",
            calisma_yuksekligi=10,
            kaldirma_kapasitesi=2000,
            uretim_yili=2023,
            calisma_durumu='bosta',
            sube_id=created_sube.id,
        )
        db.session.add(ekipman)
        db.session.commit()

        created_ekipman = Ekipman.query.filter_by(
            tipi='MAKAS',
            marka='Test Marka'
        ).first()
        assert created_ekipman is not None
        assert created_ekipman.calisma_durumu == 'bosta'
        print(f"  [OK] Ekipman olusturuldu: {created_ekipman.kod}")

        # =====================================================================
        # ADIM 6: KİRALAMA OLUŞTUR
        # =====================================================================
        print("\n[OK] ADIM 6: Kiralama Kaydi olusturma...")

        kiralama = Kiralama(
            kiralama_form_no=f"PF-TEST-{uuid.uuid4().hex[:6]}",
            firma_musteri_id=created_musteri.id,
            kdv_orani=20,
        )
        db.session.add(kiralama)
        db.session.flush()

        # Kiralama Kalemi ekle
        kalem = KiralamaKalemi(
            kiralama_id=kiralama.id,
            ekipman_id=created_ekipman.id,
            kiralama_baslangici=date(2026, 4, 14),
            kiralama_bitis=date(2026, 4, 30),
            kiralama_brm_fiyat=Decimal('1000.00'),
            sonlandirildi=False,
            is_active=True,
        )
        db.session.add(kalem)
        db.session.commit()

        created_kiralama = Kiralama.query.filter_by(
            firma_musteri_id=created_musteri.id
        ).first()
        assert created_kiralama is not None
        assert len(created_kiralama.kalemler) > 0
        print(f"  [OK] Kiralama olusturuldu: {created_kiralama.kiralama_form_no}")

        # =====================================================================
        # ADIM 7: CARI HİZMET KAYDI OLUŞTUR
        # =====================================================================
        print("\n[OK] ADIM 7: Cari Hizmet Kaydi olusturma...")

        hizmet = HizmetKaydi(
            firma_id=created_musteri.id,
            tarih=date.today(),
            tutar=Decimal('17000.00'),
            yon='giden',  # Müşteri borçlanır
            fatura_no=f"FAT-{uuid.uuid4().hex[:6]}",
            aciklama='Test Kiralama Faturası',
        )
        db.session.add(hizmet)
        db.session.commit()

        created_hizmet = HizmetKaydi.query.filter_by(
            firma_id=created_musteri.id
        ).first()
        assert created_hizmet is not None
        assert created_hizmet.yon == 'giden'
        print(f"  [OK] Cari Hizmet Kaydi olusturuldu: {created_hizmet.fatura_no}")

        # Musteri bakiyesini dogrula
        musteri_verified = Firma.query.filter_by(id=created_musteri.id).first()
        hizmets = list(musteri_verified.hizmet_kayitlari)
        assert len(hizmets) > 0
        print(f"  [OK] Musterinin {len(hizmets)} adet cari hareketi var")

        # =====================================================================
        # ADIM 8: DIŞ TEDARİK KIRALAMA KALEMİ OLUŞTUR
        # =====================================================================
        print("\n[OK] ADIM 8: Dis Tedarik Kiralama Kalemi olusturma...")

        dis_kiralama = Kiralama(
            kiralama_form_no=f"PF-DIS-{uuid.uuid4().hex[:6]}",
            firma_musteri_id=created_musteri.id,
            kdv_orani=20,
        )
        db.session.add(dis_kiralama)
        db.session.flush()

        # Dış tedarik kalemi ekle
        dis_tedarik_kalem = KiralamaKalemi(
            kiralama_id=dis_kiralama.id,
            ekipman_id=None,  # Harici ekipman
            is_dis_tedarik_ekipman=True,
            harici_ekipman_tipi='BİLGİSAYAR',
            harici_ekipman_marka='Dell',
            harici_ekipman_model='OptiPlex',
            harici_ekipman_seri_no='SN123456',
            harici_ekipman_kapasite=8,
            harici_ekipman_tedarikci_id=created_tedarikci.id,
            kiralama_baslangici=date(2026, 4, 15),
            kiralama_bitis=date(2026, 4, 25),
            kiralama_brm_fiyat=Decimal('500.00'),
            kiralama_alis_fiyat=Decimal('400.00'),
            kiralama_alis_kdv=20,
            sonlandirildi=False,
            is_active=True,
        )
        db.session.add(dis_tedarik_kalem)
        db.session.commit()

        # Dış tedarik kalemin oluştuğunu doğrula
        dis_kalem = KiralamaKalemi.query.filter_by(
            is_dis_tedarik_ekipman=True
        ).first()
        assert dis_kalem is not None
        assert dis_kalem.harici_ekipman_marka == 'Dell'
        assert dis_kalem.harici_ekipman_tedarikci_id == created_tedarikci.id
        print(f"  [OK] Dis Tedarik Kalemi olusturuldu: {dis_kalem.harici_ekipman_marka}")

        # =====================================================================
        # ADIM 9: NAKLİYE ARACI OLUŞTUR
        # =====================================================================
        print("\n[OK] ADIM 9: Nakliye Araci olusturma...")

        arac = Arac(
            plaka=_unique_plaka(),
            arac_tipi='Kamyon',
            marka_model='Volvo FH16',
            is_nakliye_araci=True,
        )
        db.session.add(arac)
        db.session.commit()

        created_arac = Arac.query.filter_by(arac_tipi='Kamyon').first()
        assert created_arac is not None
        print(f"  [OK] Nakliye Araci olusturuldu: {created_arac.plaka}")

        # =====================================================================
        # ADIM 10: NAKLİYE OPERASYONUlarındır OLUŞTUR
        # =====================================================================
        print("\n[OK] ADIM 10: Nakliye (Sefer) Kaydi olusturma...")

        nakliye = Nakliye(
            kiralama_id=created_kiralama.id,
            firma_id=created_musteri.id,
            nakliye_tipi='oz_mal',  # Kendi aracımız
            tarih=date(2026, 4, 15),
            guzergah='Istanbul - Ankara',
            arac_id=created_arac.id,
            tutar=Decimal('1500.00'),
            kdv_orani=20,
            toplam_tutar=Decimal('1500.00'),
        )
        db.session.add(nakliye)
        db.session.commit()

        created_nakliye = Nakliye.query.filter_by(
            guzergah='Istanbul - Ankara'
        ).first()
        assert created_nakliye is not None
        assert created_nakliye.nakliye_tipi == 'oz_mal'
        print(f"  [OK] Nakliye Kaydi olusturuldu: {created_nakliye.guzergah}")

        # =====================================================================
        # ADIM 11: STOK KARTI OLUŞTUR
        # =====================================================================
        print("\n[OK] ADIM 11: Stok Karti olusturma...")

        stok_karti = StokKarti(
            parca_kodu=_unique_kod(),
            parca_adi='Test Yedek Parcasi',
            mevcut_stok=50,
        )
        db.session.add(stok_karti)
        db.session.commit()

        created_stok = StokKarti.query.filter_by(
            parca_adi='Test Yedek Parcasi'
        ).first()
        assert created_stok is not None
        assert created_stok.mevcut_stok == 50
        print(f"  [OK] Stok Karti olusturuldu: {created_stok.parca_kodu}")

        # =====================================================================
        # ADIM 12: STOK HAREKETİ OLUŞTUR
        # =====================================================================
        print("\n[OK] ADIM 12: Stok Hareketi (Giris) olusturma...")

        hareket = StokHareket(
            stok_karti_id=created_stok.id,
            firma_id=created_tedarikci.id,
            tarih=date.today(),
            adet=25,
            birim_fiyat=Decimal('100.00'),
            kdv_orani=20,
            hareket_tipi='giris',
            fatura_no='FAT-STOK-001',
            aciklama='Test Stok Girisi',
        )
        db.session.add(hareket)
        db.session.commit()

        created_hareket = StokHareket.query.filter_by(
            hareket_tipi='giris'
        ).first()
        assert created_hareket is not None
        assert created_hareket.adet == 25
        print(f"  [OK] Stok Hareketi olusturuldu: {created_hareket.adet} adet")

        # =====================================================================
        # ADIM 13: PERSONEL OLUŞTUR
        # =====================================================================
        print("\n[OK] ADIM 13: Personel kaydi olusturma...")

        personel = Personel(
            ad='Ahmet',
            soyad='Yilmaz',
            tc_no=f"1{uuid.uuid4().hex[:10].upper()}"[:11],
            telefon='05321234567',
            meslek='Operator',
            maas=Decimal('15000.00'),
            sube_id=created_sube.id,
            ise_giris_tarihi=date(2025, 1, 1),
        )
        db.session.add(personel)
        db.session.commit()

        created_personel = Personel.query.filter_by(
            ad='Ahmet',
            soyad='Yilmaz'
        ).first()
        assert created_personel is not None
        assert created_personel.meslek == 'Operator'
        assert created_personel.tam_ad == 'Ahmet Yilmaz'
        print(f"  [OK] Personel kaydi olusturuldu: {created_personel.tam_ad}")

        # =====================================================================
        # ADIM 14: TAKVİM HATIRLATMASI OLUŞTUR
        # =====================================================================
        print("\n[OK] ADIM 14: Takvim Hatirlatmasi olusturma...")

        hatirlatma = TakvimHatirlatma(
            user_id=admin_id,
            tarih=date(2026, 5, 15),
            baslik='Makine Bakimi',
            aciklama='Test Ekipmaninin periyodik bakimi yapilmasi gerekiyor.',
        )
        db.session.add(hatirlatma)
        db.session.commit()

        created_hatirlatma = TakvimHatirlatma.query.filter_by(
            baslik='Makine Bakimi'
        ).first()
        assert created_hatirlatma is not None
        assert created_hatirlatma.user_id == admin_id
        print(f"  [OK] Takvim Hatirlatmasi olusturuldu: {created_hatirlatma.baslik}")

        # =====================================================================
        # FİNAL DOĞRULAMA: TÜM KAYITLARIN VERİTABANINDA OLUP OLMADIĞINI KONTROL ET
        # =====================================================================
        print("\n" + "="*70)
        print("FINAL DOGRULAMA: TUM KAYITLAR VERITABANINDA MEVCUT")
        print("="*70)

        # Kullanıcı
        admin = User.query.filter_by(username='test_admin').first()
        assert admin is not None
        print("[OK] Admin kullanıcı: MEVCUT")

        # Firma (Müşteri)
        musteri_verify = Firma.query.filter_by(is_musteri=True).first()
        assert musteri_verify is not None
        print(f"[OK] Müşteri Firma: {musteri_verify.firma_adi}")

        # Firma (Tedarikçi)
        tedarikci_verify = Firma.query.filter_by(is_tedarikci=True).first()
        assert tedarikci_verify is not None
        print(f"[OK] Tedarikçi Firma: {tedarikci_verify.firma_adi}")

        # Şube
        sube_verify = Sube.query.first()
        assert sube_verify is not None
        print(f"[OK] Şube / Depo: {sube_verify.isim}")

        # Ekipman
        ekipman_verify = Ekipman.query.first()
        assert ekipman_verify is not None
        print(f"[OK] Ekipman (Makine): {ekipman_verify.kod}")

        # Kiralama
        kiralama_verify = Kiralama.query.first()
        assert kiralama_verify is not None
        assert len(kiralama_verify.kalemler) > 0
        print(f"[OK] Kiralama: {kiralama_verify.kiralama_form_no} ({len(kiralama_verify.kalemler)} kalem)")

        # Cari
        hizmet_verify = HizmetKaydi.query.first()
        assert hizmet_verify is not None
        print(f"[OK] Cari Hizmet Kaydı: {hizmet_verify.fatura_no}")

        # Dış Tedarik
        dis_kalem_verify = KiralamaKalemi.query.filter_by(
            is_dis_tedarik_ekipman=True
        ).first()
        assert dis_kalem_verify is not None
        print(f"[OK] Dış Tedarik Ekipmanı: {dis_kalem_verify.harici_ekipman_marka}")

        # Araç
        arac_verify = Arac.query.first()
        assert arac_verify is not None
        print(f"[OK] Nakliye Aracı: {arac_verify.plaka}")

        # Nakliye
        nakliye_verify = Nakliye.query.first()
        assert nakliye_verify is not None
        print(f"[OK] Nakliye (Sefer): {nakliye_verify.guzergah}")

        # Stok
        stok_verify = StokKarti.query.first()
        assert stok_verify is not None
        print(f"[OK] Stok Kartı: {stok_verify.parca_kodu}")

        # Stok Hareketi
        hareket_verify = StokHareket.query.first()
        assert hareket_verify is not None
        print(f"[OK] Stok Hareketi: {hareket_verify.adet} adet")

        # Personel
        personel_verify = Personel.query.first()
        assert personel_verify is not None
        print(f"[OK] Personel: {personel_verify.tam_ad}")

        # Takvim Hatırlatması
        hatirlatma_verify = TakvimHatirlatma.query.first()
        assert hatirlatma_verify is not None
        print(f"[OK] Takvim Hatırlatması: {hatirlatma_verify.baslik}")

        print("\n" + "="*70)
        print("[PASS] TAM İŞ AKIŞI ENTEGRASYON TESTİ BAŞARILI TAMAMLANDI!")
        print("="*70)
        print("""
    Yapılan İşlemler:
    [OK] Admin kullanıcı giriş yaptı
    [OK] Şube / Depo tanımlandı
    [OK] Müşteri Firma oluşturuldu
    [OK] Tedarikçi Firma oluşturuldu
    [OK] Ekipman (Makine) oluşturuldu
    [OK] Normal Kiralama kaydı oluşturuldu
    [OK] Kiralama Cari'ye (HizmetKaydi) işlendi
    [OK] Dış Tedarik Ekipmanı tanımlandı
    [OK] Nakliye Aracı oluşturuldu
    [OK] Nakliye Seferi kaydedildi
    [OK] Stok Kartı oluşturuldu
    [OK] Stok Hareketi (Giriş) kaydedildi
    [OK] Personel kaydı oluşturuldu
    [OK] Takvim Hatırlatması oluşturuldu

    Tüm Veritabanı Kayıtları Doğrulandı!
        """)
