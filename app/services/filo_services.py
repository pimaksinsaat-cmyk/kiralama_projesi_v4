from app.services.base import BaseService, ValidationError
from app.filo.models import Ekipman, BakimKaydi, KullanilanParca, StokKarti, StokHareket
from app.kiralama.models import KiralamaKalemi
from app.extensions import db
from datetime import datetime, date
from decimal import Decimal
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

    OPEN_STATUSES = {'acik', 'parca_bekliyor'}

    @classmethod
    def get_active_rental(cls, ekipman_id, reference_date=None):
        reference_date = reference_date or date.today()
        return KiralamaKalemi.query.filter(
            KiralamaKalemi.ekipman_id == ekipman_id,
            KiralamaKalemi.is_deleted == False,
            KiralamaKalemi.is_active == True,
            KiralamaKalemi.sonlandirildi == False,
            KiralamaKalemi.kiralama_baslangici <= reference_date,
            KiralamaKalemi.kiralama_bitis >= reference_date,
        ).order_by(KiralamaKalemi.id.desc()).first()

    @classmethod
    def has_active_rental(cls, ekipman_id, reference_date=None):
        return cls.get_active_rental(ekipman_id, reference_date=reference_date) is not None

    @classmethod
    def _validate_rental_safe_service_type(cls, ekipman, servis_tipi):
        if ekipman and cls.has_active_rental(ekipman.id) and servis_tipi != 'yerinde_servis':
            raise ValidationError(
                f"'{ekipman.kod}' aktif kiralamada oldugu icin sadece Yerinde Servis olarak islem gorebilir. "
                "Ic/Dis servis secimi kiralama kaydini bozabilir."
            )

    @staticmethod
    def _normalize_date(value):
        if isinstance(value, str) and value:
            return datetime.strptime(value, '%Y-%m-%d').date()
        return value or None

    @staticmethod
    def _normalize_parts(parts_data):
        normalized_rows = []
        normalized_stock_totals = {}
        for part in parts_data or []:
            try:
                stok_karti_id = int(part.get('stok_karti_id') or 0)
                kullanilan_adet = int(part.get('kullanilan_adet') or 0)
            except (TypeError, ValueError):
                stok_karti_id = 0
                try:
                    kullanilan_adet = int(part.get('kullanilan_adet') or 0)
                except (TypeError, ValueError):
                    continue

            malzeme_adi = (part.get('malzeme_adi') or '').strip()
            birim_fiyat_raw = part.get('birim_fiyat')
            try:
                birim_fiyat = Decimal(str(birim_fiyat_raw).replace(' ', '').replace(',', '.')) if str(birim_fiyat_raw).strip() else None
            except (ArithmeticError, ValueError, TypeError):
                birim_fiyat = None

            if kullanilan_adet <= 0:
                continue

            if stok_karti_id > 0:
                normalized_rows.append({
                    'stok_karti_id': stok_karti_id,
                    'malzeme_adi': None,
                    'kullanilan_adet': kullanilan_adet,
                    'birim_fiyat': birim_fiyat,
                })
                normalized_stock_totals[stok_karti_id] = normalized_stock_totals.get(stok_karti_id, 0) + kullanilan_adet
                continue

            if malzeme_adi:
                normalized_rows.append({
                    'stok_karti_id': None,
                    'malzeme_adi': malzeme_adi,
                    'kullanilan_adet': kullanilan_adet,
                    'birim_fiyat': birim_fiyat or Decimal('0'),
                })

        return {
            'rows': normalized_rows,
            'stock_totals': normalized_stock_totals,
        }

    @staticmethod
    def _latest_price(stok_karti_id):
        hareket = StokHareket.query.filter_by(stok_karti_id=stok_karti_id).order_by(StokHareket.id.desc()).first()
        return Decimal(hareket.birim_fiyat or 0) if hareket else Decimal('0')

    @classmethod
    def _sync_parts(cls, bakim_kaydi, normalized_parts):
        mevcut_parcalar = {}
        for parca in bakim_kaydi.kullanilan_parcalar:
            if parca.stok_karti_id:
                mevcut_parcalar[parca.stok_karti_id] = mevcut_parcalar.get(parca.stok_karti_id, 0) + int(parca.kullanilan_adet or 0)

        hedef_stok = normalized_parts.get('stock_totals', {})
        hedef_satirlar = normalized_parts.get('rows', [])

        tum_kartlar = set(mevcut_parcalar) | set(hedef_stok)
        for stok_karti_id in tum_kartlar:
            onceki_adet = mevcut_parcalar.get(stok_karti_id, 0)
            yeni_adet = hedef_stok.get(stok_karti_id, 0)
            delta = yeni_adet - onceki_adet
            if delta == 0:
                continue

            stok_karti = StokKarti.query.filter_by(id=stok_karti_id, is_deleted=False).first()
            if not stok_karti:
                raise ValidationError('Seçilen stok kartı bulunamadı.')

            if delta > 0 and (stok_karti.mevcut_stok or 0) < delta:
                raise ValidationError(f"'{stok_karti.parca_adi}' için yeterli stok yok. Mevcut: {stok_karti.mevcut_stok}")

            stok_karti.mevcut_stok = int(stok_karti.mevcut_stok or 0) - delta
            db.session.add(stok_karti)

            db.session.add(
                StokHareket(
                    stok_karti_id=stok_karti.id,
                    firma_id=bakim_kaydi.servis_veren_firma_id,
                    bakim_kaydi_id=bakim_kaydi.id,
                    tarih=bakim_kaydi.tarih,
                    adet=abs(delta),
                    birim_fiyat=cls._latest_price(stok_karti.id),
                    hareket_tipi='cikis' if delta > 0 else 'giris',
                    aciklama=f"Servis kaydi #{bakim_kaydi.id} parca senkronizasyonu",
                )
            )

        bakim_kaydi.kullanilan_parcalar.clear()
        db.session.flush()

        for satir in hedef_satirlar:
            birim_fiyat = satir.get('birim_fiyat')
            if satir.get('stok_karti_id') and birim_fiyat is None:
                birim_fiyat = cls._latest_price(satir['stok_karti_id'])

            bakim_kaydi.kullanilan_parcalar.append(
                KullanilanParca(
                    stok_karti_id=satir.get('stok_karti_id'),
                    malzeme_adi=satir.get('malzeme_adi'),
                    kullanilan_adet=satir.get('kullanilan_adet'),
                    birim_fiyat=birim_fiyat,
                )
            )

    @classmethod
    def _sync_ekipman_status(cls, bakim_kaydi):
        ekipman = bakim_kaydi.ekipman
        if not ekipman:
            return

        if cls.has_active_rental(ekipman.id):
            if ekipman.calisma_durumu != 'kirada':
                ekipman.calisma_durumu = 'kirada'
                db.session.add(ekipman)
            return

        # Yerinde servis: makine sahada (kirada) kalmaya devam eder, durum değişmez.
        if bakim_kaydi.servis_tipi == 'yerinde_servis':
            return

        # Kirada olan makinenin durumunu servis açılışı/kapanışı bozmamalı
        # (aksi halde kiralama kaydı bozulur).
        if ekipman.calisma_durumu == 'kirada':
            return

        if bakim_kaydi.durum in cls.OPEN_STATUSES:
            ekipman.calisma_durumu = 'serviste'
        elif ekipman.calisma_durumu == 'serviste':
            ekipman.calisma_durumu = 'bosta'

        db.session.add(ekipman)
    
    @classmethod
    def bakim_kaydet(cls, ekipman_id, bakim_verileri, parts_data=None, actor_id=None):
        """Yeni bir bakım kaydı açar."""
        bakim_verileri['tarih'] = cls._normalize_date(bakim_verileri.get('tarih'))
        bakim_verileri['sonraki_bakim_tarihi'] = cls._normalize_date(bakim_verileri.get('sonraki_bakim_tarihi'))

        ekipman = Ekipman.query.filter_by(id=ekipman_id, is_deleted=False).first()
        if not ekipman:
            raise ValidationError('Makine bulunamadı.')

        cls._validate_rental_safe_service_type(ekipman, bakim_verileri.get('servis_tipi') or 'ic_servis')

        acik_kayit = cls.model.query.filter(
            cls.model.ekipman_id == ekipman_id,
            cls.model.is_deleted == False,
            cls.model.durum.in_(tuple(cls.OPEN_STATUSES)),
        ).first()
        if acik_kayit:
            raise ValidationError('Bu makine için zaten açık bir servis kaydı bulunuyor.')

        try:
            yeni_bakim = cls.model(ekipman_id=ekipman_id, **bakim_verileri)
            cls.save(yeni_bakim, is_new=True, auto_commit=False, actor_id=actor_id)
            cls._sync_parts(yeni_bakim, cls._normalize_parts(parts_data))
            cls._sync_ekipman_status(yeni_bakim)
            db.session.commit()
            return yeni_bakim
        except Exception:
            db.session.rollback()
            raise

    @classmethod
    def bakim_guncelle(cls, bakim_id, bakim_verileri, parts_data=None, actor_id=None):
        bakim_kaydi = cls.get_by_id(bakim_id)
        if not bakim_kaydi:
            raise ValidationError('Servis kaydı bulunamadı.')

        bakim_verileri['tarih'] = cls._normalize_date(bakim_verileri.get('tarih'))
        bakim_verileri['sonraki_bakim_tarihi'] = cls._normalize_date(bakim_verileri.get('sonraki_bakim_tarihi'))
        cls._validate_rental_safe_service_type(
            bakim_kaydi.ekipman,
            bakim_verileri.get('servis_tipi') or bakim_kaydi.servis_tipi or 'ic_servis',
        )

        try:
            for key, value in bakim_verileri.items():
                if hasattr(bakim_kaydi, key):
                    setattr(bakim_kaydi, key, value)

            cls.save(bakim_kaydi, is_new=False, auto_commit=False, actor_id=actor_id)
            cls._sync_parts(bakim_kaydi, cls._normalize_parts(parts_data))
            cls._sync_ekipman_status(bakim_kaydi)
            db.session.commit()
            return bakim_kaydi
        except Exception:
            db.session.rollback()
            raise

    @classmethod
    def bakim_sil(cls, bakim_id, actor_id=None):
        bakim_kaydi = cls.get_by_id(bakim_id)
        if not bakim_kaydi:
            raise ValidationError('Servis kaydı bulunamadı.')

        try:
            cls._sync_parts(bakim_kaydi, {})
            ekipman = bakim_kaydi.ekipman
            db.session.delete(bakim_kaydi)

            if ekipman and ekipman.calisma_durumu == 'serviste':
                acik_kalan = cls.model.query.filter(
                    cls.model.ekipman_id == ekipman.id,
                    cls.model.id != bakim_id,
                    cls.model.is_deleted == False,
                    cls.model.durum.in_(tuple(cls.OPEN_STATUSES)),
                ).count()
                if acik_kalan == 0:
                    ekipman.calisma_durumu = 'bosta'
                    db.session.add(ekipman)

            db.session.commit()
        except Exception:
            db.session.rollback()
            raise

    @classmethod
    def ekipman_bakimini_tamamla(cls, ekipman_id, actor_id=None):
        acik_kayit = cls.model.query.filter(
            cls.model.ekipman_id == ekipman_id,
            cls.model.is_deleted == False,
            cls.model.durum.in_(tuple(cls.OPEN_STATUSES)),
        ).order_by(cls.model.tarih.desc(), cls.model.id.desc()).first()

        if not acik_kayit:
            return None

        try:
            acik_kayit.durum = 'tamamlandi'
            cls.save(acik_kayit, is_new=False, auto_commit=False, actor_id=actor_id)
            cls._sync_ekipman_status(acik_kayit)
            db.session.commit()
            return acik_kayit
        except Exception:
            db.session.rollback()
            raise