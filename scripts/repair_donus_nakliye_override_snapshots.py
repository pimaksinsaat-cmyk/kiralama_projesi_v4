"""Gidis-gelis form toplamının yarısına eşit donus override snapshot'larını temizler.

Varsayılan mod read-only dry-run'dır. --apply yalnızca şu kayıtları NULL yapar:
  - donus_nakliye_fatura_et = True
  - donus_nakliye_satis_fiyat is not None
  - override == nakliye_satis_fiyat / 2 (0.01 quantize)

Bilinçli farklı tutarlar, tek yön + ek dönüş ve 0 TL override'lar yalnızca raporlanır.
Sefer / cari tutarlarına dokunulmaz (zaten aynı yarı).
"""

from __future__ import annotations

import argparse
from decimal import Decimal

from app import create_app
from app.extensions import db
from app.kiralama.models import KiralamaKalemi
from app.services.kiralama_services import money_equal, quantize_money, to_decimal


def _classify(kalem: KiralamaKalemi):
    override = kalem.donus_nakliye_satis_fiyat
    if override is None:
        return None

    override_q = quantize_money(override)
    total = to_decimal(kalem.nakliye_satis_fiyat)
    half = quantize_money(total / Decimal('2')) if kalem.donus_nakliye_fatura_et else Decimal('0.00')
    form_no = kalem.kiralama.kiralama_form_no if kalem.kiralama else ''

    base = {
        'form': form_no,
        'kalem_id': kalem.id,
        'nakliye_toplam': total,
        'override': override_q,
        'half': half,
        'donus_fatura_et': bool(kalem.donus_nakliye_fatura_et),
    }

    if kalem.donus_nakliye_fatura_et and money_equal(override_q, half):
        return 'normalize', base
    if override_q == Decimal('0.00'):
        return 'zero_manual', base
    if not kalem.donus_nakliye_fatura_et:
        return 'one_way_extra', base
    return 'intentional', base


def main(apply: bool = False):
    app = create_app()
    with app.app_context():
        buckets = {
            'normalize': [],
            'intentional': [],
            'one_way_extra': [],
            'zero_manual': [],
        }
        for kalem in KiralamaKalemi.query.filter(
            KiralamaKalemi.is_deleted == False,
            KiralamaKalemi.donus_nakliye_satis_fiyat.isnot(None),
        ).order_by(KiralamaKalemi.id.asc()).all():
            result = _classify(kalem)
            if not result:
                continue
            kind, info = result
            buckets[kind].append((kalem, info))

        print(f"normalize_aday={len(buckets['normalize'])}")
        print(f"bilincli_farkli={len(buckets['intentional'])}")
        print(f"tek_yon_ek_donus={len(buckets['one_way_extra'])}")
        print(f"sifir_override={len(buckets['zero_manual'])}")

        for kalem, info in buckets['normalize']:
            print(
                f"NORMALIZE form={info['form']} kalem={info['kalem_id']} "
                f"toplam={info['nakliye_toplam']} override={info['override']}"
            )
        for _kalem, info in buckets['intentional']:
            print(
                f"KORU_FARKLI form={info['form']} kalem={info['kalem_id']} "
                f"toplam={info['nakliye_toplam']} override={info['override']} half={info['half']}"
            )
        for _kalem, info in buckets['one_way_extra']:
            print(
                f"KORU_TEK_YON form={info['form']} kalem={info['kalem_id']} "
                f"override={info['override']}"
            )
        for _kalem, info in buckets['zero_manual']:
            print(
                f"KORU_SIFIR form={info['form']} kalem={info['kalem_id']} "
                f"donus_fatura_et={info['donus_fatura_et']}"
            )

        if not apply:
            db.session.rollback()
            print('dry_run=1 apply_edilmedi')
            return

        for kalem, _info in buckets['normalize']:
            kalem.donus_nakliye_satis_fiyat = None
            db.session.add(kalem)
        db.session.commit()
        print(f"normalize_uygulandi={len(buckets['normalize'])}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    main(apply=args.apply)
