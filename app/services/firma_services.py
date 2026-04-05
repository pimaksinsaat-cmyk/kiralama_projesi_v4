import os
from datetime import date
from decimal import Decimal
import re
from sqlalchemy import or_, and_
from sqlalchemy.orm import joinedload, subqueryload

from app.services.base import BaseService, ValidationError
from app.firmalar.models import Firma
from app.kiralama.models import Kiralama, KiralamaKalemi
from app.cari.models import Odeme
from app.nakliyeler.models import Nakliye
from app.extensions import db
from app.ayarlar.models import AppSettings
from app.utils import klasor_adi_temizle, normalize_turkish_upper

class FirmaService(BaseService):
    """
    Firma (Müşteri/Tedarikçi) yönetimi ve cari hesaplamalar için iş mantığı katmanı.
    """
    model = Firma
    use_soft_delete = True
    
    # Güncellenebilir alanlar
    updatable_fields = [
        'firma_adi', 'yetkili_adi', 'telefon', 'eposta', 
        'iletisim_bilgileri', 'vergi_dairesi', 'vergi_no',
        'is_musteri', 'is_tedarikci', 'sozlesme_no', 
        'sozlesme_rev_no', 'sozlesme_tarihi', 'imza_yetkisi_kontrol_edildi',
        'imza_yetkisi_kontrol_tarihi', 'is_active'
    ]

    @classmethod
    def validate(cls, instance, is_new=True):
        """Vergi numarası benzersizlik kontrolü."""
        if instance.vergi_no:
            mevcut = cls.find_one_by(vergi_no=instance.vergi_no)
            if mevcut and (is_new or mevcut.id != instance.id):
                raise ValidationError(f"'{instance.vergi_no}' vergi numarası başka bir firmada kayıtlı!")

    @classmethod
    def before_save(cls, instance, is_new=True):
        """Kayıt öncesi standartlaştırma."""
        if instance.firma_adi:
            instance.firma_adi = normalize_turkish_upper(instance.firma_adi)
        if instance.vergi_no:
            instance.vergi_no = instance.vergi_no.strip()

    @staticmethod
    def _extract_sozlesme_sequence(sozlesme_no, prefix, year):
        """PS numarasındaki ana sayısal sırayı çıkarır, olası ekleri yok sayar."""
        if not sozlesme_no:
            return None

        match = re.match(rf"^{re.escape(prefix)}-{year}-(\d+)", str(sozlesme_no).strip())
        if not match:
            return None

        return int(match.group(1))

    @classmethod
    def get_next_sozlesme_no(cls):
        """Sıradaki genel sözleşme numarasını veritabanından bağımsız şekilde üretir."""
        current_year = date.today().year
        settings = AppSettings.get_current()
        start_no = settings.genel_sozlesme_start_no if settings else 1
        prefix = settings.genel_sozlesme_prefix if settings and settings.genel_sozlesme_prefix else 'PS'

        sozlesme_nolari = cls._get_base_query().with_entities(Firma.sozlesme_no).filter(
            Firma.sozlesme_no.like(f"{prefix}-{current_year}-%")
        ).all()

        sequence_values = [
            sequence
            for sozlesme_no, in sozlesme_nolari
            for sequence in [cls._extract_sozlesme_sequence(sozlesme_no, prefix, current_year)]
            if sequence is not None
        ]
        max_seq = max(sequence_values, default=None)

        next_nr = (max_seq + 1) if max_seq else start_no
        return f"{prefix}-{current_year}-{next_nr:03d}"

    @classmethod
    def get_active_firms(cls, search_query=None):
        """Aktif firmaları listeler (Dahili Kasa hariç)."""
        query = cls._get_base_query().filter(
            and_(
                Firma.firma_adi != 'Dahili Kasa İşlemleri',
                or_(Firma.is_active == True, Firma.is_active.is_(None))
            )
        )
        if search_query:
            term = f"%{search_query}%"
            query = query.filter(or_(
                Firma.firma_adi.ilike(term),
                Firma.yetkili_adi.ilike(term),
                Firma.vergi_no.ilike(term),
                Firma.telefon.ilike(term),
                Firma.eposta.ilike(term)
            ))
        return query.order_by(Firma.id.desc())
    @classmethod
    def get_inactive_firms(cls, search_query=None):
        """Arşivlenmiş (is_active=False) firmaları listeler."""
        query = cls._get_base_query().filter(Firma.is_active == False)
        if search_query:
            term = f"%{search_query}%"
            query = query.filter(or_(
                Firma.firma_adi.ilike(term),
                Firma.vergi_no.ilike(term)
            ))
        return query.order_by(Firma.id.desc())

    @classmethod
    def archive_with_check(cls, firma_id, actor_id=None):
        """
        Firmayı arşive kaldırır. 
        EĞER üzerinde kiralama kaydı varsa işlemi engeller.
        """
        firma = cls._get_base_query().options(subqueryload(Firma.kiralamalar)).filter_by(id=firma_id).first()
        
        if not firma:
            raise ValidationError("Firma bulunamadı.")

        if firma.kiralamalar:
            raise ValidationError(f"'{firma.firma_adi}' ünvanlı firmanın üzerinde kiralama kayıtları bulunduğu için arşive kaldırılamaz.")

        return cls.update(firma_id, {'is_active': False}, actor_id=actor_id)
    
    @classmethod
    def sozlesme_hazirla(cls, firma_id, base_app_path, actor_id=None):
        """Sözleşme numarası üretir ve fiziksel arşiv klasörlerini açar."""
        firma = cls.get_by_id(firma_id)
        if not firma:
            raise ValidationError("Firma bulunamadı.")
        if firma.sozlesme_no:
            raise ValidationError(f"Bu firma için zaten bir sözleşme ({firma.sozlesme_no}) mevcut.")

        next_ps_no = cls.get_next_sozlesme_no()
        
        ikinci_parametre = firma.vergi_no if firma.vergi_no else str(firma.id)
        klasor_adi = klasor_adi_temizle(firma.firma_adi, ikinci_parametre)
        
        firma.sozlesme_no = next_ps_no
        # İlk kez hazırlanırken tarihi set et, sonra değişme
        if firma.sozlesme_tarihi is None:
            firma.sozlesme_tarihi = date.today()
        firma.bulut_klasor_adi = klasor_adi
        
        # Fiziksel klasörleri oluştur
        base_path = os.path.join(base_app_path, 'static', 'arsiv', klasor_adi)
        os.makedirs(os.path.join(base_path, 'PS'), exist_ok=True)
        os.makedirs(os.path.join(base_path, 'Kiralama_Formlari'), exist_ok=True)
        
        return cls.save(firma, is_new=False, actor_id=actor_id)

    @classmethod
    def get_financial_summary(cls, firma_id):
        """Firmanın tüm cari hareketlerini (Fatura, Ödeme, Kiralama) hesaplar."""
        firma = cls._get_base_query().options(
            subqueryload(Firma.kiralamalar).options(subqueryload(Kiralama.kalemler).options(joinedload(KiralamaKalemi.ekipman))),
            subqueryload(Firma.odemeler).joinedload(Odeme.kasa),
            subqueryload(Firma.hizmet_kayitlari),
        ).filter_by(id=firma_id).first()
        if not firma:
            raise ValidationError("Firma bulunamadı.")
        # Nakliye tevkifat oranlarını tek sorguda çek (N+1'den kaçın)
        nakliye_ids = [h.nakliye_id for h in firma.hizmet_kayitlari if getattr(h, 'nakliye_id', None)]
        nakliye_info_map = {}
        if nakliye_ids:
            nakliyeler = Nakliye.query.filter(Nakliye.id.in_(nakliye_ids)).with_entities(
                Nakliye.id, Nakliye.tevkifat_orani, Nakliye.kiralama_id
            ).all()
            kiralama_ids_for_nakliye = [n.kiralama_id for n in nakliyeler if n.kiralama_id]
            kiralama_form_map = {}
            if kiralama_ids_for_nakliye:
                kiralamalar_q = Kiralama.query.filter(Kiralama.id.in_(kiralama_ids_for_nakliye)).with_entities(
                    Kiralama.id, Kiralama.kiralama_form_no
                ).all()
                kiralama_form_map = {k.id: k.kiralama_form_no for k in kiralamalar_q}
            nakliye_info_map = {
                n.id: {
                    'tevkifat_orani': n.tevkifat_orani or '',
                    'kiralama_id': n.kiralama_id,
                    'kiralama_form_no': kiralama_form_map.get(n.kiralama_id) if n.kiralama_id else None,
                }
                for n in nakliyeler
            }
        hareketler = []
        for h in firma.hizmet_kayitlari:
            if getattr(h, 'is_deleted', False):
                continue
            if (
                getattr(h, 'ozel_id', None)
                and getattr(h, 'aciklama', '').startswith('Kiralama Bekleyen Bakiye')
                and not db.session.get(Kiralama, h.ozel_id)
            ):
                continue
            tutar = h.tutar or Decimal('0')
            if getattr(h, 'nakliye_id', None):
                tur_adi, tur_tipi, ozel_id = 'Nakliye', 'nakliye', h.nakliye_id
            elif getattr(h, 'ozel_id', None): 
                tur_adi, tur_tipi, ozel_id = 'Kiralama', 'kiralama', h.ozel_id
            else:
                tur_tipi, ozel_id = 'fatura', h.id
                tur_adi = 'Fatura (Satış)' if h.yon == 'giden' else 'Fatura (Alış)'
            tutar_sign = 1 if (h.yon == 'giden') else -1 if (h.yon == 'gelen') else 0
            tutar_deger = tutar * tutar_sign
            yon = getattr(h, 'yon', None)

            # KDV oranı: nakliye_alis_kdv varsa onu kullan, aksi takdirde kdv_orani kullan
            nakliye_alis_kdv = getattr(h, 'nakliye_alis_kdv', None)
            kdv_orani = getattr(h, 'kdv_orani', None)
            hesap_kdv_orani = nakliye_alis_kdv if nakliye_alis_kdv is not None else kdv_orani

            # KDV tutarı hesapla (matrah * hesap_kdv_orani / 100)
            if hesap_kdv_orani is not None and tutar_deger is not None:
                kdv_tutari = tutar_deger * hesap_kdv_orani / 100
            else:
                kdv_tutari = None
            if tutar_deger is not None and kdv_tutari is not None:
                tutar_toplam = tutar_deger + kdv_tutari
            else:
                tutar_toplam = None

            # Borç/Alacak hesapla (yön bilgisine göre)
            if tur_tipi == 'odeme':
                # Finansal işlemler: KDV yok, sadece tutar kullan
                alacak = -tutar if yon == 'tahsilat' else Decimal('0')
                borc = tutar if yon == 'odeme' else Decimal('0')
            else:
                # HizmetKaydi: KDV dahil tutar_toplam kullan
                if tutar_toplam is not None:
                    abs_tutar_toplam = abs(tutar_toplam)
                    borc = abs_tutar_toplam if yon == 'giden' else Decimal('0')
                    alacak = -abs_tutar_toplam if yon == 'gelen' else Decimal('0')
                else:
                    # KDV hesaplanamamışsa tutar_deger kullan
                    abs_tutar_deger = abs(tutar_deger) if tutar_deger else Decimal('0')
                    borc = abs_tutar_deger if yon == 'giden' else Decimal('0')
                    alacak = -abs_tutar_deger if yon == 'gelen' else Decimal('0')
            hareketler.append({
                'id': h.id,
                'ozel_id': ozel_id,
                'tarih': h.tarih,
                'tur': tur_adi,
                'tur_tipi': tur_tipi,
                'aciklama': h.aciklama,
                'belge_no': h.fatura_no,
                'tutar': tutar_deger,
                'borc': borc,
                'alacak': alacak,
                'tutar_pozitif_mi': tutar_deger > 0,
                'tutar_renk': 'text-danger' if tutar_deger > 0 else 'text-success' if tutar_deger < 0 else '',
                'kdv_tutari': kdv_tutari,
                'kdv_orani': hesap_kdv_orani,
                'kiralama_alis_kdv': getattr(h, 'kiralama_alis_kdv', None),
                'nakliye_alis_kdv': nakliye_alis_kdv,
                'tevkifat_str': nakliye_info_map.get(getattr(h, 'nakliye_id', None), {}).get('tevkifat_orani', ''),
                'nakliye_kiralama_id': nakliye_info_map.get(getattr(h, 'nakliye_id', None), {}).get('kiralama_id'),
                'nakliye_kiralama_form_no': nakliye_info_map.get(getattr(h, 'nakliye_id', None), {}).get('kiralama_form_no'),
                'tutar_toplam': tutar_toplam,
                'nesne': h,
                'yon': yon
            })
        for o in firma.odemeler:
            if getattr(o, 'is_deleted', False):
                continue
            tutar = o.tutar or Decimal('0')
            yon = getattr(o, 'yon', 'tahsilat')
            tutar_sign = 1 if yon == 'odeme' else -1 if yon == 'tahsilat' else 0
            tutar_deger = tutar * tutar_sign
            # Finansal işlemler: tahsilat (para girişi) → alacak, odeme (para çıkışı) → borç
            alacak = -tutar if yon == 'tahsilat' else Decimal('0')
            borc = tutar if yon == 'odeme' else Decimal('0')
            # Ödeme ve tahsilatlarda KDV yok, tutar_toplam = tutar_deger
            hareketler.append({
                'id': o.id, 'ozel_id': o.id, 'tarih': o.tarih,
                'tur': 'Tahsilat (Giriş)' if yon == 'tahsilat' else 'Ödeme (Çıkış)',
                'tur_tipi': 'odeme', 'aciklama': o.aciklama or 'Finansal İşlem',
                'belge_no': f"{o.kasa.kasa_adi if o.kasa else 'Kasa Tanımsız'}",
                'tutar': tutar_deger,
                'borc': borc,
                'alacak': alacak,
                'tutar_pozitif_mi': tutar_deger > 0,
                'tutar_renk': 'text-danger' if tutar_deger > 0 else 'text-success' if tutar_deger < 0 else '',
                'kdv_tutari': None,
                'kdv_orani': None,
                'tutar_toplam': tutar_deger,
                'nesne': o
            })
        def _sort_key(x):
            if x.get('tur_tipi') == 'kiralama':
                grup = x.get('belge_no') or ''
                tur_sira = 0
            elif x.get('tur_tipi') == 'nakliye' and x.get('nakliye_kiralama_form_no'):
                grup = x.get('nakliye_kiralama_form_no') or ''
                tur_sira = 1
            else:
                grup = ''
                tur_sira = 2
            tarih = x.get('tarih') or date.min
            tarih_ts = tarih.toordinal() if tarih != date.min else 0
            # grup azalan (ters string karşılaştırması için negatif ord listesi), tur_sira artan, tarih azalan
            grup_key = tuple(127 - ord(c) for c in grup) if grup else (127,) * 20
            return (grup_key, tur_sira, -tarih_ts)

        hareketler.sort(key=_sort_key)
        # toplam_borc ve toplam_alacak kaldırıldı (borc/alacak alanları yok)
        # --- SADECE BAKİYE HESAPLAMA KISMI ASKIDA ---
        # yuruyen_bakiye = Decimal('0')
        # for islem in hareketler:
        #     yuruyen_bakiye = (yuruyen_bakiye + islem['borc']) - islem['alacak']
        #     islem['kumulatif_bakiye'] = yuruyen_bakiye
        # if yuruyen_bakiye > 0: 
        #     durum_metni, durum_rengi = "Borçlu", "text-danger"
        # elif yuruyen_bakiye < 0: 
        #     durum_metni, durum_rengi = "Alacaklı", "text-success"
        # else: 
        #     durum_metni, durum_rengi = "Hesap Kapalı", "text-muted"
        # KDV dahil kümülatif bakiye hesaplama
        yuruyen_bakiye = 0
        for islem in hareketler:
            # tutar_toplam yoksa 0 kabul edilir
            tutar_toplam = islem.get('tutar_toplam') or 0
            # Hareket tipi: giden/ödeme ise +, gelen/tahsilat ise -
            if islem.get('tur_tipi') in ['giden', 'odeme']:
                yuruyen_bakiye += tutar_toplam
            elif islem.get('tur_tipi') in ['gelen', 'tahsilat']:
                yuruyen_bakiye -= tutar_toplam
            else:
                yuruyen_bakiye += tutar_toplam  # default davranış
            islem['kumulatif_bakiye'] = yuruyen_bakiye
        # Toplam borç, alacak ve bakiye hesapla
        toplam_borc = sum(islem.get('borc') or Decimal('0') for islem in hareketler)
        toplam_alacak = sum(islem.get('alacak') or Decimal('0') for islem in hareketler)
        # Güncel bakiye: Toplam Borç - abs(Toplam Alacak)
        guncel_bakiye = toplam_borc - abs(toplam_alacak)

        durum_metni, durum_rengi = '', ''
        return {
            'firma': firma,
            'hareketler': hareketler,
            'bakiye': guncel_bakiye,
            'toplam_borc': toplam_borc,
            'toplam_alacak': toplam_alacak,
            'guncel_bakiye': guncel_bakiye,
            'durum_metni': durum_metni,
            'durum_rengi': durum_rengi
        }
    