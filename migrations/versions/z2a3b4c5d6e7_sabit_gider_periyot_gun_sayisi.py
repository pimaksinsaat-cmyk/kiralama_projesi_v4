"""sabit gider periyot gun sayisi

Revision ID: z2a3b4c5d6e7
Revises: y1z2a3b4c5d6
Create Date: 2026-06-07
"""

from alembic import op
import sqlalchemy as sa


revision = 'z2a3b4c5d6e7'
down_revision = 'y1z2a3b4c5d6'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'sube_sabit_gider_donemleri',
        sa.Column('periyot_gun_sayisi', sa.Integer(), nullable=False, server_default='30'),
    )
    op.execute(
        "UPDATE sube_sabit_gider_donemleri "
        "SET periyot_gun_sayisi = 30 "
        "WHERE periyot_gun_sayisi IS NULL"
    )
    op.execute(
        "UPDATE sube_sabit_gider_donemleri "
        "SET apply_retroactively = false "
        "WHERE apply_retroactively = true"
    )


def downgrade():
    op.drop_column('sube_sabit_gider_donemleri', 'periyot_gun_sayisi')
