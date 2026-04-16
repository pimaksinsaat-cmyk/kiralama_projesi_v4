"""Odeme ve HizmetKaydi aggregation indeksleri ekle

Revision ID: f4a7c2d9e1b0
Revises: c3f4d9b1a2ef
Create Date: 2026-04-15 23:05:00.000000
"""

from alembic import op


# revision identifiers, used by Alembic.
revision = 'f4a7c2d9e1b0'
down_revision = 'c3f4d9b1a2ef'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('odeme', schema=None) as batch_op:
        batch_op.create_index(
            'ix_odeme_firma_deleted_yon',
            ['firma_musteri_id', 'is_deleted', 'yon'],
            unique=False,
        )

    with op.batch_alter_table('hizmet_kaydi', schema=None) as batch_op:
        batch_op.create_index(
            'ix_hizmet_kaydi_firma_deleted_yon',
            ['firma_id', 'is_deleted', 'yon'],
            unique=False,
        )


def downgrade():
    with op.batch_alter_table('hizmet_kaydi', schema=None) as batch_op:
        batch_op.drop_index('ix_hizmet_kaydi_firma_deleted_yon')

    with op.batch_alter_table('odeme', schema=None) as batch_op:
        batch_op.drop_index('ix_odeme_firma_deleted_yon')
