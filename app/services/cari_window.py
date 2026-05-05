"""
Cari satırlarında tarih penceresi (dönem) payları: devir bakiyesi + dönem listesi için ortak hesap.
firma_services.build_cari_rows ile uyumlu inclusive gün sayımı (+1).
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Mapping, Tuple


TWOPLACES = Decimal('0.01')
ACCRUAL_TYPES = frozenset({'kiralama', 'harici_kiralama'})


def inclusive_days(lo: date, hi: date) -> int:
    """Her iki uç dahil gün sayısı; lo > hi ise 0."""
    if lo > hi:
        return 0
    return (hi - lo).days + 1


def calculate_window_amounts(
    row: Mapping[str, Any],
    start_date: date,
    end_date: date,
) -> Tuple[Decimal, Decimal]:
    """
    Satırın toplam işaretli tutarına göre pencere öncesi ve pencere içi payları döner.

    Returns:
        (amount_before_start, amount_in_window)
    """
    total = Decimal(str(row.get('toplam') or 0))
    if total == Decimal('0'):
        return Decimal('0'), Decimal('0')

    row_type = row.get('islem_turu')
    baslangic = row.get('baslangic')
    bitis = row.get('bitis')
    gun_sayisi = row.get('gun_sayisi')

    if row_type in ACCRUAL_TYPES and baslangic is not None and bitis is not None:
        try:
            gs = int(gun_sayisi) if gun_sayisi is not None else 0
        except (TypeError, ValueError):
            gs = 0
        if gs > 0:
            acc_start = baslangic
            acc_end = bitis

            if acc_start > end_date:
                return Decimal('0'), Decimal('0')
            # Tamamen filtre başlangıcından önce bitmiş kiralama: tamamı devir payı
            if acc_end < start_date:
                return total, Decimal('0')

            if acc_start >= start_date:
                n_before = 0
            else:
                hi_bef = min(acc_end, start_date - timedelta(days=1))
                n_before = inclusive_days(acc_start, hi_bef)

            lo_in = max(acc_start, start_date)
            hi_in = min(acc_end, end_date)
            n_in = inclusive_days(lo_in, hi_in)
            if n_in <= 0:
                return Decimal('0'), Decimal('0')

            n_acc = gs
            daily = total / Decimal(n_acc)
            amt_before = (daily * Decimal(n_before)).quantize(TWOPLACES, rounding=ROUND_HALF_UP)
            amt_in = (daily * Decimal(n_in)).quantize(TWOPLACES, rounding=ROUND_HALF_UP)

            # Yuvarlama farkini yalnizca satirin tamamini pencere icinde gordugumuzde
            # doneme ekle. Pencere bitisinden sonraki gunler donem tutarina karismamali.
            if acc_start >= start_date and acc_end <= end_date:
                residual = total - amt_before - amt_in
                amt_in = (amt_in + residual).quantize(TWOPLACES, rounding=ROUND_HALF_UP)

            return amt_before, amt_in

    # Anlık (tek tarihli) işlemler
    d = row.get('sort_date') or row.get('baslangic') or row.get('form_tarihi')
    if d is None:
        return Decimal('0'), Decimal('0')
    if hasattr(d, 'date') and callable(getattr(d, 'date', None)):
        try:
            d = d.date()  # type: ignore[assignment, union-attr]
        except Exception:
            pass

    if d > end_date:
        return Decimal('0'), Decimal('0')

    if d < start_date:
        return total, Decimal('0')

    if start_date <= d <= end_date:
        return Decimal('0'), total

    return Decimal('0'), Decimal('0')


def _row_sort_key_asc(row: Mapping[str, Any]) -> Tuple[date, int]:
    d = row.get('sort_date') or row.get('baslangic') or row.get('form_tarihi')
    dd = date.min if d is None else d
    if hasattr(dd, 'date') and callable(getattr(dd, 'date', None)):
        try:
            dd = dd.date()  # type: ignore[union-attr, assignment]
        except Exception:
            dd = date.min
    rid = row.get('id')
    try:
        ri = int(rid) if rid is not None else 0
    except (TypeError, ValueError):
        ri = 0
    return (dd, ri)


def build_period_filtered_cari(
    rows: list[dict[str, Any]],
    start_date: date,
    end_date: date,
) -> Tuple[list[dict[str, Any]], Decimal, Decimal, Decimal, Decimal]:
    """
    Dönem filtresine göre cari satır listesi (yeniden-eski), finans özeti ve devir dahil bakiye akışı.

    Returns:
        cari_rows_newest_first, opening_balance,
        period_borc (pozitif tutarların toplamı),
        period_alacak (negatif tutarların toplamı, işaretli),
        closing_balance (= opening + tüm inn toplamı)
    """
    triples = []
    opening = Decimal('0')
    r: dict[str, Any]
    for r in rows:
        bef, inn = calculate_window_amounts(r, start_date, end_date)
        opening += bef
        triples.append((r, bef, inn))

    triples.sort(key=lambda t: _row_sort_key_asc(t[0]))

    borc_period = Decimal('0')
    alacak_period = Decimal('0')
    for _, _, inn in triples:
        if inn > 0:
            borc_period += inn
        elif inn < Decimal('0'):
            alacak_period += inn

    net_in_period = borc_period + alacak_period
    closing = opening + net_in_period

    filtered_old_to_new: list[dict[str, Any]] = []
    running = opening
    for row0, _, inn in triples:
        if inn == Decimal('0'):
            continue
        row = dict(row0)
        row['toplam_raw'] = row0.get('toplam')
        row['toplam'] = float(inn)
        row['bakiye_original'] = row0.get('bakiye')
        running += inn
        row['bakiye'] = float(running.quantize(TWOPLACES, rounding=ROUND_HALF_UP))
        filtered_old_to_new.append(row)

    cari_rows_newest_first = list(reversed(filtered_old_to_new))
    return cari_rows_newest_first, opening, borc_period, alacak_period, closing


def row_visible_in_period(
    row: Mapping[str, Any],
    start_date: date,
    end_date: date,
) -> bool:
    """Liste için: kiralama çizgisi kesişimi veya tek günlük hareket pencerede."""
    row_type = row.get('islem_turu')
    baslangic = row.get('baslangic')
    bitis = row.get('bitis')

    if row_type in ACCRUAL_TYPES and baslangic:
        etkin_bitis = bitis if bitis else end_date
        return baslangic <= end_date and etkin_bitis >= start_date

    d = row.get('sort_date') or row.get('baslangic') or row.get('form_tarihi')
    return bool(d and start_date <= d <= end_date)
