"""kiralama kalemi donus nakliye alis kdv

Revision ID: x0y1z2a3b4c5
Revises: w9x0y1z2a3b4
Create Date: 2026-05-10
"""

from alembic import op
import sqlalchemy as sa


revision = 'x0y1z2a3b4c5'
down_revision = 'w9x0y1z2a3b4'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('kiralama_kalemi', schema=None) as batch_op:
        batch_op.add_column(sa.Column('donus_nakliye_alis_kdv', sa.Integer(), nullable=True))


def downgrade():
    with op.batch_alter_table('kiralama_kalemi', schema=None) as batch_op:
        batch_op.drop_column('donus_nakliye_alis_kdv')
