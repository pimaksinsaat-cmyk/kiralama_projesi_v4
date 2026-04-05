from wtforms import StringField, DateField, SelectField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Optional, Length, ValidationError
from datetime import date

# --- MİMARİ ENTEGRASYONU ---
try:
    from app.forms.base_form import BaseForm, TRDateField, MoneyField
except ImportError:
    from flask_wtf import FlaskForm as BaseForm
    TRDateField = DateField
    from wtforms import DecimalField as MoneyField


class HakedisOlusturForm(BaseForm):
    """
    Hakediş oluşturma formu.
    e-Fatura/e-Arşiv altyapısına temel teşkil edecek verileri toplar.
    """

    # --- Sözleşme Bağı ---
    kiralama_id = SelectField('Sözleşme (PS No)', coerce=int, validators=[DataRequired(message="Lütfen bir sözleşme seçiniz.")])

    # --- Şantiye Bilgisi ---
    proje_adi = StringField('Proje Adı', validators=[Optional(), Length(max=200)])
    santiye_adresi = TextAreaField('Şantiye Adresi', validators=[Optional()])

    # --- Dönem Bilgileri ---
    baslangic_tarihi = TRDateField('Dönem Başlangıcı', format='%Y-%m-%d',
                                    default=date.today, validators=[DataRequired()])
    bitis_tarihi = TRDateField('Dönem Bitişi', format='%Y-%m-%d',
                                default=date.today, validators=[DataRequired()])

    # --- e-Fatura Entegrasyon Seçenekleri ---
    fatura_senaryosu = SelectField('Fatura Senaryosu', choices=[
        ('TEMELFATURA', 'Temel Fatura (e-Fatura mükellefi olmayan alıcılar)'),
        ('TICARIFATURA', 'Ticari Fatura (e-Fatura mükellefi alıcılar)'),
    ], default='TEMELFATURA')
    # Not: e-Arşiv ayrı bir belge tipidir, senaryo değil.
    # İleride belge_tipi alanı eklendiğinde buraya da eklenir.

    fatura_tipi = SelectField('Fatura Tipi', choices=[
        ('SATIS', 'Satış'),
        ('TEVKIFAT', 'Tevkifatlı'),
        ('ISTISNA', 'İstisna'),
        ('IADE', 'İade')
    ], default='SATIS')

    # --- Para Birimi ---
    para_birimi = SelectField('Para Birimi', choices=[
        ('TRY', 'Türk Lirası (TL)'),
        ('USD', 'Amerikan Doları ($)'),
        ('EUR', 'Euro (€)')
    ], default='TRY')

    kur_degeri = MoneyField('Döviz Kuru (TRY karşılığı)',
                             places=4, validators=[Optional()])
    # para_birimi != TRY ise zorunlu — servis katmanında kontrol edilir

    submit = SubmitField('Hakediş Taslağı Oluştur')

    # --- Tarih Validasyonu ---
    def validate_bitis_tarihi(self, field):
        if field.data and self.baslangic_tarihi.data:
            if field.data < self.baslangic_tarihi.data:
                raise ValidationError("Bitiş tarihi, başlangıç tarihinden önce olamaz!")

    # --- Kur Validasyonu ---
    def validate_kur_degeri(self, field):
        if self.para_birimi.data != 'TRY':
            if not field.data or field.data <= 0:
                raise ValidationError("Dövizli işlemlerde kur değeri zorunludur!")