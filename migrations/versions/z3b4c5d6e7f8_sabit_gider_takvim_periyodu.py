"""sabit gider takvim periyodu

Revision ID: z3b4c5d6e7f8
Revises: z2a3b4c5d6e7
Create Date: 2026-06-07
"""

from alembic import op
import sqlalchemy as sa


revision = 'z3b4c5d6e7f8'
down_revision = 'z2a3b4c5d6e7'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'sube_sabit_gider_donemleri',
        sa.Column('periyot_tipi', sa.String(length=10), nullable=False, server_default='ay'),
    )
    op.add_column(
        'sube_sabit_gider_donemleri',
        sa.Column('periyot_degeri', sa.Integer(), nullable=False, server_default='1'),
    )
    op.execute(
        "UPDATE sube_sabit_gider_donemleri "
        "SET periyot_tipi = 'ay', periyot_degeri = 1 "
        "WHERE periyot_tipi IS NULL OR periyot_degeri IS NULL"
    )


def downgrade():
    op.drop_column('sube_sabit_gider_donemleri', 'periyot_degeri')
    op.drop_column('sube_sabit_gider_donemleri', 'periyot_tipi')
