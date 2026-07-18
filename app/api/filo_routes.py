"""Filo REST API — liste ve detay."""

from sqlalchemy import or_

from flask import request

from app.api import api_bp
from app.api.auth import token_required
from app.api.routes import fail, ok
from app.filo.models import Ekipman
from app.kiralama.models import Kiralama, KiralamaKalemi
from app.utils import tr_ilike


def _equipment_summary(ekipman):
    return {
        'id': ekipman.id,
        'code': ekipman.kod,
        'type': ekipman.tipi,
        'brand': ekipman.marka,
        'model': ekipman.model,
        'serial_no': ekipman.seri_no,
        'fuel': ekipman.yakit,
        'working_height': ekipman.calisma_yuksekligi,
        'lift_capacity': ekipman.kaldirma_kapasitesi,
        'production_year': ekipman.uretim_yili,
        'status': ekipman.calisma_durumu,
        'branch_id': ekipman.sube_id,
        'branch_name': ekipman.sube.isim if getattr(ekipman, 'sube', None) else None,
        'is_active': bool(ekipman.is_active),
        'is_external': ekipman.firma_tedarikci_id is not None,
        'supplier_id': ekipman.firma_tedarikci_id,
    }


def _equipment_detail(ekipman):
    payload = _equipment_summary(ekipman)
    active_lines = [
        k for k in (ekipman.kiralama_kalemleri or [])
        if not k.is_deleted and k.is_active and not k.sonlandirildi
    ]
    active = max(active_lines, key=lambda k: k.id) if active_lines else None
    payload.update({
        'weight': ekipman.agirlik,
        'indoor_suitable': ekipman.ic_mekan_uygun,
        'offroad_suitable': ekipman.arazi_tipi_uygun,
        'width': ekipman.genislik,
        'length': ekipman.uzunluk,
        'closed_height': ekipman.kapali_yukseklik,
        'entry_date': ekipman.filoya_giris_tarihi,
        'entry_cost': ekipman.giris_maliyeti,
        'currency': ekipman.para_birimi,
        'active_rental': {
            'line_id': active.id,
            'rental_id': active.kiralama_id,
            'form_no': active.kiralama.kiralama_form_no if active.kiralama else None,
            'customer_name': (
                active.kiralama.firma_musteri.firma_adi
                if active.kiralama and active.kiralama.firma_musteri
                else None
            ),
            'start_date': active.kiralama_baslangici,
            'end_date': active.kiralama_bitis,
        } if active else None,
        'rental_history_count': len([
            k for k in (ekipman.kiralama_kalemleri or []) if not k.is_deleted
        ]),
    })
    return payload


def _base_fleet_query(scope='owned', include_archived=False):
    query = Ekipman.query.filter(Ekipman.is_deleted.is_(False))
    scope = (scope or 'owned').strip().lower()

    if scope == 'external':
        return query.filter(
            Ekipman.firma_tedarikci_id.isnot(None),
            Ekipman.is_active.is_(True),
        )
    if scope == 'all':
        if include_archived:
            query = query.filter(Ekipman.is_active.is_(False))
        else:
            query = query.filter(Ekipman.is_active.is_(True))
        return query

    query = query.filter(Ekipman.firma_tedarikci_id.is_(None))
    if include_archived:
        query = query.filter(Ekipman.is_active.is_(False))
    else:
        query = query.filter(Ekipman.is_active.is_(True))
    return query


def _apply_filo_filters(query, search, sube_id, status, tip):
    if search:
        query = query.filter(or_(
            tr_ilike(Ekipman.kod, f'%{search}%'),
            tr_ilike(Ekipman.tipi, f'%{search}%'),
            tr_ilike(Ekipman.marka, f'%{search}%'),
            Ekipman.seri_no.ilike(f'%{search}%'),
        ))
    if sube_id:
        query = query.filter(Ekipman.sube_id == sube_id)
    if status:
        query = query.filter(Ekipman.calisma_durumu == status)
    if tip:
        query = query.filter(Ekipman.tipi == tip)
    return query


@api_bp.route('/filo', methods=['GET'])
@token_required
def filo_list():
    page = max(request.args.get('page', default=1, type=int), 1)
    per_page = min(max(request.args.get('per_page', default=25, type=int), 1), 100)
    search = (request.args.get('q') or '').strip()
    include_archived = request.args.get('archived', default='0') == '1'
    scope = (request.args.get('scope') or 'owned').strip().lower()
    sube_id = request.args.get('sube_id', type=int)
    status = (request.args.get('status') or '').strip()
    tip = (request.args.get('tip') or request.args.get('type') or '').strip()

    from sqlalchemy.orm import joinedload
    query = _base_fleet_query(scope=scope, include_archived=include_archived).options(
        joinedload(Ekipman.sube)
    )
    query = _apply_filo_filters(query, search, sube_id, status, tip)

    pagination = query.order_by(Ekipman.kod.asc()).paginate(
        page=page,
        per_page=per_page,
        error_out=False,
    )
    return ok({
        'items': [_equipment_summary(item) for item in pagination.items],
        'page': pagination.page,
        'per_page': pagination.per_page,
        'total': pagination.total,
        'pages': pagination.pages,
        'scope': scope,
    })


@api_bp.route('/filo/harici', methods=['GET'])
@token_required
def filo_harici_list():
    """Harici (tedarikci) ekipman listesi — web /filo/harici ile ayni kapsam."""
    page = max(request.args.get('page', default=1, type=int), 1)
    per_page = min(max(request.args.get('per_page', default=25, type=int), 1), 100)
    search = (request.args.get('q') or '').strip()
    sube_id = request.args.get('sube_id', type=int)
    status = (request.args.get('status') or '').strip()
    tip = (request.args.get('tip') or request.args.get('type') or '').strip()

    from sqlalchemy.orm import joinedload
    query = _base_fleet_query(scope='external').options(joinedload(Ekipman.sube))
    query = _apply_filo_filters(query, search, sube_id, status, tip)

    pagination = query.order_by(Ekipman.kod.asc()).paginate(
        page=page,
        per_page=per_page,
        error_out=False,
    )
    return ok({
        'items': [_equipment_summary(item) for item in pagination.items],
        'page': pagination.page,
        'per_page': pagination.per_page,
        'total': pagination.total,
        'pages': pagination.pages,
        'scope': 'external',
    })


@api_bp.route('/filo/<int:equipment_id>', methods=['GET'])
@token_required
def filo_detail(equipment_id):
    from sqlalchemy.orm import joinedload, subqueryload
    ekipman = Ekipman.query.filter(
        Ekipman.id == equipment_id,
        Ekipman.is_deleted.is_(False),
    ).options(
        joinedload(Ekipman.sube),
        subqueryload(Ekipman.kiralama_kalemleri).joinedload(KiralamaKalemi.kiralama).joinedload(
            Kiralama.firma_musteri
        ),
    ).first()
    if not ekipman:
        return fail('Ekipman bulunamadi.', 404)
    return ok(_equipment_detail(ekipman))
