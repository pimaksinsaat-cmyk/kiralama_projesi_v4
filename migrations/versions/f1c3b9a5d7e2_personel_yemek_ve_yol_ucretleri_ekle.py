"""personel_yemek_ve_yol_ucretleri_ekle

Revision ID: f1c3b9a5d7e2
Revises: e4b7c9d1f2a6
Create Date: 2026-04-05 11:25:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = 'f1c3b9a5d7e2'
down_revision = 'e4b7c9d1f2a6'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('personel', sa.Column('yemek_ucreti', sa.Numeric(15, 2), nullable=True))
    op.add_column('personel', sa.Column('yol_ucreti', sa.Numeric(15, 2), nullable=True))

    op.add_column('personel_maas_donemleri', sa.Column('aylik_yemek_ucreti', sa.Numeric(15, 2), nullable=True))
    op.add_column('personel_maas_donemleri', sa.Column('aylik_yol_ucreti', sa.Numeric(15, 2), nullable=True))


def downgrade():
    op.drop_column('personel_maas_donemleri', 'aylik_yol_ucreti')
    op.drop_column('personel_maas_donemleri', 'aylik_yemek_ucreti')

    op.drop_column('personel', 'yol_ucreti')
    op.drop_column('personel', 'yemek_ucreti')