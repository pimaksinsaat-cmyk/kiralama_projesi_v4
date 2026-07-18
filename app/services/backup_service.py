import os
import subprocess
from datetime import datetime, timedelta, timezone

from app.extensions import db


BACKUP_DIR = os.environ.get(
    'BACKUP_DIR',
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        'backups',
    ),
)
BACKUP_RETENTION_DAYS = 14


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


def _require_postgresql():
    if db.engine.url.get_backend_name() != 'postgresql':
        raise RuntimeError('Veritabani yedekleme akisi sadece PostgreSQL icin yapilandirildi.')


def sql_dump():
    _require_postgresql()
    command, env = _postgres_dump_command()
    try:
        completed = subprocess.run(command, check=True, capture_output=True, env=env)
    except FileNotFoundError as exc:
        raise RuntimeError('pg_dump bulunamadi; postgresql-client kurulmalidir.') from exc
    except subprocess.CalledProcessError as exc:
        message = exc.stderr.decode('utf-8', errors='ignore').strip()
        raise RuntimeError(message or 'pg_dump basarisiz oldu.') from exc
    return completed.stdout


def write_backup_file(target_path):
    _require_postgresql()
    command, env = _postgres_dump_command(output_path=target_path)
    try:
        subprocess.run(command, check=True, capture_output=True, env=env)
    except FileNotFoundError as exc:
        raise RuntimeError('pg_dump bulunamadi; postgresql-client kurulmalidir.') from exc
    except subprocess.CalledProcessError as exc:
        message = exc.stderr.decode('utf-8', errors='ignore').strip()
        raise RuntimeError(message or 'pg_dump basarisiz oldu.') from exc


def rotate_automatic_backups(*, now=None, keep_path=None):
    if not os.path.isdir(BACKUP_DIR):
        return
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=BACKUP_RETENTION_DAYS)
    keep_path = os.path.abspath(keep_path) if keep_path else None
    for filename in os.listdir(BACKUP_DIR):
        if not filename.startswith('oto_') or not filename.endswith('.sql'):
            continue
        path = os.path.abspath(os.path.join(BACKUP_DIR, filename))
        if path == keep_path:
            continue
        try:
            modified_at = datetime.fromtimestamp(os.path.getmtime(path), tz=timezone.utc)
            if modified_at < cutoff:
                os.remove(path)
        except OSError:
            continue


def create_automatic_backup(*, now=None):
    now = now or datetime.now(timezone.utc)
    os.makedirs(BACKUP_DIR, exist_ok=True)
    target = os.path.join(BACKUP_DIR, f"oto_{now.strftime('%Y%m%d')}.sql")
    if not os.path.exists(target):
        write_backup_file(target)
    rotate_automatic_backups(now=now, keep_path=target)
    return target


def list_backups():
    if not os.path.isdir(BACKUP_DIR):
        return []
    result = []
    for filename in sorted(os.listdir(BACKUP_DIR), reverse=True):
        if not filename.endswith('.sql'):
            continue
        path = os.path.join(BACKUP_DIR, filename)
        try:
            size = os.path.getsize(path)
            modified_at = datetime.fromtimestamp(os.path.getmtime(path), tz=timezone.utc)
        except OSError:
            continue
        result.append({
            'ad': filename,
            'boyut_kb': round(size / 1024, 1),
            'tarih': modified_at.strftime('%d.%m.%Y %H:%M'),
        })
    return result
