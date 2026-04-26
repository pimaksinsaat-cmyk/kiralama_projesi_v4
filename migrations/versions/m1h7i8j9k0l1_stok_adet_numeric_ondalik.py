"""stok_adet_numeric_ondalik_ve_birim

Revision ID: m1h7i8j9k0l1
Revises: l0g6h7i8j9k0
Create Date: 2026-04-26 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'm1h7i8j9k0l1'
down_revision = 'l0g6h7i8j9k0'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    conn.execute(sa.text(
        'ALTER TABLE stok_hareket ALTER COLUMN adet TYPE NUMERIC(15,3)'
    ))
    conn.execute(sa.text(
        'ALTER TABLE stok_karti ALTER COLUMN mevcut_stok TYPE NUMERIC(15,3)'
    ))
    conn.execute(sa.text(
        "ALTER TABLE stok_karti ADD COLUMN IF NOT EXISTS birim VARCHAR(20) DEFAULT 'adet'"
    ))


def downgrade():
    conn = op.get_bind()
    conn.execute(sa.text(
        'ALTER TABLE stok_hareket ALTER COLUMN adet TYPE INTEGER USING adet::integer'
    ))
    conn.execute(sa.text(
        'ALTER TABLE stok_karti ALTER COLUMN mevcut_stok TYPE INTEGER USING mevcut_stok::integer'
    ))
    conn.execute(sa.text(
        'ALTER TABLE stok_karti DROP COLUMN IF EXISTS birim'
    ))
