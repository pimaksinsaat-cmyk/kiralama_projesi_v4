"""teklif_kalemi_fiyat_tipi

Revision ID: q2r3s4t5u6v7
Revises: p1q2r3s4t5u6
Create Date: 2026-05-03 15:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'q2r3s4t5u6v7'
down_revision = 'p1q2r3s4t5u6'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'teklif_kalemi',
        sa.Column('fiyat_tipi', sa.String(length=20), nullable=False, server_default='gunluk'),
    )
    op.alter_column('teklif_kalemi', 'fiyat_tipi', server_default=None)


def downgrade():
    op.drop_column('teklif_kalemi', 'fiyat_tipi')
