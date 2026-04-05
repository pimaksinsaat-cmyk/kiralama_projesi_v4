"""Kullanilan parcayi hibrit malzeme yap

Revision ID: 91c4d2e7ab55
Revises: 7f3a9e2b6c41
Create Date: 2026-04-04 19:45:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = '91c4d2e7ab55'
down_revision = '7f3a9e2b6c41'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('kullanilan_parca', schema=None) as batch_op:
        batch_op.alter_column('stok_karti_id', existing_type=sa.Integer(), nullable=True)
        batch_op.add_column(sa.Column('malzeme_adi', sa.String(length=250), nullable=True))


def downgrade():
    with op.batch_alter_table('kullanilan_parca', schema=None) as batch_op:
        batch_op.drop_column('malzeme_adi')
        batch_op.alter_column('stok_karti_id', existing_type=sa.Integer(), nullable=False)
