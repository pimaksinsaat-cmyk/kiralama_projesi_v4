"""Çoklu makine nakliye seferi ve dağıtım modeli.

Revision ID: a5b6c7d8e9f0
Revises: a4b5c6d7e8f0
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import uuid


revision = 'a5b6c7d8e9f0'
down_revision = 'a4b5c6d7e8f0'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()

    op.add_column('nakliye', sa.Column('yon', sa.String(length=10), nullable=True))
    op.add_column('nakliye', sa.Column('sefer_uuid', sa.String(length=36), nullable=True))
    op.add_column('kiralama', sa.Column('nakliye_modeli', sa.String(length=20), nullable=False, server_default='legacy'))

    # Legacy seferlere yalnızca kimlik verilir; kayıtların anlamı ve gruplaması
    # değiştirilmez.
    rows = bind.execute(sa.text('SELECT id FROM nakliye WHERE sefer_uuid IS NULL')).fetchall()
    for row in rows:
        bind.execute(
            sa.text('UPDATE nakliye SET sefer_uuid = :value WHERE id = :id'),
            {'value': str(uuid.uuid4()), 'id': row[0]},
        )

    op.create_table(
        'nakliye_dagitim',
        sa.Column('nakliye_id', sa.Integer(), nullable=False),
        sa.Column('kiralama_kalemi_id', sa.Integer(), nullable=False),
        sa.Column('tutar', sa.Numeric(15, 2), nullable=False, server_default='0.00'),
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('created_by_id', sa.Integer(), nullable=True),
        sa.Column('updated_by_id', sa.Integer(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.Column('deleted_by_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['nakliye_id'], ['nakliye.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['kiralama_kalemi_id'], ['kiralama_kalemi.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint('tutar >= 0', name='ck_nakliye_dagitim_tutar_nonnegative'),
    )

    op.add_column('hizmet_kaydi', sa.Column('nakliye_dagitim_id', sa.Integer(), nullable=True))
    op.add_column('hizmet_kaydi', sa.Column('kiralama_kalemi_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_hizmet_kaydi_nakliye_dagitim',
        'hizmet_kaydi', 'nakliye_dagitim',
        ['nakliye_dagitim_id'], ['id'], ondelete='CASCADE',
    )
    op.create_foreign_key(
        'fk_hizmet_kaydi_kiralama_kalemi',
        'hizmet_kaydi', 'kiralama_kalemi',
        ['kiralama_kalemi_id'], ['id'], ondelete='SET NULL',
    )

    if bind.dialect.name == 'postgresql':
        op.create_index(
            'uq_nakliye_sefer_uuid_active', 'nakliye', ['sefer_uuid'],
            unique=True, postgresql_where=sa.text('is_deleted = false'),
        )
        op.create_index(
            'uq_nakliye_dagitim_active_sefer_kalem',
            'nakliye_dagitim', ['nakliye_id', 'kiralama_kalemi_id'],
            unique=True, postgresql_where=sa.text('is_deleted = false'),
        )
        op.create_index(
            'ix_nakliye_dagitim_kalem_active',
            'nakliye_dagitim', ['kiralama_kalemi_id'],
            postgresql_where=sa.text('is_deleted = false'),
        )
        op.create_index(
            'uq_hizmet_kaydi_nakliye_dagitim_active',
            'hizmet_kaydi', ['nakliye_dagitim_id', 'kaynak'],
            unique=True, postgresql_where=sa.text(
                "is_deleted = false AND nakliye_dagitim_id IS NOT NULL"
            ),
        )
        op.execute(sa.text("""
            CREATE OR REPLACE FUNCTION validate_nakliye_dagitim_direction()
            RETURNS trigger AS $$
            DECLARE
                new_yon text;
                existing_id integer;
                kalem_kiralama integer;
                sefer_kiralama integer;
            BEGIN
                SELECT yon, kiralama_id INTO new_yon, sefer_kiralama
                FROM nakliye WHERE id = NEW.nakliye_id;
                SELECT kiralama_id INTO kalem_kiralama
                FROM kiralama_kalemi WHERE id = NEW.kiralama_kalemi_id;

                IF new_yon IS NOT NULL AND new_yon NOT IN ('gidis', 'donus') THEN
                    RAISE EXCEPTION 'Geçersiz nakliye yönü: %', new_yon;
                END IF;
                IF sefer_kiralama IS NOT NULL AND kalem_kiralama IS NOT NULL
                   AND sefer_kiralama <> kalem_kiralama THEN
                    RAISE EXCEPTION 'Nakliye dağıtımı farklı kiralamaya bağlanamaz';
                END IF;

                IF NEW.is_deleted = false AND new_yon IS NOT NULL THEN
                    SELECT d.id INTO existing_id
                    FROM nakliye_dagitim d
                    JOIN nakliye n ON n.id = d.nakliye_id
                    WHERE d.kiralama_kalemi_id = NEW.kiralama_kalemi_id
                      AND d.is_deleted = false
                      AND d.id <> COALESCE(NEW.id, -1)
                      AND n.is_deleted = false
                      AND n.yon = new_yon
                    LIMIT 1;
                    IF existing_id IS NOT NULL THEN
                        RAISE EXCEPTION 'Kalem için aktif % seferi zaten var', new_yon;
                    END IF;
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
        """))
        op.execute(sa.text("""
            CREATE TRIGGER trg_validate_nakliye_dagitim_direction
            BEFORE INSERT OR UPDATE ON nakliye_dagitim
            FOR EACH ROW EXECUTE FUNCTION validate_nakliye_dagitim_direction();
        """))
    else:
        # SQLite test ortamında partial unique desteklenir, yön kuralı servis
        # transaction'ında uygulanır.
        op.create_index(
            'uq_nakliye_sefer_uuid_active', 'nakliye', ['sefer_uuid'], unique=True,
        )
        op.create_index(
            'uq_nakliye_dagitim_active_sefer_kalem',
            'nakliye_dagitim', ['nakliye_id', 'kiralama_kalemi_id'], unique=True,
        )


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name == 'postgresql':
        op.execute(sa.text('DROP TRIGGER IF EXISTS trg_validate_nakliye_dagitim_direction ON nakliye_dagitim'))
        op.execute(sa.text('DROP FUNCTION IF EXISTS validate_nakliye_dagitim_direction()'))
        for name in (
            'uq_hizmet_kaydi_nakliye_dagitim_active',
            'ix_nakliye_dagitim_kalem_active',
            'uq_nakliye_dagitim_active_sefer_kalem',
            'uq_nakliye_sefer_uuid_active',
        ):
            op.drop_index(name, table_name='hizmet_kaydi' if name.startswith('uq_hizmet') else ('nakliye' if 'sefer_uuid' in name else 'nakliye_dagitim'))
    else:
        op.drop_index('uq_nakliye_dagitim_active_sefer_kalem', table_name='nakliye_dagitim')
        op.drop_index('uq_nakliye_sefer_uuid_active', table_name='nakliye')

    op.drop_constraint('fk_hizmet_kaydi_kiralama_kalemi', 'hizmet_kaydi', type_='foreignkey')
    op.drop_constraint('fk_hizmet_kaydi_nakliye_dagitim', 'hizmet_kaydi', type_='foreignkey')
    op.drop_column('hizmet_kaydi', 'kiralama_kalemi_id')
    op.drop_column('hizmet_kaydi', 'nakliye_dagitim_id')
    op.drop_table('nakliye_dagitim')
    op.drop_column('nakliye', 'sefer_uuid')
    op.drop_column('nakliye', 'yon')
    op.drop_column('kiralama', 'nakliye_modeli')
