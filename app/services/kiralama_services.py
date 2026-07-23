import os
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, date, timedelta, timezone
from decimal import Decimal, InvalidOperation
import logging
import re
from sqlalchemy import and_, func, or_
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.extensions import db
from app.utils import bugun as _bugun
# En güncel yapı: app/services/base_service.py
from app.services.base import BaseService, ValidationError

# İlgili Modüllerin İçe Aktarılması
from app.kiralama.models import Kiralama, KiralamaKalemi, KiralamaKalemDondurma
from app.filo.models import Ekipman
from app.firmalar.models import Firma
from app.cari.models import HizmetKaydi
from app.nakliyeler.models import Nakliye
from app.araclar.models import Arac as NakliyeAraci
from app.subeler.models import Sube
from app.ayarlar.models import AppSettings
from app.models.system_state import ExchangeRate

logger = logging.getLogger(__name__)


def _soft_delete_hizmet_kaydi(kayit, actor_id=None):
    """Cari kaydini geri izlenebilir sekilde pasiflestirir."""
    kayit.is_deleted = True
    kayit.is_active = False
    kayit.deleted_at = datetime.now(timezone.utc)
    if actor_id is not None and hasattr(kayit, 'deleted_by_id'):
        kayit.deleted_by_id = actor_id
    db.session.add(kayit)


class ExchangeRateUnavailableError(RuntimeError):
    """Ortak kur verisi okunamadiginda veya henuz hazir olmadiginda olusur."""


class ExchangeRateRefreshError(RuntimeError):
    """TCMB kur yenileme islemi tamamlanamadiginda olusur."""


TURKIYE_TZ = timezone(timedelta(hours=3))


def _turkiye_simdi():
    return datetime.now(TURKIYE_TZ)


def _tcmb_request_verify():
    """
    TCMB HTTPS istegi icin SSL dogrulama parametresi.
    Varsayilan: guvenli (certifi yolu veya True).
    Sadece gelistirme / ozel ag ortamlari icin TCMB_SSL_VERIFY=0 ile kapatilabilir.
    """
    flag = os.environ.get("TCMB_SSL_VERIFY", "1").strip().lower()
    if flag in ("0", "false", "no", "off"):
        logger.warning(
            "TCMB istegi SSL dogrulamasiz yapiliyor (TCMB_SSL_VERIFY=%s). "
            "Uretimde kullanmayin.",
            flag,
        )
        return False
    try:
        import certifi

        return certifi.where()
    except ImportError:
        return True


def _tcmb_request_timeout():
    """Baglanti + okuma icin saniye (tek sayi). Ortam: TCMB_REQUEST_TIMEOUT, varsayilan 10."""
    raw = os.environ.get("TCMB_REQUEST_TIMEOUT", "10").strip()
    try:
        t = float(raw)
        return max(3.0, min(t, 60.0))
    except ValueError:
        return 10.0

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

def guncelle_cari_toplam(kiralama_id, auto_commit=True, sync_firma_cache=True):
    """Dış modüllerin kiralama cari toplamını tetiklemesi için köprü fonksiyon."""
    return KiralamaService.guncelle_cari_toplam(
        kiralama_id,
        auto_commit=auto_commit,
        sync_firma_cache=sync_firma_cache,
    )


# ==============================================================================
# KİRALAMA KALEMİ SERVİSİ
# ==============================================================================

class KiralamaKalemiService(BaseService):
    """Kiralama satırlarının (kalemlerin) iş mantığını yönetir."""
    model = KiralamaKalemi
    use_soft_delete = False 

    @staticmethod
    def _soft_delete_hizmet_kaydi(kayit):
        _soft_delete_hizmet_kaydi(kayit)

    @staticmethod
    def _validate_donus_nakliye_inputs(
        is_harici_nakliye,
        nakliye_tedarikci_id,
        nakliye_alis_fiyat,
        donus_nakliye_alis_kdv,
        donus_nakliye_satis_fiyat,
    ):
        donus_satis_explicit = donus_nakliye_satis_fiyat not in (None, '')
        donus_satis = (
            to_decimal(donus_nakliye_satis_fiyat)
            if donus_satis_explicit
            else None
        )
        if donus_satis is not None and donus_satis < 0:
            raise ValidationError("Dönüş nakliye satış bedeli negatif olamaz.")

        donus_alis = to_decimal(nakliye_alis_fiyat)
        if donus_alis < 0:
            raise ValidationError("Dönüş nakliye alış bedeli negatif olamaz.")

        tedarikci_id = to_int_or_none(nakliye_tedarikci_id)
        alis_kdv = to_int_or_none(donus_nakliye_alis_kdv)

        if is_harici_nakliye:
            if not tedarikci_id:
                raise ValidationError("Dönüş taşeron nakliye firması seçilmelidir.")

            tedarikci = db.session.get(Firma, tedarikci_id)
            if not tedarikci or tedarikci.is_deleted or not tedarikci.is_active:
                raise ValidationError("Seçilen dönüş taşeron nakliye firması geçerli değil.")

            if donus_alis > 0 and (alis_kdv is None or alis_kdv < 0 or alis_kdv > 100):
                raise ValidationError("Dönüş taşeron KDV oranı 0 ile 100 arasında olmalıdır.")
        else:
            tedarikci_id = None
            donus_alis = None
            alis_kdv = None

        return {
            'donus_satis_explicit': donus_satis_explicit,
            'donus_satis': donus_satis,
            'tedarikci_id': tedarikci_id,
            'donus_alis': donus_alis,
            'alis_kdv': alis_kdv,
        }

    @staticmethod
    def _donus_makine_bilgisi(kalem):
        if kalem.ekipman and kalem.ekipman.kod:
            return kalem.ekipman.kod
        if any([kalem.harici_ekipman_marka, kalem.harici_ekipman_model, kalem.harici_ekipman_seri_no]):
            marka_model = " ".join(
                filter(None, [kalem.harici_ekipman_marka, kalem.harici_ekipman_model])
            ).strip()
            return marka_model or kalem.harici_ekipman_seri_no
        return "Makine"

    @staticmethod
    def _donus_sube_adi(donus_sube_val):
        if donus_sube_val and str(donus_sube_val).isdigit() and int(donus_sube_val) > 0:
            donus_sube = db.session.get(Sube, int(donus_sube_val))
            return donus_sube.isim if donus_sube else "Bilinmeyen Şube"
        if donus_sube_val == 'tedarikci':
            return "Tedarikçiye İade"
        return "Bilinmeyen Şube"

    @classmethod
    def _sync_donus_taseron_cari(cls, kalem, makine_bilgisi, donus_sube_adi):
        form_no = kalem.kiralama.kiralama_form_no if kalem.kiralama else None
        mevcut_kayitlar = HizmetKaydi.query.filter(
            HizmetKaydi.ozel_id == kalem.id,
            HizmetKaydi.yon == 'gelen',
            HizmetKaydi.fatura_no == form_no,
            HizmetKaydi.aciklama.like('Dönüş Nakliye:%'),
            HizmetKaydi.is_deleted == False,
        ).order_by(HizmetKaydi.id.asc()).all()

        donus_alis = to_decimal(kalem.donus_nakliye_alis_fiyat)
        aktif_kayit = None
        if (
            kalem.donus_is_harici_nakliye
            and kalem.donus_nakliye_tedarikci_id
            and donus_alis > 0
        ):
            for kayit in mevcut_kayitlar:
                if kayit.firma_id == kalem.donus_nakliye_tedarikci_id and aktif_kayit is None:
                    aktif_kayit = kayit
                else:
                    cls._soft_delete_hizmet_kaydi(kayit)

            if aktif_kayit is None:
                aktif_kayit = HizmetKaydi(yon='gelen')

            aktif_kayit.firma_id = kalem.donus_nakliye_tedarikci_id
            aktif_kayit.tarih = date.today()
            aktif_kayit.islem_tarihi = kalem.kiralama_bitis or date.today()
            aktif_kayit.tutar = donus_alis
            aktif_kayit.yon = 'gelen'
            aktif_kayit.fatura_no = form_no
            aktif_kayit.ozel_id = kalem.id
            aktif_kayit.aciklama = f"Dönüş Nakliye: {makine_bilgisi} - {donus_sube_adi}"
            aktif_kayit.kdv_orani = None
            aktif_kayit.nakliye_alis_kdv = kalem.donus_nakliye_alis_kdv
            aktif_kayit.is_deleted = False
            aktif_kayit.is_active = True
            db.session.add(aktif_kayit)
        else:
            for kayit in mevcut_kayitlar:
                cls._soft_delete_hizmet_kaydi(kayit)

    @classmethod
    def _cleanup_legacy_musteri_donus_cari(cls, kalem):
        if not kalem.kiralama or not kalem.kiralama.firma_musteri_id:
            return

        legacy_kayitlar = HizmetKaydi.query.filter(
            HizmetKaydi.ozel_id == kalem.id,
            HizmetKaydi.firma_id == kalem.kiralama.firma_musteri_id,
            HizmetKaydi.nakliye_id.is_(None),
            HizmetKaydi.is_deleted == False,
            db.or_(
                HizmetKaydi.aciklama.like('Müşteri Dönüş Nakliye Bedeli%'),
                HizmetKaydi.aciklama.like('Nakliye Farkı%'),
                HizmetKaydi.aciklama.like('Dönüş Nakliye (%'),
            ),
        ).order_by(HizmetKaydi.id.asc()).all()

        for kayit in legacy_kayitlar:
            cls._soft_delete_hizmet_kaydi(kayit)

    @staticmethod
    def _create_zero_musteri_donus_cari(kalem, makine_bilgisi):
        if not kalem.kiralama or not kalem.kiralama.firma_musteri_id:
            return

        kdv_kaynak = getattr(kalem.kiralama, 'kdv_orani', None)
        hizmet_kaydi = HizmetKaydi(
            firma_id=kalem.kiralama.firma_musteri_id,
            tarih=date.today(),
            islem_tarihi=kalem.kiralama_bitis or date.today(),
            tutar=Decimal('0.00'),
            yon='giden',
            fatura_no=kalem.kiralama.kiralama_form_no,
            ozel_id=kalem.id,
            aciklama=f"Dönüş Nakliye ({makine_bilgisi}) - Form: {kalem.kiralama.kiralama_form_no}",
            kdv_orani=kdv_kaynak if kdv_kaynak is not None else 20,
            nakliye_alis_kdv=None,
        )
        db.session.add(hizmet_kaydi)

    @staticmethod
    def _create_donus_nakliye_seferi(kalem, makine_bilgisi, musteri_adi, is_yeri_donus, donus_sube_adi, donus_satis):
        if not kalem.kiralama:
            return None

        form_no = kalem.kiralama.kiralama_form_no or ''
        Nakliye.query.filter(
            Nakliye.kiralama_id == kalem.kiralama_id,
            Nakliye.aciklama == f"Dönüş: {form_no} #{kalem.id}"
        ).delete(synchronize_session=False)

        donus_guzergah = (
            f"{makine_bilgisi} {musteri_adi} firmasının {is_yeri_donus}'nden "
            f"{donus_sube_adi} şubesine getirildi"
        )
        nak_tipi = 'taseron' if kalem.donus_is_harici_nakliye else 'oz_mal'
        donus_sefer = Nakliye(
            kiralama_id=kalem.kiralama_id,
            firma_id=kalem.kiralama.firma_musteri_id,
            tarih=kalem.kiralama_bitis or date.today(),
            islem_tarihi=kalem.kiralama_bitis or date.today(),
            guzergah=donus_guzergah,
            tutar=donus_satis,
            kdv_orani=(
                kalem.nakliye_satis_kdv
                if kalem.nakliye_satis_kdv is not None
                else (kalem.kiralama.kdv_orani if kalem.kiralama.kdv_orani is not None else 20)
            ),
            tevkifat_orani=kalem.nakliye_satis_tevkifat_oran or None,
            aciklama=f"Dönüş: {form_no} #{kalem.id}",
            nakliye_tipi=nak_tipi,
            arac_id=kalem.donus_nakliye_araci_id if not kalem.donus_is_harici_nakliye else None,
        )

        if kalem.donus_is_harici_nakliye:
            donus_sefer.taseron_firma_id = kalem.donus_nakliye_tedarikci_id
            donus_sefer.taseron_maliyet = to_decimal(kalem.donus_nakliye_alis_fiyat)
            donus_sefer.taseron_kdv_orani = kalem.donus_nakliye_alis_kdv
            donus_sefer.plaka = "Dış Nakliye"
            donus_sefer.arac_id = None
        else:
            donus_sefer.taseron_firma_id = None
            donus_sefer.taseron_maliyet = Decimal('0.00')
            donus_sefer.taseron_kdv_orani = None
            if kalem.donus_nakliye_araci_id:
                secilen_arac = db.session.get(NakliyeAraci, kalem.donus_nakliye_araci_id)
                if secilen_arac:
                    donus_sefer.plaka = secilen_arac.plaka

        donus_sefer.hesapla_ve_guncelle()
        db.session.add(donus_sefer)
        db.session.flush()
        return donus_sefer

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
        donus_nakliye_alis_kdv=None,
        donus_nakliye_satis_fiyat=None,
    ):
        """Kiralama kalemini sonlandırır ve makinenin durumunu günceller."""
        kalem = cls.get_by_id(kalem_id)
        if not kalem:
            raise ValidationError("İlgili kiralama kalemi bulunamadı.")

        validated = cls._validate_donus_nakliye_inputs(
            is_harici_nakliye=bool(is_harici_nakliye),
            nakliye_tedarikci_id=nakliye_tedarikci_id,
            nakliye_alis_fiyat=nakliye_alis_fiyat,
            donus_nakliye_alis_kdv=donus_nakliye_alis_kdv,
            donus_nakliye_satis_fiyat=donus_nakliye_satis_fiyat,
        )

        bitis_date = to_date(bitis_tarihi_str)
        if bitis_date:
            kalem.kiralama_bitis = bitis_date
        
        kalem.sonlandirildi = True

        # Dönüş satış bedeli modaldan gelirse kaleme kaydet.
        if validated['donus_satis_explicit']:
            kalem.donus_nakliye_satis_fiyat = validated['donus_satis']
        fiili_donus_satis = KiralamaService._get_donus_nakliye_satis(kalem)
        cls._cleanup_legacy_musteri_donus_cari(kalem)

        # Dönüş müşteri tahakkuku: planlanan bedeli yaz, sapma varsa farkı ayrı satır yaz.
        for kayit in HizmetKaydi.query.filter(
            HizmetKaydi.ozel_id == kalem.id,
            HizmetKaydi.aciklama.like('Müşteri Dönüş Nakliye Bedeli%'),
            HizmetKaydi.is_deleted == False,
        ).all():
            _soft_delete_hizmet_kaydi(kayit)
        for kayit in HizmetKaydi.query.filter(
            HizmetKaydi.ozel_id == kalem.id,
            HizmetKaydi.aciklama.like('Nakliye Farkı%'),
            HizmetKaydi.is_deleted == False,
        ).all():
            _soft_delete_hizmet_kaydi(kayit)

        # Checkbox durumunu kontrol et
        donus_checkbox_aktif = bool(kalem.donus_nakliye_fatura_et)
        
        # Checkbox AKTIF (Gidiş-Geliş): Ekle menüsünde yazıldı, sonlandır'da yazma
        # Sadece fark var ise yazacağız (aşağıya bak)
        
        # Checkbox PASİF (Sadece gidiş): Modal'dan gelen dönüş bedeli varsa doğrudan yaz  
        if False and not donus_checkbox_aktif and fiili_donus_satis > 0 and kalem.kiralama and kalem.kiralama.firma_musteri_id:
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
                islem_tarihi=kalem.kiralama_bitis or date.today(),
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
        nakliye_farki = Decimal('0')
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
                islem_tarihi=kalem.kiralama_bitis or date.today(),
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
            else:
                # donus_sube_val geçersiz/eksik olsa bile kalem sonlandırıldığında
                # makineyi bosta'ya al (şube atanmadan)
                kalem.ekipman.calisma_durumu = 'bosta'
        elif kalem.is_dis_tedarik_ekipman:
            # Dış tedarik makinesini şubeye ata (tedarikçiye iade edilene kadar bekleme)
            if donus_sube_val and str(donus_sube_val).isdigit() and int(donus_sube_val) > 0:
                kalem.donus_sube_id = int(donus_sube_val)
            else:
                kalem.donus_sube_id = None

        # Dönüş nakliye (modal): gidiş taşeron alanlarına dokunma — ayrı kolonlara yaz
        kalem.donus_is_harici_nakliye = bool(is_harici_nakliye)
        if kalem.donus_is_harici_nakliye:
            kalem.donus_nakliye_tedarikci_id = validated['tedarikci_id']
            kalem.donus_nakliye_alis_fiyat = validated['donus_alis']
            kalem.donus_nakliye_alis_kdv = validated['alis_kdv']
            kalem.donus_nakliye_araci_id = None
        else:
            kalem.donus_nakliye_tedarikci_id = None
            kalem.donus_nakliye_alis_fiyat = None
            kalem.donus_nakliye_alis_kdv = None
            kalem.donus_nakliye_araci_id = int(nakliye_araci_id or 0) or None

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

        # Harici dönüş nakliye giderini idempotent tut: aynı kalem/firma/form için
        # kayıt varsa güncelle, eski mükerrer dönüş kayıtlarını soft-delete et.
        form_no_donus = kalem.kiralama.kiralama_form_no if kalem.kiralama else None
        donus_taseron_kayitlari = HizmetKaydi.query.filter(
            HizmetKaydi.ozel_id == kalem.id,
            HizmetKaydi.yon == 'gelen',
            HizmetKaydi.fatura_no == form_no_donus,
            HizmetKaydi.aciklama.like('Dönüş Nakliye:%'),
            HizmetKaydi.is_deleted == False,
        ).order_by(HizmetKaydi.id.asc()).all()

        aktif_donus_taseron = None
        if (
            kalem.donus_is_harici_nakliye
            and kalem.donus_nakliye_tedarikci_id
            and to_decimal(kalem.donus_nakliye_alis_fiyat) > 0
        ):
            for kayit in donus_taseron_kayitlari:
                if kayit.firma_id == kalem.donus_nakliye_tedarikci_id and aktif_donus_taseron is None:
                    aktif_donus_taseron = kayit
                    continue
                kayit.is_deleted = True
                kayit.is_active = False
                kayit.deleted_at = datetime.now(timezone.utc)
                db.session.add(kayit)

            if aktif_donus_taseron is None:
                aktif_donus_taseron = HizmetKaydi(yon='gelen')

            aktif_donus_taseron.firma_id = kalem.donus_nakliye_tedarikci_id
            aktif_donus_taseron.tarih = date.today()
            aktif_donus_taseron.islem_tarihi = kalem.kiralama_bitis or date.today()
            aktif_donus_taseron.tutar = to_decimal(kalem.donus_nakliye_alis_fiyat)
            aktif_donus_taseron.yon = 'gelen'
            aktif_donus_taseron.fatura_no = form_no_donus
            aktif_donus_taseron.ozel_id = kalem.id
            aktif_donus_taseron.aciklama = f"Dönüş Nakliye: {makine_bilgisi_donus} - {donus_sube_adi}"
            aktif_donus_taseron.kdv_orani = None
            aktif_donus_taseron.nakliye_alis_kdv = kalem.donus_nakliye_alis_kdv
            aktif_donus_taseron.is_deleted = False
            aktif_donus_taseron.is_active = True
            db.session.add(aktif_donus_taseron)
        else:
            for kayit in donus_taseron_kayitlari:
                kayit.is_deleted = True
                kayit.is_active = False
                kayit.deleted_at = datetime.now(timezone.utc)
                db.session.add(kayit)

        # Müşteri carisine dönüş nakliye satış seferi ekle (hem öz mal hem harici)
        if kalem.kiralama:
            donus_satis = KiralamaService._get_donus_nakliye_satis(kalem)
            if validated['donus_satis_explicit'] or donus_satis > 0:
                form_no = kalem.kiralama.kiralama_form_no or ''
                Nakliye.query.filter(
                    Nakliye.kiralama_id == kalem.kiralama_id,
                    Nakliye.aciklama == f"Dönüş: {form_no} #{kalem.id}"
                ).delete(synchronize_session=False)

                donus_guzergah = (
                    f"{makine_bilgisi_donus} {musteri_adi} firmasının {is_yeri_donus}'nden "
                    f"{donus_sube_adi} şubesine getirildi"
                )
                nak_tipi = 'taseron' if kalem.donus_is_harici_nakliye else 'oz_mal'
                donus_sefer = Nakliye(
                    kiralama_id=kalem.kiralama_id,
                    firma_id=kalem.kiralama.firma_musteri_id,
                    tarih=kalem.kiralama_bitis or date.today(),
                    islem_tarihi=kalem.kiralama_bitis or date.today(),
                    guzergah=donus_guzergah,
                    tutar=donus_satis,
                    kdv_orani=kalem.nakliye_satis_kdv if kalem.nakliye_satis_kdv is not None else (kalem.kiralama.kdv_orani if kalem.kiralama.kdv_orani is not None else 20),
                    tevkifat_orani=kalem.nakliye_satis_tevkifat_oran or None,
                    aciklama=f"Dönüş: {form_no} #{kalem.id}",
                    nakliye_tipi=nak_tipi,
                    arac_id=kalem.donus_nakliye_araci_id if not kalem.donus_is_harici_nakliye else None,
                )
                if kalem.donus_is_harici_nakliye and kalem.donus_nakliye_tedarikci_id:
                    donus_sefer.taseron_firma_id = kalem.donus_nakliye_tedarikci_id
                    donus_sefer.taseron_maliyet = to_decimal(kalem.donus_nakliye_alis_fiyat)
                    donus_sefer.taseron_kdv_orani = kalem.donus_nakliye_alis_kdv
                    donus_sefer.plaka = "Dış Nakliye"
                    donus_sefer.arac_id = None
                else:
                    donus_sefer.taseron_firma_id = None
                    donus_sefer.taseron_maliyet = Decimal('0.00')
                    donus_sefer.taseron_kdv_orani = None
                if not kalem.donus_is_harici_nakliye and kalem.donus_nakliye_araci_id:
                    secilen_arac = db.session.get(NakliyeAraci, kalem.donus_nakliye_araci_id)
                    if secilen_arac:
                        donus_sefer.plaka = secilen_arac.plaka
                donus_sefer.hesapla_ve_guncelle()
                db.session.add(donus_sefer)

                if False and (
                    kalem.donus_is_harici_nakliye
                    and kalem.donus_nakliye_tedarikci_id
                    and to_decimal(kalem.donus_nakliye_alis_fiyat) > 0
                ):
                    donus_taseron_kayitlari = HizmetKaydi.query.filter(
                        HizmetKaydi.ozel_id == kalem.id,
                        HizmetKaydi.yon == 'gelen',
                        HizmetKaydi.fatura_no == kiralama.kiralama_form_no,
                        HizmetKaydi.aciklama.like('Dönüş Nakliye:%'),
                    ).order_by(HizmetKaydi.id.asc()).all()
                    donus_taseron_cari = donus_taseron_kayitlari[0] if donus_taseron_kayitlari else HizmetKaydi(yon='gelen')
                    for fazla_kayit in donus_taseron_kayitlari[1:]:
                        _soft_delete_hizmet_kaydi(fazla_kayit)

                    donus_taseron_cari.firma_id = kalem.donus_nakliye_tedarikci_id
                    donus_taseron_cari.tarih = kalem.kiralama_bitis or date.today()
                    donus_taseron_cari.islem_tarihi = kalem.kiralama_bitis or date.today()
                    donus_taseron_cari.tutar = to_decimal(kalem.donus_nakliye_alis_fiyat)
                    donus_taseron_cari.yon = 'gelen'
                    donus_taseron_cari.fatura_no = kiralama.kiralama_form_no
                    donus_taseron_cari.ozel_id = kalem.id
                    donus_taseron_cari.aciklama = f"Dönüş Nakliye: {makine_adi} - {donus_sube_adi}"
                    donus_taseron_cari.kdv_orani = None
                    donus_taseron_cari.nakliye_alis_kdv = kalem.donus_nakliye_alis_kdv
                    donus_taseron_cari.is_deleted = False
                    donus_taseron_cari.is_active = True
                    db.session.add(donus_taseron_cari)

        if validated['donus_satis_explicit'] and fiili_donus_satis == 0:
            cls._create_zero_musteri_donus_cari(kalem, makine_bilgisi_donus)

        cls._iptal_gelecek_dondurmalar(kalem, bitis_date)

        cls.save(kalem, is_new=False, auto_commit=False, actor_id=actor_id)
        
        # Cari hesaplamayı tetikle
        KiralamaService.guncelle_cari_toplam(kalem.kiralama_id, auto_commit=False)
        if kalem.is_dis_tedarik_ekipman and kalem.harici_ekipman_tedarikci_id:
            KiralamaService.guncelle_tedarikci_cari_toplam(
                kalem.harici_ekipman_tedarikci_id,
                auto_commit=False,
            )
        db.session.commit()
        return kalem

    @classmethod
    def _iptal_gelecek_dondurmalar(cls, kalem, bitis_tarihi):
        """Erken sonlandırmada bitişten sonra başlayan dondurmaları iptal eder."""
        if not bitis_tarihi:
            return
        for kayit in list(kalem.dondurmalar or []):
            if kayit.baslangic_tarihi > bitis_tarihi:
                kayit.is_deleted = True
                kayit.is_active = False
                kayit.deleted_at = datetime.now(timezone.utc)
                db.session.add(kayit)

    @staticmethod
    def _dondur_iptal_kayit(kalem, kayit):
        yeni_bitis = kalem.kiralama_bitis - timedelta(days=kayit.muaf_gun_sayisi)
        bas = to_date(kalem.kiralama_baslangici)
        if bas and yeni_bitis < bas:
            raise ValidationError("Dondurma iptali bitiş tarihini başlangıçtan önceye çeker.")
        kalem.kiralama_bitis = yeni_bitis
        kayit.is_deleted = True
        kayit.is_active = False
        kayit.deleted_at = datetime.now(timezone.utc)
        db.session.add(kalem)
        db.session.add(kayit)

    @classmethod
    def _validate_dondurulabilir_kalem(cls, kalem):
        if not kalem or getattr(kalem, 'is_deleted', False):
            raise ValidationError("Kalem bulunamadı.")
        if not kalem.is_active:
            raise ValidationError("Sadece aktif kalemler dondurulabilir.")
        if kalem.sonlandirildi:
            raise ValidationError("Sonlandırılmış kalemler dondurulamaz.")

    @staticmethod
    def _dondurma_cakisma_var(bas, bit, kayitlar):
        for kayit in kayitlar or []:
            if bas <= kayit.bitis_tarihi and bit >= kayit.baslangic_tarihi:
                return True
        return False

    @classmethod
    def dondur_ekle(
        cls,
        kalem_id,
        baslangic_tarihi,
        bitis_tarihi,
        aciklama=None,
        tedarikci_alis_dondur=False,
        actor_id=None,
    ):
        kalem = cls.get_by_id(kalem_id)
        cls._validate_dondurulabilir_kalem(kalem)

        bas = to_date(baslangic_tarihi)
        bit = to_date(bitis_tarihi)
        if not bas or not bit:
            raise ValidationError("Geçerli başlangıç ve bitiş tarihi girilmelidir.")
        if bas > bit:
            raise ValidationError("Başlangıç tarihi bitişten sonra olamaz.")

        kalem_bas = to_date(kalem.kiralama_baslangici)
        if kalem_bas and bas < kalem_bas:
            raise ValidationError("Dondurma başlangıcı kiralama başlangıcından önce olamaz.")

        dondurulabilir = KiralamaService._dondurulabilir_bitis_tarihi(kalem)
        if dondurulabilir and bit > dondurulabilir:
            raise ValidationError(
                f"Dondurma bitişi {dondurulabilir.strftime('%d.%m.%Y')} tarihini aşamaz."
            )

        mevcut = list(kalem.dondurmalar or [])
        if cls._dondurma_cakisma_var(bas, bit, mevcut):
            raise ValidationError("Seçilen tarih aralığı mevcut dondurma ile çakışıyor.")

        if not kalem.is_dis_tedarik_ekipman:
            tedarikci_alis_dondur = False

        muaf_gun = KiralamaService._hesapla_gun_sayisi(bas, bit)
        kalem.kiralama_bitis = (kalem.kiralama_bitis or bit) + timedelta(days=muaf_gun)

        kayit = KiralamaKalemDondurma(
            kalem_id=kalem.id,
            baslangic_tarihi=bas,
            bitis_tarihi=bit,
            muaf_gun_sayisi=muaf_gun,
            aciklama=(aciklama or '').strip() or None,
            tedarikci_alis_dondur=bool(tedarikci_alis_dondur),
        )
        db.session.add(kayit)
        cls.save(kalem, is_new=False, auto_commit=False, actor_id=actor_id)

        KiralamaService.guncelle_cari_toplam(kalem.kiralama_id, auto_commit=False)
        if kalem.is_dis_tedarik_ekipman and kalem.harici_ekipman_tedarikci_id:
            KiralamaService.guncelle_tedarikci_cari_toplam(
                kalem.harici_ekipman_tedarikci_id,
                auto_commit=False,
            )
        db.session.commit()
        return kayit

    @classmethod
    def dondur_iptal(cls, dondurma_id, actor_id=None):
        kayit = db.session.get(KiralamaKalemDondurma, dondurma_id)
        if not kayit or kayit.is_deleted:
            raise ValidationError("Dondurma kaydı bulunamadı.")
        kalem = cls.get_by_id(kayit.kalem_id)
        cls._validate_dondurulabilir_kalem(kalem)

        cls._dondur_iptal_kayit(kalem, kayit)
        cls.save(kalem, is_new=False, auto_commit=False, actor_id=actor_id)

        KiralamaService.guncelle_cari_toplam(kalem.kiralama_id, auto_commit=False)
        if kalem.is_dis_tedarik_ekipman and kalem.harici_ekipman_tedarikci_id:
            KiralamaService.guncelle_tedarikci_cari_toplam(
                kalem.harici_ekipman_tedarikci_id,
                auto_commit=False,
            )
        db.session.commit()
        return kayit

    @classmethod
    def listele_dondurmalar(cls, kalem_id):
        kalem = cls.get_by_id(kalem_id)
        if not kalem:
            return []
        return sorted(
            kalem.dondurmalar or [],
            key=lambda d: (d.baslangic_tarihi, d.id),
        )

    @classmethod
    def validate_tarih_guncelle_koruma(cls, kalem, yeni_bitis):
        """Planlanan bitiş güncellemesinde dondurma koruması."""
        for kayit in kalem.dondurmalar or []:
            if yeni_bitis <= kayit.bitis_tarihi:
                if yeni_bitis >= kayit.baslangic_tarihi:
                    raise ValidationError(
                        f"Bitiş tarihi dondurma dönemine ({kayit.baslangic_tarihi.strftime('%d.%m.%Y')} - "
                        f"{kayit.bitis_tarihi.strftime('%d.%m.%Y')}) çekilemez."
                    )
                raise ValidationError(
                    f"Bitiş tarihi dondurma öncesine ({kayit.baslangic_tarihi.strftime('%d.%m.%Y')}) "
                    f"çekilemez."
                )

    @classmethod
    def iptal_et_sonlandirma(cls, kalem_id, actor_id=None):
        """Sonlandırmayı iptal eder ve makineyi tekrar kirada gösterir."""
        kalem = cls.get_by_id(kalem_id)
        if not kalem:
            raise ValidationError("İlgili kiralama kalemi bulunamadı.")

        # ÇAKIŞMA KORUMASI: Sonlandırma iptal edilmeden önce, bu kalemin ekipmanı
        # başka bir aktif kiralamada kullanılıyorsa işlemi engelle. Aksi halde aynı
        # makine iki kiralamada aynı anda 'kirada' görünür ve veri tutarsızlığı oluşur.
        if kalem.ekipman_id:
            cakisan = (
                KiralamaKalemi.query
                .join(Kiralama, KiralamaKalemi.kiralama_id == Kiralama.id)
                .filter(
                    KiralamaKalemi.ekipman_id == kalem.ekipman_id,
                    KiralamaKalemi.id != kalem.id,
                    KiralamaKalemi.is_active == True,
                    KiralamaKalemi.sonlandirildi == False,
                    KiralamaKalemi.is_deleted == False,
                )
                .first()
            )
            if cakisan:
                cakisan_form_no = cakisan.kiralama.kiralama_form_no if cakisan.kiralama else f"#{cakisan.kiralama_id}"
                makine_kod = kalem.ekipman.kod if kalem.ekipman else f"id={kalem.ekipman_id}"
                raise ValidationError(
                    f"Sonlandırma iptal edilemez: '{makine_kod}' makinesi şu an "
                    f"{cakisan_form_no} numaralı kiralamada aktif kullanımda."
                )

        kalem.sonlandirildi = False
        kalem.donus_nakliye_satis_fiyat = None  # Modalın bir sonraki açılışında form varsayını kullansın
        kalem.donus_is_harici_nakliye = False
        kalem.donus_nakliye_tedarikci_id = None
        kalem.donus_nakliye_alis_fiyat = None
        kalem.donus_nakliye_araci_id = None
        kalem.donus_nakliye_alis_kdv = None
        if kalem.ekipman:
            kalem.ekipman.calisma_durumu = 'kirada'

        # Sonlandırma sırasında açılmış taşeron ve nakliye farkı kayıtlarını geri al
        for kayit in HizmetKaydi.query.filter(
            HizmetKaydi.ozel_id == kalem.id,
            HizmetKaydi.yon == 'gelen',
            HizmetKaydi.aciklama.like('Dönüş Nakliye:%'),
            HizmetKaydi.is_deleted == False,
        ).all():
            _soft_delete_hizmet_kaydi(kayit)
        for kayit in HizmetKaydi.query.filter(
            HizmetKaydi.ozel_id == kalem.id,
            HizmetKaydi.aciklama.like('Müşteri Dönüş Nakliye Bedeli%'),
            HizmetKaydi.is_deleted == False,
        ).all():
            _soft_delete_hizmet_kaydi(kayit)
        for kayit in HizmetKaydi.query.filter(
            HizmetKaydi.ozel_id == kalem.id,
            HizmetKaydi.aciklama.like('Nakliye Farkı%'),
            HizmetKaydi.is_deleted == False,
        ).all():
            _soft_delete_hizmet_kaydi(kayit)

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
    UNDO_WINDOW_SECONDS = 60

    # KUR ÖNBELLEKLEME İÇİN SINIF DEĞİŞKENLERİ
    _cache_suresi_dakika = 60

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
    def _fetch_tcmb_kurlari(cls):
        """TCMB'den kur çekme işlemi (ağ erişimi)."""
        rates = {'USD': Decimal('0.00'), 'EUR': Decimal('0.00')}
        url = "https://www.tcmb.gov.tr/kurlar/today.xml"
        verify = _tcmb_request_verify()
        timeout = _tcmb_request_timeout()
        headers = {
            "User-Agent": "KiralamaApp/1.0 (TCMB kur; +https://www.tcmb.gov.tr)",
            "Accept": "application/xml, text/xml, */*;q=0.8",
        }
        response = requests.get(
            url,
            headers=headers,
            verify=verify,
            timeout=timeout,
        )
        response.raise_for_status()
        root = ET.fromstring(response.content)
        usd = root.find("./Currency[@CurrencyCode='USD']/ForexSelling")
        eur = root.find("./Currency[@CurrencyCode='EUR']/ForexSelling")
        if usd is not None and usd.text:
            rates['USD'] = Decimal(str(usd.text).replace(',', '.'))
        if eur is not None and eur.text:
            rates['EUR'] = Decimal(str(eur.text).replace(',', '.'))
        return rates

    @classmethod
    def refresh_tcmb_kurlari(cls, force=False):
        """TCMB kurlarını ortak veritabanına atomik olarak kaydeder."""
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        last_updated = cls.get_kur_son_guncelleme()
        if not force and last_updated and now - last_updated < timedelta(minutes=cls._cache_suresi_dakika):
            return cls.get_tcmb_kurlari()
        try:
            rates = cls._fetch_tcmb_kurlari()
            if any(rates.get(code, Decimal('0')) <= 0 for code in ('USD', 'EUR')):
                raise ValueError('TCMB yanıtında USD/EUR satış kuru bulunamadı.')
        except Exception as exc:
            db.session.rollback()
            logger.warning("TCMB kur verisi alinamadi; son gecerli kurlar korunuyor: %s", exc)
            raise ExchangeRateRefreshError('TCMB kur verisi alinamadi.') from exc

        try:
            for currency in ('USD', 'EUR'):
                row = db.session.get(ExchangeRate, currency)
                if row is None:
                    row = ExchangeRate(currency=currency)
                    db.session.add(row)
                row.selling_rate = rates[currency]
                row.source = 'TCMB'
                row.fetched_at = now
            db.session.commit()
            return rates
        except SQLAlchemyError as exc:
            db.session.rollback()
            logger.exception("TCMB kurlari ortak veritabanina kaydedilemedi.")
            raise ExchangeRateRefreshError('TCMB kurlari kaydedilemedi.') from exc

    @classmethod
    def get_tcmb_kurlari(cls):
        """Son başarılı USD/EUR kurlarını ortak veritabanından okur."""
        try:
            rows = ExchangeRate.query.filter(ExchangeRate.currency.in_(('USD', 'EUR'))).all()
        except SQLAlchemyError as exc:
            db.session.rollback()
            logger.exception("Ortak kur tablosu okunamadi.")
            raise ExchangeRateUnavailableError('Kur verisi okunamadi.') from exc

        result = {
            row.currency: Decimal(row.selling_rate)
            for row in rows
            if row.currency in ('USD', 'EUR') and Decimal(row.selling_rate) > 0
        }
        missing = [code for code in ('USD', 'EUR') if code not in result]
        if missing:
            raise ExchangeRateUnavailableError(
                f"Kur verisi henuz hazir degil: {', '.join(missing)}."
            )
        return result

    @classmethod
    def get_kur_son_guncelleme(cls):
        """Ortak kur tablosundaki son güncelleme zamanını döndürür."""
        try:
            return db.session.query(db.func.max(ExchangeRate.fetched_at)).scalar()
        except SQLAlchemyError as exc:
            db.session.rollback()
            logger.exception("Kur son guncelleme zamani okunamadi.")
            raise ExchangeRateUnavailableError('Kur guncelleme bilgisi okunamadi.') from exc

    @classmethod
    def get_kur_son_guncelleme_text(cls):
        """Kur cache zamanini Turkiye saatiyle ekranda gosterilecek metne cevirir."""
        son = cls.get_kur_son_guncelleme()
        if not son:
            return 'Henüz güncellenmedi'
        if son.tzinfo is None:
            son = son.replace(tzinfo=timezone.utc)
        son = son.astimezone(TURKIYE_TZ)
        return son.strftime('%d.%m.%Y %H:%M:%S')

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
    def _swap_reason_for_kalem(kalem):
        """Kalemin swap nedenini tek kaynaktan çözer; legacy kalemlerde None döner."""
        from app.makinedegisim.models import MakineDegisim

        if not kalem or not kalem.id:
            return None
        degisim = MakineDegisim.query.filter(
            MakineDegisim.is_deleted == False,
            db.or_(
                MakineDegisim.eski_kalem_id == kalem.id,
                MakineDegisim.yeni_kalem_id == kalem.id,
            ),
        ).order_by(MakineDegisim.id.desc()).first()
        return (degisim.neden or '').strip().lower() if degisim else None

    @classmethod
    def _soft_delete_donus_nakliye_artifacts(cls, kalem):
        """Kaleme bağlı dönüş seferi ve cari kayıtlarını transaction içinde kapatır."""
        if not kalem or not kalem.kiralama:
            return 0

        form_no = kalem.kiralama.kiralama_form_no or ''
        seferler = Nakliye.query.filter(
            Nakliye.kiralama_id == kalem.kiralama_id,
            Nakliye.aciklama == f"Dönüş: {form_no} #{kalem.id}",
            Nakliye.is_active == True,
        ).all()
        kapatilan = 0
        nakliye_ids = {sefer.id for sefer in seferler}
        for sefer in seferler:
            sefer.is_active = False
            db.session.add(sefer)
            kapatilan += 1

        cari_kayitlari = HizmetKaydi.query.filter(
            HizmetKaydi.is_deleted == False,
            db.or_(
                HizmetKaydi.nakliye_id.in_(nakliye_ids or {-1}),
                and_(
                    HizmetKaydi.ozel_id == kalem.id,
                    HizmetKaydi.aciklama.like('Dönüş Nakliye:%'),
                ),
            ),
        ).all()
        for kayit in cari_kayitlari:
            _soft_delete_hizmet_kaydi(kayit)
            kapatilan += 1
        return kapatilan

    @classmethod
    def reconcile_swap_donus_nakliye(cls, kalem, neden=None, explicit_sales=None):
        """Swap politikasına göre eski kalemin dönüş hareketini reconcile eder.

        Pozitif swap ekranı bedeli yeni swap seferinde tutulur; eski dönüş seferi
        bununla birlikte kapatılır. Arıza/periyodik swaplar müşteri dönüşünü
        bedelsiz bırakır. Müşteri talebi swaplarında mevcut ücretli dönüş korunur.
        """
        reason = (neden or cls._swap_reason_for_kalem(kalem) or '').strip().lower()
        explicit_sales = to_decimal(explicit_sales)
        if explicit_sales > 0 or reason in ('serviste', 'periyodik', 'bakimda'):
            return cls._soft_delete_donus_nakliye_artifacts(kalem)
        return 0

    @classmethod
    def reconcile_donus_nakliye_policy(cls, kalem):
        """Form güncellemesinde dönüş seferini güncel fiyat politikasına uyarlar."""
        reason = cls._swap_reason_for_kalem(kalem)
        if reason in ('serviste', 'periyodik', 'bakimda'):
            return cls._soft_delete_donus_nakliye_artifacts(kalem)
        if reason == 'bosta':
            # Müşteri talebi swapında daha önce açıkça oluşturulmuş ücret korunur.
            return 0
        if kalem.sonlandirildi and cls._get_donus_nakliye_satis(kalem) <= 0:
            return cls._soft_delete_donus_nakliye_artifacts(kalem)
        return 0

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
            referans_tarih = _bugun()

        if bas > referans_tarih:
            return Decimal('0.00')

        # sonlandirildi=True → makine iade edildi, sözleşme bitişine kadar hesapla
        # sonlandirildi=False → makine hâlâ dışarıda, bugüne kadar tahakkuk et
        #   (bitiş tarihi geçmiş olsa bile devam eder)
        ust_sinir = bit if kalem.sonlandirildi else referans_tarih
        if ust_sinir < bas:
            return Decimal('0.00')

        gun = KiralamaService.hesapla_kalem_etkin_gun(kalem, referans_tarih=referans_tarih)
        kira_tahakkuk = to_decimal(kalem.kiralama_brm_fiyat) * Decimal(gun)
        return kira_tahakkuk

    @staticmethod
    def _hesapla_sozlesme_kalem_tutari(kalem):
        """Kalem için toplam sozlesme kira tutarini hesaplar (nakliye ayrı kaydedilir)."""
        bas = to_date(kalem.kiralama_baslangici)
        bit = to_date(kalem.kiralama_bitis)
        if not (bas and bit) or bit < bas:
            return Decimal('0.00')

        gun = KiralamaService.hesapla_kalem_etkin_gun(kalem, tam_sozlesme=True)
        kira_toplam = to_decimal(kalem.kiralama_brm_fiyat) * Decimal(gun)
        return kira_toplam

    @staticmethod
    def _hesapla_bekleyen_alis_kalem_tutari(kalem, referans_tarih=None):
        """Dış tedarikçi için bugüne kadar tahakkuk eden alış tutarını hesaplar.
        Müşteri tarafıyla birebir aynı mantık kullanılır:
          - bas > referans → 0 (henüz başlamamış)
          - sonlandirildi=True → bit'e kadar tam süre (makine iade edildi)
          - sonlandirildi=False → bugüne kadar tahakkuk et (makine hâlâ dışarıda)
        """
        bas = to_date(kalem.kiralama_baslangici)
        bit = to_date(kalem.kiralama_bitis)
        if not (bas and bit):
            return Decimal('0.00')
        if referans_tarih is None:
            referans_tarih = _bugun()
        if bas > referans_tarih:
            return Decimal('0.00')
        ust_sinir = bit if kalem.sonlandirildi else referans_tarih
        if ust_sinir < bas:
            return Decimal('0.00')
        gun = KiralamaService.hesapla_kalem_etkin_gun(
            kalem, referans_tarih=referans_tarih, alis_tarafi=True,
        )
        return to_decimal(kalem.kiralama_alis_fiyat) * Decimal(gun)

    @staticmethod
    def hesapla_hizmet_kaydi_canli_tutari(hizmet_kaydi, referans_tarih=None):
        """HizmetKaydi için CANLI (on-the-fly) tahakkuk tutarını döner.

        'Kiralama Bekleyen Bakiye' kayıtları → bağlı kiralamanın tüm kalemleri
        üzerinden bugüne kadar tahakkuk eden müşteri alacağını yeniden hesaplar.

        'Dış Kiralama' kayıtları → bağlı kalem üzerinden bugüne kadar tahakkuk
        eden tedarikçi borcunu yeniden hesaplar.

        Diğer kayıtlar (fatura, nakliye vb.) → DB'deki sabit tutar döner.

        Böylece gün geçtikçe stored değerler bayatlasa bile ekranda her zaman
        güncel bekleyen tahakkuk görünür. İleri tarihli kontratlarda başlangıç
        tarihi geldiğinde tahakkuk otomatik olarak doğru hesaplanmaya başlar.
        """
        aciklama = (hizmet_kaydi.aciklama or '').strip()
        ozel_id  = getattr(hizmet_kaydi, 'ozel_id', None)

        if ozel_id and aciklama.startswith('Kiralama Bekleyen Bakiye'):
            kiralama_obj = db.session.get(Kiralama, ozel_id)
            if kiralama_obj:
                toplam = Decimal('0.00')
                for kalem in kiralama_obj.kalemler:
                    if getattr(kalem, 'is_deleted', False):
                        continue
                    k_tutar = KiralamaService._hesapla_bekleyen_kalem_tutari(kalem, referans_tarih)
                    toplam += k_tutar
                return toplam

        if ozel_id and aciklama.startswith('Dış Kiralama'):
            kalem_obj = db.session.get(KiralamaKalemi, ozel_id)
            if kalem_obj and not getattr(kalem_obj, 'is_deleted', False):
                return KiralamaService._hesapla_bekleyen_alis_kalem_tutari(kalem_obj, referans_tarih)

        return hizmet_kaydi.tutar or Decimal('0.00')

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
    def _get_dondurma_kayitlari(kalem, alis_tarafi=False):
        kayitlar = list(getattr(kalem, 'dondurmalar', None) or [])
        if not alis_tarafi:
            return kayitlar
        return [k for k in kayitlar if k.tedarikci_alis_dondur]

    @staticmethod
    def _dondurma_kesisim_gunleri(bas, bit, kayitlar):
        """Verilen aralık ile çakışan dondurma günlerini birleştirip sayar."""
        if not (bas and bit) or bit < bas or not kayitlar:
            return 0

        araliklar = []
        for kayit in kayitlar:
            k_bas = max(bas, kayit.baslangic_tarihi)
            k_bit = min(bit, kayit.bitis_tarihi)
            if k_bas <= k_bit:
                araliklar.append((k_bas, k_bit))

        if not araliklar:
            return 0

        araliklar.sort(key=lambda x: x[0])
        birlesik = [araliklar[0]]
        for k_bas, k_bit in araliklar[1:]:
            son_bas, son_bit = birlesik[-1]
            if k_bas <= son_bit + timedelta(days=1):
                birlesik[-1] = (son_bas, max(son_bit, k_bit))
            else:
                birlesik.append((k_bas, k_bit))

        return sum(KiralamaService._hesapla_gun_sayisi(a, b) for a, b in birlesik)

    @staticmethod
    def _hesapla_etkin_gun_sayisi(bas, bit, kayitlar, alis_tarafi=False):
        toplam = KiralamaService._hesapla_gun_sayisi(bas, bit)
        if toplam <= 0:
            return 0
        filt = kayitlar
        if alis_tarafi:
            filt = [k for k in (kayitlar or []) if k.tedarikci_alis_dondur]
        muaf = KiralamaService._dondurma_kesisim_gunleri(bas, bit, filt)
        return max(toplam - muaf, 0)

    @staticmethod
    def _dondurulabilir_bitis_tarihi(kalem):
        bit = to_date(kalem.kiralama_bitis)
        if not bit:
            return None
        toplam_muaf = sum(
            (k.muaf_gun_sayisi or 0) for k in (kalem.dondurmalar or [])
        )
        return bit - timedelta(days=toplam_muaf)

    @staticmethod
    def hesapla_kalem_etkin_gun(kalem, referans_tarih=None, alis_tarafi=False, tam_sozlesme=False):
        """Kalem için ücretli (dondurma hariç) gün sayısı."""
        bas = to_date(kalem.kiralama_baslangici)
        bit = to_date(kalem.kiralama_bitis)
        if not (bas and bit):
            return 0

        if tam_sozlesme:
            ust_sinir = bit
        else:
            if referans_tarih is None:
                referans_tarih = _bugun()
            if bas > referans_tarih:
                return 0
            ust_sinir = bit if kalem.sonlandirildi else referans_tarih

        if ust_sinir < bas:
            return 0

        kayitlar = KiralamaService._get_dondurma_kayitlari(kalem, alis_tarafi=alis_tarafi)
        return KiralamaService._hesapla_etkin_gun_sayisi(bas, ust_sinir, kayitlar, alis_tarafi=alis_tarafi)

    @staticmethod
    def toplam_muaf_gun_sayisi(kalem, alis_tarafi=False):
        kayitlar = KiralamaService._get_dondurma_kayitlari(kalem, alis_tarafi=alis_tarafi)
        return sum((k.muaf_gun_sayisi or 0) for k in kayitlar)

    @staticmethod
    def kalem_dondurma_aktif_mi(kalem, referans_tarih=None, *, alis_tarafi=False):
        """Referans tarih bir dondurma aralığı içindeyse True döner."""
        ref = referans_tarih or _bugun()
        for kayit in KiralamaService._get_dondurma_kayitlari(kalem, alis_tarafi=alis_tarafi):
            if kayit.baslangic_tarihi <= ref <= kayit.bitis_tarihi:
                return True
        return False

    @staticmethod
    def _hesapla_kalem_satis_tutari(bas, bit, kiralama_brm_fiyat, nakliye_satis_fiyat, kayitlar=None):
        """
        Kalem için satış tutarını backend'de YENIDEN HESAPLAR (DOĞRULUK KAYNAĞIDIR).
        Frontend'den gelen tutar KABUL EDİLMEZ.

        Formül:
          gun = bitis - baslangic + 1 - muaf
          toplam = gun * kiralama_brm_fiyat + nakliye_satis_fiyat
        """
        gun = KiralamaService._hesapla_etkin_gun_sayisi(bas, bit, kayitlar or [])
        if gun <= 0:
            return Decimal('0.00')
        kiralama_tutari = to_decimal(kiralama_brm_fiyat) * Decimal(gun)
        nakliye_tutari = to_decimal(nakliye_satis_fiyat)
        return kiralama_tutari + nakliye_tutari

    @staticmethod
    def guncelle_cari_toplam(kiralama_id, auto_commit=True, sync_firma_cache=True):
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
                _soft_delete_hizmet_kaydi(kayit)

        toplam_tahakkuk = Decimal('0.00')
        toplam_sozlesme = Decimal('0.00')
        for kalem in kiralama.kalemler:
            if getattr(kalem, 'is_deleted', False):
                continue
            toplam_tahakkuk += KiralamaService._hesapla_bekleyen_kalem_tutari(kalem)
            toplam_sozlesme += KiralamaService._hesapla_sozlesme_kalem_tutari(kalem)

        # Kiralamaya ait cari kaydı her zaman aç (0 TL bile olsa)
        # Kiralama başladığında tutarı otomatik güncellenecek
        toplam_gelir = toplam_tahakkuk if toplam_tahakkuk > 0 else Decimal('0.00')

        if True:  # Her zaman cari kaydını aç/güncelle
            if not cari_kayit:
                kdv_orani = getattr(kiralama, 'kdv_orani', None)
                if kdv_orani is None:
                    kdv_orani = 0
                cari_kayit = HizmetKaydi(
                    firma_id=kiralama.firma_musteri_id,
                    tarih=date.today(),
                    islem_tarihi=date.today(),
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
                cari_kayit.islem_tarihi = date.today()
                cari_kayit.tutar = toplam_gelir
                cari_kayit.kdv_orani = kdv_orani
                cari_kayit.aciklama = f"Kiralama Bekleyen Bakiye - {kiralama.kiralama_form_no}"

            db.session.add(cari_kayit)
        else:
            # toplam_gelir = 0 ama cari_kayit varsa, 0 TL olarak güncelle
            # (Kiralama başlamadığında 0 TL, başladığında tutarı otomatik güncellenecek)
            if cari_kayit:
                cari_kayit.tutar = Decimal('0.00')
                db.session.add(cari_kayit)

        # Kiralamaya bağlı nakliye HizmetKaydi'lerini ayrı olarak senkronize et
        from app.services.nakliye_services import CariServis as NakliyeCariServis
        db.session.flush()
        nakliyeler = Nakliye.query.filter_by(kiralama_id=kiralama.id).all()
        for nakliye in nakliyeler:
            NakliyeCariServis.musteri_nakliye_senkronize_et(nakliye)

        if sync_firma_cache and kiralama.firma_musteri_id:
            # Tahakkuk ve firma cache'i ayni transaction icinde yenilenmelidir.
            KiralamaService._sync_firma_balances({kiralama.firma_musteri_id})

        if auto_commit:
            try:
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                logger.error(f"Cari Toplam Güncelleme Commit Hatası: {e}")
                raise ValidationError("Finansal kayıt güncellenemedi.")

    @classmethod
    def sync_all_cari_totals(cls):
        """Acik kiralamalarin tahakkuk ve firma cache'lerini topluca yeniler."""
        kiralamalar = Kiralama.query.filter(
            Kiralama.is_deleted == False,
            Kiralama.is_active == True,
        ).order_by(Kiralama.id.asc()).all()
        affected_firma_ids = set()
        supplier_firma_ids = {
            firma_id for (firma_id,) in db.session.query(
                KiralamaKalemi.harici_ekipman_tedarikci_id
            ).join(Kiralama, KiralamaKalemi.kiralama_id == Kiralama.id).filter(
                KiralamaKalemi.harici_ekipman_tedarikci_id.isnot(None),
                KiralamaKalemi.is_active == True,
                KiralamaKalemi.is_deleted == False,
                Kiralama.is_active == True,
                Kiralama.is_deleted == False,
            ).distinct().all()
        }

        for kiralama in kiralamalar:
            cls.guncelle_cari_toplam(
                kiralama.id,
                auto_commit=False,
                sync_firma_cache=False,
            )
            if kiralama.firma_musteri_id:
                affected_firma_ids.add(kiralama.firma_musteri_id)

        supplier_dedupe = 0
        for firma_id in sorted(supplier_firma_ids):
            result = cls.guncelle_tedarikci_cari_toplam(
                firma_id,
                auto_commit=False,
                sync_firma_cache=False,
            ) or {}
            supplier_dedupe += int(result.get('dedupe_sayisi', 0))

        affected_firma_ids.update(supplier_firma_ids)
        cls._sync_firma_balances(affected_firma_ids)
        db.session.commit()
        return {
            'kiralama_sayisi': len(kiralamalar),
            'firma_sayisi': len(affected_firma_ids),
            'tedarikci_sayisi': len(supplier_firma_ids),
            'tedarikci_dedupe_sayisi': supplier_dedupe,
        }

    @classmethod
    def validate_chain_date_range(cls, kalem, baslangic, bitis):
        """Ayni swap zincirinde tarih araligi cakismasini engeller."""
        if not baslangic or not bitis or baslangic > bitis:
            raise ValidationError("Kiralama tarih araligi gecersiz.")
        chain_id = kalem.chain_id or kalem.id
        conflict = KiralamaKalemi.query.filter(
            KiralamaKalemi.chain_id == chain_id,
            KiralamaKalemi.id != kalem.id,
            KiralamaKalemi.is_deleted == False,
            KiralamaKalemi.kiralama_baslangici <= bitis,
            KiralamaKalemi.kiralama_bitis >= baslangic,
        ).first()
        if conflict:
            raise ValidationError(
                f"Swap zincirinde tarih cakismasi var: kalem #{conflict.id}."
            )

    @staticmethod
    def _guncelle_tedarikci_cari_toplam_v2(
        firma_id,
        auto_commit=True,
        sync_firma_cache=True,
    ):
        if not firma_id:
            return {'kalem_sayisi': 0, 'dedupe_sayisi': 0}
        from app.makinedegisim.models import MakineDegisim

        aktif_kalemler = KiralamaKalemi.query.filter(
            KiralamaKalemi.harici_ekipman_tedarikci_id == firma_id,
            KiralamaKalemi.is_active == True,
            KiralamaKalemi.is_deleted == False,
        ).all()
        linked_ids = {
            hizmet_id for (hizmet_id,) in db.session.query(
                MakineDegisim.swap_kira_hizmet_id
            ).filter(
                MakineDegisim.swap_kira_hizmet_id.isnot(None),
                MakineDegisim.is_deleted == False,
            ).all()
        }
        dedupe_sayisi = 0

        for kalem in aktif_kalemler:
            kir = kalem.kiralama
            if not kir or kir.is_deleted:
                continue

            mevcut = HizmetKaydi.query.filter(
                HizmetKaydi.ozel_id == kalem.id,
                HizmetKaydi.firma_id == firma_id,
                HizmetKaydi.yon == 'gelen',
                HizmetKaydi.is_deleted == False,
            ).order_by(HizmetKaydi.id.asc()).all()
            sistem = [
                kayit for kayit in mevcut
                if kayit.id in linked_ids
                or kayit.kaynak in ('dis_kiralama_tahakkuk', 'swap_dis_kiralama')
                or (kayit.aciklama or '').startswith(('Dış Kiralama', 'Dis Kiralama'))
            ]
            canonical = next(
                (kayit for kayit in sistem if kayit.kaynak == 'dis_kiralama_tahakkuk'),
                None,
            ) or next((kayit for kayit in sistem if kayit.id in linked_ids), None)
            if canonical is None and sistem:
                canonical = sistem[0]

            for kayit in sistem:
                if canonical is None or kayit.id != canonical.id:
                    _soft_delete_hizmet_kaydi(kayit)
                    dedupe_sayisi += 1
            if dedupe_sayisi and sistem:
                db.session.flush()

            tahakkuk = KiralamaService._hesapla_bekleyen_alis_kalem_tutari(kalem)
            makine_adi = kalem.harici_ekipman_marka or "Dış Ekipman"
            bas = to_date(kalem.kiralama_baslangici) or date.today()
            if canonical is None:
                canonical = HizmetKaydi(
                    firma_id=firma_id,
                    tarih=date.today(),
                    islem_tarihi=bas,
                    tutar=tahakkuk,
                    yon='gelen',
                    fatura_no=kir.kiralama_form_no,
                    ozel_id=kalem.id,
                    aciklama=f"Dış Kiralama (Güncelleme): {makine_adi}",
                    kaynak='dis_kiralama_tahakkuk',
                    kdv_orani=kalem.kiralama_alis_kdv,
                    kiralama_alis_kdv=kalem.kiralama_alis_kdv,
                    nakliye_alis_kdv=kalem.nakliye_alis_kdv,
                )
            else:
                canonical.firma_id = firma_id
                canonical.tarih = date.today()
                canonical.islem_tarihi = bas
                canonical.tutar = tahakkuk
                canonical.yon = 'gelen'
                canonical.fatura_no = kir.kiralama_form_no
                canonical.ozel_id = kalem.id
                canonical.aciklama = f"Dış Kiralama (Güncelleme): {makine_adi}"
                canonical.kaynak = 'dis_kiralama_tahakkuk'
                canonical.is_deleted = False
                canonical.is_active = True
                canonical.deleted_at = None
                canonical.kdv_orani = kalem.kiralama_alis_kdv
                canonical.kiralama_alis_kdv = kalem.kiralama_alis_kdv
                canonical.nakliye_alis_kdv = kalem.nakliye_alis_kdv
            db.session.add(canonical)

        if sync_firma_cache:
            KiralamaService._sync_firma_balances({firma_id})
        if auto_commit:
            db.session.commit()
        return {'kalem_sayisi': len(aktif_kalemler), 'dedupe_sayisi': dedupe_sayisi}

    @staticmethod
    def guncelle_tedarikci_cari_toplam(
        firma_id,
        auto_commit=True,
        sync_firma_cache=True,
    ):
        """Firma tedarikçi olarak bağlı olduğu aktif harici kiralama kalemlerinin
        'Dış Kiralama' HKD kayıtlarını bugüne kadar tahakkuk eden tutarla günceller.
        guncelle_cari_toplam'ın müşteri versiyonunun TEDARİKÇİ karşılığıdır."""
        if not firma_id:
            return {'kalem_sayisi': 0, 'dedupe_sayisi': 0}
        return KiralamaService._guncelle_tedarikci_cari_toplam_v2(
            firma_id,
            auto_commit=auto_commit,
            sync_firma_cache=sync_firma_cache,
        )
        aktif_kalemler = KiralamaKalemi.query.filter(
            KiralamaKalemi.harici_ekipman_tedarikci_id == firma_id,
            KiralamaKalemi.is_active == True,
            KiralamaKalemi.is_deleted == False,
        ).all()

        for kalem in aktif_kalemler:
            kir = kalem.kiralama
            if not kir or kir.is_deleted:
                continue

            mevcut_kayitlar = HizmetKaydi.query.filter(
                HizmetKaydi.ozel_id == kalem.id,
                HizmetKaydi.firma_id == firma_id,
                HizmetKaydi.yon == 'gelen',
                HizmetKaydi.is_deleted == False,
                db.or_(
                    HizmetKaydi.aciklama.like('Dış Kiralama%'),
                    HizmetKaydi.aciklama.like('Dis Kiralama%'),
                ),
            ).order_by(HizmetKaydi.id.asc()).all()

            cari_kayit = mevcut_kayitlar[0] if mevcut_kayitlar else None
            for fazla in mevcut_kayitlar[1:]:
                _soft_delete_hizmet_kaydi(fazla)

            tahakkuk = KiralamaService._hesapla_bekleyen_alis_kalem_tutari(kalem)
            makine_adi = kalem.harici_ekipman_marka or "Dış Ekipman"
            bas = to_date(kalem.kiralama_baslangici) or date.today()

            if cari_kayit:
                cari_kayit.tutar = tahakkuk
                cari_kayit.tarih = date.today()
                cari_kayit.islem_tarihi = bas
                cari_kayit.kdv_orani = kalem.kiralama_alis_kdv
                cari_kayit.kiralama_alis_kdv = kalem.kiralama_alis_kdv
                cari_kayit.nakliye_alis_kdv = kalem.nakliye_alis_kdv
                cari_kayit.aciklama = f"Dış Kiralama (Güncelleme): {makine_adi}"
                db.session.add(cari_kayit)
            else:
                yeni = HizmetKaydi(
                    firma_id=firma_id,
                    tarih=date.today(),
                    islem_tarihi=bas,
                    tutar=tahakkuk,
                    yon='gelen',
                    fatura_no=kir.kiralama_form_no,
                    ozel_id=kalem.id,
                    aciklama=f"Dış Kiralama (Güncelleme): {makine_adi}",
                    kdv_orani=kalem.kiralama_alis_kdv,
                    kiralama_alis_kdv=kalem.kiralama_alis_kdv,
                    nakliye_alis_kdv=kalem.nakliye_alis_kdv,
                )
                db.session.add(yeni)

        if auto_commit:
            try:
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                logger.error(f"Tedarikçi Cari Toplam Güncelleme Commit Hatası: {e}")

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
                    dis_kiralama_hizmet = None
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
                        if kalem.harici_ekipman_tedarikci_id > 0:
                            ust_sinir = bit if kalem.sonlandirildi else min(bit, _bugun())
                            gun = cls._hesapla_gun_sayisi(bas, ust_sinir)
                            tedarikci_id = kalem.harici_ekipman_tedarikci_id if kalem.harici_ekipman_tedarikci_id and kalem.harici_ekipman_tedarikci_id > 0 else kalem.nakliye_tedarikci_id
                            logger.debug(f"[CREATE] Dış ekipman/nakliye HizmetKaydi ekleniyor: tedarikci_id={tedarikci_id}, tutar={kalem.kiralama_alis_fiyat * gun}, kdv_orani={kalem.kiralama_alis_kdv}, nakliye_alis_kdv={kalem.nakliye_alis_kdv}")
                            hizmet_kaydi = HizmetKaydi(
                                firma_id=tedarikci_id,
                                tarih=date.today(),
                                islem_tarihi=bas,
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
                            dis_kiralama_hizmet = hizmet_kaydi
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
                    if kalem.chain_id is None:
                        kalem.chain_id = kalem.id
                        db.session.add(kalem)
                    if dis_kiralama_hizmet is not None and not getattr(dis_kiralama_hizmet, 'ozel_id', None):
                        # Kalem ID'si flush sonrası belli olur; kayıt kiralama ile bağlansın.
                        dis_kiralama_hizmet.ozel_id = kalem.id
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
            for kayit in HizmetKaydi.query.filter_by(
                fatura_no=kiralama.kiralama_form_no,
            ).filter(HizmetKaydi.is_deleted == False).all():
                _soft_delete_hizmet_kaydi(kayit)
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
                is_kapatilmis_mevcut = (not is_yeni) and (bool(orijinal_sonlandirildi) or not bool(aktif.is_active))

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
                _donus_h = int(k_data.get('donus_is_harici_nakliye') or 0) == 1
                aktif.donus_is_harici_nakliye = _donus_h
                if _donus_h:
                    aktif.donus_nakliye_tedarikci_id = int(k_data.get('donus_nakliye_tedarikci_id') or 0) or None
                    aktif.donus_nakliye_alis_fiyat = to_decimal(k_data.get('donus_nakliye_alis_fiyat'))
                    aktif.donus_nakliye_alis_kdv = to_int_or_none(k_data.get('donus_nakliye_alis_kdv'))
                    aktif.donus_nakliye_araci_id = None
                else:
                    aktif.donus_nakliye_tedarikci_id = None
                    aktif.donus_nakliye_alis_fiyat = None
                    aktif.donus_nakliye_alis_kdv = None
                    aktif.donus_nakliye_araci_id = int(k_data.get('donus_nakliye_araci_id') or 0) or None

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
                            makine_adi = ekip.kod
                            if not is_kapatilmis_mevcut:
                                ekip.calisma_durumu = 'kirada'
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

                    if aktif.harici_ekipman_tedarikci_id > 0:
                        ust_sinir = bit if aktif.sonlandirildi else min(bit, _bugun())
                        gun = cls._hesapla_gun_sayisi(bas, ust_sinir)
                        db.session.add(HizmetKaydi(
                            firma_id=aktif.harici_ekipman_tedarikci_id, tarih=date.today(),
                            islem_tarihi=bas,
                            tutar=(aktif.kiralama_alis_fiyat * gun), yon='gelen',
                            fatura_no=kiralama.kiralama_form_no, ozel_id=aktif.id, aciklama=f"Dış Kiralama (Güncelleme): {makine_adi}",
                            kdv_orani=aktif.kiralama_alis_kdv,
                            kiralama_alis_kdv=aktif.kiralama_alis_kdv,
                            nakliye_alis_kdv=aktif.nakliye_alis_kdv
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

                if (
                    to_decimal(aktif.nakliye_satis_fiyat) > 0
                    or to_decimal(aktif.nakliye_alis_fiyat) > 0
                    or getattr(aktif, 'sonlandirildi', False)
                ):
                    cls._create_nakliye_ve_cari(kiralama, aktif, makine_adi, bas)
                    if (
                        aktif.sonlandirildi
                        and aktif.donus_is_harici_nakliye
                        and aktif.donus_nakliye_tedarikci_id
                        and to_decimal(aktif.donus_nakliye_alis_fiyat) > 0
                    ):
                        db.session.add(HizmetKaydi(
                            firma_id=aktif.donus_nakliye_tedarikci_id,
                            tarih=aktif.kiralama_bitis or date.today(),
                            islem_tarihi=aktif.kiralama_bitis or date.today(),
                            tutar=to_decimal(aktif.donus_nakliye_alis_fiyat),
                            yon='gelen',
                            fatura_no=kiralama.kiralama_form_no,
                            ozel_id=aktif.id,
                            aciklama=f"Dönüş Nakliye: {makine_adi}",
                            kdv_orani=None,
                            nakliye_alis_kdv=aktif.donus_nakliye_alis_kdv,
                        ))

            # Form güncellemesi dönüş seferlerini körlemesine korumaz; swap
            # nedeni ve güncel ücret politikasına göre eski hareketleri kapatır.
            for policy_kalem in list(kiralama.kalemler):
                if not policy_kalem.is_deleted:
                    cls.reconcile_donus_nakliye_policy(policy_kalem)

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

    @staticmethod
    def _normalize_utc(dt_value):
        if dt_value is None:
            return None
        if dt_value.tzinfo is None:
            return dt_value.replace(tzinfo=timezone.utc)
        return dt_value.astimezone(timezone.utc)

    @classmethod
    def _deleted_at_matches(cls, record_deleted_at, target_deleted_at, tolerance_seconds=2):
        record_dt = cls._normalize_utc(record_deleted_at)
        target_dt = cls._normalize_utc(target_deleted_at)
        if record_dt is None or target_dt is None:
            return False
        return abs((record_dt - target_dt).total_seconds()) <= tolerance_seconds

    @classmethod
    def _soft_delete_instance(cls, instance, actor_id=None, deleted_at=None):
        if getattr(instance, 'is_deleted', False):
            return
        deleted_at = deleted_at or datetime.now(timezone.utc)
        instance.is_deleted = True
        if hasattr(instance, 'is_active'):
            instance.is_active = False
        if hasattr(instance, 'deleted_at'):
            instance.deleted_at = deleted_at
        if actor_id and hasattr(instance, 'deleted_by_id'):
            instance.deleted_by_id = actor_id
        db.session.add(instance)

    @classmethod
    def _restore_instance(cls, instance, state=None):
        state = state or {}
        instance.is_deleted = state.get('is_deleted', False)
        if hasattr(instance, 'is_active'):
            instance.is_active = state.get('is_active', True)
        if hasattr(instance, 'deleted_at'):
            instance.deleted_at = cls._parse_snapshot_datetime(state.get('deleted_at'))
        if hasattr(instance, 'deleted_by_id'):
            instance.deleted_by_id = state.get('deleted_by_id')
        db.session.add(instance)

    @staticmethod
    def undo_session_key(kiralama_id):
        return f"kiralama_undo_snapshot:{kiralama_id}"

    @staticmethod
    def _snapshot_datetime(value):
        if value is None:
            return None
        if hasattr(value, 'isoformat'):
            return value.isoformat()
        return str(value)

    @classmethod
    def _parse_snapshot_datetime(cls, value):
        if not value:
            return None
        if isinstance(value, datetime):
            return value
        try:
            return datetime.fromisoformat(value)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _snapshot_model_state(cls, instance, extra_fields=None):
        fields = ['is_deleted', 'is_active', 'deleted_at', 'deleted_by_id']
        if extra_fields:
            fields.extend(extra_fields)
        state = {}
        for field in fields:
            if not hasattr(instance, field):
                continue
            value = getattr(instance, field)
            if isinstance(value, datetime):
                value = cls._snapshot_datetime(value)
            state[field] = value
        return state

    @classmethod
    def _snapshot_map(cls, instances, extra_fields=None):
        return {
            str(instance.id): cls._snapshot_model_state(instance, extra_fields=extra_fields)
            for instance in instances
            if getattr(instance, 'id', None)
        }

    @classmethod
    def _related_nakliyeler(cls, kiralama_id):
        return Nakliye.query.filter_by(kiralama_id=kiralama_id).all()

    @classmethod
    def _related_hizmetler(cls, kiralama, nakliyeler):
        form_no = kiralama.kiralama_form_no
        nakliye_ids = [n.id for n in nakliyeler if n.id]
        filters = [HizmetKaydi.fatura_no == form_no]
        if nakliye_ids:
            filters.append(HizmetKaydi.nakliye_id.in_(nakliye_ids))
        return HizmetKaydi.query.filter(or_(*filters)).all()

    @classmethod
    def _create_delete_snapshot(cls, kiralama, nakliyeler, hizmetler, actor_id=None):
        ekipmanlar = []
        seen_ekipman_ids = set()
        for kalem in kiralama.kalemler:
            if kalem.ekipman and kalem.ekipman.id not in seen_ekipman_ids:
                ekipmanlar.append(kalem.ekipman)
                seen_ekipman_ids.add(kalem.ekipman.id)

        now = datetime.now(timezone.utc)
        return {
            'kiralama_id': kiralama.id,
            'actor_id': actor_id,
            'created_at': cls._snapshot_datetime(now),
            'expires_at': cls._snapshot_datetime(now + timedelta(seconds=cls.UNDO_WINDOW_SECONDS)),
            'kiralama': cls._snapshot_model_state(kiralama),
            'kalemler': cls._snapshot_map(kiralama.kalemler),
            'nakliyeler': cls._snapshot_map(nakliyeler),
            'hizmetler': cls._snapshot_map(hizmetler),
            'ekipmanlar': cls._snapshot_map(
                ekipmanlar,
                extra_fields=['calisma_durumu', 'sube_id'],
            ),
        }

    @classmethod
    def _validate_restore_snapshot(cls, kiralama_id, snapshot, actor_id=None, max_undo_seconds=None):
        if not snapshot:
            raise ValidationError("Geri alma bilgisi bulunamadi veya sunucu yeniden baslatildi.")
        if snapshot.get('kiralama_id') != kiralama_id:
            raise ValidationError("Geri alma bilgisi bu kiralama kaydi ile eslesmiyor.")
        if snapshot.get('actor_id') and actor_id and snapshot.get('actor_id') != actor_id:
            raise ValidationError("Bu kaydi yalnizca silme islemini yapan kullanici geri alabilir.")

        expires_at = cls._parse_snapshot_datetime(snapshot.get('expires_at'))
        if not expires_at:
            raise ValidationError("Geri alma icin silinme zamani bulunamadi.")
        if datetime.now(timezone.utc) > cls._normalize_utc(expires_at):
            seconds = max_undo_seconds or cls.UNDO_WINDOW_SECONDS
            raise ValidationError(
                f"Geri alma suresi doldu ({seconds} saniye). Kayit artik geri getirilemez."
            )

    @classmethod
    def _collect_affected_firma_ids(cls, kiralama, nakliyeler, hizmetler):
        firma_ids = {kiralama.firma_musteri_id}
        for kalem in kiralama.kalemler:
            firma_ids.update([
                kalem.harici_ekipman_tedarikci_id,
                kalem.nakliye_tedarikci_id,
                kalem.donus_nakliye_tedarikci_id,
            ])
        for nakliye in nakliyeler:
            firma_ids.update([
                getattr(nakliye, 'firma_id', None),
                getattr(nakliye, 'taseron_firma_id', None),
            ])
        for hizmet in hizmetler:
            firma_ids.add(hizmet.firma_id)
        return {firma_id for firma_id in firma_ids if firma_id}

    @classmethod
    def _sync_firma_balances(cls, firma_ids):
        from app.services.firma_services import FirmaService

        for firma_id in sorted(firma_ids):
            firma = db.session.get(Firma, firma_id)
            if not firma:
                continue
            ozet = firma.bakiye_ozeti
            firma.bakiye = ozet['net_bakiye']
            FirmaService.guncelle_firma_cari_cache(firma_id, auto_commit=False)
            db.session.add(firma)

    @classmethod
    def sync_firma_caches(cls, firma_ids, auto_commit=False):
        """Firma cache'lerini bir batch icinde yeniler."""
        cls._sync_firma_balances({firma_id for firma_id in (firma_ids or []) if firma_id})
        if auto_commit:
            db.session.commit()

    @classmethod
    def _sync_ekipman_states(cls, ekipman_ids, snapshot=None):
        snapshot_states = (snapshot or {}).get('ekipmanlar') or {}
        for ekipman_id in {eid for eid in ekipman_ids if eid}:
            ekipman = db.session.get(Ekipman, ekipman_id)
            if not ekipman:
                continue
            aktif_kullanim = (
                KiralamaKalemi.query
                .join(Kiralama, KiralamaKalemi.kiralama_id == Kiralama.id)
                .filter(
                    KiralamaKalemi.ekipman_id == ekipman_id,
                    KiralamaKalemi.is_active == True,
                    KiralamaKalemi.sonlandirildi == False,
                    KiralamaKalemi.is_deleted == False,
                    Kiralama.is_deleted == False,
                )
                .first()
            )
            if aktif_kullanim:
                ekipman.calisma_durumu = 'kirada'
            else:
                state = snapshot_states.get(str(ekipman_id)) or {}
                ekipman.calisma_durumu = state.get('calisma_durumu') or 'bosta'
                if 'sube_id' in state:
                    ekipman.sube_id = state.get('sube_id')
            db.session.add(ekipman)

    @classmethod
    def _sync_ekipman_after_restore(cls, kiralama):
        for kalem in kiralama.kalemler:
            if not kalem.ekipman:
                continue
            if kalem.sonlandirildi or not kalem.is_active:
                continue
            kalem.ekipman.calisma_durumu = 'kirada'
            db.session.add(kalem.ekipman)

    @classmethod
    def _check_restore_ekipman_conflicts(cls, kiralama, snapshot=None):
        snapshot_kalemler = (snapshot or {}).get('kalemler') or {}
        for kalem in kiralama.kalemler:
            state = snapshot_kalemler.get(str(kalem.id), {})
            will_be_active = state.get('is_active', kalem.is_active)
            will_be_deleted = state.get('is_deleted', False)
            if not kalem.ekipman_id or kalem.sonlandirildi or not will_be_active or will_be_deleted:
                continue
            cakisan = (
                KiralamaKalemi.query
                .join(Kiralama, KiralamaKalemi.kiralama_id == Kiralama.id)
                .filter(
                    KiralamaKalemi.ekipman_id == kalem.ekipman_id,
                    KiralamaKalemi.id != kalem.id,
                    KiralamaKalemi.is_active == True,
                    KiralamaKalemi.sonlandirildi == False,
                    KiralamaKalemi.is_deleted == False,
                    Kiralama.is_deleted == False,
                    Kiralama.id != kiralama.id,
                )
                .first()
            )
            if cakisan:
                cakisan_form_no = (
                    cakisan.kiralama.kiralama_form_no
                    if cakisan.kiralama else f"#{cakisan.kiralama_id}"
                )
                makine_kod = kalem.ekipman.kod if kalem.ekipman else f"id={kalem.ekipman_id}"
                raise ValidationError(
                    f"Geri alınamaz: '{makine_kod}' makinesi şu an "
                    f"{cakisan_form_no} numaralı kiralamada aktif kullanımda."
                )

    @classmethod
    def delete_with_relations(cls, kiralama_id, actor_id=None):
        """Kiralamayı ve bağlı kayıtları mantıksal olarak siler (geri alınabilir)."""
        kiralama = db.session.get(Kiralama, kiralama_id)
        if not kiralama:
            raise ValidationError("Kiralama bulunamadı.")
        if kiralama.is_deleted:
            raise ValidationError("Kiralama zaten silinmiş.")

        try:
            deleted_at = datetime.now(timezone.utc)
            nakliyeler = cls._related_nakliyeler(kiralama.id)
            hizmetler = cls._related_hizmetler(kiralama, nakliyeler)
            affected_firma_ids = cls._collect_affected_firma_ids(kiralama, nakliyeler, hizmetler)
            affected_ekipman_ids = {
                kalem.ekipman_id for kalem in kiralama.kalemler if kalem.ekipman_id
            }
            snapshot = cls._create_delete_snapshot(
                kiralama,
                nakliyeler,
                hizmetler,
                actor_id=actor_id,
            )

            for kayit in hizmetler:
                cls._soft_delete_instance(kayit, actor_id=actor_id, deleted_at=deleted_at)

            for nakliye in nakliyeler:
                nakliye.is_active = False
                db.session.add(nakliye)

            for kalem in list(kiralama.kalemler):
                cls._soft_delete_instance(kalem, actor_id=actor_id, deleted_at=deleted_at)

            cls._soft_delete_instance(kiralama, actor_id=actor_id, deleted_at=deleted_at)
            db.session.flush()
            cls._sync_ekipman_states(affected_ekipman_ids)
            cls._sync_firma_balances(affected_firma_ids)
            db.session.commit()
            return snapshot
        except ValidationError:
            db.session.rollback()
            raise
        except Exception as e:
            db.session.rollback()
            raise ValidationError(f"Silme hatası: {str(e)}") from e

    @classmethod
    def restore_with_relations(cls, kiralama_id, actor_id=None, max_undo_seconds=None, snapshot=None):
        """Soft-delete edilmiş kiralamayı kısa süre içinde geri yükler."""
        if max_undo_seconds is None:
            max_undo_seconds = cls.UNDO_WINDOW_SECONDS

        kiralama = db.session.get(Kiralama, kiralama_id)
        if not kiralama:
            raise ValidationError("Kiralama bulunamadı.")
        if not kiralama.is_deleted:
            raise ValidationError("Kiralama silinmiş durumda değil.")
        if not kiralama.deleted_at:
            raise ValidationError("Geri alma için silinme zamanı bulunamadı.")

        cls._validate_restore_snapshot(
            kiralama_id,
            snapshot,
            actor_id=actor_id,
            max_undo_seconds=max_undo_seconds,
        )

        now = datetime.now(timezone.utc)
        deleted_at = cls._normalize_utc(kiralama.deleted_at)
        elapsed = (now - deleted_at).total_seconds()
        if elapsed > max_undo_seconds:
            raise ValidationError(
                f"Geri alma süresi doldu ({max_undo_seconds} saniye). "
                "Kayıt artık geri getirilemez."
            )

        cls._check_restore_ekipman_conflicts(kiralama, snapshot=snapshot)

        try:
            nakliyeler = cls._related_nakliyeler(kiralama.id)
            hizmetler = cls._related_hizmetler(kiralama, nakliyeler)
            affected_firma_ids = cls._collect_affected_firma_ids(kiralama, nakliyeler, hizmetler)
            affected_ekipman_ids = set()

            for kayit in hizmetler:
                state = (snapshot.get('hizmetler') or {}).get(str(kayit.id))
                if state:
                    cls._restore_instance(kayit, state=state)

            for nakliye in nakliyeler:
                state = (snapshot.get('nakliyeler') or {}).get(str(nakliye.id), {})
                nakliye.is_active = state.get('is_active', True)
                db.session.add(nakliye)

            cls._restore_instance(kiralama, state=snapshot.get('kiralama'))
            for kalem in list(kiralama.kalemler):
                state = (snapshot.get('kalemler') or {}).get(str(kalem.id))
                if state:
                    cls._restore_instance(kalem, state=state)
                if kalem.ekipman_id:
                    affected_ekipman_ids.add(kalem.ekipman_id)

            db.session.flush()
            cls._sync_ekipman_states(affected_ekipman_ids, snapshot=snapshot)
            cls.guncelle_cari_toplam(kiralama.id, auto_commit=False)
            for kalem in kiralama.kalemler:
                if kalem.is_dis_tedarik_ekipman and kalem.harici_ekipman_tedarikci_id:
                    cls.guncelle_tedarikci_cari_toplam(
                        kalem.harici_ekipman_tedarikci_id,
                        auto_commit=False,
                    )
            cls._sync_firma_balances(affected_firma_ids)

            if actor_id and hasattr(kiralama, 'updated_by_id'):
                kiralama.updated_by_id = actor_id
            if hasattr(kiralama, 'updated_at'):
                kiralama.updated_at = datetime.now(timezone.utc)
            db.session.add(kiralama)

            db.session.commit()
            return kiralama
        except ValidationError:
            db.session.rollback()
            raise
        except Exception as e:
            db.session.rollback()
            raise ValidationError(f"Geri alma hatası: {str(e)}") from e

    @classmethod
    def _archive_restore_kalem_state(cls, kalem):
        return {
            'is_deleted': False,
            'is_active': not bool(getattr(kalem, 'revizyonlar', None)),
            'deleted_at': None,
            'deleted_by_id': None,
        }

    @classmethod
    def restore_archived_with_relations(cls, kiralama_id, actor_id=None):
        """Arşivdeki kiralamayı süre sınırı olmadan geri yükler."""
        kiralama = db.session.get(Kiralama, kiralama_id)
        if not kiralama:
            raise ValidationError("Kiralama bulunamadı.")
        if not kiralama.is_deleted:
            raise ValidationError("Kiralama silinmiş durumda değil.")

        kalem_states = {
            str(kalem.id): cls._archive_restore_kalem_state(kalem)
            for kalem in kiralama.kalemler
            if getattr(kalem, 'id', None)
        }
        restore_snapshot = {'kalemler': kalem_states}
        cls._check_restore_ekipman_conflicts(kiralama, snapshot=restore_snapshot)

        try:
            nakliyeler = cls._related_nakliyeler(kiralama.id)
            hizmetler = cls._related_hizmetler(kiralama, nakliyeler)
            affected_firma_ids = cls._collect_affected_firma_ids(kiralama, nakliyeler, hizmetler)
            affected_ekipman_ids = {
                kalem.ekipman_id for kalem in kiralama.kalemler if kalem.ekipman_id
            }

            for kayit in hizmetler:
                if getattr(kayit, 'is_deleted', False):
                    cls._restore_instance(kayit)

            for nakliye in nakliyeler:
                if hasattr(nakliye, 'is_deleted'):
                    nakliye.is_deleted = False
                    nakliye.deleted_at = None
                    nakliye.deleted_by_id = None
                nakliye.is_active = True
                db.session.add(nakliye)

            cls._restore_instance(kiralama)
            for kalem in list(kiralama.kalemler):
                state = kalem_states.get(str(kalem.id), {'is_deleted': False, 'is_active': True})
                cls._restore_instance(kalem, state=state)

            db.session.flush()
            cls._sync_ekipman_states(affected_ekipman_ids)
            cls.guncelle_cari_toplam(kiralama.id, auto_commit=False)
            for kalem in kiralama.kalemler:
                if kalem.is_dis_tedarik_ekipman and kalem.harici_ekipman_tedarikci_id:
                    cls.guncelle_tedarikci_cari_toplam(
                        kalem.harici_ekipman_tedarikci_id,
                        auto_commit=False,
                    )
            cls._sync_firma_balances(affected_firma_ids)

            if actor_id and hasattr(kiralama, 'updated_by_id'):
                kiralama.updated_by_id = actor_id
            if hasattr(kiralama, 'updated_at'):
                kiralama.updated_at = datetime.now(timezone.utc)
            db.session.add(kiralama)

            db.session.commit()
            return kiralama
        except ValidationError:
            db.session.rollback()
            raise
        except Exception as e:
            db.session.rollback()
            raise ValidationError(f"Arşivden geri yükleme hatası: {str(e)}") from e

    @staticmethod
    def _create_nakliye_ve_cari(kiralama, kalem, makine_adi, bas_tarihi):
        """Nakliye seferi ve varsa taşeron cari gider kaydını senkronize eder."""
        firma_adi = kiralama.firma_musteri.firma_adi if kiralama.firma_musteri else "Müşteri"
        is_yeri = (kiralama.makine_calisma_adresi or '').strip() or firma_adi
        gidis_sube_adi = kalem.ekipman.sube.isim if (kalem.ekipman and kalem.ekipman.sube) else None
        if gidis_sube_adi:
            guzergah_gidis = f"{makine_adi} {gidis_sube_adi} şubesinden {firma_adi} firmasının {is_yeri}'ne götürüldü"
        else:
            guzergah_gidis = f"{makine_adi} {firma_adi} firmasına götürüldü ({is_yeri})"

        form_no = kiralama.kiralama_form_no or ''
        gidis_aciklama = f"Gidiş: {form_no} #{kalem.id}" if kalem.id else f"Gidiş: {form_no}"
        legacy_gidis_aciklama = f"Gidiş: {form_no}"
        yeni_sefer = Nakliye.query.filter(
            Nakliye.kiralama_id == kiralama.id,
            Nakliye.aciklama == gidis_aciklama,
        ).first()
        if not yeni_sefer and kalem.id:
            legacy_adaylar = Nakliye.query.filter(
                Nakliye.kiralama_id == kiralama.id,
                Nakliye.aciklama == legacy_gidis_aciklama,
            ).order_by(Nakliye.id.asc()).all()
            if len(legacy_adaylar) == 1:
                yeni_sefer = legacy_adaylar[0]
            else:
                makine_adi_norm = (makine_adi or '').strip().lower()
                guzergah_norm = (guzergah_gidis or '').strip().lower()
                for aday in legacy_adaylar:
                    aday_guzergah_norm = (aday.guzergah or '').strip().lower()
                    if (
                        aday_guzergah_norm == guzergah_norm
                        or (makine_adi_norm and makine_adi_norm in aday_guzergah_norm)
                    ):
                        yeni_sefer = aday
                        break
        if not yeni_sefer:
            yeni_sefer = Nakliye(kiralama_id=kiralama.id)

        yeni_sefer.firma_id = kiralama.firma_musteri_id
        yeni_sefer.tarih = bas_tarihi
        yeni_sefer.islem_tarihi = bas_tarihi
        yeni_sefer.guzergah = guzergah_gidis
        yeni_sefer.tutar = KiralamaService._get_gidis_nakliye_satis(kalem)
        yeni_sefer.kdv_orani = kalem.nakliye_satis_kdv if kalem.nakliye_satis_kdv is not None else (kiralama.kdv_orani if kiralama.kdv_orani is not None else 20)
        yeni_sefer.tevkifat_orani = kalem.nakliye_satis_tevkifat_oran or None
        yeni_sefer.aciklama = gidis_aciklama
        yeni_sefer.is_active = True

        if kalem.is_harici_nakliye and kalem.nakliye_tedarikci_id:
            # TAŞERON NAKLİYE
            yeni_sefer.nakliye_tipi = 'taseron'
            yeni_sefer.taseron_firma_id = kalem.nakliye_tedarikci_id
            yeni_sefer.taseron_maliyet = to_decimal(kalem.nakliye_alis_fiyat)
            yeni_sefer.taseron_kdv_orani = kalem.nakliye_alis_kdv
            yeni_sefer.plaka = "Dış Nakliye"
            yeni_sefer.arac_id = None

            if yeni_sefer.taseron_maliyet > 0:
                nakliye_kdv = kalem.nakliye_alis_kdv
                taseron_kayitlari = HizmetKaydi.query.filter(
                    HizmetKaydi.firma_id == yeni_sefer.taseron_firma_id,
                    HizmetKaydi.ozel_id == kalem.id,
                    HizmetKaydi.yon == 'gelen',
                    HizmetKaydi.fatura_no == kiralama.kiralama_form_no,
                    HizmetKaydi.aciklama.like('Taşeron Nakliye Bedeli%')
                ).order_by(HizmetKaydi.id.asc()).all()
                taseron_cari = taseron_kayitlari[0] if taseron_kayitlari else HizmetKaydi(yon='gelen')
                for fazla_kayit in taseron_kayitlari[1:]:
                    fazla_kayit.is_deleted = True
                    fazla_kayit.is_active = False
                    fazla_kayit.deleted_at = datetime.now(timezone.utc)
                    db.session.add(fazla_kayit)

                taseron_cari.firma_id = yeni_sefer.taseron_firma_id
                taseron_cari.tarih = bas_tarihi or date.today()
                taseron_cari.islem_tarihi = bas_tarihi or date.today()
                taseron_cari.tutar = yeni_sefer.taseron_maliyet
                taseron_cari.yon = 'gelen'
                taseron_cari.fatura_no = kiralama.kiralama_form_no
                taseron_cari.ozel_id = kalem.id
                taseron_cari.aciklama = f"Taşeron Nakliye Bedeli ({makine_adi}) - {kiralama.kiralama_form_no}"
                taseron_cari.nakliye_alis_kdv = nakliye_kdv
                taseron_cari.kdv_orani = None
                taseron_cari.is_deleted = False
                taseron_cari.is_active = True
                db.session.add(taseron_cari)
        else:
            # ÖZ MAL NAKLİYE
            yeni_sefer.nakliye_tipi = 'oz_mal'
            yeni_sefer.taseron_firma_id = None
            yeni_sefer.taseron_maliyet = Decimal('0.00')
            yeni_sefer.taseron_kdv_orani = None
            yeni_sefer.arac_id = kalem.nakliye_araci_id
            yeni_sefer.plaka = None
            if yeni_sefer.arac_id:
                secilen_arac = db.session.get(NakliyeAraci, yeni_sefer.arac_id)
                if secilen_arac:
                    yeni_sefer.plaka = secilen_arac.plaka

        yeni_sefer.hesapla_ve_guncelle()
        db.session.add(yeni_sefer)

        # Sonlandırılmış kalem ise dönüş nakliyeyi yalnızca politika izin
        # veriyorsa yeniden oluştur. Swap müşteri talebiyse mevcut ücretli
        # dönüş kaydı korunur; arıza/periyodik swapta reconcile temizler.
        swap_reason = KiralamaService._swap_reason_for_kalem(kalem)
        if (
            kalem.sonlandirildi
            and swap_reason not in ('serviste', 'periyodik', 'bakimda')
            and (
                KiralamaService._get_donus_nakliye_satis(kalem) > 0
                or swap_reason == 'bosta'
            )
        ):
            donus_satis = KiralamaService._get_donus_nakliye_satis(kalem)
            if donus_satis and donus_satis > 0:
                form_no = kiralama.kiralama_form_no or ''
                Nakliye.query.filter(
                    Nakliye.kiralama_id == kiralama.id,
                    Nakliye.aciklama == f"Dönüş: {form_no} #{kalem.id}"
                ).delete(synchronize_session=False)

                donus_sube_adi = "Şube"
                if kalem.ekipman and kalem.ekipman.sube:
                    donus_sube_adi = kalem.ekipman.sube.isim
                donus_guzergah = (
                    f"{makine_adi} {firma_adi} firmasının {is_yeri}'nden "
                    f"{donus_sube_adi} şubesine getirildi"
                )
                nak_tipi = 'taseron' if kalem.donus_is_harici_nakliye else 'oz_mal'
                donus_sefer = Nakliye(
                    kiralama_id=kiralama.id,
                    firma_id=kiralama.firma_musteri_id,
                    tarih=kalem.kiralama_bitis or date.today(),
                    islem_tarihi=kalem.kiralama_bitis or date.today(),
                    guzergah=donus_guzergah,
                    tutar=donus_satis,
                    kdv_orani=kalem.nakliye_satis_kdv if kalem.nakliye_satis_kdv is not None else (kiralama.kdv_orani if kiralama.kdv_orani is not None else 20),
                    tevkifat_orani=kalem.nakliye_satis_tevkifat_oran or None,
                    aciklama=f"Dönüş: {form_no} #{kalem.id}",
                    nakliye_tipi=nak_tipi,
                    arac_id=kalem.donus_nakliye_araci_id if not kalem.donus_is_harici_nakliye else None,
                )
                if kalem.donus_is_harici_nakliye and kalem.donus_nakliye_tedarikci_id:
                    donus_sefer.taseron_firma_id = kalem.donus_nakliye_tedarikci_id
                    donus_sefer.taseron_maliyet = to_decimal(kalem.donus_nakliye_alis_fiyat)
                    donus_sefer.taseron_kdv_orani = kalem.donus_nakliye_alis_kdv
                    donus_sefer.plaka = "Dış Nakliye"
                    donus_sefer.arac_id = None
                else:
                    donus_sefer.taseron_firma_id = None
                    donus_sefer.taseron_maliyet = Decimal('0.00')
                    donus_sefer.taseron_kdv_orani = None
                if not kalem.donus_is_harici_nakliye and kalem.donus_nakliye_araci_id:
                    secilen_arac = db.session.get(NakliyeAraci, kalem.donus_nakliye_araci_id)
                    if secilen_arac:
                        donus_sefer.plaka = secilen_arac.plaka
                donus_sefer.hesapla_ve_guncelle()
                db.session.add(donus_sefer)
