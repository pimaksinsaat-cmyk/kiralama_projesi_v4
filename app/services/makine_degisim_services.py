from app.services.base import BaseService, ValidationError
from app.extensions import db
from sqlalchemy import func
from app.kiralama.models import KiralamaKalemi
from app.makinedegisim.models import MakineDegisim
from app.filo.models import Ekipman
from app.nakliyeler.models import Nakliye
from app.araclar.models import Arac
from datetime import datetime, timedelta
from decimal import Decimal

# Kötü bir pratik olan "Rotadan fonksiyon çağırma" işlemini mecburiyetten koruyoruz
# TODO: İleride guncelle_cari_toplam mantığı KiralamaService içine taşınmalı!
from app.services.kiralama_services import guncelle_cari_toplam 

try:
    from app.cari.models import HizmetKaydi
except ImportError:
    HizmetKaydi = None

# --- CARİ SERVİS ENTEGRASYONU ---
try:
    from app.services.nakliye_services import CariServis
except ImportError:
    CariServis = None


class MakineDegisimService(BaseService):
    """Makine değişim/swap operasyonları ve cari entegrasyonlarının yönetildiği servis."""
    model = MakineDegisim
    use_soft_delete = False

    @classmethod
    def degisim_uygula(cls, eski_kalem_id, data, actor_id=None):
        """Aktif makineyi sahadan çeker, yeni makineyi sahaya sürer ve finansal kayıtları oluşturur."""
        eski_kalem = db.session.get(KiralamaKalemi, eski_kalem_id)
        if not eski_kalem or not eski_kalem.is_active:
            raise ValidationError("Sadece aktif makine üzerinden değişim yapılabilir.")

        ana_kiralama_id = eski_kalem.kiralama_id
        secilen_tarih = data['degisim_tarihi']

        # 1. ZİNCİRDEKİ GERÇEK AKTİFİ BUL
        aktif_kalem = KiralamaKalemi.query.filter_by(
            kiralama_id=ana_kiralama_id,
            is_active=True
        ).filter(
            (KiralamaKalemi.id == eski_kalem.id) |
            (KiralamaKalemi.parent_id == eski_kalem.id)
        ).first()

        if not aktif_kalem:
            aktif_kalem = eski_kalem

        # 2. TARİH KONTROLLERİ
        if secilen_tarih < aktif_kalem.kiralama_baslangici:
            raise ValidationError(f"Değişim tarihi, başlangıç/değişim tarihinden ({aktif_kalem.kiralama_baslangici.strftime('%d.%m.%Y')}) önce olamaz!")

        guncel_bitis_tarihi = eski_kalem.kiralama_bitis
        if secilen_tarih > guncel_bitis_tarihi:
            guncel_bitis_tarihi = secilen_tarih

        # İşlemleri başlat (Transaction)
        try:
            swap_nakliye = None
            swap_taseron_hizmeti = None
            swap_kira_hizmeti = None

            # 3. AKTİFİ PASİF YAP VE ESKİ MAKİNEYİ YÖNLENDİR
            eski_bitis = secilen_tarih - timedelta(days=1)
            aktif_kalem.is_active = False
            aktif_kalem.sonlandirildi = True
            aktif_kalem.kiralama_bitis = eski_bitis
            aktif_kalem.degisim_tarihi = datetime.combine(secilen_tarih, datetime.min.time())
            aktif_kalem.degisim_nedeni = data['neden']

            if aktif_kalem.ekipman_id:
                eski_makine_obj = db.session.get(Ekipman, aktif_kalem.ekipman_id)
                if eski_makine_obj:
                    donus_sube = data.get('donus_sube_val')
                    if donus_sube == 'tedarikci':
                        eski_makine_obj.calisma_durumu = 'iade_edildi'
                        eski_makine_obj.sube_id = None
                    elif donus_sube and str(donus_sube).isdigit():
                        # ŞUBE ATAMA ÇÖZÜMÜ
                        eski_makine_obj.calisma_durumu = data['neden']
                        eski_makine_obj.sube_id = int(donus_sube)

            # 4. YENİ KALEM OLUŞTUR
            yeni_kalem = KiralamaKalemi(
                kiralama_id=ana_kiralama_id,
                kiralama_baslangici=secilen_tarih,
                kiralama_bitis=guncel_bitis_tarihi,
                kiralama_brm_fiyat=data.get('kiralama_brm_fiyat') or Decimal('0.00'),
                kiralama_alis_fiyat=aktif_kalem.kiralama_alis_fiyat or Decimal('0.00'),
                parent_id=aktif_kalem.id,
                versiyon_no=(aktif_kalem.versiyon_no or 1) + 1,
                is_active=True,
                sonlandirildi=False
            )

            # EKSİK VERİLERİ YENİ KALEME KAYDET (Dış Tedarik & Öz Mal)
            if data.get('is_dis_tedarik'):
                yeni_kalem.is_dis_tedarik_ekipman = True
                yeni_kalem.harici_ekipman_tedarikci_id = data.get('harici_ekipman_tedarikci_id')
                yeni_kalem.harici_ekipman_marka = data.get('harici_marka')
                yeni_kalem.harici_ekipman_model = data.get('harici_model')
                yeni_kalem.harici_ekipman_seri_no = data.get('harici_seri_no')
                yeni_kalem.harici_ekipman_tipi = data.get('harici_tipi')
                yeni_kalem.harici_ekipman_kapasite = data.get('harici_kapasite') or None
                yeni_kalem.harici_ekipman_yukseklik = data.get('harici_yukseklik') or None
                yeni_kalem.harici_ekipman_uretim_yili = data.get('harici_uretim_yili') or None
                yeni_kalem.kiralama_alis_fiyat = data.get('kiralama_alis_fiyat') or Decimal('0.00')
            elif data.get('yeni_ekipman_id'):
                yeni_kalem.ekipman_id = data['yeni_ekipman_id']
                yeni_makine_obj = db.session.get(Ekipman, yeni_kalem.ekipman_id)
                if yeni_makine_obj:
                    yeni_makine_obj.calisma_durumu = 'kirada'
                    # YENİ GİDEN MAKİNENİN MERKEZİ (ŞUBESİ) ARTIK SİLİNMİYOR
                    # yeni_makine_obj.sube_id = None 

            # Kalem İçi Nakliye Bilgileri
            yeni_kalem.nakliye_satis_fiyat = data.get('nakliye_satis_fiyat') or Decimal('0.00')
            if data.get('is_harici_nakliye'):
                yeni_kalem.is_harici_nakliye = True
                yeni_kalem.nakliye_alis_fiyat = data.get('nakliye_alis_fiyat') or Decimal('0.00')
                yeni_kalem.nakliye_tedarikci_id = data.get('nakliye_tedarikci_id')
            else:
                yeni_kalem.is_harici_nakliye = False
                yeni_kalem.nakliye_alis_fiyat = Decimal('0.00')
                yeni_kalem.nakliye_tedarikci_id = None
                yeni_kalem.nakliye_araci_id = data.get('nakliye_araci_id')

            db.session.add(yeni_kalem)
            db.session.flush() # ID almak için flush

            # =========================================================
            # 5. CARİ VE NAKLİYE ENTEGRASYONU 
            # =========================================================
            musteri_firma_adi = eski_kalem.kiralama.firma_musteri.firma_adi if eski_kalem.kiralama.firma_musteri else "Bilinmeyen"
            form_no = eski_kalem.kiralama.kiralama_form_no

            # --- MAKİNE İSİMLERİNİ TEMİZCE BULALIM ---
            eski_makine_ad = ""
            if aktif_kalem.ekipman_id:
                e_obj = db.session.get(Ekipman, aktif_kalem.ekipman_id)
                if e_obj:
                    eski_makine_ad = e_obj.kod
            if not eski_makine_ad:
                eski_makine_ad = f"{aktif_kalem.harici_ekipman_marka or ''} {aktif_kalem.harici_ekipman_model or ''}".strip()

            yeni_makine_ad = ""
            if yeni_kalem.ekipman_id:
                y_obj = db.session.get(Ekipman, yeni_kalem.ekipman_id)
                if y_obj:
                    yeni_makine_ad = y_obj.kod
            if not yeni_makine_ad:
                yeni_makine_ad = f"{data.get('harici_marka') or ''} {data.get('harici_model') or ''}".strip()
            
            # --- KULLANICININ İSTEDİĞİ ÖZEL AÇIKLAMA METNİ ---
            ozel_guzergah = f"{musteri_firma_adi} firmasından alınan {eski_makine_ad} makinenin {yeni_makine_ad} ile değişimi nakliye bedeli"
            
            # İptal fonksiyonunun bu kaydı bulabilmesi için teknik ve BENZERSİZ bir iz bırakıyoruz
            detayli_aciklama = f"Makine Değişim (Swap) Operasyonu [Ref:{yeni_kalem.id}]. Neden: {data['neden']}"

            is_harici = data.get('is_harici_nakliye')
            satis_fiyat = data.get('nakliye_satis_fiyat') or Decimal('0.00')
            alis_fiyat = data.get('nakliye_alis_fiyat') or Decimal('0.00')
            arac_id = data.get('nakliye_araci_id')

            # PLAKAYI BUL (Arac modelinden)
            plaka_str = None
            if not is_harici and arac_id:
                secili_arac = db.session.get(Arac, arac_id)
                if secili_arac:
                    plaka_str = secili_arac.plaka

            # NAKLİYE KAYDI OLUŞTUR
            if data.get('yeni_nakliye_ekle') or is_harici or satis_fiyat > 0 or alis_fiyat > 0 or arac_id:
                guncel_kdv = eski_kalem.kiralama.kdv_orani if eski_kalem.kiralama.kdv_orani is not None else 20
                
                yeni_nakliye = Nakliye(
                    kiralama_id=ana_kiralama_id,
                    tarih=secilen_tarih,
                    islem_tarihi=secilen_tarih,
                    firma_id=eski_kalem.kiralama.firma_musteri_id,
                    nakliye_tipi='taseron' if is_harici else 'oz_mal',
                    arac_id=arac_id if not is_harici else None,
                    taseron_firma_id=data.get('nakliye_tedarikci_id') if is_harici else None,
                    guzergah=ozel_guzergah,
                    plaka=plaka_str, 
                    tutar=satis_fiyat,
                    kdv_orani=guncel_kdv,
                    taseron_maliyet=alis_fiyat,
                    aciklama=detayli_aciklama,
                    cari_islendi_mi=True
                )
                yeni_nakliye.hesapla_ve_guncelle()
                db.session.add(yeni_nakliye)
                db.session.flush()
                swap_nakliye = yeni_nakliye

                # Cari Servis Entegrasyonu (Eğer ekliyse)
                if CariServis and hasattr(CariServis, 'musteri_nakliye_senkronize_et'):
                    if satis_fiyat > 0:
                        CariServis.musteri_nakliye_senkronize_et(yeni_nakliye)
                    if is_harici and alis_fiyat > 0:
                        CariServis.taseron_maliyet_senkronize_et(yeni_nakliye)
                        if HizmetKaydi:
                            db.session.flush()
                            swap_taseron_hizmeti = HizmetKaydi.query.filter_by(
                                ozel_id=yeni_nakliye.id,
                                yon='gelen'
                            ).order_by(HizmetKaydi.id.desc()).first()
                else:
                    # Manuel Hizmet Kaydı (Fallback)
                    if is_harici and alis_fiyat > 0 and HizmetKaydi and yeni_nakliye.taseron_firma_id:
                        swap_taseron_hizmeti = HizmetKaydi(
                            firma_id=yeni_nakliye.taseron_firma_id,
                            nakliye_id=yeni_nakliye.id,
                            tarih=secilen_tarih,
                            islem_tarihi=secilen_tarih,
                            tutar=alis_fiyat,
                            yon='gelen',
                            aciklama=ozel_guzergah,
                            fatura_no=form_no,
                            ozel_id=yeni_nakliye.id
                        )
                        db.session.add(swap_taseron_hizmeti)

            # Dış Tedarik Kira Cari Kaydı
            if yeni_kalem.is_dis_tedarik_ekipman and yeni_kalem.kiralama_alis_fiyat and yeni_kalem.kiralama_alis_fiyat > 0:
                if HizmetKaydi and yeni_kalem.harici_ekipman_tedarikci_id:
                    swap_kira_hizmeti = HizmetKaydi(
                        firma_id=yeni_kalem.harici_ekipman_tedarikci_id,
                        tarih=secilen_tarih,
                        islem_tarihi=secilen_tarih,
                        tutar=yeni_kalem.kiralama_alis_fiyat, 
                        yon='gelen',  
                        aciklama=f"{musteri_firma_adi} projesi {yeni_makine_ad} makinesi kira bedeli",
                        fatura_no=form_no,
                        ozel_id=yeni_kalem.id
                    )
                    db.session.add(swap_kira_hizmeti)

            db.session.flush()

            # 6. LOG OLUŞTURMA
            degisim_log = MakineDegisim(
                kiralama_id=ana_kiralama_id,
                eski_kalem_id=aktif_kalem.id,
                yeni_kalem_id=yeni_kalem.id,
                eski_ekipman_id=aktif_kalem.ekipman_id,
                yeni_ekipman_id=yeni_kalem.ekipman_id,
                swap_nakliye_id=swap_nakliye.id if swap_nakliye else None,
                swap_taseron_hizmet_id=swap_taseron_hizmeti.id if swap_taseron_hizmeti else None,
                swap_kira_hizmet_id=swap_kira_hizmeti.id if swap_kira_hizmeti else None,
                neden=data['neden'],
                tarih=datetime.combine(secilen_tarih, datetime.min.time())
            )
            db.session.add(degisim_log)
            db.session.commit()

            # Toplamları Güncelle
            guncelle_cari_toplam(ana_kiralama_id)

        except Exception as e:
            db.session.rollback()
            raise ValidationError(f"İşlem sırasında beklenmeyen hata: {str(e)}")

    @classmethod
    def iptal_et(cls, kalem_id, actor_id=None):
        """Makine değişimini iptal eder, cari hareketleri temizler ve makineleri eski konumlarına çeker."""
        eski_kalem = db.session.get(KiralamaKalemi, kalem_id)
        if not eski_kalem:
            raise ValidationError("Kayıt bulunamadı.")

        aktif_child = KiralamaKalemi.query.filter_by(parent_id=eski_kalem.id, is_active=True).first()
        if not aktif_child:
            raise ValidationError("İptal edilecek aktif değişim bulunamadı.")

        try:
            degisim_log = MakineDegisim.query.filter_by(yeni_kalem_id=aktif_child.id).first()

            # 1. OTOMATİK OLUŞAN NAKLİYE VE CARİ KAYDINI SİL 
            tarih_sorgu = aktif_child.degisim_tarihi.date() if aktif_child.degisim_tarihi else aktif_child.kiralama_baslangici

            silinecek_nakliye = None
            if degisim_log and degisim_log.swap_nakliye_id:
                silinecek_nakliye = db.session.get(Nakliye, degisim_log.swap_nakliye_id)

            if silinecek_nakliye is None:
                silinecek_nakliye = Nakliye.query.filter(
                    Nakliye.kiralama_id == eski_kalem.kiralama_id,
                    func.coalesce(Nakliye.islem_tarihi, Nakliye.tarih) == tarih_sorgu,
                    Nakliye.aciklama.like(f"Makine Değişim (Swap) Operasyonu [Ref:{aktif_child.id}]%")
                ).first()

            if silinecek_nakliye:
                if CariServis and hasattr(CariServis, 'nakliye_cari_temizle'):
                    CariServis.nakliye_cari_temizle(silinecek_nakliye.id)
                db.session.delete(silinecek_nakliye)
            elif degisim_log and degisim_log.swap_taseron_hizmet_id and HizmetKaydi:
                taseron_hizmeti = db.session.get(HizmetKaydi, degisim_log.swap_taseron_hizmet_id)
                if taseron_hizmeti:
                    db.session.delete(taseron_hizmeti)

            # 2. DIŞ TEDARİK MAKİNE KİRASINI İPTAL ET
            if HizmetKaydi and aktif_child.is_dis_tedarik_ekipman and aktif_child.harici_ekipman_tedarikci_id:
                kira_hizmeti = None
                if degisim_log and degisim_log.swap_kira_hizmet_id:
                    kira_hizmeti = db.session.get(HizmetKaydi, degisim_log.swap_kira_hizmet_id)

                if kira_hizmeti:
                    db.session.delete(kira_hizmeti)
                else:
                    iptal_makine_ad = f"{aktif_child.harici_ekipman_marka} {aktif_child.harici_ekipman_model}".strip()
                    musteri_firma_adi = eski_kalem.kiralama.firma_musteri.firma_adi if eski_kalem.kiralama.firma_musteri else "Bilinmeyen"
                    aciklama_metni_kira = f"{musteri_firma_adi} projesi {iptal_makine_ad} makinesi kira bedeli"
                    
                    HizmetKaydi.query.filter_by(
                        ozel_id=aktif_child.id,
                        firma_id=aktif_child.harici_ekipman_tedarikci_id,
                        yon='gelen',
                        aciklama=aciklama_metni_kira
                    ).delete(synchronize_session=False)

            # 3. YENİ MAKİNEYİ BOŞA ÇEK, ESKİ MAKİNEYİ SAHAYA DÖNDÜR
            if aktif_child.ekipman_id:
                yeni_makine = db.session.get(Ekipman, aktif_child.ekipman_id)
                if yeni_makine: yeni_makine.calisma_durumu = 'bosta'

            if eski_kalem.ekipman_id:
                eski_makine = db.session.get(Ekipman, eski_kalem.ekipman_id)
                if eski_makine:
                    eski_makine.calisma_durumu = 'kirada'
                    # İPTAL İŞLEMİNDE SAHAYA DÖNEN MAKİNENİN DE MERKEZİ SİLİNMİYOR
                    # eski_makine.sube_id = None

            # 4. MAKİNE DEĞİŞİM (SWAP) LOGUNU SİL (FOREIGN KEY HATASINI ÖNLER)
            if degisim_log:
                db.session.delete(degisim_log)

            # Eski kalemi canlandır
            eski_kalem.is_active = True
            eski_kalem.sonlandirildi = False
            eski_kalem.kiralama_bitis = aktif_child.kiralama_bitis

            db.session.delete(aktif_child)
            db.session.commit()

            guncelle_cari_toplam(eski_kalem.kiralama_id)

        except Exception as e:
            db.session.rollback()
            raise ValidationError(f"İptal işlemi başarısız: {str(e)}")