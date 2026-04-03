import logging
from flask import send_file, flash, redirect, url_for, current_app
from . import dokumanlar_bp
from .engine_teslim_tutanagi import teslim_tutanagi_uret

# Modelleri projenizdeki yapıya göre en güvenli şekilde çekiyoruz
try:
    from app.kiralama.models import Kiralama
except ImportError:
    try:
        from app.models import Kiralama
    except ImportError:
        logging.error("Kiralama modeli döküman rotasında bulunamadı!")

@dokumanlar_bp.route('/yazdir/teslim-tutanagi/<int:rental_id>')
def teslim_tutanagi_hazirla(rental_id):
    """
    Teslim Tutanağı üretim rotası.
    Hata Notu: Eğer 'unknown tag tr' hatası alıyorsanız, Word şablonunda 
    {% tr for ... %} yerine standart {% for ... %} kullanmalısınız.
    """
    try:
        # 1. Veritabanından veriyi çek
        kiralama = Kiralama.query.get_or_404(rental_id)
        musteri = kiralama.firma_musteri
        
        if not musteri:
            flash("Müşteri bilgisi bulunamadı.", "danger")
            return redirect(url_for('kiralama.index'))

        # 2. Kalem verilerini Word tablosu formatında hazırla
        kalemler_verisi = []
        for kalem in kiralama.kalemler:
            kullanim_yeri = kiralama.makine_calisma_adresi or "-"

            # Ekipman ve Seri No Belirleme
            if kalem.is_dis_tedarik_ekipman:
                marka = (kalem.harici_ekipman_marka or "").strip()
                model = (kalem.harici_ekipman_model or "").strip()
                ekipman_adi = " ".join([x for x in [marka, model] if x]) or "Bilinmiyor"
                seri_no = kalem.harici_ekipman_seri_no or "-"
            else:
                if kalem.ekipman:
                    marka = (kalem.ekipman.marka or "").strip()
                    model = (kalem.ekipman.model or "").strip()
                    ekipman_adi = " ".join([x for x in [marka, model] if x])
                    if not ekipman_adi:
                        ekipman_adi = f"{kalem.ekipman.kod} ({kalem.ekipman.tipi})"
                    seri_no = kalem.ekipman.seri_no or "-"
                else:
                    marka = ""
                    model = ""
                    ekipman_adi = "Bilinmiyor"
                    seri_no = "-"

            kalemler_verisi.append({
                'ekipman': ekipman_adi,
                'ekipman_marka': marka or "-",
                'ekipman_model': model or "-",
                'seri_no': seri_no,
                'makine_kullanim_yeri': kullanim_yeri,
                'teslim_tarihi': kalem.kiralama_baslangici.strftime('%d.%m.%Y')
            })

        # 3. Döküman motorunu tetikle
        # Word doldurma ve PDF dönüşümü burada gerçekleşir
        dosya_yolu, hata = teslim_tutanagi_uret(kiralama, kalemler_verisi, musteri)
        
        if hata:
            # Jinja2 tag hataları genellikle burada yakalanır
            logging.error(f"Döküman Motoru Hatası: {hata}")
            flash(f"Döküman oluşturulamadı: {hata}", "warning")
            return redirect(url_for('kiralama.index'))

        # 4. Dosyayı kullanıcıya PDF olarak gönder
        if str(dosya_yolu).lower().endswith('.pdf'):
            return send_file(dosya_yolu, mimetype='application/pdf')
        else:
            # PDF dönüşümü başarısız olduysa Word dosyasını gönder
            return send_file(dosya_yolu, as_attachment=True)

    except Exception as e:
        logging.error(f"Teslim Tutanağı Rota Hatası: {str(e)}")
        flash(f"Sistem Hatası: {str(e)}", "danger")
        return redirect(url_for('kiralama.index'))