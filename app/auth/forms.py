# app/auth/forms.py
from wtforms import StringField, PasswordField, SubmitField, BooleanField
from wtforms.validators import InputRequired, Length
from app.forms.base_form import BaseForm

class LoginForm(BaseForm):
    username = StringField('Kullanıcı Adı', validators=[
        InputRequired(), Length(min=3, max=80)
    ])
    password = PasswordField('Şifre', validators=[
        InputRequired(), Length(min=4)
    ])
    beni_hatirla = BooleanField('Beni Hatırla')
    submit = SubmitField('Giriş Yap')