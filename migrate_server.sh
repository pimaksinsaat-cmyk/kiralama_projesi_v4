#!/bin/bash
# ============================================================
# MIGRATION-ONLY DEPLOY SCRIPT
# Kullanim: sudo bash migrate_server.sh
#
# Bu script DB'yi SILMEZ. Sadece:
#   1. Backup al
#   2. git pull
#   3. pip install
#   4. flask db upgrade
#   5. servisi restart et
# ============================================================
set -e

PROJECT_DIR="/root/kiralama_projesi_v4"
DB_USER="cuneytdemir"
DB_PASS="Ayseela@2014"
DB_NAME="kiralama_db"
DB_HOST="localhost"
SERVICE="kiralama_test"

BACKUP_FILE="/tmp/pre_migration_backup_$(date +%Y%m%d_%H%M%S).sql"

echo ""
echo "======================================================="
echo "  MIGRATION DEPLOY - $(date '+%d.%m.%Y %H:%M:%S')"
echo "======================================================="

# 1. Mevcut migration head kontrolü
echo ""
echo "=== [1/6] Mevcut migration durumu ==="
cd $PROJECT_DIR
FLASK_APP=run.py DATABASE_URL="postgresql://$DB_USER:$DB_PASS@$DB_HOST:5432/$DB_NAME" \
  SECRET_KEY="kiralama-projesi-icin-cok-gizli-anahtar-123" \
  venv/bin/flask db current
echo ""

# 2. DB yedeği al (DROP YOK!)
echo "=== [2/6] DB yedeği alınıyor ==="
PGPASSWORD="$DB_PASS" pg_dump -U $DB_USER -h $DB_HOST $DB_NAME > "$BACKUP_FILE"
echo "  Yedek: $BACKUP_FILE ($(du -sh $BACKUP_FILE | cut -f1))"

# 3. Servisi durdur
echo ""
echo "=== [3/6] Servis durduruluyor ==="
systemctl stop $SERVICE
echo "  Servis durduruldu."

# 4. Kodu güncelle
echo ""
echo "=== [4/6] Kod güncelleniyor (git pull) ==="
git pull origin main
echo "  Git pull tamamlandı."

# 5. Bağımlılıkları güncelle
echo ""
echo "=== [5/6] Bağımlılıklar güncelleniyor ==="
venv/bin/pip install -r requirements.txt -q
echo "  pip install tamamlandı."

# 6. Migration uygula (h6c2d3e4f5g6 = son head)
echo ""
echo "=== [6/6] Migration uygulanıyor ==="
echo "  Hedef revision: h6c2d3e4f5g6 (son migration)"
FLASK_APP=run.py DATABASE_URL="postgresql://$DB_USER:$DB_PASS@$DB_HOST:5432/$DB_NAME" \
  SECRET_KEY="kiralama-projesi-icin-cok-gizli-anahtar-123" \
  venv/bin/flask db upgrade h6c2d3e4f5g6

echo ""
echo "  Migration sonrası durum:"
FLASK_APP=run.py DATABASE_URL="postgresql://$DB_USER:$DB_PASS@$DB_HOST:5432/$DB_NAME" \
  SECRET_KEY="kiralama-projesi-icin-cok-gizli-anahtar-123" \
  venv/bin/flask db current

# 7. Servisi başlat
echo ""
echo "=== Servis başlatılıyor ==="
systemctl start $SERVICE
sleep 2
systemctl status $SERVICE --no-pager -l | head -15

echo ""
echo "======================================================="
echo "  TAMAMLANDI - $(date '+%d.%m.%Y %H:%M:%S')"
echo "  Yedek dosyası: $BACKUP_FILE"
echo "======================================================="
echo ""
echo "  Sorun çıkarsa geri almak için:"
echo "  flask db downgrade <önceki_revision>"
echo ""
