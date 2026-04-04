"""Arşivlenen legacy SQLite taşıma girişi.

Bu dosya yanlışlıkla tekrar çalıştırılmasın diye varsayılan olarak durdurulur.
Gerekirse arşivlenmiş gerçek araç `scripts/legacy_migrate_sqlite_to_pg.py` altındadır.
"""

import os
import runpy
from pathlib import Path


LEGACY_SCRIPT = Path(__file__).resolve().parent / 'scripts' / 'legacy_migrate_sqlite_to_pg.py'
ALLOW_ENV = 'ALLOW_LEGACY_SQLITE_MIGRATION'


def main():
    if os.environ.get(ALLOW_ENV) != '1':
        raise SystemExit(
            'Bu script arşive alındı ve varsayılan olarak kapatıldı. '
            'Legacy taşıma gerçekten gerekiyorsa önce eski SQLite snapshot\'ını doğrulayın, '
            f'sonra {ALLOW_ENV}=1 ile scripts/legacy_migrate_sqlite_to_pg.py çalıştırın.'
        )

    runpy.run_path(str(LEGACY_SCRIPT), run_name='__main__')


if __name__ == '__main__':
    main()
