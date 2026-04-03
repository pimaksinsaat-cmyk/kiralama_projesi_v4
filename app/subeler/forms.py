from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, SubmitField, SelectField, URLField, EmailField, HiddenField
from wtforms.validators import DataRequired, Length, Optional, Email, URL

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