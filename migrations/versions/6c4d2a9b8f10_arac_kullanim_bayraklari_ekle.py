"""arac_kullanim_bayraklari_ekle

Revision ID: 6c4d2a9b8f10
Revises: db93d0cf03a2
Create Date: 2026-04-05 15:20:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '6c4d2a9b8f10'
down_revision = 'db93d0cf03a2'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('araclar', schema=None) as batch_op:
        batch_op.add_column(sa.Column('is_nakliye_araci', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column('is_hizmet_araci', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.create_index(batch_op.f('ix_araclar_is_nakliye_araci'), ['is_nakliye_araci'], unique=False)
        batch_op.create_index(batch_op.f('ix_araclar_is_hizmet_araci'), ['is_hizmet_araci'], unique=False)

    connection = op.get_bind()
    connection.execute(sa.text("""
        UPDATE araclar
        SET
            is_nakliye_araci = CASE
                WHEN lower(coalesce(arac_tipi, '')) LIKE '%kayar kasa%'
                  OR lower(coalesce(arac_tipi, '')) LIKE '%çekici%'
                  OR lower(coalesce(arac_tipi, '')) LIKE '%cekici%'
                  OR lower(coalesce(arac_tipi, '')) LIKE '%kamyon%'
                  OR lower(coalesce(arac_tipi, '')) LIKE '%tır%'
                  OR lower(coalesce(arac_tipi, '')) LIKE '%tir%'
                  OR lower(coalesce(arac_tipi, '')) LIKE '%lowbed%'
                  OR lower(coalesce(arac_tipi, '')) LIKE '%dorse%'
                THEN TRUE
                WHEN lower(coalesce(arac_tipi, '')) LIKE '%binek%'
                  OR lower(coalesce(arac_tipi, '')) LIKE '%otomobil%'
                  OR lower(coalesce(arac_tipi, '')) LIKE '%panelvan%'
                  OR lower(coalesce(arac_tipi, '')) LIKE '%minibüs%'
                  OR lower(coalesce(arac_tipi, '')) LIKE '%minibus%'
                THEN FALSE
                ELSE TRUE
            END,
            is_hizmet_araci = CASE
                WHEN lower(coalesce(arac_tipi, '')) LIKE '%binek%'
                  OR lower(coalesce(arac_tipi, '')) LIKE '%otomobil%'
                  OR lower(coalesce(arac_tipi, '')) LIKE '%panelvan%'
                  OR lower(coalesce(arac_tipi, '')) LIKE '%minibüs%'
                  OR lower(coalesce(arac_tipi, '')) LIKE '%minibus%'
                THEN TRUE
                ELSE FALSE
            END
    """))

    with op.batch_alter_table('araclar', schema=None) as batch_op:
        batch_op.alter_column('is_nakliye_araci', server_default=None)
        batch_op.alter_column('is_hizmet_araci', server_default=None)


def downgrade():
    with op.batch_alter_table('araclar', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_araclar_is_hizmet_araci'))
        batch_op.drop_index(batch_op.f('ix_araclar_is_nakliye_araci'))
        batch_op.drop_column('is_hizmet_araci')
        batch_op.drop_column('is_nakliye_araci')