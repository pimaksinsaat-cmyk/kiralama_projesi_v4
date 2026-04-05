"""Personel ve izin tablolarını ekle

Revision ID: 9c1e4f7a2b63
Revises: b5e2c1a7d4f8
Create Date: 2026-04-05 08:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = '9c1e4f7a2b63'
down_revision = 'b5e2c1a7d4f8'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'personel',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('created_by_id', sa.Integer(), nullable=True),
        sa.Column('updated_by_id', sa.Integer(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default='0'),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.Column('deleted_by_id', sa.Integer(), nullable=True),
        sa.Column('sube_id', sa.Integer(), nullable=False),
        sa.Column('ad', sa.String(length=50), nullable=False),
        sa.Column('soyad', sa.String(length=50), nullable=False),
        sa.Column('tc_no', sa.String(length=11), nullable=True),
        sa.Column('telefon', sa.String(length=20), nullable=True),
        sa.Column('meslek', sa.String(length=100), nullable=True),
        sa.Column('maas', sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column('ise_giris_tarihi', sa.Date(), nullable=True),
        sa.Column('isten_cikis_tarihi', sa.Date(), nullable=True),
        sa.ForeignKeyConstraint(['sube_id'], ['subeler.id'], name=op.f('fk_personel_sube_id_subeler')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_personel')),
        sa.UniqueConstraint('tc_no', name=op.f('uq_personel_tc_no')),
    )
    with op.batch_alter_table('personel', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_personel_sube_id'), ['sube_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_personel_is_deleted'), ['is_deleted'], unique=False)

    op.create_table(
        'personel_izin',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('personel_id', sa.Integer(), nullable=False),
        sa.Column('izin_turu', sa.String(length=30), nullable=False),
        sa.Column('baslangic_tarihi', sa.Date(), nullable=False),
        sa.Column('bitis_tarihi', sa.Date(), nullable=False),
        sa.Column('gun_sayisi', sa.Integer(), nullable=False),
        sa.Column('aciklama', sa.String(length=250), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['personel_id'], ['personel.id'], name=op.f('fk_personel_izin_personel_id_personel')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_personel_izin')),
    )
    with op.batch_alter_table('personel_izin', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_personel_izin_personel_id'), ['personel_id'], unique=False)


def downgrade():
    with op.batch_alter_table('personel_izin', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_personel_izin_personel_id'))

    op.drop_table('personel_izin')

    with op.batch_alter_table('personel', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_personel_is_deleted'))
        batch_op.drop_index(batch_op.f('ix_personel_sube_id'))

    op.drop_table('personel')
