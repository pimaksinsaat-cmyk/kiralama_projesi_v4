from app.extensions import db
from app.cari.models import HizmetKaydi
from decimal import Decimal


def _net_kdv_orani(kdv_orani, tevkifat_str):
    """Tevkifat uygulayarak efektif KDV oranını döner. Örn: 20 & '2/10' → 16"""
    if not tevkifat_str or not kdv_orani:
        return kdv_orani
    try:
        pay, payda = map(int, str(tevkifat_str).split('/'))
        return kdv_orani * (payda - pay) / payda
    except (ValueError, ZeroDivisionError):
        return kdv_orani

class CariServis:
    """
    Tüm modüllerin (Nakliye vb.) cari hesap işlemlerini tek bir merkezden yöneten,
    kod tekrarını önleyen ve veri bütünlüğünü sağlayan servis katmanı.
    """

    # ==========================================
    # 1. NAKLİYE OPERASYONLARI (MEVCUT SENKRONİZASYON)
    # ==========================================

    @staticmethod
    def musteri_nakliye_senkronize_et(nakliye):
        """
        Nakliye kaydına göre müşterinin (satış) cari hareketini yönetir.
        """
        # Nakliye kaydına bağlı bir cari hareket var mı bakıyoruz
        hizmet = HizmetKaydi.query.filter_by(nakliye_id=nakliye.id, yon='giden').first()

        aciklama = f"Nakliye Hizmeti: {nakliye.plaka or ''} | {nakliye.guzergah}"
        
        nakliye_islem_tarihi = getattr(nakliye, 'islem_tarihi', None) or nakliye.tarih
        if hizmet:
            # Varsa güncelle (Firma, Tarih, Tutar veya KDV değişmiş olabilir)
            hizmet.firma_id = nakliye.firma_id
            hizmet.tarih = nakliye.tarih
            hizmet.islem_tarihi = nakliye_islem_tarihi
            hizmet.tutar = nakliye.toplam_tutar
            hizmet.aciklama = aciklama
            hk_kdv = getattr(nakliye, 'kdv_orani', None) or 0
            hizmet.kdv_orani = _net_kdv_orani(hk_kdv, getattr(nakliye, 'tevkifat_orani', None) or '')
        else:
            # Yoksa yeni oluştur
            hk_kdv = getattr(nakliye, 'kdv_orani', None) or 0
            hizmet = HizmetKaydi(
                firma_id=nakliye.firma_id,
                tarih=nakliye.tarih,
                islem_tarihi=nakliye_islem_tarihi,
                tutar=nakliye.toplam_tutar,
                yon='giden', # Müşteriye giden hizmet = Borç
                aciklama=aciklama,
                nakliye_id=nakliye.id,
                kdv_orani=_net_kdv_orani(hk_kdv, getattr(nakliye, 'tevkifat_orani', None) or '')
            )
            db.session.add(hizmet)

    @staticmethod
    def taseron_maliyet_senkronize_et(nakliye):
        """
        Taşeron nakliyelerde tedarikçinin alacak kaydını (maliyet) yönetir.
        """
        # Taşeron maliyetlerini ozel_id üzerinden takip ediyoruz
        eski_maliyet = HizmetKaydi.query.filter_by(ozel_id=nakliye.id, yon='gelen').first()

        nakliye_islem_tarihi = getattr(nakliye, 'islem_tarihi', None) or nakliye.tarih
        if nakliye.nakliye_tipi == 'taseron' and nakliye.taseron_firma_id and nakliye.taseron_maliyet > 0:
            aciklama = f"Nakliye Taşeron Gideri: {nakliye.guzergah} ({nakliye.plaka or ''})"
            if eski_maliyet:
                # Tedarikçi veya maliyet tutarı değişmiş olabilir
                eski_maliyet.firma_id = nakliye.taseron_firma_id
                eski_maliyet.tutar = nakliye.taseron_maliyet
                eski_maliyet.tarih = nakliye.tarih
                eski_maliyet.islem_tarihi = nakliye_islem_tarihi
                eski_maliyet.aciklama = aciklama
            else:
                # Yeni maliyet kaydı oluştur
                hk_kdv = getattr(nakliye, 'kdv_orani', None)
                if hk_kdv is None:
                    hk_kdv = 0
                yeni_maliyet = HizmetKaydi(
                    firma_id=nakliye.taseron_firma_id,
                    tarih=nakliye.tarih,
                    islem_tarihi=nakliye_islem_tarihi,
                    tutar=nakliye.taseron_maliyet,
                    yon='gelen', # Bize gelen hizmet = Taşeron Alacağı (Gider)
                    aciklama=aciklama,
                    ozel_id=nakliye.id,
                    kdv_orani=hk_kdv,
                    nakliye_alis_kdv=hk_kdv
                )
                db.session.add(yeni_maliyet)
        elif eski_maliyet:
            # Eğer nakliye tipi 'öz mal'a döndüyse veya maliyet 0 yapıldıysa kaydı temizle
            db.session.delete(eski_maliyet)

    # ==========================================
    # 2. TEMİZLİK (SİLME) İŞLEMLERİ
    # ==========================================

    @staticmethod
    def nakliye_cari_temizle(nakliye_id):
        """
        Nakliye silindiğinde bağlı tüm cari kayıtları (Müşteri Borcu + Taşeron Alacağı) 
        tek bir sorguyla güvenli bir şekilde siler.
        """
        HizmetKaydi.query.filter(
            (HizmetKaydi.nakliye_id == nakliye_id) | 
            ((HizmetKaydi.ozel_id == nakliye_id) & (HizmetKaydi.yon == 'gelen'))
        ).delete()