from wtforms import SelectField, StringField, BooleanField, IntegerField, TextAreaField, SubmitField
from wtforms.validators import DataRequired, Optional, NumberRange
from app.forms.base_form import BaseForm, MoneyField, TRDateField
from datetime import date

class MakineDegisimForm(BaseForm):
    """
    Makine değişim işlemlerinde kullanılan form.
    Eski formdaki tüm alanları içerir, parasal veriler MoneyField ile güvence altındadır.
    """
    neden = SelectField('Değişim Nedeni / Yeni Durumu', validators=[DataRequired()])
    
    degisim_tarihi = TRDateField('Değişim Tarihi', default=date.today, validators=[DataRequired()])
    
    donus_saati = IntegerField('Dönüş Saati', validators=[Optional(), NumberRange(min=0, max=23)])
    cikis_saati = IntegerField('Çıkış Saati', validators=[Optional(), NumberRange(min=0, max=23)])
    
    aciklama = TextAreaField('Değişim Notu / Açıklama')

    yeni_ekipman_id = SelectField('Yeni Makine Seçimi (Filo)', coerce=int, validators=[Optional()])
    
    # --- DIŞ TEDARİK ALANLARI ---
    is_dis_tedarik = BooleanField('Dış Tedarik (Kiralık) Makine Gönderilecek')
    harici_ekipman_tedarikci_id = SelectField('Tedarikçi Firma', coerce=int, validators=[Optional()])
    harici_marka = StringField('Harici Marka', validators=[Optional()])
    harici_model = StringField('Harici Model', validators=[Optional()])
    harici_ekipman_seri_no = StringField('Seri Numarası', validators=[Optional()])
    harici_ekipman_tipi = StringField('Ekipman Tipi', validators=[Optional()])
    
    harici_ekipman_yukseklik = IntegerField('Yükseklik (m)', validators=[Optional()])
    harici_ekipman_kapasite = IntegerField('Kapasite (kg)', validators=[Optional()])
    harici_ekipman_uretim_yili = IntegerField('Üretim Yılı', validators=[Optional()])

    # --- KİRALAMA FİNANS ---
    kiralama_brm_fiyat = MoneyField('Yeni Birim Fiyat (₺)', validators=[Optional()])
    kiralama_alis_fiyat = MoneyField('Harici Kira Alış Fiyatı (₺)', validators=[Optional()])
    
    # --- NAKLİYE ALANLARI ---
    yeni_nakliye_ekle = BooleanField('Yeni nakliye ücreti yansıtılsın mı?')
    is_oz_mal_nakliye = BooleanField('Öz Mal Nakliye')
    is_harici_nakliye = BooleanField('Dış Nakliye')
    
    nakliye_satis_fiyat = MoneyField('Nakliye Satış Fiyatı (₺)', validators=[Optional()])
    nakliye_alis_fiyat = MoneyField('Nakliye Alış Fiyatı (₺)', validators=[Optional()])
    
    nakliye_tedarikci_id = SelectField('Nakliye Tedarikçisi', coerce=int, validators=[Optional()])
    nakliye_araci_id = SelectField('Nakliye Aracı', coerce=int, validators=[Optional()])
    
    submit = SubmitField('Değişimi Tamamla ve Kaydet')