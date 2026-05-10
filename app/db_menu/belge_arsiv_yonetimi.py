import json
import os
import shutil
import tempfile
import uuid
import zipfile
from datetime import datetime, timedelta, timezone
from hashlib import sha256

from flask import after_this_request, current_app, jsonify, request, send_file
from flask_login import current_user, login_required

from app.db_menu import db_menu_bp
from app.services.operation_log_service import OperationLogService
from app.utils import admin_required


ALLOWED_EXTENSIONS = {'.pdf', '.docx'}
HASH_CHUNK_SIZE = 1024 * 1024
MANIFEST_MAX_AGE = timedelta(hours=24)


def _utc_now():
    return datetime.now(timezone.utc)


def _archive_root():
    return os.path.realpath(os.path.join(current_app.static_folder, 'arsiv'))


def _manifest_cache_dir():
    path = os.path.join(tempfile.gettempdir(), 'kiralama_belge_arsiv_manifestleri')
    os.makedirs(path, exist_ok=True)
    return path


def _manifest_cache_path(manifest_id):
    safe_id = str(manifest_id or '').strip()
    if not safe_id or not all(c.isalnum() or c in '-_' for c in safe_id):
        return None
    return os.path.join(_manifest_cache_dir(), f'{safe_id}.json')


def _cleanup_old_manifests():
    cache_dir = _manifest_cache_dir()
    cutoff = _utc_now() - MANIFEST_MAX_AGE
    for entry in os.scandir(cache_dir):
        if not entry.is_file() or not entry.name.endswith('.json'):
            continue
        try:
            mtime = datetime.fromtimestamp(entry.stat().st_mtime, tz=timezone.utc)
            if mtime < cutoff:
                os.remove(entry.path)
        except Exception:
            continue


def sha256_file(path):
    digest = sha256()
    with open(path, 'rb') as handle:
        while True:
            chunk = handle.read(HASH_CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _is_allowed_archive_file(path):
    _, ext = os.path.splitext(path)
    if ext.lower() not in ALLOWED_EXTENSIONS:
        return False
    root = _archive_root()
    real_path = os.path.realpath(path)
    try:
        return os.path.commonpath([root, real_path]) == root
    except ValueError:
        return False


def _safe_rel_path(path):
    root = _archive_root()
    real_path = os.path.realpath(path)
    if os.path.commonpath([root, real_path]) != root:
        raise ValueError('Arsiv disi dosya yolu reddedildi.')
    return os.path.relpath(real_path, root).replace(os.sep, '/')


def _path_from_manifest_rel(rel_path):
    rel = str(rel_path or '').replace('\\', '/').strip()
    if not rel or rel.startswith('/') or '\x00' in rel:
        return None
    parts = [part for part in rel.split('/') if part not in ('', '.')]
    if any(part == '..' for part in parts):
        return None
    candidate = os.path.realpath(os.path.join(_archive_root(), *parts))
    if not _is_allowed_archive_file(candidate):
        return None
    return candidate


def _iter_archive_files():
    root = _archive_root()
    if not os.path.isdir(root):
        return

    stack = [root]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                        elif entry.is_file(follow_symlinks=False) and _is_allowed_archive_file(entry.path):
                            yield entry.path, entry.stat(follow_symlinks=False)
                    except OSError:
                        continue
        except OSError:
            continue


def _build_archive_summary():
    total_size = 0
    count = 0
    min_mtime = None
    max_mtime = None

    for _path, stat_info in _iter_archive_files() or []:
        count += 1
        total_size += stat_info.st_size
        mtime = datetime.fromtimestamp(stat_info.st_mtime, tz=timezone.utc)
        min_mtime = mtime if min_mtime is None or mtime < min_mtime else min_mtime
        max_mtime = mtime if max_mtime is None or mtime > max_mtime else max_mtime

    disk_total = None
    disk_used = None
    disk_free = None
    try:
        usage_target = _archive_root()
        if not os.path.exists(usage_target):
            usage_target = current_app.static_folder
        disk_usage = shutil.disk_usage(usage_target)
        disk_total = disk_usage.total
        disk_used = disk_usage.used
        disk_free = disk_usage.free
    except OSError:
        pass

    return {
        'file_count': count,
        'total_size': total_size,
        'total_size_mb': round(total_size / (1024 * 1024), 2),
        'disk_total': disk_total,
        'disk_used': disk_used,
        'disk_free': disk_free,
        'disk_total_gb': round(disk_total / (1024 * 1024 * 1024), 2) if disk_total is not None else None,
        'disk_free_gb': round(disk_free / (1024 * 1024 * 1024), 2) if disk_free is not None else None,
        'oldest_mtime': min_mtime.isoformat() if min_mtime else None,
        'newest_mtime': max_mtime.isoformat() if max_mtime else None,
    }


def _manifest_meta(manifest_id):
    return {
        'manifest_id': manifest_id,
        'created_at': _utc_now().isoformat(),
        'admin_id': getattr(current_user, 'id', None),
        'admin_username': getattr(current_user, 'username', None),
        'archive_root': 'app/static/arsiv',
        'extensions': sorted(ALLOWED_EXTENSIONS),
    }


def _save_manifest_cache(manifest):
    _cleanup_old_manifests()
    manifest_path = _manifest_cache_path(manifest.get('manifest_id'))
    if not manifest_path:
        raise ValueError('Gecersiz manifest id.')
    with open(manifest_path, 'w', encoding='utf-8') as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)


def _load_manifest(manifest_id=None, manifest_payload=None):
    uploaded_manifest = request.files.get('manifest') if request.files else None
    if uploaded_manifest:
        return json.load(uploaded_manifest.stream)

    if manifest_payload:
        if isinstance(manifest_payload, str):
            return json.loads(manifest_payload)
        if isinstance(manifest_payload, dict):
            return manifest_payload

    manifest_id = manifest_id or request.cookies.get('belge_arsiv_manifest_id')
    manifest_path = _manifest_cache_path(manifest_id)
    if manifest_path and os.path.exists(manifest_path):
        with open(manifest_path, 'r', encoding='utf-8') as handle:
            return json.load(handle)

    return _load_latest_user_manifest()


def _load_latest_user_manifest():
    user_id = getattr(current_user, 'id', None)
    latest = None
    latest_mtime = None
    cutoff = _utc_now() - MANIFEST_MAX_AGE

    for entry in os.scandir(_manifest_cache_dir()):
        if not entry.is_file() or not entry.name.endswith('.json'):
            continue
        try:
            mtime = datetime.fromtimestamp(entry.stat().st_mtime, tz=timezone.utc)
            if mtime < cutoff:
                continue
            with open(entry.path, 'r', encoding='utf-8') as handle:
                manifest = json.load(handle)
            if manifest.get('admin_id') != user_id:
                continue
            if latest_mtime is None or mtime > latest_mtime:
                latest = manifest
                latest_mtime = mtime
        except Exception:
            continue

    return latest


def _log_archive_action(action, description, success=True):
    OperationLogService.log(
        module='belge_arsiv',
        action=action,
        user_id=getattr(current_user, 'id', None),
        username=getattr(current_user, 'username', None),
        entity_type='BelgeArsiv',
        description=description,
        success=success,
    )


@db_menu_bp.route('/belge-arsiv-durum', methods=['GET'])
@login_required
@admin_required
def belge_arsiv_durum():
    return jsonify(_build_archive_summary())


@db_menu_bp.route('/belge-arsiv-yedek', methods=['GET'])
@login_required
@admin_required
def belge_arsiv_yedek():
    manifest_id = uuid.uuid4().hex
    timestamp = _utc_now().strftime('%Y%m%d_%H%M%S')
    zip_filename = f'belge_arsiv_yedek_{timestamp}.zip'
    temp_dir = tempfile.mkdtemp(prefix='belge_arsiv_')
    zip_path = os.path.join(temp_dir, zip_filename)

    manifest = _manifest_meta(manifest_id)
    manifest['files'] = []

    try:
        with zipfile.ZipFile(zip_path, 'w', compression=zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
            for path, stat_info in _iter_archive_files() or []:
                rel_path = _safe_rel_path(path)
                file_hash = sha256_file(path)
                manifest['files'].append({
                    'path': rel_path,
                    'size': stat_info.st_size,
                    'mtime': datetime.fromtimestamp(stat_info.st_mtime, tz=timezone.utc).isoformat(),
                    'sha256_hash': file_hash,
                })
                archive.write(path, arcname=rel_path)

            manifest['file_count'] = len(manifest['files'])
            manifest['total_size'] = sum(item['size'] for item in manifest['files'])
            archive.writestr(
                'manifest.json',
                json.dumps(manifest, ensure_ascii=False, indent=2),
            )

        _save_manifest_cache(manifest)
        _log_archive_action(
            'belge_arsiv_yedek',
            f"Belge arsiv yedegi hazirlandi. manifest_id={manifest_id}, dosya={manifest['file_count']}",
            success=True,
        )
    except Exception as exc:
        try:
            if os.path.exists(zip_path):
                os.remove(zip_path)
            os.rmdir(temp_dir)
        except Exception:
            pass
        _log_archive_action('belge_arsiv_yedek_hata', f'Belge arsiv yedegi alinamadi: {exc}', success=False)
        return jsonify({'error': str(exc)}), 500

    @after_this_request
    def _cleanup_temp_zip(response):
        response.set_cookie(
            'belge_arsiv_manifest_id',
            manifest_id,
            max_age=int(MANIFEST_MAX_AGE.total_seconds()),
            samesite='Strict',
        )

        @response.call_on_close
        def _remove_temp_file():
            try:
                if os.path.exists(zip_path):
                    os.remove(zip_path)
                if os.path.isdir(temp_dir):
                    os.rmdir(temp_dir)
            except Exception:
                current_app.logger.warning('Gecici belge arsiv ZIP dosyasi silinemedi: %s', zip_path)

        return response

    return send_file(
        zip_path,
        as_attachment=True,
        download_name=zip_filename,
        mimetype='application/zip',
        max_age=0,
    )


@db_menu_bp.route('/belge-arsiv-sil', methods=['POST'])
@login_required
@admin_required
def belge_arsiv_sil():
    payload = request.get_json(silent=True) or request.form.to_dict()
    dry_run = str(payload.get('dry_run', 'true')).lower() in ('1', 'true', 'yes', 'on')
    manifest = _load_manifest(
        manifest_id=payload.get('manifest_id'),
        manifest_payload=payload.get('manifest'),
    )

    if not manifest or not manifest.get('files'):
        _log_archive_action('belge_arsiv_sil_reddedildi', 'Manifest bulunamadigi icin silme reddedildi.', success=False)
        return jsonify({'error': 'Gecerli manifest bulunamadi. Once belge arsiv yedegi indirin.'}), 400

    result = {
        'dry_run': dry_run,
        'manifest_id': manifest.get('manifest_id'),
        'deleted': [],
        'skipped': [],
        'changed_hash': [],
        'missing': [],
        'errors': [],
    }

    for item in manifest.get('files', []):
        rel_path = item.get('path')
        expected_hash = item.get('sha256_hash')
        abs_path = _path_from_manifest_rel(rel_path)

        if not abs_path:
            result['errors'].append({'path': rel_path, 'error': 'Gecersiz veya arsiv disi yol.'})
            continue

        if not os.path.exists(abs_path):
            result['missing'].append({'path': rel_path})
            continue

        try:
            current_hash = sha256_file(abs_path)
            if not expected_hash or current_hash != expected_hash:
                result['changed_hash'].append({
                    'path': rel_path,
                    'expected': expected_hash,
                    'actual': current_hash,
                })
                continue

            if dry_run:
                result['skipped'].append({'path': rel_path, 'reason': 'dry_run'})
            else:
                os.remove(abs_path)
                result['deleted'].append({'path': rel_path})
        except Exception as exc:
            result['errors'].append({'path': rel_path, 'error': str(exc)})
            continue

    success = not result['errors'] and not result['changed_hash']
    _log_archive_action(
        'belge_arsiv_sil_onizleme' if dry_run else 'belge_arsiv_sil',
        (
            f"manifest_id={result['manifest_id']}, dry_run={dry_run}, "
            f"deleted={len(result['deleted'])}, skipped={len(result['skipped'])}, "
            f"changed_hash={len(result['changed_hash'])}, missing={len(result['missing'])}, "
            f"errors={len(result['errors'])}"
        ),
        success=success,
    )
    return jsonify(result)
