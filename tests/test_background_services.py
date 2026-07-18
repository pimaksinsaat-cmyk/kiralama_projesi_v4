import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.extensions import db
from app.models.system_state import ExchangeRate
from app.services import backup_service
from app.services.kiralama_services import (
    ExchangeRateRefreshError,
    ExchangeRateUnavailableError,
    KiralamaService,
)
import scheduler as scheduler_module


def test_exchange_rates_are_persisted_and_survive_fetch_error(app, monkeypatch):
    with app.app_context():
        monkeypatch.setattr(
            KiralamaService,
            '_fetch_tcmb_kurlari',
            classmethod(lambda cls: {'USD': Decimal('42.10'), 'EUR': Decimal('48.20')}),
        )
        first = KiralamaService.refresh_tcmb_kurlari(force=True)
        assert first['USD'] == Decimal('42.10')
        assert db.session.get(ExchangeRate, 'EUR').selling_rate == Decimal('48.20')

        def fail_fetch(cls):
            raise RuntimeError('network down')

        monkeypatch.setattr(KiralamaService, '_fetch_tcmb_kurlari', classmethod(fail_fetch))
        with pytest.raises(ExchangeRateRefreshError):
            KiralamaService.refresh_tcmb_kurlari(force=True)

        retained = KiralamaService.get_tcmb_kurlari()
        assert retained == {'USD': Decimal('42.100000'), 'EUR': Decimal('48.200000')}


def test_exchange_rates_do_not_silently_return_zero_when_empty(app):
    with app.app_context():
        with pytest.raises(ExchangeRateUnavailableError, match='henuz hazir degil'):
            KiralamaService.get_tcmb_kurlari()


def test_exchange_rates_report_missing_table(app):
    with app.app_context():
        ExchangeRate.__table__.drop(db.engine)
        with pytest.raises(ExchangeRateUnavailableError, match='okunamadi'):
            KiralamaService.get_tcmb_kurlari()


def test_backup_rotation_only_removes_old_automatic_files(tmp_path, monkeypatch):
    monkeypatch.setattr(backup_service, 'BACKUP_DIR', str(tmp_path))
    now = datetime.now(timezone.utc)
    old_auto = tmp_path / 'oto_20260101.sql'
    old_manual = tmp_path / 'db_yedek_20260101.sql'
    fresh_auto = tmp_path / 'oto_20260628.sql'
    for path in (old_auto, old_manual, fresh_auto):
        path.write_text('backup', encoding='utf-8')

    old_timestamp = (now - timedelta(days=15)).timestamp()
    os.utime(old_auto, (old_timestamp, old_timestamp))
    os.utime(old_manual, (old_timestamp, old_timestamp))

    backup_service.rotate_automatic_backups(now=now, keep_path=str(fresh_auto))

    assert not old_auto.exists()
    assert old_manual.exists()
    assert fresh_auto.exists()


def test_automatic_backup_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(backup_service, 'BACKUP_DIR', str(tmp_path))
    written = []

    def fake_write(path):
        written.append(path)
        with open(path, 'w', encoding='utf-8') as handle:
            handle.write('backup')

    monkeypatch.setattr(backup_service, 'write_backup_file', fake_write)
    now = datetime(2026, 6, 28, tzinfo=timezone.utc)
    first = backup_service.create_automatic_backup(now=now)
    second = backup_service.create_automatic_backup(now=now)

    assert first == second
    assert len(written) == 1


def test_scheduler_job_releases_database_session(app):
    called = []
    scheduler_module.app = app
    try:
        scheduler_module._run_locked_job('test job', 123, lambda: called.append(True))
    finally:
        scheduler_module.app = None
    assert called == [True]


def test_scheduler_job_does_not_log_failed_refresh_as_completed(app, caplog):
    scheduler_module.app = app

    def fail_job():
        raise ExchangeRateRefreshError('network down')

    try:
        scheduler_module._run_locked_job('TCMB test', 124, fail_job)
    finally:
        scheduler_module.app = None

    assert 'TCMB test basarisiz oldu.' in caplog.text
    assert 'TCMB test tamamlandi.' not in caplog.text
