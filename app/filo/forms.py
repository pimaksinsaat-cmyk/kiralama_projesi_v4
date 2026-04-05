from wtforms import FloatField, StringField, SelectField, IntegerField, BooleanField, SubmitField
from wtforms.validators import DataRequired, Length, Optional
from app.forms.base_form import BaseForm, MoneyField

EKIPMAN_TIPI_SECENEKLERI = [
    ('MAKAS', 'Makaslı Platform'),
    ('EKLEMLI PLATFORM', 'Eklemli Platform'),
    ('BOOM', 'Bomlu Platform'),
    ('FORKLIFT', 'Forklift'),
    ('VINC', 'MobilVinç'),
    ('DIGER', 'Diğer'),
]

class EkipmanForm(BaseForm):
    """
    Ekipman (Makine) ekleme ve düzenleme formu.
    BaseForm ve MoneyField sayesinde veriler otomatik temizlenir ve formatlanır.
    """
    kod = StringField('Makine Kodu', validators=[
        DataRequired(message="Makine kodu zorunludur."),
        Length(max=50)
    ])
    
    tipi = SelectField('Makine Tipi', choices=EKIPMAN_TIPI_SECENEKLERI,
        validators=[DataRequired(message="Lütfen makine tipini seçin.")], default='MAKAS')
    
    marka = StringField('Marka', validators=[Optional(), Length(max=100)])
    model = StringField('Model', validators=[Optional(), Length(max=100)])
    seri_no = StringField('Seri Numarası', validators=[Optional(), Length(max=100)])
    
    uretim_yili = IntegerField('Üretim Yılı', validators=[Optional()])
    calisma_yuksekligi = StringField('Çalışma Yüksekliği (m)', validators=[Optional(), Length(max=50)])
    kaldirma_kapasitesi = StringField('Kaldırma Kapasitesi (kg)', validators=[Optional(), Length(max=50)])
    
    yakit = SelectField('Yakıt Tipi', choices=[
        ('Dizel', 'Dizel'),
        ('Akülü', 'Akülü'),
        ('LPG', 'LPG'),
        ('Hibrit', 'Hibrit')
    ], validators=[Optional()], default='Akülü')

    agirlik = FloatField('Makine Ağırlığı (kg)', validators=[Optional()])
    ic_mekan_uygun = BooleanField('İç Mekan Kullanımına Uygun')
    arazi_tipi_uygun = BooleanField('Arazi Tipi')
   
    genislik = FloatField('Genişlik (m)', validators=[Optional()])
    uzunluk = FloatField('Uzunluk (m)', validators=[Optional()])
    kapali_yukseklik = FloatField('Kapalı Yükseklik (m)', validators=[Optional()])

    # --- İŞTE EN BÜYÜK YENİLİK: Otomatik formatlanan parasal alan ---
    giris_maliyeti = MoneyField('Giriş Maliyeti', validators=[Optional()])
    
    para_birimi = SelectField('Para Birimi', choices=[
        ('TRY', 'TRY'), ('USD', 'USD'), ('EUR', 'EUR'), ('GBP', 'GBP')
    ], default='TRY')
    
    # Şubeler rotada (routes.py) dinamik olarak veritabanından doldurulacak
    sube_id = SelectField('Bulunduğu Şube', coerce=int, validators=[
        DataRequired(message="Şube seçimi zorunludur.")
    ])
    
    calisma_durumu = SelectField('Çalışma Durumu', choices=[
        ('bosta', 'Boşta (Depoda)'),
        ('kirada', 'Kirada'),
        ('serviste', 'Serviste / Bakımda')
    ], default='bosta')



    submit = SubmitField('Kaydet')