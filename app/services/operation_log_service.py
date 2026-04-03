from flask import request

from app import db
from app.models.operation_log import OperationLog


class OperationLogService:
    @staticmethod
    def log(
        *,
        module,
        action,
        user_id=None,
        username=None,
        entity_type=None,
        entity_id=None,
        description=None,
        success=True,
    ):
        """
        İşlem logunu veritabanına yazar.
        Uygulama akışını bozmasın diye hataları dışarı fırlatmaz.
        """
        try:
            entry = OperationLog(
                module=module,
                action=action,
                user_id=user_id,
                username=username,
                entity_type=entity_type,
                entity_id=entity_id,
                description=description,
                success=bool(success),
                ip_address=(request.remote_addr if request else None),
                request_path=(request.path if request else None),
            )
            db.session.add(entry)
            db.session.commit()
        except Exception:
            db.session.rollback()
