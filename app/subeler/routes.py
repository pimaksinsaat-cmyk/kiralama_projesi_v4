from flask import render_template, redirect, url_for, flash, request, jsonify
from app.subeler import subeler_bp
from app.extensions import db
from app.subeler.models import Sube
from app.filo.models import Ekipman
from app.subeler.forms import SubeForm # Yazdığımız form sınıfı

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