from flask_wtf import FlaskForm
from app.utils import validate_currency 
from app.firmalar.models import Firma

from wtforms import (
    StringField, TextAreaField, IntegerField, DateField, 
    SelectField, SubmitField
)
from wtforms.validators import DataRequired, Optional

# ==========================================
# YARDIMCI ALAN: Türk Lirası Formatlayıcı
# ==========================================
# Veritabanından gelen ondalıklı veriyi (Örn: Decimal('2000.00')) arayüze (2000 veya 2000,50) 
# olarak çeviren özel alan. Böylece to_decimal fonksiyonunun kafası karışmaz.
class TurkishDecimalField(StringField):
    def process_data(self, value):
        if value is not None:
            try:
                # Gelen veriyi (Decimal/Float) tam sayı mı yoksa küsuratlı mı diye matematiksel kontrol et
                val_float = float(value)
                
                if val_float.is_integer():
                    # Tam sayı ise .00 kısmını tamamen at (Örn: 150000.00 -> 150000)
                    self.data = str(int(val_float))
                else:
                    # Küsuratlı ise noktayı virgüle çevir (Örn: 2000.50 -> 2000,50)
                    self.data = f"{val_float:.2f}".replace('.', ',')
            except (ValueError, TypeError):
                self.data = str(value)
        else:
            self.data = ''

# ==========================================
# 1. NAKLİYE SEFER FORMU (Operasyonel)
# ==========================================
class NakliyeForm(FlaskForm):
    from datetime import date
    tarih = DateField('Sefer Tarihi', format='%Y-%m-%d', validators=[DataRequired()], default=date.today)
    
    # Müşteri (Kime fatura kesilecek)
    firma_id = SelectField('Müşteri / Firma', coerce=int, validators=[DataRequired()])
    
    # Operasyon Türü
    nakliye_tipi = SelectField('Nakliye Tipi', choices=[('oz_mal', 'Öz Mal'), ('taseron', 'Taşeron')], default='oz_mal')
    
    # Öz Mal ise Araç Seçimi
    arac_id = SelectField('Bizim Araç (Plaka)', coerce=int, validators=[Optional()])
    
    # Taşeron ise Detaylar
    taseron_firma_id = SelectField('Taşeron Firma (Tedarikçi)', coerce=int, validators=[Optional()])
    
    # DÜZELTME: Standart StringField yerine yazdığımız TurkishDecimalField'ı kullanıyoruz
    taseron_maliyet = TurkishDecimalField('Taşeron Alış Maliyeti (₺)', validators=[Optional()]) 
    
    guzergah = StringField('Güzergah (Nereden - Nereye)', validators=[DataRequired()])
    plaka = StringField('Dış Araç Plakası', validators=[Optional()])
    aciklama = TextAreaField('Yük Açıklaması / Notlar')
    
    # DÜZELTME: Standart StringField yerine yazdığımız TurkishDecimalField'ı kullanıyoruz
    tutar = TurkishDecimalField('Navlun Satış Tutarı (KDV Hariç)', validators=[DataRequired(), validate_currency])
    kdv_orani = IntegerField('KDV (%)', default=20)
    
    submit = SubmitField('Nakliye İşlemini Kaydet')

    def __init__(self, *args, **kwargs):
        super(NakliyeForm, self).__init__(*args, **kwargs)
        
        # FIRMALAR: Adında Kasa/Dahili olmayan müşteriler
        firmalar = Firma.query.filter(
            Firma.firma_adi.notilike('%Kasa%'),
            Firma.firma_adi.notilike('%Dahili%')
        ).order_by(Firma.firma_adi).all()
        
        self.firma_id.choices = [(f.id, f.firma_adi) for f in firmalar]
        
        # TAŞERONLAR: Sadece tedarikçi olan firmalar
        self.taseron_firma_id.choices = [(0, '--- Taşeron Seçiniz ---')] + \
                                        [(f.id, f.firma_adi) for f in firmalar if f.is_tedarikci]