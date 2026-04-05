"""Basit dosya inceleme yardımcısı."""

from pathlib import Path


project_root = Path(__file__).resolve().parent
target_file = project_root / 'app' / 'services' / 'ekipman_rapor_services.py'

with target_file.open('r', encoding='utf-8') as file_handle:
    content = file_handle.read()

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

