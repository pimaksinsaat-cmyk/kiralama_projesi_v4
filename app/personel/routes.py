from datetime import date, timedelta
from uuid import uuid4

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user
from app.personel import personel_bp
from app.personel.forms import IZIN_TURLERI, MESLEK_SECENEKLERI, PersonelForm, PersonelIzinForm
from app.services.base import ValidationError
from app.services.personel_services import PersonelIzinService, PersonelService
from app.subeler.models import Sube


def _active_subeler():
    return Sube.query.filter_by(is_active=True).order_by(Sube.isim).all()


def _set_sube_choices(form):
    form.sube_id.choices = [(-1, 'Sube seciniz')] + [
        (sube.id, sube.isim) for sube in _active_subeler()
    ] + [(0, 'Sube secmeden devam et')]


def _set_meslek_choices(form, current_value=None):
    form.meslek.choices = list(MESLEK_SECENEKLERI)


def _set_meslek_form_data(form, current_value=None):
    current_value = (current_value or '').strip()
    standart_degerler = {value for value, _label in MESLEK_SECENEKLERI if value and value != 'Diger'}

    if current_value and current_value not in standart_degerler:
        form.meslek.data = 'Diger'
        form.meslek_diger.data = current_value
        return

    form.meslek.data = current_value
    form.meslek_diger.data = ''


def _resolve_meslek_value(form):
    selected_value = (form.meslek.data or '').strip()
    if selected_value == 'Diger':
        return (form.meslek_diger.data or '').strip()
    return selected_value or None


def _normalize_sube_filter(value):
    return value if value and value > 0 else None


def _flash_form_errors(form):
    for field_name, errors in form.errors.items():
        field = getattr(form, field_name, None)
        field_label = field.label.text if field is not None else field_name
        for error in errors:
            flash(f'{field_label}: {error}', 'warning')


def _set_submission_token(form):
    form.submission_token.data = uuid4().hex


def _redirect_to_index(selected_sube_id=None):
    selected_sube_id = _normalize_sube_filter(selected_sube_id)
    if selected_sube_id:
        return redirect(url_for('personel.index', sube_id=selected_sube_id))
    return redirect(url_for('personel.index'))


@personel_bp.route('/')
def index():
    selected_sube_id = _normalize_sube_filter(request.args.get('sube_id', type=int))
    q = (request.args.get('q') or '').strip()
    durum = (request.args.get('durum') or 'tum').strip().lower()
    if durum not in {'tum', 'izinli', 'calismada'}:
        durum = 'tum'

    form = PersonelForm()
    _set_sube_choices(form)
    _set_meslek_choices(form)
    form.sube_id.data = selected_sube_id if selected_sube_id else -1
    form.maas_gecerlilik_tarihi.data = date.today().strftime('%Y-%m-%d')
    _set_submission_token(form)

    if not PersonelService.table_exists():
        flash('Personel tablosu veritabaninda henuz olusturulmamis. Personel yonetimi su an devre disidir.', 'warning')
        personeller = []
        toplam_personel = 0
        aktif_personel = 0
        izinli_personel = 0
        calismada_personel = 0
    else:
        tum_personeller = PersonelService.list_personel(sube_id=selected_sube_id, search_query=q)
        enriched_personeller = PersonelService.enrich_personel_list(tum_personeller)
        personeller = PersonelService.filter_by_durum(enriched_personeller, durum=durum)
        toplam_personel = len(personeller)
        aktif_personel = sum(1 for personel in personeller if not personel.is_ayrildi)
        izinli_personel = sum(1 for personel in personeller if personel.is_izinli)
        calismada_personel = sum(1 for personel in personeller if personel.is_calisiyor)

    selected_sube = Sube.query.get(selected_sube_id) if selected_sube_id else None
    izin_default_baslangic = date.today()
    izin_default_bitis = izin_default_baslangic + timedelta(days=7)

    return render_template(
        'personel/index.html',
        form=form,
        izin_turleri=IZIN_TURLERI,
        personeller=personeller,
        subeler=_active_subeler(),
        q=q,
        durum=durum,
        selected_sube_id=selected_sube_id or 0,
        selected_sube=selected_sube,
        izin_default_baslangic=izin_default_baslangic.strftime('%Y-%m-%d'),
        izin_default_bitis=izin_default_bitis.strftime('%Y-%m-%d'),
        toplam_personel=toplam_personel,
        aktif_personel=aktif_personel,
        izinli_personel=izinli_personel,
        calismada_personel=calismada_personel,
    )


@personel_bp.route('/ekle', methods=['POST'])
def ekle():
    if not PersonelService.table_exists():
        flash('Personel tablosu veritabaninda henuz olusturulmamis. Ekleme islemi yapilamiyor.', 'warning')
        return _redirect_to_index(request.form.get('redirect_sube_id', type=int))

    form = PersonelForm()
    _set_sube_choices(form)
    _set_meslek_choices(form)

    if not form.validate_on_submit():
        _flash_form_errors(form)
        return _redirect_to_index(request.form.get('redirect_sube_id', type=int))

    try:
        yeni_personel = PersonelService.create_personel(
            {
                'submission_token': form.submission_token.data,
                'sube_id': _normalize_sube_filter(form.sube_id.data),
                'ad': form.ad.data,
                'soyad': form.soyad.data,
                'tc_no': form.tc_no.data,
                'telefon': form.telefon.data,
                'meslek': _resolve_meslek_value(form),
                'maas': form.maas.data,
                'yemek_ucreti': form.yemek_ucreti.data,
                'yol_ucreti': form.yol_ucreti.data,
                'ise_giris_tarihi': form.ise_giris_tarihi.data,
                'isten_cikis_tarihi': None,
            },
            actor_id=getattr(current_user, 'id', None),
        )
        flash(f'{yeni_personel.tam_ad} basariyla eklendi.', 'success')
    except ValidationError as exc:
        flash(str(exc), 'warning')
    except Exception as exc:
        flash(f'Personel eklenirken hata olustu: {exc}', 'danger')

    return _redirect_to_index(request.form.get('redirect_sube_id', type=int))


@personel_bp.route('/duzenle/<int:personel_id>', methods=['GET', 'POST'])
def duzenle(personel_id):
    if not PersonelService.table_exists():
        flash('Personel tablosu devre disidir.', 'warning')
        return _redirect_to_index(request.args.get('sube_id', type=int))

    personel = PersonelService.get_by_id(personel_id)
    if not personel:
        flash('Personel kaydi bulunamadi.', 'warning')
        return _redirect_to_index(request.args.get('sube_id', type=int))

    selected_sube_id = request.values.get('redirect_sube_id', type=int)
    if selected_sube_id is None:
        selected_sube_id = request.args.get('sube_id', type=int)

    form = PersonelForm()
    _set_sube_choices(form)
    _set_meslek_choices(form, current_value=personel.meslek)
    if not form.submission_token.data:
        _set_submission_token(form)
    maas_donemleri = PersonelService.get_salary_periods(personel)
    aktif_maas_donemi = PersonelService.get_current_salary_period(personel)

    if request.method == 'POST':
        if not form.validate_on_submit():
            _flash_form_errors(form)
        else:
            try:
                personel = PersonelService.update_personel(
                    personel.id,
                    {
                        'sube_id': _normalize_sube_filter(form.sube_id.data),
                        'ad': form.ad.data,
                        'soyad': form.soyad.data,
                        'tc_no': form.tc_no.data,
                        'telefon': form.telefon.data,
                        'meslek': _resolve_meslek_value(form),
                        'maas': form.maas.data,
                        'yemek_ucreti': form.yemek_ucreti.data,
                        'yol_ucreti': form.yol_ucreti.data,
                        'maas_gecerlilik_tarihi': form.maas_gecerlilik_tarihi.data,
                        'ise_giris_tarihi': form.ise_giris_tarihi.data,
                        'isten_cikis_tarihi': form.isten_cikis_tarihi.data,
                    },
                    actor_id=getattr(current_user, 'id', None),
                )
                flash(f'{personel.tam_ad} basariyla guncellendi.', 'success')
                return _redirect_to_index(selected_sube_id)
            except ValidationError as exc:
                flash(str(exc), 'warning')
            except Exception as exc:
                flash(f'Guncelleme sirasinda hata olustu: {exc}', 'danger')
    else:
        form.sube_id.data = personel.sube_id if personel.sube_id else -1
        form.ad.data = personel.ad
        form.soyad.data = personel.soyad
        form.tc_no.data = personel.tc_no
        form.telefon.data = personel.telefon
        _set_meslek_form_data(form, current_value=personel.meslek)
        form.maas.data = personel.maas
        form.yemek_ucreti.data = personel.yemek_ucreti
        form.yol_ucreti.data = personel.yol_ucreti
        form.maas_gecerlilik_tarihi.data = date.today().strftime('%Y-%m-%d')
        form.ise_giris_tarihi.data = personel.ise_giris_tarihi.strftime('%Y-%m-%d') if personel.ise_giris_tarihi else ''
        form.isten_cikis_tarihi.data = personel.isten_cikis_tarihi.strftime('%Y-%m-%d') if personel.isten_cikis_tarihi else ''

    return render_template(
        'personel/duzenle.html',
        form=form,
        personel=personel,
        maas_donemleri=maas_donemleri,
        aktif_maas_donemi=aktif_maas_donemi,
        selected_sube_id=_normalize_sube_filter(selected_sube_id) or 0,
    )


@personel_bp.route('/sil/<int:personel_id>', methods=['POST'])
def sil(personel_id):
    if not PersonelService.table_exists():
        flash('Personel tablosu devre disidir.', 'warning')
        return _redirect_to_index(request.form.get('redirect_sube_id', type=int))

    try:
        personel = PersonelService.get_by_id(personel_id)
        if not personel:
            raise ValidationError('Personel kaydi bulunamadi.')
        PersonelService.delete_personel(personel_id, actor_id=getattr(current_user, 'id', None))
        flash(f'{personel.tam_ad} basariyla silindi.', 'success')
    except ValidationError as exc:
        flash(str(exc), 'warning')
    except Exception as exc:
        flash(f'Silme sirasinda hata olustu: {exc}', 'danger')

    return _redirect_to_index(request.form.get('redirect_sube_id', type=int))


@personel_bp.route('/<int:personel_id>/izin/ekle', methods=['POST'])
def izin_ekle(personel_id):
    if not PersonelIzinService.table_exists():
        flash('Personel tablosu devre disidir.', 'warning')
        return _redirect_to_index(request.form.get('redirect_sube_id', type=int))

    form = PersonelIzinForm()

    if not form.validate_on_submit():
        _flash_form_errors(form)
        return _redirect_to_index(request.form.get('redirect_sube_id', type=int))

    try:
        personel = PersonelService.get_by_id(personel_id)
        if not personel:
            raise ValidationError('Personel bulunamadi.')
        PersonelIzinService.create_izin(
            personel_id,
            {
                'izin_turu': form.izin_turu.data,
                'baslangic_tarihi': form.baslangic_tarihi.data,
                'bitis_tarihi': form.bitis_tarihi.data,
                'gun_sayisi': form.gun_sayisi.data,
                'aciklama': form.aciklama.data,
            },
            actor_id=getattr(current_user, 'id', None),
        )
        flash(f'{personel.tam_ad} icin izin kaydi eklendi.', 'success')
    except ValidationError as exc:
        flash(str(exc), 'warning')
    except Exception as exc:
        flash(f'Izin eklenirken hata olustu: {exc}', 'danger')

    return _redirect_to_index(request.form.get('redirect_sube_id', type=int))


@personel_bp.route('/izin/<int:izin_id>/sil', methods=['POST'])
def izin_sil(izin_id):
    if not PersonelIzinService.table_exists():
        flash('Personel tablosu devre disidir.', 'warning')
        return _redirect_to_index(request.form.get('redirect_sube_id', type=int))

    try:
        PersonelIzinService.delete_izin(izin_id, actor_id=getattr(current_user, 'id', None))
        flash('Izin kaydi silindi.', 'success')
    except ValidationError as exc:
        flash(str(exc), 'warning')
    except Exception as exc:
        flash(f'Izin silinirken hata olustu: {exc}', 'danger')

    return _redirect_to_index(request.form.get('redirect_sube_id', type=int))