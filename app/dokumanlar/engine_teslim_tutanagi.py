import os
import subprocess
import platform
import logging
import re
from datetime import date
from docxtpl import DocxTemplate
from app.utils import turkish_upper

# Windows için COM başlatma
if platform.system() == "Windows":
    import pythoncom

logger = logging.getLogger(__name__)

def safe_filename(name):
    if not name: return "isimsiz_dosya"
    return re.sub(r'[\\/*?:"<>|]', '_', str(name).strip())

def pdf_donustur_motoru(docx_path, output_dir):
    """
    Teslim tutanağı için PDF dönüşüm işlemini gerçekleştirir.
    """
    current_os = platform.system()
    pdf_path = docx_path.replace(".docx", ".pdf")
    abs_docx = os.path.abspath(docx_path)
    abs_pdf = os.path.abspath(pdf_path)

    if current_os == "Windows":
        try:
            from docx2pdf import convert
            pythoncom.CoInitialize()
            if os.path.exists(abs_pdf): os.remove(abs_pdf)
            convert(abs_docx, abs_pdf)
            return pdf_path if os.path.exists(abs_pdf) else None
        except Exception as e:
            logger.error(f"Teslimat PDF Hatası (Win): {e}")
            return None
        finally:
            try: pythoncom.CoUninitialize()
            except: pass
    else:
        try:
            subprocess.run([
                'soffice', '--headless', '--convert-to', 'pdf',
                '--outdir', output_dir, abs_docx
            ], check=True, capture_output=True, timeout=30)
            return pdf_path if os.path.exists(abs_pdf) else None
        except Exception as e:
            logger.error(f"Teslimat PDF Hatası (Linux): {e}")
            return None

def teslim_tutanagi_uret(kiralama, kalemler_verisi, musteri):
    """
    Word şablonunu doldurur ve PDF'e dönüştürür.
    """
    # İlk kez yazıdırıldığında tarihi kaydet
    if kiralama.kiralama_olusturma_tarihi is None:
        kiralama.kiralama_olusturma_tarihi = date.today()
        from app import db
        db.session.commit()
    try:
        base_dir = os.path.abspath(os.getcwd())
        template_path = os.path.join(base_dir, 'app', 'static', 'templates', 'Teslim_Tutanagi_TASLAK.docx')
        
        bulut_adi = musteri.bulut_klasor_adi or "Genel_Arsiv"
        output_dir = os.path.join(base_dir, 'app', 'static', 'arsiv', bulut_adi, 'Formlar')
        os.makedirs(output_dir, exist_ok=True)
        
        safe_f_no = safe_filename(kiralama.kiralama_form_no)
        docx_path = os.path.join(output_dir, f"{safe_f_no}_Teslim_Tutanagi.docx")

        if not os.path.exists(template_path):
            return None, "Şablon bulunamadı."

        doc = DocxTemplate(template_path)
        form_tarihi = kiralama.kiralama_olusturma_tarihi.strftime('%d.%m.%Y') if kiralama.kiralama_olusturma_tarihi else date.today().strftime('%d.%m.%Y')
        context = {
            'form_no': kiralama.kiralama_form_no,
            'gunun_tarihi': form_tarihi,
            'musteri_unvan': turkish_upper(musteri.firma_adi),
            'musteri_vergi': f"{musteri.vergi_dairesi or ''} / {musteri.vergi_no or ''}",
            'musteri_adres': musteri.iletisim_bilgileri or "",
            'makine_kullanim_yeri': kiralama.makine_calisma_adresi or "-",
            'kalemler': kalemler_verisi # Word'de {% tr for k in kalemler %}
        }
        
        doc.render(context)
        doc.save(docx_path)
        
        pdf_file = pdf_donustur_motoru(docx_path, output_dir)
        if pdf_file:
            try: os.remove(docx_path)
            except: pass
            return pdf_file, None
        
        return docx_path, None

    except Exception as e:
        return None, str(e)