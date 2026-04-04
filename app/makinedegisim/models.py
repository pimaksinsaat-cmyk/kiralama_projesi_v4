from app.extensions import db
from datetime import datetime
from app.models.base_model import BaseModel
class MakineDegisim(BaseModel):
    __tablename__ = 'makine_degisim'
    
    
    kiralama_id = db.Column(db.Integer, db.ForeignKey('kiralama.id'), nullable=False)
    eski_kalem_id = db.Column(db.Integer, db.ForeignKey('kiralama_kalemi.id'), nullable=False)
    yeni_kalem_id = db.Column(db.Integer, db.ForeignKey('kiralama_kalemi.id'), nullable=False)
    eski_ekipman_id = db.Column(db.Integer, db.ForeignKey('ekipman.id'), nullable=True)
    yeni_ekipman_id = db.Column(db.Integer, db.ForeignKey('ekipman.id'), nullable=True)
    swap_nakliye_id = db.Column(db.Integer, db.ForeignKey('nakliye.id', ondelete='SET NULL'), nullable=True)
    swap_taseron_hizmet_id = db.Column(db.Integer, db.ForeignKey('hizmet_kaydi.id', ondelete='SET NULL'), nullable=True)
    swap_kira_hizmet_id = db.Column(db.Integer, db.ForeignKey('hizmet_kaydi.id', ondelete='SET NULL'), nullable=True)
    
    neden = db.Column(db.String(50), nullable=False) 
    tarih = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    aciklama = db.Column(db.Text, nullable=True)
    eski_ekipman_donus_saati = db.Column(db.Integer, nullable=True)
    yeni_ekipman_cikis_saati = db.Column(db.Integer, nullable=True)
    servis_kayit_id = db.Column(db.Integer, nullable=True) 

    # İlişkiler
    eski_ekipman = db.relationship('Ekipman', foreign_keys=[eski_ekipman_id],back_populates='swap_cikis_kayitlari')
    yeni_ekipman = db.relationship('Ekipman', foreign_keys=[yeni_ekipman_id], back_populates='swap_giris_kayitlari')
    eski_satir = db.relationship('KiralamaKalemi', foreign_keys=[eski_kalem_id])
    yeni_satir = db.relationship('KiralamaKalemi', foreign_keys=[yeni_kalem_id])
    swap_nakliye = db.relationship('Nakliye', foreign_keys=[swap_nakliye_id])
    swap_taseron_hizmeti = db.relationship('HizmetKaydi', foreign_keys=[swap_taseron_hizmet_id])
    swap_kira_hizmeti = db.relationship('HizmetKaydi', foreign_keys=[swap_kira_hizmet_id])
    

    def __repr__(self):
        return f'<MakineDegisim {self.id}>'