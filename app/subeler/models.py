from app.extensions import db
from datetime import datetime

# 1. ŞUBE / DEPO MODELİ
class Sube(db.Model):
    __tablename__ = 'subeler'
    id = db.Column(db.Integer, primary_key=True)
    isim = db.Column(db.String(100), nullable=False) 
    adres = db.Column(db.Text, nullable=True)
    konum_linki = db.Column(db.String(500), nullable=True) 
    yetkili_kisi = db.Column(db.String(100), nullable=True) 
    telefon = db.Column(db.String(20), nullable=True)       
    email = db.Column(db.String(100), nullable=True)        
    is_active = db.Column(db.Boolean, default=True) 
    
    ekipmanlar = db.relationship('Ekipman', back_populates='sube', lazy=True)
    

# 2. TRANSFER GEÇMİŞİ MODELİ
class SubelerArasiTransfer(db.Model):
    __tablename__ = 'sube_transferleri'
    id = db.Column(db.Integer, primary_key=True)
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
    