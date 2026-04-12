from app.extensions import db
from datetime import datetime
from app.models.base_model import BaseModel

# 1. ŞUBE / DEPO MODELİ
class Sube(BaseModel):
    __tablename__ = 'subeler'
    isim = db.Column(db.String(100), nullable=False)
    adres = db.Column(db.Text, nullable=True)
    konum_linki = db.Column(db.String(500), nullable=True)
    yetkili_kisi = db.Column(db.String(100), nullable=True)
    telefon = db.Column(db.String(20), nullable=True)
    email = db.Column(db.String(100), nullable=True)

    ekipmanlar = db.relationship('Ekipman', back_populates='sube', lazy=True)
    sabit_gider_donemleri = db.relationship('SubeSabitGiderDonemi', backref='sube', lazy='select', cascade='all, delete-orphan')
    

# 2. TRANSFER GEÇMİŞİ MODELİ
class SubelerArasiTransfer(BaseModel):
    __tablename__ = 'sube_transferleri'
    tarih = db.Column(db.DateTime, default=datetime.now)
    
    ekipman_id = db.Column(db.Integer, db.ForeignKey('ekipman.id'), nullable=False)
    gonderen_sube_id = db.Column(db.Integer, db.ForeignKey('subeler.id'), nullable=False)
    alan_sube_id = db.Column(db.Integer, db.ForeignKey('subeler.id'), nullable=False)
    
    # Arac tablosu artık nakliyeler modülünde ama veritabanı adı hala 'araclar'
    arac_id = db.Column(db.Integer, db.ForeignKey('araclar.id'), nullable=False)
    
    neden = db.Column(db.String(50), nullable=False) 
    aciklama = db.Column(db.Text, nullable=True)

    # SQLAlchemy İlişkileri
    ekipman = db.relationship('Ekipman', backref='transfer_gecmisi')
    gonderen_sube = db.relationship('Sube', foreign_keys=[gonderen_sube_id])
    alan_sube = db.relationship('Sube', foreign_keys=[alan_sube_id])
    arac = db.relationship('Arac', backref='yaptigi_transferler')


# 3. ŞUBE GİDER/MASRAF MODELİ
class SubeGideri(BaseModel):
    __tablename__ = 'sube_giderleri'
    sube_id = db.Column(db.Integer, db.ForeignKey('subeler.id'), nullable=False, index=True)
    arac_id = db.Column(db.Integer, db.ForeignKey('araclar.id'), nullable=True, index=True)
    tarih = db.Column(db.Date, nullable=False)
    kategori = db.Column(db.String(50), nullable=False)  # kira, elektrik, su, internet, ikram, personel, temizlik, mazot, diger
    tutar = db.Column(db.Numeric(15, 2), nullable=False)
    litre = db.Column(db.Numeric(10, 2), nullable=True)
    birim_fiyat = db.Column(db.Numeric(10, 2), nullable=True)
    km = db.Column(db.Integer, nullable=True)
    istasyon = db.Column(db.String(150), nullable=True)
    aciklama = db.Column(db.String(250), nullable=True)
    fatura_no = db.Column(db.String(50), nullable=True)

    sube = db.relationship('Sube', backref='giderler')
    arac = db.relationship('Arac', backref='gider_kayitlari')


class SubeSabitGiderDonemi(BaseModel):
    __tablename__ = 'sube_sabit_gider_donemleri'

    sube_id = db.Column(db.Integer, db.ForeignKey('subeler.id'), nullable=False, index=True)
    kategori = db.Column(db.String(50), nullable=False, index=True)
    baslangic_tarihi = db.Column(db.Date, nullable=False, index=True)
    bitis_tarihi = db.Column(db.Date, nullable=True, index=True)
    aylik_tutar = db.Column(db.Numeric(15, 2), nullable=False)
    kdv_orani = db.Column(db.Numeric(5, 2), nullable=True)
    aciklama = db.Column(db.String(250), nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)
    apply_retroactively = db.Column(db.Boolean, default=False, nullable=False)
