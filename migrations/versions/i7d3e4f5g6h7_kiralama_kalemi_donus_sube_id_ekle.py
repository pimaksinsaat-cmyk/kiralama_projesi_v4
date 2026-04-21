"""kiralama_kalemi_donus_sube_id_ekle

Revision ID: i7d3e4f5g6h7
Revises: be8068e3ce1f
Create Date: 2026-04-21 18:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'i7d3e4f5g6h7'
down_revision = 'be8068e3ce1f'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('kiralama_kalemi',
        sa.Column('donus_sube_id', sa.Integer(), nullable=True)
    )
    op.create_foreign_key(
        'fk_kiralama_kalemi_donus_sube_id',
        'kiralama_kalemi', 'subeler',
        ['donus_sube_id'], ['id'],
        ondelete='SET NULL'
    )


def downgrade():
    op.drop_constraint('fk_kiralama_kalemi_donus_sube_id', 'kiralama_kalemi', type_='foreignkey')
    op.drop_column('kiralama_kalemi', 'donus_sube_id')
