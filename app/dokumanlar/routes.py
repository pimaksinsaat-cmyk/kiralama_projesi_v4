import os
from flask import flash, redirect, url_for, send_file, request
from . import dokumanlar_bp
from app.firmalar.models import Firma

# engine_ps.py modülünü güvenli bir şekilde içe aktaralım
try:
    from app.dokumanlar.engine_ps import ps_word_olustur
except ImportError:
    from .engine_ps import ps_word_olustur

@dokumanlar_bp.route('/ps-yazdir/<int:firma_id>')
def ps_yazdir(firma_id):
    """
    Sözleşmeyi oluşturur ve tarayıcıya gönderir.
    Hız Optimizasyonu: Dosya zaten varsa LibreOffice'i çalıştırmadan mevcut dosyayı gönderir.
    """
    try:
        # 1. Firmayı veritabanından bul
        firma = Firma.query.get_or_404(firma_id)
        
        # 2. PS Numarası atanıp atanmadığını kontrol et
        if not firma.sozlesme_no:
            flash(f"'{firma.firma_adi}' için önce PS numarası oluşturmalısınız (Sağ Tık -> Sözleşme Hazırla).", "warning")
            return redirect(url_for('firmalar.index'))

        # --- HIZ OPTİMİZASYONU (ÖNBELLEK) ---
        # Eğer kullanıcı özellikle 'yenile' demediyse ve dosya sistemde varsa doğrudan gönder.
        # Bu işlem mobildeki 5-10 saniyelik beklemeyi ikinci tıklamada 0'a indirir.
        refresh = request.args.get('refresh', 'false').lower() == 'true'
        
        # Dosya yolunu oluştur (engine_ps.py ile aynı mantık)
        base_path = os.path.join(os.getcwd(), 'app', 'static', 'arsiv', firma.bulut_klasor_adi, 'PS')
        pdf_yolu = os.path.join(base_path, f"{firma.sozlesme_no}_Sozlesme.pdf")

        if not refresh and os.path.exists(pdf_yolu):
            # Dosya bulundu, motoru çalıştırmadan doğrudan gönderiyoruz.
            dosya_yolu = pdf_yolu
        else:
            # 3. Dosyayı OLUŞTUR (İlk kez oluşturuluyor veya zorunlu yenileme yapılıyor)
            dosya_yolu = ps_word_olustur(firma)
        
        if not dosya_yolu or not os.path.exists(dosya_yolu):
            flash("Dosya oluşturulamadı veya sunucu diskinde bulunamadı.", "danger")
            return redirect(url_for('firmalar.index'))

        # 4. Uzantıyı ve MIME Tipini Dinamik Olarak Belirle
        uzanti = os.path.splitext(dosya_yolu)[1].lower()
        
        if uzanti == '.pdf':
            mimetype = 'application/pdf'
            # as_attachment=False: iPhone'da doğrudan Safari içinde açar
            as_attachment = False
        else:
            mimetype = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
            as_attachment = True

        # 5. Dosyayı Kullanıcıya Gönder
        return send_file(
            dosya_yolu,
            mimetype=mimetype,
            as_attachment=as_attachment,
            download_name=f"{firma.sozlesme_no}_{firma.firma_adi}{uzanti}"
        )
        
    except Exception as e:
        flash(f"Döküman hazırlama sırasında bir hata oluştu: {str(e)}", "danger")
        return redirect(url_for('firmalar.index'))