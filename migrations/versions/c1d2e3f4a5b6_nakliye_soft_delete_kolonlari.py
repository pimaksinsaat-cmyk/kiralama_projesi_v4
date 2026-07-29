"""nakliye soft-delete ve audit kolonlarini tamamla

Revision ID: c1d2e3f4a5b6
Revises: b9c0d1e2f3a4
Create Date: 2026-07-29

Canli semada d4e5f6a7b8c9 yansimamis olabilecegi icin kolonlari
idempotent ekler, is_deleted = NOT is_active backfill uygular,
ix_nakliye_is_deleted ve aktiflik bileşik indekslerini olusturur.
"""

from alembic import op
import sqlalchemy as sa


revision = 'c1d2e3f4a5b6'
down_revision = 'b9c0d1e2f3a4'
branch_labels = None
depends_on = None


def _column_names(table_name):
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {col['name'] for col in inspector.get_columns(table_name)}


def _index_names(table_name):
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {idx['name'] for idx in inspector.get_indexes(table_name)}


def upgrade():
    cols = _column_names('nakliye')
    indexes = _index_names('nakliye')

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

    # Aktif olup is_deleted=true olanlar veri tutarsizligidir. Otomatik olarak
    # acilmaz; deploy sonrasi raporlama sorgulariyla incelenmelidir.
    inconsistent_count = op.get_bind().execute(
        sa.text(
            "SELECT COUNT(*) FROM nakliye "
            "WHERE is_deleted IS TRUE AND is_active IS TRUE"
        )
    ).scalar()
    if inconsistent_count:
        print(
            f"[nakliye-soft-delete] {inconsistent_count} tutarsiz kayit: "
            "is_deleted=true ve is_active=true"
        )

    # Pasif kayitlari soft-deleted kabul et (silinme zamani/kullanicisi bilinmiyor).
    # Acikca silinmis aktif kayitlara dokunulmaz.
    op.execute(
        sa.text(
            "UPDATE nakliye SET is_deleted = true "
            "WHERE is_active IS FALSE AND is_deleted IS DISTINCT FROM TRUE"
        )
    )

    indexes = _index_names('nakliye')
    if 'ix_nakliye_is_deleted' not in indexes:
        with op.batch_alter_table('nakliye', schema=None) as batch_op:
            batch_op.create_index('ix_nakliye_is_deleted', ['is_deleted'], unique=False)

    indexes = _index_names('nakliye')
    if 'ix_nakliye_active_deleted' not in indexes:
        with op.batch_alter_table('nakliye', schema=None) as batch_op:
            batch_op.create_index(
                'ix_nakliye_active_deleted',
                ['is_active', 'is_deleted'],
                unique=False,
            )


def downgrade():
    # Bu migration canli DB'de daha once uygulanmis d4e5f6a7b8c9'un eksik
    # nesnelerini de tamamlayabilir. Mevcut kolonlari/indexleri silmek
    # guvenli degildir; downgrade bilerek no-op'tur.
    pass
