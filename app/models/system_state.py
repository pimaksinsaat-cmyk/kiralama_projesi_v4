from datetime import datetime

from app.extensions import db


class ExchangeRate(db.Model):
    __tablename__ = 'exchange_rate'

    currency = db.Column(db.String(3), primary_key=True)
    selling_rate = db.Column(db.Numeric(12, 6), nullable=False)
    source = db.Column(db.String(32), nullable=False, default='TCMB')
    fetched_at = db.Column(db.DateTime, nullable=False)


class ApiRefreshRotation(db.Model):
    __tablename__ = 'api_refresh_rotation'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey('user.id', ondelete='CASCADE'),
        nullable=False,
        unique=True,
        index=True,
    )
    previous_jti = db.Column(db.String(64), nullable=False, unique=True, index=True)
    successor_session_token = db.Column(db.String(128), nullable=False)
    access_jti = db.Column(db.String(64), nullable=False)
    refresh_jti = db.Column(db.String(64), nullable=False)
    issued_at = db.Column(db.DateTime, nullable=False)
    grace_expires_at = db.Column(db.DateTime, nullable=False, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
