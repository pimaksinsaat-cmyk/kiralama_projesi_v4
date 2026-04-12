"""hakedis_kalemi.kiralama_kalemi_id icin katı FK (RESTRICT)

Revision ID: c3a8e1f0b9d2
Revises: 7b3e5a2f9c18
Create Date: 2026-04-11

"""
from alembic import op

revision = 'c3a8e1f0b9d2'
down_revision = '7b3e5a2f9c18'
branch_labels = None
depends_on = None


def upgrade():
    op.create_foreign_key(
        'fk_hakedis_kalemi_kiralama_kalemi_id_kiralama_kalemi',
        'hakedis_kalemi',
        'kiralama_kalemi',
        ['kiralama_kalemi_id'],
        ['id'],
        ondelete='RESTRICT',
    )


def downgrade():
    op.drop_constraint(
        'fk_hakedis_kalemi_kiralama_kalemi_id_kiralama_kalemi',
        'hakedis_kalemi',
        type_='foreignkey',
    )
