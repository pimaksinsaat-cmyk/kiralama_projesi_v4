"""
Kiralama / taşeron / nakliye / tahsilat-ödeme cari tutarlılık denetimi (read-only).

Kontroller:
  1) Dış tedarik (Dış Kiralama) HizmetKaydi tutar/KDV ve mükerrer kayıt
  2) Sonlandırılmış kalemlerde dönüş nakliye seferi + müşteri/taşeron cari
  3) Müşteri dönüş çift yansıma riski (manuel HKD + nakliye_id HKD)
  4) Firma.bakiye ve Kasa.bakiye cache sapması

Kullanım:
  python scripts/audit_kiralama_taseron_nakliye_odeme_cari.py
  python scripts/audit_kiralama_taseron_nakliye_odeme_cari.py --csv audit.csv
  python scripts/audit_kiralama_taseron_nakliye_odeme_cari.py --tolerance 0.01 --today 2026-05-26
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Iterable, Optional

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from app import create_app
from app.cari.models import HizmetKaydi, Kasa, Odeme
from app.extensions import db
from app.firmalar.models import Firma
from app.kiralama.models import Kiralama, KiralamaKalemi
from app.nakliyeler.models import Nakliye
from app.services.kiralama_services import KiralamaService, to_decimal
from app.services.nakliye_services import _net_kdv_orani

DAHILI_FIRMA_ADLARI = ("DAHİLİ İŞLEMLER", "Dahili Kasa İşlemleri")


@dataclass
class AuditFinding:
    category: str
    entity_id: Optional[int] = None
    firma_id: Optional[int] = None
    beklenen: Optional[str] = None
    mevcut: Optional[str] = None
    fark: Optional[str] = None
    aciklama: str = ""
    extra: str = ""

    def to_row(self) -> dict[str, str]:
        return {
            "category": self.category,
            "entity_id": "" if self.entity_id is None else str(self.entity_id),
            "firma_id": "" if self.firma_id is None else str(self.firma_id),
            "beklenen": self.beklenen or "",
            "mevcut": self.mevcut or "",
            "fark": self.fark or "",
            "aciklama": self.aciklama or "",
            "extra": self.extra or "",
        }


@dataclass
class AuditResult:
    findings: list[AuditFinding] = field(default_factory=list)
    checked: dict[str, int] = field(default_factory=dict)

    def add(self, finding: AuditFinding) -> None:
        self.findings.append(finding)

    def summary(self) -> Counter:
        return Counter(f.category for f in self.findings)


def _decimal_diff(a: Decimal, b: Decimal) -> Decimal:
    return abs(to_decimal(a) - to_decimal(b))


def _exceeds_tolerance(left: Decimal, right: Decimal, tolerance: Decimal) -> bool:
    return _decimal_diff(left, right) > tolerance


def _dis_kiralama_query(kalem: KiralamaKalemi) -> list[HizmetKaydi]:
    return (
        HizmetKaydi.query.filter(
            HizmetKaydi.ozel_id == kalem.id,
            HizmetKaydi.firma_id == kalem.harici_ekipman_tedarikci_id,
            HizmetKaydi.yon == "gelen",
            HizmetKaydi.is_deleted == False,
            db.or_(
                HizmetKaydi.aciklama.like("Dış Kiralama%"),
                HizmetKaydi.aciklama.like("Dis Kiralama%"),
            ),
        )
        .order_by(HizmetKaydi.id.asc())
        .all()
    )


def _audit_dis_kiralama(result: AuditResult, today: date, tolerance: Decimal) -> None:
    kalemler = (
        KiralamaKalemi.query.filter(
            KiralamaKalemi.is_dis_tedarik_ekipman == True,
            KiralamaKalemi.harici_ekipman_tedarikci_id.isnot(None),
            KiralamaKalemi.harici_ekipman_tedarikci_id > 0,
            KiralamaKalemi.is_deleted == False,
        )
        .order_by(KiralamaKalemi.id.asc())
        .all()
    )
    result.checked["dis_kiralama_kalem"] = len(kalemler)

    for kalem in kalemler:
        kir = kalem.kiralama
        if not kir or kir.is_deleted:
            continue
        form_no = kir.kiralama_form_no or "-"
        expected = KiralamaService._hesapla_bekleyen_alis_kalem_tutari(kalem, referans_tarih=today)
        expected_kdv = kalem.kiralama_alis_kdv
        kayitlar = _dis_kiralama_query(kalem)

        if not kayitlar:
            if expected > 0:
                result.add(
                    AuditFinding(
                        category="DIS_KIRALAMA_MISSING",
                        entity_id=kalem.id,
                        firma_id=kalem.harici_ekipman_tedarikci_id,
                        beklenen=str(expected),
                        aciklama=f"Dış Kiralama HKD yok | form={form_no}",
                    )
                )
            continue

        if len(kayitlar) > 1:
            ids = ",".join(str(h.id) for h in kayitlar)
            result.add(
                AuditFinding(
                    category="DIS_KIRALAMA_DUPLICATE",
                    entity_id=kalem.id,
                    firma_id=kalem.harici_ekipman_tedarikci_id,
                    mevcut=str(len(kayitlar)),
                    aciklama=f"Aktif Dış Kiralama HKD mükerrer | form={form_no}",
                    extra=f"hizmet_ids={ids}",
                )
            )

        primary = kayitlar[0]
        current = to_decimal(primary.tutar)
        if _exceeds_tolerance(current, expected, tolerance):
            result.add(
                AuditFinding(
                    category="DIS_KIRALAMA_AMOUNT_MISMATCH",
                    entity_id=kalem.id,
                    firma_id=kalem.harici_ekipman_tedarikci_id,
                    beklenen=str(expected),
                    mevcut=str(current),
                    fark=str(_decimal_diff(current, expected)),
                    aciklama=f"hizmet_id={primary.id} form={form_no}",
                )
            )

        current_kdv = primary.kiralama_alis_kdv if primary.kiralama_alis_kdv is not None else primary.kdv_orani
        if expected_kdv is not None and current_kdv != expected_kdv:
            result.add(
                AuditFinding(
                    category="DIS_KIRALAMA_KDV_MISMATCH",
                    entity_id=kalem.id,
                    firma_id=kalem.harici_ekipman_tedarikci_id,
                    beklenen=str(expected_kdv),
                    mevcut=str(current_kdv),
                    aciklama=f"hizmet_id={primary.id} form={form_no}",
                )
            )


def _donus_nakliye_aciklama(kir: Kiralama, kalem: KiralamaKalemi) -> str:
    form_no = kir.kiralama_form_no or ""
    return f"Dönüş: {form_no} #{kalem.id}"


def _audit_sonlandirma_nakliye(result: AuditResult, tolerance: Decimal) -> None:
    kalemler = (
        KiralamaKalemi.query.filter(
            KiralamaKalemi.sonlandirildi == True,
            KiralamaKalemi.is_deleted == False,
        )
        .order_by(KiralamaKalemi.id.asc())
        .all()
    )
    result.checked["sonlandirilmis_kalem"] = len(kalemler)

    for kalem in kalemler:
        kir = kalem.kiralama
        if not kir or kir.is_deleted:
            continue
        # Kiralama halen devam ediyorsa (herhangi bir aktif kalem varsa),
        # makine değişimi gibi ara sonlandırmalarda dönüş nakliyesi beklemiyoruz.
        aktif_var = (
            KiralamaKalemi.query.filter(
                KiralamaKalemi.kiralama_id == kir.id,
                KiralamaKalemi.is_active == True,
                KiralamaKalemi.sonlandirildi == False,
                KiralamaKalemi.is_deleted == False,
            )
            .limit(1)
            .count()
        )
        if aktif_var:
            continue
        form_no = kir.kiralama_form_no or "-"
        donus_satis = KiralamaService._get_donus_nakliye_satis(kalem)
        donus_aciklama = _donus_nakliye_aciklama(kir, kalem)

        if donus_satis <= 0:
            continue

        donus_seferleri = Nakliye.query.filter(
            Nakliye.kiralama_id == kir.id,
            Nakliye.aciklama == donus_aciklama,
        ).all()

        if not donus_seferleri:
            result.add(
                AuditFinding(
                    category="DONUS_NAKLIYE_TRIP_MISSING",
                    entity_id=kalem.id,
                    firma_id=kir.firma_musteri_id,
                    beklenen=str(donus_satis),
                    aciklama=f"Dönüş Nakliye seferi yok | form={form_no}",
                )
            )
            continue

        if len(donus_seferleri) > 1:
            ids = ",".join(str(n.id) for n in donus_seferleri)
            result.add(
                AuditFinding(
                    category="DONUS_NAKLIYE_TRIP_DUPLICATE",
                    entity_id=kalem.id,
                    firma_id=kir.firma_musteri_id,
                    mevcut=str(len(donus_seferleri)),
                    aciklama=f"Dönüş seferi mükerrer | form={form_no}",
                    extra=f"nakliye_ids={ids}",
                )
            )

        sefer = donus_seferleri[0]
        sefer_tutar = to_decimal(sefer.tutar)
        if _exceeds_tolerance(sefer_tutar, donus_satis, tolerance):
            result.add(
                AuditFinding(
                    category="DONUS_NAKLIYE_TRIP_AMOUNT_MISMATCH",
                    entity_id=kalem.id,
                    firma_id=kir.firma_musteri_id,
                    beklenen=str(donus_satis),
                    mevcut=str(sefer_tutar),
                    fark=str(_decimal_diff(sefer_tutar, donus_satis)),
                    aciklama=f"nakliye_id={sefer.id} form={form_no}",
                )
            )

        musteri_hkd = HizmetKaydi.query.filter(
            HizmetKaydi.nakliye_id == sefer.id,
            HizmetKaydi.yon == "giden",
            HizmetKaydi.is_deleted == False,
        ).all()
        expected_musteri_tutar = to_decimal(sefer.toplam_tutar)
        hk_kdv = getattr(sefer, "kdv_orani", None) or 0
        expected_kdv = _net_kdv_orani(hk_kdv, getattr(sefer, "tevkifat_orani", None) or "")

        if not musteri_hkd:
            result.add(
                AuditFinding(
                    category="DONUS_NAKLIYE_MUSTERI_CARI_MISSING",
                    entity_id=kalem.id,
                    firma_id=kir.firma_musteri_id,
                    beklenen=str(expected_musteri_tutar),
                    aciklama=f"Müşteri nakliye HKD yok | nakliye_id={sefer.id} form={form_no}",
                )
            )
        else:
            primary = musteri_hkd[0]
            if len(musteri_hkd) > 1:
                result.add(
                    AuditFinding(
                        category="DONUS_NAKLIYE_MUSTERI_CARI_DUPLICATE",
                        entity_id=kalem.id,
                        firma_id=kir.firma_musteri_id,
                        mevcut=str(len(musteri_hkd)),
                        aciklama=f"Müşteri nakliye HKD mükerrer | nakliye_id={sefer.id}",
                        extra=",".join(str(h.id) for h in musteri_hkd),
                    )
                )
            current = to_decimal(primary.tutar)
            if _exceeds_tolerance(current, expected_musteri_tutar, tolerance):
                result.add(
                    AuditFinding(
                        category="DONUS_NAKLIYE_MUSTERI_CARI_AMOUNT_MISMATCH",
                        entity_id=kalem.id,
                        firma_id=kir.firma_musteri_id,
                        beklenen=str(expected_musteri_tutar),
                        mevcut=str(current),
                        fark=str(_decimal_diff(current, expected_musteri_tutar)),
                        aciklama=f"hizmet_id={primary.id} nakliye_id={sefer.id} form={form_no}",
                    )
                )
            if primary.kdv_orani != expected_kdv:
                result.add(
                    AuditFinding(
                        category="DONUS_NAKLIYE_MUSTERI_CARI_KDV_MISMATCH",
                        entity_id=kalem.id,
                        firma_id=kir.firma_musteri_id,
                        beklenen=str(expected_kdv),
                        mevcut=str(primary.kdv_orani),
                        aciklama=f"hizmet_id={primary.id} nakliye_id={sefer.id} form={form_no}",
                    )
                )

        # Manuel müşteri dönüş satırı + nakliye senkronu birlikte (çift yansıma riski)
        manuel_donus = HizmetKaydi.query.filter(
            HizmetKaydi.ozel_id == kalem.id,
            HizmetKaydi.firma_id == kir.firma_musteri_id,
            HizmetKaydi.yon == "giden",
            HizmetKaydi.is_deleted == False,
            HizmetKaydi.nakliye_id.is_(None),
            db.or_(
                HizmetKaydi.aciklama.like("Dönüş Nakliye (%"),
                HizmetKaydi.aciklama.like("Nakliye Farkı%"),
            ),
        ).count()
        if manuel_donus > 0 and musteri_hkd:
            result.add(
                AuditFinding(
                    category="MUSTERI_DONUS_DOUBLE_COUNT_RISK",
                    entity_id=kalem.id,
                    firma_id=kir.firma_musteri_id,
                    mevcut=str(manuel_donus),
                    aciklama=(
                        f"Manuel dönüş/fark HKD + nakliye_id HKD birlikte | "
                        f"form={form_no} nakliye_id={sefer.id}"
                    ),
                )
            )

        # Taşeron dönüş gideri
        if (
            kalem.donus_is_harici_nakliye
            and kalem.donus_nakliye_tedarikci_id
            and to_decimal(kalem.donus_nakliye_alis_fiyat) > 0
        ):
            expected_taseron = to_decimal(kalem.donus_nakliye_alis_fiyat)
            expected_taseron_kdv = kalem.donus_nakliye_alis_kdv
            taseron_kayitlari = HizmetKaydi.query.filter(
                HizmetKaydi.ozel_id == kalem.id,
                HizmetKaydi.firma_id == kalem.donus_nakliye_tedarikci_id,
                HizmetKaydi.yon == "gelen",
                HizmetKaydi.is_deleted == False,
                HizmetKaydi.aciklama.like("Dönüş Nakliye:%"),
            ).order_by(HizmetKaydi.id.asc()).all()

            if not taseron_kayitlari:
                result.add(
                    AuditFinding(
                        category="DONUS_NAKLIYE_TASERON_CARI_MISSING",
                        entity_id=kalem.id,
                        firma_id=kalem.donus_nakliye_tedarikci_id,
                        beklenen=str(expected_taseron),
                        aciklama=f"Dönüş taşeron HKD yok | form={form_no}",
                    )
                )
            else:
                if len(taseron_kayitlari) > 1:
                    result.add(
                        AuditFinding(
                            category="DONUS_NAKLIYE_TASERON_DUPLICATE",
                            entity_id=kalem.id,
                            firma_id=kalem.donus_nakliye_tedarikci_id,
                            mevcut=str(len(taseron_kayitlari)),
                            aciklama=f"Dönüş taşeron HKD mükerrer | form={form_no}",
                            extra=",".join(str(h.id) for h in taseron_kayitlari),
                        )
                    )
                primary_ts = taseron_kayitlari[0]
                current_ts = to_decimal(primary_ts.tutar)
                if _exceeds_tolerance(current_ts, expected_taseron, tolerance):
                    result.add(
                        AuditFinding(
                            category="DONUS_NAKLIYE_TASERON_CARI_AMOUNT_MISMATCH",
                            entity_id=kalem.id,
                            firma_id=kalem.donus_nakliye_tedarikci_id,
                            beklenen=str(expected_taseron),
                            mevcut=str(current_ts),
                            fark=str(_decimal_diff(current_ts, expected_taseron)),
                            aciklama=f"hizmet_id={primary_ts.id} form={form_no}",
                        )
                    )
                current_ts_kdv = (
                    primary_ts.nakliye_alis_kdv
                    if primary_ts.nakliye_alis_kdv is not None
                    else primary_ts.kdv_orani
                )
                if expected_taseron_kdv is not None and current_ts_kdv != expected_taseron_kdv:
                    result.add(
                        AuditFinding(
                            category="DONUS_NAKLIYE_TASERON_CARI_KDV_MISMATCH",
                            entity_id=kalem.id,
                            firma_id=kalem.donus_nakliye_tedarikci_id,
                            beklenen=str(expected_taseron_kdv),
                            mevcut=str(current_ts_kdv),
                            aciklama=f"hizmet_id={primary_ts.id} form={form_no}",
                        )
                    )


def _audit_firma_kasa_cache(result: AuditResult, tolerance: Decimal) -> None:
    firmalar = Firma.query.filter(
        Firma.is_deleted == False,
        Firma.firma_adi.notin_(DAHILI_FIRMA_ADLARI),
    ).all()
    result.checked["firma"] = len(firmalar)

    for firma in firmalar:
        ozet = firma.bakiye_ozeti
        expected = to_decimal(ozet.get("net_bakiye"))
        cached = to_decimal(firma.bakiye)
        if _exceeds_tolerance(cached, expected, tolerance):
            result.add(
                AuditFinding(
                    category="FIRMA_BAKIYE_CACHE_DRIFT",
                    entity_id=firma.id,
                    firma_id=firma.id,
                    beklenen=str(expected),
                    mevcut=str(cached),
                    fark=str(_decimal_diff(cached, expected)),
                    aciklama=firma.firma_adi,
                    extra=f"kdvli_net={ozet.get('net_bakiye_kdvli')}",
                )
            )

    kasalar = Kasa.query.filter(Kasa.is_deleted == False).all()
    result.checked["kasa"] = len(kasalar)

    for kasa in kasalar:
        expected = to_decimal(kasa.hesaplanan_bakiye)
        cached = to_decimal(kasa.bakiye)
        if _exceeds_tolerance(cached, expected, tolerance):
            result.add(
                AuditFinding(
                    category="KASA_BAKIYE_CACHE_DRIFT",
                    entity_id=kasa.id,
                    beklenen=str(expected),
                    mevcut=str(cached),
                    fark=str(_decimal_diff(cached, expected)),
                    aciklama=kasa.kasa_adi,
                )
            )


def run_audit(
    today: Optional[date] = None,
    tolerance: Decimal | float = Decimal("0.01"),
) -> AuditResult:
    """
    Tüm denetim kontrollerini çalıştırır; DB'ye yazmaz.
    Testler ve CLI bu fonksiyonu kullanır.
    """
    if today is None:
        today = date.today()
    tolerance = to_decimal(tolerance)

    result = AuditResult()
    _audit_dis_kiralama(result, today, tolerance)
    _audit_sonlandirma_nakliye(result, tolerance)
    _audit_firma_kasa_cache(result, tolerance)
    return result


def write_csv(findings: Iterable[AuditFinding], path: str) -> None:
    rows = [f.to_row() for f in findings]
    fieldnames = ["category", "entity_id", "firma_id", "beklenen", "mevcut", "fark", "aciklama", "extra"]
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def print_report(result: AuditResult, sample_per_category: int = 5) -> None:
    print("=== Denetim özeti (kategori bazlı) ===")
    summary = result.summary()
    if not summary:
        print("Bulgu yok.")
    else:
        for category, count in sorted(summary.items()):
            print(f"  {category}: {count}")

    print("\n=== Kontrol edilen kayıt sayıları ===")
    for key, count in sorted(result.checked.items()):
        print(f"  {key}: {count}")

    print(f"\n=== Örnek bulgular (kategori başına en fazla {sample_per_category}) ===")
    by_cat: dict[str, list[AuditFinding]] = {}
    for finding in result.findings:
        by_cat.setdefault(finding.category, []).append(finding)

    for category in sorted(by_cat):
        print(f"\n-- {category} --")
        for finding in by_cat[category][:sample_per_category]:
            parts = [
                f"entity={finding.entity_id}",
                f"firma={finding.firma_id}",
                f"beklenen={finding.beklenen}",
                f"mevcut={finding.mevcut}",
                f"fark={finding.fark}",
                finding.aciklama,
            ]
            if finding.extra:
                parts.append(finding.extra)
            print("  " + " | ".join(p for p in parts if p and p != "None"))


def _parse_today(value: Optional[str]) -> date:
    if not value:
        return date.today()
    return datetime.strptime(value, "%Y-%m-%d").date()


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Kiralama/taşeron/nakliye/ödeme cari denetimi (read-only)")
    parser.add_argument("--tolerance", type=str, default="0.01", help="Tutar toleransı (TL)")
    parser.add_argument("--today", type=str, default=None, help="Referans tarihi YYYY-MM-DD")
    parser.add_argument("--csv", type=str, default=None, help="Bulguları CSV dosyasına yaz")
    parser.add_argument("--sample", type=int, default=5, help="Konsol örnek satır sayısı")
    args = parser.parse_args(argv)

    today = _parse_today(args.today)
    tolerance = Decimal(args.tolerance)

    app = create_app()
    with app.app_context():
        result = run_audit(today=today, tolerance=tolerance)
        print_report(result, sample_per_category=args.sample)
        if args.csv:
            write_csv(result.findings, args.csv)
            print(f"\nCSV yazıldı: {args.csv}")
        print("\nNo database changes were written.")
        return 1 if result.findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
