from app.extensions import db
from datetime import date
from decimal import Decimal
from app.araclar.models import Arac


# ==========================================
# 2. NAKLİYE OPERASYONLARI (SEFERLER / ARACILIK)
# ==========================================
class Nakliye(db.Model):
    __tablename__ = 'nakliye'

    # --- KİRALAMA BAĞLANTISI (Dirsek Teması İçin) ---
    kiralama_id = db.Column(db.Integer, db.ForeignKey('kiralama.id', ondelete='CASCADE'), nullable=True)
    kiralama = db.relationship('Kiralama', back_populates='nakliyeler')
    
    # --- Temel Kimlik Bilgileri ---
    id = db.Column(db.Integer, primary_key=True)
    tarih = db.Column(db.Date, default=date.today, nullable=False)
    
    # --- Müşteri (Kime Fatura Keseceğiz / Kimin İşini Yapıyoruz) ---
    firma_id = db.Column(db.Integer, db.ForeignKey('firma.id'), nullable=False)
    firma = db.relationship('Firma', foreign_keys=[firma_id], back_populates='nakliyeler')

    # --- OPERASYON TİPİ VE KİM YAPIYOR? (Yeni Aracılık Mantığı) ---
    nakliye_tipi = db.Column(db.String(20), default='oz_mal') # Seçenekler: 'oz_mal' (kendi aracımız) veya 'taseron' (aracılık)
    
    # Eğer işi kendi aracımız yapıyorsa:
    arac_id = db.Column(db.Integer, db.ForeignKey('araclar.id'), nullable=True)
    kendi_aracimiz = db.relationship('Arac', backref='yaptigi_seferler')
    
    # Eğer işi dışarıdan bir nakliyeciye (taşerona) yaptırıyorsak:
    taseron_firma_id = db.Column(db.Integer, db.ForeignKey('firma.id'), nullable=True)
    taseron_firma = db.relationship('Firma', foreign_keys=[taseron_firma_id], backref='taseron_nakliyeleri')

    # --- Operasyonel Bilgiler ---
    guzergah = db.Column(db.String(200), nullable=False)  
    plaka = db.Column(db.String(20), nullable=True) # Taşeronun anlık plakası buraya yazılabilir
    aciklama = db.Column(db.Text, nullable=True)    
    
    # --- Parasal Veriler (Müşteriye Kestiğimiz / Gelir) ---
    tutar = db.Column(db.Numeric(15, 2), nullable=False, default=Decimal('0.00')) 
    kdv_orani = db.Column(db.Integer, default=20) 
    tevkifat_orani = db.Column(db.String(10), nullable=True, default=None)
    toplam_tutar = db.Column(db.Numeric(15, 2), nullable=False, default=Decimal('0.00')) 
    
    # --- TAŞERON MALİYETİ (Dışarıya Yaptırıyorsak Bizim Giderimiz) ---
    taseron_maliyet = db.Column(db.Numeric(15, 2), nullable=True, default=Decimal('0.00'))
    
    # --- Durum ve Arşiv Kontrolleri ---
    cari_islendi_mi = db.Column(db.Boolean, default=False, index=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    cari_hareket = db.relationship(
        'HizmetKaydi', 
        backref='ilgili_nakliye', 
        cascade='all, delete-orphan', 
        uselist=False
    )

    def hesapla_ve_guncelle(self):
        """ Sözleşme tutarını kaydeder. KDV fatura kesilirken ayrıca hesaplanacak. """
        self.toplam_tutar = self.tutar or Decimal('0.00')
        return self.toplam_tutar

    @property
    def tahmini_kar(self):
        """ Eğer iş taşerona verildiyse, aradaki komisyon/kâr farkını hesaplar """
        if self.nakliye_tipi == 'taseron' and self.taseron_maliyet:
            return self.tutar - self.taseron_maliyet
        return self.tutar # Kendi aracımızsa gelirin tamamı brüt kârdır (yakıt hariç)

    def __repr__(self):
        return f'<Nakliye #{self.id} | Tip: {self.nakliye_tipi} | {self.guzergah}>'