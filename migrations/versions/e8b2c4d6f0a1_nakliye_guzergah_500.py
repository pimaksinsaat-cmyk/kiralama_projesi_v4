"""Nakliye güzergâhı uzunluğunu 500 karaktere çıkar.

Revision ID: e8b2c4d6f0a1
Revises: c3d4e5f6a7b8
"""

from alembic import op
import sqlalchemy as sa


revision = 'e8b2c4d6f0a1'
down_revision = 'c3d4e5f6a7b8'
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column(
        'nakliye',
        'guzergah',
        existing_type=sa.String(length=200),
        type_=sa.String(length=500),
        existing_nullable=False,
    )


def downgrade():
    op.alter_column(
        'nakliye',
        'guzergah',
        existing_type=sa.String(length=500),
        type_=sa.String(length=200),
        existing_nullable=False,
    )
