# app/db_menu/routes.py
import os
import sqlite3
import atexit
from datetime import datetime, timedelta
from io import BytesIO

from flask import flash, redirect, send_file, url_for
from flask_login import current_user, login_required

from app import db
from app.db_menu import db_menu_bp
from app.utils import admin_required


# ---------------------------------------------------------------------------
# Sabitler
# ---------------------------------------------------------------------------

BACKUP_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    'backups'
)
MAX_YEDEK_GUN = 7  # Kaç günlük otomatik yedek saklanacak


# ---------------------------------------------------------------------------
# Yardımcı fonksiyonlar
# ---------------------------------------------------------------------------

def _db_dosya_yolu():
    """SQLite DB dosyasının mutlak yolunu döndürür."""
    database = db.engine.url.database
    if database and database != ':memory:':
        return os.path.normpath(str(database))
    return None


def _sql_dump(db_path: str) -> bytes:
    """SQLite veritabanını SQL dump formatında bytes olarak döndürür."""
    conn = sqlite3.connect(db_path)
    sql = '\n'.join(conn.iterdump())
    conn.close()
    return sql.encode('utf-8')


def _eski_yedekleri_temizle():
    """MAX_YEDEK_GUN günden eski .sql yedek dosyalarını siler."""
    if not os.path.exists(BACKUP_DIR):
        return
    sinir = datetime.now() - timedelta(days=MAX_YEDEK_GUN)
    for dosya in os.listdir(BACKUP_DIR):
        if not dosya.endswith('.sql'):
            continue
        yol = os.path.join(BACKUP_DIR, dosya)
        try:
            mtime = datetime.fromtimestamp(os.path.getmtime(yol))
            if mtime < sinir:
                os.remove(yol)
        except Exception:
            pass


def _yedek_listesi():
    """Mevcut yedek dosyalarını listeler (en yeni önce)."""
    if not os.path.exists(BACKUP_DIR):
        return []
    sonuc = []
    for dosya in sorted(os.listdir(BACKUP_DIR), reverse=True):
        if not dosya.endswith('.sql'):
            continue
        yol = os.path.join(BACKUP_DIR, dosya)
        try:
            boyut = os.path.getsize(yol)
            mtime = datetime.fromtimestamp(os.path.getmtime(yol))
            sonuc.append({
                'ad': dosya,
                'boyut_kb': round(boyut / 1024, 1),
                'tarih': mtime.strftime('%d.%m.%Y %H:%M'),
            })
        except Exception:
            pass
    return sonuc


def otomatik_yedek_al(app):
    """Günlük otomatik SQL yedeği alır (APScheduler tarafından çağrılır)."""
    with app.app_context():
        db_path = _db_dosya_yolu()
        if not db_path or not os.path.exists(db_path):
            return
        os.makedirs(BACKUP_DIR, exist_ok=True)
        bugun = datetime.now().strftime('%Y%m%d')
        hedef = os.path.join(BACKUP_DIR, f'oto_{bugun}.sql')
        if os.path.exists(hedef):
            return  # Bugün zaten alınmış
        try:
            conn = sqlite3.connect(db_path)
            with open(hedef, 'w', encoding='utf-8') as f:
                for line in conn.iterdump():
                    f.write(line + '\n')
            conn.close()
        except Exception:
            pass
        _eski_yedekleri_temizle()


# ---------------------------------------------------------------------------
# Context processor — tüm şablonlara yedek listesi enjekte eder
# ---------------------------------------------------------------------------

@db_menu_bp.app_context_processor
def inject_admin_db_backup_info():
    if not current_user.is_authenticated:
        return {}
    try:
        if not current_user.is_admin():
            return {}
    except Exception:
        return {}
    return {'db_yedek_listesi': _yedek_listesi()}


# ---------------------------------------------------------------------------
# Rotalar
# ---------------------------------------------------------------------------

@db_menu_bp.route('/yedek-sql', methods=['GET'])
@login_required
@admin_required
def db_yedek_sql():
    db_path = _db_dosya_yolu()
    if not db_path or not os.path.exists(db_path):
        flash('SQLite veritabanı dosyası bulunamadı.', 'danger')
        return redirect(url_for('main.index'))
    try:
        veri = _sql_dump(db_path)
    except Exception as exc:
        flash(f'SQL yedeği alınırken hata oluştu: {exc}', 'danger')
        return redirect(url_for('main.index'))

    dosya_adi = f"db_yedek_{datetime.now().strftime('%Y%m%d_%H%M%S')}.sql"
    return send_file(
        BytesIO(veri),
        as_attachment=True,
        download_name=dosya_adi,
        mimetype='text/plain'
    )
