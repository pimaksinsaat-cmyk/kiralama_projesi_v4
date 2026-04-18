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

_TR_LOWER_MAP = str.maketrans({
    'İ': 'i',
    'I': 'ı',
    'Ç': 'ç',
    'Ğ': 'ğ',
    'Ö': 'ö',
    'Ş': 'ş',
    'Ü': 'ü',
})


def bugun():
    """Türkiye saatiyle bugünün tarihini döner (UTC+3).
    date.today() yerine her yerde bu kullanılmalıdır."""
    from datetime import datetime, timezone, timedelta
    return datetime.now(timezone(timedelta(hours=3))).date()


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


def tr_lower(s: str) -> str:
    """Türkçe uyumlu küçük harf dönüşümü: İ→i, I→ı, Ş→ş vb."""
    if s is None:
        return None
    return str(s).translate(_TR_LOWER_MAP).lower()


def tr_ilike(column, term: str):
    """
    Türkçe uyumlu büyük/küçük harf duyarsız SQL LIKE filtresi.
    PostgreSQL C locale'de ilike İ/i, Ş/ş vb. eşleştiremez;
    bu fonksiyon her iki tarafı da Türkçe kural ile normalize eder.
    """
    from sqlalchemy import func
    normalized_col = func.lower(
        func.replace(func.replace(func.replace(
            func.replace(func.replace(func.replace(func.replace(
                column,
                'İ', 'i'), 'I', 'ı'), 'Ş', 'ş'), 'Ğ', 'ğ'), 'Ö', 'ö'), 'Ü', 'ü'), 'Ç', 'ç')
    )
    normalized_term = tr_lower(term)
    return normalized_col.like(normalized_term)


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


def para_format(value, decimal_places=2):
    """Sayıyı Türk finansal formatında formatlar: 1.234.567,89"""
    try:
        v = float(value or 0)
        formatted = f"{v:,.{decimal_places}f}"
        # Virgül → binlik, nokta → ondalık (TR formatı)
        return formatted.replace(',', 'X').replace('.', ',').replace('X', '.')
    except (TypeError, ValueError):
        return '0,00'


def truncate_name(name, word_limit=4):
    """Bir metni kelime sayısına göre böler ve belirtilen sayıda kelimeyi döndürür."""
    if not name:
        return ''
    words = name.split()
    return ' '.join(words[:word_limit])