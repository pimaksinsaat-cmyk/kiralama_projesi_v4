from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, SubmitField, SelectField, URLField, EmailField, HiddenField, DecimalField
from wtforms.validators import DataRequired, Length, Optional, Email, URL, NumberRange
from datetime import datetime

# 1. ŞUBE / DEPO EKLEME VE DÜZENLEME FORMU
class SubeForm(FlaskForm):
    isim = StringField('Şube / Depo Adı', 
                       validators=[DataRequired(message="Lütfen şube adını giriniz."), Length(max=100)])
    
    adres = TextAreaField('Açık Adres', 
                          validators=[Optional()])
    
    yetkili_kisi = StringField('Yetkili Kişi', 
                               validators=[Optional(), Length(max=100)])
    
    telefon = StringField('Telefon Numarası', 
                          validators=[Optional(), Length(max=20)])
    
    email = EmailField('E-Posta Adresi', 
                       validators=[Optional(), Email(message="Geçerli bir e-posta adresi giriniz."), Length(max=100)])
    
    konum_linki = URLField('Harita / Konum Linki', 
                           validators=[Optional(), URL(message="Lütfen geçerli bir harita linki (URL) giriniz.")])
    
    submit = SubmitField('Şubeyi Kaydet')


# 2. ŞUBELER ARASI EKİPMAN TRANSFER FORMU
class TransferForm(FlaskForm):
    # Sağ tıklanan ekipmanın ID'sini gizli olarak tutacağız ki form gönderildiğinde hangi ekipman olduğunu bilelim
    ekipman_id = HiddenField('Ekipman ID', validators=[DataRequired()])
    
    # Hedef şube (Seçenekleri routes.py içinde veritabanından dinamik dolduracağız)
    alan_sube_id = SelectField('Hedef Şube', coerce=int, 
                               validators=[DataRequired(message="Lütfen ekipmanın gideceği şubeyi seçiniz.")])
    
    # Nakliye aracı (Seçenekleri app.nakliyeler.models içindeki Arac tablosundan dolduracağız)
    arac_id = SelectField('Transferi Yapan Araç', coerce=int, 
                          validators=[DataRequired(message="Lütfen nakliyeyi yapacak aracı seçiniz.")])
    
    neden = SelectField('Transfer Nedeni', choices=[
        ('', 'Lütfen bir neden seçiniz...'),
        ('Stok Dengeleme', 'Stok Dengeleme (İhtiyaç Fazlası)'),
        ('Bakım / Onarım', 'Bakım / Onarım İçin Sevkiyat'),
        ('Müşteri Talebi', 'Müşteri Talebi / Şantiye Hazırlığı'),
        ('Diğer', 'Diğer')
    ], validators=[DataRequired(message="Transfer nedeni belirtmek zorunludur.")])
    
    aciklama = TextAreaField('Açıklama / Notlar',
                             validators=[Optional()],
                             render_kw={"placeholder": "Örn: Periyodik bakım için merkeze çekildi..."})

    submit = SubmitField('Transferi Başlat')


# 3. ŞUBE GİDER/MASRAF FORMU
GIDER_KATEGORILERI = [
    ('kira', 'Kira'),
    ('elektrik', 'Elektrik'),
    ('su', 'Su'),
    ('internet', 'İnternet / İletişim'),
    ('ikram', 'İkram / Yemek'),
    ('personel', 'Personel / SGK'),
    ('temizlik', 'Temizlik'),
    ('diger', 'Diğer'),
]

MANUEL_GIDER_KATEGORILERI = GIDER_KATEGORILERI[:-1] + [
    ('mazot', 'Mazot / Yakıt'),
    GIDER_KATEGORILERI[-1],
]

class SubeGideriForm(FlaskForm):
    sube_id = HiddenField('Şube ID', validators=[DataRequired()])
    tarih = StringField('Tarih',
                        validators=[DataRequired(message="Tarih zorunludur")],
                        default=lambda: datetime.now().strftime('%Y-%m-%d'),
                        render_kw={"type": "date"})
    kategori = SelectField('Kategori',
                          choices=MANUEL_GIDER_KATEGORILERI,
                          validators=[DataRequired(message="Kategori seçmek zorunludur")])
    litre = DecimalField('Litre',
                        places=2,
                        validators=[Optional(), NumberRange(min=0.01, message="Litre 0'dan buyuk olmalidir")])
    birim_fiyat = DecimalField('Birim Fiyat (TL)',
                              places=2,
                              validators=[Optional(), NumberRange(min=0.01, message="Birim fiyat 0'dan buyuk olmalidir")])
    tutar = DecimalField('Tutar (TL)',
                        places=2,
                        validators=[DataRequired(message="Tutar zorunludur"),
                                   NumberRange(min=0.01, message="Tutar 0'dan büyük olmalıdır")])
    aciklama = StringField('Açıklama',
                          validators=[Optional(), Length(max=250)])
    fatura_no = StringField('Fatura / Belge No',
                           validators=[Optional(), Length(max=50)])
    submit = SubmitField('Masraf Kaydet')


class SubeSabitGiderDonemiForm(FlaskForm):
    sube_id = HiddenField('Sube ID', validators=[DataRequired()])
    kategori = SelectField(
        'Aylik Gider Kategorisi',
        choices=GIDER_KATEGORILERI,
        validators=[DataRequired(message='Kategori secmek zorunludur')],
    )
    baslangic_tarihi = StringField(
        'Donemsel Degisim Tarihi',
        validators=[DataRequired(message='Donemsel degisim tarihi zorunludur')],
        default=lambda: datetime.now().replace(day=1).strftime('%Y-%m-%d'),
        render_kw={'type': 'date'},
    )
    aylik_tutar = DecimalField(
        'Aylik Tutar (TL)',
        places=2,
        validators=[DataRequired(message='Aylik tutar zorunludur'), NumberRange(min=0.01, message='Tutar 0 dan buyuk olmalidir')],
    )
    kdv_orani = DecimalField(
        'KDV Orani (%)',
        places=2,
        validators=[Optional(), NumberRange(min=0, message='KDV orani negatif olamaz')],
    )
    aciklama = StringField('Aciklama', validators=[Optional(), Length(max=250)])
    submit = SubmitField('Aylik Gideri Kaydet')
