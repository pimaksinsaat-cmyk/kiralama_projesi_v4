"""API refresh rotation and shared exchange rates

Revision ID: b5c6d7e8f9a0
Revises: a4b5c6d7e8f9
Create Date: 2026-06-28
"""

from alembic import op
import sqlalchemy as sa


revision = 'b5c6d7e8f9a0'
down_revision = 'a4b5c6d7e8f9'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'exchange_rate',
        sa.Column('currency', sa.String(length=3), nullable=False),
        sa.Column('selling_rate', sa.Numeric(precision=12, scale=6), nullable=False),
        sa.Column('source', sa.String(length=32), nullable=False),
        sa.Column('fetched_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('currency'),
    )
    op.create_table(
        'api_refresh_rotation',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('previous_jti', sa.String(length=64), nullable=False),
        sa.Column('successor_session_token', sa.String(length=128), nullable=False),
        sa.Column('access_jti', sa.String(length=64), nullable=False),
        sa.Column('refresh_jti', sa.String(length=64), nullable=False),
        sa.Column('issued_at', sa.DateTime(), nullable=False),
        sa.Column('grace_expires_at', sa.DateTime(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id'),
        sa.UniqueConstraint('previous_jti'),
    )
    op.create_index(
        op.f('ix_api_refresh_rotation_user_id'),
        'api_refresh_rotation',
        ['user_id'],
        unique=True,
    )
    op.create_index(
        op.f('ix_api_refresh_rotation_previous_jti'),
        'api_refresh_rotation',
        ['previous_jti'],
        unique=True,
    )
    op.create_index(
        op.f('ix_api_refresh_rotation_grace_expires_at'),
        'api_refresh_rotation',
        ['grace_expires_at'],
        unique=False,
    )


def downgrade():
    op.drop_index(
        op.f('ix_api_refresh_rotation_grace_expires_at'),
        table_name='api_refresh_rotation',
    )
    op.drop_index(
        op.f('ix_api_refresh_rotation_previous_jti'),
        table_name='api_refresh_rotation',
    )
    op.drop_index(
        op.f('ix_api_refresh_rotation_user_id'),
        table_name='api_refresh_rotation',
    )
    op.drop_table('api_refresh_rotation')
    op.drop_table('exchange_rate')
