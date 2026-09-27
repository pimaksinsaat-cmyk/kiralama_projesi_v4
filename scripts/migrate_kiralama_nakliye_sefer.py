"""Kiralama nakliyelerini güvenli biçimde sefer modeline geçirir.

Örnek çalışma sırası:
  python scripts/migrate_kiralama_nakliye_sefer.py snapshot --output reports/before.json
  python scripts/migrate_kiralama_nakliye_sefer.py preflight --output reports/preflight.json
  python scripts/migrate_kiralama_nakliye_sefer.py apply --before reports/before.json --run-id UUID --output-dir reports/run
  python scripts/migrate_kiralama_nakliye_sefer.py compare --before reports/before.json --after reports/after.json --output reports/compare.json
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys
import uuid


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app import create_app
from app.services.nakliye_gecis_services import (
    CariSnapshotService,
    GuvenliNakliyeGecisService,
    TaseronCariBaglantiOnarimService,
)


def _read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def _write_json(path, data):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True),
        encoding='utf-8',
    )
    return target


def _write_firma_csv(path, before, after):
    before_rows = {
        (row['firma_id'], row['para_birimi']): row
        for row in before.get('firma_ozetleri', [])
    }
    after_rows = {
        (row['firma_id'], row['para_birimi']): row
        for row in after.get('firma_ozetleri', [])
    }
    firm_names = {row['id']: row['firma_adi'] for row in before.get('firmalar', [])}
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        'firma_id', 'firma_adi', 'para_birimi',
        'once_borc', 'sonra_borc', 'borc_farki',
        'once_alacak', 'sonra_alacak', 'alacak_farki',
        'once_bakiye', 'sonra_bakiye', 'bakiye_farki',
    ]
    with target.open('w', newline='', encoding='utf-8-sig') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        all_keys = set(before_rows) | set(after_rows)
        all_keys.update((firma_id, 'TRY') for firma_id in firm_names)
        for firma_id, currency in sorted(all_keys):
            old = before_rows.get((firma_id, currency), {})
            new = after_rows.get((firma_id, currency), {})
            values = {}
            for name in ('borc', 'alacak', 'bakiye'):
                old_value = old.get(name, '0.00')
                new_value = new.get(name, '0.00')
                values[f'once_{name}'] = old_value
                values[f'sonra_{name}'] = new_value
                values[f'{name}_farki'] = f'{float(new_value) - float(old_value):.2f}'
            writer.writerow({
                'firma_id': firma_id,
                'firma_adi': firm_names.get(firma_id, ''),
                'para_birimi': currency,
                **values,
            })
    return target


def _parser():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)

    snapshot = sub.add_parser('snapshot')
    snapshot.add_argument('--output', required=True)

    preflight = sub.add_parser('preflight')
    preflight.add_argument('--output', required=True)

    compare = sub.add_parser('compare')
    compare.add_argument('--before', required=True)
    compare.add_argument('--after', required=True)
    compare.add_argument('--output', required=True)
    compare.add_argument('--firma-csv')
    compare.add_argument('--run-id')

    apply = sub.add_parser('apply')
    apply.add_argument('--before', required=True)
    apply.add_argument('--run-id', default=None)
    apply.add_argument('--output-dir', required=True)
    apply.add_argument('--actor-id', type=int)

    repair = sub.add_parser('repair-taseron-links')
    repair.add_argument('--output-dir', required=True)
    repair.add_argument('--reference')
    repair.add_argument('--run-id', default=None)
    repair.add_argument('--actor-id', type=int)
    repair.add_argument('--apply', action='store_true')
    return parser


def main():
    args = _parser().parse_args()
    app = create_app()
    with app.app_context():
        if args.command == 'snapshot':
            snapshot = CariSnapshotService.create_snapshot()
            path = _write_json(args.output, snapshot)
            print(f'Snapshot: {path}')
            print(f"SHA256: {snapshot['sha256']}")
            print(f"Firma: {len(snapshot['firmalar'])}; hizmet: {len(snapshot['hizmet_kayitlari'])}; ödeme: {len(snapshot['odemeler'])}")
            return 0

        if args.command == 'preflight':
            report = GuvenliNakliyeGecisService.preflight()
            path = _write_json(args.output, report)
            print(f'Preflight: {path}')
            print(
                f"Karar: {len(report['kararlar'])}; "
                f"otomatik onarım: {len(report.get('otomatik_onarimlar', []))}; "
                f"engel: {len(report['engeller'])}"
            )
            return 0 if report['ok'] else 2

        if args.command == 'compare':
            before = _read_json(args.before)
            after = _read_json(args.after)
            report = CariSnapshotService.compare(before, after)
            if args.run_id:
                GuvenliNakliyeGecisService.finish_reconciliation(args.run_id, report)
            path = _write_json(args.output, report)
            if args.firma_csv:
                _write_firma_csv(args.firma_csv, before, after)
            print(f'Karşılaştırma: {path}')
            print(f"Firma: {report['kontrol_edilen_firma_sayisi']}; hata: {report['hata_sayisi']}; beklenen teknik değişiklik: {report['beklenen_degisiklik_sayisi']}")
            return 0 if report['ok'] else 3

        if args.command == 'repair-taseron-links':
            output_dir = Path(args.output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)
            current = CariSnapshotService.create_snapshot()
            preflight = TaseronCariBaglantiOnarimService.preflight()
            _write_json(output_dir / 'taseron_link_preflight.json', preflight)
            print(
                f"Taşeron eşleşmesi: {preflight['eslesme_sayisi']}; "
                f"bağlantı: {preflight['baglanti_sayisi']}; "
                f"mükerrer: {preflight['mukerrer_temizleme_sayisi']}; "
                f"engel: {len(preflight['engeller'])}"
            )
            if not args.apply:
                print('Salt okunur ön kontrol tamamlandı; veri değiştirilmedi.')
                return 0 if preflight['ok'] else 2
            reference = _read_json(args.reference) if args.reference else None
            run, _ = TaseronCariBaglantiOnarimService.apply(
                actor_id=args.actor_id,
                run_uuid=args.run_id,
                expected_snapshot_sha256=current['sha256'],
                reference_snapshot=reference,
            )
            verification = TaseronCariBaglantiOnarimService.verify(reference)
            after = CariSnapshotService.create_snapshot()
            _write_json(output_dir / 'after.json', after)
            _write_json(output_dir / 'taseron_link_verification.json', verification)
            print(f'Run ID: {run.run_uuid}')
            print(f'Run durumu: {run.durum}')
            print(
                f"Sefer: {verification['sefer_sayisi']}; "
                f"aktif gider: {verification['aktif_hizmet_sayisi']}; "
                f"toplam: {verification['aktif_taseron_gider_toplami']}; "
                f"hata: {len(verification['hatalar'])}; "
                f"mali fark: {len(verification['firma_mali_farklari'])}"
            )
            return 0 if verification['ok'] else 3

        before = _read_json(args.before)
        run_id = args.run_id or str(uuid.uuid4())
        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        run = GuvenliNakliyeGecisService.apply(
            before,
            actor_id=args.actor_id,
            run_uuid=run_id,
        )
        after = CariSnapshotService.create_snapshot()
        report = CariSnapshotService.compare(before, after)
        run = GuvenliNakliyeGecisService.finish_reconciliation(run.run_uuid, report)
        _write_json(output_dir / 'after.json', after)
        _write_json(output_dir / 'comparison.json', report)
        _write_firma_csv(output_dir / 'firma_cari_karsilastirma.csv', before, after)
        print(f'Run ID: {run.run_uuid}')
        run_report = json.loads(run.rapor_json or '{}')
        blockers = run_report.get('engeller') or []
        print(f"Dönüşen kiralama: {run.donusturulen_kiralama_sayisi}")
        print(f"Dönüşen sefer: {run.donusturulen_sefer_sayisi}")
        print(f"Engel: {len(blockers)}")
        print(f"Mutabakat hatası: {report['hata_sayisi']}")
        if run.durum == 'kismi_basarisiz' and report['hata_sayisi'] == 0:
            print('Kısmi başarı: mutabakat hatası 0; engelli kayıtlar atlandı.')
        return 0 if report['ok'] and run.durum == 'tamamlandi' else 3


if __name__ == '__main__':
    raise SystemExit(main())
