"""fix_donus_nakliye_duplicate

Revision ID: be8068e3ce1f
Revises: h6c2d3e4f5g6
Create Date: 2026-04-21 17:55:27.572855

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'be8068e3ce1f'
down_revision = 'h6c2d3e4f5g6'
branch_labels = None
depends_on = None


def upgrade():
    # SQLite'tan PostgreSQL'e geçişte "Donus:" (aksansız) formatında kalan
    # dönüş nakliye kayıtlarından çift kayıt oluşmuş olanları sil.
    # Karşılığında "Dönüş:" versiyonu olan kayıtlar silinir; tek başına
    # duran "Donus:" kayıtlara dokunulmaz (onlar tek geçerli kayıt).
    op.execute("""
        DELETE FROM nakliye
        WHERE aciklama LIKE 'Donus:%'
          AND EXISTS (
              SELECT 1 FROM nakliye n2
              WHERE n2.kiralama_id = nakliye.kiralama_id
                AND n2.aciklama = replace(nakliye.aciklama, 'Donus:', 'Dönüş:')
          )
    """)


def downgrade():
    pass
