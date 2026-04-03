from datetime import datetime, timezone

from app.extensions import db


class OperationLog(db.Model):
    __tablename__ = 'operation_log'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)

    user_id = db.Column(db.Integer, nullable=True, index=True)
    username = db.Column(db.String(80), nullable=True, index=True)

    module = db.Column(db.String(80), nullable=False, index=True)
    action = db.Column(db.String(80), nullable=False, index=True)

    entity_type = db.Column(db.String(80), nullable=True, index=True)
    entity_id = db.Column(db.Integer, nullable=True, index=True)

    success = db.Column(db.Boolean, nullable=False, default=True, index=True)
    description = db.Column(db.Text, nullable=True)
    ip_address = db.Column(db.String(64), nullable=True)
    request_path = db.Column(db.String(255), nullable=True)

    def __repr__(self):
        return f"<OperationLog {self.module}:{self.action} user={self.user_id}>"
