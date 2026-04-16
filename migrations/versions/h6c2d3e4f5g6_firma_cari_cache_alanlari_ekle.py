"""Firma tablosuna cari durum raporu cache alanları ekle

Revision ID: h6c2d3e4f5g6
Revises: g5b1c2d3e4f5
Create Date: 2026-04-16 14:00:00.000000

Cari durum raporu artık bakiye_ozeti yerine build_cari_rows sonucunu
Firma tablosundaki cache alanlarından okur. Bu migration cache sütunlarını ekler.
"""

from alembic import op
import sqlalchemy as sa


revision = 'h6c2d3e4f5g6'
down_revision = 'g5b1c2d3e4f5'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('firma', sa.Column('cari_borc_kdvli', sa.Numeric(15, 2), nullable=False, server_default='0'))
    op.add_column('firma', sa.Column('cari_alacak_kdvli', sa.Numeric(15, 2), nullable=False, server_default='0'))
    op.add_column('firma', sa.Column('cari_bakiye_kdvli', sa.Numeric(15, 2), nullable=False, server_default='0'))
    op.add_column('firma', sa.Column('cari_son_guncelleme', sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column('firma', 'cari_son_guncelleme')
    op.drop_column('firma', 'cari_bakiye_kdvli')
    op.drop_column('firma', 'cari_alacak_kdvli')
    op.drop_column('firma', 'cari_borc_kdvli')
