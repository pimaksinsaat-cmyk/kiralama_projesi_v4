"""stok_hareket_kdv_orani_ekle

Revision ID: 5a9c2d1e7b44
Revises: 1e7b3d4c9a20, f1c3b9a5d7e2
Create Date: 2026-04-05 18:25:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '5a9c2d1e7b44'
down_revision = ('1e7b3d4c9a20', 'f1c3b9a5d7e2')
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    conn.execute(sa.text('ALTER TABLE stok_hareket ADD COLUMN IF NOT EXISTS kdv_orani INTEGER'))


def downgrade():
    with op.batch_alter_table('stok_hareket', schema=None) as batch_op:
        batch_op.drop_column('kdv_orani')