"""repair kiralama taseron nakliye sync

Revision ID: v7w8x9y0z1a2
Revises: u6v7w8x9y0z1
Create Date: 2026-05-07 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'v7w8x9y0z1a2'
down_revision = 'u6v7w8x9y0z1'
branch_labels = None
depends_on = None


BACKUP_TABLE = '_backup_nakliye_taseron_sync'


def upgrade():
    op.execute(f"""
        CREATE TABLE IF NOT EXISTS {BACKUP_TABLE} AS
        SELECT
            n.id AS nakliye_id,
            n.nakliye_tipi AS old_nakliye_tipi,
            n.taseron_firma_id AS old_taseron_firma_id,
            n.taseron_maliyet AS old_taseron_maliyet,
            n.taseron_kdv_orani AS old_taseron_kdv_orani,
            n.plaka AS old_plaka,
            n.arac_id AS old_arac_id,
            n.aciklama AS old_aciklama,
            CURRENT_TIMESTAMP AS backed_up_at
        FROM nakliye n
        WHERE 1 = 0
    """)

    op.execute(f"""
        WITH hedef AS (
            SELECT DISTINCT n.id
            FROM nakliye n
            JOIN kiralama k ON k.id = n.kiralama_id
            JOIN kiralama_kalemi kk ON kk.kiralama_id = k.id
            LEFT JOIN ekipman e ON e.id = kk.ekipman_id
            WHERE kk.is_harici_nakliye IS TRUE
              AND kk.nakliye_tedarikci_id IS NOT NULL
              AND COALESCE(kk.nakliye_alis_fiyat, 0) > 0
              AND (
                    n.aciklama = ('Gidiş: ' || k.kiralama_form_no || ' #' || kk.id)
                    OR (
                        n.aciklama = ('Gidiş: ' || k.kiralama_form_no)
                        AND e.kod IS NOT NULL
                        AND n.guzergah ILIKE ('%' || e.kod || '%')
                    )
                    OR n.aciklama = ('Dönüş: ' || k.kiralama_form_no || ' #' || kk.id)
              )
              AND (
                    n.taseron_firma_id IS NULL
                    OR COALESCE(n.taseron_maliyet, 0) = 0
                    OR n.nakliye_tipi IS DISTINCT FROM 'taseron'
              )
        )
        INSERT INTO {BACKUP_TABLE} (
            nakliye_id,
            old_nakliye_tipi,
            old_taseron_firma_id,
            old_taseron_maliyet,
            old_taseron_kdv_orani,
            old_plaka,
            old_arac_id,
            old_aciklama,
            backed_up_at
        )
        SELECT
            n.id,
            n.nakliye_tipi,
            n.taseron_firma_id,
            n.taseron_maliyet,
            n.taseron_kdv_orani,
            n.plaka,
            n.arac_id,
            n.aciklama,
            CURRENT_TIMESTAMP
        FROM nakliye n
        JOIN hedef h ON h.id = n.id
        WHERE NOT EXISTS (
            SELECT 1
            FROM {BACKUP_TABLE} b
            WHERE b.nakliye_id = n.id
        )
    """)

    op.execute("""
        WITH eslesen AS (
            SELECT DISTINCT ON (n.id)
                n.id AS nakliye_id,
                kk.id AS kalem_id,
                k.kiralama_form_no AS form_no,
                kk.nakliye_tedarikci_id,
                kk.nakliye_alis_fiyat,
                kk.nakliye_alis_kdv,
                CASE
                    WHEN n.aciklama LIKE 'Gidiş:%' THEN ('Gidiş: ' || k.kiralama_form_no || ' #' || kk.id)
                    ELSE n.aciklama
                END AS yeni_aciklama
            FROM nakliye n
            JOIN kiralama k ON k.id = n.kiralama_id
            JOIN kiralama_kalemi kk ON kk.kiralama_id = k.id
            LEFT JOIN ekipman e ON e.id = kk.ekipman_id
            WHERE kk.is_harici_nakliye IS TRUE
              AND kk.nakliye_tedarikci_id IS NOT NULL
              AND COALESCE(kk.nakliye_alis_fiyat, 0) > 0
              AND (
                    n.aciklama = ('Gidiş: ' || k.kiralama_form_no || ' #' || kk.id)
                    OR (
                        n.aciklama = ('Gidiş: ' || k.kiralama_form_no)
                        AND e.kod IS NOT NULL
                        AND n.guzergah ILIKE ('%' || e.kod || '%')
                    )
                    OR n.aciklama = ('Dönüş: ' || k.kiralama_form_no || ' #' || kk.id)
              )
            ORDER BY n.id, kk.id
        )
        UPDATE nakliye n
        SET nakliye_tipi = 'taseron',
            taseron_firma_id = e.nakliye_tedarikci_id,
            taseron_maliyet = e.nakliye_alis_fiyat,
            taseron_kdv_orani = e.nakliye_alis_kdv,
            plaka = 'Dış Nakliye',
            arac_id = NULL,
            aciklama = e.yeni_aciklama
        FROM eslesen e
        WHERE n.id = e.nakliye_id
          AND (
                n.taseron_firma_id IS NULL
                OR COALESCE(n.taseron_maliyet, 0) = 0
                OR n.nakliye_tipi IS DISTINCT FROM 'taseron'
          )
    """)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if BACKUP_TABLE not in set(inspector.get_table_names()):
        return

    op.execute(f"""
        UPDATE nakliye n
        SET nakliye_tipi = b.old_nakliye_tipi,
            taseron_firma_id = b.old_taseron_firma_id,
            taseron_maliyet = b.old_taseron_maliyet,
            taseron_kdv_orani = b.old_taseron_kdv_orani,
            plaka = b.old_plaka,
            arac_id = b.old_arac_id,
            aciklama = b.old_aciklama
        FROM {BACKUP_TABLE} b
        WHERE n.id = b.nakliye_id
    """)
