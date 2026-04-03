from wtforms import (
    StringField, SelectField, SubmitField, 
    DateField, DecimalField, IntegerField
)
from wtforms.validators import DataRequired, InputRequired, NumberRange, Optional, Length, ValidationError
from app.utils import secim_hata_mesaji

# --- MİMARİ ENTEGRASYONU: BaseForm ve Özel Alanların İçe Aktarılması ---
try:
    from app.forms.base_form import BaseForm, TRDateField, MoneyField
except ImportError:
    # Fallback (Güvenlik Ağı): Özel base form bulunamazsa standart WTF kullan
    from flask_wtf import FlaskForm as BaseForm
    TRDateField = DateField
    MoneyField = DecimalField

# -------------------------------------------------------------------------
# 1. OdemeForm (Tahsilat / Ödeme)
# -------------------------------------------------------------------------
class OdemeForm(BaseForm):
    firma_musteri_id = SelectField('Firma/Müşteri', coerce=int, default=0, validators=[DataRequired(message=secim_hata_mesaji)])
    kasa_id = SelectField('Kasa/Banka', coerce=int, default=0, validators=[DataRequired(message="Lütfen geçerli bir kasa seçiniz.")])
    
    tarih = TRDateField('Tarih', format='%Y-%m-%d', validators=[DataRequired()])
    
    tutar = MoneyField('Tutar', places=2, validators=[
        DataRequired(message="Tutar alanı boş bırakılamaz."), 
        NumberRange(min=0.01, message="Tutar 0'dan büyük olmalıdır.")
    ])
    
    yon = SelectField('İşlem Türü', choices=[
        ('tahsilat', 'Tahsilat (Para Girişi)'), 
        ('odeme', 'Ödeme (Para Çıkışı)')
    ], default='tahsilat', validators=[DataRequired()])
    
    fatura_no = StringField('Belge/Fatura No', validators=[Optional(), Length(max=50)])
    vade_tarihi = TRDateField('Vade Tarihi', format='%Y-%m-%d', validators=[Optional()])
    aciklama = StringField('Açıklama', validators=[Optional(), Length(max=250)])
    
    submit = SubmitField('Kaydet')

    def validate_vade_tarihi(self, field):
        """Vade tarihinin işlem tarihinden önce olmamasını sağlar."""
        if field.data and self.tarih.data:
            if field.data < self.tarih.data:
                raise ValidationError("Vade tarihi, işlem tarihinden önce olamaz!")

# -------------------------------------------------------------------------
# 2. HizmetKaydiForm (Gelir / Gider Faturası)
# -------------------------------------------------------------------------
class HizmetKaydiForm(BaseForm):
    firma_id = SelectField('İlgili Firma', coerce=int, default=0, validators=[DataRequired(message=secim_hata_mesaji)])
    tarih = TRDateField('İşlem Tarihi', format='%Y-%m-%d', validators=[InputRequired()])
    
    tutar = MoneyField('Tutar', places=2, validators=[
        InputRequired(message="Tutar zorunludur."), 
        NumberRange(min=0.01, message="Hatalı tutar.")
    ])
    kdv_orani = IntegerField('KDV Oranı (%)', default=20, validators=[
        Optional(), NumberRange(min=0, max=100, message="KDV oranı 0-100 arası olmalı.")
    ])
    
    aciklama = StringField('Hizmet/Ürün Açıklaması', validators=[InputRequired(), Length(max=250)])
    
    yon = SelectField('İşlem Yönü', choices=[
        ('giden', 'Hizmet/Ürün Satışı (Gelir)'), 
        ('gelen', 'Hizmet/Ürün Alımı (Gider)')
    ], validators=[InputRequired()])
    
    fatura_no = StringField('Fatura No', validators=[Optional(), Length(max=50)])
    vade_tarihi = TRDateField('Vade Tarihi', format='%Y-%m-%d', validators=[Optional()])
    
    submit = SubmitField('Hizmet Kaydını Oluştur')

    def validate_vade_tarihi(self, field):
        if field.data and self.tarih.data:
            if field.data < self.tarih.data:
                raise ValidationError("Vade tarihi, işlem tarihinden önce olamaz!")

# -------------------------------------------------------------------------
# 3. KasaForm (Banka / Nakit Hesap Tanımı)
# -------------------------------------------------------------------------
class KasaForm(BaseForm):
    kasa_adi = StringField('Hesap Adı', validators=[InputRequired(), Length(max=100)])
    
    tipi = SelectField('Hesap Tipi', choices=[
        ('nakit', 'Nakit Kasa'), 
        ('banka', 'Banka Hesabı'),
        ('pos', 'POS Cihazı')
    ], default='banka', validators=[InputRequired()])
    
    para_birimi = SelectField('Para Birimi', choices=[
        ('TRY', 'TL (Türk Lirası)'), 
        ('USD', 'USD (Dolar)'), 
        ('EUR', 'EUR (Euro)')
    ], default='TRY', validators=[InputRequired()])

    banka_sube_adi = StringField('Banka Şube Adı', validators=[Optional(), Length(max=120)])
    
    bakiye = MoneyField('Açılış Bakiyesi', places=2, default=0.0, validators=[Optional()])
    
    submit = SubmitField('Kaydet')

# -------------------------------------------------------------------------
# 4. KasaTransferForm
# -------------------------------------------------------------------------
class KasaTransferForm(BaseForm):
    kaynak_kasa_id = SelectField('Kaynak Kasa', coerce=int, validators=[DataRequired()])
    hedef_kasa_id = SelectField('Hedef Kasa', coerce=int, validators=[DataRequired()])
    
    tutar = MoneyField('Transfer Tutarı', places=2, validators=[
        DataRequired(message="Tutar zorunludur."),
        NumberRange(min=0.01, message="Geçerli bir tutar giriniz.")
    ])
    
    submit = SubmitField('Transferi Tamamla')

# -------------------------------------------------------------------------
# 5. KasaHizliIslemForm
# -------------------------------------------------------------------------
class KasaHizliIslemForm(BaseForm):
    kasa_id = SelectField('İlgili Kasa', coerce=int, validators=[DataRequired()])
    
    islem_yonu = SelectField('İşlem Yönü', choices=[
        ('giris', 'Para Girişi'),
        ('cikis', 'Para Çıkışı')
    ], validators=[DataRequired()])
    
    tutar = MoneyField('İşlem Tutarı', places=2, validators=[
        DataRequired(message="Tutar zorunludur."),
        NumberRange(min=0.01, message="Geçerli bir tutar giriniz.")
    ])
    
    aciklama = StringField('Kısa Açıklama', validators=[Optional(), Length(max=100)])
    
    submit = SubmitField('İşlemi Onayla')