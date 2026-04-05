"""sube_giderlerine_arac_bagli_mazot_alanlari_ekle

Revision ID: 1e7b3d4c9a20
Revises: 6c4d2a9b8f10
Create Date: 2026-04-05 16:05:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '1e7b3d4c9a20'
down_revision = '6c4d2a9b8f10'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    conn.execute(sa.text('ALTER TABLE sube_giderleri ADD COLUMN IF NOT EXISTS arac_id INTEGER'))
    conn.execute(sa.text('ALTER TABLE sube_giderleri ADD COLUMN IF NOT EXISTS litre NUMERIC(10,2)'))
    conn.execute(sa.text('ALTER TABLE sube_giderleri ADD COLUMN IF NOT EXISTS birim_fiyat NUMERIC(10,2)'))
    conn.execute(sa.text('ALTER TABLE sube_giderleri ADD COLUMN IF NOT EXISTS km INTEGER'))
    conn.execute(sa.text('ALTER TABLE sube_giderleri ADD COLUMN IF NOT EXISTS istasyon VARCHAR(150)'))
    conn.execute(sa.text('CREATE INDEX IF NOT EXISTS ix_sube_giderleri_arac_id ON sube_giderleri (arac_id)'))
    # FK sadece yoksa ekle
    exists = conn.execute(sa.text("""
        SELECT 1 FROM information_schema.table_constraints
        WHERE constraint_name='fk_sube_giderleri_arac_id_araclar'
          AND table_name='sube_giderleri'
    """)).fetchone()
    if not exists:
        conn.execute(sa.text('ALTER TABLE sube_giderleri ADD CONSTRAINT fk_sube_giderleri_arac_id_araclar FOREIGN KEY (arac_id) REFERENCES araclar(id)'))


def downgrade():
    with op.batch_alter_table('sube_giderleri', schema=None) as batch_op:
        batch_op.drop_constraint('fk_sube_giderleri_arac_id_araclar', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_sube_giderleri_arac_id'))
        batch_op.drop_column('istasyon')
        batch_op.drop_column('km')
        batch_op.drop_column('birim_fiyat')
        batch_op.drop_column('litre')
        batch_op.drop_column('arac_id')