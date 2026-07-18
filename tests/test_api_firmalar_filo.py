"""Firma ve Filo REST API smoke testleri."""

from __future__ import annotations

import uuid

from app.auth.models import User
from app.extensions import db
from app.filo.models import Ekipman
from app.firmalar.models import Firma
from app.subeler.models import Sube


def _auth_headers(client, username='api_admin', password='pass123'):
    response = client.post(
        '/api/auth/login',
        json={'username': username, 'password': password},
    )
    assert response.status_code == 200
    payload = response.get_json()
    token = payload['data']['access_token']
    return {'Authorization': f'Bearer {token}'}


def _seed_admin():
    admin = User(username=f'api_admin_{uuid.uuid4().hex[:6]}', rol='admin')
    admin.set_password('pass123')
    db.session.add(admin)
    db.session.commit()
    return admin


def _seed_firma(*, is_musteri=True, is_tedarikci=False, is_active=True):
    firma = Firma(
        firma_adi=f'API Firma {uuid.uuid4().hex[:4]}',
        yetkili_adi='Yetkili',
        iletisim_bilgileri='Adres',
        vergi_dairesi='VD',
        vergi_no=f'T{uuid.uuid4().hex[:10].upper()}',
        is_musteri=is_musteri,
        is_tedarikci=is_tedarikci,
        is_active=is_active,
    )
    db.session.add(firma)
    db.session.commit()
    return firma


def _seed_equipment(sube_id, *, firma_tedarikci_id=None, is_active=True, is_deleted=False):
    ekipman = Ekipman(
        kod=f'FL-{uuid.uuid4().hex[:4].upper()}',
        yakit='Elektrik',
        tipi='Makasli',
        marka='Marka',
        model='Model',
        seri_no=f'SN{uuid.uuid4().hex[:4]}',
        calisma_yuksekligi=12,
        kaldirma_kapasitesi=230,
        uretim_yili=2024,
        sube_id=sube_id,
        calisma_durumu='bosta',
        is_active=is_active,
        is_deleted=is_deleted,
        firma_tedarikci_id=firma_tedarikci_id,
    )
    db.session.add(ekipman)
    db.session.commit()
    return ekipman


def test_api_firmalar_list_and_detail(client, app):
    with app.app_context():
        admin = _seed_admin()
        firma = _seed_firma()
        headers = _auth_headers(client, admin.username, 'pass123')

        listing = client.get('/api/firmalar', headers=headers)
        assert listing.status_code == 200
        payload = listing.get_json()
        assert payload['ok'] is True
        assert any(item['id'] == firma.id for item in payload['data']['items'])

        detail = client.get(f'/api/firmalar/{firma.id}', headers=headers)
        assert detail.status_code == 200
        assert detail.get_json()['data']['name'] == firma.firma_adi


def test_api_firmalar_create(client, app):
    with app.app_context():
        admin = _seed_admin()
        headers = _auth_headers(client, admin.username, 'pass123')

        create = client.post(
            '/api/firmalar',
            headers=headers,
            json={
                'name': f'Yeni Firma {uuid.uuid4().hex[:4]}',
                'contact_person': 'Yetkili',
                'address': 'Adres',
                'tax_office': 'VD',
                'tax_no': f'T{uuid.uuid4().hex[:10].upper()}',
                'is_customer': True,
            },
        )
        assert create.status_code == 201
        assert create.get_json()['ok'] is True


def test_api_firmalar_inactive_requires_active_zero(client, app):
    with app.app_context():
        admin = _seed_admin()
        pasif = _seed_firma(is_active=False)
        headers = _auth_headers(client, admin.username, 'pass123')

        active_list = client.get('/api/firmalar?active=1', headers=headers)
        active_ids = {item['id'] for item in active_list.get_json()['data']['items']}
        assert pasif.id not in active_ids

        inactive_list = client.get('/api/firmalar?active=0', headers=headers)
        inactive_ids = {item['id'] for item in inactive_list.get_json()['data']['items']}
        assert pasif.id in inactive_ids


def test_api_filo_list_and_detail(client, app):
    with app.app_context():
        admin = _seed_admin()
        sube = Sube(isim='Filo Sube', adres='Adres', yetkili_kisi='Yetkili', telefon='0212')
        db.session.add(sube)
        db.session.flush()
        ekipman = _seed_equipment(sube.id)
        headers = _auth_headers(client, admin.username, 'pass123')

        listing = client.get('/api/filo', headers=headers)
        assert listing.status_code == 200
        payload = listing.get_json()
        assert payload['ok'] is True
        assert any(item['id'] == ekipman.id for item in payload['data']['items'])

        detail = client.get(f'/api/filo/{ekipman.id}', headers=headers)
        assert detail.status_code == 200
        assert detail.get_json()['data']['code'] == ekipman.kod


def test_api_filo_archived_and_external_filters(client, app):
    with app.app_context():
        admin = _seed_admin()
        sube = Sube(isim='Filo Sube 2', adres='Adres', yetkili_kisi='Yetkili', telefon='0212')
        db.session.add(sube)
        db.session.flush()
        tedarikci = _seed_firma(is_musteri=False, is_tedarikci=True)
        owned = _seed_equipment(sube.id)
        archived = _seed_equipment(sube.id, is_active=False)
        deleted = _seed_equipment(sube.id, is_deleted=True)
        external = _seed_equipment(sube.id, firma_tedarikci_id=tedarikci.id)
        headers = _auth_headers(client, admin.username, 'pass123')

        active_ids = {
            item['id']
            for item in client.get('/api/filo?archived=0', headers=headers).get_json()['data']['items']
        }
        assert owned.id in active_ids
        assert archived.id not in active_ids
        assert deleted.id not in active_ids
        assert external.id not in active_ids

        archived_ids = {
            item['id']
            for item in client.get('/api/filo?archived=1', headers=headers).get_json()['data']['items']
        }
        assert archived.id in archived_ids
        assert deleted.id not in archived_ids

        external_ids = {
            item['id']
            for item in client.get('/api/filo/harici', headers=headers).get_json()['data']['items']
        }
        assert external.id in external_ids
        assert owned.id not in external_ids


def test_api_firmalar_create_rejects_duplicate_tax_no(client, app):
    with app.app_context():
        admin = _seed_admin()
        existing = _seed_firma()
        headers = _auth_headers(client, admin.username, 'pass123')

        response = client.post(
            '/api/firmalar',
            headers=headers,
            json={
                'name': f'Duplicate Firma {uuid.uuid4().hex[:4]}',
                'contact_person': 'Yetkili',
                'address': 'Adres',
                'tax_office': 'VD',
                'tax_no': existing.vergi_no,
                'is_customer': True,
            },
        )

        assert response.status_code == 400
        payload = response.get_json()
        assert payload['ok'] is False
        assert 'vergi' in payload['message'].lower()


def test_api_firmalar_update_without_tax_no_keeps_existing_tax_no(client, app):
    with app.app_context():
        admin = _seed_admin()
        firma = _seed_firma()
        original_tax_no = firma.vergi_no
        headers = _auth_headers(client, admin.username, 'pass123')

        response = client.put(
            f'/api/firmalar/{firma.id}',
            headers=headers,
            json={
                'name': f'Guncel Firma {uuid.uuid4().hex[:4]}',
                'contact_person': firma.yetkili_adi,
                'address': firma.iletisim_bilgileri,
                'tax_office': firma.vergi_dairesi,
                'is_customer': True,
                'is_supplier': False,
            },
        )

        assert response.status_code == 200
        payload = response.get_json()
        assert payload['ok'] is True
        assert payload['data']['tax_no'] == original_tax_no
        assert db.session.get(Firma, firma.id).vergi_no == original_tax_no


def test_api_firmalar_update_allows_own_tax_no(client, app):
    with app.app_context():
        admin = _seed_admin()
        firma = _seed_firma()
        headers = _auth_headers(client, admin.username, 'pass123')

        response = client.put(
            f'/api/firmalar/{firma.id}',
            headers=headers,
            json={
                'name': firma.firma_adi,
                'contact_person': firma.yetkili_adi,
                'address': firma.iletisim_bilgileri,
                'tax_office': firma.vergi_dairesi,
                'tax_no': firma.vergi_no,
                'is_customer': True,
                'is_supplier': False,
            },
        )

        assert response.status_code == 200
        payload = response.get_json()
        assert payload['ok'] is True
        assert payload['data']['tax_no'] == firma.vergi_no


def test_api_firmalar_update_rejects_another_firmas_tax_no(client, app):
    with app.app_context():
        admin = _seed_admin()
        firma = _seed_firma()
        other = _seed_firma()
        original_tax_no = firma.vergi_no
        headers = _auth_headers(client, admin.username, 'pass123')

        response = client.put(
            f'/api/firmalar/{firma.id}',
            headers=headers,
            json={
                'name': firma.firma_adi,
                'contact_person': firma.yetkili_adi,
                'address': firma.iletisim_bilgileri,
                'tax_office': firma.vergi_dairesi,
                'tax_no': other.vergi_no,
                'is_customer': True,
                'is_supplier': False,
            },
        )

        assert response.status_code == 400
        payload = response.get_json()
        assert payload['ok'] is False
        assert 'vergi' in payload['message'].lower()
        assert db.session.get(Firma, firma.id).vergi_no == original_tax_no
