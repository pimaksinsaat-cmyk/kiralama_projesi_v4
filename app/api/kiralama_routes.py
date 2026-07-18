"""Kiralama REST API — CRUD, kalem operasyonlari, lookup."""

from sqlalchemy import func, or_

from flask import g, request

from app.api import api_bp
from app.api.auth import token_required
from app.api.kiralama_payload import (
    header_to_service,
    line_payload,
    lines_to_service,
    rental_detail,
    rental_query_options,
    rental_summary,
)
from app.api.routes import fail, ok
from app.araclar.models import Arac as NakliyeAraci
from app.extensions import db
from app.filo.models import Ekipman
from app.firmalar.models import Firma
from app.kiralama.models import Kiralama, KiralamaKalemi
from app.services.base import ValidationError
from app.services.kiralama_services import KiralamaKalemiService, KiralamaService
from app.subeler.models import Sube
from app.utils import tr_ilike


def _actor_id():
    return getattr(g.api_user, 'id', None)


def _require_active_sube():
    if Sube.query.filter_by(is_active=True).first() is None:
        return fail('Bu islem icin en az bir aktif sube / depo tanimlanmalidir.', 400)
    return None


def _load_rental(rental_id, include_deleted=False):
    query = Kiralama.query.options(*rental_query_options()).filter(Kiralama.id == rental_id)
    if not include_deleted:
        query = query.filter(Kiralama.is_deleted.is_(False))
    return query.first()


def _load_line(line_id):
    from sqlalchemy.orm import joinedload
    return KiralamaKalemi.query.options(
        joinedload(KiralamaKalemi.ekipman),
    ).filter(
        KiralamaKalemi.id == line_id,
        KiralamaKalemi.is_deleted.is_(False),
    ).first()


@api_bp.route('/kiralama/form-meta', methods=['GET'])
@token_required
def rental_form_meta():
    guard = _require_active_sube()
    if guard:
        return guard
    try:
        form_no = KiralamaService.get_next_form_no()
    except Exception:
        form_no = None
    try:
        kurlar = KiralamaService.get_tcmb_kurlari()
        updated_at = KiralamaService.get_kur_son_guncelleme_text()
    except Exception:
        return fail('Kur verisi su anda kullanilamiyor.', 503)
    return ok({
        'form_no': form_no,
        'usd_rate': kurlar.get('USD'),
        'eur_rate': kurlar.get('EUR'),
        'exchange_rates_updated_at': updated_at,
    })


@api_bp.route('/kiralama/deleted', methods=['GET'])
@token_required
def rental_deleted_list():
    page = max(request.args.get('page', default=1, type=int), 1)
    per_page = min(max(request.args.get('per_page', default=25, type=int), 1), 100)
    search = (request.args.get('q') or '').strip()

    query = Kiralama.query.options(*rental_query_options()).filter(
        Kiralama.is_deleted.is_(True)
    )
    if search:
        like = f'%{search}%'
        query = query.outerjoin(Kiralama.firma_musteri).filter(
            (Kiralama.kiralama_form_no.ilike(like)) | (Firma.firma_adi.ilike(like))
        )
    pagination = query.order_by(Kiralama.deleted_at.desc(), Kiralama.id.desc()).paginate(
        page=page,
        per_page=per_page,
        error_out=False,
    )
    return ok({
        'items': [rental_summary(item) for item in pagination.items],
        'page': pagination.page,
        'per_page': pagination.per_page,
        'total': pagination.total,
        'pages': pagination.pages,
    })


@api_bp.route('/kiralama', methods=['POST'])
@token_required
def rental_create():
    guard = _require_active_sube()
    if guard:
        return guard
    body = request.get_json(silent=True) or {}
    try:
        kiralama = KiralamaService.create_kiralama_with_relations(
            header_to_service(body),
            lines_to_service(body),
            actor_id=_actor_id(),
        )
        created = _load_rental(kiralama.id)
        return ok(rental_detail(created), 201)
    except ValidationError as exc:
        return fail(str(exc), 400)
    except ValueError as exc:
        return fail(str(exc), 400)


@api_bp.route('/kiralama/<int:rental_id>', methods=['PUT'])
@token_required
def rental_update(rental_id):
    guard = _require_active_sube()
    if guard:
        return guard
    kiralama = _load_rental(rental_id)
    if not kiralama:
        return fail('Kiralama kaydi bulunamadi.', 404)
    body = request.get_json(silent=True) or {}
    header = header_to_service(body)
    header['kiralama_form_no'] = kiralama.kiralama_form_no
    try:
        KiralamaService.update_kiralama_with_relations(
            rental_id,
            header,
            lines_to_service(body),
            actor_id=_actor_id(),
        )
        updated = _load_rental(rental_id)
        return ok(rental_detail(updated))
    except ValidationError as exc:
        return fail(str(exc), 400)


@api_bp.route('/kiralama/<int:rental_id>', methods=['DELETE'])
@token_required
def rental_delete(rental_id):
    body = request.get_json(silent=True) or {}
    password = body.get('password') or ''
    if not password or not g.api_user.check_password(password):
        return fail('Kiralama silmek icin kullanici sifrenizi dogrulamaniz gerekir.', 400)
    try:
        KiralamaService.delete_with_relations(rental_id, actor_id=_actor_id())
        kiralama = db.session.get(Kiralama, rental_id)
        return ok({
            'id': rental_id,
            'form_no': kiralama.kiralama_form_no if kiralama else '',
            'undo_seconds': KiralamaService.UNDO_WINDOW_SECONDS,
        })
    except ValidationError as exc:
        return fail(str(exc), 400)


@api_bp.route('/kiralama/<int:rental_id>/restore', methods=['POST'])
@token_required
def rental_restore(rental_id):
    try:
        kiralama = KiralamaService.restore_with_relations(
            rental_id,
            actor_id=_actor_id(),
            snapshot=None,
        )
        return ok({
            'id': rental_id,
            'form_no': kiralama.kiralama_form_no,
        })
    except ValidationError as exc:
        return fail(str(exc), 400)


@api_bp.route('/kiralama/<int:rental_id>/restore-archived', methods=['POST'])
@token_required
def rental_restore_archived(rental_id):
    try:
        kiralama = KiralamaService.restore_archived_with_relations(
            rental_id,
            actor_id=_actor_id(),
        )
        return ok({
            'id': rental_id,
            'form_no': kiralama.kiralama_form_no,
        })
    except ValidationError as exc:
        return fail(str(exc), 400)


@api_bp.route('/kiralama/lines/<int:line_id>/terminate', methods=['POST'])
@token_required
def rental_line_terminate(line_id):
    """Kalem sonlandir — donus nakliyesi gidişten bagimsiz."""
    body = request.get_json(silent=True) or {}
    try:
        KiralamaKalemiService.sonlandir(
            line_id,
            body.get('end_date') or body.get('bitis_tarihi'),
            body.get('return_branch_id') or body.get('donus_sube_id'),
            actor_id=_actor_id(),
            is_harici_nakliye=bool(
                body.get('return_is_external_transport')
                if 'return_is_external_transport' in body
                else body.get('is_harici_nakliye', False)
            ),
            nakliye_tedarikci_id=body.get('return_transport_supplier_id')
            or body.get('nakliye_tedarikci_id'),
            nakliye_araci_id=body.get('return_transport_vehicle_id')
            or body.get('nakliye_araci_id'),
            nakliye_alis_fiyat=body.get('return_transport_purchase_price')
            or body.get('nakliye_alis_fiyat'),
            donus_nakliye_alis_kdv=body.get('return_transport_purchase_vat_rate')
            or body.get('donus_nakliye_alis_kdv'),
            donus_nakliye_satis_fiyat=body.get('return_transport_sale_price')
            or body.get('donus_nakliye_satis_fiyat'),
        )
        kalem = _load_line(line_id)
        return ok(line_payload(kalem) if kalem else {'id': line_id})
    except ValidationError as exc:
        return fail(str(exc), 400)


@api_bp.route('/kiralama/lines/<int:line_id>/update-end-date', methods=['POST'])
@token_required
def rental_line_update_end_date(line_id):
    body = request.get_json(silent=True) or {}
    new_end = body.get('end_date') or body.get('yeni_bitis_tarihi')
    if not new_end:
        return fail('Bitis tarihi zorunludur.', 400)
    kalem = _load_line(line_id)
    if not kalem:
        return fail('Kalem bulunamadi.', 404)
    if kalem.sonlandirildi or not kalem.is_active:
        return fail('Sadece aktif ve sonlandirilmamis kalemler guncellenebilir.', 400)
    try:
        from app.services.kiralama_services import to_date
        yeni_bitis = to_date(new_end)
        if not yeni_bitis:
            return fail('Gecersiz tarih formati.', 400)
        bas = to_date(kalem.kiralama_baslangici)
        if bas and yeni_bitis < bas:
            return fail('Bitis tarihi baslangictan once olamaz.', 400)
        KiralamaKalemiService.validate_tarih_guncelle_koruma(kalem, yeni_bitis)
        kalem.kiralama_bitis = yeni_bitis
        db.session.add(kalem)
        db.session.commit()
        return ok(line_payload(kalem))
    except ValidationError as exc:
        db.session.rollback()
        return fail(str(exc), 400)


@api_bp.route('/kiralama/lines/<int:line_id>/cancel-termination', methods=['POST'])
@token_required
def rental_line_cancel_termination(line_id):
    try:
        KiralamaKalemiService.iptal_et_sonlandirma(line_id, actor_id=_actor_id())
        kalem = _load_line(line_id)
        return ok(line_payload(kalem) if kalem else {'id': line_id})
    except ValidationError as exc:
        return fail(str(exc), 400)


@api_bp.route('/kiralama/lines/<int:line_id>/freezes', methods=['GET'])
@token_required
def rental_line_freezes(line_id):
    kayitlar = KiralamaKalemiService.listele_dondurmalar(line_id)
    return ok({
        'items': [
            {
                'id': k.id,
                'start_date': k.baslangic_tarihi,
                'end_date': k.bitis_tarihi,
                'exempt_days': k.muaf_gun_sayisi,
                'description': k.aciklama or '',
                'supplier_purchase_freeze': k.tedarikci_alis_dondur,
            }
            for k in kayitlar
        ],
    })


@api_bp.route('/kiralama/lines/<int:line_id>/freezes', methods=['POST'])
@token_required
def rental_line_add_freeze(line_id):
    body = request.get_json(silent=True) or {}
    try:
        kayit = KiralamaKalemiService.dondur_ekle(
            line_id,
            body.get('start_date') or body.get('baslangic_tarihi'),
            body.get('end_date') or body.get('bitis_tarihi'),
            aciklama=body.get('description') or body.get('aciklama', ''),
            tedarikci_alis_dondur=bool(
                body.get('supplier_purchase_freeze')
                or body.get('tedarikci_alis_dondur', False)
            ),
            actor_id=_actor_id(),
        )
        return ok({
            'id': kayit.id,
            'start_date': kayit.baslangic_tarihi,
            'end_date': kayit.bitis_tarihi,
            'exempt_days': kayit.muaf_gun_sayisi,
        }, 201)
    except ValidationError as exc:
        return fail(str(exc), 400)


@api_bp.route('/kiralama/lines/freezes/<int:freeze_id>', methods=['DELETE'])
@token_required
def rental_line_cancel_freeze(freeze_id):
    try:
        kayit = KiralamaKalemiService.dondur_iptal(freeze_id, actor_id=_actor_id())
        return ok({'id': freeze_id, 'line_id': kayit.kalem_id})
    except ValidationError as exc:
        return fail(str(exc), 400)


@api_bp.route('/kiralama/lookups/customers', methods=['GET'])
@token_required
def rental_lookup_customers():
    search = (request.args.get('q') or '').strip()
    query = Firma.query.filter(
        Firma.is_musteri.is_(True),
        Firma.is_active.is_(True),
        Firma.firma_adi.notin_(['DAHİLİ İŞLEMLER', 'Dahili Kasa İşlemleri']),
    )
    if search:
        query = query.filter(tr_ilike(Firma.firma_adi, f'%{search}%'))
    items = query.order_by(Firma.firma_adi).limit(50).all()
    return ok({
        'items': [{'id': f.id, 'name': f.firma_adi} for f in items],
    })


@api_bp.route('/kiralama/lookups/suppliers', methods=['GET'])
@token_required
def rental_lookup_suppliers():
    search = (request.args.get('q') or '').strip()
    query = Firma.query.filter(
        Firma.is_tedarikci.is_(True),
        Firma.is_active.is_(True),
        Firma.firma_adi.notin_(['DAHİLİ İŞLEMLER', 'Dahili Kasa İşlemleri']),
    )
    if search:
        query = query.filter(tr_ilike(Firma.firma_adi, f'%{search}%'))
    items = query.order_by(Firma.firma_adi).limit(50).all()
    return ok({
        'items': [{'id': f.id, 'name': f.firma_adi} for f in items],
    })


@api_bp.route('/kiralama/lookups/equipment', methods=['GET'])
@token_required
def rental_lookup_equipment():
    include_id = request.args.get('include_id', type=int)
    query = Ekipman.query.filter_by(is_active=True, firma_tedarikci_id=None)
    sube_id = request.args.get('sube_id', type=int)
    tip = (request.args.get('tip') or request.args.get('type') or '').strip()
    marka = (request.args.get('marka') or request.args.get('brand') or '').strip()
    sadece_bosta = str(request.args.get('sadece_bosta', '1')).lower() in ('1', 'true', 'yes', 'on')
    if sube_id:
        query = query.filter(Ekipman.sube_id == sube_id)
    if tip:
        query = query.filter(tr_ilike(Ekipman.tipi, tip))
    if marka:
        marka_normalized = ' '.join(marka.split())
        query = query.filter(tr_ilike(func.trim(Ekipman.marka), f'%{marka_normalized}%'))
    if sadece_bosta:
        query = query.filter(
            or_(Ekipman.calisma_durumu == 'bosta', Ekipman.id == include_id)
        )
    items = query.order_by(Ekipman.kod).limit(100).all()
    return ok({
        'items': [
            {
                'id': e.id,
                'label': (
                    f"{(e.kod or '').strip()} | {(e.tipi or '').strip()} "
                    f"({(e.marka or 'Bilinmiyor').strip()}-"
                    f"{e.calisma_yuksekligi or 0}m - {e.kaldirma_kapasitesi or 0}kg)"
                ),
                'code': e.kod,
                'status': e.calisma_durumu,
            }
            for e in items
        ],
    })


@api_bp.route('/kiralama/lookups/vehicles', methods=['GET'])
@token_required
def rental_lookup_vehicles():
    items = NakliyeAraci.aktif_nakliye_query().order_by(NakliyeAraci.plaka).all()
    return ok({
        'items': [
            {'id': a.id, 'label': f'{a.plaka} - {a.arac_tipi}', 'plate': a.plaka}
            for a in items
        ],
    })


@api_bp.route('/kiralama/lookups/branches', methods=['GET'])
@token_required
def rental_lookup_branches():
    items = Sube.query.filter_by(is_active=True).order_by(Sube.isim).all()
    return ok({
        'items': [{'id': s.id, 'name': s.isim} for s in items],
    })


@api_bp.route('/kiralama/exchange-rates', methods=['GET'])
@token_required
def rental_exchange_rates():
    try:
        kurlar = KiralamaService.get_tcmb_kurlari()
        updated_at = KiralamaService.get_kur_son_guncelleme_text()
    except Exception:
        return fail('Kur verisi su anda kullanilamiyor.', 503)
    return ok({
        'usd_rate': kurlar.get('USD'),
        'eur_rate': kurlar.get('EUR'),
        'updated_at': updated_at,
    })


@api_bp.route('/kiralama/exchange-rates/refresh', methods=['POST'])
@token_required
def rental_exchange_rates_refresh():
    try:
        kurlar = KiralamaService.refresh_tcmb_kurlari(force=True)
        updated_at = KiralamaService.get_kur_son_guncelleme_text()
    except Exception:
        return fail('Kurlar guncellenemedi. Son kayitli degerler korunuyor.', 503)
    return ok({
        'usd_rate': kurlar.get('USD'),
        'eur_rate': kurlar.get('EUR'),
        'updated_at': updated_at,
    })


@api_bp.route('/kiralama/verify-financial-password', methods=['POST'])
@token_required
def rental_verify_financial_password():
    body = request.get_json(silent=True) or {}
    password = body.get('password') or ''
    if not password:
        return fail('Sifre girilmelidir.', 400)
    if not g.api_user.check_password(password):
        return fail('Sifre hatali.', 401)
    return ok({'verified': True})
