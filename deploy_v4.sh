#!/bin/bash
set -e

PROJECT_DIR="/root/kiralama_projesi_v4"
DB_USER="cuneytdemir"
DB_PASS="Ayseela@2014"
DB_NAME="kiralama_db"
DB_HOST="localhost"
DUMP_FILE="/tmp/db_restore.sql"
SERVICE="kiralama_test"

echo "=== 1. Servis durduruluyor ==="
systemctl stop $SERVICE

echo "=== 2. DB yedekleniyor (sunucu mevcut verisi) ==="
PGPASSWORD="$DB_PASS" pg_dump -U $DB_USER -h $DB_HOST $DB_NAME > /tmp/sunucu_eski_yedek_$(date +%Y%m%d_%H%M%S).sql
echo "Sunucu yedeği /tmp/ altına alındı."

echo "=== 3. DB temizlenip yeni dump yükleniyor ==="
PGPASSWORD="$DB_PASS" psql -U $DB_USER -h $DB_HOST $DB_NAME -c "
DROP SCHEMA public CASCADE;
CREATE SCHEMA public;
GRANT ALL ON SCHEMA public TO $DB_USER;
GRANT ALL ON SCHEMA public TO public;
"
PGPASSWORD="$DB_PASS" psql -U $DB_USER -h $DB_HOST $DB_NAME < $DUMP_FILE
echo "DB restore tamamlandi."

echo "=== 4. Kod güncelleniyor ==="
cd $PROJECT_DIR
git pull origin main

echo "=== 5. Bağımlılıklar güncelleniyor ==="
venv/bin/pip install -r requirements.txt -q

echo "=== 6. Migration uygulanıyor ==="
FLASK_APP=run.py DATABASE_URL="postgresql://$DB_USER:$DB_PASS@$DB_HOST:5432/$DB_NAME" \
  SECRET_KEY="kiralama-projesi-icin-cok-gizli-anahtar-123" \
  venv/bin/flask db upgrade

echo "=== 7. Servis başlatılıyor ==="
systemctl start $SERVICE
systemctl status $SERVICE --no-pager -l | head -20

echo "=== TAMAMLANDI ==="
