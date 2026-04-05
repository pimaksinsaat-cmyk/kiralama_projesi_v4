from flask_wtf import FlaskForm
from wtforms import StringField, DateField, BooleanField, SubmitField, SelectField, IntegerField, TextAreaField
from wtforms.validators import DataRequired, Optional, NumberRange
from app.forms.base_form import BaseForm, MoneyField

class AracForm(FlaskForm):
    plaka = StringField('Plaka', validators=[DataRequired()])
    arac_tipi = StringField('Araç Tipi (Örn: Çekici)')
    marka_model = StringField('Marka / Model')
    sube_id = SelectField('Bağlı Şube', coerce=int, validators=[Optional()])
    muayene_tarihi = DateField('Muayene Bitiş Tarihi', validators=[Optional()])
    sigorta_tarihi = DateField('Sigorta Bitiş Tarihi', validators=[Optional()])
    is_active = BooleanField('Aktif mi?', default=True)
    submit = SubmitField('Aracı Kaydet')


BAKIM_TURLERI = [
    ('rutin', 'Rutin Bakım'),
    ('acil', 'Acil Tamir'),
    ('degisim', 'Yağ/Filtre Değişimi'),
    ('elektrik', 'Elektrik Tamiri'),
    ('lastik', 'Lastik Değişimi'),
    ('fren', 'Fren Bakımı'),
    ('diger', 'Diğer'),
]

class AracBakimForm(BaseForm):
    """Araç bakım kaydı formu"""
    tarih = StringField('Bakım Tarihi', validators=[DataRequired()], render_kw={"type": "date"})
    bakim_tipi = SelectField('Bakım Türü', choices=BAKIM_TURLERI, validators=[DataRequired()])
    yapilan_islem = StringField('Yapılan İşlem', validators=[Optional()])
    maliyet = MoneyField('Maliyet (₺)', validators=[Optional()])
    kilometre = IntegerField('Kilometre', validators=[Optional(), NumberRange(min=0)])
    yapan_yer = StringField('Yapan Kişi/Servis', validators=[Optional()])
    notlar = TextAreaField('Notlar', validators=[Optional()])
    sonraki_bakim_turu = SelectField('Sonraki Bakım', choices=[('km', 'Kilometre Bazlı'), ('tarih', 'Tarih Bazlı')], validators=[Optional()])
    sonraki_bakim_km = IntegerField('Sonraki Bakım (km)', validators=[Optional(), NumberRange(min=0)])
    sonraki_bakim_tarihi = StringField('Sonraki Bakım Tarihi', validators=[Optional()], render_kw={"type": "date"})
    submit = SubmitField('Bakım Kaydını Kaydet')