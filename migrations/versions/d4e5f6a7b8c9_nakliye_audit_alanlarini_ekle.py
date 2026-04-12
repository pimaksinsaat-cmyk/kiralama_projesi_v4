"""nakliye tablosuna audit alanlarini ekle

Revision ID: d4e5f6a7b8c9
Revises: 5a9c2d1e7b44, c3a8e1f0b9d2
Create Date: 2026-04-12

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd4e5f6a7b8c9'
down_revision = ('5a9c2d1e7b44', 'c3a8e1f0b9d2')
branch_labels = None
depends_on = None


def _column_names(table_name):
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {col['name'] for col in inspector.get_columns(table_name)}


def upgrade():
    cols = _column_names('nakliye')

    with op.batch_alter_table('nakliye', schema=None) as batch_op:
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


def downgrade():
    cols = _column_names('nakliye')

    with op.batch_alter_table('nakliye', schema=None) as batch_op:
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
