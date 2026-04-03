"""
Ekipman rapor services file'ı düzi fix
"""
import os
os.chdir(r'c:\Users\cuney\Drive\'ım\kiralama_projesi_v3')

# Dosyayı relative path ile aç
with open(r'app\services\ekipman_rapor_services.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Satır 188-210'u göster
lines = content.split('\n')
print("=== LİNES 185-215 ===")
for i in range(184, min(215, len(lines))):
    print(f"{i+1}: {lines[i]}")

# Hatalı referansları bul
print("\n=== HATALI REFERANSLAR ===")
for i, line in enumerate(lines):
    if 'fiyat' in line and 'Kalemi' in line and i >= 185 and i <= 210:
        print(f"{i+1}: {line}")

