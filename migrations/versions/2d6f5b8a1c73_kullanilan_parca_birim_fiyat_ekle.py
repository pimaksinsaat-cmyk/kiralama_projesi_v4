"""Kullanilan parca birim fiyat alanini ekle

Revision ID: 2d6f5b8a1c73
Revises: 91c4d2e7ab55
Create Date: 2026-04-04 20:18:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = '2d6f5b8a1c73'
down_revision = '91c4d2e7ab55'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('kullanilan_parca', schema=None) as batch_op:
        batch_op.add_column(sa.Column('birim_fiyat', sa.Numeric(precision=15, scale=2), nullable=True))


def downgrade():
    with op.batch_alter_table('kullanilan_parca', schema=None) as batch_op:
        batch_op.drop_column('birim_fiyat')
