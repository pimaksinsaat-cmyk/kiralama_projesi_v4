from flask import render_template, redirect, url_for, flash, request, jsonify
from datetime import date, datetime
from sqlalchemy import inspect
from app.subeler import subeler_bp
from app.extensions import db
from app.subeler.models import Sube, SubeGideri
from app.filo.models import Ekipman
from app.subeler.forms import SubeForm, SubeGideriForm, SubeSabitGiderDonemiForm, GIDER_KATEGORILERI
from app.services.base import ValidationError
from app.services.sube_gider_services import SubeGiderService, SubeSabitGiderDonemiService


def _sube_giderleri_table_exists():
    return inspect(db.engine).has_table(SubeGideri.__tablename__)


AY_ADLARI = [
    'Ocak', 'Subat', 'Mart', 'Nisan', 'Mayis', 'Haziran',
    'Temmuz', 'Agustos', 'Eylul', 'Ekim', 'Kasim', 'Aralik'
]


def _resolve_selected_period():
    today = date.today()
    raw_period = request.args.get('period') or request.form.get('period')
    raw_year = request.args.get('year') or request.form.get('year')
    raw_month = request.args.get('month') or request.form.get('month')

    if raw_period and '-' in raw_period:
        raw_year, raw_month = raw_period.split('-', 1)

    try:
        selected_year = int(raw_year) if raw_year else today.year
        selected_month = int(raw_month) if raw_month else today.month
        if selected_month < 1 or selected_month > 12:
            raise ValueError()
    except (TypeError, ValueError):
        selected_year = today.year
        selected_month = today.month

    return selected_year, selected_month


def _build_period_context(selected_year, selected_month):
    previous_year = selected_year if selected_month > 1 else selected_year - 1
    previous_month = selected_month - 1 if selected_month > 1 else 12
    next_year = selected_year if selected_month < 12 else selected_year + 1
    next_month = selected_month + 1 if selected_month < 12 else 1

    return {
        'selected_year': selected_year,
        'selected_month': selected_month,
        'selected_period_key': f'{selected_year:04d}-{selected_month:02d}',
        'selected_period_label': f'{AY_ADLARI[selected_month - 1]} {selected_year}',
        'previous_year': previous_year,
        'previous_month': previous_month,
        'next_year': next_year,
        'next_month': next_month,
    }

# 1. LİSTELEME SAYFASI (Zaten yazmıştık)
@subeler_bp.route('/')
def index():
    aktif_subeler = Sube.query.filter_by(is_active=True).all()
    sube_verileri = []
    for sube in aktif_subeler:
        toplam = Ekipman.query.filter_by(sube_id=sube.id, is_active=True).count()
        bosta = Ekipman.query.filter_by(sube_id=sube.id, calisma_durumu='bosta', is_active=True).count()
        kirada = Ekipman.query.filter(
            Ekipman.sube_id == sube.id,
            Ekipman.calisma_durumu != 'bosta',
            Ekipman.is_active == True
        ).count()
        
        sube_verileri.append({
            'detay': sube,
            'istatistik': {
                'toplam': toplam, 'kirada': kirada, 'bosta': bosta
            }
        })
    return render_template('subeler/index.html', sube_verileri=sube_verileri)

# 2. YENİ ŞUBE EKLEME ROTASI
@subeler_bp.route('/ekle', methods=['GET', 'POST'])
def ekle():
    form = SubeForm()
    if form.validate_on_submit():
        # Formdan gelen verilerle yeni bir Sube nesnesi oluşturuyoruz
        yeni_sube = Sube(
            isim=form.isim.data,
            adres=form.adres.data,
            yetkili_kisi=form.yetkili_kisi.data,
            telefon=form.telefon.data,
            email=form.email.data,
            konum_linki=form.konum_linki.data
        )
        try:
            db.session.add(yeni_sube)
            db.session.commit()
            flash(f'{yeni_sube.isim} şubesi başarıyla oluşturuldu!', 'success')
            return redirect(url_for('subeler.index'))
        except Exception as e:
            db.session.rollback()
            flash(f'Bir hata oluştu: {str(e)}', 'danger')
            
    return render_template('subeler/ekle.html', form=form, title="Yeni Şube Ekle")

# 3. ŞUBE DÜZENLEME ROTASI (Süsleme için lazım olacak)
@subeler_bp.route('/duzenle/<int:id>', methods=['GET', 'POST'])
def duzenle(id):
    sube = Sube.query.get_or_404(id)
    form = SubeForm(obj=sube) # Mevcut bilgileri forma doldurur
    if form.validate_on_submit():
        sube.isim = form.isim.data
        sube.adres = form.adres.data
        sube.yetkili_kisi = form.yetkili_kisi.data
        sube.telefon = form.telefon.data
        sube.email = form.email.data
        sube.konum_linki = form.konum_linki.data
        
        db.session.commit()
        flash('Şube bilgileri güncellendi.', 'info')
        return redirect(url_for('subeler.index'))
    
    return render_template('subeler/ekle.html', form=form, title="Şubeyi Düzenle")

# 4. ŞUBE MAKİNELERİ (DURUM GÖRE KATEGORİZE)
@subeler_bp.route('/<int:sube_id>/makineler')
def sube_makineleri(sube_id):
    try:
        sube = Sube.query.get_or_404(sube_id)
        
        # Makineleri durumuna göre kategorize et
        bosta = Ekipman.query.filter_by(sube_id=sube_id, calisma_durumu='bosta', is_active=True).all()
        kirada = Ekipman.query.filter(
            Ekipman.sube_id == sube_id,
            Ekipman.calisma_durumu != 'bosta',
            Ekipman.is_active == True
        ).all()
        
        # 'plaka' yerine 'kod' kullan ve ekstra alanlar ekle
        bosta_list = [{'id': e.id, 'kod': e.kod, 'marka': e.marka, 'yukseklik': e.calisma_yuksekligi, 'kapasite': e.kaldirma_kapasitesi} for e in bosta]
        kirada_list = [{'id': e.id, 'kod': e.kod, 'marka': e.marka, 'yukseklik': e.calisma_yuksekligi, 'kapasite': e.kaldirma_kapasitesi} for e in kirada]
        
        return jsonify({
            'sube_id': sube.id,
            'sube_adi': sube.isim,
            'bosta': bosta_list,
            'kirada': kirada_list,
            'bosta_sayisi': len(bosta),
            'kirada_sayisi': len(kirada)
        })
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"ERROR in sube_makineleri: {str(e)}")
        print(error_trace)
        return jsonify({'error': f'Veri yükleme hatası: {str(e)}'}), 500


# 5. ŞUBE MASRAF/GİDER ROTASI
@subeler_bp.route('/<int:sube_id>/masraflar', methods=['GET'])
def sube_masraflari(sube_id):
    """Şubenin masraf listesi ve giriş formu."""
    from app.services.personel_services import PersonelService

    sube = Sube.query.get_or_404(sube_id)
    selected_year, selected_month = _resolve_selected_period()
    period_context = _build_period_context(selected_year, selected_month)
    form = SubeGideriForm()
    form.sube_id.data = sube_id
    sabit_gider_form = SubeSabitGiderDonemiForm()
    sabit_gider_form.sube_id.data = sube_id

    if not _sube_giderleri_table_exists():
        flash('Sube giderleri tablosu veritabaninda henuz olusturulmamis. Giderler su an gosterilemiyor.', 'warning')
        masraflar = []
    else:
        masraflar = SubeGiderService.list_giderler_for_month(sube_id, selected_year, selected_month)

    if not SubeSabitGiderDonemiService.table_exists():
        sabit_giderler = []
        aylik_sabit_toplam = 0.0
    else:
        sabit_giderler = SubeSabitGiderDonemiService.list_donemler(sube_id)
        aylik_sabit_toplam = SubeSabitGiderDonemiService.calculate_monthly_total(sube_id, selected_year, selected_month)

    kategori_toplamlar = SubeGiderService.build_category_totals(masraflar)
    manuel_masraf_toplam = sum(kategori_toplamlar.values())
    personel_gider_detaylari = PersonelService.get_monthly_cost_breakdown(selected_year, selected_month, sube_id=sube_id)
    aylik_personel_toplam = sum(row['toplam_tutar'] for row in personel_gider_detaylari)
    genel_toplam = manuel_masraf_toplam + aylik_personel_toplam + aylik_sabit_toplam

    kategori_labels = dict(GIDER_KATEGORILERI)

    return render_template(
        'subeler/masraflar.html',
        sube=sube,
        form=form,
        sabit_gider_form=sabit_gider_form,
        masraflar=masraflar,
        sabit_giderler=sabit_giderler,
        aktif_sabit_toplam=aylik_sabit_toplam,
        genel_toplam=genel_toplam,
        manuel_masraf_toplam=manuel_masraf_toplam,
        aylik_personel_toplam=aylik_personel_toplam,
        personel_gider_detaylari=personel_gider_detaylari,
        kategori_toplamlar=kategori_toplamlar,
        kategori_labels=kategori_labels,
        kategori_secenekleri=GIDER_KATEGORILERI,
        today=datetime.now().strftime('%Y-%m-%d'),
        **period_context,
    )


@subeler_bp.route('/masraflar/ekle', methods=['POST'])
def masraf_ekle():
    """Yeni masraf kaydı ekle (form gönderimi veya AJAX)."""
    form = SubeGideriForm()
    redirect_params = {
        'sube_id': form.sube_id.data,
        'year': request.form.get('year'),
        'month': request.form.get('month'),
    }

    if not _sube_giderleri_table_exists():
        flash('Sube giderleri tablosu veritabaninda henuz olusturulmamis. Once migration uygulanmali.', 'warning')
        return redirect(url_for('subeler.sube_masraflari', **redirect_params))

    if form.validate_on_submit():
        try:
            yeni_gider = SubeGiderService.create_gider(
                {
                    'sube_id': form.sube_id.data,
                    'tarih': form.tarih.data,
                    'kategori': form.kategori.data,
                    'tutar': form.tutar.data,
                    'aciklama': form.aciklama.data,
                    'fatura_no': form.fatura_no.data,
                }
            )

            flash(f'{yeni_gider.tutar} TL masraf başarıyla kaydedildi.', 'success')
            return redirect(url_for('subeler.sube_masraflari', sube_id=yeni_gider.sube_id, year=request.form.get('year'), month=request.form.get('month')))
        except ValidationError as e:
            flash(str(e), 'warning')
            return redirect(url_for('subeler.sube_masraflari', **redirect_params))
        except Exception as e:
            flash(f'Masraf kaydedilirken hata oluştu: {str(e)}', 'danger')
            return redirect(url_for('subeler.sube_masraflari', **redirect_params))
    else:
        # Form doğrulama hatası
        for field, errors in form.errors.items():
            for error in errors:
                flash(f'{field}: {error}', 'warning')
        return redirect(url_for('subeler.sube_masraflari', **redirect_params))


@subeler_bp.route('/masraflar/<int:gider_id>/sil', methods=['POST'])
def masraf_sil(gider_id):
    """Masraf kaydını sil."""
    if not _sube_giderleri_table_exists():
        flash('Sube giderleri tablosu veritabaninda henuz olusturulmamis. Silme islemi yapilamiyor.', 'warning')
        return redirect(url_for('subeler.index'))

    gider = SubeGideri.query.get_or_404(gider_id)
    sube_id = gider.sube_id

    try:
        SubeGiderService.delete_gider(gider_id)
        flash('Masraf kaydı silindi.', 'success')
    except Exception as e:
        flash(f'Masraf silinirken hata oluştu: {str(e)}', 'danger')

    return redirect(url_for('subeler.sube_masraflari', sube_id=sube_id, year=request.form.get('year'), month=request.form.get('month')))


@subeler_bp.route('/sabit-giderler/ekle', methods=['POST'])
def sabit_gider_ekle():
    form = SubeSabitGiderDonemiForm()
    redirect_params = {
        'sube_id': form.sube_id.data,
        'year': request.form.get('year'),
        'month': request.form.get('month'),
    }

    if not SubeSabitGiderDonemiService.table_exists():
        flash('Sabit gider donemleri tablosu veritabaninda henuz olusturulmamis.', 'warning')
        return redirect(url_for('subeler.sube_masraflari', **redirect_params))

    if not form.validate_on_submit():
        for field, errors in form.errors.items():
            for error in errors:
                flash(f'{field}: {error}', 'warning')
        return redirect(url_for('subeler.sube_masraflari', **redirect_params))

    try:
        SubeSabitGiderDonemiService.create_donem(
            {
                'sube_id': form.sube_id.data,
                'kategori': form.kategori.data,
                'baslangic_tarihi': form.baslangic_tarihi.data,
                'aylik_tutar': form.aylik_tutar.data,
                'kdv_orani': form.kdv_orani.data,
                'aciklama': form.aciklama.data,
            }
        )
        flash('Aylik sabit gider kaydi olusturuldu.', 'success')
    except ValidationError as exc:
        flash(str(exc), 'warning')
    except Exception as exc:
        flash(f'Sabit gider kaydedilirken hata olustu: {exc}', 'danger')

    return redirect(url_for('subeler.sube_masraflari', **redirect_params))


@subeler_bp.route('/sabit-giderler/<int:donem_id>/durdur', methods=['POST'])
def sabit_gider_durdur(donem_id):
    donem = SubeSabitGiderDonemiService.get_by_id(donem_id)
    if not donem:
        flash('Sabit gider donemi bulunamadi.', 'warning')
        return redirect(url_for('subeler.index'))

    try:
        SubeSabitGiderDonemiService.stop_donem(donem_id, request.form.get('bitis_tarihi'))
        flash('Sabit gider donemi sonlandirildi.', 'success')
    except ValidationError as exc:
        flash(str(exc), 'warning')
    except Exception as exc:
        flash(f'Sabit gider sonlandirilirken hata olustu: {exc}', 'danger')

    return redirect(url_for('subeler.sube_masraflari', sube_id=donem.sube_id, year=request.form.get('year'), month=request.form.get('month')))


@subeler_bp.route('/<int:sube_id>/personel', methods=['GET'])
def sube_personeli(sube_id):
    """Eski şube personel URL'sini yeni personel modülüne yönlendir."""
    return redirect(url_for('personel.index', sube_id=sube_id))