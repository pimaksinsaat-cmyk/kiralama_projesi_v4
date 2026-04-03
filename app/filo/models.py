from app.extensions import db
from app.models.base_model import BaseModel
from datetime import date

# 3. EKIPMAN (Filo)
class Ekipman(BaseModel):
    __tablename__ = 'ekipman'
    
    kod = db.Column(db.String(100), unique=True, nullable=False, index=True)
    yakit = db.Column(db.String(50), nullable=False, default='')
    tipi = db.Column(db.String(100), nullable=False, default='')
    marka = db.Column(db.String(100), nullable=False)
    model = db.Column(db.String(100), nullable=True, default='') 
    seri_no = db.Column(db.String(100), nullable=False, index=True) 
    calisma_yuksekligi = db.Column(db.Integer, nullable=False) # Metre (veya cm)
    kaldirma_kapasitesi = db.Column(db.Integer, nullable=False) # Kg
    
    # --- YENİ EKLENEN TEKNİK VE FİLTRE ALANLARI ---
    agirlik = db.Column(db.Float, nullable=True) # Makine ağırlığı (kg)
    ic_mekan_uygun = db.Column(db.Boolean, default=False, nullable=False)
    arazi_tipi_uygun = db.Column(db.Boolean, default=False, nullable=False)
    genislik = db.Column(db.Float, nullable=True) # Maksimum genişlik (metre)
    uzunluk = db.Column(db.Float, nullable=True) # Maksimum uzunluk (metre)
    kapali_yukseklik = db.Column(db.Float, nullable=True) # Kapı/tavan geçişleri için kapalı yükseklik (metre)
    # ---------------------------------------------
    
    uretim_yili = db.Column(db.Integer, nullable=False)
    calisma_durumu = db.Column(db.String(50), nullable=False, default='bosta') 
    giris_maliyeti = db.Column(db.Numeric(15, 2), nullable=True, default=0.0)
    para_birimi = db.Column(db.String(3), nullable=False, default='TRY')
    
    # --- SATINALMA DÖVİZ KURLARI (Finansal Analiz için) ---
    temin_doviz_kuru_usd = db.Column(db.Numeric(10, 4), nullable=True, default=0.0)
    temin_doviz_kuru_eur = db.Column(db.Numeric(10, 4), nullable=True, default=0.0) 
    
    sube_id = db.Column(db.Integer, db.ForeignKey('subeler.id'), nullable=True)
    sube = db.relationship('Sube', back_populates='ekipmanlar')

    firma_tedarikci_id = db.Column(db.Integer, db.ForeignKey('firma.id'), nullable=True)
    firma_tedarikci = db.relationship('Firma', back_populates='tedarik_edilen_ekipmanlar', foreign_keys=[firma_tedarikci_id])
    
    # HATA DÜZELTME: KiralamaKalemi'ndeki iki farklı FK (ekipman_id ve nakliye_araci_id) 
    # arasındaki belirsizliği gidermek için foreign_keys argümanını ekledik.
    kiralama_kalemleri = db.relationship(
        'KiralamaKalemi', 
        back_populates='ekipman', 
        foreign_keys='KiralamaKalemi.ekipman_id',
        cascade="all, delete-orphan"
    )
    
    bakim_kayitlari = db.relationship('BakimKaydi', back_populates='ekipman', cascade="all, delete-orphan")

    __table_args__ = (db.UniqueConstraint('firma_tedarikci_id', 'seri_no', name='_tedarikci_seri_no_uc'),)

    # Bu ekipmanın 'sahadan çekildiği' (eski makine olduğu) durumlar
    swap_cikis_kayitlari = db.relationship('MakineDegisim', foreign_keys='MakineDegisim.eski_ekipman_id', back_populates='eski_ekipman', lazy='dynamic')
    swap_giris_kayitlari = db.relationship('MakineDegisim', foreign_keys='MakineDegisim.yeni_ekipman_id', back_populates='yeni_ekipman', lazy='dynamic')

    def __repr__(self): 
        return f'<Ekipman {self.kod}>'


# 10. BAKIM KAYDI (Servis)
class BakimKaydi(BaseModel):
    __tablename__ = 'bakim_kaydi'
    
    ekipman_id = db.Column(db.Integer, db.ForeignKey('ekipman.id'), nullable=False)
    tarih = db.Column(db.Date, nullable=False, default=date.today)
    aciklama = db.Column(db.String(500), nullable=True) 
    calisma_saati = db.Column(db.Integer, nullable=True) 
    
    ekipman = db.relationship('Ekipman', back_populates='bakim_kayitlari')
    kullanilan_parcalar = db.relationship('KullanilanParca', back_populates='bakim_kaydi', cascade="all, delete-orphan")
    
    def __repr__(self): 
        return f'<Bakim {self.ekipman_id}>'


# 11. KULLANILAN PARCA (Servis Detayı)
class KullanilanParca(BaseModel):
    __tablename__ = 'kullanilan_parca'
    
    bakim_kaydi_id = db.Column(db.Integer, db.ForeignKey('bakim_kaydi.id'), nullable=False)
    stok_karti_id = db.Column(db.Integer, db.ForeignKey('stok_karti.id'), nullable=False)
    kullanilan_adet = db.Column(db.Integer, nullable=False, default=1)
    
    bakim_kaydi = db.relationship('BakimKaydi', back_populates='kullanilan_parcalar')
    stok_karti = db.relationship('StokKarti', back_populates='kullanim_kayitlari')
    
    def __repr__(self): 
        return f'<Kullanim {self.kullanilan_adet}>'


# 8. STOK KARTI
class StokKarti(BaseModel):
    __tablename__ = 'stok_karti'
    
    parca_kodu = db.Column(db.String(100), unique=True, nullable=False, index=True)
    parca_adi = db.Column(db.String(250), nullable=False)
    mevcut_stok = db.Column(db.Integer, nullable=False, default=0)
    varsayilan_tedarikci_id = db.Column(db.Integer, db.ForeignKey('firma.id'), nullable=True)
    
    varsayilan_tedarikci = db.relationship('Firma', back_populates='tedarik_edilen_parcalar', foreign_keys=[varsayilan_tedarikci_id])
    hareketler = db.relationship('StokHareket', back_populates='stok_karti', cascade="all, delete-orphan")
    kullanim_kayitlari = db.relationship('KullanilanParca', back_populates='stok_karti')
    
    def __repr__(self): 
        return f'<Stok {self.parca_kodu}>'


# 9. STOK HAREKET (Yeni - Giriş/Çıkış)
class StokHareket(BaseModel):
    __tablename__ = 'stok_hareket'
    
    stok_karti_id = db.Column(db.Integer, db.ForeignKey('stok_karti.id'), nullable=False)
    firma_id = db.Column(db.Integer, db.ForeignKey('firma.id'), nullable=True) 
    tarih = db.Column(db.Date, nullable=False, default=date.today)
    adet = db.Column(db.Integer, nullable=False) 
    birim_fiyat = db.Column(db.Numeric(15, 2), nullable=False, default=0.0)
    hareket_tipi = db.Column(db.String(20), nullable=False, default='giris')
    fatura_no = db.Column(db.String(50), nullable=True)
    aciklama = db.Column(db.String(250), nullable=True)

    stok_karti = db.relationship('StokKarti', back_populates='hareketler')
    firma = db.relationship('Firma', back_populates='stok_hareketleri')
    
    def __repr__(self): 
        return f'<StokHareket {self.adet}>'