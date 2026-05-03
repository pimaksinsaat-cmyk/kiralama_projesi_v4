from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import or_
from sqlalchemy.orm import joinedload

from app.extensions import db
from app.filo.models import Ekipman
from app.firmalar.models import Firma
from app.services.base import ValidationError
from app.services.teklif_services import TeklifService
from app.teklifler import teklifler_bp
from app.teklifler.forms import AdayFirmaAktarForm, TeklifForm
from app.teklifler.models import Teklif, TeklifKalemi
from app.utils import tr_ilike


def _actor_id():
    return current_user.id if current_user and current_user.is_authenticated else None


def _populate_choices(form):
    firmalar = (
        Firma.query
        .filter(Firma.is_musteri == True, Firma.is_active == True, Firma.is_deleted == False)
        .order_by(Firma.firma_adi)
        .all()
    )
    form.firma_musteri_id.choices = [(0, '--- Firma seçiniz ---')] + [(f.id, f.firma_adi) for f in firmalar]

    ekipmanlar = (
        Ekipman.query
        .filter(Ekipman.is_deleted == False, Ekipman.is_active == True)
        .order_by(Ekipman.kod)
        .all()
    )
    ekipman_choices = [(0, '--- Kayıtlı makine seçme ---')] + [
        (e.id, f"{e.kod} | {e.tipi} {e.marka} {e.model or ''}".strip())
        for e in ekipmanlar
    ]
    for entry in form.kalemler:
        entry.form.ekipman_id.choices = ekipman_choices


def _filo_spec_options():
    ekipmanlar = (
        Ekipman.query
        .filter(Ekipman.is_deleted == False, Ekipman.is_active == True)
        .order_by(Ekipman.tipi, Ekipman.marka, Ekipman.model)
        .all()
    )
    specs = []
    seen = set()
    for ekipman in ekipmanlar:
        tip = (ekipman.tipi or '').strip()
        marka = (ekipman.marka or '').strip()
        model = (ekipman.model or '').strip()
        if not any([tip, marka, model]):
            continue
        key = (tip.casefold(), marka.casefold(), model.casefold(), ekipman.calisma_yuksekligi, ekipman.kaldirma_kapasitesi)
        if key in seen:
            continue
        seen.add(key)
        specs.append({
            'tip': tip,
            'marka': marka,
            'model': model,
            'marka_model': ' '.join(part for part in [marka, model] if part).strip(),
            'calisma_yuksekligi': float(ekipman.calisma_yuksekligi or 0),
            'kaldirma_kapasitesi': ekipman.kaldirma_kapasitesi or 0,
        })
    return specs


def _form_teklif_data(form):
    musteri_tipi = form.musteri_tipi.data
    return {
        'teklif_no': (form.teklif_no.data or '').strip() or None,
        'teklif_tarihi': form.teklif_tarihi.data,
        'gecerlilik_tarihi': form.gecerlilik_tarihi.data,
        'durum': form.durum.data,
        'kdv_orani': form.kdv_orani.data or 20,
        'notlar': (form.notlar.data or '').strip() or None,
        'firma_musteri_id': form.firma_musteri_id.data if musteri_tipi == 'kayitli' else None,
        'aday_firma_adi': (form.aday_firma_adi.data or '').strip() if musteri_tipi == 'aday' else None,
        'aday_yetkili_adi': (form.aday_yetkili_adi.data or '').strip() or None,
        'aday_telefon': (form.aday_telefon.data or '').strip() or None,
        'aday_eposta': (form.aday_eposta.data or '').strip() or None,
        'aday_adres': (form.aday_adres.data or '').strip() or None,
        'aday_not': (form.aday_not.data or '').strip() or None,
    }


@teklifler_bp.route('/')
@teklifler_bp.route('/index')
@login_required
def index():
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 25, type=int)
    if per_page not in {10, 25, 50, 100}:
        per_page = 25
    q = (request.args.get('q', '') or '').strip()

    query = Teklif.query.options(joinedload(Teklif.firma_musteri), joinedload(Teklif.kalemler)).filter(
        Teklif.is_deleted == False
    )
    if q:
        search = f'%{q}%'
        query = query.filter(or_(
            Teklif.teklif_no.ilike(search),
            tr_ilike(Teklif.aday_firma_adi, search),
            Teklif.firma_musteri.has(tr_ilike(Firma.firma_adi, search)),
            Teklif.kalemler.any(tr_ilike(TeklifKalemi.makine_tipi, search)),
            Teklif.kalemler.any(tr_ilike(TeklifKalemi.marka_model, search)),
        ))

    pagination = query.order_by(Teklif.created_at.desc()).paginate(page=page, per_page=per_page)
    return render_template('teklifler/index.html', teklifler=pagination.items, pagination=pagination, q=q, per_page=per_page)


@teklifler_bp.route('/ekle', methods=['GET', 'POST'])
@login_required
def ekle():
    form = TeklifForm()
    if request.method == 'GET':
        form.teklif_no.data = TeklifService.get_next_teklif_no()
    _populate_choices(form)

    if form.validate_on_submit():
        try:
            teklif = TeklifService.create_with_items(_form_teklif_data(form), [entry.form.data for entry in form.kalemler], actor_id=_actor_id())
            flash(f'{teklif.teklif_no} numaralı teklif kaydedildi.', 'success')
            return redirect(url_for('teklifler.detay', teklif_id=teklif.id))
        except ValidationError as exc:
            flash(str(exc), 'danger')
        except Exception as exc:
            db.session.rollback()
            flash(f'Teklif kaydedilemedi: {exc}', 'danger')

    return render_template('teklifler/form.html', form=form, teklif=None, is_edit=False, filo_specs=_filo_spec_options())


@teklifler_bp.route('/duzelt/<int:teklif_id>', methods=['GET', 'POST'])
@login_required
def duzelt(teklif_id):
    teklif = TeklifService.get_by_id(teklif_id)
    if not teklif:
        flash('Teklif bulunamadı.', 'danger')
        return redirect(url_for('teklifler.index'))

    form = TeklifForm(obj=teklif)
    form.current_teklif_id = teklif.id
    if request.method == 'GET':
        form.musteri_tipi.data = 'kayitli' if teklif.firma_musteri_id else 'aday'
        form.firma_musteri_id.data = teklif.firma_musteri_id or 0
        form.kalemler.entries = []
        for kalem in teklif.kalemler:
            form.kalemler.append_entry(kalem)
    _populate_choices(form)

    if form.validate_on_submit():
        try:
            teklif = TeklifService.update_with_items(teklif.id, _form_teklif_data(form), [entry.form.data for entry in form.kalemler], actor_id=_actor_id())
            flash(f'{teklif.teklif_no} numaralı teklif güncellendi.', 'success')
            return redirect(url_for('teklifler.detay', teklif_id=teklif.id))
        except ValidationError as exc:
            flash(str(exc), 'danger')
        except Exception as exc:
            db.session.rollback()
            flash(f'Teklif güncellenemedi: {exc}', 'danger')

    return render_template('teklifler/form.html', form=form, teklif=teklif, is_edit=True, filo_specs=_filo_spec_options())


@teklifler_bp.route('/detay/<int:teklif_id>')
@login_required
def detay(teklif_id):
    teklif = Teklif.query.options(joinedload(Teklif.firma_musteri), joinedload(Teklif.kalemler)).filter(
        Teklif.id == teklif_id,
        Teklif.is_deleted == False,
    ).first_or_404()
    return render_template('teklifler/detay.html', teklif=teklif)


@teklifler_bp.route('/sil/<int:teklif_id>', methods=['POST'])
@login_required
def sil(teklif_id):
    try:
        TeklifService.delete(teklif_id, actor_id=_actor_id())
        flash('Teklif silindi.', 'success')
    except Exception as exc:
        flash(f'Teklif silinemedi: {exc}', 'danger')
    return redirect(url_for('teklifler.index'))


@teklifler_bp.route('/durum/<int:teklif_id>', methods=['POST'])
@login_required
def durum_guncelle(teklif_id):
    durum = request.form.get('durum')
    try:
        TeklifService.durum_guncelle(teklif_id, durum, actor_id=_actor_id())
        flash('Teklif durumu güncellendi.', 'success')
    except Exception as exc:
        flash(f'Durum güncellenemedi: {exc}', 'danger')
    return redirect(url_for('teklifler.detay', teklif_id=teklif_id))


@teklifler_bp.route('/firmaya-aktar/<int:teklif_id>', methods=['GET', 'POST'])
@login_required
def firmaya_aktar(teklif_id):
    teklif = TeklifService.get_by_id(teklif_id)
    if not teklif:
        flash('Teklif bulunamadı.', 'danger')
        return redirect(url_for('teklifler.index'))
    if teklif.firma_musteri_id:
        flash('Bu teklif zaten kayıtlı bir firmaya bağlı.', 'warning')
        return redirect(url_for('teklifler.detay', teklif_id=teklif.id))

    form = AdayFirmaAktarForm()
    if request.method == 'GET':
        form.firma_adi.data = teklif.aday_firma_adi
        form.yetkili_adi.data = teklif.aday_yetkili_adi
        form.telefon.data = teklif.aday_telefon
        form.eposta.data = teklif.aday_eposta
        form.iletisim_bilgileri.data = teklif.aday_adres

    if form.validate_on_submit():
        try:
            firma = TeklifService.aday_musteriyi_firmaya_aktar(teklif.id, form.data, actor_id=_actor_id())
            flash(f'{firma.firma_adi} firma listesine aktarıldı.', 'success')
            return redirect(url_for('teklifler.detay', teklif_id=teklif.id))
        except Exception as exc:
            db.session.rollback()
            flash(f'Firma aktarımı yapılamadı: {exc}', 'danger')

    return render_template('teklifler/firmaya_aktar.html', form=form, teklif=teklif)
