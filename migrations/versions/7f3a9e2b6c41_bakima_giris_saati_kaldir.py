"""Bakima giris saati alanini kaldir

Revision ID: 7f3a9e2b6c41
Revises: 4b8c7d1a2f90
Create Date: 2026-04-04 18:18:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = '7f3a9e2b6c41'
down_revision = '4b8c7d1a2f90'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('bakim_kaydi', schema=None) as batch_op:
        batch_op.drop_column('bakima_giris_saati')


def downgrade():
    with op.batch_alter_table('bakim_kaydi', schema=None) as batch_op:
        batch_op.add_column(sa.Column('bakima_giris_saati', sa.Time(), nullable=True))
