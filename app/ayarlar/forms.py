from flask_wtf.file import FileAllowed, FileField
from wtforms import IntegerField, StringField, SubmitField, TextAreaField
from wtforms.validators import Email, InputRequired, Length, NumberRange, Optional

from app.forms.base_form import BaseForm
from app.utils import normalize_turkish_upper


class AppSettingsForm(BaseForm):
    company_name = StringField('Şirket Adı', validators=[InputRequired(), Length(max=150)])
    company_short_name = StringField('Kısa Ad', validators=[Optional(), Length(max=80)])
    logo_file = FileField(
        'Şirket Logosu',
        validators=[FileAllowed(['jpg', 'jpeg', 'png', 'webp', 'gif'], 'Sadece görsel dosyaları yükleyebilirsiniz.')]
    )

    company_address = TextAreaField('Şirket Adresi', validators=[Optional()])
    company_phone = StringField('Telefon', validators=[Optional(), Length(max=30)])
    company_email = StringField('E-posta', validators=[Optional(), Email(), Length(max=120)])
    company_website = StringField('Web Sitesi', validators=[Optional(), Length(max=200)])

    invoice_title = StringField('Fatura Ünvanı', validators=[Optional(), Length(max=150)])
    invoice_address = TextAreaField('Fatura Adresi', validators=[Optional()])
    invoice_tax_office = StringField('Vergi Dairesi', validators=[Optional(), Length(max=100)])
    invoice_tax_number = StringField('Vergi Numarası', validators=[Optional(), Length(max=50)])
    invoice_mersis_no = StringField('MERSİS No', validators=[Optional(), Length(max=16)])
    invoice_iban = StringField('IBAN', validators=[Optional(), Length(max=64)])
    invoice_notes = TextAreaField('Fatura Notu', validators=[Optional()])

    kiralama_form_start_no = IntegerField(
        'Kiralama Formu Başlangıç No',
        validators=[InputRequired(), NumberRange(min=1)],
        default=1
    )
    kiralama_form_prefix = StringField(
        'Kiralama Formu Kısaltması',
        validators=[InputRequired(), Length(min=1, max=10)],
        default='PF'
    )
    genel_sozlesme_start_no = IntegerField(
        'Genel Sözleşme Başlangıç No',
        validators=[InputRequired(), NumberRange(min=1)],
        default=1
    )
    genel_sozlesme_prefix = StringField(
        'Genel Sözleşme Kısaltması',
        validators=[InputRequired(), Length(min=1, max=10)],
        default='PS'
    )

    submit = SubmitField('Ayarları Kaydet')

    def validate_on_submit(self):
        """Form validate olmadan önce metin alanlarını büyük harf yap (email ve web sitesi hariç)."""
        # Uppercase yapılacak alanlar
        uppercase_fields = [
            'company_name', 'company_short_name', 'invoice_title',
            'invoice_address', 'invoice_tax_office', 'invoice_tax_number',
            'invoice_mersis_no', 'kiralama_form_prefix', 'genel_sozlesme_prefix',
            'invoice_notes'
        ]
        
        for field_name in uppercase_fields:
            field = getattr(self, field_name, None)
            if field and field.data and isinstance(field.data, str):
                field.data = normalize_turkish_upper(field.data)
        
        return super().validate_on_submit()