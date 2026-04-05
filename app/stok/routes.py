from datetime import date
from decimal import Decimal

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func, or_
from sqlalchemy.orm import joinedload

from app.extensions import db
from app.filo.models import BakimKaydi, StokHareket, StokKarti
from app.firmalar.models import Firma
from app.services.base import ValidationError
from app.services.operation_log_service import OperationLogService
from app.services.stok_services import StokHareketService, StokKartiService
from app.stok import stok_bp


def get_actor_id():
    return current_user.id if current_user.is_authenticated else None


def _supplier_options():
    return (
        Firma.query.filter_by(is_deleted=False, is_tedarikci=True)
        .order_by(Firma.firma_adi.asc())
        .all()
    )


def _attach_card_metrics(kartlar):
    for kart in kartlar:
        kart.son_birim_fiyat = StokKartiService.latest_price(kart.id)
        kart.stok_degeri = StokKartiService.inventory_value_for_card(kart)


@stok_bp.route('/')
@login_required
def index():
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 25, type=int)
    if per_page not in {10, 25, 50, 100}:
        per_page = 25

    q = request.args.get('q', '', type=str).strip()

    base_query = StokKarti.query.filter(StokKarti.is_deleted == False).options(
        joinedload(StokKarti.varsayilan_tedarikci)
    )
    query = base_query
    if q:
        term = f'%{q}%'
        query = query.outerjoin(StokKarti.varsayilan_tedarikci).filter(
            or_(
                StokKarti.parca_kodu.ilike(term),
                StokKarti.parca_adi.ilike(term),
                Firma.firma_adi.ilike(term),
            )
        )

    pagination = query.order_by(StokKarti.parca_adi.asc(), StokKarti.id.desc()).paginate(
        page=page,
        per_page=per_page,
        error_out=False,
    )
    kartlar = pagination.items
    _attach_card_metrics(kartlar)

    aktif_kart_sayisi = base_query.count()
    hareket_sayisi = StokHareket.query.filter(StokHareket.is_deleted == False).count()
    toplam_stok_adedi = (
        db.session.query(func.coalesce(func.sum(StokKarti.mevcut_stok), 0))
        .filter(StokKarti.is_deleted == False)
        .scalar()
        or 0
    )
    toplam_envanter_degeri = StokKartiService.total_inventory_value()
    arsiv_kart_sayisi = StokKarti.query.filter(StokKarti.is_deleted == True).count()

    return render_template(
        'stok/index.html',
        kartlar=kartlar,
        pagination=pagination,
        q=q,
        per_page=per_page,
        tedarikciler=_supplier_options(),
        aktif_kart_sayisi=aktif_kart_sayisi,
        arsiv_kart_sayisi=arsiv_kart_sayisi,
        hareket_sayisi=hareket_sayisi,
        toplam_stok_adedi=toplam_stok_adedi,
        toplam_envanter_degeri=toplam_envanter_degeri,
    )


@stok_bp.route('/arsiv')
@login_required
def arsiv():
    q = request.args.get('q', '', type=str).strip()

    query = StokKarti.query.filter(StokKarti.is_deleted == True).options(
        joinedload(StokKarti.varsayilan_tedarikci)
    )

    if q:
        term = f'%{q}%'
        query = query.outerjoin(StokKarti.varsayilan_tedarikci).filter(
            or_(
                StokKarti.parca_kodu.ilike(term),
                StokKarti.parca_adi.ilike(term),
                Firma.firma_adi.ilike(term),
            )
        )

    kartlar = query.order_by(StokKarti.deleted_at.desc(), StokKarti.id.desc()).all()
    return render_template('stok/arsiv.html', kartlar=kartlar, q=q)


@stok_bp.route('/yeni', methods=['POST'])
@login_required
def yeni_kart():
    try:
        kart = StokKartiService.create_card(request.form, actor_id=get_actor_id())
        OperationLogService.log(
            module='stok',
            action='create',
            user_id=get_actor_id(),
            username=getattr(current_user, 'username', None),
            entity_type='StokKarti',
            entity_id=kart.id,
            description=f'{kart.parca_kodu} stok karti eklendi.',
            success=True,
        )
        flash('Stok karti olusturuldu.', 'success')
    except ValidationError as exc:
        OperationLogService.log(
            module='stok',
            action='create',
            user_id=get_actor_id(),
            username=getattr(current_user, 'username', None),
            entity_type='StokKarti',
            description=f'Stok karti olusturma hatasi: {exc}',
            success=False,
        )
        flash(str(exc), 'danger')
    except Exception as exc:
        OperationLogService.log(
            module='stok',
            action='create',
            user_id=get_actor_id(),
            username=getattr(current_user, 'username', None),
            entity_type='StokKarti',
            description=f'Stok karti olusturma hatasi: {exc}',
            success=False,
        )
        flash(f'Hata: {exc}', 'danger')
    return redirect(url_for('stok.index'))


@stok_bp.route('/<int:kart_id>')
@login_required
def detay(kart_id):
    kart = (
        StokKarti.query.filter(StokKarti.id == kart_id, StokKarti.is_deleted == False)
        .options(joinedload(StokKarti.varsayilan_tedarikci))
        .first_or_404()
    )

    hareketler = (
        StokHareket.query.filter(
            StokHareket.stok_karti_id == kart_id,
            StokHareket.is_deleted == False,
        )
        .options(
            joinedload(StokHareket.firma),
            joinedload(StokHareket.bakim_kaydi).joinedload(BakimKaydi.ekipman),
        )
        .order_by(StokHareket.tarih.desc(), StokHareket.id.desc())
        .all()
    )

    toplam_giris = (
        db.session.query(func.coalesce(func.sum(StokHareket.adet), 0))
        .filter(
            StokHareket.stok_karti_id == kart_id,
            StokHareket.is_deleted == False,
            StokHareket.hareket_tipi == 'giris',
        )
        .scalar()
        or 0
    )
    toplam_cikis = (
        db.session.query(func.coalesce(func.sum(StokHareket.adet), 0))
        .filter(
            StokHareket.stok_karti_id == kart_id,
            StokHareket.is_deleted == False,
            StokHareket.hareket_tipi == 'cikis',
        )
        .scalar()
        or 0
    )

    kart.son_birim_fiyat = StokKartiService.latest_price(kart.id)
    kart.stok_degeri = Decimal(kart.mevcut_stok or 0) * kart.son_birim_fiyat

    return render_template(
        'stok/detay.html',
        kart=kart,
        hareketler=hareketler,
        tedarikciler=_supplier_options(),
        bugun=date.today().strftime('%Y-%m-%d'),
        toplam_giris=toplam_giris,
        toplam_cikis=toplam_cikis,
    )


@stok_bp.route('/<int:kart_id>/guncelle', methods=['POST'])
@login_required
def guncelle(kart_id):
    try:
        kart = StokKartiService.update_card(kart_id, request.form, actor_id=get_actor_id())
        OperationLogService.log(
            module='stok',
            action='update',
            user_id=get_actor_id(),
            username=getattr(current_user, 'username', None),
            entity_type='StokKarti',
            entity_id=kart.id,
            description=f'{kart.parca_kodu} stok karti guncellendi.',
            success=True,
        )
        flash('Stok karti guncellendi.', 'success')
    except ValidationError as exc:
        OperationLogService.log(
            module='stok',
            action='update',
            user_id=get_actor_id(),
            username=getattr(current_user, 'username', None),
            entity_type='StokKarti',
            entity_id=kart_id,
            description=f'Stok karti guncelleme hatasi: {exc}',
            success=False,
        )
        flash(str(exc), 'danger')
    except Exception as exc:
        OperationLogService.log(
            module='stok',
            action='update',
            user_id=get_actor_id(),
            username=getattr(current_user, 'username', None),
            entity_type='StokKarti',
            entity_id=kart_id,
            description=f'Stok karti guncelleme hatasi: {exc}',
            success=False,
        )
        flash(f'Hata: {exc}', 'danger')
    return redirect(url_for('stok.detay', kart_id=kart_id))


@stok_bp.route('/<int:kart_id>/hareket', methods=['POST'])
@login_required
def hareket_ekle(kart_id):
    try:
        hareket = StokHareketService.create_movement(kart_id, request.form, actor_id=get_actor_id())
        OperationLogService.log(
            module='stok',
            action='movement_create',
            user_id=get_actor_id(),
            username=getattr(current_user, 'username', None),
            entity_type='StokHareket',
            entity_id=hareket.id,
            description=f'Stok hareketi eklendi: kart #{kart_id}, tip={hareket.hareket_tipi}, adet={hareket.adet}.',
            success=True,
        )
        flash('Stok hareketi kaydedildi.', 'success')
    except ValidationError as exc:
        OperationLogService.log(
            module='stok',
            action='movement_create',
            user_id=get_actor_id(),
            username=getattr(current_user, 'username', None),
            entity_type='StokHareket',
            description=f'Stok hareketi hatasi: {exc}',
            success=False,
        )
        flash(str(exc), 'danger')
    except Exception as exc:
        OperationLogService.log(
            module='stok',
            action='movement_create',
            user_id=get_actor_id(),
            username=getattr(current_user, 'username', None),
            entity_type='StokHareket',
            description=f'Stok hareketi hatasi: {exc}',
            success=False,
        )
        flash(f'Hata: {exc}', 'danger')
    return redirect(url_for('stok.detay', kart_id=kart_id))


@stok_bp.route('/<int:kart_id>/hareket/<int:hareket_id>/sil', methods=['POST'])
@login_required
def hareket_sil(kart_id, hareket_id):
    try:
        hareket, kart = StokHareketService.delete_movement(kart_id, hareket_id)
        OperationLogService.log(
            module='stok',
            action='movement_delete',
            user_id=get_actor_id(),
            username=getattr(current_user, 'username', None),
            entity_type='StokHareket',
            entity_id=hareket_id,
            description=(
                f'Stok hareketi silindi: kart={kart.parca_kodu}, tip={hareket.hareket_tipi}, adet={hareket.adet}.'
            ),
            success=True,
        )
        flash('Stok hareketi kalici olarak silindi.', 'success')
    except ValidationError as exc:
        OperationLogService.log(
            module='stok',
            action='movement_delete',
            user_id=get_actor_id(),
            username=getattr(current_user, 'username', None),
            entity_type='StokHareket',
            entity_id=hareket_id,
            description=f'Stok hareketi silme hatasi: {exc}',
            success=False,
        )
        flash(str(exc), 'danger')
    except Exception as exc:
        OperationLogService.log(
            module='stok',
            action='movement_delete',
            user_id=get_actor_id(),
            username=getattr(current_user, 'username', None),
            entity_type='StokHareket',
            entity_id=hareket_id,
            description=f'Stok hareketi silme hatasi: {exc}',
            success=False,
        )
        flash(f'Hata: {exc}', 'danger')
    return redirect(url_for('stok.detay', kart_id=kart_id))


@stok_bp.route('/<int:kart_id>/arsivle', methods=['POST'])
@login_required
def arsivle(kart_id):
    kart = StokKartiService.get_by_id(kart_id)
    try:
        StokKartiService.delete(kart_id, actor_id=get_actor_id())
        OperationLogService.log(
            module='stok',
            action='delete',
            user_id=get_actor_id(),
            username=getattr(current_user, 'username', None),
            entity_type='StokKarti',
            entity_id=kart_id,
            description=f'{getattr(kart, "parca_kodu", kart_id)} stok karti arsivlendi.',
            success=True,
        )
        flash('Stok karti arsivlendi.', 'success')
    except ValidationError as exc:
        OperationLogService.log(
            module='stok',
            action='delete',
            user_id=get_actor_id(),
            username=getattr(current_user, 'username', None),
            entity_type='StokKarti',
            entity_id=kart_id,
            description=f'Stok karti arsivleme hatasi: {exc}',
            success=False,
        )
        flash(str(exc), 'danger')
    except Exception as exc:
        OperationLogService.log(
            module='stok',
            action='delete',
            user_id=get_actor_id(),
            username=getattr(current_user, 'username', None),
            entity_type='StokKarti',
            entity_id=kart_id,
            description=f'Stok karti arsivleme hatasi: {exc}',
            success=False,
        )
        flash(f'Hata: {exc}', 'danger')
    return redirect(url_for('stok.index'))


@stok_bp.route('/<int:kart_id>/kalici_sil', methods=['POST'])
@login_required
def kalici_sil(kart_id):
    kart = StokKartiService.get_by_id(kart_id, include_deleted=True)
    parca_kodu = getattr(kart, 'parca_kodu', kart_id)
    try:
        StokKartiService.hard_delete_card(kart_id)
        OperationLogService.log(
            module='stok',
            action='hard_delete',
            user_id=get_actor_id(),
            username=getattr(current_user, 'username', None),
            entity_type='StokKarti',
            entity_id=kart_id,
            description=f'{parca_kodu} stok karti kalici olarak silindi.',
            success=True,
        )
        flash('Stok karti kalici olarak silindi.', 'success')
    except ValidationError as exc:
        OperationLogService.log(
            module='stok',
            action='hard_delete',
            user_id=get_actor_id(),
            username=getattr(current_user, 'username', None),
            entity_type='StokKarti',
            entity_id=kart_id,
            description=f'Stok karti kalici silme hatasi: {exc}',
            success=False,
        )
        flash(str(exc), 'danger')
    except Exception as exc:
        OperationLogService.log(
            module='stok',
            action='hard_delete',
            user_id=get_actor_id(),
            username=getattr(current_user, 'username', None),
            entity_type='StokKarti',
            entity_id=kart_id,
            description=f'Stok karti kalici silme hatasi: {exc}',
            success=False,
        )
        flash(f'Hata: {exc}', 'danger')
    return redirect(url_for('stok.arsiv'))


@stok_bp.route('/<int:kart_id>/geri_yukle', methods=['POST'])
@login_required
def geri_yukle(kart_id):
    try:
        kart = StokKartiService.restore_card(kart_id, actor_id=get_actor_id())
        OperationLogService.log(
            module='stok',
            action='restore',
            user_id=get_actor_id(),
            username=getattr(current_user, 'username', None),
            entity_type='StokKarti',
            entity_id=kart_id,
            description=f'{kart.parca_kodu} stok karti arsivden geri yuklendi.',
            success=True,
        )
        flash('Stok karti arsivden geri yuklendi.', 'success')
    except ValidationError as exc:
        OperationLogService.log(
            module='stok',
            action='restore',
            user_id=get_actor_id(),
            username=getattr(current_user, 'username', None),
            entity_type='StokKarti',
            entity_id=kart_id,
            description=f'Stok karti geri yukleme hatasi: {exc}',
            success=False,
        )
        flash(str(exc), 'danger')
    except Exception as exc:
        OperationLogService.log(
            module='stok',
            action='restore',
            user_id=get_actor_id(),
            username=getattr(current_user, 'username', None),
            entity_type='StokKarti',
            entity_id=kart_id,
            description=f'Stok karti geri yukleme hatasi: {exc}',
            success=False,
        )
        flash(f'Hata: {exc}', 'danger')
    return redirect(url_for('stok.arsiv'))