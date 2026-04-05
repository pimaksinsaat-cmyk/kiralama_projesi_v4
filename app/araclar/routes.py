from datetime import date, datetime

from flask import render_template, redirect, url_for, flash, request
from flask_login import current_user
from app.extensions import db
from . import araclar_bp
from .models import Arac, AracBakim
from .forms import AracForm, AracBakimForm, AracYakitGiderForm
from app.subeler.models import Sube
from app.subeler.models import SubeGideri
from app.services.sube_gider_services import SubeGiderService
from app.utils import normalize_turkish_upper
from decimal import Decimal

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
            is_nakliye_araci=form.is_nakliye_araci.data,
            is_hizmet_araci=form.is_hizmet_araci.data,
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
        arac.is_nakliye_araci = form.is_nakliye_araci.data
        arac.is_hizmet_araci = form.is_hizmet_araci.data
        arac.muayene_tarihi = form.muayene_tarihi.data
        arac.sigorta_tarihi = form.sigorta_tarihi.data
        arac.is_active = form.is_active.data
        db.session.commit()
        flash(f'{arac.plaka} plakalı araç güncellendi.', 'success')
        return redirect(url_for('araclar.index'))

    return render_template('araclar/ekle.html', form=form, arac=arac)


# -------------------------------------------------------------------------
# Araç Bakım Kaydı Yönetimi
# -------------------------------------------------------------------------
@araclar_bp.route('/<int:arac_id>/bakim_gecmisi', methods=['GET'])
def bakim_gecmisi(arac_id):
    """Aracın bakım geçmişini göster"""
    arac = db.session.get(Arac, arac_id)
    if not arac:
        flash('Araç bulunamadı.', 'danger')
        return redirect(url_for('araclar.index'))

    form = AracBakimForm()
    bakim_kayitlari = AracBakim.query.filter_by(
        arac_id=arac_id,
        is_deleted=False
    ).order_by(AracBakim.tarih.desc()).all()

    return render_template(
        'araclar/bakim_gecmisi.html',
        arac=arac,
        form=form,
        bakim_kayitlari=bakim_kayitlari
    )


@araclar_bp.route('/<int:arac_id>/bakim_ekle', methods=['POST'])
def bakim_ekle(arac_id):
    """Yeni bakım kaydı ekle"""
    arac = db.session.get(Arac, arac_id)
    if not arac:
        flash('Araç bulunamadı.', 'danger')
        return redirect(url_for('araclar.index'))

    form = AracBakimForm()

    if form.validate_on_submit():
        try:
            tarih = datetime.strptime(form.tarih.data, '%Y-%m-%d').date()
            sonraki_bakim_tarihi = None
            sonraki_bakim_turu = form.sonraki_bakim_turu.data or 'km'

            if sonraki_bakim_turu == 'tarih' and form.sonraki_bakim_tarihi.data:
                sonraki_bakim_tarihi = datetime.strptime(form.sonraki_bakim_tarihi.data, '%Y-%m-%d').date()

            yeni_bakim = AracBakim(
                arac_id=arac_id,
                tarih=tarih,
                bakim_tipi=form.bakim_tipi.data,
                yapilan_islem=form.yapilan_islem.data.strip() if form.yapilan_islem.data else None,
                maliyet=form.maliyet.data or 0.0,
                kilometre=form.kilometre.data,
                yapan_yer=form.yapan_yer.data.strip() if form.yapan_yer.data else None,
                notlar=form.notlar.data.strip() if form.notlar.data else None,
                sonraki_bakim_turu=sonraki_bakim_turu,
                sonraki_bakim_km=form.sonraki_bakim_km.data if sonraki_bakim_turu == 'km' else None,
                sonraki_bakim_tarihi=sonraki_bakim_tarihi
            )
            db.session.add(yeni_bakim)
            db.session.commit()

            flash(f'{arac.plaka} için bakım kaydı başarıyla eklendi.', 'success')
            return redirect(url_for('araclar.bakim_gecmisi', arac_id=arac_id))
        except Exception as e:
            db.session.rollback()
            flash(f'Bakım kaydı eklenirken hata oluştu: {str(e)}', 'danger')
            return redirect(url_for('araclar.bakim_gecmisi', arac_id=arac_id))
    else:
        for field, errors in form.errors.items():
            for error in errors:
                flash(f'{field}: {error}', 'warning')
        return redirect(url_for('araclar.bakim_gecmisi', arac_id=arac_id))


@araclar_bp.route('/bakim/<int:bakim_id>/duzenle', methods=['GET', 'POST'])
def bakim_duzenle(bakim_id):
    """Bakım kaydını düzenle"""
    bakim = db.session.get(AracBakim, bakim_id)
    if not bakim:
        flash('Bakım kaydı bulunamadı.', 'danger')
        return redirect(url_for('araclar.index'))

    form = AracBakimForm()

    if form.validate_on_submit():
        try:
            bakim.tarih = datetime.strptime(form.tarih.data, '%Y-%m-%d').date()
            bakim.bakim_tipi = form.bakim_tipi.data
            bakim.yapilan_islem = form.yapilan_islem.data.strip() if form.yapilan_islem.data else None
            bakim.maliyet = form.maliyet.data or 0.0
            bakim.kilometre = form.kilometre.data
            bakim.yapan_yer = form.yapan_yer.data.strip() if form.yapan_yer.data else None
            bakim.notlar = form.notlar.data.strip() if form.notlar.data else None
            bakim.sonraki_bakim_turu = form.sonraki_bakim_turu.data or 'km'

            if bakim.sonraki_bakim_turu == 'tarih' and form.sonraki_bakim_tarihi.data:
                bakim.sonraki_bakim_tarihi = datetime.strptime(form.sonraki_bakim_tarihi.data, '%Y-%m-%d').date()
                bakim.sonraki_bakim_km = None
            else:
                bakim.sonraki_bakim_tarihi = None
                bakim.sonraki_bakim_km = form.sonraki_bakim_km.data if bakim.sonraki_bakim_turu == 'km' else None

            db.session.commit()

            flash('Bakım kaydı başarıyla güncellendi.', 'success')
            return redirect(url_for('araclar.bakim_gecmisi', arac_id=bakim.arac_id))
        except Exception as e:
            db.session.rollback()
            flash(f'Güncelleme sırasında hata oluştu: {str(e)}', 'danger')

    elif request.method == 'GET':
        form.tarih.data = bakim.tarih.strftime('%Y-%m-%d') if bakim.tarih else ''
        form.bakim_tipi.data = bakim.bakim_tipi
        form.yapilan_islem.data = bakim.yapilan_islem or ''
        form.maliyet.data = bakim.maliyet
        form.kilometre.data = bakim.kilometre
        form.yapan_yer.data = bakim.yapan_yer or ''
        form.notlar.data = bakim.notlar or ''
        form.sonraki_bakim_turu.data = bakim.sonraki_bakim_turu or 'km'
        form.sonraki_bakim_km.data = bakim.sonraki_bakim_km
        form.sonraki_bakim_tarihi.data = bakim.sonraki_bakim_tarihi.strftime('%Y-%m-%d') if bakim.sonraki_bakim_tarihi else ''

    return render_template('araclar/bakim_duzenle.html', bakim=bakim, form=form)


@araclar_bp.route('/bakim/<int:bakim_id>/sil', methods=['POST'])
def bakim_sil(bakim_id):
    """Bakım kaydını sil"""
    bakim = db.session.get(AracBakim, bakim_id)
    if not bakim:
        flash('Bakım kaydı bulunamadı.', 'danger')
        return redirect(url_for('araclar.index'))

    arac_id = bakim.arac_id

    try:
        bakim.delete(soft=True, user_id=getattr(current_user, 'id', None))
        flash('Bakım kaydı silindi.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Silme sırasında hata oluştu: {str(e)}', 'danger')

    return redirect(url_for('araclar.bakim_gecmisi', arac_id=arac_id))


@araclar_bp.route('/<int:arac_id>/yakit_giderleri', methods=['GET'])
def yakit_giderleri(arac_id):
    arac = db.session.get(Arac, arac_id)
    if not arac:
        flash('Araç bulunamadı.', 'danger')
        return redirect(url_for('araclar.index'))

    form = AracYakitGiderForm()
    if request.method == 'GET' and not form.tarih.data:
        form.tarih.data = date.today()

    giderler = (
        SubeGideri.query.filter_by(arac_id=arac_id, kategori='mazot')
        .order_by(SubeGideri.tarih.desc(), SubeGideri.id.desc())
        .all()
    )

    toplam_tutar = sum(float(gider.tutar or 0) for gider in giderler)
    toplam_litre = sum(float(gider.litre or 0) for gider in giderler)

    return render_template(
        'araclar/yakit_giderleri.html',
        arac=arac,
        form=form,
        giderler=giderler,
        toplam_tutar=toplam_tutar,
        toplam_litre=toplam_litre,
    )


@araclar_bp.route('/<int:arac_id>/yakit_gideri_ekle', methods=['POST'])
def yakit_gideri_ekle(arac_id):
    arac = db.session.get(Arac, arac_id)
    if not arac:
        flash('Araç bulunamadı.', 'danger')
        return redirect(url_for('araclar.index'))

    if not arac.sube_id:
        flash('Mazot gideri eklemek için aracın bağlı olduğu bir şube tanımlı olmalı.', 'warning')
        return redirect(url_for('araclar.duzenle', arac_id=arac.id))

    form = AracYakitGiderForm()
    if form.validate_on_submit():
        try:
            litre = form.litre.data or Decimal('0')
            birim_fiyat = form.birim_fiyat.data or Decimal('0')
            tutar = litre * birim_fiyat
            detay_parcalari = [arac.plaka]
            if form.istasyon.data:
                detay_parcalari.append(form.istasyon.data.strip())
            otomatik_aciklama = ' - '.join(detay_parcalari)
            kullanici_aciklama = (form.aciklama.data or '').strip()

            SubeGiderService.create_gider(
                {
                    'sube_id': arac.sube_id,
                    'arac_id': arac.id,
                    'tarih': form.tarih.data,
                    'kategori': 'mazot',
                    'tutar': tutar,
                    'litre': litre,
                    'birim_fiyat': birim_fiyat,
                    'km': form.km.data,
                    'istasyon': form.istasyon.data,
                    'fatura_no': form.fatura_no.data,
                    'aciklama': f'{otomatik_aciklama} | {kullanici_aciklama}' if kullanici_aciklama else otomatik_aciklama,
                },
                actor_id=getattr(current_user, 'id', None),
            )
            flash('Mazot gideri araca bağlı olarak kaydedildi.', 'success')
        except Exception as exc:
            flash(f'Mazot gideri kaydedilirken hata oluştu: {str(exc)}', 'danger')
    else:
        for field_name, errors in form.errors.items():
            for error in errors:
                flash(f'{field_name}: {error}', 'warning')

    return redirect(url_for('araclar.yakit_giderleri', arac_id=arac.id))


@araclar_bp.route('/yakit_gideri/<int:gider_id>/sil', methods=['POST'])
def yakit_gideri_sil(gider_id):
    gider = SubeGideri.query.filter_by(id=gider_id, kategori='mazot').first()
    if not gider or not gider.arac_id:
        flash('Mazot gideri bulunamadı.', 'danger')
        return redirect(url_for('araclar.index'))

    arac_id = gider.arac_id
    try:
        SubeGiderService.delete_gider(gider_id)
        flash('Mazot gideri silindi.', 'success')
    except Exception as exc:
        flash(f'Silme sırasında hata oluştu: {str(exc)}', 'danger')

    return redirect(url_for('araclar.yakit_giderleri', arac_id=arac_id))