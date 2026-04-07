# 1. Python 3.11 tabanlı ince bir Linux imajı kullan
FROM python:3.11-slim

# 2. Linux sistem paketlerini güncelle ve LibreOffice'i kur
# LibreOffice'in çalışması için gereken temel kütüphaneleri de ekliyoruz
RUN apt-get update && apt-get install -y \
    libreoffice \
    libxrender1 \
    libxext6 \
    postgresql-client \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# 3. Çalışma dizinini ayarla
WORKDIR /app

# 4. Gerekli dosyaları kopyala
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5. Tüm proje dosyalarını kopyala
COPY . .


# 6. Uygulamanın dinleyeceği portu ayarla (Varsayılan 5000)
EXPOSE 5000

# 7. Uygulamayı Gunicorn ile başlat
CMD gunicorn --worker-class gthread --workers 1 --threads 4 --timeout 90 --graceful-timeout 30 --keep-alive 5 --bind 0.0.0.0:${PORT:-5000} run:app