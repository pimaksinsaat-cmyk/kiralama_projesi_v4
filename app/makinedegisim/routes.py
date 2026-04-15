from flask import render_template, request, redirect, url_for, flash, current_app
from datetime import date
from flask_login import current_user

from app.makinedegisim import makinedegisim_bp
from app.makinedegisim.forms import MakineDegisimForm
from app.services.makine_degisim_services import MakineDegisimService
from app.services.base import ValidationError

# Veritabanı sorguları için db importu (Filtre listeleri için gerekli)
from app.extensions import db 

# Modeller
from app.kiralama.models import KiralamaKalemi
from app.firmalar.models import Firma 
from app.filo.models import Ekipman
from app.subeler.models import Sube
from app.araclar.models import Arac
from app.utils import ensure_active_sube_exists

# --- GÜVENLİK YARDIMCISI ---
def get_actor_id():
    """Kullanıcı giriş sistemi aktifse işlemi yapanın ID'sini alır."""
    if hasattr(current_app, 'login_manager'):
        try:
            if current_user.is_authenticated:
                return current_user.id
        except Exception:
            pass
    return None

@makinedegisim_bp.route('/degistir/<int:kalem_id>', methods=['GET', 'POST'])
def makine_degistir(kalem_id):
    guard_response = ensure_active_sube_exists(
        warning_message="Makine değişimi yapmadan önce en az bir aktif şube / depo tanımlamalısınız."
    )
    if guard_response:
        return guard_response

    eski_kalem = KiralamaKalemi.query.get_or_404(kalem_id)

    if not eski_kalem.is_active:
        flash("Sadece aktif makine üzerinden değişim yapılabilir.", "warning")
        return redirect(url_for('kiralama.index'))

    form = MakineDegisimForm()

    # --- SEÇENEKLERİ DOLDURMA (HTML ile tam uyumlu) ---
    form.neden.choices = [
        ('serviste', 'Serviste (Makine Arızalı/Bakıma Alınacak)'),
        ('bakimda', 'Serviste (Makine Bakıma Alınacak)'),
        ('bosta', 'Müşteri Talebi / İade (Makine Boşa Çıkacak)'),
        ('periyodik', 'Periyodik Değişim (Makine Boşa Çıkacak)')
    ]

    musait_makineler = Ekipman.query.filter(Ekipman.calisma_durumu == 'bosta', Ekipman.is_active == True).all()
    form.yeni_ekipman_id.choices = [(0, '-- Seçiniz --')] + [(m.id, f"{m.kod} - {m.marka} {m.model}") for m in musait_makineler]
    
    # NAKLİYE ARAÇLARI ARTIK KENDİ MODELİNDEN (ARAC) ÇEKİLİYOR
    aktif_araclar = Arac.aktif_nakliye_query().order_by(Arac.plaka).all()
    form.nakliye_araci_id.choices = [(0, '-- Araç Seçiniz --')] + [(a.id, f"{a.plaka} ({a.marka_model})") for a in aktif_araclar]

    tedarikci_listesi = Firma.query.filter_by(is_tedarikci=True, is_active=True).all()
    form.harici_ekipman_tedarikci_id.choices = [(0, '-- Firma Seçiniz --')] + [(f.id, f.firma_adi) for f in tedarikci_listesi]
    form.nakliye_tedarikci_id.choices = [(0, '-- Tedarikçi Seçiniz --')] + [(f.id, f.firma_adi) for f in tedarikci_listesi]

    # --- POST İŞLEMİ ---
    if form.validate_on_submit():
        try:
            # Formdan verileri toparlayıp Servis'e iletiyoruz.
            islem_verileri = {
                'degisim_tarihi': form.degisim_tarihi.data,
                'neden': form.neden.data,
                'donus_saati': form.donus_saati.data,
                'cikis_saati': form.cikis_saati.data,
                'aciklama': form.aciklama.data,
                
                'yeni_ekipman_id': form.yeni_ekipman_id.data if form.yeni_ekipman_id.data != 0 else None,
                'kiralama_brm_fiyat': form.kiralama_brm_fiyat.data,
                
                # Dinamik (HTML'den gelen) veriler
                'donus_sube_val': request.form.get('donus_sube_id'),
                
                # Dış Tedarik Ekipman
                'is_dis_tedarik': form.is_dis_tedarik.data,
                'harici_ekipman_tedarikci_id': form.harici_ekipman_tedarikci_id.data if form.harici_ekipman_tedarikci_id.data != 0 else None,
                'harici_marka': form.harici_marka.data,
                'harici_model': form.harici_model.data,
                'harici_seri_no': form.harici_ekipman_seri_no.data,
                'harici_tipi': form.harici_ekipman_tipi.data,
                'harici_kapasite': form.harici_ekipman_kapasite.data,
                'harici_yukseklik': form.harici_ekipman_yukseklik.data,
                'harici_uretim_yili': form.harici_ekipman_uretim_yili.data,
                'kiralama_alis_fiyat': form.kiralama_alis_fiyat.data,
                
                # Nakliye (Araç ve Harici)
                'yeni_nakliye_ekle': form.yeni_nakliye_ekle.data,
                'is_oz_mal_nakliye': not request.form.get('is_harici_nakliye'),
                'is_harici_nakliye': bool(request.form.get('is_harici_nakliye')),
                'nakliye_satis_fiyat': form.nakliye_satis_fiyat.data,
                'nakliye_alis_fiyat': form.nakliye_alis_fiyat.data,
                'nakliye_tedarikci_id': form.nakliye_tedarikci_id.data if request.form.get('is_harici_nakliye') and form.nakliye_tedarikci_id.data != 0 else None,
                
                # Eğer dışarıdan nakliye değilse ve araç seçilmişse araç ID'sini kaydet
                'nakliye_araci_id': form.nakliye_araci_id.data if not request.form.get('is_harici_nakliye') and form.nakliye_araci_id.data != 0 else None
            }

            # İş Mantığını Çalıştır!
            MakineDegisimService.degisim_uygula(kalem_id, islem_verileri, actor_id=get_actor_id())
            
            flash("Makine değişimi ve şube transferi başarıyla tamamlandı.", "success")
            return redirect(url_for('kiralama.index'))

        except ValidationError as e:
            flash(str(e), "danger")
        except Exception as e:
            flash(f"Sistem Hatası: {str(e)}", "danger")

    elif request.method == 'POST':
        # FORM GEÇERSİZSE (Sessizce resetlenmesini engeller, hatayı ekrana basar)
        for field_name, error_messages in form.errors.items():
            for err in error_messages:
                field_label = getattr(form, field_name).label.text if hasattr(form, field_name) else field_name
                flash(f"Lütfen kontrol edin ({field_label}): {err}", "danger")

    # --- GET İŞLEMİ (Form Ekranı) ---
    if request.method == 'GET':
        form.degisim_tarihi.data = date.today()
        form.kiralama_brm_fiyat.data = eski_kalem.kiralama_brm_fiyat

    eski_makine = db.session.get(Ekipman, eski_kalem.ekipman_id) if eski_kalem.ekipman_id else None
    
    # --- UX İYİLEŞTİRMESİ: Mevcut makinenin özelliklerini ipucu olarak hazırlıyoruz ---
    filtre_ipuclari = {
        'tip': eski_makine.tipi if eski_makine else getattr(eski_kalem, 'harici_ekipman_tipi', ''),
        'yukseklik': eski_makine.calisma_yuksekligi if eski_makine else getattr(eski_kalem, 'harici_ekipman_calisma_yuksekligi', getattr(eski_kalem, 'harici_ekipman_yukseklik', '')),
        'kapasite': eski_makine.kaldirma_kapasitesi if eski_makine else getattr(eski_kalem, 'harici_ekipman_kapasite', ''),
        'uretim_yili': eski_makine.uretim_yili if eski_makine else getattr(eski_kalem, 'harici_ekipman_uretim_yili', ''),
        'marka': eski_makine.marka if eski_makine else getattr(eski_kalem, 'harici_ekipman_marka', ''),
        'agirlik': eski_makine.agirlik if eski_makine else getattr(eski_kalem, 'harici_ekipman_agirlik', ''),
        'yakit': eski_makine.yakit if eski_makine else getattr(eski_kalem, 'harici_ekipman_yakit', ''),
        'ic_mekan_uygun': eski_makine.ic_mekan_uygun if eski_makine else getattr(eski_kalem, 'harici_ekipman_ic_mekan_uygun', False),
        'genislik': eski_makine.genislik if eski_makine else getattr(eski_kalem, 'harici_ekipman_genislik', ''),
        'uzunluk': eski_makine.uzunluk if eski_makine else getattr(eski_kalem, 'harici_ekipman_uzunluk', ''),
        'kapali_yukseklik': eski_makine.kapali_yukseklik if eski_makine else getattr(eski_kalem, 'harici_ekipman_kapali_yukseklik', ''),
        #'sube_id': eski_kalem.kiralama.sube_id if eski_kalem.kiralama and eski_kalem.kiralama.sube_id else None
    }

    # Filtre asistanı için gerekli dropdown listelerini çekiyoruz
    markalar = [m[0] for m in db.session.query(Ekipman.marka).filter(Ekipman.marka.isnot(None), Ekipman.marka != '').distinct().all()]
    tipler = [t[0] for t in db.session.query(Ekipman.tipi).filter(Ekipman.tipi.isnot(None), Ekipman.tipi != '').distinct().all()]
    enerji_kaynaklari = [e[0] for e in db.session.query(Ekipman.yakit).filter(Ekipman.yakit.isnot(None), Ekipman.yakit != '').distinct().all()]
    #yakit_turleri = [y[0] for y in db.session.query(Ekipman.yakit).filter(Ekipman.yakit.isnot(None), Ekipman.yakit != '').distinct().all()]
    return render_template(
        'makinedegisim/degisim_formu.html',
        form=form,
        eski_kalem=eski_kalem,
        eski_makine=eski_makine,
        makineler=musait_makineler,
        subeler=Sube.query.all(),
        markalar=markalar,
        tipler=tipler,
        enerji_kaynaklari=enerji_kaynaklari,
        #yakit_turleri=yakit_turleri,
        filtre_ipuclari=filtre_ipuclari,
        now_date=date.today().strftime('%Y-%m-%d'),
        secili_donus_sube=request.form.get('donus_sube_id') # Form hata verip resetlendiğinde değeri korumak için
    )

@makinedegisim_bp.route('/degisim_iptal/<int:kalem_id>', methods=['POST'])
def degisim_iptal(kalem_id):
    try:
        MakineDegisimService.iptal_et(kalem_id, actor_id=get_actor_id())
        flash("Makine değişimi geri alındı, envanter güncellendi.", "success")
    except ValidationError as e:
        flash(str(e), "danger")
    except Exception as e:
        flash(f"Sistem Hatası: {str(e)}", "danger")

    return redirect(url_for('kiralama.index'))