"""Add validation constraints for firma_adi, kiralama_brm_fiyat, mevcut_stok

Revision ID: cda9100a2a7a
Revises: f9g0h1i2j3k4
Create Date: 2026-04-14

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'cda9100a2a7a'
down_revision = 'f9g0h1i2j3k4'
branch_labels = None
depends_on = None


def _constraint_exists(table_name, constraint_name):
    """Helper function to check if a constraint already exists"""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    constraints = inspector.get_check_constraints(table_name)
    return any(c['name'] == constraint_name for c in constraints)


def upgrade():
    """Add CHECK constraints for validation"""
    bind = op.get_bind()

    # --- FIRMA TABLE: firma_adi length validation ---
    try:
        if bind.dialect.name == 'postgresql':
            if not _constraint_exists('firma', 'check_firma_adi_length'):
                op.execute('''
                    ALTER TABLE firma
                    ADD CONSTRAINT check_firma_adi_length
                    CHECK (LENGTH(firma_adi) > 0 AND LENGTH(firma_adi) <= 150)
                ''')
        elif bind.dialect.name == 'sqlite':
            if not _constraint_exists('firma', 'check_firma_adi_length'):
                op.execute('''
                    ALTER TABLE firma
                    ADD CONSTRAINT check_firma_adi_length
                    CHECK (LENGTH(firma_adi) > 0 AND LENGTH(firma_adi) <= 150)
                ''')
    except Exception as e:
        print(f"Warning: Could not add firma_adi constraint: {e}")

    # --- KIRALAMA_KALEMI TABLE: kiralama_brm_fiyat non-negative ---
    try:
        if not _constraint_exists('kiralama_kalemi', 'check_kiralama_brm_fiyat_non_negative'):
            op.execute('''
                ALTER TABLE kiralama_kalemi
                ADD CONSTRAINT check_kiralama_brm_fiyat_non_negative
                CHECK (kiralama_brm_fiyat >= 0)
            ''')
    except Exception as e:
        print(f"Warning: Could not add kiralama_brm_fiyat constraint: {e}")

    # --- STOK_KARTI TABLE: mevcut_stok non-negative ---
    try:
        if not _constraint_exists('stok_karti', 'check_mevcut_stok_non_negative'):
            op.execute('''
                ALTER TABLE stok_karti
                ADD CONSTRAINT check_mevcut_stok_non_negative
                CHECK (mevcut_stok >= 0)
            ''')
    except Exception as e:
        print(f"Warning: Could not add mevcut_stok constraint: {e}")


def downgrade():
    """Remove CHECK constraints"""
    bind = op.get_bind()

    # --- Remove constraints in reverse order ---
    try:
        if bind.dialect.name == 'postgresql':
            op.execute('ALTER TABLE stok_karti DROP CONSTRAINT IF EXISTS check_mevcut_stok_non_negative')
            op.execute('ALTER TABLE kiralama_kalemi DROP CONSTRAINT IF EXISTS check_kiralama_brm_fiyat_non_negative')
            op.execute('ALTER TABLE firma DROP CONSTRAINT IF EXISTS check_firma_adi_length')
        elif bind.dialect.name == 'sqlite':
            # SQLite doesn't support DROP CONSTRAINT, so we'd need to recreate the table
            # For now, we'll just log a warning
            print("Warning: SQLite does not support dropping constraints. Manual intervention required.")
    except Exception as e:
        print(f"Warning: Could not remove constraints: {e}")
