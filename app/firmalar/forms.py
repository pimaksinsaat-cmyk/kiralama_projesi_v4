from wtforms import StringField, TextAreaField, SubmitField, BooleanField, IntegerField, EmailField, HiddenField
from wtforms.validators import DataRequired, Length, Optional, Email
from datetime import date

# --- YENİ MİMARİ İÇE AKTARIMLARI ---
from app.forms.base_form import BaseForm, TRDateField

class FirmaForm(BaseForm): # FlaskForm yerine BaseForm'dan miras alıyoruz
    # --- TEMEL KİMLİK BİLGİLERİ ---
    firma_adi = StringField('Firma Ünvanı', validators=[
        DataRequired(message="Firma adı boş bırakılamaz."),
        Length(max=150, message="Firma adı en fazla 150 karakter olabilir.")
    ])

    yetkili_adi = StringField('Yetkili Kişi', validators=[
        DataRequired(message="Yetkili adı boş bırakılamaz."),
        Length(max=100, message="Yetkili adı en fazla 100 karakter olabilir.")
    ])

    # --- İLETİŞİM (PROFESYONEL ALANLAR) ---
    telefon = StringField('Telefon', validators=[
        Optional(),
        Length(max=20, message="Telefon numarası en fazla 20 karakter olabilir.")
    ])

    eposta = EmailField('E-posta', validators=[
        Optional(),
        Email(message="Lütfen geçerli bir e-posta adresi giriniz."),
        Length(max=120, message="E-posta en fazla 120 karakter olabilir.")
    ])
    
    iletisim_bilgileri = TextAreaField('Adres / İletişim Bilgileri', validators=[
        DataRequired(message="İletişim bilgisi zorunludur.")
    ])

    # --- VERGİ DAİRESİ BİLGİLERİ ---
    vergi_dairesi = StringField('Vergi Dairesi', validators=[
        DataRequired(message="Vergi dairesi zorunludur."),
        Length(max=100)
    ])

    vergi_no = StringField('Vergi Numarası', validators=[
        DataRequired(message="Vergi numarası zorunludur."),
        Length(max=50, message="Vergi numarası çok uzun.")
    ])

    # --- SÖZLEŞME VE DOKÜMAN TAKİBİ ---
    genel_sozlesme_no = StringField('PS Numarası (Boşsa Otomatik Oluşur)', 
                                   validators=[Optional(), Length(max=50)])
    
    sozlesme_rev_no = IntegerField('Sözleşme Revizyon No', default=0)
    
    # Standart DateField yerine TRDateField kullanıyoruz
    sozlesme_tarihi = TRDateField('Sözleşme İmza Tarihi', 
                               default=date.today, 
                               validators=[Optional()])

    # --- ROL SEÇİMLERİ ---
    is_musteri = BooleanField('Bu bir Müşteri mi?', default=True)
    is_tedarikci = BooleanField('Bu bir Tedarikçi mi?', default=False)

    submit = SubmitField('Firma Kaydını Tamamla')

class SozlesmeNoDuzeltForm(BaseForm):
    firma_id = HiddenField('Firma ID', validators=[DataRequired()])
    sozlesme_no = StringField('Yeni Sözleşme No', validators=[DataRequired(), Length(max=50)])
    sozlesme_tarihi = TRDateField('Sözleşme Tarihi', validators=[Optional()])