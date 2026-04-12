"""db_yedek.sql COPY bloklarini parse ederek yetim FK / ozel_id kontrolu."""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "db_yedek.sql"


def main():
    text = open(path, "r", encoding="utf-8", errors="replace").read()
    print(f"Dosya: {path}\n")

    def parse_copy(table_name):
        pat = rf"^COPY public\.{table_name} \(([^)]+)\) FROM stdin;$"
        m = re.search(pat, text, re.MULTILINE)
        if not m:
            return [], []
        cols = [c.strip() for c in m.group(1).split(",")]
        start = m.end()
        end = text.find("\\.\n", start)
        if end == -1:
            end = text.find("\\.\r\n", start)
        block = text[start:end] if end != -1 else text[start:]
        lines = [ln for ln in block.strip().splitlines() if ln.strip()]
        return cols, lines

    def row_dict(cols, line):
        parts = line.split("\t")
        if len(parts) < len(cols):
            return None
        if len(parts) > len(cols):
            parts = parts[: len(cols) - 1] + ["\t".join(parts[len(cols) - 1 :])]
        d = {}
        for c, v in zip(cols, parts):
            d[c] = None if v == r"\N" else v
        return d

    def int_or_none(x):
        if x is None:
            return None
        try:
            return int(x)
        except ValueError:
            return None

    firma_cols, firma_lines = parse_copy("firma")
    kiralama_cols, kiralama_lines = parse_copy("kiralama")
    kk_cols, kk_lines = parse_copy("kiralama_kalemi")
    nak_cols, nak_lines = parse_copy("nakliye")
    hk_cols, hk_lines = parse_copy("hizmet_kaydi")
    ekip_cols, ekip_lines = parse_copy("ekipman")
    odeme_cols, odeme_lines = parse_copy("odeme")
    kasa_cols, kasa_lines = parse_copy("kasa")

    firma_ids = set()
    for ln in firma_lines:
        d = row_dict(firma_cols, ln)
        if d:
            firma_ids.add(int(d["id"]))

    kiralama_ids = set()
    kiralama_by_form = {}
    for ln in kiralama_lines:
        d = row_dict(kiralama_cols, ln)
        if d:
            kid = int(d["id"])
            kiralama_ids.add(kid)
            kiralama_by_form[d.get("kiralama_form_no")] = kid

    kk_ids = set()
    for ln in kk_lines:
        d = row_dict(kk_cols, ln)
        if d:
            kk_ids.add(int(d["id"]))

    nak_ids = set()
    for ln in nak_lines:
        d = row_dict(nak_cols, ln)
        if d:
            nak_ids.add(int(d["id"]))

    ekip_ids = set()
    for ln in ekip_lines:
        d = row_dict(ekip_cols, ln)
        if d:
            ekip_ids.add(int(d["id"]))

    kasa_ids = set()
    for ln in kasa_lines:
        d = row_dict(kasa_cols, ln)
        if d:
            kasa_ids.add(int(d["id"]))

    issues = []

    for ln in kk_lines:
        d = row_dict(kk_cols, ln)
        if not d:
            continue
        rid = int(d["kiralama_id"])
        if rid not in kiralama_ids:
            issues.append(("kiralama_kalemi", d.get("id"), f"kiralama_id={rid} yok"))

    for ln in nak_lines:
        d = row_dict(nak_cols, ln)
        if not d:
            continue
        fid = int_or_none(d.get("firma_id"))
        if fid and fid not in firma_ids:
            issues.append(("nakliye", d.get("id"), f"firma_id={fid} yok"))
        kid = int_or_none(d.get("kiralama_id"))
        if kid is not None and kid not in kiralama_ids:
            issues.append(("nakliye", d.get("id"), f"kiralama_id={kid} yok"))

    for ln in hk_lines:
        d = row_dict(hk_cols, ln)
        if not d:
            continue
        hid = d.get("id")
        fid = int_or_none(d.get("firma_id"))
        if fid and fid not in firma_ids:
            issues.append(("hizmet_kaydi", hid, f"firma_id={fid} yok"))
        nid = int_or_none(d.get("nakliye_id"))
        if nid is not None and nid not in nak_ids:
            issues.append(("hizmet_kaydi", hid, f"nakliye_id={nid} yok"))
        oid = int_or_none(d.get("ozel_id"))
        ac = (d.get("aciklama") or "")
        if oid is not None:
            if ac.startswith("Kiralama Bekleyen Bakiye"):
                if oid not in kiralama_ids:
                    issues.append(
                        ("hizmet_kaydi", hid, f"ozel_id={oid} kiralama yok (bekleyen)")
                    )
            elif ac.startswith("Dış Kiralama"):
                if oid not in kk_ids:
                    issues.append(
                        ("hizmet_kaydi", hid, f"ozel_id={oid} kiralama_kalemi yok")
                    )
            elif "Müşteri Dönüş Nakliye" in ac or ac.startswith("Nakliye Farkı"):
                if oid not in kk_ids:
                    issues.append(
                        ("hizmet_kaydi", hid, f"ozel_id={oid} kiralama_kalemi yok (donus)")
                    )
        fn = d.get("fatura_no")
        if fn and ac.startswith("Kiralama Bekleyen Bakiye"):
            if fn not in kiralama_by_form:
                issues.append(
                    ("hizmet_kaydi", hid, f"fatura_no={fn} kiralama_form_no eslesmedi")
                )

    for ln in kk_lines:
        d = row_dict(kk_cols, ln)
        if not d:
            continue
        eid = int_or_none(d.get("ekipman_id"))
        if eid is not None and eid not in ekip_ids:
            issues.append(("kiralama_kalemi", d.get("id"), f"ekipman_id={eid} yok"))

    for ln in odeme_lines:
        d = row_dict(odeme_cols, ln)
        if not d:
            continue
        fid = int_or_none(d.get("firma_musteri_id"))
        if fid and fid not in firma_ids:
            issues.append(("odeme", d.get("id"), f"firma_musteri_id={fid} yok"))
        kid = int_or_none(d.get("kasa_id"))
        if kid is not None and kid not in kasa_ids:
            issues.append(("odeme", d.get("id"), f"kasa_id={kid} yok"))

    print("=== db_yedek.sql yetim kontrolu ===")
    print(f"firma: {len(firma_ids)}  kiralama: {len(kiralama_ids)}  kalem: {len(kk_ids)}")
    print(f"nakliye: {len(nak_ids)}  hizmet_kaydi: {len(hk_lines)}  ekipman: {len(ekip_ids)}")
    print(f"Sorun satiri: {len(issues)}")
    for t, i, msg in issues[:100]:
        print(f"  [{t}] id={i}  {msg}")
    if len(issues) > 100:
        print(f"  ... +{len(issues) - 100} daha")


if __name__ == "__main__":
    main()
