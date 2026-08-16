"""teklif kalemlerine harici ekipman ve nakliye alanlari ekle

Revision ID: a4b5c6d7e8f0
Revises: c1d2e3f4a5b6
Create Date: 2026-08-16 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'a4b5c6d7e8f0'
down_revision = 'c1d2e3f4a5b6'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'teklif_kalemi',
        sa.Column('is_dis_tedarik_ekipman', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        'teklif_kalemi',
        sa.Column('harici_ekipman_tedarikci_id', sa.Integer(), nullable=True),
    )
    op.add_column(
        'teklif_kalemi',
        sa.Column('harici_ekipman_seri_no', sa.String(length=100), nullable=True),
    )
    op.add_column(
        'teklif_kalemi',
        sa.Column('is_harici_nakliye', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        'teklif_kalemi',
        sa.Column('nakliye_tedarikci_id', sa.Integer(), nullable=True),
    )

    op.create_foreign_key(
        'fk_teklif_kalemi_harici_ekipman_tedarikci',
        'teklif_kalemi', 'firma',
        ['harici_ekipman_tedarikci_id'], ['id'],
    )
    op.create_foreign_key(
        'fk_teklif_kalemi_nakliye_tedarikci',
        'teklif_kalemi', 'firma',
        ['nakliye_tedarikci_id'], ['id'],
    )
    op.create_index(
        'ix_teklif_kalemi_harici_ekipman_tedarikci_id',
        'teklif_kalemi', ['harici_ekipman_tedarikci_id'], unique=False,
    )
    op.create_index(
        'ix_teklif_kalemi_nakliye_tedarikci_id',
        'teklif_kalemi', ['nakliye_tedarikci_id'], unique=False,
    )
    op.alter_column('teklif_kalemi', 'is_dis_tedarik_ekipman', server_default=None)
    op.alter_column('teklif_kalemi', 'is_harici_nakliye', server_default=None)


def downgrade():
    op.drop_index('ix_teklif_kalemi_nakliye_tedarikci_id', table_name='teklif_kalemi')
    op.drop_index('ix_teklif_kalemi_harici_ekipman_tedarikci_id', table_name='teklif_kalemi')
    op.drop_constraint('fk_teklif_kalemi_nakliye_tedarikci', 'teklif_kalemi', type_='foreignkey')
    op.drop_constraint('fk_teklif_kalemi_harici_ekipman_tedarikci', 'teklif_kalemi', type_='foreignkey')
    op.drop_column('teklif_kalemi', 'nakliye_tedarikci_id')
    op.drop_column('teklif_kalemi', 'is_harici_nakliye')
    op.drop_column('teklif_kalemi', 'harici_ekipman_seri_no')
    op.drop_column('teklif_kalemi', 'harici_ekipman_tedarikci_id')
    op.drop_column('teklif_kalemi', 'is_dis_tedarik_ekipman')
