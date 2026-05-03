from datetime import date
from decimal import Decimal

from sqlalchemy.orm import validates

from app.extensions import db
from app.models.base_model import BaseModel


TEKLIF_DURUMLARI = ('taslak', 'gonderildi', 'kabul_edildi', 'reddedildi', 'iptal')
TEKLIF_FIYAT_TIPLERI = ('gunluk', 'aylik')
TEKLIF_NAKLIYE_YONLERI = ('tek_yon', 'cift_yon')


class Teklif(BaseModel):
    __tablename__ = 'teklif'

    teklif_no = db.Column(db.String(100), nullable=False, unique=True, index=True)
    teklif_tarihi = db.Column(db.Date, nullable=False, default=date.today)
    gecerlilik_tarihi = db.Column(db.Date, nullable=True)
    durum = db.Column(db.String(30), nullable=False, default='taslak', index=True)
    kdv_orani = db.Column(db.Integer, nullable=False, default=20)
    notlar = db.Column(db.Text, nullable=True)

    firma_musteri_id = db.Column(db.Integer, db.ForeignKey('firma.id'), nullable=True, index=True)
    kiralama_id = db.Column(db.Integer, db.ForeignKey('kiralama.id'), nullable=True, index=True)

    aday_firma_adi = db.Column(db.String(150), nullable=True, index=True)
    aday_yetkili_adi = db.Column(db.String(100), nullable=True)
    aday_telefon = db.Column(db.String(20), nullable=True)
    aday_eposta = db.Column(db.String(120), nullable=True)
    aday_adres = db.Column(db.Text, nullable=True)
    aday_not = db.Column(db.Text, nullable=True)

    firma_musteri = db.relationship('Firma', back_populates='teklifler', foreign_keys=[firma_musteri_id])
    kiralama = db.relationship('Kiralama', backref=db.backref('kaynak_teklifler', lazy='dynamic'), foreign_keys=[kiralama_id])
    kalemler = db.relationship(
        'TeklifKalemi',
        back_populates='teklif',
        cascade='all, delete-orphan',
        order_by='TeklifKalemi.id',
    )

    @property
    def musteri_adi(self):
        if self.firma_musteri:
            return self.firma_musteri.firma_adi
        return self.aday_firma_adi or ''

    @property
    def ara_toplam(self):
        return sum((kalem.satir_toplami for kalem in self.kalemler), Decimal('0.00'))

    @property
    def kdv_tutari(self):
        oran = Decimal(str(self.kdv_orani or 0)) / Decimal('100')
        return self.ara_toplam * oran

    @property
    def genel_toplam(self):
        return self.ara_toplam + self.kdv_tutari

    @validates('durum')
    def validate_durum(self, key, value):
        if value not in TEKLIF_DURUMLARI:
            raise ValueError('Gecersiz teklif durumu')
        return value

    def __repr__(self):
        return f'<Teklif {self.teklif_no}>'


class TeklifKalemi(BaseModel):
    __tablename__ = 'teklif_kalemi'

    teklif_id = db.Column(db.Integer, db.ForeignKey('teklif.id'), nullable=False, index=True)
    ekipman_id = db.Column(db.Integer, db.ForeignKey('ekipman.id'), nullable=True, index=True)

    makine_tipi = db.Column(db.String(100), nullable=True)
    marka_model = db.Column(db.String(150), nullable=True)
    calisma_yuksekligi = db.Column(db.Numeric(10, 2), nullable=True)
    kaldirma_kapasitesi = db.Column(db.Integer, nullable=True)
    adet = db.Column(db.Integer, nullable=False, default=1)
    calisacagi_konum = db.Column(db.Text, nullable=True)
    baslangic_tarihi = db.Column(db.Date, nullable=True)
    bitis_tarihi = db.Column(db.Date, nullable=True)
    fiyat_tipi = db.Column(db.String(20), nullable=False, default='gunluk')
    gunluk_fiyat = db.Column(db.Numeric(15, 2), nullable=False, default=0)
    nakliye_fiyati = db.Column(db.Numeric(15, 2), nullable=False, default=0)
    nakliye_yon = db.Column(db.String(20), nullable=False, default='tek_yon')
    satir_notu = db.Column(db.Text, nullable=True)

    teklif = db.relationship('Teklif', back_populates='kalemler')
    ekipman = db.relationship('Ekipman', back_populates='teklif_kalemleri', foreign_keys=[ekipman_id])

    @property
    def gun_sayisi(self):
        if self.baslangic_tarihi and self.bitis_tarihi and self.bitis_tarihi >= self.baslangic_tarihi:
            return (self.bitis_tarihi - self.baslangic_tarihi).days + 1
        return 1

    @property
    def satir_toplami(self):
        adet = Decimal(str(self.adet or 1))
        gun = Decimal(str(self.gun_sayisi))
        birim_fiyat = Decimal(str(self.gunluk_fiyat or 0))
        nakliye = Decimal(str(self.nakliye_fiyati or 0))
        nakliye_toplam = nakliye * (Decimal('2') if self.nakliye_yon == 'cift_yon' else Decimal('1'))
        if self.fiyat_tipi == 'aylik':
            return (adet * (gun / Decimal('30')) * birim_fiyat) + nakliye_toplam
        return (adet * gun * birim_fiyat) + nakliye_toplam

    @validates('adet')
    def validate_adet(self, key, value):
        value = int(value or 1)
        if value < 1:
            raise ValueError('Adet 1 veya daha buyuk olmalidir')
        return value

    @validates('gunluk_fiyat', 'nakliye_fiyati')
    def validate_money(self, key, value):
        amount = Decimal(str(value or 0))
        if amount < 0:
            raise ValueError('Fiyat negatif olamaz')
        return amount

    @validates('fiyat_tipi')
    def validate_fiyat_tipi(self, key, value):
        value = value or 'gunluk'
        if value not in TEKLIF_FIYAT_TIPLERI:
            raise ValueError('Gecersiz fiyat tipi')
        return value

    @validates('nakliye_yon')
    def validate_nakliye_yon(self, key, value):
        value = value or 'tek_yon'
        if value not in TEKLIF_NAKLIYE_YONLERI:
            raise ValueError('Gecersiz nakliye yonu')
        return value

    def __repr__(self):
        return f'<TeklifKalemi {self.teklif_id}>'
