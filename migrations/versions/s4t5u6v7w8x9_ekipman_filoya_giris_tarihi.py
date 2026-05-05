"""ekipman filoya giris tarihi

Revision ID: s4t5u6v7w8x9
Revises: r3s4t5u6v7w8
Create Date: 2026-05-05 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = 's4t5u6v7w8x9'
down_revision = 'r3s4t5u6v7w8'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('ekipman', schema=None) as batch_op:
        batch_op.add_column(sa.Column('filoya_giris_tarihi', sa.Date(), nullable=True))


def downgrade():
    with op.batch_alter_table('ekipman', schema=None) as batch_op:
        batch_op.drop_column('filoya_giris_tarihi')
