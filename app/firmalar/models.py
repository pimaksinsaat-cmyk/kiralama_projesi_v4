from app import db
from datetime import date
import sqlalchemy as sa
from sqlalchemy import func
from sqlalchemy.orm import validates
from app.models.base_model import BaseModel

class Firma(BaseModel):
    """
    Sistemin ana Cari (Ledger) ve Firma modeli.
    Tüm modüller (Stok, Kiralama, Nakliye, Cari) bu modele bağlıdır.

    VALIDATION RULES:
    - firma_adi: 1-150 characters, non-empty, automatically trimmed
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

    # --- Cari Durum Raporu Cache ---
    cari_borc_kdvli = db.Column(db.Numeric(15, 2), default=0, nullable=False, server_default='0')
    cari_alacak_kdvli = db.Column(db.Numeric(15, 2), default=0, nullable=False, server_default='0')
    cari_bakiye_kdvli = db.Column(db.Numeric(15, 2), default=0, nullable=False, server_default='0')
    cari_son_guncelleme = db.Column(db.DateTime, nullable=True)

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

    # --- VALIDATION DECORATORS ---
    @validates('firma_adi')
    def validate_firma_adi(self, key, value):
        """Validate firma_adi: non-empty, max 150 chars, trimmed"""
        if not value:
            raise ValueError("Firma adı boş olamaz")
        # Trim first, then check if empty after stripping
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("Firma adı boş olamaz")
        if len(trimmed) > 150:
            raise ValueError("Firma adı maksimum 150 karakter olabilir")
        return trimmed

    # --- Ledger (Muhasebe) Hesaplama ---
    @property
    def bakiye_ozeti(self):
        """
        PostgreSQL üzerinde tek aggregation sorgusuyla borç/alacak özetini döner.
        Python tarafında satır satır dolaşma yapmaz.
        """
        from app.cari.models import Odeme, HizmetKaydi
        from decimal import Decimal

        aciklama_text = func.coalesce(HizmetKaydi.aciklama, '')
        nakliye_muhasebe_kaydi = sa.or_(
            aciklama_text.like('Müşteri Dönüş Nakliye Bedeli%'),
            aciklama_text.like('Müşteri Nakliye Fark%'),
        )

        dahil_hizmet = sa.and_(
            HizmetKaydi.firma_id == self.id,
            HizmetKaydi.is_deleted.is_(False),
            sa.or_(
                HizmetKaydi.nakliye_id.isnot(None),
                HizmetKaydi.ozel_id.is_(None),
                sa.not_(nakliye_muhasebe_kaydi),
            ),
        )

        # Nakliye'ye bağlı HizmetKaydi kayıtlarında KDV oranı öncelikle Nakliye
        # tablosundan alınır. HizmetKaydi otomatik oluşturulurken kdv_orani
        # sıfır bırakılabileceğinden bu join olmadan bakiye_ozeti ile
        # build_cari_rows arasında tutarsızlık oluşur.
        from app.nakliyeler.models import Nakliye as _Nakliye
        nak_kdv_subq = (
            sa.select(_Nakliye.kdv_orani)
            .where(_Nakliye.id == HizmetKaydi.nakliye_id)
            .correlate(HizmetKaydi)
            .scalar_subquery()
        )
        kdv_oran_expr = sa.cast(
            func.coalesce(
                nak_kdv_subq,
                HizmetKaydi.nakliye_alis_kdv,
                HizmetKaydi.kiralama_alis_kdv,
                HizmetKaydi.kdv_orani,
                0,
            ),
            sa.Numeric(10, 4),
        )
        kdv_carpan_expr = sa.cast(1, sa.Numeric(10, 4)) + (kdv_oran_expr / sa.cast(100, sa.Numeric(10, 4)))
        tutar_kdvli_expr = HizmetKaydi.tutar * kdv_carpan_expr

        hizmet_agg = (
            sa.select(
                func.coalesce(func.sum(sa.case((HizmetKaydi.yon == 'giden', HizmetKaydi.tutar), else_=0)), 0).label('h_borc'),
                func.coalesce(func.sum(sa.case((HizmetKaydi.yon == 'gelen', HizmetKaydi.tutar), else_=0)), 0).label('h_alacak'),
                func.coalesce(func.sum(sa.case((HizmetKaydi.yon == 'giden', tutar_kdvli_expr), else_=0)), 0).label('h_borc_kdvli'),
                func.coalesce(func.sum(sa.case((HizmetKaydi.yon == 'gelen', tutar_kdvli_expr), else_=0)), 0).label('h_alacak_kdvli'),
            )
            .where(dahil_hizmet)
            .subquery()
        )

        odeme_agg = (
            sa.select(
                func.coalesce(func.sum(sa.case((Odeme.yon == 'odeme', Odeme.tutar), else_=0)), 0).label('o_odeme'),
                func.coalesce(func.sum(sa.case((Odeme.yon == 'tahsilat', Odeme.tutar), else_=0)), 0).label('o_tahsilat'),
            )
            .where(
                Odeme.firma_musteri_id == self.id,
                Odeme.is_deleted.is_(False),
            )
            .subquery()
        )

        totals = db.session.execute(
            sa.select(
                hizmet_agg.c.h_borc,
                hizmet_agg.c.h_alacak,
                hizmet_agg.c.h_borc_kdvli,
                hizmet_agg.c.h_alacak_kdvli,
                odeme_agg.c.o_odeme,
                odeme_agg.c.o_tahsilat,
            )
        ).one()

        h_borc = Decimal(str(totals.h_borc or 0))
        h_alacak = Decimal(str(totals.h_alacak or 0))
        h_borc_kdvli = Decimal(str(totals.h_borc_kdvli or 0))
        h_alacak_kdvli = Decimal(str(totals.h_alacak_kdvli or 0))
        odeme = Decimal(str(totals.o_odeme or 0))
        tahsilat = Decimal(str(totals.o_tahsilat or 0))

        total_debit = h_borc + odeme
        total_credit = h_alacak + tahsilat
        total_debit_kdvli = h_borc_kdvli + odeme
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