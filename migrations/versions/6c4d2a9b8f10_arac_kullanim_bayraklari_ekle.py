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
    connection = op.get_bind()
    # Kolonlar zaten varsa atlıyoruz (IF NOT EXISTS)
    connection.execute(sa.text(
        "ALTER TABLE araclar ADD COLUMN IF NOT EXISTS is_nakliye_araci BOOLEAN NOT NULL DEFAULT false"
    ))
    connection.execute(sa.text(
        "ALTER TABLE araclar ADD COLUMN IF NOT EXISTS is_hizmet_araci BOOLEAN NOT NULL DEFAULT false"
    ))
    connection.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_araclar_is_nakliye_araci ON araclar (is_nakliye_araci)"
    ))
    connection.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_araclar_is_hizmet_araci ON araclar (is_hizmet_araci)"
    ))

    # Veri güncelleme: mevcut kayıtlara arac_tipi'ne göre bayrak ata (idempotent)
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


def downgrade():
    with op.batch_alter_table('araclar', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_araclar_is_hizmet_araci'))
        batch_op.drop_index(batch_op.f('ix_araclar_is_nakliye_araci'))
        batch_op.drop_column('is_hizmet_araci')
        batch_op.drop_column('is_nakliye_araci')