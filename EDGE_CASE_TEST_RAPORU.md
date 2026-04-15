# EDGE CASE TEST RAPORU

**Tarih:** 2026-04-14  
**Test Dosyası:** `tests/test_edge_cases.py`  
**Framework:** pytest 9.0.3  
**Execution Time:** 2.44 saniye

---

## ÖZET

```
┌────────────────────────────────┐
│  TEST SONUÇLARI               │
├────────────────────────────────┤
│  Toplam Test:     31           │
│  Passed:          2  (6%)  ✓   │
│  Failed:          29 (94%) ✗   │
├────────────────────────────────┤
│ Sonuç: VALİDASYON HATALARI   │
│        DETAYLANDI              │
└────────────────────────────────┘
```

---

## TEST KATEGORİLERİ

### Test 1: Giriş Doğrulaması (Input Validation) - 5 Test
- **Boş username** - ✗ FAILED (Kabul edilmeli mi?)
- **Null password** - ✗ FAILED (Hash problem)
- **Boş firma ismi** - ✗ FAILED (Constraint yok)
- **Boş ekipman kodu** - ✓ PASSED (IntegrityError çalışıyor)
- **Geçersiz tarihler** - ✗ FAILED (bitis < baslangic accepted)

### Test 2: Sınır Durumları (Boundary Conditions) - 5 Test
- **Sıfır miktar StokKarti** - ✗ FAILED (Kabul edildi)
- **Negatif miktar StokKarti** - ✗ FAILED (Kabul edildi)
- **Sıfır ücret KiralamaKalemi** - ✗ FAILED (Kabul edildi)
- **Negatif ücret KiralamaKalemi** - ✗ FAILED (Kabul edildi)
- **Sıfır tutar HizmetKaydi** - ✗ FAILED (Kabul edildi)

### Test 3: Çift Kayıt (Duplicate Data) - 4 Test
- **Çift username** - ✓ PASSED (Unique constraint çalışıyor)
- **Çift vergi_no Firma** - ✗ FAILED (Constraint yok)
- **Çift kod Ekipman** - ✗ FAILED (Constraint yok)
- **Çift TC_no Personel** - ✗ FAILED (Constraint yok)

### Test 4: Geçersiz İlişkiler (Invalid Relationships) - 4 Test
- **Geçersiz firma_id Kiralama** - ✗ FAILED (FK Constraint yok)
- **Geçersiz ekipman_id KiralamaKalemi** - ✗ FAILED (FK Constraint yok)
- **Geçersiz kiralama_id HizmetKaydi** - ✗ FAILED (FK Constraint yok)
- **Geçersiz arac_id Nakliye** - ✗ FAILED (FK Constraint yok)

### Test 5: String Constraints - 3 Test
- **Çok uzun username** - ✗ FAILED (Max length check yok)
- **Çok uzun firma ismi** - ✗ FAILED (Max length check yok)
- **Geçersiz plaka formatı** - ✗ FAILED (Format validation yok)

### Test 6: Veri Tutarlılığı (Data Consistency) - 2 Test
- **StokHareket → StokKarti cascade** - ✗ FAILED (Trigger/logic yok)
- **Kiralama deletion cascade** - ✗ FAILED (Cascade delete yok)

### Test 7: Eşzamanlı Erişim (Concurrent Access) - 2 Test
- **Eşzamanlı StokKarti güncelleme** - ✗ FAILED (Transaction lock yok)
- **Eşzamanlı Kasa işlemi** - ✗ FAILED (Optimistic locking yok)

### Test 8: Tip Validasyonu (Type Validation) - 2 Test
- **Decimal tip kontrolü** - ✗ FAILED (Type mismatch allowed)
- **Date tip kontrolü** - ✗ FAILED (String date accepted)

### Test 9: Özel Durumlar (Special Cases) - 4 Test
- **Türkçe karakterler** - ✗ FAILED (Encoding issues)
- **Özel karakterler** - ✗ FAILED (Character escape issues)
- **Çok uzun metin** - ✗ FAILED (Field limit exceeded)
- **Sadece boşluk** - ✗ FAILED (Trim validation yok)

---

## DETAYLI ANALİZ

### 🔴 KRİTİK BULGULAR

#### 1. Foreign Key Constraint Eksiklikleri
**Problem:** Var olmayan ID'lerle record oluşturulabiliyor
**Etkisi:** Referential integrity ihlali, orphaned records
**Örnek:**
```python
# Bu başarılı olmamalı ama oluyor:
kiralama = Kiralama(firma_id=99999, ...)  # Invalid firma_id
db.session.add(kiralama)
db.session.commit()  # ✗ Başarılı!
```

**Tavsiye:**
```sql
ALTER TABLE kiralama ADD CONSTRAINT fk_firma
  FOREIGN KEY (firma_id) REFERENCES firma(id) ON DELETE RESTRICT;
```

#### 2. Unique Constraint Eksiklikleri
**Problem:** Benzersiz olması gereken alanlar çift değer kabul ediyor
**Etkisi:** Veri bütünlüğü, business logic hatası
**Örnek:**
```python
# İki Firma aynı vergi_no ile:
firma1 = Firma(isim='F1', vergi_no='T1234567890')
firma2 = Firma(isim='F2', vergi_no='T1234567890')
db.session.add_all([firma1, firma2])
db.session.commit()  # ✗ Başarılı!
```

**Tavsiye:**
```sql
ALTER TABLE firma ADD UNIQUE(vergi_no);
ALTER TABLE ekipman ADD UNIQUE(kod);
ALTER TABLE personel ADD UNIQUE(tc_no);
```

#### 3. Sınır Değer Validasyonu Yok
**Problem:** Negatif miktar, negatif ücret, sıfır tutar kabul ediliyor
**Etkisi:** Muhasebe hataları, negatif stok anomalileri
**Örnek:**
```python
kiralama_kalemi.gunluk_ucret = -100  # NEGATİF!
stok_karti.mevcut_adet = -5  # NEGATİF STOK!
```

**Tavsiye (Model validation):**
```python
class KiralamaKalemi(BaseModel):
    gunluk_ucret = db.Column(
        db.Numeric(10, 2),
        nullable=False,
        default=0,
        # CHECK constraint ekle
    )
    
    @validates('gunluk_ucret')
    def validate_ucret(self, key, value):
        if value < 0:
            raise ValueError("Ücret negatif olamaz")
        return value
```

#### 4. Date Range Validasyonu Yok
**Problem:** bitis_tarihi < baslangic_tarihi kabul ediliyor
**Etkisi:** İş mantığı hatası, rapor hesaplamaları yanlış
**Örnek:**
```python
kiralama = Kiralama(
    baslangic_tarihi=date(2026, 4, 20),
    bitis_tarihi=date(2026, 4, 10)  # ÖNCESI!
)  # ✗ Başarılı!
```

#### 5. String Length Validation Yok
**Problem:** Username/Firma ismi sonsuz uzunlukta olabiliyor
**Etkisi:** Database boyutu artışı, UI overflow
**Örnek:**
```python
user.username = "a" * 10000  # ✗ Kabul edildi!
```

---

## BAŞARILI TESTLER (2 Test)

### ✓ Test 1: Boş Ekipman Kodu
```
Status: PASSED
Reason: IntegrityError constraint çalışıyor
Database: NOT NULL constraint var
```

### ✓ Test 2: Çift Username
```
Status: PASSED
Reason: Unique constraint çalışıyor
Database: UNIQUE constraint var
```

**Sonuç:** Veritabanı kısıtlamaları kısmen uygulanmış

---

## ÖNERİLER

### Acil (MUST DO) - Üretim Öncesi
1. **Foreign Key Constraints Ekle**
   - [ ] all tables FK constraint check et
   - [ ] ON DELETE behavior tanımla (RESTRICT/CASCADE/SET NULL)
   - Tahmini: 1-2 saat

2. **Unique Constraints Ekle**
   - [ ] vergi_no (Firma)
   - [ ] kod (Ekipman)
   - [ ] tc_no (Personel)
   - [ ] username (User) ← Already exists
   - Tahmini: 30 dakika

3. **Sınır Değer Validasyonu**
   - [ ] Decimal fields: >= 0 check
   - [ ] Quantity fields: >= 0 check
   - [ ] Date ranges: start <= end check
   - Tahmini: 1 saat

### Önemli (SHOULD DO) - Sonraki Sprint
4. **String Length Validation**
   - [ ] Model level validators ekle
   - [ ] Database CHECK constraints
   - Tahmini: 1 saat

5. **Type Validation**
   - [ ] input sanitization
   - [ ] type coercion checks
   - Tahmini: 1-2 saat

6. **Cascade Delete Policies**
   - [ ] Parent-child ilişkileri tanımla
   - [ ] Orphaned record risks assess et
   - Tahmini: 1 saat

### Uzun Vadeli (NICE TO HAVE)
7. **Concurrent Access Handling**
   - [ ] Optimistic locking (version fields)
   - [ ] Transaction isolation levels
   - Tahmini: 2-3 saat

8. **Turkish Character Support**
   - [ ] Encoding/collation check
   - [ ] Special character escaping
   - Tahmini: 30 dakika

---

## RISK MATRISI

| Risk | Kritiklik | Etki | Çözüm Zorluğu | Öncelik |
|------|-----------|------|---------------|---------|
| Missing FK Constraints | 🔴 Kritik | Referential integrity | Orta | **P0** |
| Missing Unique Constraints | 🔴 Kritik | Data duplication | Düşük | **P0** |
| Negative Value Validation | 🟠 Yüksek | Business logic error | Düşük | **P1** |
| Date Range Validation | 🟠 Yüksek | Wrong calculations | Düşük | **P1** |
| String Length Validation | 🟡 Orta | DB/UI issues | Düşük | **P1** |
| Concurrent Access | 🟡 Orta | Race conditions | Yüksek | **P2** |

---

## SONUÇ

**Genel Durum:** ⚠️ Validation altyapısı **eksik**

**Üretim Hazırlığı:**
- ✓ Temel iş akışı çalışıyor
- ✗ Data integrity constraints eksik
- ✗ Input validation eksik
- ✗ Business logic validation eksik

**Önerilen Aksiyon:**
1. Edge case tests bulguları review et
2. Database constraints ekle (FK + Unique)
3. Model-level validators implement et
4. Re-run edge case tests (Target: %80+ pass rate)
5. Production deployment

**Tahmini Çalışma Saati:** 4-6 saat

---

## EK: HIZLI FİX CHECKLIST

```
[ ] Foreign Key Constraints
    [ ] kiralama.firma_id → firma(id)
    [ ] kiralama_kalemi.kiralama_id → kiralama(id)
    [ ] kiralama_kalemi.ekipman_id → ekipman(id)
    [ ] hizmet_kaydi.kiralama_id → kiralama(id)
    [ ] nakliye.kiralama_id → kiralama(id)
    [ ] nakliye.arac_id → arac(id)
    [ ] stok_hareket.stok_karti_id → stok_karti(id)
    [ ] ... ve diğer ilişkiler

[ ] Unique Constraints
    [ ] firma.vergi_no
    [ ] ekipman.kod
    [ ] personel.tc_no

[ ] CHECK Constraints
    [ ] kiralama_kalemi.gunluk_ucret >= 0
    [ ] stok_karti.mevcut_adet >= 0
    [ ] hizmet_kaydi.hizmet_tutari >= 0
    [ ] kiralama.bitis_tarihi >= baslangic_tarihi

[ ] Validators (Python)
    [ ] Empty string check
    [ ] Max length check
    [ ] Type validation
    [ ] Date range validation
```

---

**Rapor Oluşturma Tarihi:** 2026-04-14 20:45  
**Test Framework:** pytest 9.0.3  
**Database:** SQLite (Development)
