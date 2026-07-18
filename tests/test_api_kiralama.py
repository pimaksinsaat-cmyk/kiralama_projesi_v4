"""Kiralama REST API smoke testleri."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from app.auth.models import User
from app.extensions import db
from app.filo.models import Ekipman
from app.firmalar.models import Firma
from app.kiralama.models import Kiralama
from app.models.system_state import ExchangeRate
from app.services.kiralama_services import KiralamaService
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


def _seed_rental_fixtures():
    admin = User(username=f'api_admin_{uuid.uuid4().hex[:6]}', rol='admin')
    admin.set_password('pass123')
    db.session.add(admin)

    sube = Sube(isim='API Sube', adres='Adres', yetkili_kisi='Yetkili', telefon='0212')
    db.session.add(sube)
    db.session.flush()

    musteri = Firma(
        firma_adi=f'API Musteri {uuid.uuid4().hex[:4]}',
        yetkili_adi='Yetkili',
        iletisim_bilgileri='Adres',
        vergi_dairesi='VD',
        vergi_no=f'T{uuid.uuid4().hex[:10].upper()}',
        is_musteri=True,
        is_active=True,
    )
    db.session.add(musteri)
    db.session.flush()

    ekipman = Ekipman(
        kod=f'API-{uuid.uuid4().hex[:4].upper()}',
        yakit='Elektrik',
        tipi='Makasli',
        marka='Marka',
        model='Model',
        seri_no=f'SN{uuid.uuid4().hex[:4]}',
        calisma_yuksekligi=12,
        kaldirma_kapasitesi=230,
        uretim_yili=2024,
        sube_id=sube.id,
        calisma_durumu='bosta',
        is_active=True,
    )
    db.session.add(ekipman)
    db.session.commit()
    return admin, musteri, ekipman


def test_api_kiralama_form_meta_and_create(client, app):
    with app.app_context():
        admin, musteri, ekipman = _seed_rental_fixtures()
        db.session.add_all([
            ExchangeRate(
                currency='USD',
                selling_rate=Decimal('42.10'),
                source='TCMB',
                fetched_at=datetime(2026, 6, 28, 9, 0, 0),
            ),
            ExchangeRate(
                currency='EUR',
                selling_rate=Decimal('48.20'),
                source='TCMB',
                fetched_at=datetime(2026, 6, 28, 9, 0, 0),
            ),
        ])
        db.session.commit()
        headers = _auth_headers(client, admin.username, 'pass123')

        meta = client.get('/api/kiralama/form-meta', headers=headers)
        assert meta.status_code == 200
        assert meta.get_json()['ok'] is True

        form_no = KiralamaService.get_next_form_no()
        create = client.post(
            '/api/kiralama',
            headers=headers,
            json={
                'form_no': form_no,
                'customer_id': musteri.id,
                'work_address': 'Test adres',
                'vat_rate': 20,
                'lines': [
                    {
                        'equipment_id': ekipman.id,
                        'start_date': '2026-06-01',
                        'end_date': '2026-06-30',
                        'unit_price': 1000,
                    }
                ],
            },
        )
        assert create.status_code == 201
        body = create.get_json()
        assert body['ok'] is True
        rental_id = body['data']['id']
        assert body['data']['lines']

        detail = client.get(f'/api/kiralama/{rental_id}', headers=headers)
        assert detail.status_code == 200
        assert detail.get_json()['data']['form_no'] == form_no


def test_api_kiralama_delete_requires_password(client, app):
    with app.app_context():
        admin, musteri, ekipman = _seed_rental_fixtures()
        headers = _auth_headers(client, admin.username, 'pass123')
        kiralama = KiralamaService.create_kiralama_with_relations(
            {
                'kiralama_form_no': KiralamaService.get_next_form_no(),
                'makine_calisma_adresi': 'Adres',
                'firma_musteri_id': musteri.id,
                'kdv_orani': 20,
                'doviz_kuru_usd': 1,
                'doviz_kuru_eur': 1,
            },
            [{
                'dis_tedarik_ekipman': 0,
                'ekipman_id': ekipman.id,
                'kiralama_baslangici': '2026-06-01',
                'kiralama_bitis': '2026-06-15',
                'kiralama_brm_fiyat': 500,
            }],
        )

        bad = client.delete(f'/api/kiralama/{kiralama.id}', headers=headers, json={})
        assert bad.status_code == 400

        ok_delete = client.delete(
            f'/api/kiralama/{kiralama.id}',
            headers=headers,
            json={'password': 'pass123'},
        )
        assert ok_delete.status_code == 200
        assert ok_delete.get_json()['data']['undo_seconds'] == KiralamaService.UNDO_WINDOW_SECONDS
