import os

from config import Config, ProductionConfig
from app import create_app


def _select_config():
    if os.environ.get('FLASK_ENV', '').lower() == 'production':
        return ProductionConfig
    if os.environ.get('FLASK_CONFIG', '').lower() == 'production':
        return ProductionConfig
    return Config


# __init__.py'deki fabrikamızı çağırarak uygulamayı oluştur
app = create_app(_select_config())

if __name__ == '__main__':
    # Sadece 'python run.py' komutuyla çalıştırıldığında devreye girer
     app.run(debug=True, host="127.0.0.1", port=5000)