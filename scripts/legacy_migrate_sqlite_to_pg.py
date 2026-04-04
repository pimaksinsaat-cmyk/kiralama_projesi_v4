"""
SQLite → PostgreSQL Veri Aktarım Scripti
=========================================
Arşivlenmiş legacy taşıma aracı.
Sadece eski bir SQLite snapshot'ını bilinçli biçimde PostgreSQL'e taşımak gerektiğinde kullanılmalıdır.

Flask app_context içinde çalışır.
SQLite'dan satırları dict olarak okur, SQLAlchemy modelleri üzerinden PostgreSQL'e yazar.
Yeni sütunlar (SQLite'da olmayan) nullable=True olduğu için NULL olarak kalır.

FK kontrolleri aktarım süresince devre dışı bırakılır (session_replication_role = replica).
Tablo sırası, Foreign Key bağımlılıklarından otomatik olarak (topolojik sıralama) türetilir.
"""

import os
import sys
import sqlite3
from datetime import datetime, date, time
from decimal import Decimal, InvalidOperation
from collections import defaultdict, deque

os.environ["FLASK_RUN_FROM_CLI"] = "false"

from app import create_app
from app.extensions import db
from config import Config


class MigrateConfig(Config):
    """PostgreSQL bağlantısını kullanan config (config.py'deki ayar zaten PG)."""
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        'postgresql://postgres:gizlisifre@db:5432/kiralama_db'


app = create_app(MigrateConfig)

SQLITE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'app.db')

from app.auth.models import User
from app.subeler.models import Sube, SubelerArasiTransfer
from app.ayarlar.models import AppSettings
from app.firmalar.models import Firma
from app.araclar.models import Arac
from app.filo.models import Ekipman, BakimKaydi, KullanilanParca, StokKarti, StokHareket
from app.cari.models import Kasa, Odeme, HizmetKaydi, CariHareket, CariMahsup
from app.kiralama.models import Kiralama, KiralamaKalemi
from app.nakliyeler.models import Nakliye
from app.makinedegisim.models import MakineDegisim
from app.fatura.models import Hakedis, HakedisKalemi
from app.takvim.models import TakvimHatirlatma

ALL_MODELS = {
    User:                 'user',
    Sube:                 'subeler',
    AppSettings:          'app_settings',
    Firma:                'firma',
    Arac:                 'araclar',
    Ekipman:              'ekipman',
    StokKarti:            'stok_karti',
    Kasa:                 'kasa',
    Kiralama:             'kiralama',
    KiralamaKalemi:       'kiralama_kalemi',
    Nakliye:              'nakliye',
    Odeme:                'odeme',
    HizmetKaydi:          'hizmet_kaydi',
    CariHareket:          'cari_hareket',
    CariMahsup:           'cari_mahsup',
    BakimKaydi:           'bakim_kaydi',
    KullanilanParca:      'kullanilan_parca',
    StokHareket:          'stok_hareket',
    MakineDegisim:        'makine_degisim',
    Hakedis:              'hakedis',
    HakedisKalemi:        'hakedis_kalemi',
    SubelerArasiTransfer: 'sube_transferleri',
    TakvimHatirlatma:     'takvim_hatirlatma',
}


def resolve_migration_order(model_map):
    table_to_model = {}
    for model_cls in model_map:
        table_to_model[model_cls.__tablename__] = model_cls

    all_tables = set(table_to_model.keys())
    deps = defaultdict(set)
    dependents = defaultdict(set)

    for model_cls in model_map:
        table = model_cls.__tablename__
        sa_table = model_cls.__table__

        for fk in sa_table.foreign_keys:
            parent_table = fk.column.table.name
            if parent_table == table:
                continue
            if parent_table not in all_tables:
                continue
            deps[table].add(parent_table)
            dependents[parent_table].add(table)

    in_degree = {t: len(deps[t]) for t in all_tables}
    queue = deque(t for t in all_tables if in_degree[t] == 0)
    ordered = []

    while queue:
        table = queue.popleft()
        ordered.append(table)
        for dep_table in dependents[table]:
            in_degree[dep_table] -= 1
            if in_degree[dep_table] == 0:
                queue.append(dep_table)

    remaining = [t for t in all_tables if t not in set(ordered)]
    if remaining:
        ordered.extend(remaining)

    result = []
    for table_name in ordered:
        model_cls = table_to_model[table_name]
        sqlite_name = model_map[model_cls]
        result.append((model_cls, sqlite_name))

    return result


def disable_fk_checks():
    db.session.execute(db.text("SET session_replication_role = 'replica'"))
    db.session.commit()


def enable_fk_checks():
    db.session.execute(db.text("SET session_replication_role = 'origin'"))
    db.session.commit()


def convert_value(value, column):
    if value is None:
        return None

    col_type = type(column.type)
    type_name = col_type.__name__

    if type_name == 'Boolean':
        if isinstance(value, str):
            return value.lower() in ('1', 'true', 'yes')
        return bool(value)

    if type_name == 'DateTime':
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            value = value.strip()
            for fmt in (
                '%Y-%m-%d %H:%M:%S.%f',
                '%Y-%m-%d %H:%M:%S',
                '%Y-%m-%dT%H:%M:%S.%f',
                '%Y-%m-%dT%H:%M:%S',
                '%Y-%m-%d',
            ):
                try:
                    return datetime.strptime(value, fmt)
                except ValueError:
                    continue
        return None

    if type_name == 'Date':
        if isinstance(value, date):
            return value
        if isinstance(value, str):
            value = value.strip()
            try:
                return datetime.strptime(value, '%Y-%m-%d').date()
            except ValueError:
                return None
        return None

    if type_name == 'Time':
        if isinstance(value, time):
            return value
        if isinstance(value, str):
            value = value.strip()
            for fmt in ('%H:%M:%S', '%H:%M:%S.%f', '%H:%M'):
                try:
                    return datetime.strptime(value, fmt).time()
                except ValueError:
                    continue
        return None

    if type_name == 'Numeric':
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError):
            return Decimal('0')

    if type_name == 'Float':
        try:
            return float(value)
        except (ValueError, TypeError):
            return None

    if type_name == 'Integer':
        try:
            return int(value)
        except (ValueError, TypeError):
            return None

    return value


def get_model_columns(model_class):
    from sqlalchemy import inspect as sa_inspect
    mapper = sa_inspect(model_class)
    columns = {}
    for attr in mapper.mapper.column_attrs:
        for col in attr.columns:
            columns[col.key] = col
    return columns


def migrate_table(sqlite_conn, model_class, sqlite_table):
    cursor = sqlite_conn.cursor()
    cursor.execute(f"PRAGMA table_info([{sqlite_table}])")
    sqlite_columns = [row[1] for row in cursor.fetchall()]
    model_columns = get_model_columns(model_class)
    common_columns = [c for c in sqlite_columns if c in model_columns]

    if not common_columns:
        print("  ⚠  Ortak sütun yok, atlanıyor.")
        return 0

    cols_sql = ', '.join(f'[{c}]' for c in common_columns)
    cursor.execute(f"SELECT {cols_sql} FROM [{sqlite_table}]")
    rows = cursor.fetchall()

    if not rows:
        print("  ○  Boş tablo, atlanıyor.")
        return 0

    count = 0
    skipped = []
    for row in rows:
        row_dict = dict(zip(common_columns, row))
        converted = {}
        for col_name, raw_value in row_dict.items():
            col_obj = model_columns[col_name]
            converted[col_name] = convert_value(raw_value, col_obj)

        try:
            nested = db.session.begin_nested()
            instance = model_class(**converted)
            db.session.add(instance)
            nested.commit()
            count += 1
        except Exception as exc:
            nested.rollback()
            row_id = converted.get('id', '?')
            skipped.append(row_id)
            print(f"  ⚠  Satır atlandı (id={row_id}): {exc}")

    if skipped:
        print(f"  ⚠  {len(skipped)} satır atlandı: {skipped}")

    return count


def reset_sequences(migration_order):
    print("\n● Sequence'lar güncelleniyor (pg_get_serial_sequence)...")

    for model_class, _ in migration_order:
        table_name = model_class.__tablename__
        model_cols = get_model_columns(model_class)
        if 'id' not in model_cols:
            continue

        try:
            seq_name = db.session.execute(
                db.text("SELECT pg_get_serial_sequence(:tbl, 'id')"),
                {'tbl': table_name}
            ).scalar()

            if not seq_name:
                print(f"  ○ {table_name}: sequence tanımlı değil, atlandı")
                continue

            max_id = db.session.execute(
                db.text(f'SELECT MAX(id) FROM "{table_name}"')
            ).scalar()

            if max_id is not None:
                db.session.execute(
                    db.text("SELECT setval(:seq, :val, true)"),
                    {'seq': seq_name, 'val': max_id}
                )
                print(f"  ✓ {table_name}: {seq_name} → {max_id}  (sonraki ID: {max_id + 1})")
            else:
                db.session.execute(
                    db.text("SELECT setval(:seq, 1, false)"),
                    {'seq': seq_name}
                )
                print(f"  ○ {table_name}: boş tablo, {seq_name} → 1'den başlayacak")

        except Exception as exc:
            print(f"  ⚠ {table_name}: {exc}")
            db.session.rollback()


def main():
    with app.app_context():
        print("=" * 60)
        print("  SQLite → PostgreSQL Veri Aktarımı")
        print("=" * 60)

        print("\n● PostgreSQL tabloları oluşturuluyor (create_all)...")
        db.create_all()
        print("  ✓ Tablolar hazır.")

        print("\n● Tablo sırası FK bağımlılıklarından hesaplanıyor...")
        migration_order = resolve_migration_order(ALL_MODELS)
        print("  Aktarım sırası:")
        for i, (model_cls, sqlite_tbl) in enumerate(migration_order, 1):
            print(f"    {i:2d}. {model_cls.__tablename__:<25s} ← SQLite: {sqlite_tbl}")

        if not os.path.exists(SQLITE_PATH):
            print(f"\n✗ SQLite dosyası bulunamadı: {SQLITE_PATH}")
            sys.exit(1)

        print(f"\n● SQLite kaynak: {SQLITE_PATH}")
        sqlite_conn = sqlite3.connect(SQLITE_PATH)

        print("\n● PostgreSQL FK kontrolleri devre dışı bırakılıyor...")
        disable_fk_checks()
        print("  ✓ SET session_replication_role = 'replica'")

        total = 0
        errors = []
        table_counts = []

        try:
            for model_class, sqlite_table in migration_order:
                table_display = model_class.__tablename__
                print(f"\n── {table_display} ({model_class.__name__}) ──")

                try:
                    count = migrate_table(sqlite_conn, model_class, sqlite_table)
                    db.session.commit()
                    if count > 0:
                        print(f"  ✓ {count} kayıt aktarıldı.")
                    table_counts.append((table_display, model_class.__name__, count, 'OK'))
                    total += count
                except Exception as exc:
                    db.session.rollback()
                    err_msg = f"{table_display}: {exc}"
                    errors.append(err_msg)
                    table_counts.append((table_display, model_class.__name__, 0, f'HATA: {exc}'))
                    print(f"  ✗ HATA: {exc}")

            reset_sequences(migration_order)
            db.session.commit()

        finally:
            print("\n● PostgreSQL FK kontrolleri tekrar etkinleştiriliyor...")
            enable_fk_checks()
            print("  ✓ SET session_replication_role = 'origin'")

        sqlite_conn.close()

        print("\n● PostgreSQL doğrulama sorgusu çalıştırılıyor...")
        pg_counts = {}
        for model_class, _ in migration_order:
            tbl = model_class.__tablename__
            try:
                pg_cnt = db.session.execute(
                    db.text(f'SELECT COUNT(*) FROM "{tbl}"')
                ).scalar()
                pg_counts[tbl] = pg_cnt
            except Exception:
                pg_counts[tbl] = '?'

        print("\n" + "=" * 72)
        print("  AKTARIM SONUÇ RAPORU")
        print("=" * 72)
        header = f"  {'Tablo':<25s} {'Model':<22s} {'SQLite':>7s} {'PG':>7s}  Durum"
        print(header)
        print("  " + "-" * 68)

        for tbl_name, model_name, sqlite_cnt, status in table_counts:
            pg_cnt = pg_counts.get(tbl_name, '?')
            if status == 'OK' and sqlite_cnt > 0:
                icon = '✓'
            elif status == 'OK' and sqlite_cnt == 0:
                icon = '○'
            else:
                icon = '✗'
            print(f"  {tbl_name:<25s} {model_name:<22s} {sqlite_cnt:>7d} {str(pg_cnt):>7s}  {icon} {status}")

        print("  " + "-" * 68)
        pg_total = sum(v for v in pg_counts.values() if isinstance(v, int))
        print(f"  {'TOPLAM':<25s} {'':<22s} {total:>7d} {pg_total:>7d}")
        print("=" * 72)

        if errors:
            print(f"\n  HATALAR ({len(errors)}):")
            for error in errors:
                print(f"    • {error}")
        else:
            print("\n  ✓ Tüm tablolar hatasız aktarıldı!")

        print("\n  ℹ  Atlanan SQLite tabloları (modelsiz):")
        print("      - alembic_version (migration metadata)")
        print("      - operation_log   (uygulama logu, model yok)")
        print("=" * 72)


if __name__ == '__main__':
    main()
