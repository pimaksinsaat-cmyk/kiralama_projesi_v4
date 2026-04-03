from flask import Blueprint

# Fatura ve Hakediş işlemleri için Blueprint tanımı
# Bu isim 'app/fatura/routes.py' içindeki 'fatura_bp' ile eşleşmelidir.
fatura_bp = Blueprint('fatura', __name__, template_folder='templates')

# Dairesel içe aktarmayı (circular import) önlemek için 
# rotaları dosyanın en altında içe aktarıyoruz.
from app.fatura import routes