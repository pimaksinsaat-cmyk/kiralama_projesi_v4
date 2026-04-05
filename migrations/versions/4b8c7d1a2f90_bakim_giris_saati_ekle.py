"""Bakim giris saati alanini ekle

Revision ID: 4b8c7d1a2f90
Revises: c9e5f2a4b7d1
Create Date: 2026-04-04 18:05:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = '4b8c7d1a2f90'
down_revision = 'c9e5f2a4b7d1'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('bakim_kaydi', schema=None) as batch_op:
        batch_op.add_column(sa.Column('bakima_giris_saati', sa.Time(), nullable=True))


def downgrade():
    with op.batch_alter_table('bakim_kaydi', schema=None) as batch_op:
        batch_op.drop_column('bakima_giris_saati')
