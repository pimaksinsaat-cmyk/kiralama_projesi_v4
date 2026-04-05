from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField, SelectField, DecimalField, HiddenField, IntegerField
from wtforms.validators import DataRequired, Length, Optional, NumberRange


IZIN_TURLERI = [
    ('yillik', 'Yillik Izin'),
    ('ucretsiz', 'Ucretsiz Izin'),
    ('hastalik', 'Hastalik Izni'),
    ('mazeret', 'Mazeret Izni'),
]

MESLEK_SECENEKLERI = [
    ('', 'Seciniz'),
    ('Teknik Servis', 'Teknik Servis'),
    ('Sofor', 'Sofor'),
    ('Operator', 'Operator'),
    ('Muhasebe', 'Muhasebe'),
    ('Hizmet', 'Hizmet'),
    ('Ofis Calisani', 'Ofis Calisani'),
    ('Idari Personel', 'Idari Personel'),
    ('Beden Iscisi', 'Beden Iscisi'),
    ('Diger', 'Diger'),
]


class PersonelForm(FlaskForm):
    submission_token = HiddenField(
        'Gonderim Anahtari',
        validators=[DataRequired(message='Form gonderim anahtari eksik. Sayfayi yenileyip tekrar deneyin.')],
    )
    sube_id = SelectField(
        'Bagli Oldugu Sube',
        coerce=int,
        validators=[Optional()],
        choices=[(0, 'Sube secmeden devam et')],
    )
    ad = StringField(
        'Ad',
        validators=[DataRequired(message='Ad zorunludur'), Length(max=50)],
    )
    soyad = StringField(
        'Soyad',
        validators=[DataRequired(message='Soyad zorunludur'), Length(max=50)],
    )
    tc_no = StringField(
        'TC Kimlik No',
        validators=[Optional(), Length(min=11, max=11, message='TC No 11 haneli olmalidir')],
    )
    telefon = StringField('Telefon', validators=[Optional(), Length(max=20)])
    meslek = SelectField(
        'Meslek / Pozisyon',
        validators=[Optional()],
        choices=MESLEK_SECENEKLERI,
    )
    meslek_diger = StringField(
        'Diger Meslek / Pozisyon',
        validators=[Optional(), Length(max=100)],
    )
    maas = DecimalField(
        'Maas (TL)',
        places=2,
        validators=[Optional(), NumberRange(min=0, message='Maas negatif olamaz')],
    )
    yemek_ucreti = DecimalField(
        'Yemek Ucreti (TL)',
        places=2,
        validators=[Optional(), NumberRange(min=0, message='Yemek ucreti negatif olamaz')],
    )
    yol_ucreti = DecimalField(
        'Yol Ucreti (TL)',
        places=2,
        validators=[Optional(), NumberRange(min=0, message='Yol ucreti negatif olamaz')],
    )
    maas_gecerlilik_tarihi = StringField(
        'Ucret / Sube Degisiklik Tarihi',
        validators=[Optional()],
        render_kw={'type': 'date'},
    )
    ise_giris_tarihi = StringField('Ise Giris Tarihi', validators=[Optional()], render_kw={'type': 'date'})
    isten_cikis_tarihi = StringField('Isten Cikis Tarihi', validators=[Optional()], render_kw={'type': 'date'})
    submit = SubmitField('Personel Kaydet')

    def validate(self, extra_validators=None):
        if not super().validate(extra_validators=extra_validators):
            return False

        if (self.meslek.data or '').strip() == 'Diger' and not (self.meslek_diger.data or '').strip():
            self.meslek_diger.errors.append('Diger secildiginde aciklama girmek zorunludur.')
            return False

        return True


class PersonelIzinForm(FlaskForm):
    personel_id = HiddenField('Personel ID', validators=[DataRequired()])
    izin_turu = SelectField(
        'Izin Turu',
        choices=IZIN_TURLERI,
        validators=[DataRequired(message='Izin turu secmek zorunludur')],
    )
    baslangic_tarihi = StringField(
        'Baslangic Tarihi',
        validators=[DataRequired(message='Baslangic tarihi zorunludur')],
        render_kw={'type': 'date'},
    )
    bitis_tarihi = StringField(
        'Bitis Tarihi',
        validators=[DataRequired(message='Bitis tarihi zorunludur')],
        render_kw={'type': 'date'},
    )
    gun_sayisi = IntegerField(
        'Gun Sayisi',
        validators=[Optional(), NumberRange(min=1, message='En az 1 gun olmalidir')],
    )
    aciklama = StringField('Aciklama', validators=[Optional(), Length(max=250)])
    submit = SubmitField('Izin Kaydet')