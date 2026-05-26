"""
Repair legacy rental transport descriptions that only contain the form number.

Default mode is dry-run. Use --apply to update only nakliye.aciklama.

Examples:
  python scripts/repair_legacy_nakliye_kalem_refs.py
  python scripts/repair_legacy_nakliye_kalem_refs.py --apply
"""

import argparse
import csv
import os
import re
import shutil
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlparse

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from sqlalchemy import text

from app import create_app
from app.extensions import db
from app.kiralama.models import Kiralama, KiralamaKalemi
from app.nakliyeler.models import Nakliye


GIDIS = "Gidi\u015f"
DONUS = "D\u00f6n\u00fc\u015f"
STATUS_UPDATE = "UPDATE"
STATUS_AMBIGUOUS = "AMBIGUOUS"
STATUS_UNMATCHED = "UNMATCHED"
STATUS_CONFLICT = "CONFLICT"


@dataclass(frozen=True)
class KalemInfo:
    id: int
    tokens: tuple[tuple[str, str], ...]
    gidis_satis: Decimal = Decimal("0.00")
    donus_satis: Decimal = Decimal("0.00")


@dataclass(frozen=True)
class LegacyNakliyeInfo:
    id: int
    kiralama_id: int
    form_no: str
    direction: str
    old_aciklama: str
    guzergah: str
    tutar: Decimal = Decimal("0.00")


@dataclass
class RepairDecision:
    status: str
    nakliye_id: int
    kiralama_id: int
    form_no: str
    old_aciklama: str
    new_aciklama: str = ""
    guzergah: str = ""
    matched_kalem_id: int | None = None
    match_reason: str = ""
    candidate_kalem_ids: list[int] = field(default_factory=list)


def _norm(value):
    return re.sub(r"\s+", " ", (value or "").casefold()).strip()


def _safe_token(value):
    token = _norm(value)
    if not token:
        return ""
    if len(token) < 4:
        return ""
    if token.isdigit():
        return ""
    return token


def _contains_token(text, token):
    normalized_text = _norm(text)
    normalized_token = _safe_token(token)
    if not normalized_text or not normalized_token:
        return False

    if " " in normalized_token:
        return normalized_token in normalized_text

    return re.search(rf"(?<!\w){re.escape(normalized_token)}(?!\w)", normalized_text) is not None


def _to_decimal(value):
    if value is None or value == "":
        return Decimal("0.00")
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return Decimal("0.00")


def _dedupe_tokens(tokens):
    seen = set()
    result = []
    for reason, token in tokens:
        safe = _safe_token(token)
        if not safe or safe in seen:
            continue
        seen.add(safe)
        result.append((reason, safe))
    return tuple(result)


def build_kalem_info(kalem):
    tokens = []

    ekipman = getattr(kalem, "ekipman", None)
    if ekipman is not None:
        tokens.append(("equipment_code", getattr(ekipman, "kod", None)))
        tokens.append(("machine_name", getattr(ekipman, "kod", None)))

    marka = getattr(kalem, "harici_ekipman_marka", None)
    model = getattr(kalem, "harici_ekipman_model", None)
    combined = " ".join(part for part in [marka, model] if part)
    tokens.append(("external_equipment", combined))
    tokens.append(("external_brand", marka))
    tokens.append(("external_model", model))

    nakliye_satis = _to_decimal(getattr(kalem, "nakliye_satis_fiyat", None))
    if bool(getattr(kalem, "donus_nakliye_fatura_et", False)):
        gidis_satis = (nakliye_satis / Decimal("2")).quantize(Decimal("0.01"))
        raw_donus = getattr(kalem, "donus_nakliye_satis_fiyat", None)
        donus_satis = _to_decimal(raw_donus) if raw_donus is not None else gidis_satis
    else:
        gidis_satis = nakliye_satis
        donus_satis = _to_decimal(getattr(kalem, "donus_nakliye_satis_fiyat", None))

    return KalemInfo(
        id=int(kalem.id),
        tokens=_dedupe_tokens(tokens),
        gidis_satis=gidis_satis,
        donus_satis=donus_satis,
    )


def _candidate_ids_for_nakliye(nakliye, kalemler):
    matches = []
    for kalem in kalemler:
        reasons = []
        for reason, token in kalem.tokens:
            if _contains_token(nakliye.guzergah, token):
                reasons.append(reason)
        if reasons:
            matches.append((kalem.id, "+".join(sorted(set(reasons)))))

    if matches:
        return matches

    amount_matches = []
    for kalem in kalemler:
        expected = kalem.donus_satis if nakliye.direction == DONUS else kalem.gidis_satis
        if expected > 0 and expected == _to_decimal(nakliye.tutar):
            amount_matches.append((kalem.id, "amount_match"))
    if len(amount_matches) == 1:
        return amount_matches
    if len(amount_matches) > 1:
        return amount_matches

    if len(kalemler) == 1:
        return [(kalemler[0].id, "single_kalem")]

    return []


def decide_group_repairs(nakliyeler, kalemler, existing_descriptions=None):
    existing_descriptions = existing_descriptions or {}
    preliminary = []
    for nakliye in sorted(nakliyeler, key=lambda item: item.id):
        matches = _candidate_ids_for_nakliye(nakliye, kalemler)
        preliminary.append((nakliye, matches))

    decisions = []
    used_kalem_ids = set()
    used_new_descriptions = set()

    preliminary.sort(key=lambda item: (len(item[1]) if item[1] else 9999, item[0].id))

    for nakliye, matches in preliminary:
        available = [(kid, reason) for kid, reason in matches if kid not in used_kalem_ids]
        candidate_ids = [kid for kid, _ in matches]

        decision = RepairDecision(
            status=STATUS_UNMATCHED,
            nakliye_id=nakliye.id,
            kiralama_id=nakliye.kiralama_id,
            form_no=nakliye.form_no,
            old_aciklama=nakliye.old_aciklama,
            guzergah=nakliye.guzergah,
            candidate_kalem_ids=candidate_ids,
        )

        if not matches:
            decisions.append(decision)
            continue

        if len(available) != 1:
            decision.status = STATUS_AMBIGUOUS if available else STATUS_UNMATCHED
            decision.candidate_kalem_ids = [kid for kid, _ in available] or candidate_ids
            decisions.append(decision)
            continue

        matched_kalem_id, reason = available[0]
        new_aciklama = f"{nakliye.direction}: {nakliye.form_no} #{matched_kalem_id}"
        conflicting_ids = set(existing_descriptions.get((nakliye.kiralama_id, new_aciklama), set()))
        conflicting_ids.discard(nakliye.id)

        if new_aciklama in used_new_descriptions or conflicting_ids:
            decision.status = STATUS_CONFLICT
            decision.new_aciklama = new_aciklama
            decision.matched_kalem_id = matched_kalem_id
            decision.match_reason = reason
            decisions.append(decision)
            continue

        decision.status = STATUS_UPDATE
        decision.new_aciklama = new_aciklama
        decision.matched_kalem_id = matched_kalem_id
        decision.match_reason = reason
        decisions.append(decision)
        used_kalem_ids.add(matched_kalem_id)
        used_new_descriptions.add(new_aciklama)

    return sorted(decisions, key=lambda item: item.nakliye_id)


def _legacy_direction(aciklama, form_no):
    if aciklama == f"{GIDIS}: {form_no}":
        return GIDIS
    if aciklama == f"{DONUS}: {form_no}":
        return DONUS
    return ""


def _fetch_legacy_nakliyeler():
    return (
        Nakliye.query.join(Kiralama, Kiralama.id == Nakliye.kiralama_id)
        .filter(
            (Nakliye.aciklama == (GIDIS + ": ") + Kiralama.kiralama_form_no)
            | (Nakliye.aciklama == (DONUS + ": ") + Kiralama.kiralama_form_no)
        )
        .order_by(Nakliye.kiralama_id.asc(), Nakliye.id.asc())
        .all()
    )


def _fetch_suspicious_rows():
    return db.session.execute(
        text(
            """
            SELECT n.id, n.kiralama_id, k.kiralama_form_no, n.aciklama
            FROM nakliye n
            LEFT JOIN kiralama k ON k.id = n.kiralama_id
            WHERE n.aciklama IS NOT NULL
              AND n.aciklama NOT LIKE '%#%'
              AND (
                    trim(n.aciklama) <> n.aciklama
                 OR n.aciklama LIKE 'Gidiş:%'
                 OR n.aciklama LIKE 'Dönüş:%'
                 OR coalesce(k.kiralama_form_no, '') = ''
              )
              AND NOT (
                    n.aciklama = ('Gidiş: ' || k.kiralama_form_no)
                 OR n.aciklama = ('Dönüş: ' || k.kiralama_form_no)
              )
            ORDER BY n.id
            """
        )
    ).fetchall()


def build_decisions():
    legacy_rows = _fetch_legacy_nakliyeler()
    kiralama_ids = sorted({row.kiralama_id for row in legacy_rows})

    kalemler_by_kiralama = defaultdict(list)
    if kiralama_ids:
        kalemler = (
            KiralamaKalemi.query.filter(
                KiralamaKalemi.kiralama_id.in_(kiralama_ids),
                KiralamaKalemi.is_deleted == False,
            )
            .order_by(KiralamaKalemi.id.asc())
            .all()
        )
        for kalem in kalemler:
            kalemler_by_kiralama[kalem.kiralama_id].append(build_kalem_info(kalem))

    existing_descriptions = defaultdict(set)
    if kiralama_ids:
        rows = (
            Nakliye.query.filter(Nakliye.kiralama_id.in_(kiralama_ids))
            .with_entities(Nakliye.id, Nakliye.kiralama_id, Nakliye.aciklama)
            .all()
        )
        for row in rows:
            if row.aciklama:
                existing_descriptions[(row.kiralama_id, row.aciklama)].add(row.id)

    legacy_by_group = defaultdict(list)
    for row in legacy_rows:
        form_no = row.kiralama.kiralama_form_no
        direction = _legacy_direction(row.aciklama, form_no)
        legacy_by_group[(row.kiralama_id, direction)].append(
            LegacyNakliyeInfo(
                id=row.id,
                kiralama_id=row.kiralama_id,
                form_no=form_no,
                direction=direction,
                old_aciklama=row.aciklama,
                guzergah=row.guzergah or "",
                tutar=_to_decimal(row.tutar),
            )
        )

    decisions = []
    for (kiralama_id, _direction), group_nakliyeler in sorted(legacy_by_group.items()):
        decisions.extend(
            decide_group_repairs(
                group_nakliyeler,
                kalemler_by_kiralama.get(kiralama_id, []),
                existing_descriptions,
            )
        )
    return decisions, _fetch_suspicious_rows()


def _write_csv(path, decisions):
    fields = [
        "status",
        "nakliye_id",
        "kiralama_id",
        "form_no",
        "old_aciklama",
        "new_aciklama",
        "guzergah",
        "matched_kalem_id",
        "match_reason",
        "candidate_kalem_ids",
    ]
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for d in decisions:
            writer.writerow(
                {
                    "status": d.status,
                    "nakliye_id": d.nakliye_id,
                    "kiralama_id": d.kiralama_id,
                    "form_no": d.form_no,
                    "old_aciklama": d.old_aciklama,
                    "new_aciklama": d.new_aciklama,
                    "guzergah": d.guzergah,
                    "matched_kalem_id": d.matched_kalem_id or "",
                    "match_reason": d.match_reason,
                    "candidate_kalem_ids": ",".join(str(i) for i in d.candidate_kalem_ids),
                }
            )


def _print_decisions(decisions, suspicious_rows, limit):
    counts = Counter(d.status for d in decisions)
    print("=== Legacy nakliye kalem ref repair ===")
    print(f"Total legacy scope: {len(decisions)}")
    for status in [STATUS_UPDATE, STATUS_AMBIGUOUS, STATUS_UNMATCHED, STATUS_CONFLICT]:
        print(f"{status}: {counts.get(status, 0)}")

    print("\n=== Decisions ===")
    for d in decisions[:limit]:
        candidates = ",".join(str(i) for i in d.candidate_kalem_ids)
        print(
            f"{d.status} | nakliye_id={d.nakliye_id} form={d.form_no} "
            f"old='{d.old_aciklama}' new='{d.new_aciklama}' "
            f"matched={d.matched_kalem_id or ''} reason={d.match_reason} candidates={candidates}"
        )
    if len(decisions) > limit:
        print(f"... {len(decisions) - limit} more rows hidden; use --limit to show more or --csv.")

    print("\n=== Suspicious non-exact legacy-like rows ===")
    print(f"Total: {len(suspicious_rows)}")
    for row in suspicious_rows[:limit]:
        print(
            f"nakliye_id={row.id} kiralama_id={row.kiralama_id} "
            f"form={row.kiralama_form_no} aciklama='{row.aciklama}'"
        )
    if len(suspicious_rows) > limit:
        print(f"... {len(suspicious_rows) - limit} more suspicious rows hidden.")


def _backup_database(app, backup_dir):
    pg_dump = shutil.which("pg_dump")
    if not pg_dump:
        raise RuntimeError("pg_dump bulunamadi; --apply yedek almadan calismaz.")

    db_uri = app.config.get("SQLALCHEMY_DATABASE_URI")
    if not db_uri:
        raise RuntimeError("SQLALCHEMY_DATABASE_URI bulunamadi.")

    parsed = urlparse(db_uri)
    if parsed.scheme.startswith("postgresql"):
        Path(backup_dir).mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = Path(backup_dir) / f"kiralama_db_before_legacy_nakliye_ref_repair_{timestamp}.dump"
        subprocess.run([pg_dump, db_uri, "-Fc", "-f", str(backup_path)], check=True)
        return backup_path

    raise RuntimeError(f"Desteklenmeyen DB URI scheme: {parsed.scheme}")


def apply_decisions(decisions):
    for d in decisions:
        if d.status != STATUS_UPDATE:
            continue
        nakliye = db.session.get(Nakliye, d.nakliye_id)
        if not nakliye:
            raise RuntimeError(f"Nakliye bulunamadi: {d.nakliye_id}")
        if nakliye.aciklama != d.old_aciklama:
            raise RuntimeError(
                f"Nakliye aciklama degismis: {d.nakliye_id} "
                f"expected={d.old_aciklama!r} actual={nakliye.aciklama!r}"
            )
        nakliye.aciklama = d.new_aciklama
        db.session.add(nakliye)


def main():
    parser = argparse.ArgumentParser(description="Repair legacy nakliye form-only line refs.")
    parser.add_argument("--apply", action="store_true", help="Write changes to the database.")
    parser.add_argument("--csv", help="Write dry-run/apply decision rows to CSV.")
    parser.add_argument("--limit", type=int, default=120, help="Rows to print per section.")
    parser.add_argument("--backup-dir", default="backups", help="Directory for pg_dump backups.")
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        decisions, suspicious_rows = build_decisions()
        _print_decisions(decisions, suspicious_rows, args.limit)

        if args.csv:
            _write_csv(args.csv, decisions)
            print(f"\nCSV written: {args.csv}")

        blockers = [d for d in decisions if d.status != STATUS_UPDATE]
        if blockers:
            print("\nApply blocked: AMBIGUOUS/UNMATCHED/CONFLICT rows exist.")
            return 2

        if not args.apply:
            print("\nDry-run only. No database changes were written.")
            return 0

        backup_path = _backup_database(app, args.backup_dir)
        print(f"\nBackup written: {backup_path}")

        apply_decisions(decisions)
        db.session.commit()
        print(f"Applied: {len(decisions)} nakliye.aciklama updates.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
