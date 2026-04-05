"""Sube giderleri tablosunu ekle

Revision ID: b5e2c1a7d4f8
Revises: 2d6f5b8a1c73
Create Date: 2026-04-05 07:35:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = 'b5e2c1a7d4f8'
down_revision = '2d6f5b8a1c73'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'sube_giderleri',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('sube_id', sa.Integer(), nullable=False),
        sa.Column('tarih', sa.Date(), nullable=False),
        sa.Column('kategori', sa.String(length=50), nullable=False),
        sa.Column('tutar', sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column('aciklama', sa.String(length=250), nullable=True),
        sa.Column('fatura_no', sa.String(length=50), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['sube_id'], ['subeler.id'], name=op.f('fk_sube_giderleri_sube_id_subeler')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_sube_giderleri')),
    )
    with op.batch_alter_table('sube_giderleri', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_sube_giderleri_sube_id'), ['sube_id'], unique=False)


def downgrade():
    with op.batch_alter_table('sube_giderleri', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_sube_giderleri_sube_id'))

    op.drop_table('sube_giderleri')