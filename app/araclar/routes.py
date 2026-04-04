from datetime import date

from flask import render_template, redirect, url_for, flash, request
from app.extensions import db
from . import araclar_bp
from .models import Arac
from .forms import AracForm
from app.subeler.models import Sube
from app.utils import normalize_turkish_upper

@araclar_bp.route('/')
def index():
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 25, type=int)
    if per_page not in {10, 20, 25, 50, 100}:
        per_page = 25

    pagination = Arac.query.order_by(Arac.plaka).paginate(page=page, per_page=per_page, error_out=False)
    araclar = pagination.items

    bugun = date.today()
    uyari_gun_esigi = 30
    for arac in araclar:
        muayene_kalan = None
        if arac.muayene_tarihi:
            muayene_kalan = (arac.muayene_tarihi - bugun).days
        arac.muayene_kalan_gun = muayene_kalan

        sigorta_kalan = None
        if arac.sigorta_tarihi:
            sigorta_kalan = (arac.sigorta_tarihi - bugun).days
        arac.sigorta_kalan_gun = sigorta_kalan

        arac.muayene_durum = 'yok'
        if muayene_kalan is not None:
            if muayene_kalan < 0:
                arac.muayene_durum = 'gecmis'
            elif muayene_kalan <= uyari_gun_esigi:
                arac.muayene_durum = 'yaklasiyor'
            else:
                arac.muayene_durum = 'normal'

        arac.sigorta_durum = 'yok'
        if sigorta_kalan is not None:
            if sigorta_kalan < 0:
                arac.sigorta_durum = 'gecmis'
            elif sigorta_kalan <= uyari_gun_esigi:
                arac.sigorta_durum = 'yaklasiyor'
            else:
                arac.sigorta_durum = 'normal'

    return render_template('araclar/index.html', araclar=araclar, pagination=pagination, per_page=per_page)

@araclar_bp.route('/ekle', methods=['GET', 'POST'])
def ekle():
    form = AracForm()
    sube_listesi = Sube.query.filter_by(is_active=True).order_by(Sube.isim).all()
    form.sube_id.choices = [(0, '--- Şube Seçiniz ---')] + [(s.id, s.isim) for s in sube_listesi]
    if form.validate_on_submit():
        plaka_norm = normalize_turkish_upper(form.plaka.data).replace(" ", "")
        mevcut = Arac.query.filter_by(plaka=plaka_norm).first()
        if mevcut:
            flash(f'{plaka_norm} plakalı araç zaten kayıtlı.', 'warning')
            return render_template('araclar/ekle.html', form=form, arac=None)

        yeni_arac = Arac(
            plaka=plaka_norm,
            arac_tipi=form.arac_tipi.data,
            marka_model=form.marka_model.data,
            sube_id=(form.sube_id.data or None),
            muayene_tarihi=form.muayene_tarihi.data,
            sigorta_tarihi=form.sigorta_tarihi.data
        )
        db.session.add(yeni_arac)
        db.session.commit()
        flash(f'{yeni_arac.plaka} plakalı araç sisteme eklendi.', 'success')
        return redirect(url_for('araclar.index'))
        
    return render_template('araclar/ekle.html', form=form, arac=None)

@araclar_bp.route('/duzenle/<int:arac_id>', methods=['GET', 'POST'])
def duzenle(arac_id):
    arac = db.session.get(Arac, arac_id)
    if not arac:
        flash('Araç bulunamadı.', 'danger')
        return redirect(url_for('araclar.index'))

    form = AracForm(obj=arac)
    sube_listesi = Sube.query.filter_by(is_active=True).order_by(Sube.isim).all()
    form.sube_id.choices = [(0, '--- Şube Seçiniz ---')] + [(s.id, s.isim) for s in sube_listesi]
    if form.validate_on_submit():
        plaka_norm = normalize_turkish_upper(form.plaka.data).replace(" ", "")
        mevcut = Arac.query.filter(Arac.plaka == plaka_norm, Arac.id != arac.id).first()
        if mevcut:
            flash(f'{plaka_norm} plakası başka bir araçta kayıtlı.', 'warning')
            return render_template('araclar/ekle.html', form=form, arac=arac)

        arac.plaka = plaka_norm
        arac.arac_tipi = form.arac_tipi.data
        arac.marka_model = form.marka_model.data
        arac.sube_id = form.sube_id.data or None
        arac.muayene_tarihi = form.muayene_tarihi.data
        arac.sigorta_tarihi = form.sigorta_tarihi.data
        arac.is_active = form.is_active.data
        db.session.commit()
        flash(f'{arac.plaka} plakalı araç güncellendi.', 'success')
        return redirect(url_for('araclar.index'))

    return render_template('araclar/ekle.html', form=form, arac=arac)