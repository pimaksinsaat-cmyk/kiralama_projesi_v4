from app.extensions import db
from datetime import datetime
from app.models.base_model import BaseModel

class Kiralama(BaseModel):
    __tablename__ = 'kiralama'
    
    
    kiralama_form_no = db.Column(db.String(100), nullable=False, unique=True)
    makine_calisma_adresi = db.Column(db.Text, nullable=True)
    kiralama_olusturma_tarihi = db.Column(db.Date, nullable=True)  # Form ilk hazırlandı ğında set edilir, sonra değişmez
    kdv_orani = db.Column(db.Integer, nullable=False, default=20)
    
    # Döviz kurları için yüksek hassasiyet (Numeric)
    doviz_kuru_usd = db.Column(db.Numeric(10, 4), nullable=True, default=0.0)
    doviz_kuru_eur = db.Column(db.Numeric(10, 4), nullable=True, default=0.0)
    
    firma_musteri_id = db.Column(db.Integer, db.ForeignKey('firma.id'), nullable=False)
    
    # İlişkiler
    firma_musteri = db.relationship('Firma', back_populates='kiralamalar', foreign_keys=[firma_musteri_id])
    kalemler = db.relationship('KiralamaKalemi', back_populates='kiralama', cascade="all, delete-orphan")
    nakliyeler = db.relationship('Nakliye', back_populates='kiralama', cascade="all, delete-orphan")
    def __repr__(self):
        return f'<Kiralama {self.kiralama_form_no}>'

from app.extensions import db
from datetime import datetime

class KiralamaKalemi(BaseModel):
    __tablename__ = 'kiralama_kalemi'
    
    
    kiralama_id = db.Column(db.Integer, db.ForeignKey('kiralama.id'), nullable=False)
    
    # --- PİMAKS FİLOSU ---
    ekipman_id = db.Column(db.Integer, db.ForeignKey('ekipman.id'), nullable=True)
    
    # --- DIŞ TEDARİK (HARİCİ) EKİPMAN BİLGİLERİ ---
    # Not: Eski kayıtlarda bu alanlar yoktu (NULL olacak). is_dis_tedarik_ekipman=True iken
    # bu alanlar doldurulmalı, ama mevcut verileri bozmamak için nullable=True tutuldu.
    # Uygulama mantığında is_dis_tedarik_ekipman=True ise bu alanlar validate edilmeli.
    is_dis_tedarik_ekipman = db.Column(db.Boolean, default=False)
    harici_ekipman_tipi = db.Column(db.String(100), nullable=True)
    harici_ekipman_marka = db.Column(db.String(100), nullable=True)
    harici_ekipman_model = db.Column(db.String(100), nullable=True)
    harici_ekipman_seri_no = db.Column(db.String(100), nullable=True)
    harici_ekipman_kapasite = db.Column(db.Integer, nullable=True)
    harici_ekipman_yukseklik = db.Column(db.Integer, nullable=True)
    harici_ekipman_uretim_yili = db.Column(db.Integer, nullable=True)
    harici_ekipman_tedarikci_id = db.Column(db.Integer, db.ForeignKey('firma.id'), nullable=True)
    
    # --- TARİHLER ---
    kiralama_baslangici = db.Column(db.Date, nullable=False)
    kiralama_bitis = db.Column(db.Date, nullable=False)
    
    # --- FİNANSAL VERİLER ---
    kiralama_brm_fiyat = db.Column(db.Numeric(15, 2), nullable=False, default=0.0) 
    kiralama_alis_fiyat = db.Column(db.Numeric(15, 2), nullable=True, default=0.0) 
    kiralama_alis_kdv = db.Column(db.Integer, nullable=True, default=None)  # Alış KDV (%)
    
    # --- NAKLİYE ---
    is_oz_mal_nakliye = db.Column(db.Boolean, default=True)
    is_harici_nakliye = db.Column(db.Boolean, default=False)
    nakliye_satis_fiyat = db.Column(db.Numeric(15, 2), nullable=True, default=0.0) 
    donus_nakliye_fatura_et = db.Column(db.Boolean, default=False, nullable=False)
    donus_nakliye_satis_fiyat = db.Column(db.Numeric(15, 2), nullable=True)
    nakliye_alis_fiyat = db.Column(db.Numeric(15, 2), nullable=True, default=0.0)
    nakliye_alis_kdv = db.Column(db.Integer, nullable=True, default=None)
    nakliye_satis_kdv = db.Column(db.Integer, nullable=True, default=None)
    nakliye_alis_tevkifat_oran = db.Column(db.String(10), nullable=True, default=None)
    nakliye_satis_tevkifat_oran = db.Column(db.String(10), nullable=True, default=None)
    nakliye_tedarikci_id = db.Column(db.Integer, db.ForeignKey('firma.id'), nullable=True)
    nakliye_araci_id = db.Column(db.Integer, db.ForeignKey('ekipman.id'), nullable=True)
    
    # --- DURUM VE VERSİYONLAMA (YENİ EKLENENLER) ---
    sonlandirildi = db.Column(db.Boolean, default=False, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False) # Şu anki aktif versiyon mu?
    
    parent_id = db.Column(db.Integer, db.ForeignKey('kiralama_kalemi.id'), nullable=True)
    versiyon_no = db.Column(db.Integer, default=1, nullable=False)
    
    # --- DEĞİŞİM VE SAYAÇ BİLGİLERİ (SAAT ŞARTI YOK) ---
    degisim_nedeni = db.Column(db.String(50), nullable=True) # ariza, bakim, musteri_istegi
    degisim_tarihi = db.Column(db.DateTime, nullable=True)
    
    cikis_saati = db.Column(db.Integer, nullable=True) # Teslimat anındaki saat
    donus_saati = db.Column(db.Integer, nullable=True) # Sahadan çekildiği andaki saat
    
    degisim_aciklama = db.Column(db.Text, nullable=True)

    

    # --- İLİŞKİLER ---
    kiralama = db.relationship('Kiralama', back_populates='kalemler')
    ekipman = db.relationship('Ekipman', back_populates='kiralama_kalemleri', foreign_keys=[ekipman_id])
    
    # Nakliye aracı ve tedarikçiler
    nakliye_araci = db.relationship('Ekipman', foreign_keys=[nakliye_araci_id], backref='yapilan_nakliyeler')
    harici_tedarikci = db.relationship('Firma', foreign_keys=[harici_ekipman_tedarikci_id])
    nakliye_tedarikci = db.relationship('Firma', foreign_keys=[nakliye_tedarikci_id])

    # Versiyon Ağacı İlişkisi (Self-Referential)
    # Bir kalemin alt revizyonlarını listelemek için
    revizyonlar = db.relationship('KiralamaKalemi', backref=db.backref('ust_kayit', remote_side='KiralamaKalemi.id'))

      
    # Aynı kalem ailesindeki tüm kayıtlar için ortak ID
    chain_id = db.Column(db.Integer, index=True)

    def validate_harici_ekipman(self):
        """
        is_dis_tedarik_ekipman=True ise harici ekipman bilgilerinin doldurulup doldurulmadığını kontrol eder.
        Mevcut kayıtlar NULL olabilir, ama yenileri validation gerektirir.
        """
        if self.is_dis_tedarik_ekipman:
            required_fields = [
                self.harici_ekipman_tipi,
                self.harici_ekipman_marka,
                self.harici_ekipman_model,
                self.harici_ekipman_seri_no
            ]
            if not all(required_fields):
                raise ValueError(
                    "Dış tedarik ekipman seçildiyse şunlar zorunludur: "
                    "tип, marka, model, seri no"
                )

    def __repr__(self):
        status = "AKTİF" if self.is_active else "PASİF/REVİZE"
        return f'<KiralamaKalemi ID:{self.id} Ver:{self.versiyon_no} {status}>'