"""kiralama kalem dondurma tablosu

Revision ID: a4b5c6d7e8f9
Revises: z3b4c5d6e7f8
Create Date: 2026-06-10
"""

from alembic import op
import sqlalchemy as sa


revision = 'a4b5c6d7e8f9'
down_revision = 'z3b4c5d6e7f8'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'kiralama_kalem_dondurma',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('created_by_id', sa.Integer(), nullable=True),
        sa.Column('updated_by_id', sa.Integer(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.Column('deleted_by_id', sa.Integer(), nullable=True),
        sa.Column('kalem_id', sa.Integer(), nullable=False),
        sa.Column('baslangic_tarihi', sa.Date(), nullable=False),
        sa.Column('bitis_tarihi', sa.Date(), nullable=False),
        sa.Column('muaf_gun_sayisi', sa.Integer(), nullable=False),
        sa.Column('aciklama', sa.Text(), nullable=True),
        sa.Column('tedarikci_alis_dondur', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.ForeignKeyConstraint(['kalem_id'], ['kiralama_kalemi.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_kiralama_kalem_dondurma_is_active'),
        'kiralama_kalem_dondurma',
        ['is_active'],
        unique=False,
    )
    op.create_index(
        op.f('ix_kiralama_kalem_dondurma_is_deleted'),
        'kiralama_kalem_dondurma',
        ['is_deleted'],
        unique=False,
    )
    op.create_index(
        op.f('ix_kiralama_kalem_dondurma_kalem_id'),
        'kiralama_kalem_dondurma',
        ['kalem_id'],
        unique=False,
    )


def downgrade():
    op.drop_index(op.f('ix_kiralama_kalem_dondurma_kalem_id'), table_name='kiralama_kalem_dondurma')
    op.drop_index(op.f('ix_kiralama_kalem_dondurma_is_deleted'), table_name='kiralama_kalem_dondurma')
    op.drop_index(op.f('ix_kiralama_kalem_dondurma_is_active'), table_name='kiralama_kalem_dondurma')
    op.drop_table('kiralama_kalem_dondurma')
