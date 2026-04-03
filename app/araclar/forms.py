from flask_wtf import FlaskForm
from wtforms import StringField, DateField, BooleanField, SubmitField, SelectField
from wtforms.validators import DataRequired, Optional

class AracForm(FlaskForm):
    plaka = StringField('Plaka', validators=[DataRequired()])
    arac_tipi = StringField('Araç Tipi (Örn: Çekici)')
    marka_model = StringField('Marka / Model')
    sube_id = SelectField('Bağlı Şube', coerce=int, validators=[Optional()])
    muayene_tarihi = DateField('Muayene Bitiş Tarihi', validators=[Optional()])
    sigorta_tarihi = DateField('Sigorta Bitiş Tarihi', validators=[Optional()])
    is_active = BooleanField('Aktif mi?', default=True)
    submit = SubmitField('Aracı Kaydet')