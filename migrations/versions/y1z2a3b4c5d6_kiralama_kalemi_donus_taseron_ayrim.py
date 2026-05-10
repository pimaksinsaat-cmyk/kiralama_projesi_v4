"""kiralama kalemi donus taseron alanlari

Revision ID: y1z2a3b4c5d6
Revises: x0y1z2a3b4c5
Create Date: 2026-05-10

"""
from alembic import op
import sqlalchemy as sa


revision = 'y1z2a3b4c5d6'
down_revision = 'x0y1z2a3b4c5'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('kiralama_kalemi', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('donus_is_harici_nakliye', sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch_op.add_column(
            sa.Column('donus_nakliye_tedarikci_id', sa.Integer(), nullable=True)
        )
        batch_op.add_column(
            sa.Column('donus_nakliye_alis_fiyat', sa.Numeric(precision=15, scale=2), nullable=True)
        )
        batch_op.add_column(
            sa.Column('donus_nakliye_araci_id', sa.Integer(), nullable=True)
        )
        batch_op.create_foreign_key(
            'fk_kiralama_kalemi_donus_nakliye_tedarikci',
            'firma',
            ['donus_nakliye_tedarikci_id'],
            ['id'],
        )
        batch_op.create_foreign_key(
            'fk_kiralama_kalemi_donus_nakliye_araci',
            'araclar',
            ['donus_nakliye_araci_id'],
            ['id'],
        )
        batch_op.alter_column(
            'donus_is_harici_nakliye',
            server_default=None,
        )


def downgrade():
    with op.batch_alter_table('kiralama_kalemi', schema=None) as batch_op:
        batch_op.drop_constraint('fk_kiralama_kalemi_donus_nakliye_araci', type_='foreignkey')
        batch_op.drop_constraint('fk_kiralama_kalemi_donus_nakliye_tedarikci', type_='foreignkey')
        batch_op.drop_column('donus_nakliye_araci_id')
        batch_op.drop_column('donus_nakliye_alis_fiyat')
        batch_op.drop_column('donus_nakliye_tedarikci_id')
        batch_op.drop_column('donus_is_harici_nakliye')
