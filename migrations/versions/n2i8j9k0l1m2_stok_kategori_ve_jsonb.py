"""stok_kategori_ve_jsonb

Revision ID: n2i8j9k0l1m2
Revises: m1h7i8j9k0l1
Create Date: 2026-04-26 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = 'n2i8j9k0l1m2'
down_revision = 'm1h7i8j9k0l1'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()

    # stok_kategori tablosu
    conn.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS stok_kategori (
            id SERIAL PRIMARY KEY,
            kategori_adi VARCHAR(150) NOT NULL,
            parent_id INTEGER REFERENCES stok_kategori(id),
            is_active BOOLEAN NOT NULL DEFAULT TRUE
        )
    """))

    # stok_karti'ye kategori_id ve ozellikler kolonları
    conn.execute(sa.text(
        'ALTER TABLE stok_karti ADD COLUMN IF NOT EXISTS kategori_id INTEGER REFERENCES stok_kategori(id)'
    ))
    conn.execute(sa.text(
        "ALTER TABLE stok_karti ADD COLUMN IF NOT EXISTS ozellikler JSONB DEFAULT '{}'"
    ))

    # JSONB GIN index — ozellikler içinde anahtar/değer araması için
    conn.execute(sa.text(
        'CREATE INDEX IF NOT EXISTS ix_stok_karti_ozellikler_gin ON stok_karti USING GIN (ozellikler)'
    ))


def downgrade():
    conn = op.get_bind()
    conn.execute(sa.text('DROP INDEX IF EXISTS ix_stok_karti_ozellikler_gin'))
    conn.execute(sa.text('ALTER TABLE stok_karti DROP COLUMN IF EXISTS ozellikler'))
    conn.execute(sa.text('ALTER TABLE stok_karti DROP COLUMN IF EXISTS kategori_id'))
    conn.execute(sa.text('DROP TABLE IF EXISTS stok_kategori'))
