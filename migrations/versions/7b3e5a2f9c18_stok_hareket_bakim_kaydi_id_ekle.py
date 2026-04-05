"""stok_hareket_bakim_kaydi_id_ekle

Revision ID: 7b3e5a2f9c18
Revises: 5a9c2d1e7b44
Create Date: 2026-04-05 19:10:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '7b3e5a2f9c18'
down_revision = '5a9c2d1e7b44'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('stok_hareket', schema=None) as batch_op:
        batch_op.add_column(sa.Column('bakim_kaydi_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            'fk_stok_hareket_bakim_kaydi_id',
            'bakim_kaydi',
            ['bakim_kaydi_id'],
            ['id'],
        )


def downgrade():
    with op.batch_alter_table('stok_hareket', schema=None) as batch_op:
        batch_op.drop_constraint('fk_stok_hareket_bakim_kaydi_id', type_='foreignkey')
        batch_op.drop_column('bakim_kaydi_id')
