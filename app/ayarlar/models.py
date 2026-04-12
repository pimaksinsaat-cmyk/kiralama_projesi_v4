from sqlalchemy import inspect as sa_inspect
from sqlalchemy.exc import SQLAlchemyError

from app.extensions import db
from app.models.base_model import BaseModel


class AppSettings(BaseModel):
    __tablename__ = 'app_settings'

    company_name = db.Column(db.String(150), nullable=False, default='Pimaks İnşaat')
    company_short_name = db.Column(db.String(80), nullable=True, default='Pimaks')
    logo_path = db.Column(db.String(255), nullable=False, default='img/logo.JPG')

    company_address = db.Column(db.Text, nullable=True)
    company_phone = db.Column(db.String(30), nullable=True)
    company_email = db.Column(db.String(120), nullable=True)
    company_website = db.Column(db.String(200), nullable=True)

    invoice_title = db.Column(db.String(150), nullable=True)
    invoice_address = db.Column(db.Text, nullable=True)
    invoice_tax_office = db.Column(db.String(100), nullable=True)
    invoice_tax_number = db.Column(db.String(50), nullable=True)
    invoice_mersis_no = db.Column(db.String(16), nullable=True)
    invoice_iban = db.Column(db.String(64), nullable=True)
    invoice_notes = db.Column(db.Text, nullable=True)

    kiralama_form_start_no = db.Column(db.Integer, nullable=False, default=1)
    genel_sozlesme_start_no = db.Column(db.Integer, nullable=False, default=1)
    
    kiralama_form_prefix = db.Column(db.String(10), nullable=False, default='PF')
    genel_sozlesme_prefix = db.Column(db.String(10), nullable=False, default='PS')

    @classmethod
    def get_current(cls):
        try:
            if not sa_inspect(db.engine).has_table(cls.__tablename__):
                return None
        except Exception:
            return None

        def _fetch_first():
            return cls.query.order_by(cls.id.asc()).first()

        settings = None
        for _ in range(2):
            try:
                settings = _fetch_first()
                break
            except SQLAlchemyError:
                db.session.rollback()

        if settings:
            return settings

        try:
            settings = cls()
            db.session.add(settings)
            db.session.commit()
            return settings
        except SQLAlchemyError:
            db.session.rollback()
            return None

    @property
    def display_name(self):
        return self.company_short_name or self.company_name or 'Pimaks'