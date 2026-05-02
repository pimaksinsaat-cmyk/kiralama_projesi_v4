"""Servis yapilan islem tablosu ekle

Revision ID: b2c4d6e8f1a3
Revises: n2i8j9k0l1m2
Create Date: 2026-05-02 22:10:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = 'b2c4d6e8f1a3'
down_revision = 'n2i8j9k0l1m2'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'yapilan_islem',
        sa.Column('bakim_kaydi_id', sa.Integer(), nullable=False),
        sa.Column('islem_aciklama', sa.String(length=500), nullable=False),
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('created_by_id', sa.Integer(), nullable=True),
        sa.Column('updated_by_id', sa.Integer(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.Column('deleted_by_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['bakim_kaydi_id'], ['bakim_kaydi.id'], name=op.f('fk_yapilan_islem_bakim_kaydi_id_bakim_kaydi')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_yapilan_islem')),
    )
    with op.batch_alter_table('yapilan_islem', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_yapilan_islem_bakim_kaydi_id'), ['bakim_kaydi_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_yapilan_islem_is_active'), ['is_active'], unique=False)
        batch_op.create_index(batch_op.f('ix_yapilan_islem_is_deleted'), ['is_deleted'], unique=False)


def downgrade():
    with op.batch_alter_table('yapilan_islem', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_yapilan_islem_is_deleted'))
        batch_op.drop_index(batch_op.f('ix_yapilan_islem_is_active'))
        batch_op.drop_index(batch_op.f('ix_yapilan_islem_bakim_kaydi_id'))

    op.drop_table('yapilan_islem')
