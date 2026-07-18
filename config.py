import os

# Projemizin temel dizinini bul
basedir = os.path.abspath(os.path.dirname(__file__))


def _env_to_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return str(value).strip().lower() in {'1', 'true', 'yes', 'on'}

class Config:
    """
    Tüm yapılandırmalar için temel sınıf.
    """
    
    # --- Güvenlik Ayarları ---
    
    # Flask ve Flask-WTF'nin CSRF koruması için gizli anahtar
    # BU ÇOK ÖNEMLİ! Güvenlik için bunu karmaşık bir şey yapmalıyız.
    # Terminalde "python -c 'import secrets; print(secrets.token_hex(16))'" 
    # komutuyla rastgele bir anahtar üretebilirsiniz.
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'buraya-tahmin-edilmesi-zor-bir-sifre-yazin'
    
    
    # --- Veritabanı Ayarları ---
    
    # Veritabanı bağlantısı öncelikle ortam değişkeninden alınır.
    # Ortam değişkeni yoksa PostgreSQL varsayılanları kullanılır.
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
    'postgresql://postgres:gizlisifre@db:5432/kiralama_db'  
    # Veritabanında değişiklik olduğunda sinyal göndermeyi kapat (performans)
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # PostgreSQL bağlantı kopması / stale connection sorununu önler
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,   # Her istekte bağlantıyı test et, kopuksa yenile
        "pool_recycle": 280,     # 280 saniyede bir bağlantıyı yenile (PG idle timeout < 300s)
    }

    # Oturum Güvenliği
    PERMANENT_SESSION_LIFETIME = 1800  # 1 saat hareketsizlikte oturum kapanır (saniye)
    SESSION_COOKIE_SECURE = False       # Production'da True yap (HTTPS gerekir)
    SESSION_COOKIE_HTTPONLY = True      # JS ile cookie erişimini engelle
    SESSION_COOKIE_SAMESITE = 'Lax'    # CSRF koruması
    REMEMBER_COOKIE_DURATION = False    # Beni hatırla süresi

    # Flask-Session Ayarları
    SESSION_TYPE = 'filesystem'  # Session'ları sunucuda dosya olarak sakla
    SESSION_FILE_DIR = os.path.join(os.path.dirname(__file__), 'flask_session')
    SESSION_PERMANENT = False    # Tarayıcı kapanınca oturum bitsin
    SESSION_USE_SIGNER = True    # Cookie imzalansın
    SESSION_KEY_PREFIX = 'pimaks_'

    # Türkçe karakterlerin JSON yanıtlarında kaçış karakteri olmadan gönderilmesi
    JSON_AS_ASCII = False

    # Template ve statik dosya yenileme davranışı
    TEMPLATES_AUTO_RELOAD = _env_to_bool('TEMPLATES_AUTO_RELOAD', False)
    SEND_FILE_MAX_AGE_DEFAULT = 0 if _env_to_bool('DISABLE_STATIC_CACHE', False) else None

    # firmalar/bilgi cari dönem tarih filtresi (calculate_window_amounts). Kapalı: eski tam-liste davranışı.
    CARI_DONEM_FILTRESI_ENABLED = _env_to_bool('CARI_DONEM_FILTRESI_ENABLED', True)


    # Mobil API JWT ayarlari
    API_JWT_SECRET_KEY = os.environ.get('API_JWT_SECRET_KEY')
    API_JWT_ISSUER = os.environ.get('API_JWT_ISSUER', 'kiralama-api')
    API_JWT_AUDIENCE = os.environ.get('API_JWT_AUDIENCE', 'kiralama-mobile')
    API_ACCESS_TOKEN_SECONDS = int(os.environ.get('API_ACCESS_TOKEN_SECONDS', '900'))
    API_REFRESH_TOKEN_SECONDS = int(os.environ.get('API_REFRESH_TOKEN_SECONDS', '2592000'))
    API_REFRESH_GRACE_SECONDS = int(os.environ.get('API_REFRESH_GRACE_SECONDS', '45'))
    API_JWT_LEEWAY_SECONDS = int(os.environ.get('API_JWT_LEEWAY_SECONDS', '10'))


class ProductionConfig(Config):
    """HTTPS üretim dağıtımı: SECRET_KEY ortamdan gelmeli, güvenli çerez."""
    DEBUG = False
    TESTING = False
    SESSION_COOKIE_SECURE = _env_to_bool('SESSION_COOKIE_SECURE', True)
    SECRET_KEY = os.environ.get('SECRET_KEY')


class TestingConfig(Config):
    """Pytest ve yerel otomatik testler için."""
    TESTING = True
    WTF_CSRF_ENABLED = False
    SECRET_KEY = 'test-secret-key'
    # Yerel: sqlite bellek. PostgreSQL ile tam entegrasyon için TEST_DATABASE_URL verin.
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        'TEST_DATABASE_URL',
        'sqlite:///:memory:',
    )
    SQLALCHEMY_ENGINE_OPTIONS = {}
