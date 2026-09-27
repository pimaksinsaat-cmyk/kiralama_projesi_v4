from app.extensions import db
from app.models.base_model import BaseModel
from app.araclar.models import Arac
from datetime import date
from decimal import Decimal
import uuid
from sqlalchemy import func


# ==========================================
# 2. NAKLİYE OPERASYONLARI (SEFERLER / ARACILIK)
# ==========================================
class Nakliye(BaseModel):
    __tablename__ = 'nakliye'

    # --- KİRALAMA BAĞLANTISI (Dirsek Teması İçin) ---
    kiralama_id = db.Column(db.Integer, db.ForeignKey('kiralama.id', ondelete='CASCADE'), nullable=True)
    kiralama = db.relationship('Kiralama', back_populates='nakliyeler')

    # Yeni sefer modeli: kiralamaya bağlı seferlerde zorunlu, bağımsız
    # legacy nakliyelerde nullable bırakılır.
    yon = db.Column(db.String(10), nullable=True, index=True)  # gidis / donus
    cift_yon = db.Column(db.Boolean, nullable=False, default=False)
    sefer_uuid = db.Column(db.String(36), nullable=True, default=lambda: str(uuid.uuid4()), index=True)

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
    guzergah = db.Column(db.String(500), nullable=False)
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
    taseron_tevkifat_orani = db.Column(db.String(10), nullable=True, default=None)

    # --- Durum ve Arşiv Kontrolleri ---
    cari_islendi_mi = db.Column(db.Boolean, default=False, index=True)

    # Geçmiş kiralama nakliyelerinin güvenli sefer dönüşüm izi. Bu alanlar
    # yalnız dönüşüm aracı tarafından yazılır; normal form akışının kaynağı
    # değildir.
    gecis_kaynagi = db.Column(db.String(40), nullable=True, index=True)
    gecis_eksik_bilgiler = db.Column(db.Text, nullable=True)

    hizmet_kayitlari = db.relationship(
        'HizmetKaydi',
        backref='ilgili_nakliye',
        cascade='all, delete-orphan',
    )
    dagitimlar = db.relationship(
        'NakliyeDagitim',
        back_populates='nakliye',
        cascade='all, delete-orphan',
        order_by='NakliyeDagitim.id',
    )

    @classmethod
    def active_filters(cls):
        """Operasyonel görünürlük: aktif ve soft-delete edilmemiş."""
        return (cls.is_active.is_(True), cls.is_deleted.is_(False))

    @classmethod
    def active_query(cls):
        return cls.query.filter(*cls.active_filters())

    @classmethod
    def etkin_plaka_expression(cls):
        return func.coalesce(
            func.nullif(func.trim(cls.plaka), ''),
            func.nullif(func.trim(Arac.plaka), ''),
        )

    @property
    def etkin_plaka(self):
        manual = (self.plaka or '').strip()
        if manual:
            return manual
        arac = getattr(self, 'kendi_aracimiz', None)
        return (getattr(arac, 'plaka', None) or '').strip() or None

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


class NakliyeDagitim(BaseModel):
    """Bir fiziksel nakliye seferinin kiralama kalemine dağıtımı."""

    __tablename__ = 'nakliye_dagitim'

    nakliye_id = db.Column(
        db.Integer,
        db.ForeignKey('nakliye.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    kiralama_kalemi_id = db.Column(
        db.Integer,
        db.ForeignKey('kiralama_kalemi.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    tutar = db.Column(db.Numeric(15, 2), nullable=False, default=Decimal('0.00'))

    nakliye = db.relationship('Nakliye', back_populates='dagitimlar')
    kiralama_kalemi = db.relationship('KiralamaKalemi', back_populates='nakliye_dagitimlari')

    __table_args__ = (
        db.CheckConstraint('tutar >= 0', name='ck_nakliye_dagitim_tutar_nonnegative'),
    )

    def __repr__(self):
        return f'<NakliyeDagitim sefer={self.nakliye_id} kalem={self.kiralama_kalemi_id} tutar={self.tutar}>'


class NakliyeGecisIslemi(BaseModel):
    """Toplu legacy -> sefer dönüşümünün kalıcı denetim başlığı."""

    __tablename__ = 'nakliye_gecis_islemi'

    run_uuid = db.Column(db.String(36), nullable=False, unique=True, index=True)
    durum = db.Column(db.String(40), nullable=False, default='hazirlaniyor', index=True)
    kaynak_snapshot_sha256 = db.Column(db.String(64), nullable=False)
    once_firma_sayisi = db.Column(db.Integer, nullable=False, default=0)
    once_hareket_sayisi = db.Column(db.Integer, nullable=False, default=0)
    donusturulen_kiralama_sayisi = db.Column(db.Integer, nullable=False, default=0)
    donusturulen_sefer_sayisi = db.Column(db.Integer, nullable=False, default=0)
    hata = db.Column(db.Text, nullable=True)
    rapor_json = db.Column(db.Text, nullable=True)

    kayitlar = db.relationship(
        'NakliyeGecisKaydi', back_populates='islem', cascade='all, delete-orphan'
    )


class NakliyeGecisKaydi(BaseModel):
    """Dönüşümde kurulan her sefer/dağıtım/cari bağlantısının izi."""

    __tablename__ = 'nakliye_gecis_kaydi'

    islem_id = db.Column(
        db.Integer,
        db.ForeignKey('nakliye_gecis_islemi.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    kiralama_id = db.Column(db.Integer, nullable=False, index=True)
    nakliye_id = db.Column(db.Integer, nullable=True, index=True)
    nakliye_dagitim_id = db.Column(db.Integer, nullable=True, index=True)
    hizmet_kaydi_id = db.Column(db.Integer, nullable=True, index=True)
    durum = db.Column(db.String(20), nullable=False, default='donusturuldu')
    once_json = db.Column(db.Text, nullable=True)
    sonra_json = db.Column(db.Text, nullable=True)
    notlar = db.Column(db.Text, nullable=True)

    islem = db.relationship('NakliyeGecisIslemi', back_populates='kayitlar')
