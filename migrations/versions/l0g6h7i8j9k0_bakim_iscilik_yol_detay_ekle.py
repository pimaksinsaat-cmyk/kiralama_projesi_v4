"""bakim_iscilik_yol_detay_ekle

Revision ID: l0g6h7i8j9k0
Revises: k9f5g6h7i8j9
Create Date: 2026-04-26 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'l0g6h7i8j9k0'
down_revision = 'k9f5g6h7i8j9'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('bakim_kaydi', sa.Column('iscilik_saat', sa.Numeric(10, 2), nullable=True))
    op.add_column('bakim_kaydi', sa.Column('iscilik_saat_ucreti', sa.Numeric(15, 2), nullable=True))
    op.add_column('bakim_kaydi', sa.Column('yol_km', sa.Numeric(10, 2), nullable=True))
    op.add_column('bakim_kaydi', sa.Column('yol_km_ucreti', sa.Numeric(15, 2), nullable=True))


def downgrade():
    op.drop_column('bakim_kaydi', 'yol_km_ucreti')
    op.drop_column('bakim_kaydi', 'yol_km')
    op.drop_column('bakim_kaydi', 'iscilik_saat_ucreti')
    op.drop_column('bakim_kaydi', 'iscilik_saat')
