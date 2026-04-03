import os
import subprocess
import platform
from docxtpl import DocxTemplate
from datetime import date
import logging
import time
from app.utils import turkish_upper

# Log seviyesini ayarla
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def ps_word_olustur(firma):
    """
    Word şablonunu doldurur ve PDF dönüşümünü Windows/Linux uyumlu hale getirir.
    Windows'ta sessiz çökmeleri engellemek için COM yönetimi optimize edildi.
    """
    try:
        # 1. Klasör ve Dosya Yollarını Hazırla (Tam Mutlak Yol Kullanımı)
        base_dir = os.path.abspath(os.getcwd())
        template_path = os.path.normpath(os.path.join(base_dir, 'app', 'static', 'templates', 'Sozlesme_TASLAK.docx'))
        output_dir = os.path.normpath(os.path.join(base_dir, 'app', 'static', 'arsiv', firma.bulut_klasor_adi, 'PS'))
        
        os.makedirs(output_dir, exist_ok=True)
        
        docx_path = os.path.normpath(os.path.join(output_dir, f"{firma.sozlesme_no}_Sozlesme.docx"))
        pdf_path = os.path.normpath(os.path.join(output_dir, f"{firma.sozlesme_no}_Sozlesme.pdf"))

        # 2. Word Şablonunu Doldur
        if not os.path.exists(template_path):
            logger.error(f"Şablon bulunamadı: {template_path}")
            return None

        doc = DocxTemplate(template_path)
        ana_sozlesme_baslangic_tarihi = (
            firma.sozlesme_tarihi.strftime('%d.%m.%Y')
            if firma.sozlesme_tarihi
            else date.today().strftime('%d.%m.%Y')
        )
        context = {
            'sozlesme_no': firma.sozlesme_no or "BELİRSİZ",
            # Geriye uyumluluk için eski anahtar da korunur.
            'tarih': ana_sozlesme_baslangic_tarihi,
            'ana_sozlesme_baslangic_tarihi': ana_sozlesme_baslangic_tarihi,
            'firma_adi': turkish_upper(firma.firma_adi),
            'adres': firma.iletisim_bilgileri or "",
            'vergi_dairesi': firma.vergi_dairesi or "",
            'vergi_no': firma.vergi_no or "",
            'yetkili': firma.yetkili_adi or "",
            'telefon': firma.telefon or "",
            'eposta': firma.eposta or ""
        }
        doc.render(context)
        doc.save(docx_path)
        logger.info(f"Word kaydedildi: {docx_path}")

        # 3. PDF Dönüşümü
        current_os = platform.system()

        if current_os == "Windows":
            try:
                from docx2pdf import convert
                import pythoncom
                
                # COM kütüphanesini temiz başlat
                pythoncom.CoInitialize()
                
                logger.info(f"Windows: PDF dönüşümü başlatılıyor... ({firma.sozlesme_no})")
                
                # Mevcut PDF varsa sil
                if os.path.exists(pdf_path):
                    try: os.remove(pdf_path)
                    except: pass

                # Dönüştür
                convert(os.path.abspath(docx_path), os.path.abspath(pdf_path))
                
                # Yazma işlemi için bekle
                time.sleep(1)

                if os.path.exists(pdf_path):
                    logger.info("PDF Başarıyla oluşturuldu.")
                    # Word dosyasını sil
                    try: 
                        if os.path.exists(docx_path):
                            os.remove(docx_path)
                    except Exception as e:
                        logger.warning(f"Word dosyası silinemedi: {e}")
                    
                    return pdf_path
                else:
                    logger.warning("PDF oluşmadı, Word dönülüyor.")
                    return docx_path
                    
            except Exception as e:
                logger.error(f"Windows PDF Dönüşüm Hatası: {str(e)}")
                return docx_path
            finally:
                try: pythoncom.CoUninitialize()
                except: pass
        
        else:
            # Linux / Render Ortamı (LibreOffice)
            try:
                subprocess.run([
                    'libreoffice', '--headless', '--convert-to', 'pdf',
                    '--outdir', output_dir, docx_path
                ], check=True, capture_output=True, timeout=60)
                
                if os.path.exists(pdf_path):
                    try: os.remove(docx_path)
                    except: pass
                    return pdf_path
            except Exception as e:
                logger.error(f"Linux PDF Hatası: {str(e)}")
        
        return docx_path

    except Exception as e:
        logger.error(f"Genel Hata: {str(e)}")
        return None