import os

from flask import flash, redirect, render_template, request, send_file, url_for
from flask_login import current_user

from . import dokumanlar_bp
from .archive_utils import document_hash_summary
from app.firmalar.models import Firma
from app.services.operation_log_service import OperationLogService

try:
    from app.dokumanlar.engine_ps import ps_word_olustur
except ImportError:
    from .engine_ps import ps_word_olustur


@dokumanlar_bp.route('/ps-yazdir/<int:firma_id>')
def ps_yazdir(firma_id):
    """
    Sözleşmeyi oluşturur ve tarayıcıya gönderir.
    PDF başarılı olsa bile DOCX arşivde tutulur.
    """
    try:
        firma = Firma.query.get_or_404(firma_id)

        if not firma.sozlesme_no:
            flash(
                f"'{firma.firma_adi}' için önce PS numarası oluşturmalısınız "
                "(Sağ Tık -> Sözleşme Hazırla).",
                "warning",
            )
            return redirect(url_for('firmalar.index'))

        refresh = request.args.get('refresh', 'false').lower() == 'true'
        base_path = os.path.join(
            os.getcwd(),
            'app',
            'static',
            'arsiv',
            firma.bulut_klasor_adi,
            'PS',
        )
        pdf_yolu = os.path.join(base_path, f"{firma.sozlesme_no}_Sozlesme.pdf")
        docx_yolu = os.path.join(base_path, f"{firma.sozlesme_no}_Sozlesme.docx")

        if not refresh and os.path.exists(pdf_yolu) and os.path.exists(docx_yolu):
            dosya_yolu = pdf_yolu
        else:
            dosya_yolu = ps_word_olustur(firma)

        if not dosya_yolu or not os.path.exists(dosya_yolu):
            flash("Dosya oluşturulamadı veya sunucu diskinde bulunamadı.", "danger")
            return redirect(url_for('firmalar.index'))

        hash_summary = document_hash_summary(pdf=pdf_yolu, docx=docx_yolu)
        OperationLogService.log(
            module='dokumanlar',
            action='sozlesme_yazdir_arsiv',
            user_id=getattr(current_user, 'id', None),
            username=getattr(current_user, 'username', None),
            entity_type='Firma',
            entity_id=firma_id,
            description=f"Sözleşme çıktısı hazırlandı: {firma.sozlesme_no}; {hash_summary}",
            success=True,
        )

        pdf_available = os.path.exists(pdf_yolu)
        docx_available = os.path.exists(docx_yolu)
        requested_format = request.args.get('format', '').lower()

        if requested_format == 'pdf':
            if not pdf_available:
                flash("PDF oluşturulamadı. Word dosyasını kullanabilirsiniz.", "warning")
                return redirect(url_for('dokumanlar.ps_yazdir', firma_id=firma_id))
            return send_file(
                pdf_yolu,
                mimetype='application/pdf',
                as_attachment=False,
                download_name=f"{firma.sozlesme_no}_{firma.firma_adi}.pdf",
            )

        if requested_format == 'docx':
            if not docx_available:
                flash("Word dosyası bulunamadı.", "warning")
                return redirect(url_for('dokumanlar.ps_yazdir', firma_id=firma_id))
            return send_file(
                docx_yolu,
                mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                as_attachment=True,
                download_name=f"{firma.sozlesme_no}_{firma.firma_adi}.docx",
            )

        return render_template(
            'dokumanlar/onizleme.html',
            belge_baslik="Sözleşmeyi Oluştur",
            belge_alt_baslik=f"{firma.firma_adi} - {firma.sozlesme_no}",
            pdf_available=pdf_available,
            docx_available=docx_available,
            pdf_url=url_for('dokumanlar.ps_yazdir', firma_id=firma_id, format='pdf'),
            docx_url=url_for('dokumanlar.ps_yazdir', firma_id=firma_id, format='docx'),
            return_url=url_for('firmalar.index'),
        )

    except Exception as e:
        flash(f"Döküman hazırlama sırasında bir hata oluştu: {str(e)}", "danger")
        return redirect(url_for('firmalar.index'))
