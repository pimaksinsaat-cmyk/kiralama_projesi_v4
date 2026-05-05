"""firma bilgi: kiralama listesi tarih aralığı süzgeci (birim, DB yok)."""

from datetime import date, datetime, timezone
from types import SimpleNamespace

from app.firmalar.routes import (
    _effective_kiralama_bilgi_tarih,
    _kiralamalar_filtered_by_olusturma_tarihi,
    _parse_kiralama_tab_iso_dates,
)


def test_kiralama_filters_by_olusturma_when_in_window():
    a = SimpleNamespace(id=1, kiralama_olusturma_tarihi=date(2026, 3, 5))
    b = SimpleNamespace(id=2, kiralama_olusturma_tarihi=date(2026, 6, 1))
    none_d = SimpleNamespace(
        id=3,
        kiralama_olusturma_tarihi=None,
        kalemler=[SimpleNamespace(kiralama_baslangici=date(2026, 3, 20))],
    )
    filt = _kiralamalar_filtered_by_olusturma_tarihi(
        [a, b, none_d],
        date(2026, 3, 1),
        date(2026, 3, 31),
    )
    assert {x.id for x in filt} == {1, 3}


def test_kiralama_filt_no_olusturma_use_created_at():
    k = SimpleNamespace(id=10, kiralama_olusturma_tarihi=date(2025, 1, 1))
    nd = SimpleNamespace(
        id=11,
        kiralama_olusturma_tarihi=None,
        kalemler=[],
        created_at=datetime(2026, 4, 15, 12, 0, 0, tzinfo=timezone.utc),
    )
    filt = _kiralamalar_filtered_by_olusturma_tarihi(
        [k, nd],
        date(2026, 4, 1),
        date(2026, 4, 30),
    )
    assert [x.id for x in filt] == [11]


def test_kiralama_filt_na_without_fallback_excluded():
    ghost = SimpleNamespace(
        id=99,
        kiralama_olusturma_tarihi=None,
        kalemler=[],
        created_at=None,
    )
    filt = _kiralamalar_filtered_by_olusturma_tarihi(
        [ghost],
        date(2026, 5, 1),
        date(2026, 5, 31),
    )
    assert filt == []


def test_effective_kiralama_tarih_min_kalem_over_created():
    olu_later = SimpleNamespace(
        kiralama_olusturma_tarihi=date(2026, 5, 1),
        kalemler=[SimpleNamespace(kiralama_baslangici=date(2026, 1, 1))],
        created_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
    )
    assert _effective_kiralama_bilgi_tarih(olu_later) == date(2026, 5, 1)

    ohne_olu = SimpleNamespace(
        kiralama_olusturma_tarihi=None,
        kalemler=[
            SimpleNamespace(kiralama_baslangici=date(2024, 1, 1)),
            SimpleNamespace(kiralama_baslangici=date(2023, 6, 1)),
        ],
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    assert _effective_kiralama_bilgi_tarih(ohne_olu) == date(2023, 6, 1)


def test_parse_kiralama_tab_iso_dates_requires_both_valid():
    assert _parse_kiralama_tab_iso_dates(None, "2026-01-01") is None
    assert _parse_kiralama_tab_iso_dates("2026-01-01", None) is None
    assert _parse_kiralama_tab_iso_dates("   ", "2026-01-01") is None
    assert _parse_kiralama_tab_iso_dates("2026-02-30", "2026-03-01") is None
    p = _parse_kiralama_tab_iso_dates("2026-03-01", "2026-03-31")
    assert p is not None
    assert p[0].isoformat() == "2026-03-01"
    assert p[1].isoformat() == "2026-03-31"
