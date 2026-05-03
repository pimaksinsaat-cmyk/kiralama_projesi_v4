from datetime import date
from decimal import Decimal

from wtforms import FieldList, FormField, HiddenField, IntegerField, SelectField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Email, Length, NumberRange, Optional, ValidationError

from app.forms.base_form import BaseForm, MoneyField, TRDateField
from app.teklifler.models import Teklif


class TeklifKalemiForm(BaseForm):
    class Meta:
        csrf = False

    id = HiddenField('Kalem ID')
    ekipman_id = SelectField('Kayıtlı Makine', coerce=int, default=0, validators=[Optional()])
    makine_tipi = StringField('Makine Tipi', validators=[Optional(), Length(max=100)])
    marka_model = StringField('Marka / Model', validators=[Optional(), Length(max=150)])
    calisma_yuksekligi = MoneyField('Çalışma Yüksekliği', validators=[Optional()])
    kaldirma_kapasitesi = IntegerField('Kaldırma Kapasitesi', validators=[Optional(), NumberRange(min=0)])
    adet = IntegerField('Adet', default=1, validators=[DataRequired(), NumberRange(min=1)])
    calisacagi_konum = TextAreaField('Çalışacağı Konum', validators=[Optional()])
    baslangic_tarihi = TRDateField('Başlangıç Tarihi', validators=[Optional()])
    bitis_tarihi = TRDateField('Bitiş Tarihi', validators=[Optional()])
    fiyat_tipi = HiddenField('Fiyat Tipi', default='gunluk')
    gunluk_fiyat = MoneyField('Günlük Fiyat', default=Decimal('0.00'), validators=[DataRequired(), NumberRange(min=0)])
    nakliye_yon = HiddenField('Nakliye Yönü', default='tek_yon')
    nakliye_fiyati = MoneyField('Nakliye Fiyatı', default=Decimal('0.00'), validators=[Optional(), NumberRange(min=0)])
    satir_notu = TextAreaField('Satır Notu', validators=[Optional()])

    def validate_bitis_tarihi(self, field):
        if self.baslangic_tarihi.data and field.data and field.data < self.baslangic_tarihi.data:
            raise ValidationError('Bitiş tarihi başlangıç tarihinden önce olamaz.')


class TeklifForm(BaseForm):
    teklif_no = StringField('Teklif No', validators=[Optional(), Length(max=100)])
    teklif_tarihi = TRDateField('Teklif Tarihi', default=date.today, validators=[DataRequired()])
    gecerlilik_tarihi = TRDateField('Geçerlilik Tarihi', validators=[Optional()])
    durum = SelectField(
        'Durum',
        choices=[
            ('taslak', 'Taslak'),
            ('gonderildi', 'Gönderildi'),
            ('kabul_edildi', 'Kabul Edildi'),
            ('reddedildi', 'Reddedildi'),
            ('iptal', 'İptal'),
        ],
        default='taslak',
    )
    kdv_orani = IntegerField('KDV Oranı (%)', default=20, validators=[DataRequired(), NumberRange(min=0, max=100)])
    notlar = TextAreaField('Notlar', validators=[Optional()])

    musteri_tipi = SelectField(
        'Müşteri Tipi',
        choices=[('kayitli', 'Kayıtlı Firma'), ('aday', 'Yeni / Aday Müşteri')],
        default='aday',
    )
    firma_musteri_id = SelectField('Kayıtlı Firma', coerce=int, default=0, validators=[Optional()])
    aday_firma_adi = StringField('Aday Firma Adı', validators=[Optional(), Length(max=150)])
    aday_yetkili_adi = StringField('Yetkili Adı', validators=[Optional(), Length(max=100)])
    aday_telefon = StringField('Telefon', validators=[Optional(), Length(max=20)])
    aday_eposta = StringField('E-posta', validators=[Optional(), Email(), Length(max=120)])
    aday_adres = TextAreaField('Adres / Konum Notu', validators=[Optional()])
    aday_not = TextAreaField('Aday Müşteri Notu', validators=[Optional()])

    kalemler = FieldList(FormField(TeklifKalemiForm), min_entries=1)
    submit = SubmitField('Teklifi Kaydet')

    def validate_teklif_no(self, field):
        if not field.data:
            return
        mevcut = Teklif.query.filter_by(teklif_no=field.data.strip()).first()
        current_teklif_id = getattr(self, 'current_teklif_id', None)
        if mevcut and (current_teklif_id is None or mevcut.id != current_teklif_id):
            raise ValidationError('Bu teklif numarası zaten kullanılıyor.')

    def validate(self, extra_validators=None):
        ok = super().validate(extra_validators=extra_validators)
        if self.musteri_tipi.data == 'kayitli' and not self.firma_musteri_id.data:
            self.firma_musteri_id.errors.append('Kayıtlı firma seçilmelidir.')
            ok = False
        if self.musteri_tipi.data == 'aday' and not (self.aday_firma_adi.data or '').strip():
            self.aday_firma_adi.errors.append('Aday firma adı zorunludur.')
            ok = False
        return ok


class AdayFirmaAktarForm(BaseForm):
    firma_adi = StringField('Firma Ünvanı', validators=[DataRequired(), Length(max=150)])
    yetkili_adi = StringField('Yetkili Kişi', validators=[DataRequired(), Length(max=100)])
    telefon = StringField('Telefon', validators=[Optional(), Length(max=20)])
    eposta = StringField('E-posta', validators=[Optional(), Email(), Length(max=120)])
    iletisim_bilgileri = TextAreaField('Adres / İletişim Bilgileri', validators=[DataRequired()])
    vergi_dairesi = StringField('Vergi Dairesi', validators=[DataRequired(), Length(max=100)])
    vergi_no = StringField('Vergi Numarası', validators=[DataRequired(), Length(max=50)])
    submit = SubmitField('Firmaya Aktar')
