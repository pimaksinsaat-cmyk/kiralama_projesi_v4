from app.extensions import db
from datetime import datetime, timezone
from sqlalchemy import func
from app.models.base_model import BaseModel


# 2. KASA (Nakit / Banka Hesapları / POS)
class Kasa(BaseModel):
    __tablename__ = 'kasa'
    
    kasa_adi = db.Column(db.String(100), nullable=False)
    tipi = db.Column(db.String(20), nullable=False, default='nakit') # nakit, banka, pos
    para_birimi = db.Column(db.String(3), nullable=False, default='TRY')
    banka_sube_adi = db.Column(db.String(120), nullable=True)
    sube_id = db.Column(db.Integer, db.ForeignKey('subeler.id'), nullable=True)
    
    # Bakiye (Performans için statik tutulur, Service katmanı tarafından güncellenir)
    bakiye = db.Column(db.Numeric(15, 2), nullable=False, default=0)
    
    # İlişkiler
    sube = db.relationship('Sube', lazy='joined')
    odemeler = db.relationship('Odeme', back_populates='kasa', lazy='dynamic')
    
    @property
    def hesaplanan_bakiye(self):
        """
        Kasa hareketlerinden (Odeme) bakiye doğrulaması yapar.
        Senkronizasyon (sync-balances) işlemleri için kullanılır.
        """
        giris = db.session.query(func.sum(Odeme.tutar)).filter(
            Odeme.kasa_id == self.id, 
            Odeme.yon == 'tahsilat', 
            Odeme.is_deleted == False
        ).scalar() or 0
        cikis = db.session.query(func.sum(Odeme.tutar)).filter(
            Odeme.kasa_id == self.id, 
            Odeme.yon == 'odeme', 
            Odeme.is_deleted == False
        ).scalar() or 0
        return giris - cikis
    
    def __repr__(self):
        return f'<Kasa {self.kasa_adi}>'




# 6. ODEME (Para Transferi: Tahsilat / Tediye)
class Odeme(BaseModel):
    """
    Cari Hareket: Kasaya giren veya çıkan parayı temsil eder.
    """
    __tablename__ = 'odeme'
    
    __table_args__ = (
        db.CheckConstraint("yon IN ('tahsilat', 'odeme')", name='check_odeme_yon'),
    )
    
    firma_musteri_id = db.Column(db.Integer, db.ForeignKey('firma.id'), nullable=False)
    kasa_id = db.Column(db.Integer, db.ForeignKey('kasa.id'), nullable=True)
    
    tarih = db.Column(db.Date, nullable=False, default=lambda: datetime.now(timezone.utc).date())
    tutar = db.Column(db.Numeric(15, 2), nullable=False, default=0)
    
    # 'tahsilat' = Kasaya Para Girişi (+) / Müşteri Bakiyesi Azalır (-)
    # 'odeme'    = Kasadan Para Çıkışı (-) / Tedarikçiye Olan Borç Azalır (+)
    yon = db.Column(db.String(20), default='tahsilat', nullable=False) 
    
    fatura_no = db.Column(db.String(50), nullable=True)
    vade_tarihi = db.Column(db.Date, nullable=True)
    aciklama = db.Column(db.String(250), nullable=True)

    # İlişkiler
    firma_musteri = db.relationship('Firma', back_populates='odemeler', foreign_keys=[firma_musteri_id])
    kasa = db.relationship('Kasa', back_populates='odemeler')
    
    def __repr__(self):
        return f'<Odeme {self.tutar} ({self.yon})>'


# 7. HIZMET KAYDI (Ticari Hareket: Gelir / Gider Faturası)
class HizmetKaydi(BaseModel):
    """
    Cari Hareket: Alınan veya verilen hizmeti temsil eder.
    """
    __tablename__ = 'hizmet_kaydi'
    
    __table_args__ = (
        db.CheckConstraint("yon IN ('gelen', 'giden')", name='check_hizmet_yon'),
    )
    
    firma_id = db.Column(db.Integer, db.ForeignKey('firma.id'), nullable=False)
    nakliye_id = db.Column(
        db.Integer, 
        db.ForeignKey('nakliye.id', ondelete='CASCADE'), 
        nullable=True
    )
    ozel_id = db.Column(db.Integer, nullable=True)
    
    tarih = db.Column(db.Date, nullable=False, default=lambda: datetime.now(timezone.utc).date())
    tutar = db.Column(db.Numeric(15, 2), nullable=False, default=0)
    
    # 'giden' = Satış Faturası (Gelir) -> Müşteri Borçlanır (+)
    # 'gelen' = Alış Faturası (Gider) -> Biz Tedarikçiye Borçlanırız (-)
    yon = db.Column(db.String(20), nullable=False, default='giden') 
    
    fatura_no = db.Column(db.String(50), nullable=True)
    vade_tarihi = db.Column(db.Date, nullable=True)
    aciklama = db.Column(db.String(250), nullable=True)


    # KDV Oranı (isteğe bağlı, performans için)
    kdv_orani = db.Column(db.Integer, nullable=True, default=None)

    # Kiralama alış KDV oranı (dış tedarik işlemleri için)
    kiralama_alis_kdv = db.Column(db.Integer, nullable=True, default=None)

    # Nakliye alış KDV oranı (dış tedarik işlemleri için)
    nakliye_alis_kdv = db.Column(db.Integer, nullable=True, default=None)


    # İlişkiler
    firma = db.relationship('Firma', back_populates='hizmet_kayitlari', foreign_keys=[firma_id])
    
    def __repr__(self):
        return f'<Hizmet {self.tutar} ({self.yon})>'


# 8. CARI HAREKET (Bekleyen Bakiye için Ana Defter)
class CariHareket(BaseModel):
    """
    Bekleyen bakiye (açık bakiye) takibi için normalize cari hareket tablosu.
    Bu model mevcut Odeme/HizmetKaydi akışını bozmaz; kademeli geçiş için eklenmiştir.
    """
    __tablename__ = 'cari_hareket'

    __table_args__ = (
        db.CheckConstraint("yon IN ('gelen', 'giden')", name='check_cari_hareket_yon'),
        db.CheckConstraint("durum IN ('acik', 'kapali', 'iptal')", name='check_cari_hareket_durum'),
    )

    firma_id = db.Column(db.Integer, db.ForeignKey('firma.id'), nullable=False, index=True)

    tarih = db.Column(db.Date, nullable=False, default=lambda: datetime.now(timezone.utc).date(), index=True)
    vade_tarihi = db.Column(db.Date, nullable=True, index=True)
    para_birimi = db.Column(db.String(3), nullable=False, default='TRY')

    # Mevcut cari modelleriyle uyumlu yön yapısı
    # giden: firmanın borcu artar, gelen: firmanın borcu azalır
    yon = db.Column(db.String(20), nullable=False, default='giden', index=True)
    tutar = db.Column(db.Numeric(15, 2), nullable=False, default=0)
    kalan_tutar = db.Column(db.Numeric(15, 2), nullable=False, default=0)
    durum = db.Column(db.String(10), nullable=False, default='acik', index=True)

    # Kaynak izleme (kiralama, nakliye, hizmet, ödeme...)
    kaynak_modul = db.Column(db.String(50), nullable=True, index=True)
    kaynak_id = db.Column(db.Integer, nullable=True, index=True)
    ozel_id = db.Column(db.Integer, nullable=True)

    belge_no = db.Column(db.String(50), nullable=True, index=True)
    aciklama = db.Column(db.String(250), nullable=True)

    # İptal/düzeltme takibi
    referans_hareket_id = db.Column(db.Integer, db.ForeignKey('cari_hareket.id'), nullable=True)

    # İlişkiler
    firma = db.relationship('Firma', back_populates='cari_hareketler', foreign_keys=[firma_id])
    referans_hareket = db.relationship('CariHareket', remote_side='CariHareket.id', backref='duzeltme_hareketleri')

    @property
    def bekleyen_tutar(self):
        return float(self.kalan_tutar or 0)

    def __repr__(self):
        return f'<CariHareket {self.id} {self.kaynak_tipi}:{self.kaynak_id} {self.yon} {self.tutar}>'


# 9. CARI MAHSUP (Borç/Alacak Eşleştirme)
class CariMahsup(BaseModel):
    """
    Bekleyen bakiyeyi kapatmak için iki cari hareketin eşleştirilmesini tutar.
    Örn: tahsilat satırı ile kiralama borç satırının kısmi/tam kapanması.
    """
    __tablename__ = 'cari_mahsup'

    borc_hareket_id = db.Column(db.Integer, db.ForeignKey('cari_hareket.id', ondelete='CASCADE'), nullable=False, index=True)
    alacak_hareket_id = db.Column(db.Integer, db.ForeignKey('cari_hareket.id', ondelete='CASCADE'), nullable=False, index=True)

    tarih = db.Column(db.Date, nullable=False, default=lambda: datetime.now(timezone.utc).date(), index=True)
    tutar = db.Column(db.Numeric(15, 2), nullable=False, default=0)
    aciklama = db.Column(db.String(250), nullable=True)

    borc_hareket = db.relationship('CariHareket', foreign_keys=[borc_hareket_id], backref='borc_mahsuplari')
    alacak_hareket = db.relationship('CariHareket', foreign_keys=[alacak_hareket_id], backref='alacak_mahsuplari')

    def __repr__(self):
        return f'<CariMahsup {self.id} borc={self.borc_hareket_id} alacak={self.alacak_hareket_id}>'