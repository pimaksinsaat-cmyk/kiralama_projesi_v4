"""Firma REST API — liste, detay, olusturma, guncelleme."""

from decimal import Decimal

from flask import g, request

from app.api import api_bp
from app.api.auth import token_required
from app.api.routes import fail, ok
from app.extensions import db
from app.firmalar.models import Firma
from app.services.base import ValidationError
from app.services.firma_services import FirmaService


def _firma_summary(firma):
    return {
        'id': firma.id,
        'name': firma.firma_adi,
        'contact_person': firma.yetkili_adi,
        'phone': firma.telefon,
        'email': firma.eposta,
        'tax_office': firma.vergi_dairesi,
        'tax_no': firma.vergi_no,
        'is_customer': bool(firma.is_musteri),
        'is_supplier': bool(firma.is_tedarikci),
        'balance': firma.bakiye,
        'is_active': bool(firma.is_active),
        'contract_no': firma.sozlesme_no,
        'address': firma.iletisim_bilgileri,
    }


def _firma_detail(firma):
    payload = _firma_summary(firma)
    payload.update({
        'contract_rev_no': firma.sozlesme_rev_no,
        'contract_date': firma.sozlesme_tarihi,
        'city': firma.il,
        'district': firma.ilce,
        'country': firma.ulke,
        'balance_vat_included': firma.cari_bakiye_kdvli,
        'is_efatura': bool(firma.is_efatura_mukellefi),
    })
    return payload


def _body_to_firma_data(body, existing=None):
    data = {}
    mapping = {
        'name': 'firma_adi',
        'firma_adi': 'firma_adi',
        'contact_person': 'yetkili_adi',
        'yetkili_adi': 'yetkili_adi',
        'phone': 'telefon',
        'telefon': 'telefon',
        'email': 'eposta',
        'eposta': 'eposta',
        'address': 'iletisim_bilgileri',
        'iletisim_bilgileri': 'iletisim_bilgileri',
        'tax_office': 'vergi_dairesi',
        'vergi_dairesi': 'vergi_dairesi',
        'tax_no': 'vergi_no',
        'vergi_no': 'vergi_no',
        'is_customer': 'is_musteri',
        'is_musteri': 'is_musteri',
        'is_supplier': 'is_tedarikci',
        'is_tedarikci': 'is_tedarikci',
    }
    for api_key, model_key in mapping.items():
        if api_key in body and body[api_key] is not None:
            data[model_key] = body[api_key]
    if existing is None:
        for required in ('firma_adi', 'yetkili_adi', 'iletisim_bilgileri', 'vergi_dairesi', 'vergi_no'):
            if required not in data or not str(data[required]).strip():
                raise ValidationError(f'{required} alani zorunludur.')
        data.setdefault('is_musteri', True)
        data.setdefault('is_tedarikci', False)
        data.setdefault('bakiye', Decimal('0'))
    return data


@api_bp.route('/firmalar', methods=['GET'])
@token_required
def firma_list():
    page = max(request.args.get('page', default=1, type=int), 1)
    per_page = min(max(request.args.get('per_page', default=25, type=int), 1), 100)
    search = (request.args.get('q') or '').strip()
    active_only = request.args.get('active', default='1') != '0'
    role = (request.args.get('role') or '').strip().lower()

    if active_only:
        query = FirmaService.get_active_firms(search_query=search)
    else:
        query = FirmaService.get_inactive_firms(search_query=search)

    if role == 'customer':
        query = query.filter(Firma.is_musteri.is_(True))
    elif role == 'supplier':
        query = query.filter(Firma.is_tedarikci.is_(True))

    pagination = query.order_by(Firma.firma_adi.asc(), Firma.id.desc()).paginate(
        page=page,
        per_page=per_page,
        error_out=False,
    )
    return ok({
        'items': [_firma_summary(item) for item in pagination.items],
        'page': pagination.page,
        'per_page': pagination.per_page,
        'total': pagination.total,
        'pages': pagination.pages,
    })


@api_bp.route('/firmalar/<int:firma_id>', methods=['GET'])
@token_required
def firma_detail(firma_id):
    firma = Firma.query.filter(Firma.id == firma_id).first()
    if not firma or firma.is_deleted:
        return fail('Firma bulunamadi.', 404)
    return ok(_firma_detail(firma))


@api_bp.route('/firmalar', methods=['POST'])
@token_required
def firma_create():
    body = request.get_json(silent=True) or {}
    try:
        data = _body_to_firma_data(body)
        firma = Firma(**data)
        FirmaService.save(firma, actor_id=getattr(g.api_user, 'id', None))
        return ok(_firma_detail(firma), 201)
    except ValidationError as exc:
        return fail(str(exc), 400)


@api_bp.route('/firmalar/<int:firma_id>', methods=['PUT'])
@token_required
def firma_update(firma_id):
    firma = Firma.query.filter(Firma.id == firma_id, Firma.is_deleted.is_(False)).first()
    if not firma:
        return fail('Firma bulunamadi.', 404)
    body = request.get_json(silent=True) or {}
    try:
        data = _body_to_firma_data(body, existing=firma)
        for key, value in data.items():
            if key in FirmaService.updatable_fields:
                setattr(firma, key, value)
        FirmaService.save(firma, is_new=False, actor_id=getattr(g.api_user, 'id', None))
        return ok(_firma_detail(firma))
    except ValidationError as exc:
        return fail(str(exc), 400)


@api_bp.route('/firmalar/<int:firma_id>/deactivate', methods=['POST'])
@token_required
def firma_deactivate(firma_id):
    firma = Firma.query.filter(Firma.id == firma_id, Firma.is_deleted.is_(False)).first()
    if not firma:
        return fail('Firma bulunamadi.', 404)
    firma.is_active = False
    db.session.add(firma)
    db.session.commit()
    return ok(_firma_summary(firma))


@api_bp.route('/firmalar/<int:firma_id>/activate', methods=['POST'])
@token_required
def firma_activate(firma_id):
    firma = Firma.query.filter(Firma.id == firma_id).first()
    if not firma or firma.is_deleted:
        return fail('Firma bulunamadi.', 404)
    firma.is_active = True
    db.session.add(firma)
    db.session.commit()
    return ok(_firma_summary(firma))
