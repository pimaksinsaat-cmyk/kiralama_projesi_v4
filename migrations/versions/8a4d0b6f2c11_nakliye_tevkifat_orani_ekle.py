"""Nakliye tevkifat orani ekle

Revision ID: 8a4d0b6f2c11
Revises: 3f1f2d7c9a01
Create Date: 2026-04-04 12:05:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '8a4d0b6f2c11'
down_revision = '3f1f2d7c9a01'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('nakliye', schema=None) as batch_op:
        batch_op.add_column(sa.Column('tevkifat_orani', sa.String(length=10), nullable=True))


def downgrade():
    with op.batch_alter_table('nakliye', schema=None) as batch_op:
        batch_op.drop_column('tevkifat_orani')