from app.extensions import db
from datetime import datetime, timezone
from app.models.base_model import BaseModel
import uuid

class Hakedis(BaseModel):
    """
    Hakediş Modeli: Sözleşme (PS) bazlı hesaplamaları ve 
    e-Fatura teknik gereksinimlerini barındıran ana tablo.
    """
    __tablename__ = 'hakedis'

    __table_args__ = (
        db.CheckConstraint(
            "fatura_senaryosu IN ('TEMELFATURA', 'TICARIFATURA')",
            name='ck_hakedis_senaryo'
        ),
        db.CheckConstraint(
            "belge_tipi IN ('EFATURA', 'EARSIV')",
            name='ck_hakedis_belge_tipi'
        ),
        db.CheckConstraint(
            "fatura_tipi IN ('SATIS', 'IADE', 'TEVKIFAT', 'OZELMATRAH', 'ISTISNA')",
            name='ck_hakedis_tip'
        ),
        db.CheckConstraint(
            "durum IN ('taslak', 'onaylandi', 'faturalasti', 'iptal')",
            name='ck_hakedis_durum'
        ),
    )

    # --- Kimlik ve Sözleşme Bağı ---
    hakedis_no = db.Column(db.String(50), unique=True, nullable=True, index=True)
    # nullable=True: Servis katmanında race-condition'sız üretilecek (PMK-2024-000001)
    fatura_no = db.Column(db.String(50), unique=True, nullable=True, index=True)
    belge_tipi = db.Column(db.String(20), nullable=False, default='EFATURA')

    firma_id = db.Column(db.Integer, db.ForeignKey('firma.id'), nullable=False)
    kiralama_id = db.Column(db.Integer, db.ForeignKey('kiralama.id'), nullable=False)

    # --- Şantiye Bilgisi ---
    proje_adi = db.Column(db.String(200), nullable=True)
    santiye_adresi = db.Column(db.Text, nullable=True)

    # --- Dönem Bilgileri ---
    baslangic_tarihi = db.Column(db.Date, nullable=False)
    bitis_tarihi = db.Column(db.Date, nullable=False)

    # --- e-Fatura / e-Arşiv Standartları (UBL-TR) ---
    uuid = db.Column(db.String(36), default=lambda: str(uuid.uuid4()), unique=True)
    duzenleme_tarihi = db.Column(db.Date, nullable=False, default=lambda: datetime.now(timezone.utc).date())
    duzenleme_saati = db.Column(db.Time, nullable=False, default=lambda: datetime.now(timezone.utc).time().replace(microsecond=0))

    fatura_senaryosu = db.Column(db.String(20), default='TEMELFATURA')
    # TEMELFATURA: KDV mükellefi olmayan alıcılar
    # TICARIFATURA: e-Fatura mükellefi alıcılar
    fatura_tipi = db.Column(db.String(20), default='SATIS')
    # SATIS, IADE, TEVKIFAT, OZELMATRAH, ISTISNA
    para_birimi = db.Column(db.String(3), default='TRY')
    kur_degeri = db.Column(db.Numeric(10, 4), default=1.0000)
    # para_birimi != TRY ise kur_degeri zorunlu — servis katmanında kontrol edilir

    # UBL tarafında zorunluya yakın başlık alanları
    siparis_referans_no = db.Column(db.String(50), nullable=True)
    siparis_referans_tarihi = db.Column(db.Date, nullable=True)

    # --- Finansal Toplamlar ---
    toplam_matrah = db.Column(db.Numeric(15, 2), default=0)
    toplam_kdv = db.Column(db.Numeric(15, 2), default=0)
    toplam_tevkifat = db.Column(db.Numeric(15, 2), default=0)
    genel_toplam = db.Column(db.Numeric(15, 2), default=0)

    # --- Durum takibi (durum makinesi) ---
    # taslak:       Düzenlenebilir; cari borç yok
    # onaylandi:    Cari köprüsü (HizmetKaydi) oluştu; GİB öncesi
    # faturalasti:  Resmi fatura kesildi (GİB); cariye İKİNCİ borç yazılmaz
    # iptal:        Taslak veya (faturasız) onay geri alındı
    durum = db.Column(db.String(20), default='taslak', index=True)
    # GİB / e-Fatura kesildiğinde True; cari borcu taslak→onaylandı adımında oluşur
    is_faturalasti = db.Column(db.Boolean, default=False)
    # Köprü: Cari tarafındaki tekil HizmetKaydi (borç) kaydı — alan adı tarihî, FK hizmet_kaydi.id
    cari_hareket_id = db.Column(
        db.Integer,
        db.ForeignKey('hizmet_kaydi.id'),
        nullable=True
    )

    # --- İlişkiler ---
    kalemler = db.relationship('HakedisKalemi', backref='hakedis', cascade='all, delete-orphan')
    firma = db.relationship('Firma', foreign_keys=[firma_id])
    kiralama = db.relationship('Kiralama', foreign_keys=[kiralama_id])
    cari_hareket = db.relationship('HizmetKaydi', foreign_keys=[cari_hareket_id])

    def __repr__(self):
        return f'<Hakedis {self.hakedis_no}>'


class HakedisKalemi(BaseModel):
    """
    Hakediş Detayları: Her bir makinenin çalışma dökümü.
    """
    __tablename__ = 'hakedis_kalemi'

    __table_args__ = (
        db.CheckConstraint(
            "birim_tipi IN ('DAY', 'MON', 'C62', 'HUR')",
            name='ck_kalem_birim'
        ),
    )

    hakedis_id = db.Column(db.Integer, db.ForeignKey('hakedis.id'), nullable=False)
    kiralama_kalemi_id = db.Column(
        db.Integer,
        db.ForeignKey('kiralama_kalemi.id', ondelete='RESTRICT'),
        nullable=False,
    )
    ekipman_id = db.Column(db.Integer, db.ForeignKey('ekipman.id'), nullable=False)

    # GIB/Ubl satırında mal-hizmet adı zorunlu olduğu için ayrı alan
    mal_hizmet_adi = db.Column(db.String(250), nullable=False, default='Kiralama Hizmeti')
    mal_hizmet_aciklama = db.Column(db.String(500), nullable=True)

    # --- Miktar ve Birim ---
    miktar = db.Column(db.Numeric(10, 2), nullable=False)  # Gün/Ay sayısı
    birim_tipi = db.Column(db.String(10), default='DAY')   # DAY, MON, C62, HUR
    birim_kodu = db.Column(db.String(10), nullable=False, default='C62')  # UBL UnitCode

    # --- Fiyatlandırma ---
    birim_fiyat = db.Column(db.Numeric(15, 2), nullable=False)
    ara_toplam = db.Column(db.Numeric(15, 2), nullable=False)  # miktar * birim_fiyat

    # --- İskonto ---
    iskonto_orani = db.Column(db.Numeric(5, 2), nullable=True)   # %
    iskonto_tutari = db.Column(db.Numeric(15, 2), default=0)     # Hesaplanan tutar

    # --- KDV ---
    kdv_orani = db.Column(db.Integer, default=20)
    kdv_tutari = db.Column(db.Numeric(15, 2), default=0)

    # --- Tevkifat ---
    tevkifat_kodu = db.Column(db.String(10), nullable=True)      # GİB tevkifat kodu (604, 601 vb.)
    tevkifat_orani = db.Column(db.Integer, nullable=True)         # Geriye dönük uyumluluk
    tevkifat_pay = db.Column(db.Integer, nullable=True)           # Pay (5/10 için 5)
    tevkifat_payda = db.Column(db.Integer, nullable=True)         # Payda (5/10 için 10)
    tevkifat_tutari = db.Column(db.Numeric(15, 2), default=0)

    # --- Özel Matrah ---
    ozel_matrah_tutari = db.Column(db.Numeric(15, 2), nullable=True)
    ozel_matrah_kdv_orani = db.Column(db.Integer, nullable=True)

    # İstisna faturalarında GİB kodu/nedeni satır bazında taşınabilir
    istisna_kodu = db.Column(db.String(10), nullable=True)
    istisna_nedeni = db.Column(db.String(250), nullable=True)

    # --- Satır Toplamı ---
    # ara_toplam - iskonto + kdv - tevkifat
    satir_toplami = db.Column(db.Numeric(15, 2), nullable=False)

    # --- İlişkiler ---
    kiralama_kalemi = db.relationship(
        'KiralamaKalemi', foreign_keys=[kiralama_kalemi_id]
    )
    ekipman = db.relationship('Ekipman', foreign_keys=[ekipman_id])