"""Kiralama kalemi nakliye araci ve etkin plaka senkronizasyonu.

Eski FK ekipman.id'ye bakiyordu; uygulama ise bu alani araclar.id olarak
kullaniyordu. Migration, degisiklikten once veri tutarliligini kontrol eder ve
yalnizca bos alanlari doldurur.
"""

from alembic import op
import sqlalchemy as sa


revision = 'b0c1d2e3f4a5'
down_revision = 'a9d0e1f2a3b4'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(sa.text("""
        DO $$
        DECLARE
            invalid_count integer;
            invalid_ids text;
            duplicate_ids text;
        BEGIN
            SELECT COUNT(*)
              INTO invalid_count
              FROM kiralama_kalemi kk
              LEFT JOIN araclar a ON a.id = kk.nakliye_araci_id
             WHERE kk.nakliye_araci_id IS NOT NULL
               AND a.id IS NULL;

            IF invalid_count > 0 THEN
                SELECT COALESCE(string_agg(id::text, ',' ORDER BY id), '')
                  INTO invalid_ids
                  FROM (
                      SELECT kk.id
                        FROM kiralama_kalemi kk
                        LEFT JOIN araclar a ON a.id = kk.nakliye_araci_id
                       WHERE kk.nakliye_araci_id IS NOT NULL
                         AND a.id IS NULL
                       ORDER BY kk.id
                       LIMIT 20
                  ) invalid_rows;
                RAISE EXCEPTION
                    'nakliye_araci_id icin % gecersiz arac ID bulundu (ilk kalemler: %). Migration durduruldu.',
                    invalid_count, invalid_ids;
            END IF;

            SELECT COALESCE(string_agg(kiralama_kalemi_id::text, ',' ORDER BY kiralama_kalemi_id), '')
              INTO duplicate_ids
              FROM (
                  SELECT d.kiralama_kalemi_id
                    FROM nakliye_dagitim d
                    JOIN nakliye n ON n.id = d.nakliye_id
                    JOIN kiralama k ON k.id = n.kiralama_id
                   WHERE k.nakliye_modeli = 'sefer'
                     AND n.yon = 'gidis'
                     AND n.arac_id IS NOT NULL
                     AND d.is_deleted IS FALSE
                     AND d.is_active IS TRUE
                     AND n.is_deleted IS FALSE
                     AND n.is_active IS TRUE
                   GROUP BY d.kiralama_kalemi_id
                  HAVING COUNT(DISTINCT n.arac_id) > 1
                   ORDER BY d.kiralama_kalemi_id
                   LIMIT 20
              ) duplicate_rows;

            IF duplicate_ids <> '' THEN
                RAISE EXCEPTION
                    'Ayni kaleme bagli birden fazla aktif gidis araci bulundu (ilk kalemler: %). Migration durduruldu.',
                    duplicate_ids;
            END IF;
        END $$;
    """))

    op.drop_constraint(
        'fk_kiralama_kalemi_nakliye_araci_id_ekipman',
        'kiralama_kalemi',
        type_='foreignkey',
    )
    op.create_foreign_key(
        'fk_kiralama_kalemi_nakliye_araci_id_araclar',
        'kiralama_kalemi',
        'araclar',
        ['nakliye_araci_id'],
        ['id'],
    )

    # Dolu manuel plakalar korunur; yalnizca arac_id ile bulunabilen boslar
    # araclar tablosundaki guncel plakayla tamamlanir.
    op.execute(sa.text("""
        UPDATE nakliye n
           SET plaka = NULLIF(BTRIM(a.plaka), '')
          FROM araclar a
         WHERE n.arac_id = a.id
           AND NULLIF(BTRIM(n.plaka), '') IS NULL
           AND NULLIF(BTRIM(a.plaka), '') IS NOT NULL
    """))

    # Kalem aynasi sadece sefer modelinin aktif gidiş aracindan beslenir.
    # Preflight tekilligi garanti ettigi icin rn=1 rastgele bir secim degildir.
    op.execute(sa.text("""
        WITH aktif_gidis AS (
            SELECT
                d.kiralama_kalemi_id,
                n.arac_id,
                ROW_NUMBER() OVER (
                    PARTITION BY d.kiralama_kalemi_id
                    ORDER BY n.id
                ) AS rn
              FROM nakliye_dagitim d
              JOIN nakliye n ON n.id = d.nakliye_id
              JOIN kiralama k ON k.id = n.kiralama_id
             WHERE k.nakliye_modeli = 'sefer'
               AND n.yon = 'gidis'
               AND n.arac_id IS NOT NULL
               AND d.is_deleted IS FALSE
               AND d.is_active IS TRUE
               AND n.is_deleted IS FALSE
               AND n.is_active IS TRUE
        )
        UPDATE kiralama_kalemi kk
           SET nakliye_araci_id = ag.arac_id
          FROM aktif_gidis ag
         WHERE ag.rn = 1
           AND kk.id = ag.kiralama_kalemi_id
           AND kk.nakliye_araci_id IS NULL
    """))


def downgrade():
    op.drop_constraint(
        'fk_kiralama_kalemi_nakliye_araci_id_araclar',
        'kiralama_kalemi',
        type_='foreignkey',
    )
    op.create_foreign_key(
        'fk_kiralama_kalemi_nakliye_araci_id_ekipman',
        'kiralama_kalemi',
        'ekipman',
        ['nakliye_araci_id'],
        ['id'],
    )
