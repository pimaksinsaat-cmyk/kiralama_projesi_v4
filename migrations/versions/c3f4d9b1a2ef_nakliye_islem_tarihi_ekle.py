"""Nakliye tablosuna islem_tarihi ekle

Revision ID: c3f4d9b1a2ef
Revises: e862a8e8eafc
Create Date: 2026-04-15 21:20:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c3f4d9b1a2ef'
down_revision = 'e862a8e8eafc'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('nakliye', schema=None) as batch_op:
        batch_op.add_column(sa.Column('islem_tarihi', sa.Date(), nullable=True))
        batch_op.create_index(
            batch_op.f('ix_nakliye_islem_tarihi'),
            ['islem_tarihi'],
            unique=False
        )


def downgrade():
    with op.batch_alter_table('nakliye', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_nakliye_islem_tarihi'))
        batch_op.drop_column('islem_tarihi')
