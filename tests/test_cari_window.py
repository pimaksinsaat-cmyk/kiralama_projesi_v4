"""Cari dönem penceresi: calculate_window_amounts ve inclusive gün bölüşümü."""

from datetime import date
from decimal import Decimal

from app.services.cari_window import build_period_filtered_cari, calculate_window_amounts
from app.firmalar.routes import (
    _effective_kiralama_bilgi_tarih,
    _filter_kiralamalar_bilgi,
    _parse_kiralama_tab_iso_dates,
)


class Obj:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def test_kiralama_10_gun_plan_ornegi():
    """01.01–10.01 (10 gün) toplam, filtre 05.01–15.01 → 4 gün devir öncesi, 6 gün pencerede."""
    row = {
        'islem_turu': 'kiralama',
        'baslangic': date(2024, 1, 1),
        'bitis': date(2024, 1, 10),
        'gun_sayisi': 10,
        'toplam': 1000.0,
        'sort_date': date(2024, 1, 1),
        'id': 1,
    }
    bef, inn = calculate_window_amounts(row, date(2024, 1, 5), date(2024, 1, 15))
    assert bef + inn == Decimal('1000')
    assert bef == Decimal('400.00')
    assert inn == Decimal('600.00')


def test_instant_odeme_aralikta_ve_disinda():
    r_once = {'islem_turu': 'tahsilat', 'baslangic': date(2024, 6, 1), 'sort_date': date(2024, 6, 1), 'toplam': -50.0, 'id': 2}
    b1, i1 = calculate_window_amounts(r_once, date(2024, 6, 1), date(2024, 6, 30))
    assert b1 == Decimal('0')
    assert i1 == Decimal('-50')

    b2, i2 = calculate_window_amounts(r_once, date(2024, 7, 1), date(2024, 7, 31))
    assert b2 == Decimal('-50')
    assert i2 == Decimal('0')


def test_build_period_filtered_cari_kapanan_bakiye():
    rows = [
        {
            'islem_turu': 'kiralama',
            'baslangic': date(2024, 1, 1),
            'bitis': date(2024, 1, 10),
            'gun_sayisi': 10,
            'toplam': 100.0,
            'sort_date': date(2024, 1, 1),
            'id': 10,
            'form_no': 'F1',
        },
        {
            'islem_turu': 'tahsilat',
            'sort_date': date(2024, 1, 8),
            'baslangic': date(2024, 1, 8),
            'toplam': -30.0,
            'id': 11,
            'form_no': '-',
        },
    ]
    newest_first, opening, borc_p, alc_p, closing = build_period_filtered_cari(
        rows, date(2024, 1, 5), date(2024, 1, 15)
    )
    # 100 TL / 10 gün; start 05.01 → önce 4 gün = 40 TL, pencerede 6 gün = 60 TL
    assert opening == Decimal('40.00')
    tahsil_satir = next(r for r in newest_first if r['id'] == 11)
    kir_satir = next(r for r in newest_first if r['id'] == 10)
    assert kir_satir['toplam'] == 60.0
    assert tahsil_satir['toplam'] == -30.0
    eski_yeni = list(reversed(newest_first))
    run = opening
    for r in eski_yeni:
        run += Decimal(str(r['toplam']))
    assert run.quantize(Decimal('0.01')) == closing.quantize(Decimal('0.01'))
    assert Decimal(str(newest_first[0]['bakiye'])).quantize(Decimal('0.01')) == closing.quantize(
        Decimal('0.01')
    )


def test_kiralama_donem_sonrasi_tutar_doneme_eklenmez():
    row = {
        'islem_turu': 'kiralama',
        'baslangic': date(2024, 1, 1),
        'bitis': date(2024, 1, 31),
        'gun_sayisi': 31,
        'toplam': 3100.0,
        'sort_date': date(2024, 1, 1),
        'id': 20,
    }
    bef, inn = calculate_window_amounts(row, date(2024, 1, 10), date(2024, 1, 20))
    assert bef == Decimal('900.00')
    assert inn == Decimal('1100.00')


def test_kiralama_tamamen_donem_oncesi_devire_gider():
    row = {
        'islem_turu': 'kiralama',
        'baslangic': date(2024, 1, 1),
        'bitis': date(2024, 1, 10),
        'gun_sayisi': 10,
        'toplam': 1000.0,
    }
    bef, inn = calculate_window_amounts(row, date(2024, 2, 1), date(2024, 2, 29))
    assert bef == Decimal('1000.0')
    assert inn == Decimal('0')


def test_kiralama_tamamen_donem_sonrasi_yok_sayilir():
    row = {
        'islem_turu': 'kiralama',
        'baslangic': date(2024, 3, 1),
        'bitis': date(2024, 3, 10),
        'gun_sayisi': 10,
        'toplam': 1000.0,
    }
    bef, inn = calculate_window_amounts(row, date(2024, 2, 1), date(2024, 2, 29))
    assert bef == Decimal('0')
    assert inn == Decimal('0')


def test_negatif_harici_kiralama_oranlanir():
    row = {
        'islem_turu': 'harici_kiralama',
        'baslangic': date(2024, 1, 1),
        'bitis': date(2024, 1, 10),
        'gun_sayisi': 10,
        'toplam': -1000.0,
        'sort_date': date(2024, 1, 1),
        'id': 21,
    }
    bef, inn = calculate_window_amounts(row, date(2024, 1, 5), date(2024, 1, 8))
    assert bef == Decimal('-400.00')
    assert inn == Decimal('-400.00')


def test_kiralama_tab_parse_gecersiz_ve_ters_aralik_pasif():
    assert _parse_kiralama_tab_iso_dates('', '2024-01-31') is None
    assert _parse_kiralama_tab_iso_dates('2024-02-01', '2024-01-31') is None
    assert _parse_kiralama_tab_iso_dates('hata', '2024-01-31') is None


def test_kiralama_filtre_olusturma_tarihi_aralikta_gorunur():
    firma = Obj(kiralamalar=[
        Obj(id=1, kiralama_form_no='A', kiralama_olusturma_tarihi=date(2024, 1, 15), kalemler=[]),
        Obj(id=2, kiralama_form_no='B', kiralama_olusturma_tarihi=date(2024, 2, 15), kalemler=[]),
    ])
    rows, active, start, end = _filter_kiralamalar_bilgi(firma, '2024-01-01', '2024-01-31')
    assert active is True
    assert start == date(2024, 1, 1)
    assert end == date(2024, 1, 31)
    assert [r.id for r in rows] == [1]


def test_kiralama_filtre_olusturma_yoksa_ilk_kalem_baslangici():
    kiralama = Obj(
        id=1,
        kiralama_form_no='A',
        kiralama_olusturma_tarihi=None,
        created_at=None,
        kalemler=[
            Obj(kiralama_baslangici=date(2024, 2, 10)),
            Obj(kiralama_baslangici=date(2024, 1, 20)),
        ],
    )
    assert _effective_kiralama_bilgi_tarih(kiralama) == date(2024, 1, 20)
    firma = Obj(kiralamalar=[kiralama])
    rows, active, _, _ = _filter_kiralamalar_bilgi(firma, '2024-01-01', '2024-01-31')
    assert active is True
    assert rows == [kiralama]


def test_kiralama_filtre_ters_aralikta_klasik_liste():
    firma = Obj(kiralamalar=[
        Obj(id=1, kiralama_form_no='A', kiralama_olusturma_tarihi=date(2024, 1, 15), kalemler=[]),
    ])
    rows, active, start, end = _filter_kiralamalar_bilgi(firma, '2024-02-01', '2024-01-31')
    assert active is False
    assert start is None
    assert end is None
    assert [r.id for r in rows] == [1]
