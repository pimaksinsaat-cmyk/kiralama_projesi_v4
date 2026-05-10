import logging
import os

from flask import flash, redirect, render_template, request, send_file, url_for
from flask_login import current_user

from . import dokumanlar_bp
from .archive_utils import document_hash_summary
from .engine_teslim_tutanagi import teslim_tutanagi_uret
from app.services.operation_log_service import OperationLogService

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
    Teslim tutanağı üretir. PDF başarılı olsa bile DOCX arşivde tutulur.
    """
    try:
        kiralama = Kiralama.query.get_or_404(rental_id)
        musteri = kiralama.firma_musteri

        if not musteri:
            flash("Müşteri bilgisi bulunamadı.", "danger")
            return redirect(url_for('kiralama.index'))

        kalemler_verisi = []
        for kalem in kiralama.kalemler:
            kullanim_yeri = kiralama.makine_calisma_adresi or "-"

            if kalem.is_dis_tedarik_ekipman:
                marka = (kalem.harici_ekipman_marka or "").strip()
                model = (kalem.harici_ekipman_model or "").strip()
                ekipman_adi = " ".join([x for x in [marka, model] if x]) or "Bilinmiyor"
                seri_no = kalem.harici_ekipman_seri_no or "-"
            elif kalem.ekipman:
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
                'teslim_tarihi': kalem.kiralama_baslangici.strftime('%d.%m.%Y'),
            })

        dosya_yolu, hata = teslim_tutanagi_uret(kiralama, kalemler_verisi, musteri)

        if hata:
            logging.error(f"Döküman Motoru Hatası: {hata}")
            flash(f"Döküman oluşturulamadı: {hata}", "warning")
            return redirect(url_for('kiralama.index'))

        if not dosya_yolu:
            flash("Döküman oluşturulamadı.", "warning")
            return redirect(url_for('kiralama.index'))

        docx_yolu = (
            str(dosya_yolu).replace(".pdf", ".docx")
            if str(dosya_yolu).lower().endswith('.pdf')
            else dosya_yolu
        )
        pdf_yolu = (
            str(dosya_yolu).replace(".docx", ".pdf")
            if str(dosya_yolu).lower().endswith('.docx')
            else dosya_yolu
        )
        hash_summary = document_hash_summary(pdf=pdf_yolu, docx=docx_yolu)
        OperationLogService.log(
            module='dokumanlar',
            action='teslim_tutanagi_yazdir_arsiv',
            user_id=getattr(current_user, 'id', None),
            username=getattr(current_user, 'username', None),
            entity_type='Kiralama',
            entity_id=rental_id,
            description=f"Teslim tutanağı çıktısı hazırlandı: {kiralama.kiralama_form_no}; {hash_summary}",
            success=str(dosya_yolu).lower().endswith('.pdf'),
        )

        pdf_available = bool(pdf_yolu and os.path.exists(pdf_yolu))
        docx_available = bool(docx_yolu and os.path.exists(docx_yolu))
        requested_format = request.args.get('format', '').lower()

        if requested_format == 'pdf':
            if not pdf_available:
                flash("PDF oluşturulamadı. Word dosyasını kullanabilirsiniz.", "warning")
                return redirect(url_for('dokumanlar.teslim_tutanagi_hazirla', rental_id=rental_id))
            return send_file(
                pdf_yolu,
                mimetype='application/pdf',
                as_attachment=False,
                download_name=f"{kiralama.kiralama_form_no}_Teslim_Tutanagi.pdf",
            )

        if requested_format == 'docx':
            if not docx_available:
                flash("Word dosyası bulunamadı.", "warning")
                return redirect(url_for('dokumanlar.teslim_tutanagi_hazirla', rental_id=rental_id))
            return send_file(
                docx_yolu,
                mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                as_attachment=True,
                download_name=f"{kiralama.kiralama_form_no}_Teslim_Tutanagi.docx",
            )

        return render_template(
            'dokumanlar/onizleme.html',
            belge_baslik="Teslim Tutanağı Oluştur",
            belge_alt_baslik=f"{kiralama.kiralama_form_no} - {musteri.firma_adi}",
            pdf_available=pdf_available,
            docx_available=docx_available,
            pdf_url=url_for('dokumanlar.teslim_tutanagi_hazirla', rental_id=rental_id, format='pdf'),
            docx_url=url_for('dokumanlar.teslim_tutanagi_hazirla', rental_id=rental_id, format='docx'),
            return_url=url_for('kiralama.index'),
        )

    except Exception as e:
        logging.error(f"Teslim Tutanağı Rota Hatası: {str(e)}")
        flash(f"Sistem Hatası: {str(e)}", "danger")
        return redirect(url_for('kiralama.index'))
