import os
from uuid import uuid4

from flask import current_app, flash, redirect, render_template, url_for
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename

from app import db
from app.ayarlar import ayarlar_bp
from app.ayarlar.forms import AppSettingsForm
from app.ayarlar.models import AppSettings
from app.utils import admin_required, normalize_turkish_upper

_PLACEHOLDER_LOGO = 'img/placeholder.svg'


def _resolve_navbar_logo_path(settings):
    """DB'deki logo yolu diskte yoksa (gitignore/uploads, yeni konteyner) yerel placeholder."""
    if not settings or not getattr(settings, 'logo_path', None):
        return _PLACEHOLDER_LOGO
    rel = str(settings.logo_path).replace('\\', '/').strip()
    if not rel or rel.startswith('/') or '..' in rel.split('/'):
        return _PLACEHOLDER_LOGO
    abs_path = os.path.join(current_app.static_folder, *rel.split('/'))
    real_static = os.path.realpath(current_app.static_folder)
    try:
        real_file = os.path.realpath(abs_path)
    except OSError:
        return _PLACEHOLDER_LOGO
    if not real_file.startswith(real_static) or not os.path.isfile(real_file):
        return _PLACEHOLDER_LOGO
    return rel


def _save_logo(file_storage):
    extension = os.path.splitext(file_storage.filename or '')[1].lower()
    filename = secure_filename(f'company_logo_{uuid4().hex}{extension}')
    relative_path = os.path.join('uploads', 'settings', filename).replace('\\', '/')
    absolute_path = os.path.join(current_app.static_folder, relative_path)
    os.makedirs(os.path.dirname(absolute_path), exist_ok=True)
    file_storage.save(absolute_path)
    return relative_path


def _apply_uppercase_to_settings(settings, form):
    """Metin alanlarını büyük harf yaparak ayarlara uygula (email ve web sitesi hariç)."""
    uppercase_fields = {
        'company_name': form.company_name.data,
        'company_short_name': form.company_short_name.data,
        'company_address': form.company_address.data,
        'company_phone': form.company_phone.data,
        'invoice_title': form.invoice_title.data,
        'invoice_address': form.invoice_address.data,
        'invoice_tax_office': form.invoice_tax_office.data,
        'invoice_tax_number': form.invoice_tax_number.data,
        'invoice_mersis_no': form.invoice_mersis_no.data,
        'invoice_iban': form.invoice_iban.data,
        'invoice_notes': form.invoice_notes.data,
        'kiralama_form_prefix': form.kiralama_form_prefix.data,
        'genel_sozlesme_prefix': form.genel_sozlesme_prefix.data,
    }
    
    for field_name, field_value in uppercase_fields.items():
        if field_value and isinstance(field_value, str):
            setattr(settings, field_name, normalize_turkish_upper(field_value))
        else:
            setattr(settings, field_name, field_value)
    
    # Email ve web sitesini küçük harf yap (standart format)
    if form.company_email.data:
        settings.company_email = form.company_email.data.lower()
    if form.company_website.data:
        settings.company_website = form.company_website.data.lower()


@ayarlar_bp.app_context_processor
def inject_system_settings():
    settings = AppSettings.get_current()
    return {
        'system_settings': settings,
        'navbar_logo_filename': _resolve_navbar_logo_path(settings),
    }


@ayarlar_bp.route('/', methods=['GET', 'POST'])
@login_required
@admin_required
def index():
    settings = AppSettings.get_current() or AppSettings()
    form = AppSettingsForm(obj=settings)

    if form.validate_on_submit():
        # Metin alanlarını büyük harf yaparak ayarlara uygula
        _apply_uppercase_to_settings(settings, form)
        
        # Logo yüklendiyse kayıt et
        if form.logo_file.data:
            settings.logo_path = _save_logo(form.logo_file.data)
        
        # Sayısal alanları ekle
        settings.kiralama_form_start_no = form.kiralama_form_start_no.data
        settings.genel_sozlesme_start_no = form.genel_sozlesme_start_no.data

        db.session.add(settings)
        db.session.commit()
        flash('Genel ayarlar güncellendi.', 'success')
        return redirect(url_for('ayarlar.index'))

    return render_template('ayarlar/index.html', form=form, settings=settings)