"""Sefer yönü değişirken dağıtım yönü tekilliğini de koru."""

from alembic import op
import sqlalchemy as sa


revision = 'a6b7c8d9e0f1'
down_revision = 'a5b6c7d8e9f0'
branch_labels = None
depends_on = None


def upgrade():
    if op.get_bind().dialect.name != 'postgresql':
        return
    op.execute(sa.text("""
        CREATE OR REPLACE FUNCTION validate_nakliye_sefer_yon_change()
        RETURNS trigger AS $$
        BEGIN
            IF NEW.yon IS NOT NULL AND NEW.yon NOT IN ('gidis', 'donus') THEN
                RAISE EXCEPTION 'Geçersiz nakliye yönü: %', NEW.yon;
            END IF;
            IF NEW.yon IS NOT NULL AND EXISTS (
                SELECT 1
                FROM nakliye_dagitim d
                JOIN nakliye other ON other.id = d.nakliye_id
                WHERE d.is_deleted = false
                  AND other.is_deleted = false
                  AND other.yon = NEW.yon
                  AND other.id <> NEW.id
                  AND EXISTS (
                      SELECT 1 FROM nakliye_dagitim mine
                      WHERE mine.nakliye_id = NEW.id
                        AND mine.is_deleted = false
                        AND mine.kiralama_kalemi_id = d.kiralama_kalemi_id
                  )
            ) THEN
                RAISE EXCEPTION 'Kalem için aktif % seferi zaten var', NEW.yon;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """))
    op.execute(sa.text("""
        CREATE TRIGGER trg_validate_nakliye_sefer_yon_change
        BEFORE UPDATE OF yon ON nakliye
        FOR EACH ROW EXECUTE FUNCTION validate_nakliye_sefer_yon_change();
    """))


def downgrade():
    if op.get_bind().dialect.name != 'postgresql':
        return
    op.execute(sa.text(
        'DROP TRIGGER IF EXISTS trg_validate_nakliye_sefer_yon_change ON nakliye'
    ))
    op.execute(sa.text(
        'DROP FUNCTION IF EXISTS validate_nakliye_sefer_yon_change()'
    ))
