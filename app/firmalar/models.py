from app.extensions import db
from datetime import date
from sqlalchemy import func
from app.models.base_model import BaseModel

class Firma(BaseModel):
    """
    Sistemin ana Cari (Ledger) ve Firma modeli. 
    Tüm modüller (Stok, Kiralama, Nakliye, Cari) bu modele bağlıdır.
    """
    __tablename__ = 'firma'
    
    # --- Kimlik Bilgileri ---
    firma_adi = db.Column(db.String(150), nullable=False, index=True)
    yetkili_adi = db.Column(db.String(100), nullable=False)
    telefon = db.Column(db.String(20), nullable=True)
    eposta = db.Column(db.String(120), nullable=True, index=True)
    iletisim_bilgileri = db.Column(db.Text, nullable=False)

    # --- GIB / UBL Taraf Alanları ---
    tckn = db.Column(db.String(11), nullable=True, index=True)
    mersis_no = db.Column(db.String(16), nullable=True)
    ticaret_sicil_no = db.Column(db.String(50), nullable=True)

    adres_satiri_1 = db.Column(db.String(250), nullable=True)
    adres_satiri_2 = db.Column(db.String(250), nullable=True)
    ilce = db.Column(db.String(100), nullable=True)
    il = db.Column(db.String(100), nullable=True)
    posta_kodu = db.Column(db.String(20), nullable=True)
    ulke = db.Column(db.String(100), nullable=False, default='Turkiye')
    ulke_kodu = db.Column(db.String(2), nullable=False, default='TR')

    web_sitesi = db.Column(db.String(200), nullable=True)
    etiket_uuid = db.Column(db.String(120), nullable=True, index=True)  # e-Fatura posta kutusu etiketi
    is_efatura_mukellefi = db.Column(db.Boolean, default=False, nullable=False)

    vergi_dairesi = db.Column(db.String(100), nullable=False)
    vergi_no = db.Column(db.String(50), unique=True, nullable=False, index=True)
    
    # --- Rol ve Durum ---
    is_musteri = db.Column(db.Boolean, default=True, nullable=False, index=True)
    is_tedarikci = db.Column(db.Boolean, default=False, nullable=False, index=True)
    bakiye = db.Column(db.Numeric(15, 2), default=0, nullable=False)

    # --- Sözleşme ve Operasyon ---
    sozlesme_no = db.Column(db.String(50), unique=False, nullable=True)
    sozlesme_rev_no = db.Column(db.Integer, default=0, nullable=True)
    sozlesme_tarihi = db.Column(db.Date, nullable=True, default=date.today)
    bulut_klasor_adi = db.Column(db.String(100), unique=True, nullable=True)

    # --- Denetim Alanları ---
    imza_yetkisi_kontrol_edildi = db.Column(db.Boolean, default=False, nullable=False)
    imza_yetkisi_kontrol_tarihi = db.Column(db.DateTime, nullable=True)
    imza_yetkisi_kontrol_eden_id = db.Column(db.Integer, nullable=True)
    imza_arsiv_notu = db.Column(db.String(255), nullable=True)
    # --- YENİ EKLENEN KISIM: Sadece Silinmemiş Hareketleri Getiren Özellikler ---
    @property
    def aktif_odemeler(self):
        """Silinmemiş ödeme ve tahsilatları tarihe göre yeninden eskiye sıralı getirir."""
        from app.cari.models import Odeme
        return self.odemeler.filter(Odeme.is_deleted == False).order_by(Odeme.tarih.desc()).all()

    @property
    def aktif_hizmetler(self):
        """Silinmemiş fatura ve hizmet kayıtlarını tarihe göre yeninden eskiye sıralı getirir."""
        from app.cari.models import HizmetKaydi
        return self.hizmet_kayitlari.filter(HizmetKaydi.is_deleted == False).order_by(HizmetKaydi.tarih.desc()).all()
    # -----------------------------------------------------------------------------

    # --- Ledger (Muhasebe) Hesaplama ---
    @property
    def bakiye_ozeti(self):
        """
        Hareketlerden (Odeme ve HizmetKaydi) anlık borç/alacak raporu üretir.
        KDV dahil toplamları da içerir.

        'Kiralama Bekleyen Bakiye' ve 'Dış Kiralama' HizmetKaydi kayıtları için
        DB'deki sabit tutar yerine bugünkü tahakkuk canlı hesaplanır. Böylece
        ileri tarihli kontratların tutarı da gün geçtikçe doğru yansıtılır.
        """
        from app.cari.models import Odeme, HizmetKaydi
        from decimal import Decimal
        from app.services.kiralama_services import KiralamaService

        h_borc        = Decimal('0.00')
        h_alacak      = Decimal('0.00')
        h_borc_kdvli  = Decimal('0.00')
        h_alacak_kdvli = Decimal('0.00')

        kayitlar = HizmetKaydi.query.filter(
            HizmetKaydi.firma_id == self.id,
            HizmetKaydi.is_deleted == False
        ).all()

        for h in kayitlar:
            tutar = KiralamaService.hesapla_hizmet_kaydi_canli_tutari(h)
            # KDV oranı: nakliye_alis_kdv → kiralama_alis_kdv → kdv_orani öncelik sırası
            kdv_oran = (
                h.nakliye_alis_kdv if h.nakliye_alis_kdv is not None
                else h.kiralama_alis_kdv if h.kiralama_alis_kdv is not None
                else h.kdv_orani
            )
            kdv   = Decimal(str(kdv_oran or 0))
            tutar_kdvli = tutar * (Decimal('1.00') + kdv / Decimal('100.00'))
            if h.yon == 'giden':
                h_borc       += tutar
                h_borc_kdvli += tutar_kdvli
            elif h.yon == 'gelen':
                h_alacak       += tutar
                h_alacak_kdvli += tutar_kdvli

        tahsilat = db.session.query(func.sum(Odeme.tutar)).filter(
            Odeme.firma_musteri_id == self.id, Odeme.yon == 'tahsilat', Odeme.is_deleted == False
        ).scalar() or 0
        odeme = db.session.query(func.sum(Odeme.tutar)).filter(
            Odeme.firma_musteri_id == self.id, Odeme.yon == 'odeme', Odeme.is_deleted == False
        ).scalar() or 0

        total_debit       = h_borc + odeme
        total_credit      = h_alacak + tahsilat
        total_debit_kdvli  = h_borc_kdvli + odeme
        total_credit_kdvli = h_alacak_kdvli + tahsilat
        return {
            'borc': total_debit,
            'alacak': total_credit,
            'net_bakiye': total_debit - total_credit,
            'borc_kdvli': total_debit_kdvli,
            'alacak_kdvli': total_credit_kdvli,
            'net_bakiye_kdvli': total_debit_kdvli - total_credit_kdvli
        }

    # --- Modüller Arası İlişkiler (Relationships) ---
    kiralamalar = db.relationship('Kiralama', back_populates='firma_musteri', foreign_keys='Kiralama.firma_musteri_id', cascade="all, delete-orphan", order_by="desc(Kiralama.id)")
    tedarik_edilen_ekipmanlar = db.relationship('Ekipman', back_populates='firma_tedarikci', foreign_keys='Ekipman.firma_tedarikci_id')
    odemeler = db.relationship('Odeme', back_populates='firma_musteri', foreign_keys='Odeme.firma_musteri_id', cascade="all, delete-orphan")
    saglanan_nakliye_hizmetleri = db.relationship('KiralamaKalemi', back_populates='nakliye_tedarikci', foreign_keys='KiralamaKalemi.nakliye_tedarikci_id')
    hizmet_kayitlari = db.relationship('HizmetKaydi', back_populates='firma', foreign_keys='HizmetKaydi.firma_id')
    cari_hareketler = db.relationship('CariHareket', back_populates='firma', foreign_keys='CariHareket.firma_id')
    tedarik_edilen_parcalar = db.relationship('StokKarti', back_populates='varsayilan_tedarikci', foreign_keys='StokKarti.varsayilan_tedarikci_id')
    stok_hareketleri = db.relationship('StokHareket', back_populates='firma', cascade="all, delete-orphan")
    nakliyeler = db.relationship('Nakliye', foreign_keys='Nakliye.firma_id', back_populates='firma', cascade="all, delete-orphan")
    servis_kayitlari = db.relationship('BakimKaydi', back_populates='servis_veren_firma', foreign_keys='BakimKaydi.servis_veren_firma_id')

    @property
    def bekleyen_bakiye(self):
        """
        Yeni cari_hareket defterinden açık (bekleyen) bakiyeyi hesaplar.
        Not: Tablo henüz migration ile oluşturulmadan kullanılmamalıdır.
        """
        from app.cari.models import CariHareket

        borc = db.session.query(func.sum(CariHareket.kalan_tutar)).filter(
            CariHareket.firma_id == self.id,
            CariHareket.yon == 'giden',
            CariHareket.durum == 'acik',
            CariHareket.is_deleted == False
        ).scalar() or 0

        alacak = db.session.query(func.sum(CariHareket.kalan_tutar)).filter(
            CariHareket.firma_id == self.id,
            CariHareket.yon == 'gelen',
            CariHareket.durum == 'acik',
            CariHareket.is_deleted == False
        ).scalar() or 0

        return float(borc - alacak)
    
    def __repr__(self):
        return f'<Firma {self.firma_adi}>'