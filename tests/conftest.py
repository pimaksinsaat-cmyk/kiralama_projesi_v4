"""
Pytest ortamı: in-memory SQLite (varsayılan) veya TEST_DATABASE_URL ile PostgreSQL.
"""
import os
import sqlite3
import uuid

import pytest
from sqlalchemy import event
from sqlalchemy.engine import Engine

# SQLite FK kısıtlarını uygula (dialect connection_record üzerinde olmayabilir; dbapi tipi güvenilir)
@event.listens_for(Engine, "connect")
def _sqlite_enable_foreign_keys(dbapi_connection, _connection_record):
    if not isinstance(dbapi_connection, sqlite3.Connection):
        return
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()


def _import_all_models():
    """Metadata'da tüm tablolar olsun diye model modüllerini yükle."""
    import app.auth.models  # noqa: F401
    import app.firmalar.models  # noqa: F401
    import app.subeler.models  # noqa: F401
    import app.filo.models  # noqa: F401
    import app.kiralama.models  # noqa: F401
    import app.cari.models  # noqa: F401
    import app.fatura.models  # noqa: F401
    import app.nakliyeler.models  # noqa: F401
    import app.makinedegisim.models  # noqa: F401
    import app.araclar.models  # noqa: F401
    import app.ayarlar.models  # noqa: F401
    import app.personel.models  # noqa: F401
    import app.takvim.models  # noqa: F401
    import app.models.operation_log  # noqa: F401


@pytest.fixture(scope="function")
def app():
    os.environ.setdefault("SECRET_KEY", "test-secret-key")
    os.environ.setdefault("FLASK_RUN_FROM_CLI", "false")

    from config import TestingConfig
    from app import create_app
    from app.extensions import db

    application = create_app(TestingConfig)

    with application.app_context():
        _import_all_models()
        db.create_all()
        yield application
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()
