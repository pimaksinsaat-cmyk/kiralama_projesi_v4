"""Kiralama bağlı seferlerde yönün zorunlu olması."""

from alembic import op
import sqlalchemy as sa


revision = 'a7b8c9d0e1f2'
down_revision = 'a6b7c8d9e0f1'
branch_labels = None
depends_on = None


def upgrade():
    if op.get_bind().dialect.name != 'postgresql':
        return
    op.execute(sa.text("""
        CREATE OR REPLACE FUNCTION validate_nakliye_linked_yon()
        RETURNS trigger AS $$
        BEGIN
            IF NEW.yon IS NOT NULL AND NEW.yon NOT IN ('gidis', 'donus') THEN
                RAISE EXCEPTION 'Geçersiz nakliye yönü: %', NEW.yon;
            END IF;
            IF NEW.kiralama_id IS NOT NULL AND NEW.yon IS NULL THEN
                RAISE EXCEPTION 'Kiralama bağlı seferlerde yön zorunludur';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """))
    op.execute(sa.text("""
        CREATE TRIGGER trg_validate_nakliye_linked_yon
        BEFORE INSERT OR UPDATE OF kiralama_id, yon ON nakliye
        FOR EACH ROW EXECUTE FUNCTION validate_nakliye_linked_yon();
    """))


def downgrade():
    if op.get_bind().dialect.name != 'postgresql':
        return
    op.execute(sa.text('DROP TRIGGER IF EXISTS trg_validate_nakliye_linked_yon ON nakliye'))
    op.execute(sa.text('DROP FUNCTION IF EXISTS validate_nakliye_linked_yon()'))
