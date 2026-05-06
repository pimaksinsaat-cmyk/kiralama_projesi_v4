"""normalize nakliye taseron hizmet kaydi

Revision ID: u6v7w8x9y0z1
Revises: t5u6v7w8x9y0
Create Date: 2026-05-06 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'u6v7w8x9y0z1'
down_revision = 't5u6v7w8x9y0'
branch_labels = None
depends_on = None


BACKUP_TABLE = '_backup_hizmetkaydi_ozel_id'


def upgrade():
    op.execute(f"""
        CREATE TABLE IF NOT EXISTS {BACKUP_TABLE} AS
        SELECT
            h.id AS hizmet_kaydi_id,
            h.ozel_id AS old_ozel_id,
            h.nakliye_id AS old_nakliye_id,
            h.aciklama AS aciklama,
            CURRENT_TIMESTAMP AS backed_up_at
        FROM hizmet_kaydi h
        WHERE 1 = 0
    """)

    op.execute(f"""
        INSERT INTO {BACKUP_TABLE} (
            hizmet_kaydi_id,
            old_ozel_id,
            old_nakliye_id,
            aciklama,
            backed_up_at
        )
        SELECT
            h.id,
            h.ozel_id,
            h.nakliye_id,
            h.aciklama,
            CURRENT_TIMESTAMP
        FROM hizmet_kaydi h
        WHERE h.yon = 'gelen'
          AND h.nakliye_id IS NULL
          AND h.ozel_id IS NOT NULL
          AND h.aciklama LIKE 'Nakliye Taşeron Gideri:%'
          AND EXISTS (
              SELECT 1
              FROM nakliye n
              WHERE n.id = h.ozel_id
          )
          AND NOT EXISTS (
              SELECT 1
              FROM {BACKUP_TABLE} b
              WHERE b.hizmet_kaydi_id = h.id
          )
    """)

    op.execute("""
        UPDATE hizmet_kaydi
        SET nakliye_id = ozel_id,
            ozel_id = NULL
        WHERE yon = 'gelen'
          AND nakliye_id IS NULL
          AND ozel_id IS NOT NULL
          AND aciklama LIKE 'Nakliye Taşeron Gideri:%'
          AND EXISTS (
              SELECT 1
              FROM nakliye n
              WHERE n.id = hizmet_kaydi.ozel_id
          )
    """)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())
    if BACKUP_TABLE not in table_names:
        return

    op.execute(f"""
        UPDATE hizmet_kaydi
        SET ozel_id = (
                SELECT b.old_ozel_id
                FROM {BACKUP_TABLE} b
                WHERE b.hizmet_kaydi_id = hizmet_kaydi.id
            ),
            nakliye_id = NULL
        WHERE id IN (
            SELECT hizmet_kaydi_id
            FROM {BACKUP_TABLE}
        )
    """)
