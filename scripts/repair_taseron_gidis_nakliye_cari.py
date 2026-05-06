"""
Repair subcontractor outbound transport ledger rows for rental form line items.

Default mode is dry-run. Use --apply to write changes.
"""

import argparse
import os
import sys
from collections import Counter
from datetime import datetime, timezone, date
from decimal import Decimal

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from app import create_app
from app.extensions import db
from app.cari.models import HizmetKaydi
from app.firmalar.models import Firma
from app.kiralama.models import KiralamaKalemi
from app.nakliyeler.models import Nakliye
from app.services.cari_services import _sync_firma_bakiye
from app.services.kiralama_services import KiralamaService, to_decimal


TASERON_PREFIX = "Ta\u015feron Nakliye Bedeli"
AMBIGUOUS_TRIP = object()


def _same_decimal(left, right):
    return to_decimal(left) == to_decimal(right)


def _same_kdv(hizmet, expected_kdv):
    current = hizmet.nakliye_alis_kdv
    if current is None:
        current = hizmet.kdv_orani
    return current == expected_kdv


def _makine_adi(kalem):
    if kalem.ekipman:
        return kalem.ekipman.kod or kalem.ekipman.marka or "Makine"
    return kalem.harici_ekipman_marka or "D\u0131\u015f Ekipman"


def _gidis_aciklama(form_no, kalem_id):
    return f"Gidi\u015f: {form_no} #{kalem_id}"


def _legacy_gidis_aciklama(form_no):
    return f"Gidi\u015f: {form_no}"


def _find_or_report_gidis_nakliye(kiralama, kalem, counters, details):
    form_no = kiralama.kiralama_form_no or ''
    exact = Nakliye.query.filter(
        Nakliye.kiralama_id == kiralama.id,
        Nakliye.aciklama == _gidis_aciklama(form_no, kalem.id),
    ).first()
    if exact:
        return exact

    legacy = Nakliye.query.filter(
        Nakliye.kiralama_id == kiralama.id,
        Nakliye.aciklama == _legacy_gidis_aciklama(form_no),
    ).order_by(Nakliye.id.asc()).all()

    if len(legacy) == 1:
        return legacy[0]
    if len(legacy) > 1:
        counters["AMBIGUOUS_TRIP"] += 1
        details.append(
            f"AMBIGUOUS_TRIP | form={form_no} kalem={kalem.id} "
            f"legacy_nakliye_ids={','.join(str(n.id) for n in legacy)}"
        )
        return AMBIGUOUS_TRIP
    return None


def _sync_gidis_nakliye(kiralama, kalem, dry_run, counters, details):
    nakliye = _find_or_report_gidis_nakliye(kiralama, kalem, counters, details)
    if nakliye is AMBIGUOUS_TRIP:
        return None
    if not nakliye:
        counters["TRIP_MISSING"] += 1
        details.append(f"TRIP_MISSING | form={kiralama.kiralama_form_no} kalem={kalem.id}")
        if dry_run:
            return None
        nakliye = Nakliye(kiralama_id=kiralama.id)

    makine_adi = _makine_adi(kalem)
    firma_adi = kiralama.firma_musteri.firma_adi if kiralama.firma_musteri else "Musteri"
    is_yeri = (kiralama.makine_calisma_adresi or '').strip() or firma_adi
    gidis_sube_adi = kalem.ekipman.sube.isim if (kalem.ekipman and kalem.ekipman.sube) else None
    if gidis_sube_adi:
        guzergah = (
            f"{makine_adi} {gidis_sube_adi} \u015fubesinden "
            f"{firma_adi} firmas\u0131n\u0131n {is_yeri}'ne g\u00f6t\u00fcr\u00fcld\u00fc"
        )
    else:
        guzergah = f"{makine_adi} {firma_adi} firmas\u0131na g\u00f6t\u00fcr\u00fcld\u00fc ({is_yeri})"

    expected = {
        "firma_id": kiralama.firma_musteri_id,
        "tarih": kalem.kiralama_baslangici,
        "islem_tarihi": kalem.kiralama_baslangici,
        "guzergah": guzergah,
        "tutar": KiralamaService._get_gidis_nakliye_satis(kalem),
        "kdv_orani": (
            kalem.nakliye_satis_kdv
            if kalem.nakliye_satis_kdv is not None
            else (kiralama.kdv_orani if kiralama.kdv_orani is not None else 20)
        ),
        "tevkifat_orani": kalem.nakliye_satis_tevkifat_oran or None,
        "aciklama": _gidis_aciklama(kiralama.kiralama_form_no or '', kalem.id),
        "nakliye_tipi": "taseron",
        "taseron_firma_id": kalem.nakliye_tedarikci_id,
        "taseron_maliyet": to_decimal(kalem.nakliye_alis_fiyat),
        "plaka": "D\u0131\u015f Nakliye",
        "arac_id": None,
        "is_active": True,
    }

    changed = False
    for attr, value in expected.items():
        current = getattr(nakliye, attr)
        if attr in ("tutar", "taseron_maliyet"):
            differs = not _same_decimal(current, value)
        else:
            differs = current != value
        if differs:
            changed = True
            if not dry_run:
                setattr(nakliye, attr, value)

    if changed:
        counters["TRIP_UPDATED"] += 1
        details.append(f"TRIP_UPDATED | form={kiralama.kiralama_form_no} kalem={kalem.id}")
    else:
        counters["TRIP_OK"] += 1

    if not dry_run:
        nakliye.hesapla_ve_guncelle()
        db.session.add(nakliye)
    return nakliye


def _active_taseron_hizmetleri(kalem):
    return HizmetKaydi.query.filter(
        HizmetKaydi.firma_id == kalem.nakliye_tedarikci_id,
        HizmetKaydi.ozel_id == kalem.id,
        HizmetKaydi.yon == 'gelen',
        HizmetKaydi.fatura_no == kalem.kiralama.kiralama_form_no,
        HizmetKaydi.aciklama.like(f"{TASERON_PREFIX}%"),
        HizmetKaydi.is_deleted == False,
    ).order_by(HizmetKaydi.id.asc()).all()


def _sync_taseron_cari(kalem, dry_run, counters, details, affected_firmalar):
    kiralama = kalem.kiralama
    hizmetler = _active_taseron_hizmetleri(kalem)
    hizmet = hizmetler[0] if hizmetler else None
    expected_tutar = to_decimal(kalem.nakliye_alis_fiyat)
    expected_kdv = kalem.nakliye_alis_kdv
    makine_adi = _makine_adi(kalem)

    if not hizmet:
        counters["MISSING"] += 1
        details.append(
            f"MISSING | firma={kalem.nakliye_tedarikci_id} "
            f"form={kiralama.kiralama_form_no} kalem={kalem.id} tutar={expected_tutar}"
        )
        if dry_run:
            return
        hizmet = HizmetKaydi(yon='gelen')
    else:
        if not _same_decimal(hizmet.tutar, expected_tutar):
            counters["AMOUNT_MISMATCH"] += 1
            details.append(
                f"AMOUNT_MISMATCH | hizmet={hizmet.id} form={kiralama.kiralama_form_no} "
                f"kalem={kalem.id} eski={hizmet.tutar} yeni={expected_tutar}"
            )
        if not _same_kdv(hizmet, expected_kdv):
            counters["KDV_MISMATCH"] += 1
            details.append(
                f"KDV_MISMATCH | hizmet={hizmet.id} form={kiralama.kiralama_form_no} "
                f"kalem={kalem.id} eski={hizmet.nakliye_alis_kdv or hizmet.kdv_orani} yeni={expected_kdv}"
            )

    if len(hizmetler) > 1:
        counters["DUPLICATE"] += len(hizmetler) - 1
        duplicate_ids = [str(h.id) for h in hizmetler[1:]]
        details.append(
            f"DUPLICATE | form={kiralama.kiralama_form_no} kalem={kalem.id} "
            f"soft_delete_ids={','.join(duplicate_ids)}"
        )
        if not dry_run:
            for fazla in hizmetler[1:]:
                fazla.is_deleted = True
                fazla.is_active = False
                fazla.deleted_at = datetime.now(timezone.utc)
                db.session.add(fazla)

    if not dry_run:
        hizmet.firma_id = kalem.nakliye_tedarikci_id
        hizmet.tarih = kalem.kiralama_baslangici or date.today()
        hizmet.islem_tarihi = kalem.kiralama_baslangici or date.today()
        hizmet.tutar = expected_tutar
        hizmet.yon = 'gelen'
        hizmet.fatura_no = kiralama.kiralama_form_no
        hizmet.ozel_id = kalem.id
        hizmet.aciklama = f"{TASERON_PREFIX} ({makine_adi}) - {kiralama.kiralama_form_no}"
        hizmet.nakliye_alis_kdv = expected_kdv
        hizmet.kdv_orani = None
        hizmet.is_deleted = False
        hizmet.is_active = True
        db.session.add(hizmet)
        affected_firmalar.add(kalem.nakliye_tedarikci_id)


def _candidate_kalemler():
    return (
        KiralamaKalemi.query
        .join(KiralamaKalemi.kiralama)
        .filter(
            KiralamaKalemi.is_deleted == False,
            KiralamaKalemi.is_harici_nakliye == True,
            KiralamaKalemi.nakliye_tedarikci_id.isnot(None),
            KiralamaKalemi.nakliye_tedarikci_id > 0,
            KiralamaKalemi.nakliye_alis_fiyat > 0,
        )
        .order_by(KiralamaKalemi.id.asc())
        .all()
    )


def main(apply=False):
    dry_run = not apply
    app = create_app()
    with app.app_context():
        counters = Counter()
        details = []
        affected_firmalar = set()
        kalemler = _candidate_kalemler()

        print(("[DRY-RUN]" if dry_run else "[APPLY]") + f" Candidate line items: {len(kalemler)}")
        for kalem in kalemler:
            _sync_gidis_nakliye(kalem.kiralama, kalem, dry_run, counters, details)
            _sync_taseron_cari(kalem, dry_run, counters, details, affected_firmalar)

        if not dry_run:
            for firma_id in sorted(affected_firmalar):
                _sync_firma_bakiye(firma_id)
            db.session.commit()

        for line in details:
            print(line)

        print("\nSUMMARY")
        for key in sorted(counters):
            print(f"{key}: {counters[key]}")
        if dry_run:
            print("\nNo database changes were written. Re-run with --apply to repair.")
        else:
            names = Firma.query.filter(Firma.id.in_(affected_firmalar)).order_by(Firma.firma_adi).all() if affected_firmalar else []
            print("\nUpdated firms: " + (", ".join(f"{f.id}:{f.firma_adi}" for f in names) if names else "-"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Write repairs to the database.")
    args = parser.parse_args()
    main(apply=args.apply)
