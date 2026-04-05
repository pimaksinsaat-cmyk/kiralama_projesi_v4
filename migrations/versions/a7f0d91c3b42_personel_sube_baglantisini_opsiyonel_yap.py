"""Personel sube baglantisini opsiyonel yap

Revision ID: a7f0d91c3b42
Revises: 9c1e4f7a2b63
Create Date: 2026-04-05 15:10:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = 'a7f0d91c3b42'
down_revision = '9c1e4f7a2b63'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('personel', schema=None) as batch_op:
        batch_op.alter_column('sube_id', existing_type=sa.Integer(), nullable=True)


def downgrade():
    connection = op.get_bind()
    varsayilan_sube_id = connection.execute(sa.text('SELECT id FROM subeler ORDER BY id LIMIT 1')).scalar()
    if varsayilan_sube_id is None:
        raise RuntimeError('Personel.sube_id kolonunu geri zorunlu yapmak icin en az bir sube kaydi bulunmali.')

    connection.execute(
        sa.text('UPDATE personel SET sube_id = :sube_id WHERE sube_id IS NULL'),
        {'sube_id': varsayilan_sube_id},
    )

    with op.batch_alter_table('personel', schema=None) as batch_op:
        batch_op.alter_column('sube_id', existing_type=sa.Integer(), nullable=False)