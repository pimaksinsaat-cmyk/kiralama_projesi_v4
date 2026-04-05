from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from sqlalchemy import or_
from sqlalchemy.orm import joinedload, subqueryload
from decimal import Decimal
from datetime import date

from app.servis import servis_bp
from app.filo.models import BakimKaydi, KullanilanParca, Ekipman, StokKarti, StokHareket
from app.firmalar.models import Firma
from app.services.base import ValidationError
from app.services.filo_services import BakimService, EkipmanService
from app.services.operation_log_service import OperationLogService


def get_actor_id():
    return current_user.id if current_user.is_authenticated else None


BAKIM_TIPI_LABELS = {
    'ariza': 'Ariza',
    'periyodik': 'Periyodik Bakim',
    'genel_kontrol': 'Genel Kontrol',
}

SERVIS_TIPI_LABELS = {
    'ic_servis': 'Ic Servis',
    'dis_servis': 'Dis Servis',
    'yerinde_servis': 'Yerinde Servis',
}

DURUM_LABELS = {
    'acik': 'Acik',
    'parca_bekliyor': 'Parca Bekliyor',
    'tamamlandi': 'Tamamlandi',
    'iptal': 'Iptal',
}


def _get_actor_id():
    if getattr(current_user, 'is_authenticated', False):
        return current_user.id
    return None


def _collect_parts_from_form(form):
    stok_karti_ids = form.getlist('parca_stok_karti_id')
    malzeme_adlari = form.getlist('parca_malzeme_adi')
    kullanilan_adetler = form.getlist('parca_kullanilan_adet')
    birim_fiyatlar = form.getlist('parca_birim_fiyat')
    parts = []

    for stok_karti_id, malzeme_adi, kullanilan_adet, birim_fiyat in zip(stok_karti_ids, malzeme_adlari, kullanilan_adetler, birim_fiyatlar):
        stok_karti_id = (stok_karti_id or '').strip()
        malzeme_adi = (malzeme_adi or '').strip()
        kullanilan_adet = (kullanilan_adet or '').strip()
        birim_fiyat = (birim_fiyat or '').strip()
        if not stok_karti_id and not malzeme_adi and not kullanilan_adet and not birim_fiyat:
            continue

        parts.append({
            'stok_karti_id': stok_karti_id,
            'malzeme_adi': malzeme_adi,
            'kullanilan_adet': kullanilan_adet,
            'birim_fiyat': birim_fiyat,
        })

    return parts


def _common_form_context():
    return {
        'bakim_tipi_labels': BAKIM_TIPI_LABELS,
        'servis_tipi_labels': SERVIS_TIPI_LABELS,
        'durum_labels': DURUM_LABELS,
        'stok_kartlari': StokKarti.query.filter_by(is_deleted=False).order_by(StokKarti.parca_adi).all(),
        'servis_firmalari': Firma.query.filter_by(is_tedarikci=True).order_by(Firma.firma_adi).all(),
    }


def _resolve_part_unit_price(parca):
    if parca.birim_fiyat is not None:
        return Decimal(parca.birim_fiyat or 0)

    if not parca.stok_karti_id:
        return Decimal('0')

    hareket = StokHareket.query.filter(
        StokHareket.stok_karti_id == parca.stok_karti_id,
        StokHareket.hareket_tipi == 'giris',
    ).order_by(StokHareket.tarih.desc(), StokHareket.id.desc()).first()
    return Decimal(hareket.birim_fiyat or 0) if hareket else Decimal('0')


def _attach_cost_totals(kayitlar):
    for kayit in kayitlar:
        malzeme_maliyeti = Decimal('0')
        for parca in kayit.kullanilan_parcalar:
            malzeme_maliyeti += Decimal(parca.kullanilan_adet or 0) * _resolve_part_unit_price(parca)

        kayit.malzeme_maliyeti = malzeme_maliyeti
        kayit.toplam_servis_maliyeti = Decimal(kayit.toplam_iscilik_maliyeti or 0) + malzeme_maliyeti


@servis_bp.route('/')
@login_required
def index():
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 25, type=int)
    if per_page not in {10, 25, 50, 100}:
        per_page = 25

    q = request.args.get('q', '', type=str).strip()
    durum = request.args.get('durum', '', type=str).strip()

    query = BakimKaydi.query.filter(BakimKaydi.is_deleted == False).options(
        joinedload(BakimKaydi.ekipman).joinedload(Ekipman.sube),
        joinedload(BakimKaydi.servis_veren_firma),
        joinedload(BakimKaydi.kullanilan_parcalar).joinedload(KullanilanParca.stok_karti),
    )

    if q:
        term = f'%{q}%'
        query = query.join(BakimKaydi.ekipman).outerjoin(BakimKaydi.servis_veren_firma).filter(
            or_(
                Ekipman.kod.ilike(term),
                Ekipman.marka.ilike(term),
                Ekipman.model.ilike(term),
                BakimKaydi.aciklama.ilike(term),
                BakimKaydi.servis_veren_kisi.ilike(term),
                Firma.firma_adi.ilike(term),
            )
        ).distinct()

    if durum:
        query = query.filter(BakimKaydi.durum == durum)

    pagination = query.order_by(BakimKaydi.tarih.desc(), BakimKaydi.id.desc()).paginate(
        page=page,
        per_page=per_page,
        error_out=False,
    )
    _attach_cost_totals(pagination.items)

    acik_servis_sayisi = BakimKaydi.query.filter(
        BakimKaydi.is_deleted == False,
        BakimKaydi.durum.in_(['acik', 'parca_bekliyor']),
    ).count()
    planli_bakim_sayisi = BakimKaydi.query.filter(
        BakimKaydi.is_deleted == False,
        BakimKaydi.bakim_tipi == 'periyodik',
    ).count()

    return render_template(
        'servis/index.html',
        kayitlar=pagination.items,
        pagination=pagination,
        per_page=per_page,
        q=q,
        durum=durum,
        acik_servis_sayisi=acik_servis_sayisi,
        planli_bakim_sayisi=planli_bakim_sayisi,
        bakim_tipi_labels=BAKIM_TIPI_LABELS,
        servis_tipi_labels=SERVIS_TIPI_LABELS,
        durum_labels=DURUM_LABELS,
    )


@servis_bp.route('/duzenle/<int:id>', methods=['GET', 'POST'])
@login_required
def duzenle(id):
    kayit = BakimKaydi.query.filter(BakimKaydi.id == id, BakimKaydi.is_deleted == False).options(
        joinedload(BakimKaydi.ekipman).joinedload(Ekipman.sube),
        joinedload(BakimKaydi.kullanilan_parcalar).joinedload(KullanilanParca.stok_karti),
        joinedload(BakimKaydi.servis_veren_firma),
    ).first_or_404()

    if request.method == 'POST':
        bakim_verileri = {
            'tarih': request.form.get('tarih'),
            'calisma_saati': request.form.get('calisma_saati', type=int),
            'bakim_tipi': request.form.get('bakim_tipi') or 'ariza',
            'servis_tipi': request.form.get('servis_tipi') or 'ic_servis',
            'durum': request.form.get('durum') or 'acik',
            'servis_veren_firma_id': request.form.get('servis_veren_firma_id', type=int) or None,
            'servis_veren_kisi': (request.form.get('servis_veren_kisi') or '').strip() or None,
            'aciklama': (request.form.get('aciklama') or '').strip() or None,
            'sonraki_bakim_tarihi': request.form.get('sonraki_bakim_tarihi') or None,
            'toplam_iscilik_maliyeti': request.form.get('toplam_iscilik_maliyeti') or 0,
        }
        parts_data = _collect_parts_from_form(request.form)

        try:
            BakimService.bakim_guncelle(id, bakim_verileri, parts_data=parts_data, actor_id=_get_actor_id())
            flash('Servis kaydı güncellendi.', 'success')
            return redirect(url_for('servis.index', q=kayit.ekipman.kod if kayit.ekipman else ''))
        except ValidationError as exc:
            flash(str(exc), 'warning')
        except Exception as exc:
            flash(f'Hata: {exc}', 'danger')

    return render_template('servis/duzenle.html', kayit=kayit, **_common_form_context())


@servis_bp.route('/sil/<int:id>', methods=['POST'])
@login_required
def sil(id):
    try:
        BakimService.bakim_sil(id, actor_id=_get_actor_id())
        flash('Servis kaydı silindi.', 'success')
    except ValidationError as exc:
        flash(str(exc), 'warning')
    except Exception as exc:
        flash(f'Hata: {exc}', 'danger')

    return redirect(url_for('servis.index'))


# -------------------------------------------------------------------------
# Bakımda olan makineler sayfası
# -------------------------------------------------------------------------
@servis_bp.route('/bakimda')
@login_required
def bakimda():
    """Serviste olan (bakımda) makinelerin listesi ve aktif makineler"""
    try:
        page = request.args.get('page', 1, type=int)
        q = request.args.get('q', '', type=str)

        # Serviste olan makineler (bakımda)
        serviste_query = Ekipman.query.filter(
            Ekipman.firma_tedarikci_id.is_(None),
            Ekipman.is_active == True,
            Ekipman.calisma_durumu == 'serviste'
        ).options(subqueryload(Ekipman.bakim_kayitlari))

        if q:
            serviste_query = serviste_query.filter(Ekipman.kod.ilike(f'%{q}%'))

        pagination = serviste_query.order_by(Ekipman.kod).paginate(page=page, per_page=25, error_out=False)
        for ekipman in pagination.items:
            acik_bakimlar = [
                kayit for kayit in ekipman.bakim_kayitlari
                if not kayit.is_deleted and kayit.durum in {'acik', 'parca_bekliyor'}
            ]
            ekipman.aktif_bakim_kaydi = max(acik_bakimlar, key=lambda kayit: (kayit.tarih or date.min, kayit.id)) if acik_bakimlar else None

        # Aktif makineler (sahadaki, kullanımda olan) - sayfalanmaz
        aktif_query = Ekipman.query.filter(
            Ekipman.firma_tedarikci_id.is_(None),
            Ekipman.is_active == True,
            Ekipman.calisma_durumu != 'serviste'
        ).order_by(Ekipman.kod)

        if q:
            aktif_query = aktif_query.filter(Ekipman.kod.ilike(f'%{q}%'))

        aktif_makineler = aktif_query.all()

        return render_template('servis/bakimda.html',
                             ekipmanlar=pagination.items,
                             pagination=pagination,
                             aktif_makineler=aktif_makineler,
                             q=q)
    except Exception as e:
        flash(f"Hata: {str(e)}", "danger")
        return render_template('servis/bakimda.html',
                             ekipmanlar=[],
                             pagination=None,
                             aktif_makineler=[],
                             q='')


@servis_bp.route('/hizli_servis_ac', methods=['POST'])
@login_required
def hizli_servis_ac():
    """Aktif makineler için hızlı servis kaydı aç (servis türüne göre makine durumunu ayarla)"""
    try:
        ekipman_id = request.form.get('ekipman_id', type=int)
        servis_tipi = request.form.get('servis_tipi', 'ic_servis')

        if not ekipman_id:
            flash('Makine seçiniz.', 'warning')
            return redirect(url_for('servis.bakimda'))

        ekipman = EkipmanService.get_by_id(ekipman_id)
        if not ekipman:
            flash('Makine bulunamadı.', 'danger')
            return redirect(url_for('servis.bakimda'))

        # Serviste olan (kirada olan) makineler için servis kaydı açılamaz
        if ekipman.calisma_durumu == 'serviste':
            flash(f"'{ekipman.kod}' zaten serviste (kirada). Servis kaydı açılamazsınız.", 'warning')
            return redirect(url_for('servis.bakimda'))

        # Servis kaydı oluştur
        bakim_verileri = {
            'tarih': date.today(),
            'bakim_tipi': 'ariza',
            'servis_tipi': servis_tipi,
            'servis_veren_firma_id': None,
            'servis_veren_kisi': None,
            'aciklama': 'Hızlı servis kaydı açıldı.',
            'calisma_saati': None,
            'sonraki_bakim_tarihi': None,
            'toplam_iscilik_maliyeti': Decimal('0'),
            'durum': 'acik',
        }

        bakim_id = BakimService.bakim_kaydet(ekipman_id, bakim_verileri, actor_id=get_actor_id())

        # Servis türüne göre makine durumunu ayarla
        # Yerinde servis = makine durumu değişmez (aktif kalır)
        # İç/Dış servis = makine serviste geçer
        if servis_tipi != 'yerinde_servis':
            ekipman.calisma_durumu = 'serviste'
            from app.extensions import db
            db.session.commit()

        OperationLogService.log(
            module='servis', action='hizli_servis_ac',
            user_id=get_actor_id(),
            username=getattr(current_user, 'username', None),
            entity_type='Ekipman', entity_id=ekipman_id,
            description=f"{ekipman.kod} için servis kaydı açıldı ({servis_tipi}).",
            success=True
        )

        flash(f"'{ekipman.kod}' için servis kaydı açıldı.", "success")
        return redirect(url_for('servis.duzenle', id=bakim_id.id))
    except ValidationError as e:
        flash(str(e), "warning")
        return redirect(url_for('servis.bakimda'))
    except Exception as e:
        flash(f"Hata: {str(e)}", "danger")
        return redirect(url_for('servis.bakimda'))


@servis_bp.route('/bakim_bitir/<int:id>', methods=['POST'])
@login_required
def bakim_bitir(id):
    """Makinenin bakımını tamamla ve servisten çıkar"""
    try:
        ekipman = EkipmanService.get_by_id(id)
        if ekipman and ekipman.calisma_durumu == 'serviste':
            BakimService.ekipman_bakimini_tamamla(id, actor_id=get_actor_id())
            OperationLogService.log(
                module='servis', action='bakim_bitir',
                user_id=get_actor_id(),
                username=getattr(current_user, 'username', None),
                entity_type='Ekipman', entity_id=id,
                description=f"{ekipman.kod} servisten çıkarıldı.",
                success=True
            )
            flash(f"'{ekipman.kod}' servisten çıkarıldı.", "success")
    except ValidationError as e:
        flash(str(e), "danger")
    except Exception as e:
        flash(f"Hata: {str(e)}", "danger")

    return redirect(url_for('servis.bakimda'))