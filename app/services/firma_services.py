import os
from datetime import date, datetime, timezone
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
from app.utils import klasor_adi_temizle, normalize_turkish_upper, tr_ilike

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

    @staticmethod
    def _to_date_ordinal(d):
        if isinstance(d, date):
            return d.toordinal()
        return 0

    @staticmethod
    def _parse_form_no_natural(form_no):
        text = (form_no or '').strip().upper()
        if not text or text == '-':
            return (0, 0, 0, '')
        m = re.match(r'^([A-Z]+)-(\d{4})[/-](\d+)(?:-(\d+))?', text)
        if not m:
            return (0, 0, 0, text)
        prefix, year, seq, rev = m.groups()
        return (int(year), int(seq), int(rev or 0), prefix)

    @staticmethod
    def _form_no_link_keys(form_no):
        """
        Form no link eşleştirmesi için toleranslı anahtarlar üretir.
        Örn:
          PF_2026/006-4 -> {"PF-2026/006-4", "PF-2026/006"}
          pf-2026/006   -> {"PF-2026/006"}
        """
        text = (form_no or '').strip().upper()
        if not text:
            return []
        text = text.replace('_', '-')
        keys = [text]

        # Revizyon eki varsa baz formu da ekle (sondaki -<sayi>)
        m = re.match(r'^(.+)-(\d+)$', text)
        if m:
            keys.append(m.group(1))
        return keys

    @staticmethod
    def _operation_rank(op_type, desc):
        op = (op_type or '').strip().lower()
        d = (desc or '').strip().lower()
        if op == 'kiralama':
            return 0
        if op == 'nakliye':
            if ('dönüş' in d) or ('getirildi' in d):
                return 2
            return 1
        if op in ('nakliye_tedarik', 'nakliye_satis'):
            return 3
        if op == 'harici_kiralama':
            return 4
        if op == 'fatura':
            return 5
        if op in ('odeme', 'tahsilat'):
            return 6
        return 7

    @staticmethod
    def _to_decimal_amount(value):
        """Kümülatif hesaplarda kayan nokta sapmasını engellemek için güvenli dönüşüm."""
        if value is None:
            return Decimal('0')
        if isinstance(value, Decimal):
            return value
        try:
            return Decimal(str(value))
        except Exception:
            return Decimal('0')

    @classmethod
    def _apply_unified_running_balance(cls, items, amount_key, balance_key, sort_key_fn, target_final_balance=None):
        """
        Kümülatif bakiyeyi tek formülle hesaplar:
        1) Eski -> yeni sırada yürütür
        2) İstenirse sonucu kanonik bakiyeye (bakiye_ozeti) sabitler.
        """
        running = Decimal('0')
        for item in sorted(items, key=sort_key_fn):
            running += cls._to_decimal_amount(item.get(amount_key))
            item[balance_key] = running

        if not items or target_final_balance is None:
            return

        newest_item = sorted(items, key=sort_key_fn, reverse=True)[0]
        drift = cls._to_decimal_amount(target_final_balance) - cls._to_decimal_amount(newest_item.get(balance_key))
        if drift == 0:
            return
        for item in items:
            item[balance_key] = cls._to_decimal_amount(item.get(balance_key)) + drift

    @classmethod
    def _unified_sort_key(cls, form_no, olay_tarihi, form_tarihi, op_type, desc, row_id):
        islem_rank = cls._operation_rank(op_type, desc)
        rid = int(row_id or 0)
        # Tek ve deterministik kural: tüm satırlar fiili olay/işlem tarihine göre sıralansın.
        # Form numarası kırılımı kaldırıldı; böylece farklı formların eski tarihleri yukarı çıkamaz.
        return (
            -cls._to_date_ordinal(olay_tarihi),
            islem_rank,
            -rid,
        )

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
            query = query.filter(or_(
                tr_ilike(Firma.firma_adi, f"%{search_query}%"),
                tr_ilike(Firma.yetkili_adi, f"%{search_query}%"),
                Firma.vergi_no.ilike(f"%{search_query}%"),
                Firma.telefon.ilike(f"%{search_query}%"),
                Firma.eposta.ilike(f"%{search_query}%")
            ))
        return query.order_by(Firma.id.desc())
    @classmethod
    def get_inactive_firms(cls, search_query=None):
        """Arşivlenmiş (is_active=False) firmaları listeler."""
        query = cls._get_base_query().filter(Firma.is_active == False)
        if search_query:
            query = query.filter(or_(
                tr_ilike(Firma.firma_adi, f"%{search_query}%"),
                Firma.vergi_no.ilike(f"%{search_query}%")
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
                Nakliye.id, Nakliye.tevkifat_orani, Nakliye.kiralama_id, Nakliye.kdv_orani
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
                    'kdv_orani': n.kdv_orani,
                }
                for n in nakliyeler
            }
        from app.services.kiralama_services import KiralamaService
        hareketler = []
        from app.services.cari_services import hizmet_kaydi_bakiyeye_dahil_mi
        # Form-bazlı cari ile aynı sıralama davranışı için kiralama başlangıç haritası:
        # kiralama hareketi (ozel_id=kiralama.id) varsa olay tarihi kalem başlangıcından gelsin.
        kiralama_baslangic_map = {}
        for kir in (firma.kiralamalar or []):
            baslangiclar = [
                k.kiralama_baslangici
                for k in (kir.kalemler or [])
                if getattr(k, 'kiralama_baslangici', None)
            ]
            kiralama_baslangic_map[kir.id] = min(baslangiclar) if baslangiclar else None
        for h in firma.hizmet_kayitlari:
            if not hizmet_kaydi_bakiyeye_dahil_mi(h):
                continue
            # Orphan "Kiralama Bekleyen Bakiye" kayıtları (bağlı kiralama silinmiş) gösterme
            if (
                getattr(h, 'ozel_id', None)
                and (h.aciklama or '').startswith('Kiralama Bekleyen Bakiye')
                and not db.session.get(Kiralama, h.ozel_id)
            ):
                continue
            # Nakliye bağlantılı kayıtlarda tutar=0 olanları gösterme
            if getattr(h, 'nakliye_id', None) and not (h.tutar and h.tutar > 0):
                continue
            # Bekleyen kiralama ve dış tedarik kayıtları için canlı tahakkuk hesapla;
            # diğer kayıtlar (fatura, nakliye vb.) için DB'deki değeri kullan.
            tutar = KiralamaService.hesapla_hizmet_kaydi_canli_tutari(h)
            aciklama_text = (h.aciklama or '').strip()
            taseron_nakliye_kaydi = (
                aciklama_text.startswith('Taşeron Nakliye Bedeli')
                or aciklama_text.startswith('Dönüş Nakliye:')
            )
            if getattr(h, 'nakliye_id', None):
                tur_adi, tur_tipi, ozel_id = 'Nakliye', 'nakliye', h.nakliye_id
            elif taseron_nakliye_kaydi:
                # Kiralama kalemine bağlı olsa bile finansal olarak nakliye hareketidir.
                tur_adi, tur_tipi, ozel_id = 'Nakliye', 'nakliye', h.id
            elif getattr(h, 'ozel_id', None): 
                tur_adi, tur_tipi, ozel_id = 'Kiralama', 'kiralama', h.ozel_id
            else:
                tur_tipi, ozel_id = 'fatura', h.id
                tur_adi = 'Fatura (Satış)' if h.yon == 'giden' else 'Fatura (Alış)'
            tutar_sign = 1 if (h.yon == 'giden') else -1 if (h.yon == 'gelen') else 0
            tutar_deger = tutar * tutar_sign
            yon = getattr(h, 'yon', None)

            # KDV oranı: nakliye_alis_kdv → kiralama_alis_kdv → kdv_orani öncelik sırası
            nakliye_alis_kdv = getattr(h, 'nakliye_alis_kdv', None)
            kiralama_alis_kdv = getattr(h, 'kiralama_alis_kdv', None)
            kdv_orani = getattr(h, 'kdv_orani', None)
            hesap_kdv_orani = (
                nakliye_alis_kdv if nakliye_alis_kdv is not None
                else kiralama_alis_kdv if kiralama_alis_kdv is not None
                else kdv_orani
            )
            # Eski kayıtlarda kdv_orani NULL olabilir; nakliye ve dış kiralama için fallback
            if hesap_kdv_orani is None and getattr(h, 'nakliye_id', None):
                hesap_kdv_orani = nakliye_info_map.get(h.nakliye_id, {}).get('kdv_orani')
            if hesap_kdv_orani is None and getattr(h, 'ozel_id', None) and (h.aciklama or '').startswith('Dış Kiralama'):
                kalem_obj = db.session.get(KiralamaKalemi, h.ozel_id)
                if kalem_obj:
                    hesap_kdv_orani = kalem_obj.kiralama_alis_kdv

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
            islem_tarih = getattr(h, 'islem_tarihi', None) or h.tarih
            sort_tarih = islem_tarih
            if tur_tipi == 'kiralama' and ozel_id:
                sort_tarih = kiralama_baslangic_map.get(ozel_id) or islem_tarih
            hareketler.append({
                'id': h.id,
                'ozel_id': ozel_id,
                'tarih': islem_tarih,
                'sort_tarih': sort_tarih,
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
            odeme_islem_tarihi = getattr(o, 'islem_tarihi', None) or o.tarih
            # Finansal işlemler: tahsilat (para girişi) → alacak, odeme (para çıkışı) → borç
            alacak = -tutar if yon == 'tahsilat' else Decimal('0')
            borc = tutar if yon == 'odeme' else Decimal('0')
            # Ödeme ve tahsilatlarda KDV yok, tutar_toplam = tutar_deger
            hareketler.append({
                'id': o.id, 'ozel_id': o.id, 'tarih': odeme_islem_tarihi, 'sort_tarih': odeme_islem_tarihi,
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
        # Her hareket için nakliye_sira ve form_no ekle
        for h in hareketler:
            tur_tipi = h.get('tur_tipi')

            # Form numarası belirle
            if tur_tipi == 'kiralama':
                h['form_no'] = h.get('belge_no', '')
            elif tur_tipi == 'nakliye':
                h['form_no'] = h.get('nakliye_kiralama_form_no', '')
            else:
                h['form_no'] = ''

            # Nakliye sırası belirle
            if tur_tipi == 'kiralama':
                h['nakliye_sira'] = 0
            elif tur_tipi == 'nakliye':
                if 'Gidiş' in h.get('aciklama', ''):
                    h['nakliye_sira'] = 1
                elif 'Dönüş' in h.get('aciklama', ''):
                    h['nakliye_sira'] = 2
                else:
                    h['nakliye_sira'] = 1
            else:
                h['nakliye_sira'] = 3

        def _sort_key(x):
            return cls._unified_sort_key(
                form_no=x.get('form_no'),
                olay_tarihi=x.get('sort_tarih') or x.get('tarih'),
                form_tarihi=x.get('tarih'),
                op_type=x.get('tur_tipi'),
                desc=x.get('aciklama'),
                row_id=x.get('id'),
            )

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
        ozet = firma.bakiye_ozeti
        toplam_borc = ozet.get('borc_kdvli', Decimal('0'))
        toplam_alacak = ozet.get('alacak_kdvli', Decimal('0'))
        guncel_bakiye = ozet.get('net_bakiye_kdvli', Decimal('0'))
        cls._apply_unified_running_balance(
            items=hareketler,
            amount_key='tutar_toplam',
            balance_key='kumulatif_bakiye',
            sort_key_fn=_sort_key,
            target_final_balance=guncel_bakiye,
        )

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

    @classmethod
    def firma_en_erken_islem_gunu(cls, firma_id):
        """
        Firma bilgi sayfası varsayılan başlangıç tarihi için: veritabanında bu firmaya
        bağlı tüm hizmet / ödeme / kiralama / nakliye / cari defter kayıtlarından
        en erken işlem günü (ORM hareket listesinden bağımsız; nakliye faturaları dahil).

        Performans: Tek SQL gidiş-dönüşü; her alt sorgu yalnızca ilgili tabloda
        ``firma_id`` (veya eşdeğeri) ile filtrelenir — tüm veritabanını taramaz.
        Uygun indekslerle süre tipik olarak birkaç ms–onlarca ms düzeyindedir.
        """
        from sqlalchemy import Date as SA_Date, cast, func, select, union_all

        from app.cari.models import HizmetKaydi, Odeme, CariHareket

        q_hiz = select(func.min(func.coalesce(HizmetKaydi.islem_tarihi, HizmetKaydi.tarih)).label('d')).where(
            HizmetKaydi.firma_id == firma_id,
            HizmetKaydi.is_deleted.is_(False),
        )
        q_od = select(func.min(func.coalesce(Odeme.islem_tarihi, Odeme.tarih)).label('d')).where(
            Odeme.firma_musteri_id == firma_id,
            Odeme.is_deleted.is_(False),
        )
        q_car = select(func.min(CariHareket.tarih).label('d')).where(
            CariHareket.firma_id == firma_id,
            CariHareket.is_deleted.is_(False),
        )
        q_kir_form = select(func.min(Kiralama.kiralama_olusturma_tarihi).label('d')).where(
            Kiralama.firma_musteri_id == firma_id,
            Kiralama.is_deleted.is_(False),
        )
        q_kir_ca = select(
            cast(func.min(Kiralama.created_at), SA_Date).label('d')
        ).where(
            Kiralama.firma_musteri_id == firma_id,
            Kiralama.is_deleted.is_(False),
        )
        q_nak_mus = select(func.min(Nakliye.tarih).label('d')).where(
            Nakliye.firma_id == firma_id,
            Nakliye.is_active.is_(True),
        )
        q_nak_tas = select(func.min(Nakliye.tarih).label('d')).where(
            Nakliye.taseron_firma_id == firma_id,
            Nakliye.is_active.is_(True),
        )
        q_kalem = select(func.min(KiralamaKalemi.kiralama_baslangici).label('d')).where(
            KiralamaKalemi.harici_ekipman_tedarikci_id == firma_id,
            KiralamaKalemi.is_active.is_(True),
            KiralamaKalemi.is_deleted.is_(False),
        )

        u = union_all(
            q_hiz,
            q_od,
            q_car,
            q_kir_form,
            q_kir_ca,
            q_nak_mus,
            q_nak_tas,
            q_kalem,
        ).subquery('ilk_islem_bilesen')

        return db.session.scalar(select(func.min(u.c.d)))

    @staticmethod
    def build_cari_rows(firma, today_date):
        """
        Cari sekmesi için tüm satırları (kiralama + nakliye + fatura + tahsilat/ödeme)
        hesaplar, tarihe göre sıralar ve kümülatif bakiyeyi döner.
        Tek kaynak olarak hem firmalar.bilgi Cari tabı hem de
        diğer özet görünümler bu metodu kullanmalıdır.
        """
        from app.cari.models import HizmetKaydi

        rows = []
        included_hizmet_kaydi_ids = set()

        def _unified_row_sort_key(row):
            return FirmaService._unified_sort_key(
                form_no=row.get('form_no'),
                olay_tarihi=row.get('sort_date') or row.get('baslangic') or row.get('form_tarihi'),
                form_tarihi=row.get('form_tarihi') or row.get('sort_date') or row.get('baslangic'),
                op_type=row.get('islem_turu'),
                desc=row.get('aciklama'),
                row_id=row.get('id'),
            )

        # --- Kiralama ve nakliye satırları ---
        for kir in sorted(firma.kiralamalar, key=lambda k: k.kiralama_form_no or ''):
            form_tarihi = kir.kiralama_olusturma_tarihi or (kir.created_at.date() if kir.created_at else None)
            kdv_pct = kir.kdv_orani or 0

            for kalem in kir.kalemler:
                if kalem.kiralama_baslangici:
                    if kalem.sonlandirildi and kalem.kiralama_bitis:
                        bitis = kalem.kiralama_bitis
                        bitis_bugun = False
                    else:
                        bitis = today_date
                        bitis_bugun = True
                    gun_sayisi = (bitis - kalem.kiralama_baslangici).days + 1
                else:
                    bitis = None
                    bitis_bugun = False
                    gun_sayisi = 0

                brm = float(kalem.kiralama_brm_fiyat or 0)
                matrah = brm * gun_sayisi
                kdv_tutar = matrah * kdv_pct / 100
                toplam = matrah + kdv_tutar

                if kalem.ekipman:
                    ekipman_kodu = kalem.ekipman.kod or ''
                    seri_no = kalem.ekipman.seri_no or ''
                    aciklama = f"{ekipman_kodu} - {kalem.ekipman.marka or ''} - {kalem.ekipman.kaldirma_kapasitesi}kg/{kalem.ekipman.calisma_yuksekligi}m"
                else:
                    ekipman_kodu = kalem.harici_ekipman_marka or ''
                    seri_no = kalem.harici_ekipman_seri_no or ''
                    kap = f"{kalem.harici_ekipman_kapasite}kg" if kalem.harici_ekipman_kapasite else ''
                    yuk = f"/{kalem.harici_ekipman_yukseklik}m" if kalem.harici_ekipman_yukseklik else ''
                    aciklama = f"{ekipman_kodu} {kalem.harici_ekipman_model or ''} - {kap}{yuk}".strip(' -')

                rows.append({'id': kalem.id, 'sort_date': kalem.kiralama_baslangici or form_tarihi,
                    'form_no': kir.kiralama_form_no, 'form_tarihi': form_tarihi,
                    'kiralama_id': kir.id, 'islem_turu': 'kiralama', 'nakliye_sira': 0,
                    'aciklama': aciklama, 'seri_no': seri_no,
                    'baslangic': kalem.kiralama_baslangici, 'bitis': bitis,
                    'bitis_bugun': bitis_bugun, 'gun_sayisi': gun_sayisi,
                    'brm_fiyat': brm, 'matrah': matrah, 'kdv_orani': kdv_pct,
                    'kdv_tutar': kdv_tutar, 'toplam': toplam, 'bakiye': 0.0})

            # Nakliye satırları
            ilk_kod = ''
            sube_adi = ''
            for k in kir.kalemler:
                if k.ekipman:
                    ilk_kod = k.ekipman.kod or ''
                    sube_adi = k.ekipman.sube.isim if k.ekipman.sube else ''
                else:
                    ilk_kod = k.harici_ekipman_marka or ''
                if ilk_kod:
                    break
            firma_kisa = ''
            if kir.firma_musteri and kir.firma_musteri.firma_adi:
                firma_kisa = kir.firma_musteri.firma_adi.split()[0]
            for nakliye in kir.nakliyeler:
                if not nakliye.is_active:
                    continue
                nak_tutar = float(nakliye.tutar or 0)
                if nak_tutar <= 0:
                    continue
                nakliye_islem_tarihi = getattr(nakliye, 'islem_tarihi', None) or nakliye.tarih
                # Muhasebe tek-kural: cari hareketler KDV dahil yürür ve box (bakiye_ozeti)
                # ile aynı KDV kaynağını kullanır. Bu nedenle brüt kdv_orani esas alınır.
                nak_kdv_pct = float(nakliye.kdv_orani or 0)
                nak_kdv = nak_tutar * nak_kdv_pct / 100
                gl = (nakliye.guzergah or '').lower()
                if 'getirildi' in gl:
                    rota = f"{firma_kisa}→{sube_adi}" if firma_kisa and sube_adi else (firma_kisa or sube_adi or 'dönüş')
                    nak_aciklama = f"{ilk_kod} {rota} dönüş".strip()
                    nak_sira = 2
                elif 'götürüldü' in gl:
                    rota = f"{sube_adi}→{firma_kisa}" if sube_adi and firma_kisa else (sube_adi or firma_kisa or 'gidiş')
                    nak_aciklama = f"{ilk_kod} {rota} gidiş".strip()
                    nak_sira = 1
                else:
                    nak_aciklama = f"{ilk_kod} {sube_adi}→{firma_kisa}".strip(' →') if (sube_adi or firma_kisa) else 'Nakliye Hizmeti'
                    nak_sira = 1
                rows.append({'id': nakliye.id, 'sort_date': nakliye_islem_tarihi or form_tarihi,
                    'form_no': kir.kiralama_form_no, 'form_tarihi': form_tarihi,
                    'kiralama_id': kir.id, 'islem_turu': 'nakliye', 'nakliye_sira': nak_sira,
                    'aciklama': nak_aciklama, 'seri_no': '',
                    'baslangic': nakliye_islem_tarihi, 'bitis': None,
                    'bitis_bugun': False, 'gun_sayisi': None,
                    'brm_fiyat': nak_tutar, 'matrah': nak_tutar, 'kdv_orani': nak_kdv_pct,
                    'kdv_tutar': nak_kdv, 'tevkifat_str': (nakliye.tevkifat_orani or ''),
                    'toplam': nak_tutar + nak_kdv, 'bakiye': 0.0})

        # --- Dış tedarik kiralaması ---
        # bakiye_ozeti ile tutarlılık için: aktif kalemler önce fatura kayıtlarına
        # (HizmetKaydi gelen, ozel_id=kalem.id) bakılır. Fatura varsa faturadan
        # satır üretilir; yoksa (henüz faturalanmamışsa) dinamik hesap kullanılır.
        harici_kalemler = KiralamaKalemi.query.filter_by(
            harici_ekipman_tedarikci_id=firma.id, is_active=True
        ).all()
        for kalem in harici_kalemler:
            kir = kalem.kiralama
            if not kir:
                continue
            form_tarihi = kir.kiralama_olusturma_tarihi or (kir.created_at.date() if kir.created_at else None)
            seri_no = kalem.harici_ekipman_seri_no or ''
            kap = f"{kalem.harici_ekipman_kapasite}kg" if kalem.harici_ekipman_kapasite else ''
            yuk = f"/{kalem.harici_ekipman_yukseklik}m" if kalem.harici_ekipman_yukseklik else ''
            aciklama_base = f"{kalem.harici_ekipman_marka or ''} {kalem.harici_ekipman_model or ''} - {kap}{yuk}".strip(' -') or 'Tedarik Edilen Ekipman'

            # Fatura bazlı satırlar (bakiye_ozeti ile aynı kaynak)
            harici_faturalar = HizmetKaydi.query.filter_by(
                ozel_id=kalem.id, firma_id=firma.id, yon='gelen', is_deleted=False
            ).order_by(HizmetKaydi.tarih).all()

            if harici_faturalar:
                for hkd in harici_faturalar:
                    islem_tarih = getattr(hkd, 'islem_tarihi', None) or hkd.tarih
                    hkd_tutar = float(hkd.tutar or 0)
                    hkd_kdv_pct = float(
                        hkd.kiralama_alis_kdv if hkd.kiralama_alis_kdv is not None
                        else (hkd.kdv_orani or 0)
                    )
                    hkd_kdv = hkd_tutar * hkd_kdv_pct / 100
                    rows.append({
                        'id': hkd.id, 'sort_date': islem_tarih or form_tarihi,
                        'form_no': kir.kiralama_form_no, 'form_tarihi': form_tarihi,
                        'kiralama_id': kir.id, 'islem_turu': 'harici_kiralama', 'nakliye_sira': 0,
                        'aciklama': hkd.aciklama or aciklama_base, 'seri_no': seri_no,
                        'baslangic': islem_tarih, 'bitis': None,
                        'bitis_bugun': False, 'gun_sayisi': None,
                        'brm_fiyat': hkd_tutar, 'matrah': hkd_tutar, 'kdv_orani': hkd_kdv_pct,
                        'kdv_tutar': hkd_kdv, 'toplam': -(hkd_tutar + hkd_kdv), 'bakiye': 0.0,
                    })
                    included_hizmet_kaydi_ids.add(hkd.id)
            else:
                # Henüz faturalanmamış: dinamik (tahakkuk) hesap
                alis_kdv_pct = kalem.kiralama_alis_kdv if kalem.kiralama_alis_kdv is not None else 0
                if kalem.kiralama_baslangici:
                    if kalem.sonlandirildi and kalem.kiralama_bitis:
                        bitis = kalem.kiralama_bitis
                        bitis_bugun = False
                    else:
                        bitis = today_date
                        bitis_bugun = True
                    gun_sayisi = (bitis - kalem.kiralama_baslangici).days + 1
                else:
                    bitis = None
                    bitis_bugun = False
                    gun_sayisi = 0
                alis_fiyat = float(kalem.kiralama_alis_fiyat or 0)
                matrah = alis_fiyat * gun_sayisi
                kdv_tutar = matrah * alis_kdv_pct / 100
                toplam = -(matrah + kdv_tutar)
                rows.append({
                    'id': kalem.id, 'sort_date': kalem.kiralama_baslangici or form_tarihi,
                    'form_no': kir.kiralama_form_no, 'form_tarihi': form_tarihi,
                    'kiralama_id': kir.id, 'islem_turu': 'harici_kiralama', 'nakliye_sira': 0,
                    'aciklama': aciklama_base, 'seri_no': seri_no,
                    'baslangic': kalem.kiralama_baslangici, 'bitis': bitis,
                    'bitis_bugun': bitis_bugun, 'gun_sayisi': gun_sayisi,
                    'brm_fiyat': alis_fiyat, 'matrah': matrah, 'kdv_orani': alis_kdv_pct,
                    'kdv_tutar': kdv_tutar, 'toplam': toplam, 'bakiye': 0.0,
                })

        # --- Standalone nakliye satışları ---
        standalone_nakliyeler = Nakliye.query.filter(
            Nakliye.firma_id == firma.id,
            Nakliye.is_active == True,
            Nakliye.kiralama_id == None
        ).order_by(Nakliye.islem_tarihi, Nakliye.tarih).all()
        for nakliye in standalone_nakliyeler:
            nakliye_tutar = float(nakliye.tutar or 0)
            nakliye_islem_tarihi = getattr(nakliye, 'islem_tarihi', None) or nakliye.tarih
            # Muhasebe tek-kural: cari hareketler KDV dahil yürür ve box (bakiye_ozeti)
            # ile aynı KDV kaynağını kullanır. Bu nedenle brüt kdv_orani esas alınır.
            nakliye_kdv_pct = float(nakliye.kdv_orani or 0)
            nakliye_kdv = nakliye_tutar * nakliye_kdv_pct / 100
            nakliye_toplam = nakliye_tutar + nakliye_kdv
            rows.append({'id': nakliye.id, 'sort_date': nakliye_islem_tarihi,
                'form_no': '-', 'form_tarihi': nakliye_islem_tarihi,
                'kiralama_id': None, 'islem_turu': 'nakliye_satis', 'nakliye_sira': 1,
                'aciklama': nakliye.guzergah or 'Nakliye Hizmeti', 'seri_no': '',
                'baslangic': nakliye_islem_tarihi, 'bitis': None,
                'bitis_bugun': False, 'gun_sayisi': None,
                'brm_fiyat': nakliye_tutar, 'matrah': nakliye_tutar, 'kdv_orani': nakliye_kdv_pct,
                'kdv_tutar': nakliye_kdv, 'tevkifat_str': (nakliye.tevkifat_orani or ''),
                'toplam': nakliye_toplam, 'bakiye': 0.0})

        # --- Kiralama kalemi kaynaklı taşeron nakliye giderleri ---
        taseron_nakliye_kayitlari = HizmetKaydi.query.filter(
            HizmetKaydi.firma_id == firma.id,
            HizmetKaydi.is_deleted == False,
            HizmetKaydi.yon == 'gelen',
            HizmetKaydi.ozel_id.isnot(None),
            or_(
                HizmetKaydi.aciklama.like('Taşeron Nakliye Bedeli%'),
                HizmetKaydi.aciklama.like('Dönüş Nakliye:%')
            )
        ).order_by(HizmetKaydi.tarih).all()
        for hizmet in taseron_nakliye_kayitlari:
            islem_tarih = getattr(hizmet, 'islem_tarihi', None) or hizmet.tarih
            matrah = float(hizmet.tutar or 0)
            kdv_pct = (
                hizmet.nakliye_alis_kdv
                if hizmet.nakliye_alis_kdv is not None
                else (hizmet.kdv_orani or 0)
            )
            kdv_tutar = matrah * kdv_pct / 100
            toplam = -(matrah + kdv_tutar)
            rows.append({
                'id': hizmet.id, 'sort_date': islem_tarih,
                'form_no': hizmet.fatura_no or '-', 'form_tarihi': islem_tarih,
                'kiralama_id': None, 'islem_turu': 'nakliye_tedarik', 'nakliye_sira': 2,
                'aciklama': hizmet.aciklama or 'Taşeron Nakliye',
                'seri_no': '',
                'baslangic': islem_tarih, 'bitis': None,
                'bitis_bugun': False, 'gun_sayisi': None,
                'brm_fiyat': matrah, 'matrah': matrah, 'kdv_orani': kdv_pct,
                'kdv_tutar': kdv_tutar, 'toplam': toplam, 'bakiye': 0.0
            })
            included_hizmet_kaydi_ids.add(hizmet.id)

        # --- Fatura girişleri (HizmetKaydi) ---
        faturalar = HizmetKaydi.query.filter_by(
            firma_id=firma.id, is_deleted=False
        ).order_by(HizmetKaydi.tarih).all()
        for fatura in faturalar:
            islem_tarih = getattr(fatura, 'islem_tarihi', None) or fatura.tarih
            # nakliye_id dolu → nakliye satırı olarak zaten gösterildi
            if getattr(fatura, 'nakliye_id', None):
                continue
            # Önceki adımlarda zaten satıra dönüştürülen HKD'ler (harici kiralama, taşeron)
            if fatura.id in included_hizmet_kaydi_ids:
                continue
            # ozel_id dolu → kiralama modülü muhasebe kaydı (Kiralama Bekleyen Bakiye vb.)
            # Finansal karşılığı kiralama kalem satırlarında zaten var; tekrar ekleme.
            # İstisna: "Dış Kiralama" fatura kayıtları — pasif kalem için gösterilmeli.
            ozel_id = getattr(fatura, 'ozel_id', None)
            if ozel_id is not None:
                aciklama_text = (fatura.aciklama or '').strip()
                is_harici_kiralama_fatura = (
                    aciklama_text.startswith('Dış Kiralama')
                    or aciklama_text.startswith('Dis Kiralama')
                )
                if not is_harici_kiralama_fatura:
                    continue
                kalem_obj = db.session.get(KiralamaKalemi, ozel_id)
                if kalem_obj and getattr(kalem_obj, 'is_active', True):
                    continue
            tutar = float(fatura.tutar or 0)
            kdv_pct = (
                fatura.nakliye_alis_kdv
                if fatura.nakliye_alis_kdv is not None
                else (
                    fatura.kiralama_alis_kdv
                    if fatura.kiralama_alis_kdv is not None
                    else (fatura.kdv_orani or 0)
                )
            )
            kdv_tutar = tutar * kdv_pct / 100
            toplam = tutar + kdv_tutar
            if fatura.yon == 'giden':
                toplam_sign = toplam
            else:
                toplam_sign = -toplam
            tur_adi = 'Fatura (Satış)' if fatura.yon == 'giden' else 'Fatura (Alış)'
            islem_turu = 'fatura'
            kiralama_link_id = None
            if ozel_id is not None:
                kalem_obj = db.session.get(KiralamaKalemi, ozel_id)
                if kalem_obj:
                    kiralama_link_id = kalem_obj.kiralama_id
            rows.append({'id': fatura.id, 'sort_date': islem_tarih,
                'form_no': fatura.fatura_no or '-', 'form_tarihi': islem_tarih,
                'kiralama_id': kiralama_link_id, 'islem_turu': islem_turu, 'nakliye_sira': 3,
                'aciklama': fatura.aciklama or tur_adi, 'seri_no': '',
                'baslangic': islem_tarih, 'bitis': None,
                'bitis_bugun': False, 'gun_sayisi': None,
                'brm_fiyat': tutar, 'matrah': tutar, 'kdv_orani': kdv_pct,
                'kdv_tutar': kdv_tutar, 'toplam': toplam_sign, 'bakiye': 0.0})

        # --- Tahsilat ve Ödeme satırları ---
        finansal_islemler = Odeme.query.filter(
            Odeme.firma_musteri_id == firma.id,
            Odeme.yon.in_(['tahsilat', 'odeme']),
            Odeme.is_deleted == False
        ).order_by(Odeme.islem_tarihi, Odeme.tarih).all()
        for odeme in finansal_islemler:
            tutar = float(odeme.tutar or 0)
            odeme_islem_tarihi = getattr(odeme, 'islem_tarihi', None) or odeme.tarih
            if odeme.yon == 'tahsilat':
                toplam_sign = -tutar
                aciklama    = odeme.aciklama or 'Tahsilat'
                islem_turu  = 'tahsilat'
            else:
                toplam_sign = +tutar
                aciklama    = odeme.aciklama or 'Ödeme (Çıkış)'
                islem_turu  = 'odeme'
            rows.append({'id': odeme.id, 'sort_date': odeme_islem_tarihi,
                'form_no': odeme.fatura_no or '-', 'form_tarihi': odeme_islem_tarihi,
                'kiralama_id': None, 'islem_turu': islem_turu, 'nakliye_sira': 3,
                'aciklama': aciklama, 'seri_no': '',
                'baslangic': odeme_islem_tarihi, 'bitis': None,
                'bitis_bugun': False, 'gun_sayisi': None,
                'brm_fiyat': 0.0, 'matrah': tutar, 'kdv_orani': 0,
                'kdv_tutar': 0.0, 'toplam': toplam_sign, 'bakiye': 0.0})

        # --- Birleşik model ile sırala ---
        # Bazı legacy satırlarda kiralama_id boş gelebilir; form no üzerinden linki tamamla.
        kiralama_id_by_form_no = {}
        for k in (firma.kiralamalar or []):
            for key in FirmaService._form_no_link_keys(k.kiralama_form_no):
                kiralama_id_by_form_no[key] = k.id
        for row in rows:
            if row.get('kiralama_id'):
                continue
            form_no = (row.get('form_no') or '').strip()
            if not form_no or form_no == '-':
                continue
            for key in FirmaService._form_no_link_keys(form_no):
                mapped_id = kiralama_id_by_form_no.get(key)
                if mapped_id:
                    row['kiralama_id'] = mapped_id
                    break

        rows.sort(key=_unified_row_sort_key)

        # Kümülatif bakiye: KDV dahil signed toplam yürüyüşü.
        # Dış kaynağa (bakiye_ozeti) sabitleme yok; satır seti kendi kanonik kaynağıdır.
        FirmaService._apply_unified_running_balance(
            items=rows,
            amount_key='toplam',
            balance_key='bakiye',
            sort_key_fn=_unified_row_sort_key,
        )

        return rows

    @classmethod
    def guncelle_firma_cari_cache(cls, firma_id, auto_commit=True):
        """build_cari_rows sonucunu Firma tablosundaki cache alanlarına yazar.
        Cari durum raporu bu cache'i tek SQL ile okur."""
        firma = db.session.get(Firma, firma_id)
        if not firma:
            return
        rows = cls.build_cari_rows(firma, date.today())
        borc = Decimal('0')
        alacak = Decimal('0')
        for row in rows:
            t = Decimal(str(row.get('toplam') or 0))
            if t > 0:
                borc += t
            elif t < 0:
                alacak += t
        firma.cari_borc_kdvli = borc
        firma.cari_alacak_kdvli = abs(alacak)
        firma.cari_bakiye_kdvli = borc + alacak
        firma.cari_son_guncelleme = datetime.now(timezone.utc)
        if auto_commit:
            db.session.commit()
