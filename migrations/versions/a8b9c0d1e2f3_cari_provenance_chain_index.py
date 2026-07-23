"""cari provenance ve tedarikci tahakkuk tekilligi

Revision ID: a8b9c0d1e2f3
Revises: z3b4c5d6e7f8
"""

from alembic import op
import sqlalchemy as sa


revision = 'a8b9c0d1e2f3'
down_revision = 'z3b4c5d6e7f8'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'hizmet_kaydi',
        sa.Column('kaynak', sa.String(length=40), nullable=True),
    )
    op.create_index(
        'ix_hizmet_kaydi_kaynak',
        'hizmet_kaydi',
        ['kaynak'],
        unique=False,
    )
    op.create_index(
        'uq_hizmet_kaydi_dis_kiralama_aktif',
        'hizmet_kaydi',
        ['firma_id', 'ozel_id', 'yon'],
        unique=True,
        postgresql_where=sa.text(
            "is_deleted = false AND kaynak = 'dis_kiralama_tahakkuk'"
        ),
        sqlite_where=sa.text(
            "is_deleted = 0 AND kaynak = 'dis_kiralama_tahakkuk'"
        ),
    )


def downgrade():
    op.drop_index('uq_hizmet_kaydi_dis_kiralama_aktif', table_name='hizmet_kaydi')
    op.drop_index('ix_hizmet_kaydi_kaynak', table_name='hizmet_kaydi')
    op.drop_column('hizmet_kaydi', 'kaynak')
