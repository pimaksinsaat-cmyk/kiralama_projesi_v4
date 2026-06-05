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
from app.subeler.models import Sube
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
    session_cookie = next(
        (cookie for cookie in client.cookie_jar if cookie.name == session_cookie_name),
        None,
    )
    assert session_cookie is not None, "Test session cookie not found"

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context()
        context.add_cookies([
            {
                "name": session_cookie.name,
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
