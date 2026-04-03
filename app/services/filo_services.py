from app.services.base import BaseService, ValidationError
from app.filo.models import Ekipman, BakimKaydi
from app.kiralama.models import KiralamaKalemi
from app.extensions import db
from datetime import datetime
from app.utils import normalize_turkish_upper

class EkipmanService(BaseService):
    """
    Filo (Ekipman/Makine) yönetimi için iş mantığı katmanı.
    Tüm CRUD işlemleri, şube transferleri ve durum güncellemeleri buradan yönetilir.
    """
    model = Ekipman
    use_soft_delete = True
    
    # Form üzerinden doğrudan güncellenmesine izin verilen alanlar (Güvenlik)
    updatable_fields = [
        'kod', 'yakit', 'tipi', 'marka', 'model', 'seri_no',
        'calisma_yuksekligi', 'kaldirma_kapasitesi', 'uretim_yili',
        'giris_maliyeti', 'para_birimi', 'sube_id', 'calisma_durumu',
        'agirlik', 'ic_mekan_uygun', 'arazi_tipi_uygun', 'genislik', 'uzunluk', 'kapali_yukseklik'
    ]

    @classmethod
    def validate(cls, instance, is_new=True):
        """Kayıt öncesi benzersizlik ve iş kuralları kontrolleri."""
        # 1. Makine Kodu her halükarda benzersiz olmalı
        if instance.kod:
            mevcut = cls.find_one_by(kod=instance.kod)
            if mevcut and (is_new or mevcut.id != instance.id):
                raise ValidationError(f"'{instance.kod}' kodlu makine zaten sistemde kayıtlı.")

        # 2. Seri No sadece Öz Mal makinelerimizde benzersiz olmalı (Tedarikçi makineleri hariç)
        if instance.seri_no and instance.firma_tedarikci_id is None:
            mevcut_seri = cls.find_one_by(seri_no=instance.seri_no, firma_tedarikci_id=None)
            if mevcut_seri and (is_new or mevcut_seri.id != instance.id):
                raise ValidationError(f"'{instance.seri_no}' seri numaralı bir öz mal makine zaten mevcut.")

    @classmethod
    def before_save(cls, instance, is_new=True):
        """Veritabanına yazılmadan milisaniyeler önce veriyi standartlaştırır."""
        if instance.kod:
            instance.kod = normalize_turkish_upper(instance.kod)
        if instance.seri_no:
            instance.seri_no = normalize_turkish_upper(instance.seri_no)
        
        # 'giris_maliyeti' alanını rotada veya formda string temizlemek yerine 
        # BaseForm ve MoneyField otomatik Decimal yapacağı için burada işleme gerek yok!

    # --- ÖZEL İŞ MANTIKLARI (BUSINESS LOGIC) ---

    @classmethod
    def sube_transfer(cls, ekipman_id, yeni_sube_id, actor_id=None):
        """Makineyi bir şubeden diğerine nakleder. Sizin yazdığınız eski 'bosta' kontrolü içerir."""
        ekipman = cls.get_by_id(ekipman_id)
        if not ekipman:
            raise ValidationError("Makine bulunamadı.")
            
        if ekipman.calisma_durumu != 'bosta':
            raise ValidationError(f"'{ekipman.kod}' şu an {ekipman.calisma_durumu} durumunda! Sadece boşta olan makineler nakledilebilir.")
            
        ekipman.sube_id = yeni_sube_id
        return cls.save(ekipman, is_new=False, actor_id=actor_id)

    @classmethod
    def kiralama_sonlandir(cls, ekipman_id, bitis_tarihi_str, donus_sube_id, actor_id=None):
        """Açık olan kiralama kalemini kapatır ve makineyi seçilen şubeye iade alır."""
        ekipman = cls.get_by_id(ekipman_id)
        if not ekipman:
            raise ValidationError("Makine bulunamadı.")
            
        if ekipman.firma_tedarikci_id is not None:
            raise ValidationError("Harici bir makine üzerinden sonlandırma yapılamaz.")

        if ekipman.calisma_durumu != 'kirada':
            raise ValidationError("Makine zaten kirada değil.")

        aktif_kalem = KiralamaKalemi.query.filter_by(
            ekipman_id=ekipman.id,
            sonlandirildi=False
        ).order_by(KiralamaKalemi.id.desc()).first()
        
        if aktif_kalem:
            try:
                # String gelen tarihi Date objesine çeviriyoruz
                bitis_dt = datetime.strptime(bitis_tarihi_str, "%Y-%m-%d").date() if isinstance(bitis_tarihi_str, str) else bitis_tarihi_str
            except ValueError:
                raise ValidationError("Tarih formatı geçersiz.")
            
            if bitis_dt < aktif_kalem.kiralama_baslangici:
                raise ValidationError("Bitiş tarihi, kiralama başlangıç tarihinden önce olamaz.")
                
            aktif_kalem.kiralama_bitis = bitis_dt
            aktif_kalem.sonlandirildi = True
            db.session.add(aktif_kalem)

        # Kalem kapatılsın veya kapatılmasın, makineyi bosta'ya çekip depoya alıyoruz
        ekipman.calisma_durumu = 'bosta'
        ekipman.sube_id = donus_sube_id
        return cls.save(ekipman, is_new=False, actor_id=actor_id)


class BakimService(BaseService):
    """
    Bakım kayıtları yönetimi.
    """
    model = BakimKaydi
    use_soft_delete = False # Bakım kayıtlarında soft delete şimdilik gerekli değil
    
    @classmethod
    def bakim_kaydet(cls, ekipman_id, bakim_verileri, actor_id=None):
        """Yeni bir bakım kaydı açar."""
        yeni_bakim = cls.model(ekipman_id=ekipman_id, **bakim_verileri)
        return cls.save(yeni_bakim, is_new=True, actor_id=actor_id)