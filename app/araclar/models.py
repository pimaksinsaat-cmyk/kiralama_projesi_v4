from app.extensions import db
from datetime import datetime, timezone
from app.models.base_model import BaseModel

class Arac(BaseModel):
    __tablename__ = 'araclar'


    plaka = db.Column(db.String(20), nullable=False, unique=True, index=True)
    arac_tipi = db.Column(db.String(50)) # Çekici, Kamyon, Kayar Kasa vb.
    marka_model = db.Column(db.String(100))
    sube_id = db.Column(db.Integer, db.ForeignKey('subeler.id'), nullable=True)
    sube = db.relationship('Sube', backref='araclar')
    is_nakliye_araci = db.Column(db.Boolean, default=False, nullable=False, index=True)
    is_hizmet_araci = db.Column(db.Boolean, default=False, nullable=False, index=True)

    # Gelecek için şimdiden eklediğimiz kritik tarihler (Şimdilik opsiyonel)
    muayene_tarihi = db.Column(db.Date, nullable=True)
    sigorta_tarihi = db.Column(db.Date, nullable=True)

    bakim_kayitlari = db.relationship('AracBakim', back_populates='arac', cascade="all, delete-orphan")

    is_active = db.Column(db.Boolean, default=True)
    kayit_tarihi = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    @classmethod
    def aktif_query(cls):
        return cls.query.filter(cls.is_active.is_(True))

    @classmethod
    def aktif_nakliye_query(cls):
        return cls.aktif_query().filter(cls.is_nakliye_araci.is_(True))

    @classmethod
    def aktif_hizmet_query(cls):
        return cls.aktif_query().filter(cls.is_hizmet_araci.is_(True))

    @property
    def kullanim_alanlari(self):
        alanlar = []
        if self.is_nakliye_araci:
            alanlar.append('Nakliye')
        if self.is_hizmet_araci:
            alanlar.append('Hizmet')
        return alanlar

    def __repr__(self):
        return f'<Arac {self.plaka}>'


class AracBakim(BaseModel):
    """Araç bakım ve tamir kaydı"""
    __tablename__ = 'arac_bakim'

    arac_id = db.Column(db.Integer, db.ForeignKey('araclar.id'), nullable=False, index=True)
    tarih = db.Column(db.Date, nullable=False)
    bakim_tipi = db.Column(db.String(50), nullable=False)  # Rutin, Acil, Tamir vb.
    yapilan_islem = db.Column(db.String(500), nullable=True)  # Ne yapıldı
    maliyet = db.Column(db.Numeric(15, 2), nullable=True, default=0.0)
    kilometre = db.Column(db.Integer, nullable=True)
    yapan_yer = db.Column(db.String(200), nullable=True)  # Servis/Usta adı
    notlar = db.Column(db.Text, nullable=True)
    sonraki_bakim_turu = db.Column(db.String(20), nullable=True, default='km')  # 'km' veya 'tarih'
    sonraki_bakim_km = db.Column(db.Integer, nullable=True)  # Sonraki bakım km
    sonraki_bakim_tarihi = db.Column(db.Date, nullable=True)  # Sonraki bakım tarihi

    arac = db.relationship('Arac', back_populates='bakim_kayitlari')

    def __repr__(self):
        return f'<AracBakim {self.arac_id}>'