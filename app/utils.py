from wtforms.validators import ValidationError
import re
from functools import wraps
from flask import flash, redirect, url_for, abort
from flask_login import current_user


_TR_UPPER_MAP = str.maketrans({
    'i': 'İ',
    'ı': 'I',
    'ç': 'Ç',
    'ğ': 'Ğ',
    'ö': 'Ö',
    'ş': 'Ş',
    'ü': 'Ü',
})


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin():
            abort(403)
        return f(*args, **kwargs)
    return decorated_function

# Ortak hata mesajı değişkeni
secim_hata_mesaji = "Lütfen geçerli bir seçim yapınız."


def turkish_upper(value):
    """Metni Turkce buyuk harf kurallarina gore donusturur."""
    if value is None:
        return None
    return str(value).translate(_TR_UPPER_MAP).upper()


def normalize_turkish_upper(value, strip=True):
    """Kullanici girdilerini Turkce uyumlu sekilde buyuk harfe cevirir."""
    if value is None:
        return None

    text = str(value)
    if strip:
        text = text.strip()
    return turkish_upper(text)


def ensure_active_sube_exists(redirect_endpoint='subeler.index', warning_message=None):
    """Aktif şube/depo yoksa kullanıcıyı uyarıp ilgili sayfaya yönlendirir."""
    from app.subeler.models import Sube

    aktif_sube_var = Sube.query.filter_by(is_active=True).first() is not None
    if aktif_sube_var:
        return None

    flash(
        warning_message or "Bu işlem için önce en az bir aktif şube / depo tanımlamalısınız.",
        'warning'
    )
    return redirect(url_for(redirect_endpoint))

# Para Birimi Doğrulayıcı Fonksiyonu
def validate_currency(form, field):
    if field.data:
        # Noktaları sil, virgülü noktaya çevir (1.500,00 -> 1500.00)
        clean_value = str(field.data).replace('.', '').replace(',', '.')
        try:
            float(clean_value)
        except ValueError:
            raise ValidationError("Lütfen geçerli bir sayısal değer giriniz (Örn: 150.000,00).")
        
# klasör adı düzeltme fonksiyonu       
def klasor_adi_temizle(firma_adi, firma_id):
    """
    Firma adını klasör dostu hale getirir: 'Pimaks İnşaat' -> '145_pimaks_i'
    """
    # 1. Türkçe karakter dönüşümü
    mapping = str.maketrans("çğıöşüÇĞİÖŞÜ ", "cgiosuCGIOSU_")
    temiz = str(firma_adi).translate(mapping)
    
    # 2. Sadece harf, rakam ve alt tire kalsın (boşluklar alt tire oldu)
    temiz = re.sub(r'[^a-zA-Z0-9_]', '', temiz)
    
    # 3. Küçük harfe çevir ve ilk 8 karakteri al
    kisa_ad = temiz[:8].lower()
    
    # 4. ID ile birleştirerek benzersiz yap
    return f"{firma_id}_{kisa_ad}"


def truncate_name(name, word_limit=4):
    """Bir metni kelime sayısına göre böler ve belirtilen sayıda kelimeyi döndürür."""
    if not name:
        return ''
    words = name.split()
    return ' '.join(words[:word_limit])