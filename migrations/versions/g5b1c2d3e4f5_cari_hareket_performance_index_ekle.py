"""Add composite index for cari_hareket performance optimization

Revision ID: g5b1c2d3e4f5
Revises: f4a7c2d9e1b0
Create Date: 2026-04-16 10:00:00.000000

Bekleyen bakiye (açık bakiye) sorguları için composite index ekler.
10K firma × 10K hareket senaryosu için ölçeklenebilirlik iyileştirmesi.
"""

from alembic import op


# revision identifiers, used by Alembic.
revision = 'g5b1c2d3e4f5'
down_revision = 'f4a7c2d9e1b0'
branch_labels = None
depends_on = None


def upgrade():
    """CariHareket tablosuna composite index ekle."""
    with op.batch_alter_table('cari_hareket', schema=None) as batch_op:
        batch_op.create_index(
            'ix_cari_hareket_firma_deleted_yon_durum',
            ['firma_id', 'is_deleted', 'yon', 'durum'],
            unique=False,
        )


def downgrade():
    """Composite index'i kaldır."""
    with op.batch_alter_table('cari_hareket', schema=None) as batch_op:
        batch_op.drop_index('ix_cari_hareket_firma_deleted_yon_durum')
