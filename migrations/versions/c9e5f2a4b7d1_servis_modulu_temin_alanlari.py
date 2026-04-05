"""Servis modulu temel alanlari

Revision ID: c9e5f2a4b7d1
Revises: 8a4d0b6f2c11
Create Date: 2026-04-04 17:25:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c9e5f2a4b7d1'
down_revision = '8a4d0b6f2c11'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('bakim_kaydi', schema=None) as batch_op:
        batch_op.add_column(sa.Column('bakim_tipi', sa.String(length=30), nullable=False, server_default='ariza'))
        batch_op.add_column(sa.Column('servis_tipi', sa.String(length=30), nullable=False, server_default='ic_servis'))
        batch_op.add_column(sa.Column('durum', sa.String(length=30), nullable=False, server_default='acik'))
        batch_op.add_column(sa.Column('servis_veren_firma_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('servis_veren_kisi', sa.String(length=150), nullable=True))
        batch_op.add_column(sa.Column('sonraki_bakim_tarihi', sa.Date(), nullable=True))
        batch_op.add_column(sa.Column('toplam_iscilik_maliyeti', sa.Numeric(precision=15, scale=2), nullable=False, server_default='0'))
        batch_op.create_foreign_key(
            'fk_bakim_kaydi_servis_veren_firma_id_firma',
            'firma',
            ['servis_veren_firma_id'],
            ['id'],
        )


def downgrade():
    with op.batch_alter_table('bakim_kaydi', schema=None) as batch_op:
        batch_op.drop_constraint('fk_bakim_kaydi_servis_veren_firma_id_firma', type_='foreignkey')
        batch_op.drop_column('toplam_iscilik_maliyeti')
        batch_op.drop_column('sonraki_bakim_tarihi')
        batch_op.drop_column('servis_veren_kisi')
        batch_op.drop_column('servis_veren_firma_id')
        batch_op.drop_column('durum')
        batch_op.drop_column('servis_tipi')
        batch_op.drop_column('bakim_tipi')