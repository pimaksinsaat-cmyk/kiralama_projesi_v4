from app.extensions import db
from datetime import date
from decimal import Decimal
from app.araclar.models import Arac


# ==========================================
# 2. NAKLİYE OPERASYONLARI (SEFERLER / ARACILIK)
# ==========================================
class Nakliye(db.Model):
    __tablename__ = 'nakliye'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)

    # --- KİRALAMA BAĞLANTISI (Dirsek Teması İçin) ---
    kiralama_id = db.Column(db.Integer, db.ForeignKey('kiralama.id', ondelete='CASCADE'), nullable=True)
    kiralama = db.relationship('Kiralama', back_populates='nakliyeler')

    # --- Temel Kimlik Bilgileri ---
    # tarih: kayıt tarihi/legacy alan
    tarih = db.Column(db.Date, default=date.today, nullable=False)
    # islem_tarihi: seferin fiilen gerçekleştiği tarih (geçmişe dönük kayıtlar için)
    islem_tarihi = db.Column(db.Date, nullable=True, index=True)
    
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

    @property
    def net_kdv_orani(self):
        """Tevkifat uygulanmış efektif KDV oranı (%). Örn: %20 & 2/10 → %16"""
        kdv = self.kdv_orani or 0
        if not self.tevkifat_orani:
            return kdv
        try:
            pay, payda = map(int, str(self.tevkifat_orani).split('/'))
            return kdv * (payda - pay) / payda
        except (ValueError, ZeroDivisionError):
            return kdv

    def delete(self, soft=True, user_id=None):
        """
        Nakliye'yi siler ve ilişkili HizmetKaydi'yi de soft delete eder.
        Bakiye tutarlılığı ve audit trail için gereklidir.
        """
        # İlişkili HizmetKaydi'yi soft delete et
        if self.cari_hareket:
            self.cari_hareket.delete(soft=True, user_id=user_id)

        if soft:
            self.is_active = False
            db.session.add(self)
        else:
            db.session.delete(self)
        db.session.commit()

    def save(self, commit=True):
        db.session.add(self)
        if commit:
            db.session.commit()
        return self

    def __repr__(self):
        return f'<Nakliye #{self.id} | Tip: {self.nakliye_tipi} | {self.guzergah}>'