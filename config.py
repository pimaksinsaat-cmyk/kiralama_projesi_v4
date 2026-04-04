import os

# Projemizin temel dizinini bul
basedir = os.path.abspath(os.path.dirname(__file__))

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