"""nakliye cift_yon bayragi

Revision ID: a8c0d1e2f3a4
Revises: a7b8c9d0e1f2
"""

from alembic import op
import sqlalchemy as sa


revision = 'a8c0d1e2f3a4'
down_revision = 'a7b8c9d0e1f2'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'nakliye',
        sa.Column('cift_yon', sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade():
    op.drop_column('nakliye', 'cift_yon')
