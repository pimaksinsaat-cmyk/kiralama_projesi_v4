"""bakim_yol_maliyeti_ekle

Revision ID: k9f5g6h7i8j9
Revises: j8e4f5g6h7i8
Create Date: 2026-04-26 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'k9f5g6h7i8j9'
down_revision = 'j8e4f5g6h7i8'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('bakim_kaydi', sa.Column('yol_maliyeti', sa.Numeric(15, 2), nullable=False, server_default='0'))


def downgrade():
    op.drop_column('bakim_kaydi', 'yol_maliyeti')
