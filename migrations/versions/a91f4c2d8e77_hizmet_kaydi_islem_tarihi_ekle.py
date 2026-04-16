"""hizmet_kaydi_islem_tarihi_ekle

Revision ID: a91f4c2d8e77
Revises: 7b3e5a2f9c18
Create Date: 2026-04-15 10:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a91f4c2d8e77'
down_revision = 'cda9100a2a7a'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('hizmet_kaydi', schema=None) as batch_op:
        batch_op.add_column(sa.Column('islem_tarihi', sa.Date(), nullable=True))
        batch_op.create_index(
            batch_op.f('ix_hizmet_kaydi_islem_tarihi'),
            ['islem_tarihi'],
            unique=False
        )


def downgrade():
    with op.batch_alter_table('hizmet_kaydi', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_hizmet_kaydi_islem_tarihi'))
        batch_op.drop_column('islem_tarihi')
