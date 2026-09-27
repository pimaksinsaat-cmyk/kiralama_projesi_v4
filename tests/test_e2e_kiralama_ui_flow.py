from __future__ import annotations

import json
import uuid
from datetime import date
from decimal import Decimal

from app.auth.models import User
from app.extensions import db
from app.firmalar.models import Firma
from app.filo.models import Ekipman
from app.kiralama.models import Kiralama, KiralamaKalemi
from app.nakliyeler.models import Nakliye, NakliyeDagitim
from app.subeler.models import Sube
from app.araclar.models import Arac
from playwright.sync_api import sync_playwright


def _login_user(client, user_id: int) -> None:
    from app.auth.session_security import (
        SESSION_LAST_PING_KEY,
        SESSION_TOKEN_KEY,
        new_session_token,
        utc_now,
    )

    token = new_session_token()
    now = utc_now()
    user = db.session.get(User, user_id)
    user.active_session_token = token
    user.active_session_started_at = now
    user.active_session_seen_at = now
    db.session.commit()

    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True
        session[SESSION_TOKEN_KEY] = token
        session[SESSION_LAST_PING_KEY] = now.isoformat()


def test_kiralama_delete_undo_ui_flow(app, client, live_server):
    with app.app_context():
        admin = User(username=f"kiralama_ui_admin_{uuid.uuid4().hex[:6]}", rol="admin")
        admin.set_password("pass123")
        db.session.add(admin)

        sube = Sube(
            isim="Kiralama UI Sube",
            adres="E2E Adres",
            yetkili_kisi="E2E Yetkili",
            telefon="0212-1234567",
        )
        db.session.add(sube)

        musteri = Firma(
            firma_adi=f"Kiralama UI Musteri {uuid.uuid4().hex[:4]}",
            yetkili_adi="Yetkili",
            iletisim_bilgileri="Adres",
            vergi_dairesi="Istanbul VD",
            vergi_no=f"T{uuid.uuid4().hex[:10].upper()}",
            is_musteri=True,
            is_tedarikci=False,
            bakiye=Decimal("0"),
        )
        db.session.add(musteri)

        ekipman = Ekipman(
            kod=f"UI-{uuid.uuid4().hex[:8].upper()}",
            yakit="Elektrik",
            tipi="MAKAS",
            marka="E2E Marka",
            model="E2E Model",
            seri_no=f"SN-{uuid.uuid4().hex[:8]}",
            calisma_yuksekligi=12,
            kaldirma_kapasitesi=2500,
            uretim_yili=2024,
            calisma_durumu="bosta",
            sube_id=sube.id,
        )
        db.session.add(ekipman)
        db.session.flush()

        kiralama = Kiralama(
            kiralama_form_no=f"PF-UI-{uuid.uuid4().hex[:6]}",
            firma_musteri_id=musteri.id,
            kdv_orani=20,
        )
        db.session.add(kiralama)
        db.session.flush()

        KiralamaKalemi(
            kiralama_id=kiralama.id,
            ekipman_id=ekipman.id,
            kiralama_baslangici=date(2026, 4, 14),
            kiralama_bitis=date(2026, 4, 30),
            kiralama_brm_fiyat=Decimal("1000.00"),
            sonlandirildi=False,
            is_active=True,
        )
        db.session.commit()

        admin_id = admin.id
        expected_form_no = kiralama.kiralama_form_no

    _login_user(client, admin_id)

    # Ensure Flask session cookie exists for browser context
    client.get("/kiralama/index")
    session_cookie_name = app.config.get("SESSION_COOKIE_NAME", "session")
    session_cookie = client.get_cookie(session_cookie_name)
    assert session_cookie is not None, "Test session cookie not found"

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context()
        context.add_cookies([
            {
                "name": session_cookie.key,
                "value": session_cookie.value,
                "domain": "127.0.0.1",
                "path": "/",
                "httpOnly": True,
                "secure": False,
                "sameSite": "Lax",
            }
        ])
        page = context.new_page()
        page.goto(f"{live_server}/kiralama/index", wait_until="networkidle")

        row = page.locator("tr.kiralama-satiri").first
        assert row.count() == 1
        row.dispatch_event("contextmenu")

        page.wait_for_selector("#menu-sil", state="visible", timeout=5000)
        page.click("#menu-sil")
        page.wait_for_selector("#deleteKiralamaPasswordModal.show", timeout=5000)

        page.fill("#delete-kiralama-password-input", "pass123")
        page.click("#delete-kiralama-password-confirm")
        page.wait_for_selector("#kiralama-undo-btn", timeout=10000)

        pending = page.evaluate("sessionStorage.getItem('kiralama_pending_undo')")
        assert pending is not None
        payload = json.loads(pending)
        assert payload["formNo"] == expected_form_no
        assert payload["rentalId"] is not None

        page.reload(wait_until="networkidle")
        page.wait_for_selector("#kiralama-undo-btn", timeout=10000)

        with page.expect_navigation(url=f"{live_server}/kiralama/index"):
            page.click("#kiralama-undo-btn")

        page.wait_for_selector("tr.kiralama-satiri", timeout=10000)
        assert expected_form_no in page.content()

        browser.close()


def test_sefer_cift_yon_paket_tutari_kiralama_kaleminde_tek_keze_sayilir(app, client, live_server):
    with app.app_context():
        admin = User(username=f"sefer_ui_admin_{uuid.uuid4().hex[:6]}", rol="admin")
        admin.set_password("pass123")
        sube = Sube(
            isim="Sefer UI Sube",
            adres="E2E Adres",
            yetkili_kisi="E2E Yetkili",
            telefon="0212-1234567",
        )
        musteri = Firma(
            firma_adi=f"Bordemir UI {uuid.uuid4().hex[:4]}",
            yetkili_adi="Yetkili", iletisim_bilgileri="Adres",
            vergi_dairesi="Istanbul VD", vergi_no=f"B{uuid.uuid4().hex[:10].upper()}",
            is_musteri=True, is_tedarikci=False, bakiye=Decimal("0"),
        )
        ekipman = Ekipman(
            kod=f"PM01-{uuid.uuid4().hex[:6].upper()}", yakit="Diesel", tipi="LIFT",
            marka="Test", model="PM01", seri_no=f"SN-{uuid.uuid4().hex[:8]}",
            calisma_yuksekligi=15, kaldirma_kapasitesi=2500, uretim_yili=2024,
            calisma_durumu="kirada", sube=sube,
        )
        arac = Arac(
            plaka="34ERJ782", arac_tipi="Kamyon", marka_model="Test",
            is_nakliye_araci=True,
        )
        db.session.add_all([admin, sube, musteri, ekipman, arac])
        db.session.flush()

        kiralama = Kiralama(
            kiralama_form_no=f"PF-SEFER-UI-{uuid.uuid4().hex[:6]}",
            firma_musteri_id=musteri.id,
            kdv_orani=20,
            nakliye_modeli="sefer",
        )
        db.session.add(kiralama)
        db.session.flush()
        kalem = KiralamaKalemi(
            kiralama_id=kiralama.id,
            ekipman_id=ekipman.id,
            kiralama_baslangici=date(2026, 9, 1),
            kiralama_bitis=date(2026, 9, 2),
            kiralama_brm_fiyat=Decimal("500.00"),
            is_active=True,
            sonlandirildi=False,
        )
        db.session.add(kalem)
        db.session.flush()
        sefer = Nakliye(
            kiralama_id=kiralama.id,
            firma_id=musteri.id,
            yon="gidis",
            cift_yon=True,
            tarih=date(2026, 9, 1),
            islem_tarihi=date(2026, 9, 1),
            guzergah="Depo - Bordemir",
            nakliye_tipi="oz_mal",
            arac_id=arac.id,
            tutar=Decimal("2000.00"),
            toplam_tutar=Decimal("2000.00"),
        )
        db.session.add(sefer)
        db.session.flush()
        db.session.add(NakliyeDagitim(
            nakliye_id=sefer.id,
            kiralama_kalemi_id=kalem.id,
            tutar=Decimal("2000.00"),
        ))
        db.session.commit()
        admin_id = admin.id
        kiralama_id = kiralama.id

    _login_user(client, admin_id)
    client.get("/kiralama/index")
    session_cookie_name = app.config.get("SESSION_COOKIE_NAME", "session")
    session_cookie = client.get_cookie(session_cookie_name)
    assert session_cookie is not None

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context()
        context.add_cookies([{
            "name": session_cookie.key,
            "value": session_cookie.value,
            "domain": "127.0.0.1",
            "path": "/",
            "httpOnly": True,
            "secure": False,
            "sameSite": "Lax",
        }])
        page = context.new_page()
        page.goto(f"{live_server}/kiralama/duzenle/{kiralama_id}", wait_until="networkidle")

        row = page.locator("#kalem-tablosu tbody tr").first
        assert "2x500,00" in row.inner_text()
        assert "+ 2.000,00 TL" in row.inner_text()
        assert "3.000,00 TL" in row.inner_text()
        assert page.locator('[name$="-nakliye_satis_fiyat"]').input_value() == "2000.00"
        page.reload(wait_until="networkidle")
        row = page.locator("#kalem-tablosu tbody tr").first
        assert "4.000,00 TL" not in row.inner_text()
        assert "3.000,00 TL" in row.inner_text()
        browser.close()
