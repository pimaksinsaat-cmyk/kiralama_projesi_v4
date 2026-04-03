from datetime import date
from decimal import Decimal
import logging
from sqlalchemy import func
from app.extensions import db
from app.fatura.models import Hakedis, HakedisKalemi
from app.kiralama.models import Kiralama, KiralamaKalemi
from app.services.base import BaseService, ValidationError
from app.cari.models import HizmetKaydi
from app.services.cari_services import HizmetKaydiService

logger = logging.getLogger(__name__)


class FaturaService(BaseService):
    model = Hakedis

    @staticmethod
    def _hakedis_no_uret():
        """
        Benzersiz hakediş numarası üretir.
        DB'deki toplam kayıt sayısına göre sıralı numara verir.
        Örn: HKD-202403-0001
        """
        son_id = db.session.query(func.count(Hakedis.id)).scalar() or 0
        return f"HKD-{date.today().strftime('%Y%m')}-{str(son_id + 1).zfill(4)}"

    @staticmethod
    def hakedis_olustur(kiralama_id, baslangic, bitis,
                         fatura_senaryosu='TEMELFATURA', fatura_tipi='SATIS',
                         para_birimi='TRY', kur_degeri=None,
                         proje_adi=None, santiye_adresi=None,
                         actor_id=None):
        """
        Sözleşmedeki ekipmanları tarar ve tarih kesişimine göre
        otomatik hakediş taslağı oluşturur.
        """
        try:
            # 1. Sözleşme Kontrolü
            kiralama = db.session.get(Kiralama, kiralama_id)
            if not kiralama:
                raise ValidationError("Seçilen sözleşme (PS) sistemde bulunamadı.")

            # 2. Para Birimi / Kur Kontrolü
            if para_birimi != 'TRY' and (not kur_degeri or kur_degeri <= 0):
                raise ValidationError("Dövizli işlemlerde geçerli bir kur değeri girilmelidir.")

            # 3. Tarih Çakışma Kontrolü
            cakisma = Hakedis.query.filter(
                Hakedis.kiralama_id == kiralama_id,
                Hakedis.is_deleted == False,
                Hakedis.durum != 'iptal',
                Hakedis.baslangic_tarihi <= bitis,
                Hakedis.bitis_tarihi >= baslangic
            ).first()
            if cakisma:
                raise ValidationError(
                    f"Bu tarihler için zaten bir hakediş ({cakisma.hakedis_no}) mevcut!"
                )

            # 4. Hakediş Oluştur
            yeni_hakedis = Hakedis(
                hakedis_no=FaturaService._hakedis_no_uret(),
                firma_id=kiralama.firma_musteri_id,
                kiralama_id=kiralama.id,
                proje_adi=proje_adi or getattr(kiralama, 'proje_adi', 'Belirtilmemiş'),
                santiye_adresi=santiye_adresi,
                baslangic_tarihi=baslangic,
                bitis_tarihi=bitis,
                fatura_senaryosu=fatura_senaryosu,
                fatura_tipi=fatura_tipi,
                para_birimi=para_birimi,
                kur_degeri=Decimal(str(kur_degeri)) if kur_degeri else Decimal('1.0000'),
                created_by_id=actor_id,
                durum='taslak'
            )
            db.session.add(yeni_hakedis)
            db.session.flush()  # ID almak için

            # 5. Kalemleri Hesapla
            total_matrah   = Decimal('0')
            total_kdv      = Decimal('0')
            total_tevkifat = Decimal('0')
            ekipman_sayisi = 0

            for kalem in kiralama.kalemler:

                # Sadece aktif kalemleri işle
                if not kalem.is_active:
                    continue

                k_bas = kalem.kiralama_baslangici
                # sonlandirildi=True ise gerçek bitiş tarihini, değilse sahada hâlâ var kabul et
                k_bit = kalem.kiralama_bitis if kalem.sonlandirildi else date(2099, 12, 31)

                # Hakediş dönemi ile makinenin sahadaki süresinin kesişimi
                akt_bas = max(baslangic, k_bas)
                akt_bit = min(bitis, k_bit)

                if akt_bas > akt_bit:
                    continue  # Bu kalem bu dönemde sahada değil

                gun_sayisi = (akt_bit - akt_bas).days + 1
                ekipman_sayisi += 1

                # DÜZELTME: birim_fiyat → kiralama_brm_fiyat
                birim_fiyat = Decimal(str(kalem.kiralama_brm_fiyat or 0))
                ara_tutar   = Decimal(str(gun_sayisi)) * birim_fiyat

                # İskonto — KiralamaKalemi'nde iskonto yok, 0 kabul et
                iskontolu_tutar = ara_tutar

                # KDV — Kiralama ana modelinden al (kalem bazında kdv_orani yok)
                kdv_orani_yuzdesi = int(kiralama.kdv_orani or 20)
                kdv_orani         = Decimal(str(kdv_orani_yuzdesi)) / 100
                kdv_tutari        = iskontolu_tutar * kdv_orani

                # Tevkifat — KiralamaKalemi'nde yok, şimdilik 0
                tevkifat_tutari = Decimal('0')
                tevkifat_kodu   = None
                tevkifat_orani  = None

                satir_toplami = iskontolu_tutar + kdv_tutari

                hk = HakedisKalemi(
                    hakedis_id=yeni_hakedis.id,
                    kiralama_kalemi_id=kalem.id,
                    ekipman_id=kalem.ekipman_id,
                    miktar=gun_sayisi,
                    birim_tipi='DAY',
                    birim_fiyat=birim_fiyat,
                    ara_toplam=ara_tutar,
                    iskonto_orani=None,
                    iskonto_tutari=Decimal('0'),
                    kdv_orani=kdv_orani_yuzdesi,
                    kdv_tutari=kdv_tutari,
                    tevkifat_kodu=tevkifat_kodu,
                    tevkifat_orani=tevkifat_orani,
                    tevkifat_tutari=tevkifat_tutari,
                    satir_toplami=satir_toplami
                )
                db.session.add(hk)

                total_matrah   += iskontolu_tutar
                total_kdv      += kdv_tutari
                total_tevkifat += tevkifat_tutari

            if ekipman_sayisi == 0:
                raise ValidationError(
                    "Seçilen tarih aralığında sahada olan ekipman bulunamadı."
                )

            # 6. Toplamları Güncelle
            yeni_hakedis.toplam_matrah   = total_matrah
            yeni_hakedis.toplam_kdv      = total_kdv
            yeni_hakedis.toplam_tevkifat = total_tevkifat
            yeni_hakedis.genel_toplam    = total_matrah + total_kdv - total_tevkifat

            db.session.commit()
            logger.info(f"Hakediş oluşturuldu: {yeni_hakedis.hakedis_no}")
            return yeni_hakedis

        except ValidationError:
            db.session.rollback()
            raise
        except Exception as e:
            db.session.rollback()
            logger.error(f"Hakediş oluşturma hatası: {str(e)}", exc_info=True)
            raise Exception(f"Sistemsel hata: {str(e)}")

    @staticmethod
    def cariye_isle(hakedis_id, actor_id=None):
        """
        Hakedişi onaylar ve Cari modüle borç olarak kaydeder.
        Sadece 'taslak' durumundaki hakedişler onaylanabilir.
        """
        try:
            hakedis = db.session.get(Hakedis, hakedis_id)

            if not hakedis:
                raise ValidationError("Hakediş bulunamadı.")
            if hakedis.is_deleted:
                raise ValidationError("Silinmiş hakediş onaylanamaz.")
            if hakedis.durum != 'taslak':
                raise ValidationError(
                    f"Sadece taslak durumundaki hakedişler onaylanabilir. "
                    f"Mevcut durum: {hakedis.durum}"
                )

            # Cari Hizmet Kaydı Oluştur
            aciklama = (
                f"{hakedis.hakedis_no} Nolu Hakediş "
                f"({hakedis.baslangic_tarihi} - {hakedis.bitis_tarihi})"
            )
            hizmet = HizmetKaydi(
                firma_id=hakedis.firma_id,
                tarih=date.today(),
                tutar=hakedis.genel_toplam,
                yon='giden',        # Gelir: Müşteri borçlanır
                ozel_id=hakedis.id, # Hakedişe geri referans
                aciklama=aciklama,
                created_by_id=actor_id
            )

            # HizmetKaydiService üzerinden kaydet — cari bakiye otomatik güncellenir
            HizmetKaydiService.save(hizmet, is_new=True, actor_id=actor_id)

            # Hakediş durumunu güncelle
            hakedis.cari_hareket_id = hizmet.id  # FK bağlantısı
            hakedis.durum           = 'onaylandi'
            hakedis.is_faturalasti  = True

            db.session.commit()
            logger.info(f"Hakediş cariye işlendi: {hakedis.hakedis_no}")
            return hakedis

        except ValidationError:
            db.session.rollback()
            raise
        except Exception as e:
            db.session.rollback()
            logger.error(f"Cariye işleme hatası: {str(e)}", exc_info=True)
            raise Exception(f"Sistemsel hata: {str(e)}")

    @staticmethod
    def hakedis_iptal(hakedis_id, actor_id=None):
        """
        Hakedişi iptal eder.
        Cariye işlenmiş hakedişler iptal edilemez.
        """
        try:
            hakedis = db.session.get(Hakedis, hakedis_id)
            if not hakedis:
                raise ValidationError("Hakediş bulunamadı.")
            if hakedis.durum in ('onaylandi', 'faturalasti'):
                raise ValidationError(
                    "Cariye işlenmiş veya faturalanmış hakediş iptal edilemez. "
                    "Lütfen muhasebe ile iletişime geçin."
                )
            hakedis.durum          = 'iptal'
            hakedis.updated_by_id  = actor_id
            db.session.commit()
            logger.info(f"Hakediş iptal edildi: {hakedis.hakedis_no}")
            return hakedis

        except ValidationError:
            db.session.rollback()
            raise
        except Exception as e:
            db.session.rollback()
            logger.error(f"Hakediş iptal hatası: {str(e)}", exc_info=True)
            raise Exception(f"Sistemsel hata: {str(e)}")