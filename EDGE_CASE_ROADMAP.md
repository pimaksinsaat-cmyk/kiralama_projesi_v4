# EDGE CASE TEST - YOL HARITASI

**Tarih:** 2026-04-15  
**Mevcut Durum:** 12/12 Test PASSED (100%) ✅  
**Framework:** pytest 9.0.3  
**Database:** SQLite with FK constraints

---

## 📊 MEVCUT DURUM

### Test Sonuçları
```
✓ 12 Test PASSED (100%)
✓ 2.10s Execution Time
✓ FK Constraints Çalışıyor
✓ Unique Constraints Çalışıyor
✓ Type Validation Çalışıyor
✓ Turkish Character Support Çalışıyor
```

### Başarılı Testler (12/12)
1. ✓ User: Duplicate username rejected
2. ✓ User: Null password rejected
3. ✓ Firma: Duplicate vergi_no rejected
4. ✓ Ekipman: Duplicate kod rejected
5. ✓ Kiralama: Invalid firma FK rejected
6. ✓ KiralamaKalemi: Invalid ekipman FK rejected
7. ✓ KiralamaKalemi: Harici ekipman validation
8. ✓ Kasa/Odeme: Check constraint validation
9. ✓ KiralamaKalemi: Decimal type validation
10. ✓ Firma: Turkish characters persisted
11. ✓ StokHareket: Relationship and counts
12. ✓ Personel: Duplicate TC_no rejected

---

## 🚀 FASE 1: MEVCUT TESTLER (TAMAMLANDI)

### ✅ Completed (12 tests)

**Input Validation (2 tests)**
- ✓ Duplicate username → IntegrityError
- ✓ Null password → IntegrityError

**Unique Constraints (2 tests)**
- ✓ Duplicate vergi_no → IntegrityError
- ✓ Duplicate kod → IntegrityError

**Foreign Key Constraints (2 tests)**
- ✓ Invalid firma_id → IntegrityError
- ✓ Invalid ekipman_id → IntegrityError

**Business Logic Validation (1 test)**
- ✓ Harici ekipman validation → ValueError

**Check Constraints (1 test)**
- ✓ Odeme yon field → IntegrityError

**Type Validation (1 test)**
- ✓ Decimal field type → StatementError

**Character Support (1 test)**
- ✓ Turkish characters → Persisted correctly

**Relationships (2 tests)**
- ✓ StokHareket counts
- ✓ Personel TC_no unique

---

## 📈 FASE 2: SINIR DURUMU TESTLERI (YAPILMALI)

### Target: 15 ek test (+25% coverage)

#### A. NUMERIC BOUNDARY TESTS (4 test)

```python
def test_kiralama_kalemi_zero_price():
    """Sıfır ücretli kiralama"""
    kalem = KiralamaKalemi(
        kiralama_brm_fiyat=Decimal("0.00")  # Allow or reject?
    )
    # Expected: Kabul edilecek (sıfır fiyat valid olabilir)

def test_kiralama_kalemi_negative_price():
    """Negatif ücret - MUST REJECT"""
    kalem = KiralamaKalemi(
        kiralama_brm_fiyat=Decimal("-100.00")
    )
    # Expected: IntegrityError (CHECK constraint)

def test_stok_karti_zero_quantity():
    """Sıfır miktar - Kabul edilecek"""
    stok = StokKarti(mevcut_adet=0)
    # Expected: OK

def test_stok_karti_negative_quantity():
    """Negatif miktar - MUST REJECT"""
    stok = StokKarti(mevcut_adet=-5)
    # Expected: IntegrityError (CHECK constraint)
```

#### B. DATE RANGE TESTS (3 test)

```python
def test_kiralama_end_before_start():
    """Bitiş < Başlangıç - MUST REJECT"""
    kiralama = Kiralama(
        kiralama_baslangici=date(2026, 4, 20),
        kiralama_bitis=date(2026, 4, 10)
    )
    # Expected: IntegrityError (CHECK constraint)

def test_kiralama_kalemi_same_dates():
    """Aynı gün başlangıç/bitiş - Kabul edilecek"""
    kalem = KiralamaKalemi(
        kiralama_baslangici=date(2026, 4, 15),
        kiralama_bitis=date(2026, 4, 15)
    )
    # Expected: OK

def test_kiralama_kalemi_end_before_kiralama_start():
    """KiralamaKalemi bitiş < Kiralama başlangıç"""
    kalem = KiralamaKalemi(
        kiralama_baslangici=date(2026, 4, 10),  # Kiralama'dan önce
        kiralama_bitis=date(2026, 4, 15)
    )
    # Expected: Warn or reject (business logic)
```

#### C. STRING VALIDATION TESTS (4 test)

```python
def test_firma_adi_empty():
    """Boş firma adı"""
    firma = Firma(firma_adi="")
    # Expected: IntegrityError (NOT NULL)

def test_firma_adi_max_length():
    """Çok uzun firma adı"""
    firma = Firma(firma_adi="A" * 500)
    # Expected: IntegrityError (length 150)

def test_ekipman_kod_special_chars():
    """Özel karakterler içeren kod"""
    ekipman = Ekipman(kod="K-@#$%-ABC")
    # Expected: OK or sanitized

def test_personel_ad_with_numbers():
    """Ad alanında numerik karakterler"""
    personel = Personel(ad="Ahmet123")
    # Expected: OK (no validation) or warn
```

#### D. RELATIONSHIP CASCADE TESTS (4 test)

```python
def test_kiralama_deletion_cascades_kalemler():
    """Kiralama silinince kalemler de silinmeli"""
    kiralama.delete() → KiralamaKalemi auto-delete

def test_ekipman_deletion_cascades_stok():
    """Ekipman silinince StokKarti de silinmeli"""
    ekipman.delete() → StokKarti auto-delete

def test_kiralama_deletion_cascades_hizmet():
    """Kiralama silinince HizmetKaydi de silinmeli"""
    kiralama.delete() → HizmetKaydi auto-delete

def test_firma_deletion_cascades_kiralama():
    """Firma silinince Kiralama'lar da silinmeli"""
    firma.delete() → Kiralama auto-delete
```

---

## 💾 FASE 3: VERI TUTARLILIĞI TESTLERI (YAPILMALI)

### Target: 8 ek test

#### A. TRANSACTION TESTS (3 test)

```python
def test_concurrent_odeme_to_same_kasa():
    """Aynı Kasa'ya eşzamanlı ödeme"""
    # Scenario: 2 thread, aynı Kasa
    # Expected: Both succeed OR one fails with lock

def test_concurrent_stok_hareket():
    """Aynı StokKarti'ye eşzamanlı hareket"""
    # Scenario: -10, -20 aynı anda
    # Expected: Final quantity correct

def test_transaction_rollback_on_validation_error():
    """Validation hataında transaction rollback"""
    # Scenario: 2 insert, ikincisi hata
    # Expected: Both rolled back
```

#### B. CONSISTENCY CHECKS (3 test)

```python
def test_kasa_bakiye_consistency_after_odeme():
    """Ödeme sonrası Kasa bakiyesi güncellenmiş mi?"""
    # Before: kasa.bakiye = 1000
    # Action: Odeme 200 TL
    # After: kasa.bakiye = 800 (auto-trigger) OR manual

def test_kiralama_total_matches_kalemler():
    """Kiralama toplam = KiralamaKalemi'lerin toplamı"""
    kiralama.total = sum(kalem.total for kalem in kalemler)

def test_stok_hareket_updates_mevcut_adet():
    """StokHareket kaydedilince mevcut_adet otomatik güncellenmiş mi?"""
```

#### C. ENUM/CHOICE TESTS (2 test)

```python
def test_odeme_yon_valid_values():
    """Odeme.yon sadece geçerli değerler kabul et"""
    # Valid: "giris", "cikis"
    # Invalid: "GIRIS", "invalid"
    with pytest.raises(IntegrityError):
        odeme = Odeme(yon="INVALID")

def test_ekipman_calisma_durumu_valid():
    """Ekipman.calisma_durumu valid values"""
    # Valid: "bosta", "kirada", "bakimda"
    # Invalid: "unknown"
```

---

## 🔧 FASE 4: PERFORMANCE TESTLERI (İLERİ)

### Target: 5 ek test

#### A. BULK OPERATIONS (2 test)

```python
def test_bulk_create_1000_firmalar():
    """1000 firma oluşturma - Performance check"""
    # Target: < 5 saniye
    # Assert: All created, no duplicates

def test_bulk_create_kiralama_kalemler():
    """1000 KiralamaKalemi oluşturma"""
    # Target: < 10 saniye
    # Assert: All relationships valid
```

#### B. QUERY PERFORMANCE (2 test)

```python
def test_query_kiralama_with_all_relationships():
    """Kiralama + tüm relationships eager load"""
    # Assert: Single query or N+1 problem?

def test_filtered_query_performance():
    """100k + filter performance"""
    # Target: < 1 saniye
```

#### C. MEMORY TESTS (1 test)

```python
def test_memory_usage_large_resultset():
    """10k record query - memory efficient?"""
    # Assert: Streaming, not full load
```

---

## 📋 IMPLEMENTATION ROADMAP

### SPRINT 1 (Hafta 1) - Boundary Tests
**Effort:** 4-5 saatlik
- [ ] Numeric boundary tests (4)
- [ ] Date range tests (3)
- [ ] String validation tests (4)
- **Target:** +11 test, 100% pass rate

### SPRINT 2 (Hafta 2) - Advanced Coverage
**Effort:** 5-6 saatlik
- [ ] Relationship cascade tests (4)
- [ ] Transaction tests (3)
- [ ] Consistency checks (3)
- [ ] Enum validation (2)
- **Target:** +12 test, maintain 100%

### SPRINT 3 (Hafta 3+) - Performance & Polish
**Effort:** 3-4 saatlik
- [ ] Bulk operation tests (2)
- [ ] Query performance tests (2)
- [ ] Memory efficiency test (1)
- **Target:** +5 test, identify bottlenecks

---

## 🎯 SUCCESS CRITERIA

### Minimum (MUST HAVE)
- ✓ Mevcut 12 test: 100% pass ← **ACHIEVED**
- [ ] Boundary tests: 11 test eklenmeli
- [ ] Pass rate: %100 korunmalı
- **Timeline:** 1 hafta

### Nice to Have (SHOULD HAVE)
- [ ] Cascade tests: 4 test
- [ ] Transaction tests: 3 test
- [ ] Enum tests: 2 test
- **Timeline:** 2. hafta

### Advanced (COULD HAVE)
- [ ] Performance tests: 5 test
- [ ] Stress tests
- [ ] Load tests
- **Timeline:** 3. hafta

---

## 📊 PROGRESS TRACKING

```
FASE 1: MEVCUT TESTLER
████████████████████ 100% (12/12) ✓

FASE 2: SINIR DURUMU TESTLERI
░░░░░░░░░░░░░░░░░░░░ 0% (0/15) ⏳

FASE 3: VERI TUTARLILIĞI TESTLERI
░░░░░░░░░░░░░░░░░░░░ 0% (0/8) ⏳

FASE 4: PERFORMANCE TESTLERI
░░░░░░░░░░░░░░░░░░░░ 0% (0/5) ⏳

────────────────────────────────
TOPLAM: 12/40 (30%)
TARGET: 40/40 (100%)
```

---

## 🔍 QUICK CHECKLIST

### Boundary Tests
- [ ] Numeric zero values (0 price, 0 qty)
- [ ] Negative values (-100 price, -5 qty) - MUST FAIL
- [ ] Max length strings
- [ ] Date range validation (end < start)

### Constraint Tests
- [ ] NOT NULL constraints
- [ ] UNIQUE constraints (already 4 passing)
- [ ] FOREIGN KEY constraints (already 2 passing)
- [ ] CHECK constraints (already 1 passing)

### Relationship Tests
- [ ] Cascade DELETE
- [ ] Orphaned records
- [ ] Soft delete handling
- [ ] Cascade UPDATE

### Transaction Tests
- [ ] Rollback on error
- [ ] Concurrent access
- [ ] Isolation levels
- [ ] Deadlock handling

### Type Tests
- [ ] Decimal rounding
- [ ] Date parsing
- [ ] Enum validation
- [ ] Boolean handling

---

## 📝 NOTES

**Current Strengths:**
- ✓ FK constraints working
- ✓ Unique constraints working
- ✓ Type validation working
- ✓ Character encoding OK
- ✓ Business logic validation OK

**Potential Gaps:**
- ? Numeric boundary validation
- ? Date range validation
- ? Cascade delete behavior
- ? Transaction isolation
- ? Concurrent access handling
- ? Performance with large datasets

**Database Schema Observations:**
- SQLite with FK constraints enabled
- Unique constraints on: username, vergi_no, kod, tc_no
- Check constraints on: yon (Odeme)
- No explicit NOT NULL on all required fields?

---

## 🚀 NEXT IMMEDIATE STEPS

1. **Run mevcut tests** (DONE ✓)
   ```bash
   pytest tests/test_edge_cases.py -v
   ```

2. **Review model validators** (IN PROGRESS)
   ```bash
   # Check which models have @validates decorators
   grep -r "@validates" app/*/models.py
   ```

3. **Check database constraints** (IN PROGRESS)
   ```bash
   # Review migration files for constraints
   ls -la migrations/
   ```

4. **Create FASE 2 tests** (NEXT)
   ```bash
   # Add 11 boundary tests
   # Add 4 date range tests
   # Target: 100% pass rate
   ```

---

**Hazırlanma Tarihi:** 2026-04-15  
**Test Framework:** pytest 9.0.3  
**Coverage:** 12/40 (30%)  
**Pass Rate:** 100% (12/12)
