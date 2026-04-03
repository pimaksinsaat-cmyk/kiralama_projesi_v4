from wtforms import StringField, SubmitField, IntegerField, SelectField, HiddenField, FieldList, FormField, DecimalField, DateField
from wtforms.validators import Optional, InputRequired, NumberRange, ValidationError
import flask_wtf

# 1. ÖZEL ALANLAR İÇİN GÜVENLİ IMPORT (FALLBACK SİSTEMİ)

# Türkçe sayı formatını destekleyen özel MoneyField
from wtforms import DecimalField
from decimal import Decimal, InvalidOperation

class MoneyField(DecimalField):
    def process_formdata(self, valuelist):
        if valuelist:
            value = valuelist[0]
            if value:
                # Eğer hem nokta hem virgül yoksa, direkt Decimal'e çevir
                if ',' in value:
                    # Türkçe format: binlik ayraçları (.) sil, ondalık ayırıcıyı (,) noktaya çevir
                    value = value.replace('.', '').replace(',', '.')
                # Eğer sadece nokta varsa (ve virgül yoksa), dokunma
                try:
                    self.data = Decimal(value)
                except (InvalidOperation, ValueError):
                    self.data = None
                    raise ValueError(self.gettext('Geçersiz tutar formatı.'))
            else:
                self.data = None
        else:
            self.data = None

try:
    from app.forms.base_form import BaseForm, TRDateField 
except ImportError:
    BaseForm = flask_wtf.FlaskForm
    TRDateField = DateField

from app.utils import secim_hata_mesaji

# 2. KALEM FORMU (Satır Bazlı Detaylar)
class KiralamaKalemiForm(BaseForm):
    class Meta: 
        csrf = False 
    
    id = HiddenField('Kalem ID')
    dis_tedarik_ekipman = IntegerField("Dış Tedarik?", default=0)
    ekipman_id = SelectField('Pimaks Filosu', coerce=int, validators=[Optional()])
    
    harici_ekipman_tedarikci_id = SelectField('Ekipman Tedarikçisi', coerce=int, default=0, validators=[Optional()])
    harici_ekipman_tipi = StringField('Harici Ekipman Tipi', validators=[Optional()])
    harici_ekipman_marka = StringField('Harici Ekipman Markası', validators=[Optional()])
    harici_ekipman_model = StringField('Harici Ekipman Modeli', validators=[Optional()])
    harici_ekipman_seri_no = StringField('Harici Seri No', validators=[Optional()])
    harici_ekipman_calisma_yuksekligi = IntegerField('Çalışma Yüksekliği (m)', validators=[Optional()])
    harici_ekipman_kaldirma_kapasitesi = IntegerField('Kaldırma Kapasitesi (kg)', validators=[Optional()])
    harici_ekipman_uretim_tarihi = IntegerField('Üretim Yılı', validators=[Optional()])
    
    kiralama_baslangici = TRDateField('Başlangıç Tarihi', validators=[InputRequired()])
    kiralama_bitis = TRDateField('Bitiş Tarihi', validators=[InputRequired()])
    
    kiralama_brm_fiyat = MoneyField('Günlük Satış Fiyatı', validators=[InputRequired()], default=0.00)
    kiralama_alis_fiyat = MoneyField('Alış Fiyatı (Maliyet)', validators=[Optional()], default=0.00)
    
    dis_tedarik_nakliye = IntegerField("Harici Nakliye?", default=0)
    nakliye_satis_fiyat = MoneyField('Nakliye Satış Fiyatı', validators=[Optional()], default=0.00)
    nakliye_alis_fiyat = MoneyField('Nakliye Alış Fiyatı', validators=[Optional()], default=0.00)
    nakliye_tedarikci_id = SelectField('Nakliye Tedarikçisi', coerce=int, default=0, validators=[Optional()])
    nakliye_araci_id = SelectField('Nakliye Aracı (Öz Mal)', coerce=int, default=0, validators=[Optional()])

    def validate_kiralama_bitis(self, field):
        if self.kiralama_baslangici.data and field.data:
            if field.data < self.kiralama_baslangici.data:
                raise ValidationError("Bitiş tarihi başlangıç tarihinden önce olamaz!")

# 3. ANA KİRALAMA FORMU
class KiralamaForm(BaseForm):
    kiralama_form_no = StringField('Kiralama Form No', validators=[Optional()])
    firma_musteri_id = SelectField('Müşteri (Firma) Seç', coerce=int, default=0, 
                                 validators=[NumberRange(min=1, message=secim_hata_mesaji)])
    kdv_orani = IntegerField('KDV Oranı (%)', default=20, 
                            validators=[InputRequired(), NumberRange(min=0, max=100)])
    
    # Jinja'da çakılan USD/EUR alanları
    doviz_kuru_usd = MoneyField('USD Kuru (TCMB)', default=0.00, validators=[Optional()])
    doviz_kuru_eur = MoneyField('EUR Kuru (TCMB)', default=0.00, validators=[Optional()])
    
    kalemler = FieldList(FormField(KiralamaKalemiForm), min_entries=1)
    submit = SubmitField('Kiralama Formunu Kaydet')