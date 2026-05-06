"""nakliye_taseron_kdv_orani_ekle

Revision ID: t5u6v7w8x9y0
Revises: s4t5u6v7w8x9
Create Date: 2026-05-06 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = 't5u6v7w8x9y0'
down_revision = 's4t5u6v7w8x9'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('nakliye') as batch_op:
        batch_op.add_column(sa.Column('taseron_kdv_orani', sa.Integer(), nullable=True, server_default='20'))

    op.execute("UPDATE nakliye SET taseron_kdv_orani = COALESCE(kdv_orani, 20) WHERE nakliye_tipi = 'taseron' AND taseron_kdv_orani IS NULL")


def downgrade():
    with op.batch_alter_table('nakliye') as batch_op:
        batch_op.drop_column('taseron_kdv_orani')
