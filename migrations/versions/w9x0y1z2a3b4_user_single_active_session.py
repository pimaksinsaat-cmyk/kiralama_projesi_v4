"""user tek aktif oturum alanlari

Revision ID: w9x0y1z2a3b4
Revises: v7w8x9y0z1a2
Create Date: 2026-05-09 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'w9x0y1z2a3b4'
down_revision = 'v7w8x9y0z1a2'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('active_session_token', sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column('active_session_started_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('active_session_seen_at', sa.DateTime(), nullable=True))


def downgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_column('active_session_seen_at')
        batch_op.drop_column('active_session_started_at')
        batch_op.drop_column('active_session_token')
