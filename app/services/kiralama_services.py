import requests
import xml.etree.ElementTree as ET
from datetime import datetime, date, timedelta
from decimal import Decimal, InvalidOperation
import logging
import re
import urllib3
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from app.extensions import db
# En güncel yapı: app/services/base_service.py
from app.services.base import BaseService, ValidationError

# İlgili Modüllerin İçe Aktarılması
from app.kiralama.models import Kiralama, KiralamaKalemi
from app.filo.models import Ekipman
from app.cari.models import HizmetKaydi
from app.nakliyeler.models import Nakliye
from app.araclar.models import Arac as NakliyeAraci
from app.subeler.models import Sube
from app.ayarlar.models import AppSettings

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logger = logging.getLogger(__name__)

# ==============================================================================
# YARDIMCI FONKSİYONLAR (Veri Güvenliği ve Dönüşümler)
# ==============================================================================

def to_decimal(value, default=Decimal('0.00')):
    """Her türlü veriyi (str, float, int) güvenli bir şekilde Decimal'e çevirir."""
    if value is None or value == '': return default
    if isinstance(value, Decimal): return value
    try:
        # TR formatındaki virgüllü sayıları noktaya çevirerek işle
        clean_val = str(value).replace(',', '.')
        return Decimal(clean_val)
    except (ValueError, InvalidOperation):
        return default

def to_date(value):
    """HTML'den gelen tarih verisini (str veya date) güvenli bir şekilde işler."""
    if not value: return None
    if isinstance(value, date): return value
    if isinstance(value, datetime): return value.date()
    for fmt in ('%Y-%m-%d', '%d.%m.%Y'):
        try:
            return datetime.strptime(str(value), fmt).date()
        except ValueError:
            continue
    return None

def to_int_or_none(value):
    """Boş veya geçersiz değerleri None, sayısalları int'e çevirir."""
    if value is None or value == '':
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None

def guncelle_cari_toplam(kiralama_id, auto_commit=True):
    """Dış modüllerin kiralama cari toplamını tetiklemesi için köprü fonksiyon."""
    return KiralamaService.guncelle_cari_toplam(kiralama_id, auto_commit=auto_commit)


# ==============================================================================
# KİRALAMA KALEMİ SERVİSİ
# ==============================================================================

class KiralamaKalemiService(BaseService):
    """Kiralama satırlarının (kalemlerin) iş mantığını yönetir."""
    model = KiralamaKalemi
    use_soft_delete = False 

    @classmethod
    def sonlandir(
        cls,
        kalem_id,
        bitis_tarihi_str,
        donus_sube_val,
        actor_id=None,
        is_harici_nakliye=False,
        nakliye_tedarikci_id=None,
        nakliye_araci_id=None,
        nakliye_alis_fiyat=None,
        donus_nakliye_satis_fiyat=None,
    ):
        """Kiralama kalemini sonlandırır ve makinenin durumunu günceller."""
        kalem = cls.get_by_id(kalem_id)
        if not kalem:
            raise ValidationError("İlgili kiralama kalemi bulunamadı.")

        planlanan_donus_satis = KiralamaService._get_planlanan_donus_nakliye_satis(kalem)

        bitis_date = to_date(bitis_tarihi_str)
        if bitis_date:
            kalem.kiralama_bitis = bitis_date
        
        kalem.sonlandirildi = True

        # Dönüş satış bedeli modaldan gelirse kaleme kaydet.
        if donus_nakliye_satis_fiyat not in (None, ''):
            kalem.donus_nakliye_satis_fiyat = to_decimal(donus_nakliye_satis_fiyat)
        fiili_donus_satis = KiralamaService._get_donus_nakliye_satis(kalem)

        # Dönüş müşteri tahakkuku: planlanan bedeli yaz, sapma varsa farkı ayrı satır yaz.
        HizmetKaydi.query.filter(
            HizmetKaydi.ozel_id == kalem.id, 
            HizmetKaydi.aciklama.like('Müşteri Dönüş Nakliye Bedeli%') 
        ).delete(synchronize_session=False)
        HizmetKaydi.query.filter(
            HizmetKaydi.ozel_id == kalem.id,
            HizmetKaydi.aciklama.like('Nakliye Farkı%')
        ).delete(synchronize_session=False)

        # Checkbox durumunu kontrol et
        donus_checkbox_aktif = bool(kalem.donus_nakliye_fatura_et)
        
        # Checkbox AKTIF (Gidiş-Geliş): Ekle menüsünde yazıldı, sonlandır'da yazma
        # Sadece fark var ise yazacağız (aşağıya bak)
        
        # Checkbox PASİF (Sadece gidiş): Modal'dan gelen dönüş bedeli varsa doğrudan yaz  
        if not donus_checkbox_aktif and fiili_donus_satis > 0 and kalem.kiralama and kalem.kiralama.firma_musteri_id:
            makine_bilgisi = "Makine"
            if kalem.ekipman and kalem.ekipman.kod:
                makine_bilgisi = kalem.ekipman.kod
            elif any([kalem.harici_ekipman_marka, kalem.harici_ekipman_model]):
                makine_bilgisi = " ".join(filter(None, [kalem.harici_ekipman_marka, kalem.harici_ekipman_model])).strip()

            kdv_kaynak = getattr(kalem.kiralama, 'kdv_orani', None) 
            print(f"[DEBUG] HizmetKaydi oluşturuluyor: kalem.id={kalem.id}, kiralama.id={getattr(kalem.kiralama, 'id', None)}, kaynak_kdv_orani={kdv_kaynak}, kullanılacak_kdv_orani={kdv_kaynak if kdv_kaynak is not None else 20}") 
            hizmet_kaydi = HizmetKaydi( 
                firma_id=kalem.kiralama.firma_musteri_id, 
                tarih=date.today(), 
                tutar=fiili_donus_satis, 
                yon='giden', 
                fatura_no=kalem.kiralama.kiralama_form_no if kalem.kiralama else None, 
                ozel_id=kalem.id, 
                aciklama=f"Dönüş Nakliye ({makine_bilgisi}) - Form: {kalem.kiralama.kiralama_form_no if kalem.kiralama else ''}", 
                kdv_orani=kdv_kaynak if kdv_kaynak is not None else 20,
                nakliye_alis_kdv=kalem.nakliye_alis_kdv
            ) 
            print(f"[DEBUG] HizmetKaydi oluşturuldu: id={getattr(hizmet_kaydi, 'id', None)}, kdv_orani={hizmet_kaydi.kdv_orani}")
            db.session.add(hizmet_kaydi)
            db.session.flush()  # id atanması için
            db.session.refresh(hizmet_kaydi)
            print(f"[DEBUG] DB'ye yazılan HizmetKaydi: id={hizmet_kaydi.id}, kdv_orani={hizmet_kaydi.kdv_orani}")

        # Fark hesapla (sadece checkbox AKTIF olduğunda, mükerrer yazımdan kaçınmak için)
        nakliye_farki = (fiili_donus_satis - planlanan_donus_satis) if donus_checkbox_aktif else Decimal('0')
        if nakliye_farki != 0 and kalem.kiralama and kalem.kiralama.firma_musteri_id:
            makine_bilgisi = "Makine"
            if kalem.ekipman and kalem.ekipman.kod:
                makine_bilgisi = kalem.ekipman.kod
            elif any([kalem.harici_ekipman_marka, kalem.harici_ekipman_model]):
                makine_bilgisi = " ".join(filter(None, [kalem.harici_ekipman_marka, kalem.harici_ekipman_model])).strip()

            pozitif = nakliye_farki > 0 
            kdv_kaynak = getattr(kalem.kiralama, 'kdv_orani', None) 
            print(f"[DEBUG] HizmetKaydi oluşturuluyor (fark): kalem.id={kalem.id}, kiralama.id={getattr(kalem.kiralama, 'id', None)}, kaynak_kdv_orani={kdv_kaynak}, kullanılacak_kdv_orani={kdv_kaynak if kdv_kaynak is not None else 20}") 
            hizmet_kaydi = HizmetKaydi( 
                firma_id=kalem.kiralama.firma_musteri_id, 
                tarih=date.today(), 
                tutar=abs(nakliye_farki), 
                yon='giden' if pozitif else 'gelen', 
                fatura_no=kalem.kiralama.kiralama_form_no if kalem.kiralama else None, 
                ozel_id=kalem.id, 
                aciklama=f"Nakliye Farkı ({makine_bilgisi}) - Form: {kalem.kiralama.kiralama_form_no if kalem.kiralama else ''}", 
                kdv_orani=kdv_kaynak if kdv_kaynak is not None else 20,
                nakliye_alis_kdv=kalem.nakliye_alis_kdv
            ) 
            print(f"[DEBUG] HizmetKaydi oluşturuldu (fark): id={getattr(hizmet_kaydi, 'id', None)}, kdv_orani={hizmet_kaydi.kdv_orani}")
            db.session.add(hizmet_kaydi)

        # Makine Durum Güncellemesi
        if kalem.ekipman:
            if donus_sube_val == 'tedarikci':
                kalem.ekipman.sube_id = None
                kalem.ekipman.calisma_durumu = 'iade_edildi'
            elif donus_sube_val and str(donus_sube_val).isdigit() and int(donus_sube_val) > 0:
                kalem.ekipman.sube_id = int(donus_sube_val)
                kalem.ekipman.calisma_durumu = 'bosta'

        # Dönüş nakliye bilgilerini güncelle
        kalem.is_harici_nakliye = bool(is_harici_nakliye)
        kalem.is_oz_mal_nakliye = not kalem.is_harici_nakliye
        if kalem.is_harici_nakliye:
            kalem.nakliye_tedarikci_id = int(nakliye_tedarikci_id or 0) or None
            kalem.nakliye_araci_id = None
            kalem.nakliye_alis_fiyat = to_decimal(nakliye_alis_fiyat)
        else:
            kalem.nakliye_tedarikci_id = None
            kalem.nakliye_araci_id = int(nakliye_araci_id or 0) or None

        # --- Dönüş için ortak değişkenler ---
        musteri_adi = "Bilinmeyen Müşteri"
        if kalem.kiralama and kalem.kiralama.firma_musteri and kalem.kiralama.firma_musteri.firma_adi:
            musteri_adi = kalem.kiralama.firma_musteri.firma_adi

        if donus_sube_val and str(donus_sube_val).isdigit() and int(donus_sube_val) > 0:
            donus_sube = db.session.get(Sube, int(donus_sube_val))
            donus_sube_adi = donus_sube.isim if donus_sube else "Bilinmeyen Şube"
        elif donus_sube_val == 'tedarikci':
            donus_sube_adi = "Tedarikçiye İade"
        else:
            donus_sube_adi = "Bilinmeyen Şube"

        makine_bilgisi_donus = "Makine"
        if kalem.ekipman and kalem.ekipman.kod:
            makine_bilgisi_donus = kalem.ekipman.kod
        elif any([kalem.harici_ekipman_marka, kalem.harici_ekipman_model, kalem.harici_ekipman_seri_no]):
            marka_model = " ".join(filter(None, [kalem.harici_ekipman_marka, kalem.harici_ekipman_model])).strip()
            makine_bilgisi_donus = marka_model or kalem.harici_ekipman_seri_no

        is_yeri_donus = (kalem.kiralama.makine_calisma_adresi or '').strip() if kalem.kiralama else ''
        is_yeri_donus = is_yeri_donus or musteri_adi
        # ------------------------------------

        # Harici nakliye varsa tedarikçi carisine nakliye bedeli işle
        if kalem.is_harici_nakliye and kalem.nakliye_tedarikci_id and to_decimal(kalem.nakliye_alis_fiyat) > 0:
            # Aynı kalem için önceki sonlandırma taşeron cari kaydını temizle (mükerrer engeli)
            HizmetKaydi.query.filter(
                HizmetKaydi.ozel_id == kalem.id,
                HizmetKaydi.yon == 'gelen',
                HizmetKaydi.aciklama.like('%nakliye bedeli%')
            ).delete(synchronize_session=False)

            aciklama = (
                f"Dönüş Nakliye: {makine_bilgisi_donus} - {donus_sube_adi}"
            )
            hizmet_kaydi = HizmetKaydi(
                firma_id=kalem.nakliye_tedarikci_id,
                tarih=date.today(),
                tutar=to_decimal(kalem.nakliye_alis_fiyat),
                yon='gelen',
                fatura_no=kalem.kiralama.kiralama_form_no if kalem.kiralama else None,
                ozel_id=kalem.id,
                aciklama=aciklama,
                kdv_orani=getattr(kalem.kiralama, 'kdv_orani', None) or 20
            )
            print(f"[DEBUG] HizmetKaydi oluşturuluyor (tedarikçi): kdv_orani={hizmet_kaydi.kdv_orani}")
            db.session.add(hizmet_kaydi)

        # Özmal dönüş: nakliye aracı kaydına dönüş seferi ekle
        elif not kalem.is_harici_nakliye and kalem.nakliye_araci_id and kalem.kiralama:
            form_no = kalem.kiralama.kiralama_form_no or ''
            # Önceki dönüş sefer kaydını temizle (yeniden sonlandırma durumunda mükerrer engeli)
            Nakliye.query.filter(
                Nakliye.kiralama_id == kalem.kiralama_id,
                Nakliye.aciklama == f"Dönüş: {form_no} #{kalem.id}"
            ).delete(synchronize_session=False)

            donus_guzergah = (
                f"{makine_bilgisi_donus} {musteri_adi} firmasının {is_yeri_donus}'nden "
                f"{donus_sube_adi} şubesine getirildi"
            )
            donus_sefer = Nakliye(
                kiralama_id=kalem.kiralama_id,
                firma_id=kalem.kiralama.firma_musteri_id,
                tarih=kalem.kiralama_bitis or date.today(),
                guzergah=donus_guzergah,
                tutar=KiralamaService._get_donus_nakliye_satis(kalem),
                kdv_orani=kalem.nakliye_satis_kdv if kalem.nakliye_satis_kdv is not None else (kalem.kiralama.kdv_orani if kalem.kiralama.kdv_orani is not None else 20),
                tevkifat_orani=kalem.nakliye_satis_tevkifat_oran or None,
                aciklama=f"Dönüş: {form_no} #{kalem.id}",
                nakliye_tipi='oz_mal',
                arac_id=kalem.nakliye_araci_id,
            )
            secilen_arac = db.session.get(NakliyeAraci, kalem.nakliye_araci_id)
            if secilen_arac:
                donus_sefer.plaka = secilen_arac.plaka
            donus_sefer.hesapla_ve_guncelle()
            db.session.add(donus_sefer)

        cls.save(kalem, is_new=False, auto_commit=False, actor_id=actor_id)
        
        # Cari hesaplamayı tetikle
        KiralamaService.guncelle_cari_toplam(kalem.kiralama_id, auto_commit=False)
        db.session.commit()
        return kalem

    @classmethod
    def iptal_et_sonlandirma(cls, kalem_id, actor_id=None):
        """Sonlandırmayı iptal eder ve makineyi tekrar kirada gösterir."""
        kalem = cls.get_by_id(kalem_id)
        if not kalem:
            raise ValidationError("İlgili kiralama kalemi bulunamadı.")

        kalem.sonlandirildi = False
        kalem.donus_nakliye_satis_fiyat = None  # Modalın bir sonraki açılışında form varsayını kullansın
        if kalem.ekipman:
            kalem.ekipman.calisma_durumu = 'kirada'

        # Sonlandırma sırasında açılmış taşeron ve nakliye farkı kayıtlarını geri al
        HizmetKaydi.query.filter(
            HizmetKaydi.ozel_id == kalem.id,
            HizmetKaydi.yon == 'gelen',
            HizmetKaydi.aciklama.like('%nakliye bedeli%')
        ).delete(synchronize_session=False)
        HizmetKaydi.query.filter(
            HizmetKaydi.ozel_id == kalem.id,
            HizmetKaydi.aciklama.like('Müşteri Dönüş Nakliye Bedeli%')
        ).delete(synchronize_session=False)
        HizmetKaydi.query.filter(
            HizmetKaydi.ozel_id == kalem.id,
            HizmetKaydi.aciklama.like('Nakliye Farkı%')
        ).delete(synchronize_session=False)

        # Dönüş özmal sefer kaydını geri al
        if kalem.kiralama:
            form_no_iptal = kalem.kiralama.kiralama_form_no or ''
            Nakliye.query.filter(
                Nakliye.kiralama_id == kalem.kiralama_id,
                Nakliye.aciklama == f"Dönüş: {form_no_iptal} #{kalem.id}"
            ).delete(synchronize_session=False)

        cls.save(kalem, is_new=False, auto_commit=False, actor_id=actor_id)
        
        # Cari hesaplamayı tetikle
        KiralamaService.guncelle_cari_toplam(kalem.kiralama_id, auto_commit=False)
        db.session.commit()
        return kalem


# ==============================================================================
# ANA KİRALAMA SERVİSİ
# ==============================================================================

class KiralamaService(BaseService):
    """Ana kiralama formunun ve finansal entegrasyonların kalbi."""
    model = Kiralama
    use_soft_delete = False

    # KUR ÖNBELLEKLEME İÇİN SINIF DEĞİŞKENLERİ
    _kur_cache = None
    _kur_son_guncelleme = None
    _cache_suresi_dakika = 60 # 1 saatte bir güncelle

    @staticmethod
    def _extract_form_sequence(form_no, prefix, year):
        """Form numarasındaki ana sayısal sırayı çıkarır, revizyon eklerini yok sayar."""
        if not form_no:
            return None

        match = re.match(rf"^{re.escape(prefix)}-{year}/(\d+)", str(form_no).strip())
        if not match:
            return None

        return int(match.group(1))

    @staticmethod
    def get_next_form_no():
        """Sıradaki kiralama form numarasını (PREFIX-YIL/SIRA) otomatik üretir."""
        year = datetime.now().year
        settings = AppSettings.get_current()
        start_no = settings.kiralama_form_start_no if settings else 1
        prefix = settings.kiralama_form_prefix if settings and settings.kiralama_form_prefix else 'PF'

        form_nolari = db.session.query(Kiralama.kiralama_form_no).filter(
            Kiralama.kiralama_form_no.like(f"{prefix}-{year}/%")
        ).all()

        sequence_values = [
            sequence
            for form_no, in form_nolari
            for sequence in [KiralamaService._extract_form_sequence(form_no, prefix, year)]
            if sequence is not None
        ]
        max_seq = max(sequence_values, default=None)

        next_no = (max_seq + 1) if max_seq else start_no
        return f"{prefix}-{year}/{next_no:04d}"

    @classmethod
    def get_tcmb_kurlari(cls):
        """TCMB'den güncel döviz kurlarını çeker (Önbellekleme ile)."""
        simdi = datetime.now()
        
        if cls._kur_cache and cls._kur_son_guncelleme:
            fark = simdi - cls._kur_son_guncelleme
            if fark < timedelta(minutes=cls._cache_suresi_dakika):
                return cls._kur_cache

        rates = {'USD': Decimal('0.00'), 'EUR': Decimal('0.00')}
        try:
            url = "https://www.tcmb.gov.tr/kurlar/today.xml"
            response = requests.get(url, verify=False, timeout=3)
            if response.status_code == 200:
                root = ET.fromstring(response.content)
                usd = root.find("./Currency[@CurrencyCode='USD']/ForexSelling")
                eur = root.find("./Currency[@CurrencyCode='EUR']/ForexSelling")
                if usd is not None:
                    rates['USD'] = Decimal(usd.text)
                if eur is not None:
                    rates['EUR'] = Decimal(eur.text)

                cls._kur_cache = rates
                cls._kur_son_guncelleme = simdi

        except Exception as e:
            logger.warning(f"TCMB Kur çekme hatası: {e}")
            return cls._kur_cache if cls._kur_cache else rates

        return rates

    @staticmethod
    def _get_gidis_nakliye_satis(kalem):
        """Formdan girilen nakliye satış bedeli (gidiş).
        Checkbox aktifse nakliye_satis_fiyat = gidiş + dönüş toplam, yarıya böl."""
        if bool(kalem.donus_nakliye_fatura_et):
            # Gidiş-Geliş seçildi: nakliye_satis_fiyat 2 ile çarpılı tutarı yarıya böl
            return to_decimal(kalem.nakliye_satis_fiyat) / Decimal('2')
        else:
            # Sadece gidiş seçildi: doğrudan kullan
            return to_decimal(kalem.nakliye_satis_fiyat)

    @staticmethod
    def _get_planlanan_donus_nakliye_satis(kalem):
        """Formdaki checkbox'a göre planlanan dönüş nakliye satış bedeli.
        Checkbox aktifse nakliye_satis_fiyat = gidiş + dönüş toplam, yarıya böl."""
        if not bool(kalem.donus_nakliye_fatura_et):
            return Decimal('0.00')
        # Gidiş-Geliş seçildi: nakliye_satis_fiyat 2 ile çarpılı tutarı yarıya böl
        return to_decimal(kalem.nakliye_satis_fiyat) / Decimal('2')

    @staticmethod
    def _get_donus_nakliye_satis(kalem):
        """Dönüşte tahakkuk edecek satış bedeli (modal override varsa onu kullanır)."""
        if kalem.donus_nakliye_satis_fiyat is not None:
            return to_decimal(kalem.donus_nakliye_satis_fiyat)
        return KiralamaService._get_planlanan_donus_nakliye_satis(kalem)

    @staticmethod
    def _hesapla_bekleyen_kalem_tutari(kalem, referans_tarih=None):
        """Kalem için bugüne kadar tahakkuk eden kira alacağını hesaplar (nakliye ayrı kaydedilir)."""
        bas = to_date(kalem.kiralama_baslangici)
        bit = to_date(kalem.kiralama_bitis)
        if not (bas and bit):
            return Decimal('0.00')

        if referans_tarih is None:
            referans_tarih = date.today()

        if bas > referans_tarih:
            return Decimal('0.00')

        ust_sinir = bit if kalem.sonlandirildi else min(bit, referans_tarih)
        if ust_sinir < bas:
            return Decimal('0.00')

        gun = KiralamaService._hesapla_gun_sayisi(bas, ust_sinir)
        kira_tahakkuk = to_decimal(kalem.kiralama_brm_fiyat) * Decimal(gun)
        return kira_tahakkuk

    @staticmethod
    def _hesapla_sozlesme_kalem_tutari(kalem):
        """Kalem için toplam sozlesme kira tutarini hesaplar (nakliye ayrı kaydedilir)."""
        bas = to_date(kalem.kiralama_baslangici)
        bit = to_date(kalem.kiralama_bitis)
        if not (bas and bit) or bit < bas:
            return Decimal('0.00')

        gun = KiralamaService._hesapla_gun_sayisi(bas, bit)
        kira_toplam = to_decimal(kalem.kiralama_brm_fiyat) * Decimal(gun)
        return kira_toplam

    @staticmethod
    def _hesapla_gun_sayisi(bas, bit):
        """
        Başlangıç ve bitiş tarihleri arasındaki gün sayısını hesaplar.
        TÜM gün hesaplamaları bu fonksiyon üzerinden yapılmalı.
        """
        if not (bas and bit):
            return 0
        gun = (bit - bas).days + 1
        return max(gun, 0)

    @staticmethod
    def _hesapla_kalem_satis_tutari(bas, bit, kiralama_brm_fiyat, nakliye_satis_fiyat):
        """
        Kalem için satış tutarını backend'de YENIDEN HESAPLAR (DOĞRULUK KAYNAĞIDIR).
        Frontend'den gelen tutar KABUL EDİLMEZ.

        Formül:
          gun = bitis - baslangic + 1
          toplam = gun * kiralama_brm_fiyat + nakliye_satis_fiyat
        """
        gun = KiralamaService._hesapla_gun_sayisi(bas, bit)
        if gun <= 0:
            return Decimal('0.00')
        kiralama_tutari = to_decimal(kiralama_brm_fiyat) * Decimal(gun)
        nakliye_tutari = to_decimal(nakliye_satis_fiyat)
        return kiralama_tutari + nakliye_tutari

    @staticmethod
    def guncelle_cari_toplam(kiralama_id, auto_commit=True):
        """Kiralamaya ait müşteri carisini bekleyen (tahakkuk eden) tutara göre günceller."""
        kiralama = db.session.get(Kiralama, kiralama_id)
        if not kiralama:
            return

        aday_kayitlar = HizmetKaydi.query.filter(
            HizmetKaydi.yon == 'giden',
            HizmetKaydi.is_deleted == False,
            HizmetKaydi.aciklama.like('Kiralama Bekleyen Bakiye%'),
            (
                (HizmetKaydi.ozel_id == kiralama.id) |
                (HizmetKaydi.fatura_no == kiralama.kiralama_form_no)
            )
        ).order_by(HizmetKaydi.id.asc()).all()

        cari_kayit = None
        for kayit in aday_kayitlar:
            if kayit.ozel_id == kiralama.id and kayit.fatura_no == kiralama.kiralama_form_no:
                cari_kayit = kayit
                break
        if not cari_kayit and aday_kayitlar:
            cari_kayit = aday_kayitlar[0]

        # Ayni kiralama icin birden fazla bekleyen bakiye kaydi olusmussa tek kayda indir.
        for kayit in aday_kayitlar:
            if cari_kayit and kayit.id != cari_kayit.id:
                db.session.delete(kayit)

        toplam_tahakkuk = Decimal('0.00')
        toplam_sozlesme = Decimal('0.00')
        for kalem in kiralama.kalemler:
            if getattr(kalem, 'is_deleted', False):
                continue
            toplam_tahakkuk += KiralamaService._hesapla_bekleyen_kalem_tutari(kalem)
            toplam_sozlesme += KiralamaService._hesapla_sozlesme_kalem_tutari(kalem)

        # Eğer kiralama gelecekte başlıyorsa cariye borç 0 gözüksün, başlangıç tarihinde otomatik hesaplama başlasın.
        toplam_gelir = toplam_tahakkuk if toplam_tahakkuk > 0 else Decimal('0.00')

        if toplam_gelir > 0:
            if not cari_kayit:
                kdv_orani = getattr(kiralama, 'kdv_orani', None)
                if kdv_orani is None:
                    kdv_orani = 0
                cari_kayit = HizmetKaydi(
                    firma_id=kiralama.firma_musteri_id,
                    tarih=date.today(),
                    tutar=toplam_gelir,
                    yon='giden',
                    fatura_no=kiralama.kiralama_form_no,
                    ozel_id=kiralama.id,
                    aciklama=f"Kiralama Bekleyen Bakiye - {kiralama.kiralama_form_no}",
                    kdv_orani=kdv_orani
                )
                db.session.add(cari_kayit)
                db.session.flush()
                db.session.refresh(cari_kayit)
                print(f"[DEBUG] DB'ye yazılan HizmetKaydi (guncelle_cari_toplam): id={cari_kayit.id}, kdv_orani={cari_kayit.kdv_orani}")
            else:
                kdv_orani = getattr(kiralama, 'kdv_orani', None)
                if kdv_orani is None:
                    kdv_orani = 0
                cari_kayit.firma_id = kiralama.firma_musteri_id
                cari_kayit.fatura_no = kiralama.kiralama_form_no
                cari_kayit.ozel_id = kiralama.id
                cari_kayit.tarih = date.today()
                cari_kayit.tutar = toplam_gelir
                cari_kayit.kdv_orani = kdv_orani
                cari_kayit.aciklama = f"Kiralama Bekleyen Bakiye - {kiralama.kiralama_form_no}"

            db.session.add(cari_kayit)
        elif cari_kayit:
            db.session.delete(cari_kayit)

        # Kiralamaya bağlı nakliye HizmetKaydi'lerini ayrı olarak senkronize et
        from app.services.nakliye_services import CariServis as NakliyeCariServis
        db.session.flush()
        for nakliye in kiralama.nakliyeler:
            NakliyeCariServis.musteri_nakliye_senkronize_et(nakliye)

        if auto_commit:
            try:
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                logger.error(f"Cari Toplam Güncelleme Commit Hatası: {e}")
                raise ValidationError("Finansal kayıt güncellenemedi.")

    @classmethod
    def create_kiralama_with_relations(cls, kiralama_data, kalemler_data, actor_id=None):
        """Yeni kiralama ve tüm alt operasyonel kayıtları tek işlemde oluşturur."""
        import traceback
        max_retries = 3
        retry_count = 0
        logger = logging.getLogger(__name__)
        logger.debug(f"[CREATE] kiralama_data: {kiralama_data}")
        logger.debug(f"[CREATE] kalemler_data: {kalemler_data}")
        # Form numarası zorunlu kontrol
        if not kiralama_data.get('kiralama_form_no'):
            logger.error("[CREATE] Form numarası boş!")
            raise ValueError("Kiralama form numarası boş olamaz. Lütfen form numarası giriniz.")
        while retry_count < max_retries:
            try:
                kiralama = Kiralama(**kiralama_data)
                logger.debug(f"[CREATE] Kiralama nesnesi oluşturuldu: {kiralama}")
                cls.save(kiralama, is_new=True, auto_commit=False, actor_id=actor_id)
                db.session.flush()
                logger.debug(f"[CREATE] Kiralama flush sonrası id: {kiralama.id}")
                for k_data in kalemler_data:
                    logger.debug(f"[CREATE] Kalem işleniyor: {k_data}")
                    bas, bit = to_date(k_data.get('kiralama_baslangici')), to_date(k_data.get('kiralama_bitis'))
                    if not (bas and bit):
                        logger.warning(f"[CREATE] Kalem başlangıç/bitiş eksik: {k_data}")
                        continue
                    kalem = KiralamaKalemi(kiralama_id=kiralama.id, sonlandirildi=False)
                    kalem.kiralama_baslangici, kalem.kiralama_bitis = bas, bit
                    kalem.kiralama_brm_fiyat = to_decimal(k_data.get('kiralama_brm_fiyat'))
                    kalem.kiralama_alis_fiyat = to_decimal(k_data.get('kiralama_alis_fiyat'))
                    kalem.nakliye_satis_fiyat = to_decimal(k_data.get('nakliye_satis_fiyat'))
                    kalem.donus_nakliye_fatura_et = bool(int(k_data.get('donus_nakliye_fatura_et') or 0))
                    kalem.nakliye_alis_fiyat = to_decimal(k_data.get('nakliye_alis_fiyat'))
                    # Alış KDV oranlarını formdan al ve kaydet
                    kalem.kiralama_alis_kdv = to_int_or_none(k_data.get('kiralama_alis_kdv'))
                    kalem.nakliye_alis_kdv = to_int_or_none(k_data.get('nakliye_alis_kdv'))
                    kalem.nakliye_satis_kdv = to_int_or_none(k_data.get('nakliye_satis_kdv'))
                    kalem.nakliye_alis_tevkifat_oran = k_data.get('nakliye_alis_tevkifat_oran') or None
                    kalem.nakliye_satis_tevkifat_oran = k_data.get('nakliye_satis_tevkifat_oran') or None

                    # BACKEND TARAFINDA TUTARI YENIDEN HESAPLA (TEK DOĞRULUK KAYNAĞIDIR)
                    gun = cls._hesapla_gun_sayisi(bas, bit)
                    hesaplanan_tutar = cls._hesapla_kalem_satis_tutari(bas, bit, kalem.kiralama_brm_fiyat, kalem.nakliye_satis_fiyat)
                    logger.info(f"[CREATE-TUTAR-DOGRULAMA] Kalem ID (yeni): Gün={gun}, Günlük Fiyat={kalem.kiralama_brm_fiyat}, Nakliye={kalem.nakliye_satis_fiyat}, Hesaplanan Toplam={hesaplanan_tutar}")
                    is_dis_ekipman = int(k_data.get('dis_tedarik_ekipman') or 0) == 1
                    makine_adi = "Makine"
                    if is_dis_ekipman:
                        kalem.is_dis_tedarik_ekipman = True
                        kalem.harici_ekipman_tedarikci_id = int(k_data.get('harici_ekipman_tedarikci_id') or 0)
                        kalem.harici_ekipman_tipi = k_data.get('harici_ekipman_tipi')
                        kalem.harici_ekipman_marka = k_data.get('harici_ekipman_marka')
                        kalem.harici_ekipman_model = k_data.get('harici_ekipman_model')
                        kalem.harici_ekipman_seri_no = k_data.get('harici_ekipman_seri_no')
                        kalem.harici_ekipman_kapasite = to_int_or_none(k_data.get('harici_ekipman_kaldirma_kapasitesi'))
                        kalem.harici_ekipman_yukseklik = to_int_or_none(k_data.get('harici_ekipman_calisma_yuksekligi'))
                        kalem.harici_ekipman_uretim_yili = to_int_or_none(k_data.get('harici_ekipman_uretim_tarihi'))
                        makine_adi = kalem.harici_ekipman_marka or "Dış Ekipman"
                        if kalem.kiralama_alis_fiyat > 0 and kalem.harici_ekipman_tedarikci_id > 0:
                            ust_sinir = bit if kalem.sonlandirildi else min(bit, date.today())
                            gun = cls._hesapla_gun_sayisi(bas, ust_sinir)
                            tedarikci_id = kalem.harici_ekipman_tedarikci_id if kalem.harici_ekipman_tedarikci_id and kalem.harici_ekipman_tedarikci_id > 0 else kalem.nakliye_tedarikci_id
                            logger.debug(f"[CREATE] Dış ekipman/nakliye HizmetKaydi ekleniyor: tedarikci_id={tedarikci_id}, tutar={kalem.kiralama_alis_fiyat * gun}, kdv_orani={kalem.kiralama_alis_kdv}, nakliye_alis_kdv={kalem.nakliye_alis_kdv}")
                            hizmet_kaydi = HizmetKaydi(
                                firma_id=tedarikci_id,
                                tarih=date.today(),
                                tutar=(kalem.kiralama_alis_fiyat * gun),
                                yon='gelen',
                                fatura_no=kiralama.kiralama_form_no,
                                ozel_id=kalem.id,
                                aciklama=f"Dış Kiralama: {makine_adi}",
                                kdv_orani=kalem.kiralama_alis_kdv,
                                kiralama_alis_kdv=kalem.kiralama_alis_kdv,
                                nakliye_alis_kdv=kalem.nakliye_alis_kdv
                            )
                            logger.info(f"[HizmetKaydi] FİRMA_ID={hizmet_kaydi.firma_id} | NAKLIYE_ALIS_KDV={hizmet_kaydi.nakliye_alis_kdv}")
                            db.session.add(hizmet_kaydi)
                    else:
                        eid = int(k_data.get('ekipman_id') or 0)
                        if eid > 0:
                            kalem.ekipman_id = eid
                            ekip = db.session.get(Ekipman, eid)
                            if ekip:
                                ekip.calisma_durumu = 'kirada'
                                makine_adi = ekip.kod
                    is_harici_nakliye = int(k_data.get('dis_tedarik_nakliye') or 0) == 1
                    kalem.is_harici_nakliye = is_harici_nakliye
                    kalem.is_oz_mal_nakliye = not is_harici_nakliye
                    if is_harici_nakliye:
                        kalem.nakliye_tedarikci_id = int(k_data.get('nakliye_tedarikci_id') or 0)
                        kalem.nakliye_araci_id = None
                    else:
                        kalem.nakliye_tedarikci_id = None
                        nid = int(k_data.get('nakliye_araci_id') or 0)
                        kalem.nakliye_araci_id = nid if nid > 0 else None
                    logger.debug(f"[CREATE] Kalem kaydediliyor: {kalem}")
                    KiralamaKalemiService.save(kalem, is_new=True, auto_commit=False, actor_id=actor_id)
                    db.session.flush()
                    logger.debug(f"[CREATE] Kalem flush sonrası id: {kalem.id}")
                    if to_decimal(kalem.nakliye_satis_fiyat) > 0 or to_decimal(kalem.nakliye_alis_fiyat) > 0:
                        logger.debug(f"[CREATE] Nakliye ve cari oluşturuluyor: kalem_id={kalem.id}")
                        cls._create_nakliye_ve_cari(kiralama, kalem, makine_adi, bas)
                logger.debug(f"[CREATE] Cari toplam güncelleniyor: kiralama_id={kiralama.id}")
                cls.guncelle_cari_toplam(kiralama.id, auto_commit=False)
                logger.debug(f"[CREATE] Commit ediliyor...")
                db.session.commit()
                logger.debug(f"[CREATE] Commit sonrası kiralama id: {kiralama.id}")
                return kiralama
            except IntegrityError:
                db.session.rollback()
                retry_count += 1
                logger.warning(f"[CREATE] IntegrityError, retry: {retry_count}")
                kiralama_data['kiralama_form_no'] = None
                if retry_count >= max_retries:
                    logger.error(f"[CREATE] Kiralama numarası çakışması aşılamadı.")
                    raise ValidationError("Kiralama numarası çakışması aşılamadı.")
            except Exception as e:
                db.session.rollback()
                tb_str = traceback.format_exc()
                logger.error(f"[CREATE] Kiralama Kayıt Hatası: {e}\nTraceback:\n{tb_str}")
                raise ValidationError(f"Kiralama kaydedilirken bir hata oluştu: {str(e)}")

    @classmethod
    def update_kiralama_with_relations(cls, kiralama_id, kiralama_data, kalemler_data, actor_id=None):
        """Mevcut kiralamayı günceller, mali kayıtları yeniden hesaplar."""
        kiralama = db.session.get(Kiralama, kiralama_id)
        if not kiralama: raise ValidationError("Kiralama bulunamadı.")

        try:
            HizmetKaydi.query.filter_by(fatura_no=kiralama.kiralama_form_no).delete(synchronize_session=False)
            # Dönüş sefer kayıtlarını koru (bunlar sonlandırma sırasında eklenir)
            Nakliye.query.filter(
                Nakliye.kiralama_id == kiralama.id,
                (Nakliye.aciklama == None) | ~Nakliye.aciklama.like('Dönüş:%')
            ).delete(synchronize_session=False)

            for key, value in kiralama_data.items():
                if hasattr(kiralama, key): setattr(kiralama, key, value)
            cls.save(kiralama, is_new=False, auto_commit=False, actor_id=actor_id)

            formdan_gelen_idler = []

            for k_data in kalemler_data:
                bas, bit = to_date(k_data.get('kiralama_baslangici')), to_date(k_data.get('kiralama_bitis'))
                if not (bas and bit): continue

                try:
                    kalem_id = k_data.get('id')
                    parsed_id = int(kalem_id) if kalem_id else 0
                except (ValueError, TypeError):
                    parsed_id = 0

                aktif = (db.session.get(KiralamaKalemi, parsed_id) if parsed_id > 0 else None) or KiralamaKalemi(kiralama_id=kiralama.id)

                # ÖNEMLI: Tamamlanmış kalemler için sonlandirildi bayrağını koru
                is_yeni = not aktif.id
                orijinal_sonlandirildi = aktif.sonlandirildi if not is_yeni else False

                aktif.kiralama_baslangici, aktif.kiralama_bitis = bas, bit
                aktif.kiralama_brm_fiyat = to_decimal(k_data.get('kiralama_brm_fiyat'))
                aktif.kiralama_alis_fiyat = to_decimal(k_data.get('kiralama_alis_fiyat'))
                aktif.nakliye_satis_fiyat = to_decimal(k_data.get('nakliye_satis_fiyat'))
                aktif.donus_nakliye_fatura_et = bool(int(k_data.get('donus_nakliye_fatura_et') or 0))
                if not aktif.donus_nakliye_fatura_et:
                    aktif.donus_nakliye_satis_fiyat = None
                aktif.nakliye_alis_fiyat = to_decimal(k_data.get('nakliye_alis_fiyat'))
                # Alış KDV oranı güncellemesi
                aktif.kiralama_alis_kdv = to_int_or_none(k_data.get('kiralama_alis_kdv'))
                aktif.nakliye_alis_kdv = to_int_or_none(k_data.get('nakliye_alis_kdv'))
                aktif.nakliye_satis_kdv = to_int_or_none(k_data.get('nakliye_satis_kdv'))
                aktif.nakliye_alis_tevkifat_oran = k_data.get('nakliye_alis_tevkifat_oran') or None
                aktif.nakliye_satis_tevkifat_oran = k_data.get('nakliye_satis_tevkifat_oran') or None

                # Orijinal sonlandirildi durumunu geri yükle
                aktif.sonlandirildi = orijinal_sonlandirildi

                # BACKEND TARAFINDA TUTARI YENIDEN HESAPLA (TEK DOĞRULUK KAYNAĞIDIR)
                gun = cls._hesapla_gun_sayisi(bas, bit)
                hesaplanan_tutar = cls._hesapla_kalem_satis_tutari(bas, bit, aktif.kiralama_brm_fiyat, aktif.nakliye_satis_fiyat)
                logger.info(f"[UPDATE-TUTAR-DOGRULAMA] Kalem ID={aktif.id}, Gün={gun}, Günlük Fiyat={aktif.kiralama_brm_fiyat}, Nakliye={aktif.nakliye_satis_fiyat}, Hesaplanan Toplam={hesaplanan_tutar}")
                
                # Ekipman Durumu
                is_dis = int(k_data.get('dis_tedarik_ekipman') or 0) == 1
                makine_adi = "Makine"

                if not is_dis:
                    y_eid = int(k_data.get('ekipman_id') or 0)
                    if y_eid > 0:
                        if aktif.ekipman_id and aktif.ekipman_id != y_eid:
                            eski = db.session.get(Ekipman, aktif.ekipman_id)
                            if eski: eski.calisma_durumu = 'bosta'
                        aktif.ekipman_id, aktif.is_dis_tedarik_ekipman = y_eid, False
                        ekip = db.session.get(Ekipman, y_eid)
                        if ekip: 
                            ekip.calisma_durumu, makine_adi = 'kirada', ekip.kod
                else:
                    if aktif.ekipman_id:
                        eski = db.session.get(Ekipman, aktif.ekipman_id)
                        if eski: eski.calisma_durumu = 'bosta'
                    aktif.ekipman_id = None
                    aktif.is_dis_tedarik_ekipman = True
                    aktif.harici_ekipman_tedarikci_id = int(k_data.get('harici_ekipman_tedarikci_id') or 0)
                    aktif.harici_ekipman_tipi = k_data.get('harici_ekipman_tipi')
                    aktif.harici_ekipman_marka = k_data.get('harici_ekipman_marka')
                    aktif.harici_ekipman_model = k_data.get('harici_ekipman_model')
                    aktif.harici_ekipman_seri_no = k_data.get('harici_ekipman_seri_no')
                    aktif.harici_ekipman_kapasite = to_int_or_none(k_data.get('harici_ekipman_kaldirma_kapasitesi'))
                    aktif.harici_ekipman_yukseklik = to_int_or_none(k_data.get('harici_ekipman_calisma_yuksekligi'))
                    aktif.harici_ekipman_uretim_yili = to_int_or_none(k_data.get('harici_ekipman_uretim_tarihi'))
                    
                    makine_adi = aktif.harici_ekipman_marka or "Dış Ekipman"

                    if aktif.kiralama_alis_fiyat > 0 and aktif.harici_ekipman_tedarikci_id > 0:
                        ust_sinir = bit if aktif.sonlandirildi else min(bit, date.today())
                        gun = cls._hesapla_gun_sayisi(bas, ust_sinir)
                        db.session.add(HizmetKaydi(
                            firma_id=aktif.harici_ekipman_tedarikci_id, tarih=date.today(),
                            tutar=(aktif.kiralama_alis_fiyat * gun), yon='gelen',
                            fatura_no=kiralama.kiralama_form_no, ozel_id=aktif.id, aciklama=f"Dış Kiralama (Güncelleme): {makine_adi}"
                        ))

                # Nakliye ayarları
                aktif.is_harici_nakliye = int(k_data.get('dis_tedarik_nakliye') or 0) == 1
                aktif.is_oz_mal_nakliye = not aktif.is_harici_nakliye
                aktif.nakliye_tedarikci_id = int(k_data.get('nakliye_tedarikci_id') or 0) if aktif.is_harici_nakliye else None
                nid = int(k_data.get('nakliye_araci_id') or 0)
                aktif.nakliye_araci_id = nid if (not aktif.is_harici_nakliye and nid > 0) else None

                KiralamaKalemiService.save(aktif, is_new=not bool(aktif.id), auto_commit=False, actor_id=actor_id)
                db.session.flush()
                formdan_gelen_idler.append(aktif.id)

                if to_decimal(aktif.nakliye_satis_fiyat) > 0 or to_decimal(aktif.nakliye_alis_fiyat) > 0:
                    cls._create_nakliye_ve_cari(kiralama, aktif, makine_adi, bas)

            for k in list(kiralama.kalemler):
                if k.id not in formdan_gelen_idler:
                    # Tamamlanmış kalemler silinemez
                    if k.sonlandirildi:
                        raise ValidationError(f"Tamamlanmış kalem silinemez: {k.id}")
                    if k.ekipman: k.ekipman.calisma_durumu = 'bosta'
                    db.session.delete(k)

            # Sabit toplam yazmak yerine bekleyen cari tahakkuk kaydını güncelle
            cls.guncelle_cari_toplam(kiralama.id, auto_commit=False)

            db.session.commit()
            return kiralama
        except Exception as e:
            db.session.rollback()
            logger.error(f"Kiralama Güncelleme Hatası: {e}", exc_info=True)
            raise ValidationError(f"Güncelleme başarısız: {str(e)}")

    @classmethod
    def delete_with_relations(cls, kiralama_id, actor_id=None):
        """Kiralamayı siler, ekipmanları boşa çıkarır."""
        kiralama = db.session.get(Kiralama, kiralama_id)
        if not kiralama: raise ValidationError("Kiralama bulunamadı.")

        try:
            HizmetKaydi.query.filter_by(fatura_no=kiralama.kiralama_form_no).delete(synchronize_session=False)
            for k in kiralama.kalemler:
                if k.ekipman: k.ekipman.calisma_durumu = 'bosta'
            
            cls.delete(kiralama.id, auto_commit=False, actor_id=actor_id)
            db.session.commit()
            return True
        except Exception as e:
            db.session.rollback()
            raise ValidationError(f"Silme hatası: {str(e)}")

    @staticmethod
    def _create_nakliye_ve_cari(kiralama, kalem, makine_adi, bas_tarihi):
        """Nakliye seferi ve varsa taşeron cari gider kaydını oluşturur."""
        firma_adi = kiralama.firma_musteri.firma_adi if kiralama.firma_musteri else "Müşteri"
        is_yeri = (kiralama.makine_calisma_adresi or '').strip() or firma_adi
        gidis_sube_adi = kalem.ekipman.sube.isim if (kalem.ekipman and kalem.ekipman.sube) else None
        if gidis_sube_adi:
            guzergah_gidis = f"{makine_adi} {gidis_sube_adi} şubesinden {firma_adi} firmasının {is_yeri}'ne götürüldü"
        else:
            guzergah_gidis = f"{makine_adi} {firma_adi} firmasına götürüldü ({is_yeri})"

        yeni_sefer = Nakliye(
            kiralama_id=kiralama.id,
            firma_id=kiralama.firma_musteri_id,
            tarih=bas_tarihi,
            guzergah=guzergah_gidis,
            tutar=KiralamaService._get_gidis_nakliye_satis(kalem),
            kdv_orani=kalem.nakliye_satis_kdv if kalem.nakliye_satis_kdv is not None else (kiralama.kdv_orani if kiralama.kdv_orani is not None else 20),
            tevkifat_orani=kalem.nakliye_satis_tevkifat_oran or None,
            aciklama=f"Gidiş: {kiralama.kiralama_form_no}"
        )

        if kalem.is_harici_nakliye and kalem.nakliye_tedarikci_id:
            # TAŞERON NAKLİYE
            yeni_sefer.nakliye_tipi = 'taseron'
            yeni_sefer.taseron_firma_id = kalem.nakliye_tedarikci_id
            yeni_sefer.taseron_maliyet = to_decimal(kalem.nakliye_alis_fiyat)
            yeni_sefer.plaka = "Dış Nakliye"

            if yeni_sefer.taseron_maliyet > 0:
                nakliye_kdv = kalem.nakliye_alis_kdv
                # HİZMETKAYDI: yeni eklenen sütunları da ekle
                db.session.add(HizmetKaydi(
                    firma_id=yeni_sefer.taseron_firma_id,
                    tarih=date.today(),
                    tutar=yeni_sefer.taseron_maliyet,
                    yon='gelen',
                    fatura_no=kiralama.kiralama_form_no,
                    aciklama=f"Taşeron Nakliye Bedeli ({makine_adi}) - {kiralama.kiralama_form_no}",
                    nakliye_alis_kdv=nakliye_kdv,
                    kdv_orani=None
                ))
        else:
            # ÖZ MAL NAKLİYE
            yeni_sefer.nakliye_tipi = 'oz_mal'
            yeni_sefer.arac_id = kalem.nakliye_araci_id
            if yeni_sefer.arac_id:
                secilen_arac = db.session.get(NakliyeAraci, yeni_sefer.arac_id)
                if secilen_arac:
                    yeni_sefer.plaka = secilen_arac.plaka

        yeni_sefer.hesapla_ve_guncelle()
        db.session.add(yeni_sefer)