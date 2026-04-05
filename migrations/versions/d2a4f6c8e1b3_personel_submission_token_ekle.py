"""personel_submission_token_ekle

Revision ID: d2a4f6c8e1b3
Revises: b74120ad3067
Create Date: 2026-04-05 08:42:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = 'd2a4f6c8e1b3'
down_revision = 'b74120ad3067'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('personel', schema=None) as batch_op:
        batch_op.add_column(sa.Column('submission_token', sa.String(length=64), nullable=True))
        batch_op.create_unique_constraint('uq_personel_submission_token', ['submission_token'])


def downgrade():
    with op.batch_alter_table('personel', schema=None) as batch_op:
        batch_op.drop_constraint('uq_personel_submission_token', type_='unique')
        batch_op.drop_column('submission_token')