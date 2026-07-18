"""Kiralama API JSON payload builders — yalnizca SQLAlchemy model kolonlari."""

from app.kiralama.models import Kiralama, KiralamaKalemi


def equipment_label(kalem):
    if kalem.is_dis_tedarik_ekipman:
        parts = [
            kalem.harici_ekipman_tipi,
            kalem.harici_ekipman_marka,
            kalem.harici_ekipman_model,
            kalem.harici_ekipman_seri_no,
        ]
        return ' '.join(str(part) for part in parts if part) or 'Harici ekipman'
    ekipman = kalem.ekipman
    if not ekipman:
        return 'Ekipman secilmemis'
    parts = [
        getattr(ekipman, 'ekipman_tipi', None) or getattr(ekipman, 'tipi', None),
        getattr(ekipman, 'marka', None),
        getattr(ekipman, 'model', None),
        getattr(ekipman, 'seri_no', None),
    ]
    return ' '.join(str(part) for part in parts if part) or f'Ekipman #{ekipman.id}'


def line_payload(kalem):
    """KiralamaKalemi model kolonlarindan JSON."""
    return {
        'id': kalem.id,
        'equipment_label': equipment_label(kalem),
        'is_external_equipment': bool(kalem.is_dis_tedarik_ekipman),
        'equipment_id': kalem.ekipman_id,
        'external_supplier_id': kalem.harici_ekipman_tedarikci_id,
        'external_equipment_type': kalem.harici_ekipman_tipi,
        'external_equipment_brand': kalem.harici_ekipman_marka,
        'external_equipment_model': kalem.harici_ekipman_model,
        'external_equipment_serial': kalem.harici_ekipman_seri_no,
        'external_capacity': kalem.harici_ekipman_kapasite,
        'external_height': kalem.harici_ekipman_yukseklik,
        'external_production_year': kalem.harici_ekipman_uretim_yili,
        'start_date': kalem.kiralama_baslangici,
        'end_date': kalem.kiralama_bitis,
        'unit_price': kalem.kiralama_brm_fiyat,
        'purchase_price': kalem.kiralama_alis_fiyat,
        'purchase_vat_rate': kalem.kiralama_alis_kdv,
        'is_own_transport': kalem.is_oz_mal_nakliye,
        'is_external_transport': kalem.is_harici_nakliye,
        'transport_sale_price': kalem.nakliye_satis_fiyat,
        'transport_purchase_price': kalem.nakliye_alis_fiyat,
        'transport_purchase_vat_rate': kalem.nakliye_alis_kdv,
        'transport_sale_vat_rate': kalem.nakliye_satis_kdv,
        'transport_purchase_withholding': kalem.nakliye_alis_tevkifat_oran,
        'transport_sale_withholding': kalem.nakliye_satis_tevkifat_oran,
        'transport_supplier_id': kalem.nakliye_tedarikci_id,
        'transport_vehicle_id': kalem.nakliye_araci_id,
        'return_transport_invoice': kalem.donus_nakliye_fatura_et,
        'return_transport_sale_price': kalem.donus_nakliye_satis_fiyat,
        'return_transport_purchase_vat_rate': kalem.donus_nakliye_alis_kdv,
        'return_is_external_transport': kalem.donus_is_harici_nakliye,
        'return_transport_supplier_id': kalem.donus_nakliye_tedarikci_id,
        'return_transport_purchase_price': kalem.donus_nakliye_alis_fiyat,
        'return_transport_vehicle_id': kalem.donus_nakliye_araci_id,
        'return_branch_id': kalem.donus_sube_id,
        'is_active': bool(kalem.is_active),
        'is_ended': bool(kalem.sonlandirildi),
        'version_no': kalem.versiyon_no,
        'parent_id': kalem.parent_id,
        'chain_id': kalem.chain_id,
    }


def rental_summary(kiralama):
    active_lines = [
        item for item in kiralama.kalemler
        if not item.is_deleted and item.is_active
    ]
    visible_lines = active_lines or [
        item for item in kiralama.kalemler if not item.is_deleted
    ]
    starts = [item.kiralama_baslangici for item in visible_lines if item.kiralama_baslangici]
    ends = [item.kiralama_bitis for item in visible_lines if item.kiralama_bitis]
    return {
        'id': kiralama.id,
        'form_no': kiralama.kiralama_form_no,
        'customer_name': kiralama.firma_musteri.firma_adi if kiralama.firma_musteri else '',
        'created_date': kiralama.kiralama_olusturma_tarihi,
        'work_address': kiralama.makine_calisma_adresi,
        'active_line_count': len(active_lines),
        'line_count': len(visible_lines),
        'start_date': min(starts) if starts else None,
        'end_date': max(ends) if ends else None,
        'equipment_summary': ', '.join(equipment_label(item) for item in visible_lines[:2]),
    }


def rental_detail(kiralama):
    payload = rental_summary(kiralama)
    payload.update({
        'customer': {
            'id': kiralama.firma_musteri.id,
            'name': kiralama.firma_musteri.firma_adi,
            'phone': kiralama.firma_musteri.telefon,
            'email': kiralama.firma_musteri.eposta,
            'balance': kiralama.firma_musteri.bakiye,
        } if kiralama.firma_musteri else None,
        'customer_id': kiralama.firma_musteri_id,
        'vat_rate': kiralama.kdv_orani,
        'usd_rate': kiralama.doviz_kuru_usd,
        'eur_rate': kiralama.doviz_kuru_eur,
        'lines': [line_payload(item) for item in kiralama.kalemler if not item.is_deleted],
    })
    return payload


def _pick(data, *keys, default=None):
    for key in keys:
        if key in data and data[key] is not None:
            return data[key]
    return default


def _bool_flag(value):
    if value is None:
        return 0
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, (int, float)):
        return 1 if int(value) else 0
    return 1 if str(value).lower() in ('1', 'true', 'on', 'yes') else 0


def header_to_service(body):
    """API JSON -> KiralamaService.create/update kiralama_data."""
    return {
        'kiralama_form_no': (_pick(body, 'kiralama_form_no', 'form_no') or '').strip(),
        'makine_calisma_adresi': _pick(body, 'makine_calisma_adresi', 'work_address'),
        'firma_musteri_id': int(_pick(body, 'firma_musteri_id', 'customer_id') or 0),
        'kdv_orani': int(_pick(body, 'kdv_orani', 'vat_rate') or 20),
        'doviz_kuru_usd': _pick(body, 'doviz_kuru_usd', 'usd_rate') or 0,
        'doviz_kuru_eur': _pick(body, 'doviz_kuru_eur', 'eur_rate') or 0,
    }


def line_to_service(line):
    """API JSON satir -> KiralamaService kalemler_data ogesi."""
    if not isinstance(line, dict):
        return {}
    return {
        'id': int(_pick(line, 'id') or 0),
        'dis_tedarik_ekipman': _bool_flag(
            _pick(line, 'dis_tedarik_ekipman', 'is_external_equipment')
        ),
        'ekipman_id': int(_pick(line, 'ekipman_id', 'equipment_id') or 0),
        'harici_ekipman_tedarikci_id': int(
            _pick(line, 'harici_ekipman_tedarikci_id', 'external_supplier_id') or 0
        ),
        'harici_ekipman_tipi': _pick(line, 'harici_ekipman_tipi', 'external_equipment_type'),
        'harici_ekipman_marka': _pick(line, 'harici_ekipman_marka', 'external_equipment_brand'),
        'harici_ekipman_model': _pick(line, 'harici_ekipman_model', 'external_equipment_model'),
        'harici_ekipman_seri_no': _pick(
            line, 'harici_ekipman_seri_no', 'external_equipment_serial'
        ),
        'harici_ekipman_kaldirma_kapasitesi': _pick(
            line, 'harici_ekipman_kaldirma_kapasitesi', 'external_capacity'
        ),
        'harici_ekipman_calisma_yuksekligi': _pick(
            line, 'harici_ekipman_calisma_yuksekligi', 'external_height'
        ),
        'harici_ekipman_uretim_tarihi': _pick(
            line, 'harici_ekipman_uretim_tarihi', 'external_production_year'
        ),
        'kiralama_baslangici': _pick(line, 'kiralama_baslangici', 'start_date'),
        'kiralama_bitis': _pick(line, 'kiralama_bitis', 'end_date'),
        'kiralama_brm_fiyat': _pick(line, 'kiralama_brm_fiyat', 'unit_price') or 0,
        'kiralama_alis_fiyat': _pick(line, 'kiralama_alis_fiyat', 'purchase_price') or 0,
        'kiralama_alis_kdv': _pick(line, 'kiralama_alis_kdv', 'purchase_vat_rate'),
        'dis_tedarik_nakliye': _bool_flag(
            _pick(line, 'dis_tedarik_nakliye', 'is_external_transport')
        ),
        'nakliye_satis_fiyat': _pick(line, 'nakliye_satis_fiyat', 'transport_sale_price') or 0,
        'donus_nakliye_fatura_et': _bool_flag(
            _pick(line, 'donus_nakliye_fatura_et', 'return_transport_invoice')
        ),
        'nakliye_alis_fiyat': _pick(line, 'nakliye_alis_fiyat', 'transport_purchase_price') or 0,
        'nakliye_alis_kdv': _pick(line, 'nakliye_alis_kdv', 'transport_purchase_vat_rate'),
        'nakliye_satis_kdv': _pick(line, 'nakliye_satis_kdv', 'transport_sale_vat_rate'),
        'nakliye_alis_tevkifat_oran': _pick(
            line, 'nakliye_alis_tevkifat_oran', 'transport_purchase_withholding'
        ),
        'nakliye_satis_tevkifat_oran': _pick(
            line, 'nakliye_satis_tevkifat_oran', 'transport_sale_withholding'
        ),
        'nakliye_tedarikci_id': int(
            _pick(line, 'nakliye_tedarikci_id', 'transport_supplier_id') or 0
        ),
        'nakliye_araci_id': int(_pick(line, 'nakliye_araci_id', 'transport_vehicle_id') or 0),
        'donus_is_harici_nakliye': _bool_flag(
            _pick(line, 'donus_is_harici_nakliye', 'return_is_external_transport')
        ),
        'donus_nakliye_tedarikci_id': int(
            _pick(line, 'donus_nakliye_tedarikci_id', 'return_transport_supplier_id') or 0
        ),
        'donus_nakliye_alis_fiyat': _pick(
            line, 'donus_nakliye_alis_fiyat', 'return_transport_purchase_price'
        ),
        'donus_nakliye_alis_kdv': _pick(
            line, 'donus_nakliye_alis_kdv', 'return_transport_purchase_vat_rate'
        ),
        'donus_nakliye_araci_id': int(
            _pick(line, 'donus_nakliye_araci_id', 'return_transport_vehicle_id') or 0
        ),
        'sonlandirildi': _bool_flag(_pick(line, 'sonlandirildi', 'is_ended')),
        'is_active': _bool_flag(_pick(line, 'is_active', default=1)),
        'parent_id': int(_pick(line, 'parent_id') or 0),
        'versiyon_no': int(_pick(line, 'versiyon_no', 'version_no') or 1),
    }


def lines_to_service(body):
    raw = body.get('lines') or body.get('kalemler') or []
    if not isinstance(raw, list):
        return []
    return [line_to_service(item) for item in raw if isinstance(item, dict)]


def rental_query_options():
    from sqlalchemy.orm import joinedload, selectinload
    return (
        joinedload(Kiralama.firma_musteri),
        selectinload(Kiralama.kalemler).joinedload(KiralamaKalemi.ekipman),
    )
