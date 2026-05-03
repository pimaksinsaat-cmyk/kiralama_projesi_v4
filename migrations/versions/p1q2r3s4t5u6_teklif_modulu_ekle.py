"""teklif_modulu_ekle

Revision ID: p1q2r3s4t5u6
Revises: b2c4d6e8f1a3
Create Date: 2026-05-03 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'p1q2r3s4t5u6'
down_revision = 'b2c4d6e8f1a3'
branch_labels = None
depends_on = None


def _base_columns():
    return [
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('created_by_id', sa.Integer(), nullable=True),
        sa.Column('updated_by_id', sa.Integer(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.Column('deleted_by_id', sa.Integer(), nullable=True),
    ]


def upgrade():
    op.create_table(
        'teklif',
        *_base_columns(),
        sa.Column('teklif_no', sa.String(length=100), nullable=False),
        sa.Column('teklif_tarihi', sa.Date(), nullable=False),
        sa.Column('gecerlilik_tarihi', sa.Date(), nullable=True),
        sa.Column('durum', sa.String(length=30), nullable=False),
        sa.Column('kdv_orani', sa.Integer(), nullable=False),
        sa.Column('notlar', sa.Text(), nullable=True),
        sa.Column('firma_musteri_id', sa.Integer(), nullable=True),
        sa.Column('kiralama_id', sa.Integer(), nullable=True),
        sa.Column('aday_firma_adi', sa.String(length=150), nullable=True),
        sa.Column('aday_yetkili_adi', sa.String(length=100), nullable=True),
        sa.Column('aday_telefon', sa.String(length=20), nullable=True),
        sa.Column('aday_eposta', sa.String(length=120), nullable=True),
        sa.Column('aday_adres', sa.Text(), nullable=True),
        sa.Column('aday_not', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['firma_musteri_id'], ['firma.id']),
        sa.ForeignKeyConstraint(['kiralama_id'], ['kiralama.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('teklif_no'),
    )
    op.create_index(op.f('ix_teklif_aday_firma_adi'), 'teklif', ['aday_firma_adi'], unique=False)
    op.create_index(op.f('ix_teklif_durum'), 'teklif', ['durum'], unique=False)
    op.create_index(op.f('ix_teklif_firma_musteri_id'), 'teklif', ['firma_musteri_id'], unique=False)
    op.create_index(op.f('ix_teklif_is_active'), 'teklif', ['is_active'], unique=False)
    op.create_index(op.f('ix_teklif_is_deleted'), 'teklif', ['is_deleted'], unique=False)
    op.create_index(op.f('ix_teklif_kiralama_id'), 'teklif', ['kiralama_id'], unique=False)
    op.create_index(op.f('ix_teklif_teklif_no'), 'teklif', ['teklif_no'], unique=False)

    op.create_table(
        'teklif_kalemi',
        *_base_columns(),
        sa.Column('teklif_id', sa.Integer(), nullable=False),
        sa.Column('ekipman_id', sa.Integer(), nullable=True),
        sa.Column('makine_tipi', sa.String(length=100), nullable=True),
        sa.Column('marka_model', sa.String(length=150), nullable=True),
        sa.Column('calisma_yuksekligi', sa.Numeric(10, 2), nullable=True),
        sa.Column('kaldirma_kapasitesi', sa.Integer(), nullable=True),
        sa.Column('adet', sa.Integer(), nullable=False),
        sa.Column('calisacagi_konum', sa.Text(), nullable=True),
        sa.Column('baslangic_tarihi', sa.Date(), nullable=True),
        sa.Column('bitis_tarihi', sa.Date(), nullable=True),
        sa.Column('gunluk_fiyat', sa.Numeric(15, 2), nullable=False),
        sa.Column('nakliye_fiyati', sa.Numeric(15, 2), nullable=False),
        sa.Column('satir_notu', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['ekipman_id'], ['ekipman.id']),
        sa.ForeignKeyConstraint(['teklif_id'], ['teklif.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_teklif_kalemi_ekipman_id'), 'teklif_kalemi', ['ekipman_id'], unique=False)
    op.create_index(op.f('ix_teklif_kalemi_is_active'), 'teklif_kalemi', ['is_active'], unique=False)
    op.create_index(op.f('ix_teklif_kalemi_is_deleted'), 'teklif_kalemi', ['is_deleted'], unique=False)
    op.create_index(op.f('ix_teklif_kalemi_teklif_id'), 'teklif_kalemi', ['teklif_id'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_teklif_kalemi_teklif_id'), table_name='teklif_kalemi')
    op.drop_index(op.f('ix_teklif_kalemi_is_deleted'), table_name='teklif_kalemi')
    op.drop_index(op.f('ix_teklif_kalemi_is_active'), table_name='teklif_kalemi')
    op.drop_index(op.f('ix_teklif_kalemi_ekipman_id'), table_name='teklif_kalemi')
    op.drop_table('teklif_kalemi')
    op.drop_index(op.f('ix_teklif_teklif_no'), table_name='teklif')
    op.drop_index(op.f('ix_teklif_kiralama_id'), table_name='teklif')
    op.drop_index(op.f('ix_teklif_is_deleted'), table_name='teklif')
    op.drop_index(op.f('ix_teklif_is_active'), table_name='teklif')
    op.drop_index(op.f('ix_teklif_firma_musteri_id'), table_name='teklif')
    op.drop_index(op.f('ix_teklif_durum'), table_name='teklif')
    op.drop_index(op.f('ix_teklif_aday_firma_adi'), table_name='teklif')
    op.drop_table('teklif')
