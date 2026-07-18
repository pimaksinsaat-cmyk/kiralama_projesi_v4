from datetime import datetime, timezone
from io import BytesIO

from flask import flash, redirect, send_file, url_for
from flask_login import current_user, login_required

from app.db_menu import db_menu_bp
from app.services.backup_service import list_backups, sql_dump
from app.utils import admin_required


@db_menu_bp.app_context_processor
def inject_admin_db_backup_info():
    if not current_user.is_authenticated:
        return {}
    try:
        if not current_user.is_admin():
            return {}
    except Exception:
        return {}
    return {'db_yedek_listesi': list_backups()}


@db_menu_bp.route('/yedek-sql', methods=['GET'])
@login_required
@admin_required
def db_yedek_sql():
    try:
        data = sql_dump()
    except Exception as exc:
        flash(f'Veritabani yedegi alinirken hata olustu: {exc}', 'danger')
        return redirect(url_for('main.index'))

    filename = f"db_yedek_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.sql"
    return send_file(
        BytesIO(data),
        as_attachment=True,
        download_name=filename,
        mimetype='text/plain',
    )
