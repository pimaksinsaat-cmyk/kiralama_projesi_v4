"""Nakliye güvenli geçiş izi ve geçmiş eksiklik alanları.

Revision ID: c2d3e4f5a6b7
Revises: b0c1d2e3f4a5
"""

from alembic import op
import sqlalchemy as sa


revision = 'c2d3e4f5a6b7'
down_revision = 'b0c1d2e3f4a5'
branch_labels = None
depends_on = None


def _base_columns():
    return [
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('created_by_id', sa.Integer(), nullable=True),
        sa.Column('updated_by_id', sa.Integer(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.Column('deleted_by_id', sa.Integer(), nullable=True),
    ]


def upgrade():
    op.add_column('nakliye', sa.Column('gecis_kaynagi', sa.String(40), nullable=True))
    op.add_column('nakliye', sa.Column('gecis_eksik_bilgiler', sa.Text(), nullable=True))
    op.create_index('ix_nakliye_gecis_kaynagi', 'nakliye', ['gecis_kaynagi'])

    op.create_table(
        'nakliye_gecis_islemi',
        sa.Column('run_uuid', sa.String(36), nullable=False),
        sa.Column('durum', sa.String(40), nullable=False, server_default='hazirlaniyor'),
        sa.Column('kaynak_snapshot_sha256', sa.String(64), nullable=False),
        sa.Column('once_firma_sayisi', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('once_hareket_sayisi', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('donusturulen_kiralama_sayisi', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('donusturulen_sefer_sayisi', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('hata', sa.Text(), nullable=True),
        sa.Column('rapor_json', sa.Text(), nullable=True),
        *_base_columns(),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('run_uuid', name='uq_nakliye_gecis_islemi_run_uuid'),
    )
    op.create_index('ix_nakliye_gecis_islemi_run_uuid', 'nakliye_gecis_islemi', ['run_uuid'])
    op.create_index('ix_nakliye_gecis_islemi_durum', 'nakliye_gecis_islemi', ['durum'])

    op.create_table(
        'nakliye_gecis_kaydi',
        sa.Column('islem_id', sa.Integer(), nullable=False),
        sa.Column('kiralama_id', sa.Integer(), nullable=False),
        sa.Column('nakliye_id', sa.Integer(), nullable=True),
        sa.Column('nakliye_dagitim_id', sa.Integer(), nullable=True),
        sa.Column('hizmet_kaydi_id', sa.Integer(), nullable=True),
        sa.Column('durum', sa.String(20), nullable=False, server_default='donusturuldu'),
        sa.Column('once_json', sa.Text(), nullable=True),
        sa.Column('sonra_json', sa.Text(), nullable=True),
        sa.Column('notlar', sa.Text(), nullable=True),
        *_base_columns(),
        sa.ForeignKeyConstraint(
            ['islem_id'], ['nakliye_gecis_islemi.id'], ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    for column in ('islem_id', 'kiralama_id', 'nakliye_id', 'nakliye_dagitim_id', 'hizmet_kaydi_id'):
        op.create_index(f'ix_nakliye_gecis_kaydi_{column}', 'nakliye_gecis_kaydi', [column])


def downgrade():
    op.drop_table('nakliye_gecis_kaydi')
    op.drop_table('nakliye_gecis_islemi')
    op.drop_index('ix_nakliye_gecis_kaynagi', table_name='nakliye')
    op.drop_column('nakliye', 'gecis_eksik_bilgiler')
    op.drop_column('nakliye', 'gecis_kaynagi')
