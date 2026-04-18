"""
EkipmanRaporuService - Makine finansal analizi ve raporlama
Makinenin satın alma maliyeti, kiralama geliri, servis masrafları ve ROI hesaplamaları
"""

from decimal import Decimal
from datetime import datetime, date
from sqlalchemy import func, and_, or_
from sqlalchemy.orm import joinedload
from app.extensions import db
from app.filo.models import Ekipman, BakimKaydi, KullanilanParca, StokHareket
from app.kiralama.models import Kiralama, KiralamaKalemi
from app.utils import bugun as _bugun


class EkipmanRaporuService:
    """
    Makine finansal analizi servisi
    - Satın alma maliyeti
    - Kiralama gelirleri (dönem bazında)
    - Servis ve nakliye masrafları
    - ROI ve amorti durum hesaplamaları
    """
    
    @staticmethod
    def get_finansal_ozet(ekipman_id: int, start_date: date = None, end_date: date = None):
        """
        Makinenin finansal özetini hesaplar.
        
        Args:
            ekipman_id: Makine ID
            start_date: Başlangıç tarihi (None = min tarih)
            end_date: Bitiş tarihi (None = bugün)
            
        Returns:
            dict: Finansal özet bilgileri
        """
        ekipman = db.session.get(Ekipman, ekipman_id)
        if not ekipman:
            return None
        
        # Varsayılan tarih aralığı
        if end_date is None:
            end_date = _bugun()
        
        # Döviz kurları (0 ise kur yok kabul edilir)
        usd_rate = float(ekipman.temin_doviz_kuru_usd or 0)
        eur_rate = float(ekipman.temin_doviz_kuru_eur or 0)

        # Ekipman kuru boşsa kiralama anında kaydedilen kur ortalamasını kullan
        if usd_rate <= 0:
            usd_rate = EkipmanRaporuService._get_kiralama_kuru(ekipman_id, 'USD', start_date, end_date)
        if eur_rate <= 0:
            eur_rate = EkipmanRaporuService._get_kiralama_kuru(ekipman_id, 'EUR', start_date, end_date)

        # Temin maliyeti (para birimini dikkate alarak TRY'ye çevir)
        temin_bedeli_try, kur_eksik = EkipmanRaporuService._convert_to_try(
            float(ekipman.giris_maliyeti or 0.0),
            ekipman.para_birimi,
            usd_rate,
            eur_rate
        )
        temin_tarihi = ekipman.created_at.date() if ekipman.created_at else None

        # Kur yoksa USD/EUR etiketinde hatalı değer göstermemek için TRY'ye düş
        rapor_para_birimi = ekipman.para_birimi
        if (ekipman.para_birimi == 'USD' and usd_rate <= 0) or (ekipman.para_birimi == 'EUR' and eur_rate <= 0):
            rapor_para_birimi = 'TRY'
        
        # Kiralama gelirleri (Makine satın alma para birimine göre hesapla)
        kiralama_geliri_orijinal = EkipmanRaporuService._calculate_kirlama_geliri(
            ekipman_id, start_date, end_date, 
            target_currency=rapor_para_birimi,
            usd_rate=usd_rate,
            eur_rate=eur_rate
        )
        
        # Kiralama gelirleri TRY cinsinden (her halükarda raporlama için)
        kiralama_geliri_try = EkipmanRaporuService._calculate_kirlama_geliri(
            ekipman_id, start_date, end_date, 
            target_currency='TRY',
            usd_rate=1,
            eur_rate=1
        )
        
        # Servis masrafları
        servis_giderleri_try = EkipmanRaporuService._calculate_servis_giderleri(
            ekipman_id, start_date, end_date
        )

        # Nakliye masrafları
        nakliye_giderleri_try = EkipmanRaporuService._calculate_nakliye_giderleri(
            ekipman_id, start_date, end_date
        )

        # Nakliye özeti (sefer sayısı + satış geliri)
        nakliye_ozeti = EkipmanRaporuService._calculate_nakliye_ozeti(
            ekipman_id, start_date, end_date
        )

        total_masraf = servis_giderleri_try + nakliye_giderleri_try
        
        # Net Gelir Hesaplama (TRY cinsinden)
        net_gelir_try = kiralama_geliri_try - total_masraf
        
        # Net Gelir Hesaplama (orijinal para biriminde)
        # Masrafları orijinal para birimine çevir
        if rapor_para_birimi == 'TRY':
            net_gelir_orijinal = kiralama_geliri_orijinal - total_masraf
        else:
            # Masrafları orijinal para birimine çevir
            if rapor_para_birimi == 'USD' and usd_rate > 0:
                masraf_orijinal = total_masraf / Decimal(usd_rate)
            elif rapor_para_birimi == 'EUR' and eur_rate > 0:
                masraf_orijinal = total_masraf / Decimal(eur_rate)
            else:
                masraf_orijinal = total_masraf  # Dönüştürülemedi, TRY olarak bırak
            
            net_gelir_orijinal = kiralama_geliri_orijinal - masraf_orijinal
        
        # ROI Hesaplaması (orijinal para biriminde)
        if rapor_para_birimi != 'TRY' and float(ekipman.giris_maliyeti or 0) > 0:
            # Orijinal para biriminde hesapla
            roi_yuzde = (float(net_gelir_orijinal) / float(ekipman.giris_maliyeti)) * 100
        elif temin_bedeli_try > 0:
            roi_yuzde = (net_gelir_try / Decimal(temin_bedeli_try)) * 100
        else:
            roi_yuzde = 0
        
        # Durum Belirleme
        durum = EkipmanRaporuService._determine_status(roi_yuzde)
        
        # Kiralama istatistikleri
        kiralama_stats = EkipmanRaporuService._get_kiralama_istatistikleri(
            ekipman_id, start_date, end_date
        )
        
        return {
            'ekipman_id': ekipman_id,
            'ekipman_kodu': ekipman.kod,
            'ekipman_adi': f"{ekipman.marka} - {ekipman.model}",
            'para_birimi': rapor_para_birimi,
            'giris_maliyeti_orijinal': float(ekipman.giris_maliyeti or 0.0),
            'temin_bedeli_try': float(temin_bedeli_try),
            'kur_bilgisi_eksik': kur_eksik,
            'temin_tarihi': temin_tarihi,
            'temin_doviz_kuru_usd': float(ekipman.temin_doviz_kuru_usd or 0),
            'temin_doviz_kuru_eur': float(ekipman.temin_doviz_kuru_eur or 0),
            'rapor_doviz_kuru_usd': float(usd_rate or 0),
            'rapor_doviz_kuru_eur': float(eur_rate or 0),
            'kiralama_geliri_orijinal': float(kiralama_geliri_orijinal),
            'kiralama_geliri_try': float(kiralama_geliri_try),
            'servis_giderleri_try': float(servis_giderleri_try),
            'nakliye_giderleri_try': float(nakliye_giderleri_try),
            'toplam_giderler_try': float(total_masraf),
            'net_gelir_orijinal': float(net_gelir_orijinal),
            'net_gelir_try': float(net_gelir_try),
            'roi_yuzde': float(roi_yuzde),
            'durum': durum,
            'start_date': start_date,
            'end_date': end_date,
            'kiralama_istatistikleri': kiralama_stats,
            'nakliye_ozeti': nakliye_ozeti,
        }
    
    @staticmethod
    def _convert_to_try(amount: float, currency: str, usd_rate: float, eur_rate: float) -> tuple:
        """
        Tutarı belirtilen para biriminden TRY'ye çevirir.
        Kur bilgisi yoksa (0 ise), orijinal tutarı döndürür ve uyarı işareti verir.
        
        Args:
            amount: Tutarın değeri
            currency: Para birimi (TRY, USD, EUR, GBP)
            usd_rate: USD/TRY kuru
            eur_rate: EUR/TRY kuru
            
        Returns:
            tuple: (try_tutarı, kur_eksik_mi)
        """
        if currency == 'TRY':
            return (amount, False)
        elif currency == 'USD':
            if usd_rate and usd_rate > 0:
                return (amount * usd_rate, False)
            else:
                # Kur girilmemiş, orijinal tutarı döndür ve uyarı ver
                return (amount, True)
        elif currency == 'EUR':
            if eur_rate and eur_rate > 0:
                return (amount * eur_rate, False)
            else:
                # Kur girilmemiş, orijinal tutarı döndür ve uyarı ver
                return (amount, True)
        else:
            # Bilinmeyen para birimi
            return (amount, True)

    @staticmethod
    def _get_kiralama_kuru(ekipman_id: int, currency: str, start_date: date = None, end_date: date = None) -> float:
        """Ekipmana ait kiralamalardan pozitif kur ortalamasını döner."""
        if currency == 'USD':
            kur_kolonu = Kiralama.doviz_kuru_usd
        elif currency == 'EUR':
            kur_kolonu = Kiralama.doviz_kuru_eur
        else:
            return 0.0

        query = db.session.query(func.avg(kur_kolonu)).select_from(KiralamaKalemi).join(
            Kiralama, Kiralama.id == KiralamaKalemi.kiralama_id
        ).filter(
            KiralamaKalemi.ekipman_id == ekipman_id,
            KiralamaKalemi.is_active == True,
            kur_kolonu.isnot(None),
            kur_kolonu > 0
        )

        if start_date:
            query = query.filter(KiralamaKalemi.kiralama_bitis >= start_date)
        if end_date:
            query = query.filter(KiralamaKalemi.kiralama_baslangici <= end_date)

        ortalama_kur = query.scalar()
        return float(ortalama_kur or 0.0)
    
    @staticmethod
    def _calculate_kirlama_geliri(ekipman_id: int, start_date: date = None, end_date: date = None, target_currency: str = 'TRY', usd_rate: float = 1, eur_rate: float = 1) -> Decimal:
        """
        Makinenin belirtilen tarih aralığında elde ettiği kiralama gelirini hesaplar.
        Belirtilen para birimine dönüştürülmüş şekilde.
        
        Args:
            ekipman_id: Makine ID
            start_date: Başlangıç tarihi
            end_date: Bitiş tarihi
            target_currency: Hedef para birimi (TRY, USD, EUR)
            usd_rate: USD/TRY kuru (dönüştürme için)
            eur_rate: EUR/TRY kuru (dönüştürme için)
        """
        query = db.session.query(KiralamaKalemi).filter(
            KiralamaKalemi.ekipman_id == ekipman_id,
            KiralamaKalemi.is_deleted == False
        )
        
        # Tarih aralığı filtresi: kirlama ile aranan dönem çakışıyor mu?
        if start_date:
            # Kiralama bitiş tarihi arama başlangıcından sonra olmalı
            query = query.filter(KiralamaKalemi.kiralama_bitis >= start_date)
        if end_date:
            # Kiralama başlangıç tarihi arama bitiş tarihinden önce olmalı
            query = query.filter(KiralamaKalemi.kiralama_baslangici <= end_date)
        
        kiralamalar = query.all()
        
        total_gelir = Decimal(0)
        
        for kalem in kiralamalar:
            kalem_bas = kalem.kiralama_baslangici
            kalem_bit = kalem.kiralama_bitis

            # Filtre ile kiralama aralığının kesişimini gün bazında (inclusive) hesapla
            etkin_bas = max(kalem_bas, start_date) if start_date else kalem_bas
            etkin_bit = min(kalem_bit, end_date) if end_date else kalem_bit
            gun_sayisi = max(0, (etkin_bit - etkin_bas).days + 1)

            kiralama_fiyat = Decimal(kalem.kiralama_brm_fiyat or 0)
            toplam_kalem_geliri = kiralama_fiyat * gun_sayisi

            # Kalemin kendi kurunu kullan; yoksa rapor kuruna düş
            kalem_usd = float(kalem.kiralama.doviz_kuru_usd or 0) or usd_rate
            kalem_eur = float(kalem.kiralama.doviz_kuru_eur or 0) or eur_rate

            # Hedef para birimine dönüştür
            if target_currency == 'USD' and kalem_usd > 0:
                converted = toplam_kalem_geliri / Decimal(kalem_usd)
            elif target_currency == 'EUR' and kalem_eur > 0:
                converted = toplam_kalem_geliri / Decimal(kalem_eur)
            else:
                converted = toplam_kalem_geliri

            total_gelir += converted
        
        return total_gelir
    
    @staticmethod
    def _calculate_servis_giderleri(ekipman_id: int, start_date: date = None, end_date: date = None) -> Decimal:
        """
        Makinenin belirtilen tarih aralığında yapılan servis masraflarını hesaplar.
        """
        query = BakimKaydi.query.filter(
            BakimKaydi.ekipman_id == ekipman_id,
            BakimKaydi.is_deleted == False,
        ).options(
            joinedload(BakimKaydi.kullanilan_parcalar)
        )

        if start_date:
            query = query.filter(BakimKaydi.tarih >= start_date)
        if end_date:
            query = query.filter(BakimKaydi.tarih <= end_date)

        toplam_gider = Decimal('0')
        for bakim_kaydi in query.all():
            toplam_gider += Decimal(bakim_kaydi.toplam_iscilik_maliyeti or 0)

            for parca in bakim_kaydi.kullanilan_parcalar:
                birim_fiyat = Decimal(parca.birim_fiyat or 0)

                if birim_fiyat <= 0 and parca.stok_karti_id:
                    son_stok_hareketi = StokHareket.query.filter(
                        StokHareket.stok_karti_id == parca.stok_karti_id,
                        StokHareket.hareket_tipi == 'giris',
                    ).order_by(StokHareket.tarih.desc(), StokHareket.id.desc()).first()
                    birim_fiyat = Decimal(son_stok_hareketi.birim_fiyat or 0) if son_stok_hareketi else Decimal('0')

                toplam_gider += Decimal(parca.kullanilan_adet or 0) * birim_fiyat

        return toplam_gider
    
    @staticmethod
    def _calculate_nakliye_giderleri(ekipman_id: int, start_date: date = None, end_date: date = None) -> Decimal:
        """
        Makinenin kiralamalarında ödenen nakliye alış maliyetlerini hesaplar.
        (Makinenin kendi kiralama kalemleri üzerindeki nakliye_alis_fiyat toplamı)
        """
        query = db.session.query(
            func.sum(KiralamaKalemi.nakliye_alis_fiyat).label('total_nakliye')
        ).filter(
            KiralamaKalemi.ekipman_id == ekipman_id,
            KiralamaKalemi.is_deleted == False
        )

        # Tarih aralığı filtresi: nakliye ile aranan dönem çakışıyor mu?
        if start_date:
            # Kiralama bitiş tarihi arama başlangıcından sonra olmalı
            query = query.filter(KiralamaKalemi.kiralama_bitis >= start_date)
        if end_date:
            # Kiralama başlangıç tarihi arama bitiş tarihinden önce olmalı
            query = query.filter(KiralamaKalemi.kiralama_baslangici <= end_date)
        
        result = query.first()
        
        if not result or result.total_nakliye is None:
            return Decimal(0)
        
        return Decimal(result.total_nakliye)
    
    @staticmethod
    def _calculate_nakliye_ozeti(ekipman_id: int, start_date: date = None, end_date: date = None) -> dict:
        """
        Makinenin nakliye istatistiklerini döner:
        - Nakliyeli sefer sayısı (gidiş + dönüş ayrı ayrı sayılır)
        - Toplam nakliye satış geliri (TRY)
        """
        query = db.session.query(KiralamaKalemi).filter(
            KiralamaKalemi.ekipman_id == ekipman_id,
            KiralamaKalemi.is_deleted == False,
        )
        if start_date:
            query = query.filter(KiralamaKalemi.kiralama_bitis >= start_date)
        if end_date:
            query = query.filter(KiralamaKalemi.kiralama_baslangici <= end_date)

        sefer_sayisi = 0
        satis_geliri = Decimal(0)

        for kalem in query.all():
            gidis_var = (kalem.nakliye_satis_fiyat or 0) > 0 or (kalem.nakliye_alis_fiyat or 0) > 0 or kalem.nakliye_araci_id or kalem.nakliye_tedarikci_id
            donus_var = (kalem.donus_nakliye_satis_fiyat or 0) > 0

            if gidis_var:
                sefer_sayisi += 1
            if donus_var:
                sefer_sayisi += 1

            satis_geliri += Decimal(kalem.nakliye_satis_fiyat or 0)
            satis_geliri += Decimal(kalem.donus_nakliye_satis_fiyat or 0)

        return {
            'sefer_sayisi': sefer_sayisi,
            'satis_geliri_try': float(satis_geliri),
        }

    @staticmethod
    def _determine_status(roi_yuzde: float) -> str:
        """
        ROI yüzdesine göre makine durumunu belirler
        """
        if roi_yuzde < 0:
            return "amorti_olmadi_zarar"  # Henüz amorti olmadı (zarar)
        elif roi_yuzde < 20:
            return "amorti_surecinde"  # Amorti süreci başladı
        elif roi_yuzde < 100:
            return "amorti_surecinde"  # Hala amorti süreci içinde
        elif roi_yuzde < 200:
            return "amorti_oldu"  # Kendini amorti etti
        else:
            return "kar_asamasi"  # Kâr aşamasında
    
    @staticmethod
    def _get_kiralama_istatistikleri(ekipman_id: int, start_date: date = None, end_date: date = None) -> dict:
        """
        Kiralama istatistiklerini (sayı, gün, vb) hesaplar
        """
        query = KiralamaKalemi.query.filter(
            KiralamaKalemi.ekipman_id == ekipman_id,
            KiralamaKalemi.is_deleted == False
        )
        
        # Tarih aralığı ile kesişen tüm kiralamalar (kırpılacak)
        if start_date and end_date:
            # Başlangıcı end_date'den önce, bitişi start_date'den sonra olan kiralamalar
            query = query.filter(and_(
                KiralamaKalemi.kiralama_bitis >= start_date,
                KiralamaKalemi.kiralama_baslangici <= end_date
            ))
        elif start_date:
            query = query.filter(KiralamaKalemi.kiralama_bitis >= start_date)
        elif end_date:
            query = query.filter(KiralamaKalemi.kiralama_baslangici <= end_date)
        
        kiralamalar = query.all()
        
        toplam_gu = 0
        toplam_kiralama = len(kiralamalar)
        musteri_listesi = set()
        
        for kalem in kiralamalar:
            # Başlangıç ve bitiş tarihini sınırlandır (aralığa göre kırp)
            baslangic = max(kalem.kiralama_baslangici, start_date) if start_date else kalem.kiralama_baslangici
            bitis = min(kalem.kiralama_bitis, end_date) if end_date else kalem.kiralama_bitis
            
            # Gün sayısını hesapla (inclusive + negatif koruma)
            gu = max(0, (bitis - baslangic).days + 1)
            toplam_gu += gu
            if kalem.kiralama.firma_musteri:
                musteri_listesi.add(kalem.kiralama.firma_musteri.firma_adi)
        
        return {
            'toplam_kiralama_sayisi': toplam_kiralama,
            'toplam_gun_sayisi': toplam_gu,
            'ortalama_gun_per_kiralama': toplam_gu / toplam_kiralama if toplam_kiralama > 0 else 0,
            'farkli_musteri_sayisi': len(musteri_listesi),
            'musteriler': list(musteri_listesi)
        }
    
    @staticmethod
    def get_kiralama_detaylari(ekipman_id: int, start_date: date = None, end_date: date = None) -> list:
        """
        Makinenin belirtilen tarih aralığındaki tüm kiralama detaylarını döner
        """
        query = KiralamaKalemi.query.filter(
            KiralamaKalemi.ekipman_id == ekipman_id,
            KiralamaKalemi.is_deleted == False
        ).join(Kiralama).order_by(KiralamaKalemi.kiralama_baslangici.desc())
        
        # Tarih aralığı filtresi: kiralama ile aranan dönem çakışıyor mu?
        if start_date:
            # Kiralama bitiş tarihi arama başlangıcından sonra olmalı
            query = query.filter(KiralamaKalemi.kiralama_bitis >= start_date)
        if end_date:
            # Kiralama başlangıç tarihi arama bitiş tarihinden önce olmalı
            query = query.filter(KiralamaKalemi.kiralama_baslangici <= end_date)
        
        kiralamalar = query.all()
        
        detaylar = []
        for kalem in kiralamalar:
            # Kiralama tarihleri
            kalem_bas = kalem.kiralama_baslangici
            kalem_bit = kalem.kiralama_bitis or date.today()

            # Filtre aralığı ile kesişim (gün sayısı ve gelir hesabı için tutarlı)
            etkin_bas = max(kalem_bas, start_date) if start_date else kalem_bas
            etkin_bit = min(kalem_bit, end_date) if end_date else kalem_bit
            filtre_gun = max(0, (etkin_bit - etkin_bas).days + 1)

            # Döviz cinsinden gelir hesapla
            gelir_try = float(kalem.kiralama_brm_fiyat or 0) * filtre_gun
            gelir_usd = gelir_try / float(kalem.kiralama.doviz_kuru_usd or 1) if kalem.kiralama.doviz_kuru_usd else 0
            gelir_eur = gelir_try / float(kalem.kiralama.doviz_kuru_eur or 1) if kalem.kiralama.doviz_kuru_eur else 0

            detaylar.append({
                'kiralama_no': kalem.kiralama.kiralama_form_no,
                'musteri': kalem.kiralama.firma_musteri.firma_adi if kalem.kiralama.firma_musteri else '-',
                'baslangic_tarihi': kalem_bas,
                'bitis_tarihi': kalem_bit,
                'gun_sayisi': filtre_gun,
                'gelir_try': gelir_try,
                'gelir_usd': gelir_usd,
                'gelir_eur': gelir_eur,
                'doviz_kuru_usd': float(kalem.kiralama.doviz_kuru_usd or 0),
                'doviz_kuru_eur': float(kalem.kiralama.doviz_kuru_eur or 0)
            })
        
        return detaylar
