# app/__init__.py
import os

from flask import Flask, request, redirect, url_for  # ← 'app' kaldırıldı
from config import Config
from flask_wtf.csrf import CSRFProtect 
from app.extensions import db, migrate, login_manager, server_session
from sqlalchemy import inspect
from flask_login import current_user
from datetime import timedelta
from flask import session

csrf = CSRFProtect()

def create_app(config_class=Config):

    app = Flask(__name__)
    app.config.from_object(config_class)
    app.jinja_env.auto_reload = app.config.get('TEMPLATES_AUTO_RELOAD', False)

    # Özel Jinja filtresini kaydet
    from .utils import truncate_name
    app.jinja_env.filters['truncate_name'] = truncate_name

    db_url = os.getenv("DATABASE_URL")

    # Test modunda TEST_DATABASE_URL / TestingConfig URI korunur (SQLite veya ayrı test PG)
    if db_url and not app.config.get("TESTING"):
        db_url = db_url.replace("postgres://", "postgresql://")
        app.config['SQLALCHEMY_DATABASE_URI'] = db_url


    # --- Günlük Otomatik Yedekleme (APScheduler) ---
    # Werkzeug reloader'ın child sürecinde veya production'da başlat
    import os as _os

    # Admin kullanıcıyı migration sonrası otomatik oluştur
    def ensure_admin():
        with app.app_context():
            from app.auth.models import User
            if hasattr(db, 'engine') and inspect(db.engine).has_table('user'):
                if not User.query.filter_by(username='admin').first():
                    yeni_admin = User(
                        username='admin',
                        rol='admin',
                        is_active=True
                    )
                    yeni_admin.set_password('123456')  # Şifreyi daha sonra değiştirin!
                    db.session.add(yeni_admin)
                    db.session.commit()

    # extensions'dan gelen nesneleri başlatıyoruz
    db.init_app(app)

    # Import MakineDegisim before Ekipman to avoid relationship resolution issues
    from app.makinedegisim.models import MakineDegisim
    from app.filo.models import Ekipman

    # Sadece ana uygulama çalışırken migrate başlatılsın, scriptlerde gerek yok
    if os.environ.get("FLASK_RUN_FROM_CLI") == "true":
        migrate.init_app(app, db)

    # Admin kullanıcısını oluştur (migration'dan sonra)
    try:
        ensure_admin()
    except Exception:
        # Migration sırasında database schema eksik olabilir, bunu ignore et
        pass
    # CSRF uygulamasını başlat
    csrf.init_app(app)
    server_session.init_app(app)

    # Login Manager
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Bu sayfayı görmek için giriş yapmalısınız.'
    login_manager.login_message_category = 'warning'

    # Tüm uygulamayı login ile koru
    @app.before_request
    def require_login():
        acik_endpointler = ['auth.login', 'auth.logout', 'static']
        
        # Authenticated AJAX/API endpoint'leri muaf tutmak
        if request.path.startswith('/subeler/') and request.path.endswith('/makineler'):
            if current_user.is_authenticated:
                return None
        
        if request.endpoint in acik_endpointler:
            return None
            
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login', next=request.url))
    
        # Hareketsizlik kontrolü — her istekte süreyi sıfırla
        #session.permanent = True
        app.permanent_session_lifetime = timedelta(seconds=1800)

    # --- BLUEPRINT (MODÜL) KAYITLARI ---

    # 1. Ana Sayfa
    from app.main import main_bp
    app.register_blueprint(main_bp)

    # 2. Firmalar (Müşteri/Tedarikçi)
    from app.firmalar import firmalar_bp
    app.register_blueprint(firmalar_bp, url_prefix='/firmalar')

    # 3. Filo (Makine Parkı)
    from app.filo import filo_bp
    app.register_blueprint(filo_bp, url_prefix='/filo')

    # 3.1 Servis Kayitlari
    from app.servis import servis_bp
    app.register_blueprint(servis_bp, url_prefix='/servis')

    # 3.2 Stok Modulu
    from app.stok import stok_bp
    app.register_blueprint(stok_bp, url_prefix='/stok')

    # 4. Kiralama (Sözleşmeler)
    from app.kiralama import kiralama_bp
    app.register_blueprint(kiralama_bp, url_prefix='/kiralama')

    # 5. Cari (Finansal İşlemler)
    from app.cari import cari_bp
    app.register_blueprint(cari_bp, url_prefix='/cari')

    # 6. Nakliyeler
    from app.nakliyeler import nakliye_bp
    app.register_blueprint(nakliye_bp, url_prefix='/nakliyeler')

    # 7. Makine Değişim
    from app.makinedegisim import makinedegisim_bp
    app.register_blueprint(makinedegisim_bp, url_prefix='/makinedegisim')

    # 8. Dökümanlar
    from app.dokumanlar import dokumanlar_bp
    app.register_blueprint(dokumanlar_bp, url_prefix='/dokumanlar')

    # 9. Şubeler & Depolar
    from app.subeler import subeler_bp
    app.register_blueprint(subeler_bp, url_prefix='/subeler')

    # 10. Araçlar (Filo)
    from app.araclar import araclar_bp
    app.register_blueprint(araclar_bp, url_prefix='/araclar')

    # 11. Login & Kullanıcı Yönetimi
    from app.auth import auth_bp
    app.register_blueprint(auth_bp, url_prefix='/auth')

    # 12. fatura yönetimi
    from app.fatura import fatura_bp
    app.register_blueprint(fatura_bp, url_prefix='/fatura')

    # 13. Raporlama Merkezi
    from app.raporlama import raporlama_bp
    app.register_blueprint(raporlama_bp, url_prefix='/raporlama')

    # 13.1 Personel Yonetimi
    from app.personel import personel_bp
    app.register_blueprint(personel_bp, url_prefix='/personel')

    # 14. Takvim ve Hatırlatmalar
    from app.takvim import takvim_bp
    app.register_blueprint(takvim_bp)

    # 15. DB Yedekleme Menüsü
    from app.db_menu import db_menu_bp
    app.register_blueprint(db_menu_bp, url_prefix='/db-menu')

    # 16. Genel Ayarlar
    from app.ayarlar import ayarlar_bp
    app.register_blueprint(ayarlar_bp, url_prefix='/ayarlar')
    
    # Sadece ana uygulama çalışırken migrate işlemleri otomatik yapılsın
    # if os.environ.get("FLASK_RUN_FROM_CLI") == "true":
    #     with app.app_context():
    #         from alembic.util.exc import CommandError
    #         from flask_migrate import stamp, upgrade
    #         try:
    #             upgrade()
    #         except CommandError as exc:
    #             # Eski/silinmis bir revizyon kaydi varsa uygulama acilisini kilitleme.
    #             if "Can't locate revision identified by" in str(exc):
    #                 app.logger.warning(
    #                     "Alembic revizyonu bulunamadi. Mevcut DB surumu head olarak damgalaniyor: %s",
    #                 exc,
    #             )
    #             stamp(revision='head')
    #         # else:
            #     raise

        # with app.app_context():
        #     from app.auth.models import User
        #     from app.ayarlar.models import AppSettings
        #     # İlk kurulumda tablo henüz yoksa sorgu patlamasın
        #     if inspect(db.engine).has_table('user'):
        #         if not User.query.filter_by(username='admin').first():
        #             yeni_admin = User(
        #                 username='admin',
        #                 rol='admin',
        #                 is_active=True
        #             )
                #             yeni_admin.set_password('123456')
                #             db.session.add(yeni_admin)
                #             db.session.commit()
                #
                #     if inspect(db.engine).has_table('app_settings'):
                #         AppSettings.get_current()

    # --- Günlük Otomatik Yedekleme (APScheduler) ---
    # Werkzeug reloader'ın child sürecinde veya production'da başlat
    import os as _os
    if not app.debug or _os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
        try:
            import atexit
            from apscheduler.schedulers.background import BackgroundScheduler
            from app.db_menu.routes import otomatik_yedek_al

            _scheduler = BackgroundScheduler(daemon=True)
            _scheduler.add_job(
                func=lambda: otomatik_yedek_al(app),
                trigger='cron',
                hour=2,
                minute=0,
                id='gunluk_yedek',
                replace_existing=True,
            )
            _scheduler.start()
            atexit.register(lambda: _scheduler.shutdown(wait=False))
            # Uygulama ilk başladığında bugünün yedeğini al
            otomatik_yedek_al(app)
        except Exception:
            pass

    return app
    

    