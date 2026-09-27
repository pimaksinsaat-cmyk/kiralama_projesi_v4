"""Aktif sefer taşeron giderini sefer bazında tekilleştir.

Revision ID: c3d4e5f6a7b8
Revises: c2d3e4f5a6b7
"""

from alembic import op


revision = 'c3d4e5f6a7b8'
down_revision = 'c2d3e4f5a6b7'
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        'uq_hizmet_aktif_sefer_taseron_gider',
        'hizmet_kaydi',
        ['nakliye_id'],
        unique=True,
        postgresql_where=(
            "is_deleted = false AND is_active = true "
            "AND nakliye_id IS NOT NULL "
            "AND kaynak = 'nakliye_sefer_taseron_gider'"
        ),
    )


def downgrade():
    op.drop_index(
        'uq_hizmet_aktif_sefer_taseron_gider',
        table_name='hizmet_kaydi',
    )
