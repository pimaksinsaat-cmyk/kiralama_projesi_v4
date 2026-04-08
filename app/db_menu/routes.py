# app/db_menu/routes.py
import os
import subprocess
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

def _db_backend_name():
    return db.engine.url.get_backend_name()


def _postgres_env(url):
    env = os.environ.copy()
    if url.password:
        env['PGPASSWORD'] = url.password
    return env


def _postgres_dump_command(*, output_path=None):
    url = db.engine.url
    command = [
        os.environ.get('PG_DUMP_BIN', '/usr/bin/pg_dump'),
        '--host', url.host or 'localhost',
        '--port', str(url.port or 5432),
        '--username', url.username or 'postgres',
        '--dbname', url.database or '',
        '--encoding=UTF8',
        '--no-owner',
        '--no-privileges',
        '--clean',
        '--if-exists',
    ]
    if output_path:
        command.extend(['--file', output_path])
    return command, _postgres_env(url)


def _sql_dump() -> bytes:
    """Aktif veritabanı için SQL dump çıktısını bytes olarak döndürür."""
    backend = _db_backend_name()
    if backend == 'postgresql':
        command, env = _postgres_dump_command()
        try:
            completed = subprocess.run(
                command,
                check=True,
                capture_output=True,
                env=env,
            )
        except FileNotFoundError as exc:
            raise RuntimeError('pg_dump komutu bulunamadı. Uygulama ortamına postgresql-client kurulmalı.') from exc
        except subprocess.CalledProcessError as exc:
            stderr = exc.stderr.decode('utf-8', errors='ignore').strip()
            raise RuntimeError(stderr or 'pg_dump başarısız oldu.') from exc

        return completed.stdout

    raise RuntimeError(f'Bu yedekleme akışı sadece PostgreSQL için yapılandırıldı. Aktif veritabanı: {backend}')


def _write_backup_file(target_path: str):
    backend = _db_backend_name()
    if backend == 'postgresql':
        command, env = _postgres_dump_command(output_path=target_path)
        try:
            subprocess.run(command, check=True, capture_output=True, env=env)
        except FileNotFoundError as exc:
            raise RuntimeError('pg_dump komutu bulunamadı. Uygulama ortamına postgresql-client kurulmalı.') from exc
        except subprocess.CalledProcessError as exc:
            stderr = exc.stderr.decode('utf-8', errors='ignore').strip()
            raise RuntimeError(stderr or 'pg_dump başarısız oldu.') from exc
        return

    raise RuntimeError(f'Bu yedekleme akışı sadece PostgreSQL için yapılandırıldı. Aktif veritabanı: {backend}')


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
        os.makedirs(BACKUP_DIR, exist_ok=True)
        bugun = datetime.now().strftime('%Y%m%d')
        hedef = os.path.join(BACKUP_DIR, f'oto_{bugun}.sql')
        if os.path.exists(hedef):
            return  # Bugün zaten alınmış
        try:
            _write_backup_file(hedef)
        except Exception as exc:
            app.logger.warning('Otomatik veritabanı yedeği alınamadı: %s', exc)
            return
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
    try:
        veri = _sql_dump()
    except Exception as exc:
        flash(f'Veritabanı yedeği alınırken hata oluştu: {exc}', 'danger')
        return redirect(url_for('main.index'))

    dosya_adi = f"db_yedek_{datetime.now().strftime('%Y%m%d_%H%M%S')}.sql"
    return send_file(
        BytesIO(veri),
        as_attachment=True,
        download_name=dosya_adi,
        mimetype='text/plain'
    )
