import logging
import os
from contextlib import contextmanager
from zoneinfo import ZoneInfo

from apscheduler.schedulers.blocking import BlockingScheduler
from sqlalchemy import text

from app import create_app
from app.extensions import db
from app.services.backup_service import create_automatic_backup
from app.services.kiralama_services import KiralamaService
from config import Config, ProductionConfig


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

RATE_LOCK_KEY = 741001
BACKUP_LOCK_KEY = 741002


def _select_config():
    environment = (
        os.environ.get('FLASK_CONFIG')
        or os.environ.get('FLASK_ENV')
        or ''
    ).lower()
    return ProductionConfig if environment == 'production' else Config


app = None


@contextmanager
def advisory_lock(lock_key):
    if db.engine.url.get_backend_name() != 'postgresql':
        yield True
        return

    connection = db.engine.connect()
    acquired = False
    try:
        acquired = bool(
            connection.execute(
                text('SELECT pg_try_advisory_lock(:lock_key)'),
                {'lock_key': lock_key},
            ).scalar()
        )
        yield acquired
    finally:
        if acquired:
            connection.execute(
                text('SELECT pg_advisory_unlock(:lock_key)'),
                {'lock_key': lock_key},
            )
        connection.close()


def _run_locked_job(name, lock_key, callback):
    if app is None:
        raise RuntimeError('Scheduler uygulamasi baslatilmadi.')
    with app.app_context():
        try:
            with advisory_lock(lock_key) as acquired:
                if not acquired:
                    logger.info('%s atlandi: advisory lock baska bir surecte.', name)
                    return
                callback()
                logger.info('%s tamamlandi.', name)
        except Exception:
            db.session.rollback()
            logger.exception('%s basarisiz oldu.', name)
        finally:
            db.session.remove()


def refresh_exchange_rates():
    _run_locked_job(
        'TCMB kur guncelleme',
        RATE_LOCK_KEY,
        lambda: KiralamaService.refresh_tcmb_kurlari(force=True),
    )


def create_database_backup():
    _run_locked_job(
        'Otomatik veritabani yedegi',
        BACKUP_LOCK_KEY,
        create_automatic_backup,
    )


def main():
    global app
    app = create_app(_select_config())
    timezone = ZoneInfo('Europe/Istanbul')
    scheduler = BlockingScheduler(timezone=timezone)
    scheduler.add_job(
        refresh_exchange_rates,
        trigger='interval',
        hours=1,
        id='saatlik_kur_guncelle',
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    scheduler.add_job(
        create_database_backup,
        trigger='cron',
        hour=2,
        minute=0,
        id='gunluk_yedek',
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )

    refresh_exchange_rates()
    create_database_backup()
    scheduler.start()


if __name__ == '__main__':
    main()
