import os
import platform
import subprocess
import time

def convert_docx_to_pdf(docx_path, output_dir, logger=None, timeout_seconds=30):
    current_os = platform.system()

    # 1. Klasörü oluştur ve Linux'ta "kapıları aç"
    if not os.path.exists(output_dir):
        os.makedirs(output_dir, exist_ok=True)
        if current_os != "Windows":
            os.chmod(output_dir, 0o777) # Herkes yazabilsin

    abs_docx = os.path.abspath(docx_path)
    filename = os.path.basename(abs_docx).replace(".docx", ".pdf")
    abs_pdf = os.path.join(os.path.abspath(output_dir), filename)

    if current_os == "Windows":
        try:
            from docx2pdf import convert
            import pythoncom

            pythoncom.CoInitialize()

            if os.path.exists(abs_pdf):
                try:
                    os.remove(abs_pdf)
                except Exception:
                    pass

            convert(abs_docx, abs_pdf)
            time.sleep(1)

            if os.path.exists(abs_pdf):
                return abs_pdf
            else:
                if logger:
                    logger.error("PDF oluşmadı (Windows docx2pdf).")
                return None

        except Exception as e:
            if logger:
                logger.error(f"Windows PDF dönüşüm hatası: {e}")
            return None
        finally:
            try:
                import pythoncom as _pc
                _pc.CoUninitialize()
            except Exception:
                pass

    # --- Helsinki / Linux Operasyonu ---
    try:
        command = [
            "soffice",
            "-env:UserInstallation=file:///tmp/libreoffice_profile",
            "--headless",
            "--convert-to", "pdf",
            "--outdir", os.path.abspath(output_dir),
            abs_docx
        ]
        
        result = subprocess.run(
            command,
            check=True,
            capture_output=True, # Hata mesajlarını yakalar
            text=True,           # Mesajları okunabilir metin yapar
            timeout=timeout_seconds,
        )
        
        if os.path.exists(abs_pdf):
            return abs_pdf
        else:
            # Burası kritik: Eğer dosya yoksa LibreOffice ne dedi?
            error_msg = f"PDF oluşmadı! LibreOffice Çıktısı: {result.stdout} {result.stderr}"
            if logger: logger.error(error_msg)
            return None

    except Exception as e:
        msg = f"soffice ile PDF donusumu basarisiz: {str(e)}"
        if logger: logger.error(msg)
        return None