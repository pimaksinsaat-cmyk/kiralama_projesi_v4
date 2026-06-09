import traceback
import threading
import json
from decimal import Decimal, InvalidOperation
from datetime import datetime, date, timedelta, timezone
from urllib.parse import urlsplit
from flask import render_template, redirect, url_for, flash, request, current_app, jsonify, session
from flask_login import current_user, login_required
from sqlalchemy import or_, func, not_
from sqlalchemy.orm import joinedload

from app import db
from app.kiralama import kiralama_bp

# Modeller
from app.firmalar.models import Firma
from app.kiralama.models import Kiralama, KiralamaKalemi
from app.filo.models import Ekipman
from app.filo.forms import EKIPMAN_TIPI_SECENEKLERI
from app.subeler.models import Sube
from app.araclar.models import Arac as NakliyeAraci
from app.kiralama.forms import KiralamaForm

# Servis Katmanı ve Hata Yönetimi
from app.services.kiralama_services import KiralamaService, KiralamaKalemiService
from app.services.base import ValidationError
from app.services.operation_log_service import OperationLogService
from app.utils import ensure_active_sube_exists, get_safe_next_redirect, tr_ilike

# --- BELLEK İÇİ ÖNBELLEKLEME (IN-MEMORY CACHE) ---
_CACHE_DATA = {
    'subeler': {'data': None, 'last_update': None},
    'aktif_araclar': {'data': None, 'last_update': None}
}

# DARBOĞAZ ÖNLEME: Her veri kümesi için ayrı kilit (lock) tanımlandı.
# Böylece şube güncellenirken araç listesi etkilenmez.
_SUBE_CACHE_LOCK = threading.Lock()
_ARAC_CACHE_LOCK = threading.Lock()

_CACHE_TIMEOUT_MINUTES = 60 

def _kiralama_return_url(default_endpoint='kiralama.index'):
    default_url = url_for(default_endpoint)
    target = (
        request.form.get('return_url')
        or get_safe_next_redirect(request.args.get('next'))
        or request.referrer
        or default_url
    )
    target = target.strip()
    if not target:
        return default_url

    parsed = urlsplit(target)
    if parsed.netloc and parsed.netloc != request.host:
        return default_url
    if not parsed.netloc and not target.startswith('/'):
        return default_url
    if not (parsed.path or '').startswith('/kiralama'):
        return default_url
    return target


def _kiralama_date_to_iso(value):
    if not value:
        return ''
    if hasattr(value, 'isoformat'):
        return value.isoformat()
    return str(value)


def _fmt_tr_date(value):
    if not value:
        return '-'
    if hasattr(value, 'strftime'):
        return value.strftime('%d.%m.%Y')
    return str(value)


def _kapali_kalem_degisti_mi(k_data, kalem):
    def _money_equal(a, b):
        try:
            left = Decimal(str(a or 0)).quantize(Decimal('0.01'))
            right = Decimal(str(b or 0)).quantize(Decimal('0.01'))
            return left == right
        except (InvalidOperation, ValueError, TypeError):
            return str(a or '') == str(b or '')

    def _int_equal(a, b):
        try:
            left = None if a in (None, '') else int(a)
            right = None if b in (None, '') else int(b)
            return left == right
        except (TypeError, ValueError):
            return str(a or '') == str(b or '')

    def _bool_equal(a, b):
        def _to_bool(value):
            try:
                return bool(int(value or 0))
            except (TypeError, ValueError):
                return str(value).lower() in ('true', 'on', 'yes')
        return _to_bool(a) == bool(b)

    return any((
        not _int_equal(k_data.get('dis_tedarik_ekipman'), 1 if kalem.is_dis_tedarik_ekipman else 0),
        not _int_equal(k_data.get('ekipman_id'), kalem.ekipman_id),
        not _int_equal(k_data.get('harici_ekipman_tedarikci_id'), kalem.harici_ekipman_tedarikci_id),
        (k_data.get('harici_ekipman_tipi') or '') != (kalem.harici_ekipman_tipi or ''),
        (k_data.get('harici_ekipman_marka') or '') != (kalem.harici_ekipman_marka or ''),
        (k_data.get('harici_ekipman_model') or '') != (kalem.harici_ekipman_model or ''),
        (k_data.get('harici_ekipman_seri_no') or '') != (kalem.harici_ekipman_seri_no or ''),
        not _int_equal(k_data.get('harici_ekipman_kaldirma_kapasitesi'), kalem.harici_ekipman_kapasite),
        not _int_equal(k_data.get('harici_ekipman_calisma_yuksekligi'), kalem.harici_ekipman_yukseklik),
        not _int_equal(k_data.get('harici_ekipman_uretim_tarihi'), kalem.harici_ekipman_uretim_yili),
        _kiralama_date_to_iso(k_data.get('kiralama_baslangici')) != _kiralama_date_to_iso(kalem.kiralama_baslangici),
        _kiralama_date_to_iso(k_data.get('kiralama_bitis')) != _kiralama_date_to_iso(kalem.kiralama_bitis),
        not _money_equal(k_data.get('kiralama_brm_fiyat'), kalem.kiralama_brm_fiyat),
        not _money_equal(k_data.get('kiralama_alis_fiyat'), kalem.kiralama_alis_fiyat),
        not _int_equal(k_data.get('kiralama_alis_kdv'), kalem.kiralama_alis_kdv),
        not _int_equal(k_data.get('dis_tedarik_nakliye'), 1 if kalem.is_harici_nakliye else 0),
        not _int_equal(k_data.get('nakliye_tedarikci_id'), kalem.nakliye_tedarikci_id),
        not _int_equal(k_data.get('nakliye_araci_id'), kalem.nakliye_araci_id),
        not _money_equal(k_data.get('nakliye_satis_fiyat'), kalem.nakliye_satis_fiyat),
        not _money_equal(k_data.get('nakliye_alis_fiyat'), kalem.nakliye_alis_fiyat),
        not _int_equal(k_data.get('nakliye_alis_kdv'), kalem.nakliye_alis_kdv),
        not _int_equal(k_data.get('nakliye_satis_kdv'), kalem.nakliye_satis_kdv),
        (k_data.get('nakliye_alis_tevkifat_oran') or '') != (kalem.nakliye_alis_tevkifat_oran or ''),
        (k_data.get('nakliye_satis_tevkifat_oran') or '') != (kalem.nakliye_satis_tevkifat_oran or ''),
        not _bool_equal(k_data.get('donus_nakliye_fatura_et'), kalem.donus_nakliye_fatura_et),
        not _bool_equal(k_data.get('donus_is_harici_nakliye'), getattr(kalem, 'donus_is_harici_nakliye', False)),
        not _int_equal(k_data.get('donus_nakliye_tedarikci_id'), kalem.donus_nakliye_tedarikci_id),
        not _money_equal(k_data.get('donus_nakliye_alis_fiyat'), kalem.donus_nakliye_alis_fiyat),
        not _int_equal(k_data.get('donus_nakliye_alis_kdv'), kalem.donus_nakliye_alis_kdv),
        not _int_equal(k_data.get('donus_nakliye_araci_id'), kalem.donus_nakliye_araci_id),
    ))


def _kiralama_tarih_cakismalari(kalemler_data):
    conflicts = []
    posted_ranges = []

    for idx, k_data in enumerate(kalemler_data):
        try:
            kalem_id = int(k_data.get('id') or 0)
            ekipman_id = int(k_data.get('ekipman_id') or 0)
            is_dis = int(k_data.get('dis_tedarik_ekipman') or 0) == 1
        except (TypeError, ValueError):
            continue

        bas = k_data.get('kiralama_baslangici')
        bit = k_data.get('kiralama_bitis')
        if is_dis or ekipman_id <= 0 or not bas or not bit:
            continue

        ekipman = db.session.get(Ekipman, ekipman_id)
        makine_kod = ekipman.kod if ekipman else f'ID {ekipman_id}'

        for onceki in posted_ranges:
            if onceki['ekipman_id'] == ekipman_id and bas <= onceki['bit'] and bit >= onceki['bas']:
                message = (
                    f"{makine_kod} makinesi aynı form içinde {idx + 1}. satır ile "
                    f"{onceki['idx'] + 1}. satır arasında çakışıyor "
                    f"({_fmt_tr_date(bas)} - {_fmt_tr_date(bit)} / "
                    f"{_fmt_tr_date(onceki['bas'])} - {_fmt_tr_date(onceki['bit'])})."
                )
                conflicts.append({
                    'idx': idx,
                    'field': 'both',
                    'message': message,
                    'machine': makine_kod,
                    'conflict_form_no': 'Aynı form',
                    'conflict_range': f"{_fmt_tr_date(onceki['bas'])} - {_fmt_tr_date(onceki['bit'])}",
                })

        cakisan = (
            KiralamaKalemi.query
            .join(Kiralama, KiralamaKalemi.kiralama_id == Kiralama.id)
            .filter(
                KiralamaKalemi.ekipman_id == ekipman_id,
                KiralamaKalemi.id != kalem_id,
                KiralamaKalemi.is_deleted == False,
                Kiralama.is_deleted == False,
                KiralamaKalemi.kiralama_baslangici <= bit,
                KiralamaKalemi.kiralama_bitis >= bas,
            )
            .order_by(KiralamaKalemi.kiralama_baslangici.asc())
            .first()
        )
        if cakisan:
            cakisan_form_no = cakisan.kiralama.kiralama_form_no if cakisan.kiralama else f"#{cakisan.kiralama_id}"
            message = (
                f"{makine_kod} makinesi {cakisan_form_no} formunda "
                f"{_fmt_tr_date(cakisan.kiralama_baslangici)} - {_fmt_tr_date(cakisan.kiralama_bitis)} "
                f"tarihleri arasında kirada. Girilen aralık: {_fmt_tr_date(bas)} - {_fmt_tr_date(bit)}."
            )
            conflicts.append({
                'idx': idx,
                'field': 'both',
                'message': message,
                'machine': makine_kod,
                'conflict_form_no': cakisan_form_no,
                'conflict_range': f"{_fmt_tr_date(cakisan.kiralama_baslangici)} - {_fmt_tr_date(cakisan.kiralama_bitis)}",
            })

        posted_ranges.append({
            'idx': idx,
            'ekipman_id': ekipman_id,
            'bas': bas,
            'bit': bit,
        })

    return conflicts


def _redirect_to_kiralama_return():
    return redirect(_kiralama_return_url())


def _kiralama_wants_json():
    return (
        request.args.get('format') == 'json'
        or request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        or 'application/json' in (request.headers.get('Accept') or '')
    )

def get_cached_subeler():
    """Şubeleri thread-safe ve bağımsız bir kilitle bellekten getirir.
    ORM objeleri yerine düz dict döner; session detach sorunu oluşmaz."""
    now = datetime.now()
    cache = _CACHE_DATA['subeler']

    if cache['data'] is not None and cache['last_update'] is not None and (now - cache['last_update']) < timedelta(minutes=_CACHE_TIMEOUT_MINUTES):
        return cache['data']

    with _SUBE_CACHE_LOCK:
        if cache['data'] is None or cache['last_update'] is None or (datetime.now() - cache['last_update']) > timedelta(minutes=_CACHE_TIMEOUT_MINUTES):
            try:
                cache['data'] = [
                    {'id': s.id, 'isim': s.isim, 'aktif': s.is_active}
                    for s in Sube.query.all()
                ]
                cache['last_update'] = datetime.now()
            except Exception as e:
                current_app.logger.error(f"Sube Cache Hatası: {e}")
                db.session.rollback()
                return cache['data'] or []
    return cache['data']

def get_cached_aktif_araclar():
    """Aktif nakliye araçlarını thread-safe ve bağımsız bir kilitle bellekten getirir.
    ORM objeleri yerine düz dict döner; session detach sorunu oluşmaz."""
    now = datetime.now()
    cache = _CACHE_DATA['aktif_araclar']

    if cache['data'] is not None and cache['last_update'] is not None and (now - cache['last_update']) < timedelta(minutes=_CACHE_TIMEOUT_MINUTES):
        return cache['data']

    with _ARAC_CACHE_LOCK:
        if cache['data'] is None or cache['last_update'] is None or (datetime.now() - cache['last_update']) > timedelta(minutes=_CACHE_TIMEOUT_MINUTES):
            try:
                cache['data'] = [
                    {'id': a.id, 'plaka': a.plaka, 'arac_tipi': a.arac_tipi}
                    for a in NakliyeAraci.aktif_nakliye_query().order_by(NakliyeAraci.plaka).all()
                ]
                cache['last_update'] = datetime.now()
            except Exception as e:
                current_app.logger.error(f"Arac Cache Hatası: {e}")
                db.session.rollback()
                return cache['data'] or []
    return cache['data']

def populate_kiralama_form_choices(form, include_ids=None):
    """
    Formdaki tüm SelectField alanlarını veritabanından dinamik olarak doldurur.
    """
    if include_ids is None: include_ids = []
    
    # 1. Ana Müşteri ve Tedarikçi Listeleri (Dahili firmalar gizlendi)
    musteriler = Firma.query.filter(
        Firma.is_musteri == True, 
        Firma.is_active == True,
        Firma.firma_adi.notin_(['DAHİLİ İŞLEMLER', 'Dahili Kasa İşlemleri'])
    ).order_by(Firma.firma_adi).all()
    form.firma_musteri_id.choices = [(0, '--- Müşteri Seçiniz ---')] + [(f.id, f.firma_adi) for f in musteriler]

    tedarikciler = Firma.query.filter(
        Firma.is_tedarikci == True, 
        Firma.is_active == True,
        Firma.firma_adi.notin_(['DAHİLİ İŞLEMLER', 'Dahili Kasa İşlemleri'])
    ).order_by(Firma.firma_adi).all()
    ted_choices = [(0, '--- Tedarikçi Seçiniz ---')] + [(f.id, f.firma_adi) for f in tedarikciler]
    
    # 2. Makine Parkı (Pimaks Filosu) - Detaylandırılmış Etiketler Eklendi
    filo_query = Ekipman.query.filter(
        Ekipman.firma_tedarikci_id.is_(None),
        or_(Ekipman.calisma_durumu == 'bosta', Ekipman.id.in_(include_ids))
    ).order_by(Ekipman.kod).all()
    
    # KOD | TİP (Marka-Yükseklikm - Kapasitekg) formatı uygulandı
    pimaks_choices = [(0, '--- Seçiniz ---')] + [
        (
            e.id,
            f"{(e.kod or '').strip()} | {(e.tipi or '').strip()} ({(e.marka or 'Bilinmiyor').strip()}-{e.calisma_yuksekligi or 0}m - {e.kaldirma_kapasitesi or 0}kg)"
        )
        for e in filo_query
    ]

    # 3. Nakliye Araçları (Cache destekli)
    arac_choices = [(0, '--- Araç Seçiniz ---')] + [(a['id'], f"{a['plaka']} - {a['arac_tipi']}") for a in get_cached_aktif_araclar()]

    # 4. Kalemler Listesi Doldurma
    if not form.kalemler.entries:
        form.kalemler.append_entry()

    for entry in form.kalemler:
        f = entry.form
        f.ekipman_id.choices = pimaks_choices
        f.harici_ekipman_tedarikci_id.choices = ted_choices
        f.nakliye_tedarikci_id.choices = ted_choices
        if hasattr(f, 'donus_nakliye_tedarikci_id'):
            f.donus_nakliye_tedarikci_id.choices = ted_choices
        if hasattr(f, 'donus_nakliye_araci_id'):
            f.donus_nakliye_araci_id.choices = arac_choices
        f.nakliye_araci_id.choices = arac_choices

@kiralama_bp.route('/')
@kiralama_bp.route('/index')
@login_required
def index():
    """Kiralama ana listesi ve arama."""
    per_page = 25
    q = ''
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 25, type=int)
        if per_page not in {10, 25, 50, 100}:
            per_page = 25
        q = (request.args.get('q', '', type=str) or '').strip()

        query = Kiralama.query.options(
            joinedload(Kiralama.firma_musteri),
            joinedload(Kiralama.kalemler).joinedload(KiralamaKalemi.ekipman)
        ).filter(not_(Kiralama.is_deleted.is_(True)))

        if q:
            search = f"%{q}%"
            query = query.filter(or_(
                Kiralama.kiralama_form_no.ilike(search),
                Kiralama.firma_musteri.has(tr_ilike(Firma.firma_adi, search)),
                Kiralama.kalemler.any(KiralamaKalemi.ekipman.has(Ekipman.kod.ilike(search))),
                Kiralama.kalemler.any(tr_ilike(KiralamaKalemi.harici_ekipman_marka, search)),
                Kiralama.kalemler.any(tr_ilike(KiralamaKalemi.harici_ekipman_model, search)),
                Kiralama.kalemler.any(KiralamaKalemi.harici_ekipman_seri_no.ilike(search)),
            ))

        # Dashboard kartları sayfalamadan bağımsız olarak, filtreye uyan tüm kayıtlar üzerinden hesaplanır.
        stats_raw = query.all()
        stats_kiralamalar = {}
        for kiralama in stats_raw:
            stats_kiralamalar[kiralama.id] = kiralama

        dashboard_stats = {
            'geciken': 0,
            'yaklasan': 0,
            'harici': 0,
            'toplam_hacim': 0,
            'aktif_sozlesme_adedi': 0,
            'aktif_sozlesme_hacmi': 0,
        }
        harici_aktif_kalemler = []
        geciken_kalemler = []
        yaklasan_kalemler = []

        today = date.today()
        for kiralama in stats_kiralamalar.values():
            kiralama_toplam_hacim = 0
            kiralama_aktif_hacim = 0
            kiralama_aktif_kalem_var = False

            for kalem in kiralama.kalemler:
                if getattr(kalem, 'is_deleted', False):
                    continue
                if not kalem.kiralama_baslangici or not kalem.kiralama_bitis:
                    continue

                gun_fark = (kalem.kiralama_bitis - kalem.kiralama_baslangici).days + 1
                if gun_fark <= 0:
                    continue

                bedel = gun_fark * (kalem.kiralama_brm_fiyat or 0)
                kiralama_toplam_hacim += bedel

                if kalem.is_active and not kalem.sonlandirildi:
                    kiralama_aktif_kalem_var = True
                    kiralama_aktif_hacim += bedel

                    kalan = (kalem.kiralama_bitis - today).days
                    if kalan < 0:
                        dashboard_stats['geciken'] += 1
                        geciken_kalemler.append({
                            'kiralama_form_no': kiralama.kiralama_form_no,
                            'musteri_adi': kiralama.firma_musteri.firma_adi if kiralama.firma_musteri else 'Müşteri Tanımsız',
                            'ekipman_adi': (
                                kalem.ekipman.kod if kalem.ekipman
                                else " ".join(
                                    p for p in [kalem.harici_ekipman_marka, kalem.harici_ekipman_model] if p
                                ) or 'Ekipman Tanımsız'
                            ),
                            'baslangic': kalem.kiralama_baslangici.strftime('%d.%m.%Y') if kalem.kiralama_baslangici else '-',
                            'bitis': kalem.kiralama_bitis.strftime('%d.%m.%Y') if kalem.kiralama_bitis else '-',
                            'kalan_gun': kalan,
                        })
                    elif kalan <= 3:
                        dashboard_stats['yaklasan'] += 1
                        yaklasan_kalemler.append({
                            'kiralama_form_no': kiralama.kiralama_form_no,
                            'musteri_adi': kiralama.firma_musteri.firma_adi if kiralama.firma_musteri else 'Müşteri Tanımsız',
                            'ekipman_adi': (
                                kalem.ekipman.kod if kalem.ekipman
                                else " ".join(
                                    p for p in [kalem.harici_ekipman_marka, kalem.harici_ekipman_model] if p
                                ) or 'Ekipman Tanımsız'
                            ),
                            'baslangic': kalem.kiralama_baslangici.strftime('%d.%m.%Y') if kalem.kiralama_baslangici else '-',
                            'bitis': kalem.kiralama_bitis.strftime('%d.%m.%Y') if kalem.kiralama_bitis else '-',
                            'kalan_gun': kalan,
                        })

                    if kalem.is_dis_tedarik_ekipman:
                        dashboard_stats['harici'] += 1
                        harici_aktif_kalemler.append({
                            'kiralama_form_no': kiralama.kiralama_form_no,
                            'musteri_adi': kiralama.firma_musteri.firma_adi if kiralama.firma_musteri else 'Müşteri Tanımsız',
                            'tedarikci_adi': (
                                kalem.harici_tedarikci.firma_adi
                                if getattr(kalem, 'harici_tedarikci', None)
                                else 'Tedarikçi Tanımsız'
                            ),
                            'ekipman_adi': " ".join(
                                p for p in [
                                    kalem.harici_ekipman_tipi,
                                    kalem.harici_ekipman_marka,
                                    kalem.harici_ekipman_model,
                                ] if p
                            ) or 'Harici Ekipman',
                            'ekipman_ozellik': " | ".join(
                                p for p in [
                                    f"Seri: {kalem.harici_ekipman_seri_no}" if kalem.harici_ekipman_seri_no else None,
                                    f"Yükseklik: {kalem.harici_ekipman_yukseklik}m" if kalem.harici_ekipman_yukseklik else None,
                                    f"Kapasite: {kalem.harici_ekipman_kapasite}kg" if kalem.harici_ekipman_kapasite else None,
                                ] if p
                            ) or '-',
                        })

            dashboard_stats['toplam_hacim'] += kiralama_toplam_hacim
            dashboard_stats['aktif_sozlesme_hacmi'] += kiralama_aktif_hacim
            if kiralama_aktif_kalem_var:
                dashboard_stats['aktif_sozlesme_adedi'] += 1

        pagination = query.order_by(Kiralama.kiralama_form_no.desc()).paginate(page=page, per_page=per_page)
        kiralamalar = pagination.items

        # ÖNCELİK: Kalem verilerini rollback'ten etkilenmeden önce hesapla.
        # (guncelle_cari_toplam rollback yaparsa session expire olur ve objelere erişim patlar)
        # İade iptal kısıtlaması kaldırıldı - tüm sonlandırılmış kalemler iptal edilebilir
        recently_returned_kalem_ids = set()
        try:
            recently_returned_kalem_ids = {
                kalem.id
                for kiralama in kiralamalar
                for kalem in kiralama.kalemler
                if (
                    not getattr(kalem, 'is_deleted', False)
                    and kalem.sonlandirildi
                    and kalem.is_active
                )
            }
        except Exception as date_err:
            # Listeyi düşürme; bu alan sadece UI kolaylığıdır.
            current_app.logger.warning(
                "recently_returned_kalem_ids hesaplanamadi: %s",
                date_err,
                exc_info=True,
            )
            recently_returned_kalem_ids = set()

        # Liste ekranında görünen kiralamalar için bekleyen cari tutarı güncel tut.
        # PostgreSQL: Tek transaction içinde bir kiralamada SQL hatası tüm oturumu
        # "aborted" yapar; her kiralama için SAVEPOINT (begin_nested) ile izole et.
        try:
            for kiralama in kiralamalar:
                try:
                    with db.session.begin_nested():
                        KiralamaService.guncelle_cari_toplam(kiralama.id, auto_commit=False)
                except Exception as row_err:
                    current_app.logger.warning(
                        "Kiralama cari senkronizasyon (id=%s): %s",
                        kiralama.id,
                        row_err,
                        exc_info=True,
                    )
            if kiralamalar:
                db.session.commit()
        except Exception as sync_err:
            db.session.rollback()
            current_app.logger.warning(f"Kiralama cari senkronizasyon toplu commit: {sync_err}", exc_info=True)
            pagination = query.order_by(Kiralama.kiralama_form_no.desc()).paginate(page=page, per_page=per_page)
            kiralamalar = pagination.items

        try:
            kurlar = KiralamaService.get_tcmb_kurlari()
        except Exception as kur_err:
            current_app.logger.warning("TCMB kurlari alinamadı (index): %s", kur_err, exc_info=True)
            kurlar = {}
        kur_son_guncelleme_text = KiralamaService.get_kur_son_guncelleme_text()

        try:
            subeler = get_cached_subeler()
        except Exception as sube_err:
            current_app.logger.warning("Sube cache okunamadi (index): %s", sube_err, exc_info=True)
            subeler = []

        try:
            nakliye_araclari = get_cached_aktif_araclar()
        except Exception as arac_err:
            current_app.logger.warning("Arac cache okunamadi (index): %s", arac_err, exc_info=True)
            nakliye_araclari = []

        try:
            nakliye_tedarikci_listesi = Firma.query.filter_by(is_tedarikci=True).order_by(Firma.firma_adi).all()
        except Exception as tedarikci_err:
            current_app.logger.warning("Tedarikci listesi okunamadi (index): %s", tedarikci_err, exc_info=True)
            nakliye_tedarikci_listesi = []

        return render_template(
            'kiralama/index.html',
            kiralamalar=kiralamalar,
            pagination=pagination,
            per_page=per_page,
            q=q,
            kurlar=kurlar,
            kur_son_guncelleme=kur_son_guncelleme_text,
            today=date.today(),
            subeler=subeler,
            nakliye_araclari=nakliye_araclari,
            nakliye_tedarikci_listesi=nakliye_tedarikci_listesi,
            recently_returned_kalem_ids=recently_returned_kalem_ids,
            dashboard_stats=dashboard_stats,
            harici_aktif_kalemler=harici_aktif_kalemler,
            geciken_kalemler=geciken_kalemler,
            yaklasan_kalemler=yaklasan_kalemler,
        )
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Kiralama Liste Yükleme Hatası: {str(e)}\n{traceback.format_exc()}")
        flash("Liste yüklenirken bir hata oluştu. Detaylar sunucu günlüğüne yazıldı.", "danger")
        try:
            return render_template(
                'kiralama/index.html',
                kiralamalar=[],
                pagination=None,
                per_page=per_page,
                q=q,
                kurlar={},
                kur_son_guncelleme='Henüz güncellenmedi',
                today=date.today(),
                subeler=[],
                nakliye_araclari=[],
                nakliye_tedarikci_listesi=[],
                recently_returned_kalem_ids=set(),
                dashboard_stats={
                    'geciken': 0,
                    'yaklasan': 0,
                    'harici': 0,
                    'toplam_hacim': 0,
                    'aktif_sozlesme_adedi': 0,
                    'aktif_sozlesme_hacmi': 0,
                },
                harici_aktif_kalemler=[],
                geciken_kalemler=[],
                yaklasan_kalemler=[],
            )
        except Exception as render_err:
            current_app.logger.error(
                "Kiralama liste hata sayfası render edilemedi: %s",
                render_err,
                exc_info=True,
            )
            raise

@kiralama_bp.route('/detay/<int:kiralama_id>')
@login_required
def detay_modal(kiralama_id):
    """AJAX: Kiralama detay bilgilerini modal içeriği olarak döner."""
    kiralama = (
        Kiralama.query.options(
            joinedload(Kiralama.firma_musteri),
            joinedload(Kiralama.kalemler).joinedload(KiralamaKalemi.ekipman),
        )
        .filter(
            Kiralama.id == kiralama_id,
            not_(Kiralama.is_deleted.is_(True)),
        )
        .first_or_404()
    )
    return render_template(
        'kiralama/detay_modal_content.html',
        kiralama=kiralama,
        today=date.today(),
    )


@kiralama_bp.route('/ekle', methods=['GET', 'POST'])
@login_required
def ekle():
    """Yeni kiralama kaydı oluşturma."""
    guard_response = ensure_active_sube_exists(
        warning_message="Kiralama oluşturmadan önce en az bir aktif şube / depo tanımlamalısınız."
    )
    if guard_response:
        return guard_response

    form = KiralamaForm()
    
    try:
        populate_kiralama_form_choices(form)
    except Exception as e:
        current_app.logger.error(f"Seçenek doldurma hatası (Ekle): {str(e)}")
        flash("Seçenek listeleri yüklenemedi. Lütfen sistem yöneticisine başvurun.", "danger")
        return redirect(url_for('kiralama.index'))

    # --- TCMB KURU VE FORM NUMARASI OTOMATİK DOLDURMA ---
    if request.method == 'GET':
        # Kur bilgisini al
        try:
            kurlar = KiralamaService.get_tcmb_kurlari()
            form.doviz_kuru_usd.data = kurlar.get('USD', 1.0)
            if hasattr(form, 'doviz_kuru_eur'):
                form.doviz_kuru_eur.data = kurlar.get('EUR', 1.0)
        except Exception as e:
            current_app.logger.warning(f"TCMB kur bilgisi alınamadı: {str(e)}")
        
        # Form numarasını otomatik al, hata durumunda manuel girilmesine izin ver
        try:
            form.kiralama_form_no.data = KiralamaService.get_next_form_no()
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Form numarası otomatik alınamadı: {str(e)}")
            # Son form numarasını al ve kullanıcıya bilgi ver
            try:
                last_kiralama = (
                    Kiralama.query.filter(not_(Kiralama.is_deleted.is_(True)))
                    .order_by(Kiralama.id.desc())
                    .first()
                )
                last_form_no = last_kiralama.kiralama_form_no if last_kiralama else "Kayıt bulunamadı"
                flash(
                    f"Uyarı: Form numarası otomatik alınamadı. Son form numarası: {last_form_no}. "
                    f"Lütfen manuel olarak giriniz.",
                    "warning"
                )
            except Exception as e2:
                flash(
                    "Uyarı: Form numarası otomatik alınamadı. Lütfen manuel olarak giriniz. "
                    "Örnek format: PF-2026/0001",
                    "warning"
                )
    # ----------------------------------------------------

    if form.validate_on_submit():
        try:
            import traceback
            actor_id = getattr(current_user, 'id', None)
            kiralama_data = {
                'kiralama_form_no': form.kiralama_form_no.data,
                'makine_calisma_adresi': form.makine_calisma_adresi.data,
                'firma_musteri_id': form.firma_musteri_id.data,
                'kdv_orani': form.kdv_orani.data,
                'doviz_kuru_usd': form.doviz_kuru_usd.data,
                'doviz_kuru_eur': getattr(form, 'doviz_kuru_eur', form.doviz_kuru_usd).data
            }
            kalemler_data = [k_form.data for k_form in form.kalemler]
            current_app.logger.debug(f"[EKLE] kiralama_data: {kiralama_data}")
            current_app.logger.debug(f"[EKLE] kalemler_data: {kalemler_data}")

            created_kiralama = KiralamaService.create_kiralama_with_relations(kiralama_data, kalemler_data, actor_id=actor_id)
            current_app.logger.debug(f"[EKLE] created_kiralama: {created_kiralama}")
            OperationLogService.log(
                module='kiralama',
                action='create',
                user_id=actor_id,
                username=getattr(current_user, 'username', None),
                entity_type='Kiralama',
                entity_id=getattr(created_kiralama, 'id', None),
                description=f"Kiralama oluşturuldu: {created_kiralama.kiralama_form_no}",
                success=True,
            )
            # İleri tarihli kalem uyarısı
            from datetime import date as _date
            ileri_tarihli = any(
                k.get('kiralama_baslangici') and str(k.get('kiralama_baslangici')) > _date.today().isoformat()
                for k in kalemler_data
            )
            if ileri_tarihli:
                flash('Kiralama kaydı başarıyla oluşturuldu. ⚠️ Bir veya daha fazla kalemin başlangıç tarihi ileridedir — cari tahakkuk başlangıç tarihine geldiğinde otomatik yansıyacaktır.', 'info')
            else:
                flash('Kiralama kaydı başarıyla oluşturuldu.', 'success')
            return redirect(url_for('kiralama.index'))

        except ValidationError as e:
            db.session.rollback()
            OperationLogService.log(
                module='kiralama',
                action='create',
                user_id=getattr(current_user, 'id', None),
                username=getattr(current_user, 'username', None),
                entity_type='Kiralama',
                description=f"Kiralama oluşturma doğrulama hatası: {str(e)}",
                success=False,
            )
            flash(f"Doğrulama Hatası: {str(e)}", "warning")
        except ValueError as e:
            db.session.rollback()
            OperationLogService.log(
                module='kiralama',
                action='create',
                user_id=getattr(current_user, 'id', None),
                username=getattr(current_user, 'username', None),
                entity_type='Kiralama',
                description=f"Kiralama oluşturma veri hatası: {str(e)}",
                success=False,
            )
            flash(f"Veri Hatası: {str(e)}", "danger")
        except Exception as e:
            db.session.rollback()
            import traceback
            tb_str = traceback.format_exc()
            current_app.logger.error(f"Kiralama Kayıt Hatası: {str(e)}\nTraceback:\n{tb_str}")
            OperationLogService.log(
                module='kiralama',
                action='create',
                user_id=getattr(current_user, 'id', None),
                username=getattr(current_user, 'username', None),
                entity_type='Kiralama',
                description=f"Kiralama oluşturma sistem hatası: {str(e)}\nTraceback:\n{tb_str}",
                success=False,
            )
            flash(f"Sistemsel bir hata oluştu. Lütfen tekrar deneyin.", "danger")
    
    elif request.method == 'POST':
        for field, errors in form.errors.items():
            if field == 'kalemler':
                for idx, kalem_errors in enumerate(errors):
                    for k_field, k_msg in kalem_errors.items():
                        flash(f"Satır {idx+1} - {k_field}: {k_msg}", "warning")
            else:
                flash(f"{field}: {errors}", "warning")

    # Rollback sonrası session bozulmuş olabilir; form render için gereken
    # sorguları korumalı blokta çalıştır
    try:
        ekipman_sube_map = {
            e.id: (e.sube.isim if e.sube else 'Şube Tanımsız')
            for e in Ekipman.query.options(joinedload(Ekipman.sube)).all()
        }
        subeler = Sube.query.all()
        markalar = [m[0] for m in db.session.query(Ekipman.marka).filter(Ekipman.marka.isnot(None)).distinct().all()]
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Ekle formu yardımcı veri hatası: {str(e)}")
        ekipman_sube_map = {}
        subeler = []
        markalar = []
    tipler = [tip for tip, _ in EKIPMAN_TIPI_SECENEKLERI]
    preselect_ekipman_id = request.args.get('ekipman_id', 0, type=int)
    return render_template('kiralama/form.html', form=form, subeler=subeler, markalar=markalar, tipler=tipler, is_edit=False, ekipman_sube_map=ekipman_sube_map, ekipman_map_json='{}', preselect_ekipman_id=preselect_ekipman_id)

@kiralama_bp.route('/duzenle/<int:kiralama_id>', methods=['GET', 'POST'])
@login_required
def duzenle(kiralama_id):
    """Mevcut bir kiralama kaydını düzenleme."""
    guard_response = ensure_active_sube_exists(
        warning_message="Kiralama düzenlemeden önce en az bir aktif şube / depo tanımlamalısınız."
    )
    if guard_response:
        return guard_response

    kiralama = db.get_or_404(Kiralama, kiralama_id)
    if kiralama.is_deleted:
        flash('Silinmiş kiralama kaydı düzenlenemez.', 'warning')
        return redirect(url_for('kiralama.index'))
    form = KiralamaForm(obj=kiralama)
    form.current_kiralama_id = kiralama.id
    date_conflicts = []

    # Düzenleme ekranında form numarası değiştirilemez.
    if request.method == 'POST':
        form.kiralama_form_no.data = kiralama.kiralama_form_no

    if request.method == 'GET':
        form.makine_calisma_adresi.data = kiralama.makine_calisma_adresi
    

    try:
        include_ids = [k.ekipman_id for k in kiralama.kalemler if k.ekipman_id]
        populate_kiralama_form_choices(form, include_ids=include_ids)
        # Güvenlik: Eğer choices None ise boş listeye çevir
        for entry in form.kalemler.entries:
            for field_name in ['ekipman_id', 'harici_ekipman_tedarikci_id', 'nakliye_tedarikci_id', 'nakliye_araci_id', 'donus_nakliye_tedarikci_id', 'donus_nakliye_araci_id']:
                field = getattr(entry.form, field_name, None)
                if field is not None and getattr(field, 'choices', None) is None:
                    field.choices = []
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        current_app.logger.error(f"Seçenek doldurma hatası (Düzenle): {str(e)}\n{tb}")
        flash(f"Form seçenekleri yüklenirken hata oluştu: {str(e)}", "danger")
        return redirect(url_for('kiralama.index'))

    if request.method == 'GET':
        # Kalemler listesini sıfırla ve modelden doldur
        form.kalemler.entries = []
        if kiralama.kalemler is None:
            current_app.logger.error(f"[DUZENLE] kiralama.kalemler None! kiralama_id={kiralama.id}")
        kalemler = kiralama.kalemler if kiralama.kalemler is not None else []
        for idx, kalem in enumerate(kalemler):
            entry = form.kalemler.append_entry()
            k_form = entry.form
            current_app.logger.info(f"[DUZENLE] kalem[{idx}].nakliye_alis_kdv DB'den: {kalem.nakliye_alis_kdv} -> Form: {getattr(k_form, 'nakliye_alis_kdv', None)}")
            # SelectField alanlarının choices'ı None ise boş listeye set et
            for field_name in ['ekipman_id', 'harici_ekipman_tedarikci_id', 'nakliye_tedarikci_id', 'nakliye_araci_id', 'donus_nakliye_tedarikci_id', 'donus_nakliye_araci_id']:
                field = getattr(k_form, field_name, None)
                if field is not None and getattr(field, 'choices', None) is None:
                    field.choices = []
            k_form.id.data = kalem.id
            k_form.dis_tedarik_ekipman.data = 1 if getattr(kalem, 'is_dis_tedarik_ekipman', False) else 0
            k_form.ekipman_id.data = kalem.ekipman_id
            k_form.harici_ekipman_tedarikci_id.data = kalem.harici_ekipman_tedarikci_id
            k_form.harici_ekipman_tipi.data = kalem.harici_ekipman_tipi
            k_form.harici_ekipman_marka.data = kalem.harici_ekipman_marka
            k_form.harici_ekipman_model.data = kalem.harici_ekipman_model
            k_form.harici_ekipman_seri_no.data = kalem.harici_ekipman_seri_no
            k_form.harici_ekipman_kaldirma_kapasitesi.data = kalem.harici_ekipman_kapasite
            k_form.harici_ekipman_calisma_yuksekligi.data = kalem.harici_ekipman_yukseklik
            k_form.harici_ekipman_uretim_tarihi.data = kalem.harici_ekipman_uretim_yili
            k_form.kiralama_baslangici.data = kalem.kiralama_baslangici
            k_form.kiralama_bitis.data = kalem.kiralama_bitis
            k_form.kiralama_brm_fiyat.data = kalem.kiralama_brm_fiyat
            k_form.kiralama_alis_fiyat.data = kalem.kiralama_alis_fiyat
            k_form.kiralama_alis_kdv.data = kalem.kiralama_alis_kdv
            k_form.nakliye_alis_kdv.data = kalem.nakliye_alis_kdv
            k_form.nakliye_satis_kdv.data = kalem.nakliye_satis_kdv
            k_form.nakliye_alis_tevkifat_oran.data = kalem.nakliye_alis_tevkifat_oran
            k_form.nakliye_satis_tevkifat_oran.data = kalem.nakliye_satis_tevkifat_oran
            k_form.dis_tedarik_nakliye.data = 1 if getattr(kalem, 'is_harici_nakliye', False) else 0
            k_form.nakliye_satis_fiyat.data = kalem.nakliye_satis_fiyat
            k_form.donus_nakliye_fatura_et.data = 1 if getattr(kalem, 'donus_nakliye_fatura_et', False) else 0
            k_form.nakliye_alis_fiyat.data = kalem.nakliye_alis_fiyat
            k_form.nakliye_tedarikci_id.data = kalem.nakliye_tedarikci_id
            k_form.nakliye_araci_id.data = kalem.nakliye_araci_id
            if hasattr(k_form, 'donus_is_harici_nakliye'):
                k_form.donus_is_harici_nakliye.data = 1 if getattr(kalem, 'donus_is_harici_nakliye', False) else 0
            if hasattr(k_form, 'donus_nakliye_tedarikci_id'):
                k_form.donus_nakliye_tedarikci_id.data = kalem.donus_nakliye_tedarikci_id
            if hasattr(k_form, 'donus_nakliye_alis_fiyat'):
                k_form.donus_nakliye_alis_fiyat.data = kalem.donus_nakliye_alis_fiyat
            if hasattr(k_form, 'donus_nakliye_alis_kdv'):
                k_form.donus_nakliye_alis_kdv.data = kalem.donus_nakliye_alis_kdv
            if hasattr(k_form, 'donus_nakliye_araci_id'):
                k_form.donus_nakliye_araci_id.data = kalem.donus_nakliye_araci_id
            # Ek alanlar (varsa formda karşılığı olanlar)
            if hasattr(k_form, 'sonlandirildi'):
                k_form.sonlandirildi.data = kalem.sonlandirildi
            if hasattr(k_form, 'is_active'):
                k_form.is_active.data = kalem.is_active
            if hasattr(k_form, 'parent_id'):
                k_form.parent_id.data = kalem.parent_id
            if hasattr(k_form, 'versiyon_no'):
                k_form.versiyon_no.data = kalem.versiyon_no
            if hasattr(k_form, 'degisim_nedeni'):
                k_form.degisim_nedeni.data = kalem.degisim_nedeni
            if hasattr(k_form, 'degisim_tarihi'):
                k_form.degisim_tarihi.data = kalem.degisim_tarihi
            if hasattr(k_form, 'cikis_saati'):
                k_form.cikis_saati.data = kalem.cikis_saati
            if hasattr(k_form, 'donus_saati'):
                k_form.donus_saati.data = kalem.donus_saati
            if hasattr(k_form, 'degisim_aciklama'):
                k_form.degisim_aciklama.data = kalem.degisim_aciklama
            if hasattr(k_form, 'chain_id'):
                k_form.chain_id.data = kalem.chain_id
        # Kalemler doldurulduktan sonra tekrar choices'ları ata
        try:
            populate_kiralama_form_choices(form, include_ids=include_ids)
        except Exception as e:
            current_app.logger.error(f"Seçenek doldurma hatası (Düzenle/GET tekrar): {str(e)}")

    # Tarih field'larını manual parse et (WTForms validation hatasından kaçınmak için)
    if request.method == 'POST':
        from datetime import datetime as dt
        for idx, k_form in enumerate(form.kalemler):
            try:
                bas_val = request.form.get(f'kalemler-{idx}-kiralama_baslangici', '')
                bit_val = request.form.get(f'kalemler-{idx}-kiralama_bitis', '')
                if bas_val:
                    k_form.kiralama_baslangici.data = dt.strptime(bas_val, '%Y-%m-%d').date()
                if bit_val:
                    k_form.kiralama_bitis.data = dt.strptime(bit_val, '%Y-%m-%d').date()
            except ValueError:
                pass

    if form.validate_on_submit():
        try:
            # Tamamlanmış kalemler: UI'da butonlar pasif, service'te sonlandirildi korunuyor.
            # Form POST'u engellemeye gerek yok, tamamlanmış kalemler olduğu gibi geçer.

            actor_id = getattr(current_user, 'id', None)
            kiralama_data = {
                'makine_calisma_adresi': form.makine_calisma_adresi.data,
                'firma_musteri_id': form.firma_musteri_id.data,
                'kdv_orani': form.kdv_orani.data,
                'doviz_kuru_usd': form.doviz_kuru_usd.data,
                'doviz_kuru_eur': getattr(form, 'doviz_kuru_eur', form.doviz_kuru_usd).data
            }
            kalemler_data = [k_form.data for k_form in form.kalemler]
            kapali_duzeltme_sayisi = 0

            for k_data in kalemler_data:
                try:
                    kalem_id = int(k_data.get('id') or 0)
                except (TypeError, ValueError):
                    continue
                if kalem_id <= 0:
                    continue
                mevcut_kalem = db.session.get(KiralamaKalemi, kalem_id)
                if not mevcut_kalem or (not mevcut_kalem.sonlandirildi and mevcut_kalem.is_active):
                    continue

                if _kapali_kalem_degisti_mi(k_data, mevcut_kalem):
                    kapali_duzeltme_sayisi += 1

            if kapali_duzeltme_sayisi:
                financial_password = request.form.get('financial_edit_password') or ''
                if not financial_password or not current_user.check_password(financial_password):
                    raise ValidationError("Kapatılmış kalemde düzenleme için kullanıcı şifresi doğrulanmalıdır.")

            date_conflicts = _kiralama_tarih_cakismalari(kalemler_data)
            if date_conflicts:
                raise ValidationError(date_conflicts[0]['message'])

            KiralamaService.update_kiralama_with_relations(kiralama.id, kiralama_data, kalemler_data, actor_id=actor_id)
            log_description = f"Kiralama güncellendi: {kiralama.kiralama_form_no}"
            if kapali_duzeltme_sayisi:
                log_description += f" | Şifre doğrulamalı kapalı kalem düzenleme: {kapali_duzeltme_sayisi} kapatılmış kalem"
            OperationLogService.log(
                module='kiralama',
                action='update',
                user_id=actor_id,
                username=getattr(current_user, 'username', None),
                entity_type='Kiralama',
                entity_id=kiralama.id,
                description=log_description,
                success=True,
            )
            # İleri tarihli kalem uyarısı
            from datetime import date as _date
            ileri_tarihli = any(
                k.get('kiralama_baslangici') and str(k.get('kiralama_baslangici')) > _date.today().isoformat()
                for k in kalemler_data
            )
            if ileri_tarihli:
                flash('Kiralama başarıyla güncellendi. ⚠️ Bir veya daha fazla kalemin başlangıç tarihi ileridedir — cari tahakkuk başlangıç tarihine geldiğinde otomatik yansıyacaktır.', 'info')
            else:
                flash('Kiralama başarıyla güncellendi.', 'success')
            return _redirect_to_kiralama_return()
        except ValidationError as e:
            db.session.rollback()
            OperationLogService.log(
                module='kiralama',
                action='update',
                user_id=getattr(current_user, 'id', None),
                username=getattr(current_user, 'username', None),
                entity_type='Kiralama',
                entity_id=kiralama_id,
                description=f"Kiralama güncelleme doğrulama hatası: {str(e)}",
                success=False,
            )
            flash(f"Hata: {str(e)}", "warning")
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Kiralama Güncelleme Hatası (ID: {kiralama_id}): {str(e)}")
            OperationLogService.log(
                module='kiralama',
                action='update',
                user_id=getattr(current_user, 'id', None),
                username=getattr(current_user, 'username', None),
                entity_type='Kiralama',
                entity_id=kiralama_id,
                description=f"Kiralama güncelleme sistem hatası: {str(e)}",
                success=False,
            )
            flash(f"Güncelleme sırasında sistemsel bir hata oluştu.", "danger")
    else:
        if request.method == 'POST':
            # Form validasyon hatalarını ve eksik alanları logla
            current_app.logger.warning(f"Kiralama düzenle formu validasyon hatası: {form.errors}")
            for idx, kalem in enumerate(form.kalemler):
                if kalem.errors:
                    current_app.logger.warning(f"Kiralama kalemi {idx} errors: {kalem.errors}")
            # Hataları kullanıcıya göster
            for field, errors in form.errors.items():
                if field == 'kalemler':
                    for idx, kalem_errors in enumerate(errors):
                        for k_field, k_msg in kalem_errors.items():
                            flash(f"Satır {idx+1} - {k_field}: {k_msg}", "warning")
                else:
                    flash(f"{field}: {errors}", "warning")
    # Rollback sonrası session bozulmuş olabilir; form render için gereken
    # sorguları korumalı blokta çalıştır
    try:
        # Rollback sonrası kiralama objesi expire olmuş olabilir, yeniden yükle
        db.session.refresh(kiralama)
        include_ids_for_map = [k.ekipman_id for k in kiralama.kalemler if k.ekipman_id]
        if request.method == 'POST':
            for entry in form.kalemler:
                try:
                    posted_ekipman_id = int(entry.form.ekipman_id.data or 0)
                except (TypeError, ValueError):
                    posted_ekipman_id = 0
                if posted_ekipman_id > 0 and posted_ekipman_id not in include_ids_for_map:
                    include_ids_for_map.append(posted_ekipman_id)
        filo_query_for_map = Ekipman.query.filter(
            Ekipman.firma_tedarikci_id.is_(None),
            or_(Ekipman.calisma_durumu == 'bosta', Ekipman.id.in_(include_ids_for_map))
        ).order_by(Ekipman.kod).all()

        ekipman_map = {
            e.id: f"{(e.kod or '').strip()} | {(e.tipi or '').strip()} ({(e.marka or 'Bilinmiyor').strip()}-{e.calisma_yuksekligi or 0}m - {e.kaldirma_kapasitesi or 0}kg)"
            for e in filo_query_for_map
        }

        ekipman_sube_map = {
            e.id: (e.sube.isim if e.sube else 'Şube Tanımsız')
            for e in Ekipman.query.options(joinedload(Ekipman.sube)).all()
        }
        subeler = Sube.query.all()
        markalar = [m[0] for m in db.session.query(Ekipman.marka).filter(Ekipman.marka.isnot(None)).distinct().all()]
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Düzenle formu yardımcı veri hatası: {str(e)}")
        ekipman_map = {}
        ekipman_sube_map = {}
        subeler = []
        markalar = []
    tipler = [tip for tip, _ in EKIPMAN_TIPI_SECENEKLERI]
    return render_template('kiralama/form.html', form=form, kiralama=kiralama, markalar=markalar, subeler=subeler, tipler=tipler, is_edit=True, ekipman_sube_map=ekipman_sube_map, ekipman_map_json=json.dumps(ekipman_map, ensure_ascii=False), return_url=_kiralama_return_url(), date_conflicts=date_conflicts)

@kiralama_bp.route('/sil/<int:kiralama_id>', methods=['POST'])
@login_required
def sil(kiralama_id):
    """Kiralama ve bağlı finansal kayıtları mantıksal olarak siler (JSON yanıt)."""
    try:
        delete_password = request.form.get('delete_confirm_password') or ''
        if not delete_password or not current_user.check_password(delete_password):
            raise ValidationError(
                'Kiralama silmek için kullanıcı şifrenizi doğrulamanız gerekir.'
            )

        actor_id = getattr(current_user, 'id', None)
        snapshot = KiralamaService.delete_with_relations(kiralama_id, actor_id=actor_id)
        session[KiralamaService.undo_session_key(kiralama_id)] = snapshot
        session.modified = True
        kiralama = db.session.get(Kiralama, kiralama_id)
        form_no = kiralama.kiralama_form_no if kiralama else ''
        OperationLogService.log(
            module='kiralama',
            action='delete',
            user_id=actor_id,
            username=getattr(current_user, 'username', None),
            entity_type='Kiralama',
            entity_id=kiralama_id,
            description=f"Kiralama silindi (soft): ID={kiralama_id}",
            success=True,
        )
        return jsonify({
            'ok': True,
            'id': kiralama_id,
            'form_no': form_no,
            'undo_seconds': KiralamaService.UNDO_WINDOW_SECONDS,
        })
    except ValidationError as e:
        OperationLogService.log(
            module='kiralama',
            action='delete',
            user_id=getattr(current_user, 'id', None),
            username=getattr(current_user, 'username', None),
            entity_type='Kiralama',
            entity_id=kiralama_id,
            description=f"Kiralama silme doğrulama hatası: {str(e)}",
            success=False,
        )
        return jsonify({'ok': False, 'message': str(e)}), 400
    except Exception as e:
        current_app.logger.error(f"Kiralama Silme Hatası (ID: {kiralama_id}): {str(e)}")
        OperationLogService.log(
            module='kiralama',
            action='delete',
            user_id=getattr(current_user, 'id', None),
            username=getattr(current_user, 'username', None),
            entity_type='Kiralama',
            entity_id=kiralama_id,
            description=f"Kiralama silme sistem hatası: {str(e)}",
            success=False,
        )
        return jsonify({'ok': False, 'message': 'Silme işlemi başarısız oldu.'}), 500


@kiralama_bp.route('/geri-al/<int:kiralama_id>', methods=['POST'])
@login_required
def geri_al(kiralama_id):
    """Soft-delete edilmiş kiralamayı kısa süre içinde geri yükler."""
    try:
        actor_id = getattr(current_user, 'id', None)
        undo_key = KiralamaService.undo_session_key(kiralama_id)
        snapshot = session.get(undo_key)
        kiralama = KiralamaService.restore_with_relations(
            kiralama_id,
            actor_id=actor_id,
            snapshot=snapshot,
        )
        session.pop(undo_key, None)
        session.modified = True
        OperationLogService.log(
            module='kiralama',
            action='restore',
            user_id=actor_id,
            username=getattr(current_user, 'username', None),
            entity_type='Kiralama',
            entity_id=kiralama_id,
            description=f"Kiralama geri alındı: ID={kiralama_id}",
            success=True,
        )
        return jsonify({
            'ok': True,
            'id': kiralama_id,
            'form_no': kiralama.kiralama_form_no,
        })
    except ValidationError as e:
        OperationLogService.log(
            module='kiralama',
            action='restore',
            user_id=getattr(current_user, 'id', None),
            username=getattr(current_user, 'username', None),
            entity_type='Kiralama',
            entity_id=kiralama_id,
            description=f"Kiralama geri alma hatası: {str(e)}",
            success=False,
        )
        return jsonify({'ok': False, 'message': str(e)}), 400
    except Exception as e:
        current_app.logger.error(f"Kiralama Geri Alma Hatası (ID: {kiralama_id}): {str(e)}")
        OperationLogService.log(
            module='kiralama',
            action='restore',
            user_id=getattr(current_user, 'id', None),
            username=getattr(current_user, 'username', None),
            entity_type='Kiralama',
            entity_id=kiralama_id,
            description=f"Kiralama geri alma sistem hatası: {str(e)}",
            success=False,
        )
        return jsonify({'ok': False, 'message': 'Geri alma işlemi başarısız oldu.'}), 500

@kiralama_bp.route('/kalem/sonlandir', methods=['POST'])
@login_required
def sonlandir_kalem():
    """Kiralama kalemini kapatır ve makineyi boşa çıkarır."""
    try:
        kalem_id = request.form.get('kalem_id', type=int)
        if not kalem_id:
            flash("İşlem yapılacak kiralama kalemi seçilmedi.", "warning")
            return _redirect_to_kiralama_return()

        actor_id = getattr(current_user, 'id', None)
        bitis_str = request.form.get('bitis_tarihi')
        donus_sube_id = request.form.get('donus_sube_id')
        is_harici_nakliye = request.form.get('is_harici_nakliye') in ('on', '1', 'true', 'True')
        nakliye_tedarikci_id = request.form.get('nakliye_tedarikci_id', type=int)
        nakliye_araci_id = request.form.get('nakliye_araci_id', type=int)
        nakliye_alis_fiyat = request.form.get('nakliye_alis_fiyat')
        donus_nakliye_alis_kdv = request.form.get('donus_nakliye_alis_kdv')
        donus_nakliye_satis_fiyat = request.form.get('donus_nakliye_satis_fiyat')
        
        KiralamaKalemiService.sonlandir(
            kalem_id,
            bitis_str,
            donus_sube_id,
            actor_id=actor_id,
            is_harici_nakliye=is_harici_nakliye,
            nakliye_tedarikci_id=nakliye_tedarikci_id,
            nakliye_araci_id=nakliye_araci_id,
            nakliye_alis_fiyat=nakliye_alis_fiyat,
            donus_nakliye_alis_kdv=donus_nakliye_alis_kdv,
            donus_nakliye_satis_fiyat=donus_nakliye_satis_fiyat,
        )
        OperationLogService.log(
            module='kiralama',
            action='sonlandir_kalem',
            user_id=actor_id,
            username=getattr(current_user, 'username', None),
            entity_type='KiralamaKalemi',
            entity_id=kalem_id,
            description=f"Kiralama kalemi sonlandırıldı: kalem_id={kalem_id}",
            success=True,
        )
        flash("Kiralama başarıyla sonlandırıldı.", "success")
    except ValidationError as e:
        OperationLogService.log(
            module='kiralama',
            action='sonlandir_kalem',
            user_id=getattr(current_user, 'id', None),
            username=getattr(current_user, 'username', None),
            entity_type='KiralamaKalemi',
            entity_id=request.form.get('kalem_id', type=int),
            description=f"Kalem sonlandırma doğrulama hatası: {str(e)}",
            success=False,
        )
        flash(f"Hata: {str(e)}", "warning")
    except Exception as e:
        current_app.logger.error(f"Kalem Sonlandırma Hatası: {str(e)}")
        OperationLogService.log(
            module='kiralama',
            action='sonlandir_kalem',
            user_id=getattr(current_user, 'id', None),
            username=getattr(current_user, 'username', None),
            entity_type='KiralamaKalemi',
            entity_id=request.form.get('kalem_id', type=int),
            description=f"Kalem sonlandırma sistem hatası: {str(e)}",
            success=False,
        )
        flash(f"İşlem sırasında bir hata oluştu.", "danger")
    return _redirect_to_kiralama_return()

@kiralama_bp.route('/kalem/tarih_guncelle', methods=['POST'])
@login_required
def tarih_guncelle_kalem():
    """Aktif kiralama kaleminin planlanan bitiş tarihini günceller."""
    try:
        kalem_id = request.form.get('kalem_id', type=int)
        yeni_bitis_str = request.form.get('yeni_bitis_tarihi')

        if not kalem_id or not yeni_bitis_str:
            flash("Kalem ID veya tarih eksik.", "warning")
            return _redirect_to_kiralama_return()

        # Kalem'i bul
        kalem = db.session.get(KiralamaKalemi, kalem_id)
        if not kalem:
            flash("Kalem bulunamadı.", "danger")
            return _redirect_to_kiralama_return()

        # Aktif ve sonlandırılmamış olmalı
        if kalem.sonlandirildi or not kalem.is_active:
            flash("Sadece aktif ve sonlandırılmamış kalemler güncellenebilir.", "warning")
            return _redirect_to_kiralama_return()

        # Tarih validasyonu
        from app.services.kiralama_services import to_date
        yeni_bitis_date = to_date(yeni_bitis_str)
        if not yeni_bitis_date:
            flash("Geçersiz tarih formatı.", "warning")
            return _redirect_to_kiralama_return()

        # Yeni bitiş tarihi başlangıçtan sonra olmalı
        bas_date = to_date(kalem.kiralama_baslangici)
        if yeni_bitis_date < bas_date:
            flash("Bitiş tarihi başlangıç tarihinden sonra olmalıdır.", "warning")
            return _redirect_to_kiralama_return()

        # Eski tarihi kaydet
        eski_bitis = kalem.kiralama_bitis

        # Yeni tarihi set et
        kalem.kiralama_bitis = yeni_bitis_date

        # DB'ye kaydet
        db.session.add(kalem)
        db.session.commit()

        actor_id = getattr(current_user, 'id', None)

        # Log kaydı oluştur
        OperationLogService.log(
            module='kiralama',
            action='tarih_guncelle',
            user_id=actor_id,
            username=getattr(current_user, 'username', None),
            entity_type='KiralamaKalemi',
            entity_id=kalem_id,
            description=f"Kiralama kalemi bitiş tarihi güncellendi: {eski_bitis} → {yeni_bitis_date}",
            success=True,
        )

        flash(f"Bitiş tarihi başarıyla güncellendi: {yeni_bitis_date.strftime('%d.%m.%Y')}", "success")

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Kalem Tarih Güncelleme Hatası: {str(e)}", exc_info=True)
        OperationLogService.log(
            module='kiralama',
            action='tarih_guncelle',
            user_id=getattr(current_user, 'id', None),
            username=getattr(current_user, 'username', None),
            entity_type='KiralamaKalemi',
            entity_id=request.form.get('kalem_id', type=int),
            description=f"Kalem tarih güncelleme hatası: {str(e)}",
            success=False,
        )
        flash(f"İşlem sırasında bir hata oluştu: {str(e)}", "danger")

    return _redirect_to_kiralama_return()

@kiralama_bp.route('/kalem/iptal_et', methods=['POST'])
@login_required
def iptal_et_kalem():
    """Sonlandırma işlemini geri alır."""
    try:
        kalem_id = request.form.get('kalem_id', type=int)
        if not kalem_id:
            flash("Hatalı kalem seçimi.", "warning")
            return _redirect_to_kiralama_return()

        actor_id = getattr(current_user, 'id', None)
        KiralamaKalemiService.iptal_et_sonlandirma(kalem_id, actor_id=actor_id)
        OperationLogService.log(
            module='kiralama',
            action='iptal_sonlandirma',
            user_id=actor_id,
            username=getattr(current_user, 'username', None),
            entity_type='KiralamaKalemi',
            entity_id=kalem_id,
            description=f"Kalem sonlandırma iptal edildi: kalem_id={kalem_id}",
            success=True,
        )
        flash("İşlem başarıyla geri alındı.", "success")
    except ValidationError as e:
        OperationLogService.log(
            module='kiralama',
            action='iptal_sonlandirma',
            user_id=getattr(current_user, 'id', None),
            username=getattr(current_user, 'username', None),
            entity_type='KiralamaKalemi',
            entity_id=request.form.get('kalem_id', type=int),
            description=f"Kalem sonlandırma iptal doğrulama hatası: {str(e)}",
            success=False,
        )
        flash(f"Hata: {str(e)}", "warning")
    except Exception as e:
        current_app.logger.error(f"Sonlandırma İptal Hatası: {str(e)}")
        OperationLogService.log(
            module='kiralama',
            action='iptal_sonlandirma',
            user_id=getattr(current_user, 'id', None),
            username=getattr(current_user, 'username', None),
            entity_type='KiralamaKalemi',
            entity_id=request.form.get('kalem_id', type=int),
            description=f"Kalem sonlandırma iptal sistem hatası: {str(e)}",
            success=False,
        )
        flash(f"İşlem geri alınamadı.", "danger")
    return _redirect_to_kiralama_return()
@kiralama_bp.route('/api/ekipman-filtrele')
def api_ekipman_filtrele():
    try:
        # Ortak temel: sadece bizim olan (tedarikçi olmayan) aktif makineler
        query = Ekipman.query.filter_by(is_active=True, firma_tedarikci_id=None)
        
        # Filtreleri yakala
        sube_id = request.args.get('sube_id', type=int)
        tip = (request.args.get('tip') or '').strip()
        marka = (request.args.get('marka') or '').strip()
        enerji = (request.args.get('enerji') or '').strip()
        ortam = request.args.get('ortam')
        sadece_bosta = str(request.args.get('sadece_bosta', '1')).lower() in ('1', 'true', 'yes', 'on')
        
        y_min = request.args.get('y_min', type=float)
        y_max = request.args.get('y_max', type=float)
        k_min = request.args.get('k_min', type=float)
        
        agirlik_max = request.args.get('agirlik_max', type=float)
        genislik_max = request.args.get('genislik_max', type=float)
        uzunluk_max = request.args.get('uzunluk_max', type=float)
        ky_max = request.args.get('ky_max', type=float)
        
        # Sorguları uygula
        if sube_id: query = query.filter(Ekipman.sube_id == sube_id)
        if tip:
            query = query.filter(tr_ilike(Ekipman.tipi, tip))
        if marka:
            # Marka verileri eski kayıtlarda farklı büyük/küçük harf veya baş/son boşlukla gelebiliyor.
            marka_normalized = " ".join(marka.split())
            query = query.filter(tr_ilike(func.trim(Ekipman.marka), f"%{marka_normalized}%"))
        if enerji:
            query = query.filter(tr_ilike(Ekipman.yakit, enerji))
        if ortam == 'ic':
            query = query.filter(Ekipman.ic_mekan_uygun == True)
        elif ortam == 'dis':
            query = query.filter(Ekipman.ic_mekan_uygun == False)
        
        if sadece_bosta:
            query = query.filter(Ekipman.calisma_durumu == 'bosta')

        if y_min: query = query.filter(Ekipman.calisma_yuksekligi >= y_min)
        if y_max: query = query.filter(Ekipman.calisma_yuksekligi <= y_max)
        if k_min: query = query.filter(Ekipman.kaldirma_kapasitesi >= k_min)
        if agirlik_max: query = query.filter(Ekipman.agirlik <= agirlik_max)
        if genislik_max: query = query.filter(Ekipman.genislik <= genislik_max)
        if uzunluk_max: query = query.filter(Ekipman.uzunluk <= uzunluk_max)
        if ky_max: query = query.filter(Ekipman.kapali_yukseklik <= ky_max)
        
        ekipmanlar = query.order_by(Ekipman.kod).all()
        
        data = []
        for e in ekipmanlar:
            # Şube varsa adını, yoksa 'Şubesiz' yazar. Değişken adı temizlendi.
            gecici_sube_adi = e.sube.isim if e.sube else 'Merkez / Şubesiz'
            
            data.append({
                'id': e.id,
                'label': f"{e.kod} | {e.tipi} ({e.calisma_yuksekligi}m) - {gecici_sube_adi}"
            })
            
        return jsonify({
            'success': True,
            'count': len(data),
            'data': data
        })
    except Exception as e:
        # Gerçek hatayı ekrana basması için 'error' anahtarı eklendi
        return jsonify({'success': False, 'error': str(e)}), 500


@kiralama_bp.route('/api/financial-edit-password/verify', methods=['POST'])
@login_required
def api_financial_edit_password_verify():
    """Kapalı kiralama kalemi finansal düzenleme şifresini doğrular."""
    password = request.form.get('password') or ''
    if not password:
        return jsonify({
            'success': False,
            'message': 'Şifre girilmelidir.',
        })

    if not current_user.check_password(password):
        return jsonify({
            'success': False,
            'message': 'Şifre hatalı.',
        })

    return jsonify({
        'success': True,
        'message': 'Şifre doğrulandı.',
    })


@kiralama_bp.route('/api/kurlar/guncelle', methods=['POST'])
@login_required
def api_kurlari_guncelle():
    """TCMB kurlarını manuel tetikler ve güncel cache'i JSON olarak döner."""
    try:
        kurlar = KiralamaService.refresh_tcmb_kurlari(force=True)
        return jsonify({
            'success': True,
            'kurlar': {
                'USD': str(kurlar.get('USD', '0.00')),
                'EUR': str(kurlar.get('EUR', '0.00')),
            },
            'son_guncelleme': KiralamaService.get_kur_son_guncelleme_text(),
        })
    except Exception as e:
        current_app.logger.warning("Kur manuel güncelleme hatası: %s", e, exc_info=True)
        kurlar = KiralamaService.get_tcmb_kurlari()
        return jsonify({
            'success': False,
            'error': 'Kur güncellenemedi. Son bilinen değer gösteriliyor.',
            'kurlar': {
                'USD': str(kurlar.get('USD', '0.00')),
                'EUR': str(kurlar.get('EUR', '0.00')),
            },
            'son_guncelleme': KiralamaService.get_kur_son_guncelleme_text(),
        }), 500
