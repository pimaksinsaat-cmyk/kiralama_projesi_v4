from datetime import date, datetime
from decimal import Decimal
from datetime import timedelta

from flask import current_app, g, jsonify, request

from app.api import api_bp
from app.api.auth import (
    bearer_token,
    decode_token,
    issue_token_pair,
    public_token_payload,
    token_required,
)
from app.auth.models import User
from app.auth.session_security import (
    account_is_active,
    clear_active_session,
    has_recent_active_session,
    mark_seen,
    new_session_token,
    utc_now,
)
from app.extensions import db
from app.models.system_state import ApiRefreshRotation
from app.firmalar.models import Firma
from app.api.kiralama_payload import (
    line_payload,
    rental_detail as _rental_detail,
    rental_query_options,
    rental_summary as _rental_summary,
)
from app.kiralama.models import Kiralama
from app.services.raporlama_services import RaporlamaService


def ok(data=None, status=200):
    return jsonify({'ok': True, 'data': _json_safe(data)}), status


def fail(message, status=400):
    return jsonify({'ok': False, 'message': message}), status


def _json_safe(value):
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _user_payload(user):
    return {
        'id': user.id,
        'username': user.username,
        'role': user.rol,
        'is_admin': user.is_admin(),
    }


def _parse_date(value, fallback):
    if not value:
        return fallback
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except ValueError:
        return fallback


@api_bp.route('/auth/login', methods=['POST'])
def login():
    data = request.get_json(silent=True) or {}
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''
    if not username or not password:
        return fail('Kullanici adi ve sifre zorunludur.', 400)

    user = User.query.with_for_update().filter_by(username=username).first()
    if not user or not user.check_password(password):
        return fail('Kullanici adi veya sifre hatali.', 401)
    if not account_is_active(user):
        return fail('Hesabiniz pasif.', 403)

    now = utc_now()
    if has_recent_active_session(user, now=now):
        return fail('Bu kullanici baska bir ekranda aktif.', 409)

    ApiRefreshRotation.query.filter(
        ApiRefreshRotation.grace_expires_at < now
    ).delete(synchronize_session=False)
    session_token = new_session_token()
    user.active_session_token = session_token
    user.active_session_started_at = now
    user.active_session_seen_at = now
    user.last_login = now
    ApiRefreshRotation.query.filter_by(user_id=user.id).delete(synchronize_session=False)
    token_pair = issue_token_pair(user, session_token)
    db.session.commit()
    return ok({
        **public_token_payload(token_pair),
        'user': _user_payload(user),
    })


@api_bp.route('/auth/refresh', methods=['POST'])
def refresh():
    token = bearer_token()
    if not token:
        return fail('Oturum acmaniz gerekiyor.', 401)
    payload, error = decode_token(token, 'refresh')
    if error:
        return fail(error, 401)

    try:
        user_id = int(payload['sub'])
    except (TypeError, ValueError):
        return fail('Gecersiz oturum anahtari.', 401)

    user = User.query.with_for_update().filter_by(id=user_id).first()
    if not user:
        return fail('Kullanici bulunamadi veya pasif.', 401)
    if not account_is_active(user):
        clear_active_session(user)
        ApiRefreshRotation.query.filter_by(user_id=user.id).delete(synchronize_session=False)
        db.session.commit()
        return fail('Kullanici bulunamadi veya pasif.', 401)

    now = utc_now()
    ApiRefreshRotation.query.filter(
        ApiRefreshRotation.grace_expires_at < now
    ).delete(synchronize_session=False)
    rotation = ApiRefreshRotation.query.filter_by(
        user_id=user.id,
        previous_jti=payload.get('jti'),
    ).first()
    if (
        rotation
        and rotation.grace_expires_at >= now
        and user.active_session_token == rotation.successor_session_token
    ):
        token_pair = issue_token_pair(
            user,
            rotation.successor_session_token,
            issued_at=rotation.issued_at,
            access_jti=rotation.access_jti,
            refresh_jti=rotation.refresh_jti,
        )
        return ok(public_token_payload(token_pair))

    if user.active_session_token != payload.get('session_token'):
        return fail('Oturumunuz sonlandi. Lutfen tekrar giris yapin.', 401)

    successor_session_token = new_session_token()
    token_pair = issue_token_pair(user, successor_session_token)
    ApiRefreshRotation.query.filter_by(user_id=user.id).delete(synchronize_session=False)
    db.session.add(ApiRefreshRotation(
        user_id=user.id,
        previous_jti=payload['jti'],
        successor_session_token=successor_session_token,
        access_jti=token_pair['_access_jti'],
        refresh_jti=token_pair['_refresh_jti'],
        issued_at=token_pair['_issued_at'],
        grace_expires_at=now + timedelta(
            seconds=current_app.config['API_REFRESH_GRACE_SECONDS']
        ),
    ))
    user.active_session_token = successor_session_token
    user.active_session_started_at = now
    user.active_session_seen_at = now
    db.session.commit()
    return ok(public_token_payload(token_pair))


@api_bp.route('/auth/logout', methods=['POST'])
@token_required
def logout():
    clear_active_session(g.api_user)
    ApiRefreshRotation.query.filter_by(user_id=g.api_user.id).delete(synchronize_session=False)
    db.session.commit()
    return ok({'logged_out': True})


@api_bp.route('/auth/me', methods=['GET'])
@token_required
def me():
    mark_seen(g.api_user, now=utc_now())
    db.session.commit()
    return ok({'user': _user_payload(g.api_user)})


@api_bp.route('/dashboard', methods=['GET'])
@token_required
def dashboard():
    today = date.today()
    default_start = date(today.year, 1, 1)
    start_date = _parse_date(request.args.get('start_date'), default_start)
    end_date = _parse_date(request.args.get('end_date'), today)
    if start_date > end_date:
        start_date, end_date = end_date, start_date

    data = RaporlamaService.build_dashboard(
        start_date=start_date,
        end_date=end_date,
        sube_id=request.args.get('sube_id', type=int),
        calisma_yuksekligi=request.args.get('calisma_yuksekligi', type=int),
        projection_mode=request.args.get('projection_mode', default='yukseklik', type=str),
        machine_search=(request.args.get('machine_search', default='', type=str) or '').strip(),
        machine_sube_id=request.args.get('machine_sube_id', type=int),
        machine_limit=request.args.get('machine_limit', default=50, type=int),
    )
    data['filters']['start_date'] = start_date
    data['filters']['end_date'] = end_date
    return ok(data)


@api_bp.route('/kiralama', methods=['GET'])
@token_required
def rental_list():
    page = max(request.args.get('page', default=1, type=int), 1)
    per_page = min(max(request.args.get('per_page', default=25, type=int), 1), 100)
    search = (request.args.get('q') or '').strip()

    query = Kiralama.query.options(*rental_query_options()).filter(
        Kiralama.is_deleted.is_(False)
    )

    if search:
        like = f'%{search}%'
        query = query.outerjoin(Kiralama.firma_musteri).filter(
            (Kiralama.kiralama_form_no.ilike(like)) | (Firma.firma_adi.ilike(like))
        )

    pagination = query.order_by(Kiralama.id.desc()).paginate(
        page=page,
        per_page=per_page,
        error_out=False,
    )
    return ok({
        'items': [_rental_summary(item) for item in pagination.items],
        'page': pagination.page,
        'per_page': pagination.per_page,
        'total': pagination.total,
        'pages': pagination.pages,
    })


@api_bp.route('/kiralama/<int:rental_id>', methods=['GET'])
@token_required
def rental_detail(rental_id):
    kiralama = Kiralama.query.options(*rental_query_options()).filter(
        Kiralama.id == rental_id,
        Kiralama.is_deleted.is_(False),
    ).first()
    if not kiralama:
        return fail('Kiralama kaydi bulunamadi.', 404)
    return ok(_rental_detail(kiralama))
