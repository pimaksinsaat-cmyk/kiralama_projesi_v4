"""personel_maas_ve_sabit_gider_donemleri

Revision ID: e4b7c9d1f2a6
Revises: d2a4f6c8e1b3, db93d0cf03a2
Create Date: 2026-04-05 10:05:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = 'e4b7c9d1f2a6'
down_revision = ('d2a4f6c8e1b3', 'db93d0cf03a2')
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'personel_maas_donemleri',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('personel_id', sa.Integer(), nullable=False),
        sa.Column('sube_id', sa.Integer(), nullable=True),
        sa.Column('baslangic_tarihi', sa.Date(), nullable=False),
        sa.Column('bitis_tarihi', sa.Date(), nullable=True),
        sa.Column('aylik_maas', sa.Numeric(15, 2), nullable=False),
        sa.Column('sgk_isveren_tutari', sa.Numeric(15, 2), nullable=True),
        sa.Column('yan_haklar_tutari', sa.Numeric(15, 2), nullable=True),
        sa.Column('diger_gider_tutari', sa.Numeric(15, 2), nullable=True),
        sa.Column('aciklama', sa.String(length=250), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['personel_id'], ['personel.id']),
        sa.ForeignKeyConstraint(['sube_id'], ['subeler.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_personel_maas_donemleri_personel_id'), 'personel_maas_donemleri', ['personel_id'], unique=False)
    op.create_index(op.f('ix_personel_maas_donemleri_sube_id'), 'personel_maas_donemleri', ['sube_id'], unique=False)
    op.create_index(op.f('ix_personel_maas_donemleri_baslangic_tarihi'), 'personel_maas_donemleri', ['baslangic_tarihi'], unique=False)
    op.create_index(op.f('ix_personel_maas_donemleri_bitis_tarihi'), 'personel_maas_donemleri', ['bitis_tarihi'], unique=False)

    op.create_table(
        'sube_sabit_gider_donemleri',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('sube_id', sa.Integer(), nullable=False),
        sa.Column('kategori', sa.String(length=50), nullable=False),
        sa.Column('baslangic_tarihi', sa.Date(), nullable=False),
        sa.Column('bitis_tarihi', sa.Date(), nullable=True),
        sa.Column('aylik_tutar', sa.Numeric(15, 2), nullable=False),
        sa.Column('kdv_orani', sa.Numeric(5, 2), nullable=True),
        sa.Column('aciklama', sa.String(length=250), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['sube_id'], ['subeler.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_sube_sabit_gider_donemleri_sube_id'), 'sube_sabit_gider_donemleri', ['sube_id'], unique=False)
    op.create_index(op.f('ix_sube_sabit_gider_donemleri_kategori'), 'sube_sabit_gider_donemleri', ['kategori'], unique=False)
    op.create_index(op.f('ix_sube_sabit_gider_donemleri_baslangic_tarihi'), 'sube_sabit_gider_donemleri', ['baslangic_tarihi'], unique=False)
    op.create_index(op.f('ix_sube_sabit_gider_donemleri_bitis_tarihi'), 'sube_sabit_gider_donemleri', ['bitis_tarihi'], unique=False)
    op.create_index(op.f('ix_sube_sabit_gider_donemleri_is_active'), 'sube_sabit_gider_donemleri', ['is_active'], unique=False)

    connection = op.get_bind()
    connection.execute(
        sa.text(
            """
            INSERT INTO personel_maas_donemleri (
                personel_id,
                sube_id,
                baslangic_tarihi,
                bitis_tarihi,
                aylik_maas,
                sgk_isveren_tutari,
                yan_haklar_tutari,
                diger_gider_tutari,
                aciklama,
                created_at
            )
            SELECT
                p.id,
                p.sube_id,
                COALESCE(p.ise_giris_tarihi, CAST(p.created_at AS DATE), CURRENT_DATE),
                p.isten_cikis_tarihi,
                p.maas,
                NULL,
                NULL,
                NULL,
                'Ilk gecis kaydi',
                COALESCE(p.created_at, CURRENT_TIMESTAMP)
            FROM personel p
            WHERE COALESCE(p.maas, 0) > 0
              AND COALESCE(p.is_deleted, FALSE) = FALSE
            """
        )
    )


def downgrade():
    op.drop_index(op.f('ix_sube_sabit_gider_donemleri_is_active'), table_name='sube_sabit_gider_donemleri')
    op.drop_index(op.f('ix_sube_sabit_gider_donemleri_bitis_tarihi'), table_name='sube_sabit_gider_donemleri')
    op.drop_index(op.f('ix_sube_sabit_gider_donemleri_baslangic_tarihi'), table_name='sube_sabit_gider_donemleri')
    op.drop_index(op.f('ix_sube_sabit_gider_donemleri_kategori'), table_name='sube_sabit_gider_donemleri')
    op.drop_index(op.f('ix_sube_sabit_gider_donemleri_sube_id'), table_name='sube_sabit_gider_donemleri')
    op.drop_table('sube_sabit_gider_donemleri')

    op.drop_index(op.f('ix_personel_maas_donemleri_bitis_tarihi'), table_name='personel_maas_donemleri')
    op.drop_index(op.f('ix_personel_maas_donemleri_baslangic_tarihi'), table_name='personel_maas_donemleri')
    op.drop_index(op.f('ix_personel_maas_donemleri_sube_id'), table_name='personel_maas_donemleri')
    op.drop_index(op.f('ix_personel_maas_donemleri_personel_id'), table_name='personel_maas_donemleri')
    op.drop_table('personel_maas_donemleri')