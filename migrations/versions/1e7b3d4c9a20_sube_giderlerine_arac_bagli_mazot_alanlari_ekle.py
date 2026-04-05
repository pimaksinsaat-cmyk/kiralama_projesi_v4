"""sube_giderlerine_arac_bagli_mazot_alanlari_ekle

Revision ID: 1e7b3d4c9a20
Revises: 6c4d2a9b8f10
Create Date: 2026-04-05 16:05:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '1e7b3d4c9a20'
down_revision = '6c4d2a9b8f10'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('sube_giderleri', schema=None) as batch_op:
        batch_op.add_column(sa.Column('arac_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('litre', sa.Numeric(precision=10, scale=2), nullable=True))
        batch_op.add_column(sa.Column('birim_fiyat', sa.Numeric(precision=10, scale=2), nullable=True))
        batch_op.add_column(sa.Column('km', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('istasyon', sa.String(length=150), nullable=True))
        batch_op.create_index(batch_op.f('ix_sube_giderleri_arac_id'), ['arac_id'], unique=False)
        batch_op.create_foreign_key('fk_sube_giderleri_arac_id_araclar', 'araclar', ['arac_id'], ['id'])


def downgrade():
    with op.batch_alter_table('sube_giderleri', schema=None) as batch_op:
        batch_op.drop_constraint('fk_sube_giderleri_arac_id_araclar', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_sube_giderleri_arac_id'))
        batch_op.drop_column('istasyon')
        batch_op.drop_column('km')
        batch_op.drop_column('birim_fiyat')
        batch_op.drop_column('litre')
        batch_op.drop_column('arac_id')