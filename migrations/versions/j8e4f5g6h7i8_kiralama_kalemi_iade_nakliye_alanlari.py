"""kiralama_kalemi_iade_nakliye_alanlari

Revision ID: j8e4f5g6h7i8
Revises: i7d3e4f5g6h7
Create Date: 2026-04-22 09:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'j8e4f5g6h7i8'
down_revision = 'i7d3e4f5g6h7'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('kiralama_kalemi', sa.Column('iade_tarihi', sa.Date(), nullable=True))
    op.add_column('kiralama_kalemi', sa.Column('iade_nakliye_var', sa.Boolean(), nullable=True))
    op.add_column('kiralama_kalemi', sa.Column('iade_nakliye_oz_mal', sa.Boolean(), nullable=True))
    op.add_column('kiralama_kalemi', sa.Column('iade_nakliye_arac_id', sa.Integer(), nullable=True))
    op.add_column('kiralama_kalemi', sa.Column('iade_nakliye_tedarikci_id', sa.Integer(), nullable=True))
    op.add_column('kiralama_kalemi', sa.Column('iade_nakliye_fiyat', sa.Numeric(15, 2), nullable=True))
    op.add_column('kiralama_kalemi', sa.Column('iade_nakliye_kdv', sa.Integer(), nullable=True))
    op.add_column('kiralama_kalemi', sa.Column('iade_aciklama', sa.Text(), nullable=True))
    op.create_foreign_key(
        'fk_kiralama_kalemi_iade_nakliye_arac_id',
        'kiralama_kalemi', 'araclar',
        ['iade_nakliye_arac_id'], ['id'], ondelete='SET NULL'
    )
    op.create_foreign_key(
        'fk_kiralama_kalemi_iade_nakliye_tedarikci_id',
        'kiralama_kalemi', 'firma',
        ['iade_nakliye_tedarikci_id'], ['id'], ondelete='SET NULL'
    )


def downgrade():
    op.drop_constraint('fk_kiralama_kalemi_iade_nakliye_tedarikci_id', 'kiralama_kalemi', type_='foreignkey')
    op.drop_constraint('fk_kiralama_kalemi_iade_nakliye_arac_id', 'kiralama_kalemi', type_='foreignkey')
    op.drop_column('kiralama_kalemi', 'iade_aciklama')
    op.drop_column('kiralama_kalemi', 'iade_nakliye_kdv')
    op.drop_column('kiralama_kalemi', 'iade_nakliye_fiyat')
    op.drop_column('kiralama_kalemi', 'iade_nakliye_tedarikci_id')
    op.drop_column('kiralama_kalemi', 'iade_nakliye_arac_id')
    op.drop_column('kiralama_kalemi', 'iade_nakliye_oz_mal')
    op.drop_column('kiralama_kalemi', 'iade_nakliye_var')
    op.drop_column('kiralama_kalemi', 'iade_tarihi')
