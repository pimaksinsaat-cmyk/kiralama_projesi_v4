# 1. Python'un hafif bir sürümünü işletim sistemi tabanı olarak alıyoruz
FROM python:3.10-slim

# 2. Docker içindeki çalışma klasörümüzü belirliyoruz
WORKDIR /app

# 3. Kütüphane listesini kopyalayıp kurulumları yapıyoruz
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 4. Projedeki tüm kodları (static, templates, vs.) konteynerin içine kopyalıyoruz
COPY . .

# 5. Dışarıdan erişim için Flask'ın varsayılan portunu açıyoruz
EXPOSE 5000

# 6. Uygulamayı çalıştırıyoruz
CMD ["python", "app.py"]