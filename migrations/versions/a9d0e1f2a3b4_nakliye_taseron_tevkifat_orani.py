"""nakliye taseron_tevkifat_orani

Revision ID: a9d0e1f2a3b4
Revises: a8c0d1e2f3a4
"""

from alembic import op
import sqlalchemy as sa


revision = 'a9d0e1f2a3b4'
down_revision = 'a8c0d1e2f3a4'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'nakliye',
        sa.Column('taseron_tevkifat_orani', sa.String(length=10), nullable=True),
    )


def downgrade():
    op.drop_column('nakliye', 'taseron_tevkifat_orani')
