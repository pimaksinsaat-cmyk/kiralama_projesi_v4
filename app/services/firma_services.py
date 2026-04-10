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
            # Form numarasına göre (yeniden eskiye), form içinde tarihe göre (yeniden eskiye), nakliye_sira'ya göre
            form_no = x.get('form_no') or ''
            tarih = x.get('tarih') or date.min
            nakliye_sira = x.get('nakliye_sira', 3)

            tarih_ordinal = tarih.toordinal() if isinstance(tarih, date) else 0

            return (
                -len(form_no),  # form_no'su olan önce (daha uzun string)
                tuple(127 - ord(c) for c in form_no) if form_no else (),  # form_no'ya göre ters
                -tarih_ordinal,  # tarih yeniden eskiye
                nakliye_sira  # nakliye sıraı artan
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

                rows.append({'id': kalem.id, 'sort_date': form_tarihi or kalem.kiralama_baslangici,
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
                nak_kdv_pct = nakliye.kdv_orani or 0
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
                rows.append({'id': nakliye.id, 'sort_date': nakliye.tarih or form_tarihi,
                    'form_no': kir.kiralama_form_no, 'form_tarihi': form_tarihi,
                    'kiralama_id': kir.id, 'islem_turu': 'nakliye', 'nakliye_sira': nak_sira,
                    'aciklama': nak_aciklama, 'seri_no': '',
                    'baslangic': nakliye.tarih, 'bitis': None,
                    'bitis_bugun': False, 'gun_sayisi': None,
                    'brm_fiyat': nak_tutar, 'matrah': nak_tutar, 'kdv_orani': nak_kdv_pct,
                    'kdv_tutar': nak_kdv, 'toplam': nak_tutar + nak_kdv, 'bakiye': 0.0})

        # --- Dış tedarik kiralaması ---
        harici_kalemler = KiralamaKalemi.query.filter_by(
            harici_ekipman_tedarikci_id=firma.id, is_active=True
        ).all()
        for kalem in harici_kalemler:
            kir = kalem.kiralama
            if not kir:
                continue
            form_tarihi = kir.kiralama_olusturma_tarihi or (kir.created_at.date() if kir.created_at else None)
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
            seri_no = kalem.harici_ekipman_seri_no or ''
            kap = f"{kalem.harici_ekipman_kapasite}kg" if kalem.harici_ekipman_kapasite else ''
            yuk = f"/{kalem.harici_ekipman_yukseklik}m" if kalem.harici_ekipman_yukseklik else ''
            aciklama = f"{kalem.harici_ekipman_marka or ''} {kalem.harici_ekipman_model or ''} - {kap}{yuk}".strip(' -')
            rows.append({'id': kalem.id, 'sort_date': form_tarihi or kalem.kiralama_baslangici,
                'form_no': kir.kiralama_form_no, 'form_tarihi': form_tarihi,
                'kiralama_id': kir.id, 'islem_turu': 'harici_kiralama', 'nakliye_sira': 0,
                'aciklama': aciklama or 'Tedarik Edilen Ekipman', 'seri_no': seri_no,
                'baslangic': kalem.kiralama_baslangici, 'bitis': bitis,
                'bitis_bugun': bitis_bugun, 'gun_sayisi': gun_sayisi,
                'brm_fiyat': alis_fiyat, 'matrah': matrah, 'kdv_orani': alis_kdv_pct,
                'kdv_tutar': kdv_tutar, 'toplam': toplam, 'bakiye': 0.0})

        # --- Standalone nakliye satışları ---
        standalone_nakliyeler = Nakliye.query.filter(
            Nakliye.firma_id == firma.id,
            Nakliye.is_active == True,
            Nakliye.kiralama_id == None
        ).order_by(Nakliye.tarih).all()
        for nakliye in standalone_nakliyeler:
            nakliye_tutar = float(nakliye.tutar or 0)
            nakliye_kdv_pct = nakliye.kdv_orani or 0
            nakliye_kdv = nakliye_tutar * nakliye_kdv_pct / 100
            nakliye_toplam = nakliye_tutar + nakliye_kdv
            rows.append({'id': nakliye.id, 'sort_date': nakliye.tarih,
                'form_no': '-', 'form_tarihi': nakliye.tarih,
                'kiralama_id': None, 'islem_turu': 'nakliye_satis', 'nakliye_sira': 1,
                'aciklama': nakliye.guzergah or 'Nakliye Hizmeti', 'seri_no': '',
                'baslangic': nakliye.tarih, 'bitis': None,
                'bitis_bugun': False, 'gun_sayisi': None,
                'brm_fiyat': nakliye_tutar, 'matrah': nakliye_tutar, 'kdv_orani': nakliye_kdv_pct,
                'kdv_tutar': nakliye_kdv, 'toplam': nakliye_toplam, 'bakiye': 0.0})

        # --- Fatura girişleri (HizmetKaydi) ---
        faturalar = HizmetKaydi.query.filter_by(
            firma_id=firma.id, is_deleted=False
        ).order_by(HizmetKaydi.tarih).all()
        for fatura in faturalar:
            # nakliye_id dolu → nakliye satırı olarak zaten gösterildi, atla
            if getattr(fatura, 'nakliye_id', None):
                continue
            # ozel_id dolu → kiralama modülü muhasebe kaydı (Bekleyen Bakiye, Dönüş Nakliye vb.), atla
            if getattr(fatura, 'ozel_id', None) is not None:
                continue
            tutar = float(fatura.tutar or 0)
            kdv_pct = fatura.kdv_orani or 0
            kdv_tutar = tutar * kdv_pct / 100
            toplam = tutar + kdv_tutar
            if fatura.yon == 'giden':
                toplam_sign = toplam
            else:
                toplam_sign = -toplam
            tur_adi = 'Fatura (Satış)' if fatura.yon == 'giden' else 'Fatura (Alış)'
            rows.append({'id': fatura.id, 'sort_date': fatura.tarih,
                'form_no': fatura.fatura_no or '-', 'form_tarihi': fatura.tarih,
                'kiralama_id': None, 'islem_turu': 'fatura', 'nakliye_sira': 3,
                'aciklama': fatura.aciklama or tur_adi, 'seri_no': '',
                'baslangic': fatura.tarih, 'bitis': None,
                'bitis_bugun': False, 'gun_sayisi': None,
                'brm_fiyat': tutar, 'matrah': tutar, 'kdv_orani': kdv_pct,
                'kdv_tutar': kdv_tutar, 'toplam': toplam_sign, 'bakiye': 0.0})

        # --- Tahsilat ve Ödeme satırları ---
        finansal_islemler = Odeme.query.filter(
            Odeme.firma_musteri_id == firma.id,
            Odeme.yon.in_(['tahsilat', 'odeme']),
            Odeme.is_deleted == False
        ).order_by(Odeme.tarih).all()
        for odeme in finansal_islemler:
            tutar = float(odeme.tutar or 0)
            if odeme.yon == 'tahsilat':
                toplam_sign = -tutar
                aciklama    = odeme.aciklama or 'Tahsilat'
                islem_turu  = 'tahsilat'
            else:
                toplam_sign = +tutar
                aciklama    = odeme.aciklama or 'Ödeme (Çıkış)'
                islem_turu  = 'odeme'
            rows.append({'id': odeme.id, 'sort_date': odeme.tarih,
                'form_no': odeme.fatura_no or '-', 'form_tarihi': odeme.tarih,
                'kiralama_id': None, 'islem_turu': islem_turu, 'nakliye_sira': 3,
                'aciklama': aciklama, 'seri_no': '',
                'baslangic': odeme.tarih, 'bitis': None,
                'bitis_bugun': False, 'gun_sayisi': None,
                'brm_fiyat': 0.0, 'matrah': tutar, 'kdv_orani': 0,
                'kdv_tutar': 0.0, 'toplam': toplam_sign, 'bakiye': 0.0})

        # --- Başlangıç tarihine göre sırala, kümülatif bakiye hesapla ---
        rows.sort(key=lambda r: (
            (r['baslangic'] or date.min).toordinal(),
            r['nakliye_sira'],
        ))
        kumulatif = 0.0
        for r in rows:
            kumulatif += r['toplam']
            r['bakiye'] = kumulatif

        return rows
