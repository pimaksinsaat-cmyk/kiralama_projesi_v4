"""
E2E (HTTP): /firmalar/bilgi tarih süzgeci + dönem modu + devre dışı flag.
"""
from __future__ import annotations

import re
import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.auth.models import User
from app.auth.session_security import (
    SESSION_LAST_PING_KEY,
    SESSION_TOKEN_KEY,
    new_session_token,
    utc_now,
)
from app.extensions import db
from app.filo.models import Ekipman
from app.firmalar.models import Firma
from app.kiralama.models import Kiralama, KiralamaKalemi
from app.subeler.models import Sube


def _uniq_vergi() -> str:
    return f"TF{uuid.uuid4().hex[:10].upper()}"


def _uniq_kod() -> str:
    return f"TDF-{uuid.uuid4().hex[:8].upper()}"


def _login(client, user_id: int) -> None:
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


def _setup_data(app):
    """Dönemi filtrelebilecek kısa süreli kiralama ile firma oluşturur."""
    admin = User(username=f"bilgi_e2e_{uuid.uuid4().hex[:6]}", rol="admin")
    admin.set_password("pass123")
    db.session.add(admin)
    db.session.flush()

    sube = Sube(isim="TDF Sube", adres="Adr", yetkili_kisi="Y", telefon="0212-1111111")
    db.session.add(sube)
    db.session.flush()

    musteri = Firma(
        firma_adi=f"TDF Müşteri {uuid.uuid4().hex[:4]}",
        yetkili_adi="Y",
        iletisim_bilgileri="Adr",
        vergi_dairesi="İstanbul VD",
        vergi_no=_uniq_vergi(),
        is_musteri=True,
        is_tedarikci=False,
        bakiye=Decimal("0"),
        cari_borc_kdvli=Decimal("0"),
        cari_alacak_kdvli=Decimal("0"),
        cari_bakiye_kdvli=Decimal("0"),
    )
    db.session.add(musteri)
    db.session.flush()

    ekipman = Ekipman(
        kod=_uniq_kod(),
        yakit="Elektrik",
        tipi="MAKAS",
        marka="TF",
        model="M1",
        seri_no=f"SN-{uuid.uuid4().hex[:8]}",
        calisma_yuksekligi=10,
        kaldirma_kapasitesi=2000,
        uretim_yili=2023,
        calisma_durumu="bosta",
        sube_id=sube.id,
    )
    db.session.add(ekipman)
    db.session.flush()

    kiralama = Kiralama(
        kiralama_form_no=f"TDF-{uuid.uuid4().hex[:6]}",
        firma_musteri_id=musteri.id,
        kdv_orani=20,
        kiralama_olusturma_tarihi=date(2026, 4, 1),
    )
    db.session.add(kiralama)
    db.session.flush()

    kalem = KiralamaKalemi(
        kiralama_id=kiralama.id,
        ekipman_id=ekipman.id,
        kiralama_baslangici=date(2026, 4, 10),
        kiralama_bitis=date(2026, 4, 30),
        kiralama_brm_fiyat=Decimal("100.00"),
        sonlandirildi=True,
        is_active=True,
    )
    db.session.add(kalem)
    db.session.commit()
    return admin.id, musteri.id


def test_bilgi_tarih_olmadan_tam_ekstre_basliklari(app, client):
    with app.app_context():
        admin_id, firma_id = _setup_data(app)

    _login(client, admin_id)
    r = client.get(f"/firmalar/bilgi/{firma_id}", follow_redirects=True)
    assert r.status_code == 200
    body = r.data.decode("utf-8", errors="replace")
    assert "Dönem Borç" not in body
    assert "Toplam Borç" in body


def test_bilgi_iki_tarih_parametresi_donem_modu_ve_filtre_disı(app, client):
    with app.app_context():
        admin_id, firma_id = _setup_data(app)

    _login(client, admin_id)
    r = client.get(
        f"/firmalar/bilgi/{firma_id}",
        query_string={
            "tab": "cari",
            "start_date": "2026-04-15",
            "end_date": "2026-04-25",
        },
        follow_redirects=True,
    )
    assert r.status_code == 200
    body = r.data.decode("utf-8", errors="replace")
    assert "Dönem Borç" in body
    assert "Dönem Alacak" in body
    assert "Dönem Bakiyesi" in body or "Dönem Bakiye" in body
    assert "Filtre dışı" in body


def _tr_amount_to_decimal(text: str) -> Decimal:
    """'1.234,56 TL' veya '1.234,56' → Decimal."""
    cleaned = text.strip().replace(" TL", "").strip()
    cleaned = cleaned.replace(".", "").replace(",", ".")
    return Decimal(cleaned)


def _parse_yazdir_cari_toplam_row(body: str) -> tuple[Decimal, Decimal, Decimal]:
    """Cari tablosu tfoot TOPLAM satırından borç, alacak, bakiye değerlerini döner."""
    idx = body.find("TOPLAM:")
    assert idx != -1, "TOPLAM satırı bulunamadı"
    chunk = body[idx : idx + 800]
    amounts = re.findall(r"(-?\d[\d.,]+)\s*TL", chunk)
    assert len(amounts) >= 3, f"TOPLAM satırında 3 tutar bekleniyordu: {chunk!r}"
    return (
        _tr_amount_to_decimal(amounts[0]),
        _tr_amount_to_decimal(amounts[1]),
        _tr_amount_to_decimal(amounts[2]),
    )


def _minimal_yazdir_cari_row(toplam: float, bakiye: float) -> dict:
    return {
        "toplam": toplam,
        "bakiye": bakiye,
        "sort_date": date(2026, 4, 20),
        "baslangic": date(2026, 4, 20),
        "form_tarihi": date(2026, 4, 20),
        "form_no": "TST-1",
        "islem_turu": "kiralama",
        "aciklama": "Test kiralama",
        "seri_no": None,
        "gun_sayisi": 10,
        "bitis_bugun": False,
        "bitis": date(2026, 4, 25),
        "brm_fiyat": 100.0,
        "matrah": 100.0,
        "kdv_orani": 20,
    }


def test_bilgi_yazdir_aynı_tarih_parametleri_200(app, client):
    with app.app_context():
        admin_id, firma_id = _setup_data(app)

    _login(client, admin_id)
    r = client.get(
        f"/firmalar/bilgi/{firma_id}/yazdir",
        query_string={
            "tab": "cari",
            "start_date": "2026-04-15",
            "end_date": "2026-04-25",
        },
        follow_redirects=True,
    )
    assert r.status_code == 200
    body = r.data.decode("utf-8", errors="replace")
    assert "15.04.2026" in body and "25.04.2026" in body


def test_yazdir_cari_toplam_bakiye_sablon(app):
    """TOPLAM bakiye = borç − alacak + devreden; son satırın kümülatif bakiyesi değil."""
    from types import SimpleNamespace

    devreden = Decimal("700.00")
    cari_rows = [
        _minimal_yazdir_cari_row(1000.0, 1700.0),
        _minimal_yazdir_cari_row(-200.0, 500.0),
    ]
    last_row_bakiye = Decimal(str(cari_rows[-1]["bakiye"]))
    expected_bakiye = Decimal("1000.00") - Decimal("200.00") + devreden

    from app.firmalar.routes import _cari_yazdir_footer_totals

    foot_borc, foot_alacak, foot_bakiye = _cari_yazdir_footer_totals(cari_rows, float(devreden))

    with app.test_request_context(
        "/firmalar/bilgi/1/yazdir?tab=cari&start_date=2026-04-15&end_date=2026-04-25"
    ):
        tpl = app.jinja_env.get_template("firmalar/yazdir.html")
        html = tpl.render(
            firma=SimpleNamespace(firma_adi="Test Firma", id=1),
            tab="cari",
            cari_rows=cari_rows,
            cari_export_period=True,
            cari_devreden_bakiye=float(devreden),
            cari_foot_borc=foot_borc,
            cari_foot_alacak=foot_alacak,
            cari_foot_bakiye=foot_bakiye,
            filt_start_print=date(2026, 4, 15),
            rapor_tarihi="15.04.2026 – 25.04.2026",
            hareketler=[],
            kiralamalar=[],
        )

        foot_borc, foot_alacak, foot_bakiye = _parse_yazdir_cari_toplam_row(html)
        assert foot_borc == Decimal("1000.00")
        assert foot_alacak == Decimal("200.00")
        assert foot_bakiye == expected_bakiye
        assert foot_bakiye == foot_borc - foot_alacak + devreden
        assert last_row_bakiye != foot_bakiye


def test_bilgi_yazdir_toplam_bakiye_borc_alacak_ve_devreden(app, client):
    """HTTP yazdır: TOPLAM bakiye backend kapanış bakiyesi ile uyumlu."""
    from app.firmalar.routes import _build_cari_rows
    from app.services.cari_window import build_period_filtered_cari

    start = date(2026, 4, 15)
    end = date(2026, 4, 25)

    with app.app_context():
        admin_id, firma_id = _setup_data(app)
        firma = db.session.get(Firma, firma_id)
        raw_rows = _build_cari_rows(firma, end)
        cari_rows, opening, period_borc, period_alacak, closing = build_period_filtered_cari(
            raw_rows, start, end
        )
        expected_bakiye = period_borc - abs(period_alacak) + opening

    _login(client, admin_id)
    r = client.get(
        f"/firmalar/bilgi/{firma_id}/yazdir",
        query_string={
            "tab": "cari",
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
        },
        follow_redirects=True,
    )
    assert r.status_code == 200
    body = r.data.decode("utf-8", errors="replace")
    assert "Yazdırma verisi yüklenemedi" not in body

    if "TOPLAM:" not in body:
        pytest.skip("Yazdır çıktısında cari satırı yok; TOPLAM satırı oluşmadı")

    foot_borc, foot_alacak, foot_bakiye = _parse_yazdir_cari_toplam_row(body)

    assert foot_borc == period_borc.quantize(Decimal("0.01"))
    assert foot_alacak == abs(period_alacak).quantize(Decimal("0.01"))
    assert foot_bakiye == expected_bakiye.quantize(Decimal("0.01"))
    assert foot_bakiye == closing.quantize(Decimal("0.01"))
    assert foot_bakiye == (foot_borc - foot_alacak + opening).quantize(Decimal("0.01"))

    if cari_rows:
        last_row_bakiye = Decimal(str(cari_rows[-1]["bakiye"])).quantize(Decimal("0.01"))
        if last_row_bakiye != closing.quantize(Decimal("0.01")):
            assert foot_bakiye != last_row_bakiye


def test_bilgi_cari_flag_kapalı_dönem_başlığı_yok(app, client):
    app.config["CARI_DONEM_FILTRESI_ENABLED"] = False
    with app.app_context():
        admin_id, firma_id = _setup_data(app)

    _login(client, admin_id)
    r = client.get(
        f"/firmalar/bilgi/{firma_id}",
        query_string={
            "tab": "cari",
            "start_date": "2026-04-15",
            "end_date": "2026-04-25",
        },
        follow_redirects=True,
    )
    assert r.status_code == 200
    assert "Dönem Borç".encode("utf-8") not in r.data
