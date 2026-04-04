"""Swap finans referanslari ekle

Revision ID: 3f1f2d7c9a01
Revises: bf17d13659c3
Create Date: 2026-04-04 16:20:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '3f1f2d7c9a01'
down_revision = 'bf17d13659c3'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('makine_degisim', schema=None) as batch_op:
        batch_op.add_column(sa.Column('swap_nakliye_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('swap_taseron_hizmet_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('swap_kira_hizmet_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            'fk_makine_degisim_swap_nakliye_id_nakliye',
            'nakliye',
            ['swap_nakliye_id'],
            ['id'],
            ondelete='SET NULL',
        )
        batch_op.create_foreign_key(
            'fk_makine_degisim_swap_taseron_hizmet_id_hizmet_kaydi',
            'hizmet_kaydi',
            ['swap_taseron_hizmet_id'],
            ['id'],
            ondelete='SET NULL',
        )
        batch_op.create_foreign_key(
            'fk_makine_degisim_swap_kira_hizmet_id_hizmet_kaydi',
            'hizmet_kaydi',
            ['swap_kira_hizmet_id'],
            ['id'],
            ondelete='SET NULL',
        )


def downgrade():
    with op.batch_alter_table('makine_degisim', schema=None) as batch_op:
        batch_op.drop_constraint('fk_makine_degisim_swap_kira_hizmet_id_hizmet_kaydi', type_='foreignkey')
        batch_op.drop_constraint('fk_makine_degisim_swap_taseron_hizmet_id_hizmet_kaydi', type_='foreignkey')
        batch_op.drop_constraint('fk_makine_degisim_swap_nakliye_id_nakliye', type_='foreignkey')
        batch_op.drop_column('swap_kira_hizmet_id')
        batch_op.drop_column('swap_taseron_hizmet_id')
        batch_op.drop_column('swap_nakliye_id')