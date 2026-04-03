from app.extensions import db
from app.models.base_model import BaseModel


class TakvimHatirlatma(BaseModel):
    __tablename__ = 'takvim_hatirlatma'

    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    tarih = db.Column(db.Date, nullable=False, index=True)
    baslik = db.Column(db.String(150), nullable=False)
    aciklama = db.Column(db.Text, nullable=True)

    user = db.relationship('User', lazy='joined')

    def __repr__(self):
        return f'<TakvimHatirlatma {self.tarih} {self.baslik}>'
