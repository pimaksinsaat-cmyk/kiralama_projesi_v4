"""
Audit subcontractor transport ledger rows.

This script is read-only. It reports:
  1. Legacy standalone subcontractor rows using "Nakliye Taşeron Gideri:".
  2. Duplicate active "Dönüş Nakliye:" rows for the same firm/form/line item.
  3. Line items that have both outbound and return subcontractor transport rows.

Usage:
  python scripts/audit_taseron_nakliye_cari.py
"""

import os
import sys
from collections import defaultdict

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from app import create_app
from app.cari.models import HizmetKaydi
from app.extensions import db
from app.firmalar.models import Firma
from app.kiralama.models import KiralamaKalemi
from app.nakliyeler.models import Nakliye


def _firma_adi(firma_id):
    firma = db.session.get(Firma, firma_id)
    return firma.firma_adi if firma else f"firma_id={firma_id}"


def _print_rows(title, rows, formatter):
    print(f"\n{title}: {len(rows)}")
    for row in rows:
        print(formatter(row))


def main():
    app = create_app()
    with app.app_context():
        legacy_hidden = (
            HizmetKaydi.query
            .join(Nakliye, Nakliye.id == HizmetKaydi.ozel_id)
            .filter(
                HizmetKaydi.yon == 'gelen',
                HizmetKaydi.is_deleted == False,
                HizmetKaydi.nakliye_id.is_(None),
                HizmetKaydi.ozel_id.isnot(None),
                HizmetKaydi.aciklama.like('Nakliye Taşeron Gideri:%'),
            )
            .order_by(HizmetKaydi.id.asc())
            .all()
        )

        donus_rows = (
            HizmetKaydi.query
            .filter(
                HizmetKaydi.yon == 'gelen',
                HizmetKaydi.is_deleted == False,
                HizmetKaydi.ozel_id.isnot(None),
                HizmetKaydi.aciklama.like('Dönüş Nakliye:%'),
            )
            .order_by(HizmetKaydi.firma_id.asc(), HizmetKaydi.fatura_no.asc(), HizmetKaydi.ozel_id.asc(), HizmetKaydi.id.asc())
            .all()
        )
        grouped_donus = defaultdict(list)
        for row in donus_rows:
            grouped_donus[(row.firma_id, row.fatura_no, row.ozel_id)].append(row)
        duplicate_donus = [rows for rows in grouped_donus.values() if len(rows) > 1]

        taseron_rows = (
            HizmetKaydi.query
            .filter(
                HizmetKaydi.yon == 'gelen',
                HizmetKaydi.is_deleted == False,
                HizmetKaydi.ozel_id.isnot(None),
                HizmetKaydi.aciklama.like('Taşeron Nakliye Bedeli%'),
            )
            .order_by(HizmetKaydi.firma_id.asc(), HizmetKaydi.fatura_no.asc(), HizmetKaydi.ozel_id.asc(), HizmetKaydi.id.asc())
            .all()
        )
        has_gidis = {(r.firma_id, r.fatura_no, r.ozel_id): r for r in taseron_rows}
        gidis_and_donus = [
            (has_gidis[key], rows)
            for key, rows in grouped_donus.items()
            if key in has_gidis
        ]

        _print_rows(
            "LEGACY_STANDALONE_TASERON_VISIBLE_AFTER_FIX",
            legacy_hidden,
            lambda h: (
                f"id={h.id} firma={_firma_adi(h.firma_id)} nakliye_id={h.ozel_id} "
                f"tarih={h.islem_tarihi or h.tarih} tutar={h.tutar} aciklama={h.aciklama}"
            ),
        )

        print(f"\nDUPLICATE_DONUS_NAKLIYE_GROUPS: {len(duplicate_donus)}")
        for rows in duplicate_donus:
            first = rows[0]
            ids = ",".join(str(r.id) for r in rows)
            total = sum((r.tutar or 0) for r in rows)
            print(
                f"firma={_firma_adi(first.firma_id)} fatura={first.fatura_no} "
                f"ozel_id={first.ozel_id} ids={ids} toplam={total}"
            )

        print(f"\nGIDIS_AND_DONUS_TASERON_GROUPS_INFO_ONLY: {len(gidis_and_donus)}")
        for gidis, donus_list in gidis_and_donus:
            kalem = db.session.get(KiralamaKalemi, gidis.ozel_id)
            form_no = gidis.fatura_no or (kalem.kiralama.kiralama_form_no if kalem and kalem.kiralama else '-')
            donus_ids = ",".join(str(r.id) for r in donus_list)
            print(
                f"firma={_firma_adi(gidis.firma_id)} form={form_no} kalem={gidis.ozel_id} "
                f"gidis_id={gidis.id} donus_ids={donus_ids}"
            )

        print("\nNo database changes were written.")


if __name__ == "__main__":
    main()
