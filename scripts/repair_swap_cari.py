"""Swap zinciri ve cari provenance icin dry-run/onarmaci.

Varsayilan modda chain_id ve kesin provenance backfill edilir, sonra ortak
tahakkuk/dedupe batch'i calistirilir. --dry-run mevcut veriyi degistirmez.
"""

import argparse
from collections import Counter

from app import create_app
from app.cari.models import HizmetKaydi, _derive_hizmet_kaynagi
from app.extensions import db
from app.kiralama.models import Kiralama, KiralamaKalemi
from app.makinedegisim.models import MakineDegisim
from app.services.kiralama_services import KiralamaService


def _components(kalemler, swaps):
    ids = {kalem.id for kalem in kalemler}
    graph = {kalem_id: set() for kalem_id in ids}
    for kalem in kalemler:
        if kalem.parent_id in ids:
            graph[kalem.id].add(kalem.parent_id)
            graph[kalem.parent_id].add(kalem.id)
    for swap in swaps:
        if swap.eski_kalem_id in ids and swap.yeni_kalem_id in ids:
            graph[swap.eski_kalem_id].add(swap.yeni_kalem_id)
            graph[swap.yeni_kalem_id].add(swap.eski_kalem_id)

    seen = set()
    result = []
    for start in sorted(graph):
        if start in seen:
            continue
        stack = [start]
        component = set()
        while stack:
            current = stack.pop()
            if current in component:
                continue
            component.add(current)
            stack.extend(graph[current] - component)
        seen.update(component)
        result.append(component)
    return result


def _system_supplier_rows(kalem):
    rows = HizmetKaydi.query.filter(
        HizmetKaydi.ozel_id == kalem.id,
        HizmetKaydi.firma_id == kalem.harici_ekipman_tedarikci_id,
        HizmetKaydi.yon == 'gelen',
        HizmetKaydi.is_deleted == False,
    ).order_by(HizmetKaydi.id.asc()).all()
    linked_ids = {
        swap.swap_kira_hizmet_id
        for swap in MakineDegisim.query.filter(
            MakineDegisim.swap_kira_hizmet_id.isnot(None),
            MakineDegisim.is_deleted == False,
        ).all()
    }
    return [
        row for row in rows
        if row.id in linked_ids
        or row.kaynak in ('dis_kiralama_tahakkuk', 'swap_dis_kiralama')
        or (row.aciklama or '').startswith(('Dış Kiralama', 'Dis Kiralama'))
    ], rows


def _date_overlaps(kalemler, component_by_id):
    """Mevcut bozuk tarihleri raporlar; hiçbir kaydı otomatik düzeltmez."""
    overlaps = []
    by_chain = {}
    for kalem in kalemler:
        if kalem.is_deleted or not kalem.kiralama_baslangici or not kalem.kiralama_bitis:
            continue
        by_chain.setdefault(component_by_id[kalem.id], []).append(kalem)
    for chain_id, chain_kalemler in by_chain.items():
        ordered = sorted(chain_kalemler, key=lambda k: (k.kiralama_baslangici, k.id))
        for previous, current in zip(ordered, ordered[1:]):
            if current.kiralama_baslangici <= previous.kiralama_bitis:
                overlaps.append({
                    'chain_id': chain_id,
                    'kalem_ids': (previous.id, current.id),
                    'previous_bitis': previous.kiralama_bitis,
                    'current_baslangic': current.kiralama_baslangici,
                })
    return overlaps


def main(dry_run=False):
    app = create_app()
    with app.app_context():
        kalemler = KiralamaKalemi.query.all()
        swaps = MakineDegisim.query.filter_by(is_deleted=False).all()
        changed_chain = 0
        components = _components(kalemler, swaps)
        component_by_id = {
            kalem_id: min(component)
            for component in components
            for kalem_id in component
        }
        date_overlaps = _date_overlaps(kalemler, component_by_id)
        for kalem in kalemler:
            target = component_by_id[kalem.id]
            if kalem.chain_id != target:
                changed_chain += 1
                kalem.chain_id = target
                db.session.add(kalem)

        linked_ids = {
            swap.swap_kira_hizmet_id
            for swap in swaps if swap.swap_kira_hizmet_id
        }
        source_updates = 0
        provenance_conflicts = []
        source_targets = {}
        for hizmet in HizmetKaydi.query.order_by(HizmetKaydi.id.asc()).all():
            if hizmet.id in linked_ids:
                target = 'swap_dis_kiralama'
            else:
                target = _derive_hizmet_kaynagi(hizmet)
                if target == 'dis_kiralama_tahakkuk' and not hizmet.is_deleted:
                    # Partial unique index nedeniyle ayni anahtardaki kesin
                    # sistem kaydi korunur; ikinci legacy satir raporlanir.
                    existing = HizmetKaydi.query.filter(
                        HizmetKaydi.id != hizmet.id,
                        HizmetKaydi.firma_id == hizmet.firma_id,
                        HizmetKaydi.ozel_id == hizmet.ozel_id,
                        HizmetKaydi.yon == hizmet.yon,
                        HizmetKaydi.kaynak == 'dis_kiralama_tahakkuk',
                        HizmetKaydi.is_deleted == False,
                    ).first()
                    if existing:
                        provenance_conflicts.append((hizmet.id, existing.id))
                        target = 'legacy_unclassified'
            source_targets[hizmet.id] = target
            if target and hizmet.kaynak != target:
                source_updates += 1
                hizmet.kaynak = target
                db.session.add(hizmet)

        duplicates = []
        supplier_ids = {
            kalem.harici_ekipman_tedarikci_id
            for kalem in kalemler
            if kalem.harici_ekipman_tedarikci_id and kalem.is_active and not kalem.is_deleted
        }
        for kalem in kalemler:
            if not kalem.harici_ekipman_tedarikci_id or not kalem.is_active or kalem.is_deleted:
                continue
            system_rows, all_rows = _system_supplier_rows(kalem)
            if len(system_rows) > 1:
                duplicates.append({
                    'kalem_id': kalem.id,
                    'firma_id': kalem.harici_ekipman_tedarikci_id,
                    'system_hkd_ids': [row.id for row in system_rows],
                    'manual_or_legacy_ids': [
                        row.id for row in all_rows if row not in system_rows
                    ],
                })

        print(f"chain_component_sayisi={len(components)}")
        print(f"chain_backfill_degisikligi={changed_chain}")
        print(f"provenance_backfill_degisikligi={source_updates}")
        print(f"provenance_cakisma_sayisi={len(provenance_conflicts)}")
        source_counts = Counter(source_targets.values())
        print(f"kaynak_sayilari={dict(sorted(source_counts.items()))}")
        print(f"manual_kayit_sayisi={source_counts.get('manual', 0)}")
        print(f"legacy_unclassified_sayisi={source_counts.get('legacy_unclassified', 0)}")
        print(f"tarih_cakisma_sayisi={len(date_overlaps)}")
        for overlap in date_overlaps:
            print(f"TARIH_CAKISMASI {overlap}")
        print(f"tedarikci_firma_sayisi={len(supplier_ids)}")
        print(f"kesin_mukerrer_grup_sayisi={len(duplicates)}")
        for duplicate in duplicates:
            print(f"MUKERRER {duplicate}")

        if dry_run:
            db.session.rollback()
            return

        db.session.commit()
        result = KiralamaService.sync_all_cari_totals()
        print(f"batch_senkron={result}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    main(dry_run=args.dry_run)
