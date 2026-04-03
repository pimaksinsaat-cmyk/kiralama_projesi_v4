from app.extensions import db
from datetime import datetime
from app.models.base_model import BaseModel
class Arac(BaseModel):
    __tablename__ = 'araclar'
    
    
    plaka = db.Column(db.String(20), nullable=False, unique=True, index=True)
    arac_tipi = db.Column(db.String(50)) # Çekici, Kamyon, Kayar Kasa vb.
    marka_model = db.Column(db.String(100))
    sube_id = db.Column(db.Integer, db.ForeignKey('subeler.id'), nullable=True)
    sube = db.relationship('Sube', backref='araclar')
    
    # Gelecek için şimdiden eklediğimiz kritik tarihler (Şimdilik opsiyonel)
    muayene_tarihi = db.Column(db.Date, nullable=True)
    sigorta_tarihi = db.Column(db.Date, nullable=True)
    
    is_active = db.Column(db.Boolean, default=True)
    kayit_tarihi = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<Arac {self.plaka}>'