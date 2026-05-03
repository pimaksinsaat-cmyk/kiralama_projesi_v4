"""teklif_kalemi_nakliye_yon

Revision ID: r3s4t5u6v7w8
Revises: q2r3s4t5u6v7
Create Date: 2026-05-03 15:45:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'r3s4t5u6v7w8'
down_revision = 'q2r3s4t5u6v7'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'teklif_kalemi',
        sa.Column('nakliye_yon', sa.String(length=20), nullable=False, server_default='tek_yon'),
    )
    op.alter_column('teklif_kalemi', 'nakliye_yon', server_default=None)


def downgrade():
    op.drop_column('teklif_kalemi', 'nakliye_yon')
