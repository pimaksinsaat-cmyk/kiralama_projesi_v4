from datetime import datetime

from app.extensions import db
from app.models.base_model import BaseModel


class Personel(BaseModel):
    __tablename__ = 'personel'

    sube_id = db.Column(db.Integer, db.ForeignKey('subeler.id'), nullable=True, index=True)
    submission_token = db.Column(db.String(64), nullable=True, unique=True)
    ad = db.Column(db.String(50), nullable=False)
    soyad = db.Column(db.String(50), nullable=False)
    tc_no = db.Column(db.String(11), nullable=True, unique=True)
    telefon = db.Column(db.String(20), nullable=True)
    meslek = db.Column(db.String(100), nullable=True)
    maas = db.Column(db.Numeric(15, 2), nullable=True)
    yemek_ucreti = db.Column(db.Numeric(15, 2), nullable=True)
    yol_ucreti = db.Column(db.Numeric(15, 2), nullable=True)
    ise_giris_tarihi = db.Column(db.Date, nullable=True)
    isten_cikis_tarihi = db.Column(db.Date, nullable=True)

    sube = db.relationship('Sube', backref='personeller')
    izinler = db.relationship('PersonelIzin', backref='personel', cascade='all, delete-orphan', lazy='joined')
    maas_donemleri = db.relationship('PersonelMaasDonemi', backref='personel', cascade='all, delete-orphan', lazy='select')

    @property
    def tam_ad(self):
        return f"{self.ad} {self.soyad}"


class PersonelIzin(db.Model):
    __tablename__ = 'personel_izin'

    id = db.Column(db.Integer, primary_key=True)
    personel_id = db.Column(db.Integer, db.ForeignKey('personel.id'), nullable=False, index=True)
    izin_turu = db.Column(db.String(30), nullable=False)
    baslangic_tarihi = db.Column(db.Date, nullable=False)
    bitis_tarihi = db.Column(db.Date, nullable=False)
    gun_sayisi = db.Column(db.Integer, nullable=False)
    aciklama = db.Column(db.String(250), nullable=True)
    is_deleted = db.Column(db.Boolean, default=False, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class PersonelMaasDonemi(db.Model):
    __tablename__ = 'personel_maas_donemleri'

    id = db.Column(db.Integer, primary_key=True)
    personel_id = db.Column(db.Integer, db.ForeignKey('personel.id'), nullable=False, index=True)
    sube_id = db.Column(db.Integer, db.ForeignKey('subeler.id'), nullable=True, index=True)
    baslangic_tarihi = db.Column(db.Date, nullable=False, index=True)
    bitis_tarihi = db.Column(db.Date, nullable=True, index=True)
    aylik_maas = db.Column(db.Numeric(15, 2), nullable=False)
    aylik_yemek_ucreti = db.Column(db.Numeric(15, 2), nullable=True)
    aylik_yol_ucreti = db.Column(db.Numeric(15, 2), nullable=True)
    sgk_isveren_tutari = db.Column(db.Numeric(15, 2), nullable=True)
    yan_haklar_tutari = db.Column(db.Numeric(15, 2), nullable=True)
    diger_gider_tutari = db.Column(db.Numeric(15, 2), nullable=True)
    aciklama = db.Column(db.String(250), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    sube = db.relationship('Sube')

    @property
    def aylik_toplam_maliyet(self):
        return float(self.aylik_maas or 0) + float(self.aylik_yemek_ucreti or 0) + float(self.aylik_yol_ucreti or 0) + float(self.sgk_isveren_tutari or 0) + float(self.yan_haklar_tutari or 0) + float(self.diger_gider_tutari or 0)