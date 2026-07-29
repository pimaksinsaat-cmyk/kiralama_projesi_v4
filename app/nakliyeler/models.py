from app.extensions import db
from app.models.base_model import BaseModel
from datetime import date
from decimal import Decimal


# ==========================================
# 2. NAKLİYE OPERASYONLARI (SEFERLER / ARACILIK)
# ==========================================
class Nakliye(BaseModel):
    __tablename__ = 'nakliye'

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
    nakliye_tipi = db.Column(db.String(20), default='oz_mal')  # 'oz_mal' | 'taseron'

    # Eğer işi kendi aracımız yapıyorsa:
    arac_id = db.Column(db.Integer, db.ForeignKey('araclar.id'), nullable=True)
    kendi_aracimiz = db.relationship('Arac', backref='yaptigi_seferler')

    # Eğer işi dışarıdan bir nakliyeciye (taşerona) yaptırıyorsak:
    taseron_firma_id = db.Column(db.Integer, db.ForeignKey('firma.id'), nullable=True)
    taseron_firma = db.relationship('Firma', foreign_keys=[taseron_firma_id], backref='taseron_nakliyeleri')

    # --- Operasyonel Bilgiler ---
    guzergah = db.Column(db.String(200), nullable=False)
    plaka = db.Column(db.String(20), nullable=True)
    aciklama = db.Column(db.Text, nullable=True)

    # --- Parasal Veriler (Müşteriye Kestiğimiz / Gelir) ---
    tutar = db.Column(db.Numeric(15, 2), nullable=False, default=Decimal('0.00'))
    kdv_orani = db.Column(db.Integer, default=20)
    tevkifat_orani = db.Column(db.String(10), nullable=True, default=None)
    toplam_tutar = db.Column(db.Numeric(15, 2), nullable=False, default=Decimal('0.00'))

    # --- TAŞERON MALİYETİ ---
    taseron_maliyet = db.Column(db.Numeric(15, 2), nullable=True, default=Decimal('0.00'))
    taseron_kdv_orani = db.Column(db.Integer, nullable=True, default=20)

    # --- Durum ve Arşiv Kontrolleri ---
    cari_islendi_mi = db.Column(db.Boolean, default=False, index=True)

    hizmet_kayitlari = db.relationship(
        'HizmetKaydi',
        backref='ilgili_nakliye',
        cascade='all, delete-orphan',
    )

    @classmethod
    def active_filters(cls):
        """Operasyonel görünürlük: aktif ve soft-delete edilmemiş."""
        return (cls.is_active.is_(True), cls.is_deleted.is_(False))

    @classmethod
    def active_query(cls):
        return cls.query.filter(*cls.active_filters())

    @property
    def cari_hareket(self):
        for hizmet in self.hizmet_kayitlari:
            if hizmet.yon == 'giden':
                return hizmet
        return self.hizmet_kayitlari[0] if self.hizmet_kayitlari else None

    def hesapla_ve_guncelle(self):
        """ Sözleşme tutarını kaydeder. KDV fatura kesilirken ayrıca hesaplanacak. """
        self.toplam_tutar = self.tutar or Decimal('0.00')
        return self.toplam_tutar

    @property
    def tahmini_kar(self):
        """ Eğer iş taşerona verildiyse, aradaki komisyon/kâr farkını hesaplar """
        if self.nakliye_tipi == 'taseron' and self.taseron_maliyet:
            return self.tutar - self.taseron_maliyet
        return self.tutar

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

    def __repr__(self):
        return f'<Nakliye #{self.id} | Tip: {self.nakliye_tipi} | {self.guzergah}>'
