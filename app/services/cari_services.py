from app.extensions import db
from app.services.base import ValidationError
from sqlalchemy import func
from datetime import datetime, timezone

# ---------------------------------------------------------
# ORTAK FİLTRELEME: HizmetKaydi bakiye hesabına dahil edilecek kayıtlar
# ---------------------------------------------------------
# Kiralama kapanışında kapat_kalem tarafından oluşturulan nakliye muhasebe kayıtları
# (ozel_id=kalem.id ile işaretlenir). Bunların finansal karşılığı CariServis tarafından
# nakliye_id dolu bir HizmetKaydi ile zaten oluşturulmaktadır; dolayısıyla bu kayıtlar
# bakiye hesabına dahil edilmemelidir.
NAKLIYE_MUHASEBE_PREFIXLERI = (
    'Müşteri Dönüş Nakliye Bedeli',
    'Müşteri Nakliye Fark',
)


def hizmet_kaydi_bakiyeye_dahil_mi(h) -> bool:
    """
    Bir HizmetKaydi kaydının bakiye hesabına dahil edilip edilmeyeceğini döner.
    Her iki hesaplama yolu (bakiye_ozeti ve firma_services hareketler) bu fonksiyonu
    kullanarak tutarlı davranış sağlar.
    """
    if getattr(h, 'is_deleted', False):
        return False
    # nakliye_id dolu kayıtlar doğrudan nakliye işlemini temsil eder — dahil et
    if getattr(h, 'nakliye_id', None):
        return True
    # ozel_id dolu + nakliye muhasebe aciklama → kapat_kalem çift kaydı → hariç tut
    if getattr(h, 'ozel_id', None) is not None:
        aciklama = (h.aciklama or '')
        if aciklama.startswith(NAKLIYE_MUHASEBE_PREFIXLERI):
            return False
    return True


# ---------------------------------------------------------
# YARDIMCI FONKSİYONLAR (BAKİYE SENKRONİZASYONU)
# ---------------------------------------------------------
def _sync_firma_bakiye(firma_id):
    """Bir firmanın bakiyesini hareketlerden (Ledger) yeniden hesaplar ve günceller."""
    from app.firmalar.models import Firma
    if not firma_id: return
    firma = Firma.query.get(firma_id)
    if firma:
        ozet = firma.bakiye_ozeti
        firma.bakiye = ozet['net_bakiye']
        db.session.commit()

def _sync_kasa_bakiye(kasa_id):
    """Bir kasanın bakiyesini ödeme hareketlerinden yeniden hesaplar ve günceller."""
    from app.cari.models import Kasa
    if not kasa_id: return
    kasa = Kasa.query.get(kasa_id)
    if kasa:
        kasa.bakiye = kasa.hesaplanan_bakiye
        db.session.commit()

def get_dahili_islem_firmasi():
    """Kasa transferleri için kullanılan dahili sistem firmasını getirir."""
    from app.firmalar.models import Firma
    firma = Firma.query.filter_by(firma_adi="DAHİLİ İŞLEMLER").first()
    if not firma:
        firma = Firma(
            firma_adi="DAHİLİ İŞLEMLER", 
            yetkili_adi="SİSTEM", 
            iletisim_bilgileri="SİSTEM", 
            vergi_dairesi="SİSTEM", 
            vergi_no="0000000000", 
            is_active=True
        )
        db.session.add(firma)
        db.session.commit()
    return firma

# ---------------------------------------------------------
# KASA SERVİSİ
# ---------------------------------------------------------
class KasaService:
    @staticmethod
    def get_by_id(kasa_id):
        from app.cari.models import Kasa
        return Kasa.query.get(kasa_id)

    @staticmethod
    def find_by(**kwargs):
        from app.cari.models import Kasa
        return Kasa.query.filter_by(**kwargs).all()

    @staticmethod
    def save(kasa, is_new=True, actor_id=None):
        if is_new: 
            kasa.created_by_id = actor_id
        else: 
            kasa.updated_by_id = actor_id
            
        db.session.add(kasa)
        db.session.commit()
        return kasa

    @staticmethod
    def transfer_yap(kaynak_id, hedef_id, tutar, actor_id=None):
        from app.cari.models import Kasa, Odeme
        
        if kaynak_id == hedef_id: 
            raise ValidationError("Aynı kasalar arasında transfer yapılamaz.")
        if tutar <= 0:
            raise ValidationError("Transfer tutarı sıfırdan büyük olmalıdır.")
            
        kaynak = Kasa.query.get(kaynak_id)
        hedef = Kasa.query.get(hedef_id)
        
        # --- TRANSFER İÇİN YETERSİZ BAKİYE KONTROLÜ EKLENDİ ---
        if kaynak.bakiye < tutar:
            raise ValidationError(f"Transfer Başarısız: Kaynak kasada yeterli bakiye yok! (Mevcut Bakiye: {kaynak.bakiye:,.2f} TL)")
        
        dahili_firma = get_dahili_islem_firmasi()
        
        # Transfer işlemi çift taraflı (Double-Entry) kaydedilir
        cikis = Odeme(firma_musteri_id=dahili_firma.id, kasa_id=kaynak.id, tutar=tutar, yon='odeme', aciklama=f"{hedef.kasa_adi} kasasına transfer", created_by_id=actor_id)
        giris = Odeme(firma_musteri_id=dahili_firma.id, kasa_id=hedef.id, tutar=tutar, yon='tahsilat', aciklama=f"{kaynak.kasa_adi} kasasından transfer", created_by_id=actor_id)
        
        db.session.add_all([cikis, giris])
        db.session.commit()
        
        # Bakiyeleri doğrula
        _sync_kasa_bakiye(kaynak.id)
        _sync_kasa_bakiye(hedef.id)

    @staticmethod
    def kasa_kapat_ve_devret(kasa_id, hedef_kasa_id, actor_id=None):
        from app.cari.models import Kasa
        kasa = Kasa.query.get(kasa_id)
        if not kasa: raise ValidationError("Kasa bulunamadı.")
        
        if kasa.bakiye != 0:
            if not hedef_kasa_id:
                raise ValidationError("Bakiyesi olan bir kasayı kapatmak için hedef kasa seçmelisiniz.")
            KasaService.transfer_yap(kasa_id, hedef_kasa_id, kasa.bakiye, actor_id)
        
        kasa.is_active = False
        kasa.is_deleted = True
        kasa.deleted_at = datetime.now(timezone.utc)
        kasa.deleted_by_id = actor_id
        db.session.commit()

# ---------------------------------------------------------
# ÖDEME / TAHSİLAT SERVİSİ
# ---------------------------------------------------------
class OdemeService:
    @staticmethod
    def get_by_id(odeme_id):
        from app.cari.models import Odeme
        return Odeme.query.get(odeme_id)

    @staticmethod
    def save(odeme, is_new=True, actor_id=None):
        """Ödeme/Tahsilat ekler veya günceller. Kasayı ve Firmayı senkronize eder."""
        from app.cari.models import Kasa, Odeme as OdemeModel
        
        kasa = Kasa.query.get(odeme.kasa_id)
        if not kasa: 
            raise ValidationError("Geçerli bir kasa seçilmelidir.")

        # --- YETERSİZ BAKİYE KONTROLÜ (YENİ EKLENDİ) ---
        if odeme.yon == 'odeme': # Eğer firmaya ödeme yapıyorsak (kasadan çıkış)
            if is_new:
                if kasa.bakiye < odeme.tutar:
                    raise ValidationError(f"İşlem Başarısız: Seçili kasada yeterli bakiye yok! (Mevcut Kasa Bakiyesi: {kasa.bakiye:,.2f} TL)")
            else:
                # Düzenleme modunda, eski kaydın tutarını kasaya iade edip "gerçek" bakiyeyi buluyoruz
                eski_kayit = OdemeModel.query.get(odeme.id)
                gercek_bakiye = kasa.bakiye
                if eski_kayit.yon == 'odeme':
                    gercek_bakiye += eski_kayit.tutar
                else:
                    gercek_bakiye -= eski_kayit.tutar
                    
                if gercek_bakiye < odeme.tutar:
                    raise ValidationError(f"İşlem Başarısız: Seçili kasada yeterli bakiye yok! (İşlem yapılabilecek maksimum tutar: {gercek_bakiye:,.2f} TL)")
        # ----------------------------------------------

        if is_new:
            odeme.created_by_id = actor_id
        else:
            odeme.updated_by_id = actor_id
            
        db.session.add(odeme)
        db.session.commit()
        
        # Delta hesaplamak yerine bakiyeleri baştan hesaplamak en güvenli yoldur
        _sync_kasa_bakiye(odeme.kasa_id)
        _sync_firma_bakiye(odeme.firma_musteri_id)
        
        return odeme

    @staticmethod
    def delete(odeme_id, actor_id=None):
        from app.cari.models import Odeme
        odeme = Odeme.query.get(odeme_id)
        if not odeme: return
        
        kasa_id = odeme.kasa_id
        firma_id = odeme.firma_musteri_id
        
        # Kaydı soft-delete yap
        odeme.delete(soft=True, user_id=actor_id)
        
        # Silinen kaydın etkisini kaldırmak için bakiyeleri tekrar hesapla
        _sync_kasa_bakiye(kasa_id)
        _sync_firma_bakiye(firma_id)

# ---------------------------------------------------------
# HİZMET / FATURA SERVİSİ
# ---------------------------------------------------------
class HizmetKaydiService:
    @staticmethod
    def get_by_id(id):
        from app.cari.models import HizmetKaydi
        return HizmetKaydi.query.get(id)

    @staticmethod
    def save(hizmet, is_new=True, actor_id=None, commit=True):
        # KDV dahil toplam tutarı otomatik hesapla (KDV hariç giriliyor)
        if hizmet.tutar is not None and hizmet.kdv_orani is not None:
            try:
                # Decimal ile çarpma için float'a çevirme
                kdv_carpan = 1 + (float(hizmet.kdv_orani) / 100)
                hizmet.toplam_tutar = float(hizmet.tutar) * kdv_carpan
            except Exception:
                hizmet.toplam_tutar = hizmet.tutar
        else:
            hizmet.toplam_tutar = hizmet.tutar

        if is_new:
            hizmet.created_by_id = actor_id
        else:
            hizmet.updated_by_id = actor_id

        db.session.add(hizmet)
        if commit:
            db.session.commit()
            _sync_firma_bakiye(hizmet.firma_id)
        else:
            db.session.flush()

        return hizmet

    @staticmethod
    def delete(id, actor_id=None):
        from app.cari.models import HizmetKaydi
        hizmet = HizmetKaydi.query.get(id)
        if not hizmet: return
        
        firma_id = hizmet.firma_id
        hizmet.delete(soft=True, user_id=actor_id)
        
        # İptal edilen faturayı cari bakiyeden düş
        _sync_firma_bakiye(firma_id)

# ---------------------------------------------------------
# RAPORLAMA VE MUTABAKAT SERVİSİ
# ---------------------------------------------------------
class CariRaporService:
    @staticmethod
    def sync_all_balances():
        """Tüm Kasa ve Firma bakiyelerini defterden (Ledger) baştan hesaplar.
        Veritabanında tutarsızlık olduğunda hayat kurtarır."""
        from app.cari.models import Kasa
        from app.firmalar.models import Firma
        
        kasalar = Kasa.query.all()
        for kasa in kasalar:
            kasa.bakiye = kasa.hesaplanan_bakiye
            
        firmalar = Firma.query.all()
        for f in firmalar:
            ozet = f.bakiye_ozeti
            f.bakiye = ozet['net_bakiye']
            
        db.session.commit()

    @staticmethod
    def get_durum_raporu():
        from app.firmalar.models import Firma
        # Dahili sistem firmaları rapor listesinden ve genel toplamdan dışlandı
        firmalar = Firma.query.filter(
            Firma.is_deleted == False,
            Firma.firma_adi.notin_(['DAHİLİ İŞLEMLER', 'Dahili Kasa İşlemleri'])
        ).all()
        rapor = []
        g_borc, g_alacak = 0, 0
        g_borc_kdvli, g_alacak_kdvli = 0, 0
        for f in firmalar:
            ozet = f.bakiye_ozeti
            # Tüm firmaları göster (sıfır bakiyeli olanları da dahil et)
            rapor.append({
                'id': f.id,
                'firma_adi': f.firma_adi,
                'yetkili': f.yetkili_adi,
                'tipi': (
                    'Müşteri, Tedarikçi' if f.is_musteri and f.is_tedarikci
                    else 'Müşteri' if f.is_musteri
                    else 'Tedarikçi' if f.is_tedarikci
                    else 'Firma'
                ),
                'borc': ozet['borc'],
                'alacak': ozet['alacak'],
                'bakiye': ozet['net_bakiye'],
                'borc_kdvli': ozet['borc_kdvli'],
                'alacak_kdvli': ozet['alacak_kdvli'],
                'bakiye_kdvli': ozet['net_bakiye_kdvli']
            })
            g_borc += ozet['borc']
            g_alacak += ozet['alacak']
            g_borc_kdvli += ozet['borc_kdvli']
            g_alacak_kdvli += ozet['alacak_kdvli']
        return rapor, {
            'borc': g_borc,
            'alacak': g_alacak,
            'bakiye': g_borc - g_alacak,
            'borc_kdvli': g_borc_kdvli,
            'alacak_kdvli': g_alacak_kdvli,
            'bakiye_kdvli': g_borc_kdvli - g_alacak_kdvli
        }