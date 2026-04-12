"""BaseModel alanlari eklendi (subeler, personel, auth)

Revision ID: f9g0h1i2j3k4
Revises: d4e5f6a7b8c9
Create Date: 2026-04-12

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f9g0h1i2j3k4'
down_revision = 'd4e5f6a7b8c9'
branch_labels = None
depends_on = None


def _column_names(table_name):
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {col['name'] for col in inspector.get_columns(table_name)}


def upgrade():
    # =========== USER TABLOSU ===========
    cols = _column_names('user')
    with op.batch_alter_table('user', schema=None) as batch_op:
        if 'is_deleted' not in cols:
            batch_op.add_column(
                sa.Column(
                    'is_deleted',
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.text('false'),
                )
            )
        if 'deleted_at' not in cols:
            batch_op.add_column(sa.Column('deleted_at', sa.DateTime(), nullable=True))
        if 'deleted_by_id' not in cols:
            batch_op.add_column(sa.Column('deleted_by_id', sa.Integer(), nullable=True))
        if 'updated_at' not in cols:
            batch_op.add_column(sa.Column('updated_at', sa.DateTime(), nullable=True))
        if 'updated_by_id' not in cols:
            batch_op.add_column(sa.Column('updated_by_id', sa.Integer(), nullable=True))
        if 'created_by_id' not in cols:
            batch_op.add_column(sa.Column('created_by_id', sa.Integer(), nullable=True))

    # =========== SUBELER TABLOSU ===========
    cols = _column_names('subeler')
    with op.batch_alter_table('subeler', schema=None) as batch_op:
        # is_active nullable=True -> nullable=False fix
        if 'is_active' in cols:
            batch_op.alter_column(
                'is_active',
                existing_type=sa.Boolean(),
                nullable=False,
                existing_server_default=sa.text('true'),
            )

        # Missing audit fields
        if 'created_at' not in cols:
            batch_op.add_column(
                sa.Column(
                    'created_at',
                    sa.DateTime(),
                    nullable=False,
                    server_default=sa.text('CURRENT_TIMESTAMP'),
                )
            )
        if 'updated_at' not in cols:
            batch_op.add_column(sa.Column('updated_at', sa.DateTime(), nullable=True))
        if 'created_by_id' not in cols:
            batch_op.add_column(sa.Column('created_by_id', sa.Integer(), nullable=True))
        if 'updated_by_id' not in cols:
            batch_op.add_column(sa.Column('updated_by_id', sa.Integer(), nullable=True))
        if 'is_deleted' not in cols:
            batch_op.add_column(
                sa.Column(
                    'is_deleted',
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.text('false'),
                )
            )
        if 'deleted_at' not in cols:
            batch_op.add_column(sa.Column('deleted_at', sa.DateTime(), nullable=True))
        if 'deleted_by_id' not in cols:
            batch_op.add_column(sa.Column('deleted_by_id', sa.Integer(), nullable=True))

    # =========== SUBE_GIDERLERI TABLOSU ===========
    cols = _column_names('sube_giderleri')
    with op.batch_alter_table('sube_giderleri', schema=None) as batch_op:
        if 'is_active' not in cols:
            batch_op.add_column(
                sa.Column(
                    'is_active',
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.text('true'),
                )
            )
        if 'is_deleted' not in cols:
            batch_op.add_column(
                sa.Column(
                    'is_deleted',
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.text('false'),
                )
            )
        if 'deleted_at' not in cols:
            batch_op.add_column(sa.Column('deleted_at', sa.DateTime(), nullable=True))
        if 'deleted_by_id' not in cols:
            batch_op.add_column(sa.Column('deleted_by_id', sa.Integer(), nullable=True))
        if 'updated_at' not in cols:
            batch_op.add_column(sa.Column('updated_at', sa.DateTime(), nullable=True))
        if 'updated_by_id' not in cols:
            batch_op.add_column(sa.Column('updated_by_id', sa.Integer(), nullable=True))
        if 'created_by_id' not in cols:
            batch_op.add_column(sa.Column('created_by_id', sa.Integer(), nullable=True))

    # =========== SUBE_TRANSFERLERI TABLOSU ===========
    cols = _column_names('sube_transferleri')
    with op.batch_alter_table('sube_transferleri', schema=None) as batch_op:
        if 'is_active' not in cols:
            batch_op.add_column(
                sa.Column(
                    'is_active',
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.text('true'),
                )
            )
        if 'is_deleted' not in cols:
            batch_op.add_column(
                sa.Column(
                    'is_deleted',
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.text('false'),
                )
            )
        if 'deleted_at' not in cols:
            batch_op.add_column(sa.Column('deleted_at', sa.DateTime(), nullable=True))
        if 'deleted_by_id' not in cols:
            batch_op.add_column(sa.Column('deleted_by_id', sa.Integer(), nullable=True))
        if 'created_at' not in cols:
            batch_op.add_column(
                sa.Column(
                    'created_at',
                    sa.DateTime(),
                    nullable=False,
                    server_default=sa.text('CURRENT_TIMESTAMP'),
                )
            )
        if 'updated_at' not in cols:
            batch_op.add_column(sa.Column('updated_at', sa.DateTime(), nullable=True))
        if 'created_by_id' not in cols:
            batch_op.add_column(sa.Column('created_by_id', sa.Integer(), nullable=True))
        if 'updated_by_id' not in cols:
            batch_op.add_column(sa.Column('updated_by_id', sa.Integer(), nullable=True))

    # =========== SUBE_SABIT_GIDER_DONEMLERI TABLOSU ===========
    cols = _column_names('sube_sabit_gider_donemleri')
    with op.batch_alter_table('sube_sabit_gider_donemleri', schema=None) as batch_op:
        # Critical: apply_retroactively might be missing
        if 'apply_retroactively' not in cols:
            batch_op.add_column(
                sa.Column(
                    'apply_retroactively',
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.text('false'),
                )
            )
        if 'is_deleted' not in cols:
            batch_op.add_column(
                sa.Column(
                    'is_deleted',
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.text('false'),
                )
            )
        if 'deleted_at' not in cols:
            batch_op.add_column(sa.Column('deleted_at', sa.DateTime(), nullable=True))
        if 'deleted_by_id' not in cols:
            batch_op.add_column(sa.Column('deleted_by_id', sa.Integer(), nullable=True))
        if 'updated_at' not in cols:
            batch_op.add_column(sa.Column('updated_at', sa.DateTime(), nullable=True))
        if 'updated_by_id' not in cols:
            batch_op.add_column(sa.Column('updated_by_id', sa.Integer(), nullable=True))
        if 'created_by_id' not in cols:
            batch_op.add_column(sa.Column('created_by_id', sa.Integer(), nullable=True))

    # =========== PERSONEL_IZIN TABLOSU ===========
    cols = _column_names('personel_izin')
    with op.batch_alter_table('personel_izin', schema=None) as batch_op:
        if 'is_active' not in cols:
            batch_op.add_column(
                sa.Column(
                    'is_active',
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.text('true'),
                )
            )
        if 'deleted_at' not in cols:
            batch_op.add_column(sa.Column('deleted_at', sa.DateTime(), nullable=True))
        if 'deleted_by_id' not in cols:
            batch_op.add_column(sa.Column('deleted_by_id', sa.Integer(), nullable=True))
        if 'updated_at' not in cols:
            batch_op.add_column(sa.Column('updated_at', sa.DateTime(), nullable=True))
        if 'updated_by_id' not in cols:
            batch_op.add_column(sa.Column('updated_by_id', sa.Integer(), nullable=True))
        if 'created_by_id' not in cols:
            batch_op.add_column(sa.Column('created_by_id', sa.Integer(), nullable=True))

    # =========== PERSONEL_MAAS_DONEMLERI TABLOSU ===========
    cols = _column_names('personel_maas_donemleri')
    with op.batch_alter_table('personel_maas_donemleri', schema=None) as batch_op:
        if 'is_active' not in cols:
            batch_op.add_column(
                sa.Column(
                    'is_active',
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.text('true'),
                )
            )
        if 'is_deleted' not in cols:
            batch_op.add_column(
                sa.Column(
                    'is_deleted',
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.text('false'),
                )
            )
        if 'deleted_at' not in cols:
            batch_op.add_column(sa.Column('deleted_at', sa.DateTime(), nullable=True))
        if 'deleted_by_id' not in cols:
            batch_op.add_column(sa.Column('deleted_by_id', sa.Integer(), nullable=True))
        if 'updated_at' not in cols:
            batch_op.add_column(sa.Column('updated_at', sa.DateTime(), nullable=True))
        if 'updated_by_id' not in cols:
            batch_op.add_column(sa.Column('updated_by_id', sa.Integer(), nullable=True))
        if 'created_by_id' not in cols:
            batch_op.add_column(sa.Column('created_by_id', sa.Integer(), nullable=True))


def downgrade():
    # =========== PERSONEL_MAAS_DONEMLERI TABLOSU ===========
    cols = _column_names('personel_maas_donemleri')
    with op.batch_alter_table('personel_maas_donemleri', schema=None) as batch_op:
        if 'created_by_id' in cols:
            batch_op.drop_column('created_by_id')
        if 'updated_by_id' in cols:
            batch_op.drop_column('updated_by_id')
        if 'updated_at' in cols:
            batch_op.drop_column('updated_at')
        if 'deleted_by_id' in cols:
            batch_op.drop_column('deleted_by_id')
        if 'deleted_at' in cols:
            batch_op.drop_column('deleted_at')
        if 'is_deleted' in cols:
            batch_op.drop_column('is_deleted')
        if 'is_active' in cols:
            batch_op.drop_column('is_active')

    # =========== PERSONEL_IZIN TABLOSU ===========
    cols = _column_names('personel_izin')
    with op.batch_alter_table('personel_izin', schema=None) as batch_op:
        if 'created_by_id' in cols:
            batch_op.drop_column('created_by_id')
        if 'updated_by_id' in cols:
            batch_op.drop_column('updated_by_id')
        if 'updated_at' in cols:
            batch_op.drop_column('updated_at')
        if 'deleted_by_id' in cols:
            batch_op.drop_column('deleted_by_id')
        if 'deleted_at' in cols:
            batch_op.drop_column('deleted_at')
        if 'is_active' in cols:
            batch_op.drop_column('is_active')

    # =========== SUBE_SABIT_GIDER_DONEMLERI TABLOSU ===========
    cols = _column_names('sube_sabit_gider_donemleri')
    with op.batch_alter_table('sube_sabit_gider_donemleri', schema=None) as batch_op:
        if 'created_by_id' in cols:
            batch_op.drop_column('created_by_id')
        if 'updated_by_id' in cols:
            batch_op.drop_column('updated_by_id')
        if 'updated_at' in cols:
            batch_op.drop_column('updated_at')
        if 'deleted_by_id' in cols:
            batch_op.drop_column('deleted_by_id')
        if 'deleted_at' in cols:
            batch_op.drop_column('deleted_at')
        if 'is_deleted' in cols:
            batch_op.drop_column('is_deleted')
        if 'apply_retroactively' in cols:
            batch_op.drop_column('apply_retroactively')

    # =========== SUBE_TRANSFERLERI TABLOSU ===========
    cols = _column_names('sube_transferleri')
    with op.batch_alter_table('sube_transferleri', schema=None) as batch_op:
        if 'updated_by_id' in cols:
            batch_op.drop_column('updated_by_id')
        if 'created_by_id' in cols:
            batch_op.drop_column('created_by_id')
        if 'updated_at' in cols:
            batch_op.drop_column('updated_at')
        if 'created_at' in cols:
            batch_op.drop_column('created_at')
        if 'deleted_by_id' in cols:
            batch_op.drop_column('deleted_by_id')
        if 'deleted_at' in cols:
            batch_op.drop_column('deleted_at')
        if 'is_deleted' in cols:
            batch_op.drop_column('is_deleted')
        if 'is_active' in cols:
            batch_op.drop_column('is_active')

    # =========== SUBE_GIDERLERI TABLOSU ===========
    cols = _column_names('sube_giderleri')
    with op.batch_alter_table('sube_giderleri', schema=None) as batch_op:
        if 'created_by_id' in cols:
            batch_op.drop_column('created_by_id')
        if 'updated_by_id' in cols:
            batch_op.drop_column('updated_by_id')
        if 'updated_at' in cols:
            batch_op.drop_column('updated_at')
        if 'deleted_by_id' in cols:
            batch_op.drop_column('deleted_by_id')
        if 'deleted_at' in cols:
            batch_op.drop_column('deleted_at')
        if 'is_deleted' in cols:
            batch_op.drop_column('is_deleted')
        if 'is_active' in cols:
            batch_op.drop_column('is_active')

    # =========== SUBELER TABLOSU ===========
    cols = _column_names('subeler')
    with op.batch_alter_table('subeler', schema=None) as batch_op:
        if 'deleted_by_id' in cols:
            batch_op.drop_column('deleted_by_id')
        if 'deleted_at' in cols:
            batch_op.drop_column('deleted_at')
        if 'is_deleted' in cols:
            batch_op.drop_column('is_deleted')
        if 'updated_by_id' in cols:
            batch_op.drop_column('updated_by_id')
        if 'created_by_id' in cols:
            batch_op.drop_column('created_by_id')
        if 'updated_at' in cols:
            batch_op.drop_column('updated_at')
        if 'created_at' in cols:
            batch_op.drop_column('created_at')
        # Revert is_active nullable change
        if 'is_active' in cols:
            batch_op.alter_column(
                'is_active',
                existing_type=sa.Boolean(),
                nullable=True,
                existing_server_default=sa.text('true'),
            )

    # =========== USER TABLOSU ===========
    cols = _column_names('user')
    with op.batch_alter_table('user', schema=None) as batch_op:
        if 'created_by_id' in cols:
            batch_op.drop_column('created_by_id')
        if 'updated_by_id' in cols:
            batch_op.drop_column('updated_by_id')
        if 'updated_at' in cols:
            batch_op.drop_column('updated_at')
        if 'deleted_by_id' in cols:
            batch_op.drop_column('deleted_by_id')
        if 'deleted_at' in cols:
            batch_op.drop_column('deleted_at')
        if 'is_deleted' in cols:
            batch_op.drop_column('is_deleted')
