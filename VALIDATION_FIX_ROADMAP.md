# VALIDATION HATALARI DÜZELTME YOL HARITASI

**Tarih:** 2026-04-15  
**Durum:** Planning  
**Priority:** HIGH (Production Readiness)  
**Timeline:** 2-3 hours  

---

## 📋 BULUNAN HATALAR

### Error #1: firma_adi Max Length Validation Yok
```
Severity:     MEDIUM
Field:        Firma.firma_adi
Definition:   db.Column(db.String(150), nullable=False, index=True)
Problem:      Accepts 200+ chars, limit is 150
Impact:       Database inconsistency, UI overflow
Test:         test_firma_adi_max_length_enforced
```

### Error #2: Negative Prices Accepted
```
Severity:     HIGH
Field:        KiralamaKalemi.kiralama_brm_fiyat
Definition:   db.Column(db.Numeric(15, 2), nullable=False, default=0.0)
Problem:      Accepts negative values (e.g., -100.00)
Impact:       Muhasebe hataları, raporlama yanlışlığı
Test:         test_kiralama_kalemi_negative_price_rejected
```

### Error #3: Negative Quantities Accepted
```
Severity:     HIGH
Field:        StokKarti.mevcut_stok
Definition:   db.Column(db.Integer, nullable=False, default=0)
Problem:      Accepts negative values (e.g., -5)
Impact:       Stok anomalileri, operasyon hataları
Test:         test_stok_karti_negative_quantity_rejected
```

---

## 🎯 ÇÖZÜM STRATEJISI

### Katmanlı Yaklaşım (Layered Approach)

```
┌─────────────────────────────────────────────┐
│  PRESENTATION LAYER (UI Validation)         │
│  - Client-side validation (HTML5, JS)       │
└─────────────────────────────────────────────┘
                      ↓
┌─────────────────────────────────────────────┐
│  APPLICATION LAYER (Model Validators)       │
│  - @validates decorators (SQLAlchemy)       │
│  - WTForms validation                       │
└─────────────────────────────────────────────┘
                      ↓
┌─────────────────────────────────────────────┐
│  DATABASE LAYER (Constraints)               │
│  - CHECK constraints                        │
│  - Triggers                                 │
└─────────────────────────────────────────────┘
```

**Recommendation:** Implement **2 layers**:
- Application Layer (Fast, user-friendly)
- Database Layer (Safety net, data integrity)

---

## 📝 FIX #1: firma_adi Max Length

### Current Code
```python
# app/firmalar/models.py:14
firma_adi = db.Column(db.String(150), nullable=False, index=True)
```

### Option A: Application-Level Validator (QUICK FIX)
**File:** `app/firmalar/models.py`  
**Effort:** 5 minutes  
**Impact:** Medium (catches errors early)

```python
from sqlalchemy.orm import validates

class Firma(BaseModel):
    firma_adi = db.Column(db.String(150), nullable=False, index=True)
    
    @validates('firma_adi')
    def validate_firma_adi(self, key, value):
        if not value:
            raise ValueError("firma_adi cannot be empty")
        if len(value) > 150:
            raise ValueError("firma_adi must be max 150 characters")
        return value.strip()  # Also trim whitespace
```

### Option B: Database Constraint (SAFETY NET)
**File:** Migration file  
**Effort:** 10 minutes  
**Impact:** High (enforces at database level)

```python
# Migration: add_check_constraint_firma_adi_length
def upgrade():
    op.execute('''
        ALTER TABLE firma 
        ADD CONSTRAINT check_firma_adi_length 
        CHECK (LENGTH(firma_adi) > 0 AND LENGTH(firma_adi) <= 150)
    ''')

def downgrade():
    op.execute('ALTER TABLE firma DROP CONSTRAINT check_firma_adi_length')
```

### Option C: Combined Approach (RECOMMENDED)
**Files:** Model + Migration  
**Effort:** 15 minutes  
**Impact:** Excellent (defense in depth)

1. Add @validates in model (immediate)
2. Add CHECK constraint in migration (database safety)

### Testing Strategy

```python
# tests/test_validation_fixes.py

def test_firma_adi_max_length_validator():
    """Application validator should catch oversized strings"""
    firma = Firma(firma_adi="A" * 200)
    with pytest.raises(ValueError, match="max 150"):
        db.session.add(firma)
        db.session.commit()

def test_firma_adi_empty_rejected():
    """Empty firma_adi should be rejected"""
    firma = Firma(firma_adi="")
    with pytest.raises(ValueError):
        db.session.add(firma)
        db.session.commit()

def test_firma_adi_trimmed():
    """Whitespace should be trimmed"""
    firma = Firma(firma_adi="  Test Firma  ")
    db.session.add(firma)
    db.session.commit()
    assert firma.firma_adi == "Test Firma"
```

---

## 📝 FIX #2: Negative Prices Rejected

### Current Code
```python
# app/kiralama/models.py
kiralama_brm_fiyat = db.Column(db.Numeric(15, 2), nullable=False, default=0.0)
```

### Option A: Application-Level Validator (QUICK FIX)
**File:** `app/kiralama/models.py`  
**Effort:** 5 minutes  

```python
from sqlalchemy.orm import validates
from decimal import Decimal

class KiralamaKalemi(BaseModel):
    kiralama_brm_fiyat = db.Column(db.Numeric(15, 2), nullable=False, default=0.0)
    
    @validates('kiralama_brm_fiyat')
    def validate_price(self, key, value):
        if value is None:
            value = Decimal('0.00')
        if Decimal(value) < 0:
            raise ValueError("kiralama_brm_fiyat cannot be negative")
        return Decimal(value)
```

### Option B: Database Constraint (SAFETY NET)
**File:** Migration file  
**Effort:** 10 minutes  

```sql
-- Migration: add_check_constraint_kiralama_brm_fiyat
ALTER TABLE kiralama_kalemi
ADD CONSTRAINT check_kiralama_brm_fiyat_non_negative 
CHECK (kiralama_brm_fiyat >= 0)
```

### Combined Approach (RECOMMENDED)

```python
# Step 1: Add to model
@validates('kiralama_brm_fiyat')
def validate_kiralama_brm_fiyat(self, key, value):
    if value is None:
        return Decimal('0.00')
    if Decimal(value) < 0:
        raise ValueError("Kiralama ücreti negatif olamaz")
    return Decimal(value)

# Step 2: Migration
op.execute('''
    ALTER TABLE kiralama_kalemi 
    ADD CONSTRAINT check_kiralama_brm_fiyat_non_negative 
    CHECK (kiralama_brm_fiyat >= 0)
''')
```

### Testing Strategy

```python
def test_kiralama_brm_fiyat_negative_rejected():
    """Negative price should be rejected"""
    kalem = KiralamaKalemi(
        kiralama_brm_fiyat=Decimal("-100.00")
    )
    with pytest.raises(ValueError, match="negatif"):
        db.session.add(kalem)
        db.session.commit()

def test_kiralama_brm_fiyat_zero_allowed():
    """Zero price should be allowed"""
    kalem = KiralamaKalemi(
        kiralama_brm_fiyat=Decimal("0.00")
    )
    db.session.add(kalem)
    db.session.commit()
    assert kalem.kiralama_brm_fiyat == Decimal("0.00")

def test_kiralama_brm_fiyat_positive_allowed():
    """Positive prices should be allowed"""
    kalem = KiralamaKalemi(
        kiralama_brm_fiyat=Decimal("999.99")
    )
    db.session.add(kalem)
    db.session.commit()
    assert kalem.kiralama_brm_fiyat == Decimal("999.99")
```

---

## 📝 FIX #3: Negative Quantities Rejected

### Current Code
```python
# app/filo/models.py
mevcut_stok = db.Column(db.Integer, nullable=False, default=0)
```

### Option A: Application-Level Validator
**File:** `app/filo/models.py`  
**Effort:** 5 minutes  

```python
from sqlalchemy.orm import validates

class StokKarti(BaseModel):
    mevcut_stok = db.Column(db.Integer, nullable=False, default=0)
    
    @validates('mevcut_stok')
    def validate_mevcut_stok(self, key, value):
        if value is None:
            value = 0
        if int(value) < 0:
            raise ValueError("mevcut_stok cannot be negative")
        return int(value)
```

### Option B: Database Constraint
**File:** Migration file  

```sql
ALTER TABLE stok_karti
ADD CONSTRAINT check_mevcut_stok_non_negative 
CHECK (mevcut_stok >= 0)
```

### Combined Approach (RECOMMENDED)

```python
# Model
@validates('mevcut_stok')
def validate_mevcut_stok(self, key, value):
    if value is None:
        return 0
    if int(value) < 0:
        raise ValueError("Stok miktarı negatif olamaz")
    return int(value)

# Migration
op.execute('''
    ALTER TABLE stok_karti 
    ADD CONSTRAINT check_mevcut_stok_non_negative 
    CHECK (mevcut_stok >= 0)
''')
```

### Testing Strategy

```python
def test_stok_karti_negative_rejected():
    """Negative stock should be rejected"""
    stok = StokKarti(mevcut_stok=-5)
    with pytest.raises(ValueError, match="negatif"):
        db.session.add(stok)
        db.session.commit()

def test_stok_karti_zero_allowed():
    """Zero stock should be allowed"""
    stok = StokKarti(mevcut_stok=0)
    db.session.add(stok)
    db.session.commit()
    assert stok.mevcut_stok == 0

def test_stok_karti_positive_allowed():
    """Positive stock should be allowed"""
    stok = StokKarti(mevcut_stok=1000)
    db.session.add(stok)
    db.session.commit()
    assert stok.mevcut_stok == 1000
```

---

## 🔧 IMPLEMENTATION STEPS

### Step 1: Application-Level Validators (30 min)

```bash
# 1.1 Update Firma model
vim app/firmalar/models.py
# → Add @validates('firma_adi')

# 1.2 Update KiralamaKalemi model
vim app/kiralama/models.py
# → Add @validates('kiralama_brm_fiyat')

# 1.3 Update StokKarti model
vim app/filo/models.py
# → Add @validates('mevcut_stok')

# 1.4 Run tests
pytest tests/test_edge_cases.py -v
```

### Step 2: Database Constraints (30 min)

```bash
# 2.1 Create migrations
flask db migrate -m "Add validation constraints"

# 2.2 Update migration files
vim migrations/versions/add_validation_constraints.py
# → Add CHECK constraints

# 2.3 Apply migrations
flask db upgrade

# 2.4 Verify constraints
sqlite3 kiralama.db ".schema firma" | grep -i constraint
```

### Step 3: Testing (30 min)

```bash
# 3.1 Update test file
vim tests/test_validation_fixes.py
# → Add comprehensive test cases

# 3.2 Run all validation tests
pytest tests/test_validation_fixes.py -v

# 3.3 Run edge case tests (should still pass)
pytest tests/test_edge_cases.py -v

# 3.4 Run full test suite
pytest tests/ -v --cov=app
```

### Step 4: Documentation (15 min)

```bash
# 4.1 Update model docstrings
vim app/firmalar/models.py
# → Add validation rules to docstring

# 4.2 Create validation guide
vim docs/VALIDATION_RULES.md
```

---

## 📊 IMPLEMENTATION MATRIX

| Fix # | Field | Layer | Implementation | Effort | Risk | Priority |
|-------|-------|-------|---|--------|------|----------|
| 1 | firma_adi | App | @validates | 5min | Low | HIGH |
| 1 | firma_adi | DB | CHECK | 10min | Low | HIGH |
| 2 | kiralama_brm_fiyat | App | @validates | 5min | Low | HIGH |
| 2 | kiralama_brm_fiyat | DB | CHECK | 10min | Low | HIGH |
| 3 | mevcut_stok | App | @validates | 5min | Low | HIGH |
| 3 | mevcut_stok | DB | CHECK | 10min | Low | HIGH |
| - | Testing | Test | pytest cases | 30min | Low | HIGH |
| | **TOTAL** | | | **90min** | **Low** | **HIGH** |

---

## 📋 DETAILED IMPLEMENTATION PLAN

### Phase 1: Application-Level Validators (30 minutes)

**File 1: `app/firmalar/models.py`**

```python
from sqlalchemy.orm import validates

class Firma(BaseModel):
    """
    Sistemin ana Cari (Ledger) ve Firma modeli.
    
    Validation Rules:
    - firma_adi: 1-150 characters, non-empty, trimmed
    """
    
    firma_adi = db.Column(db.String(150), nullable=False, index=True)
    # ... other fields ...
    
    @validates('firma_adi')
    def validate_firma_adi(self, key, value):
        """Validate firma_adi: non-empty, max 150 chars"""
        if not value:
            raise ValueError("Firma adı boş olamaz")
        if len(value) > 150:
            raise ValueError("Firma adı maksimum 150 karakter olabilir")
        return value.strip()
```

**File 2: `app/kiralama/models.py`**

```python
from sqlalchemy.orm import validates
from decimal import Decimal

class KiralamaKalemi(BaseModel):
    """
    Kiralama Kalemi (Equipment Item in Rental).
    
    Validation Rules:
    - kiralama_brm_fiyat: >= 0, max 15 digits total with 2 decimals
    """
    
    kiralama_brm_fiyat = db.Column(db.Numeric(15, 2), nullable=False, default=0.0)
    # ... other fields ...
    
    @validates('kiralama_brm_fiyat')
    def validate_kiralama_brm_fiyat(self, key, value):
        """Validate price: non-negative"""
        if value is None:
            return Decimal('0.00')
        price = Decimal(str(value))
        if price < 0:
            raise ValueError("Kiralama ücreti negatif olamaz")
        return price
```

**File 3: `app/filo/models.py`**

```python
from sqlalchemy.orm import validates

class StokKarti(BaseModel):
    """
    Stock Card (Inventory Item).
    
    Validation Rules:
    - mevcut_stok: >= 0 (non-negative integer)
    """
    
    mevcut_stok = db.Column(db.Integer, nullable=False, default=0)
    # ... other fields ...
    
    @validates('mevcut_stok')
    def validate_mevcut_stok(self, key, value):
        """Validate quantity: non-negative"""
        if value is None:
            return 0
        quantity = int(value)
        if quantity < 0:
            raise ValueError("Stok miktarı negatif olamaz")
        return quantity
```

### Phase 2: Database Constraints (30 minutes)

**File: `migrations/versions/XXXXXXXXX_add_validation_constraints.py`**

```python
"""Add validation constraints."""

from alembic import op
import sqlalchemy as sa

def upgrade():
    # Fix #1: firma_adi length validation
    op.execute('''
        ALTER TABLE firma 
        ADD CONSTRAINT check_firma_adi_length 
        CHECK (LENGTH(firma_adi) > 0 AND LENGTH(firma_adi) <= 150)
    ''')
    
    # Fix #2: kiralama_brm_fiyat non-negative
    op.execute('''
        ALTER TABLE kiralama_kalemi 
        ADD CONSTRAINT check_kiralama_brm_fiyat_non_negative 
        CHECK (kiralama_brm_fiyat >= 0)
    ''')
    
    # Fix #3: mevcut_stok non-negative
    op.execute('''
        ALTER TABLE stok_karti 
        ADD CONSTRAINT check_mevcut_stok_non_negative 
        CHECK (mevcut_stok >= 0)
    ''')

def downgrade():
    op.execute('ALTER TABLE firma DROP CONSTRAINT check_firma_adi_length')
    op.execute('ALTER TABLE kiralama_kalemi DROP CONSTRAINT check_kiralama_brm_fiyat_non_negative')
    op.execute('ALTER TABLE stok_karti DROP CONSTRAINT check_mevcut_stok_non_negative')
```

### Phase 3: Comprehensive Testing (30 minutes)

**File: `tests/test_validation_fixes.py`**

```python
"""Test validation constraint fixes."""

import pytest
from decimal import Decimal
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.firmalar.models import Firma
from app.kiralama.models import KiralamaKalemi
from app.filo.models import StokKarti


class TestFirmaAdiValidation:
    """Test firma_adi validation"""
    
    def test_firma_adi_empty_rejected(self, app):
        """Empty firma_adi should be rejected"""
        with app.app_context():
            firma = Firma(firma_adi="")
            with pytest.raises(ValueError, match="boş olamaz"):
                db.session.add(firma)
                db.session.commit()
            db.session.rollback()
    
    def test_firma_adi_max_length_rejected(self, app):
        """firma_adi > 150 chars should be rejected"""
        with app.app_context():
            firma = Firma(firma_adi="A" * 200)
            with pytest.raises(ValueError, match="maksimum"):
                db.session.add(firma)
                db.session.commit()
            db.session.rollback()
    
    def test_firma_adi_trimmed(self, app):
        """Whitespace should be trimmed"""
        with app.app_context():
            firma = Firma(
                firma_adi="  Test Firma  ",
                yetkili_adi="Test",
                iletisim_bilgileri="Adres",
                vergi_dairesi="VD",
                vergi_no="T1234567890"
            )
            db.session.add(firma)
            db.session.commit()
            assert firma.firma_adi == "Test Firma"
    
    def test_firma_adi_valid_accepted(self, app):
        """Valid firma_adi should be accepted"""
        with app.app_context():
            firma = Firma(
                firma_adi="Valid Firma Name",
                yetkili_adi="Test",
                iletisim_bilgileri="Adres",
                vergi_dairesi="VD",
                vergi_no="T1234567890"
            )
            db.session.add(firma)
            db.session.commit()
            assert len(firma.firma_adi) <= 150


class TestKiralamaBrmFiyatValidation:
    """Test kiralama_brm_fiyat validation"""
    
    def test_kiralama_brm_fiyat_negative_rejected(self, app):
        """Negative price should be rejected"""
        with app.app_context():
            kalem = KiralamaKalemi(
                kiralama_brm_fiyat=Decimal("-100.00")
            )
            with pytest.raises(ValueError, match="negatif"):
                db.session.add(kalem)
                db.session.commit()
            db.session.rollback()
    
    def test_kiralama_brm_fiyat_zero_allowed(self, app):
        """Zero price should be allowed"""
        with app.app_context():
            kalem = KiralamaKalemi(
                kiralama_brm_fiyat=Decimal("0.00")
            )
            db.session.add(kalem)
            db.session.commit()
            assert kalem.kiralama_brm_fiyat == Decimal("0.00")
    
    def test_kiralama_brm_fiyat_positive_allowed(self, app):
        """Positive prices should be allowed"""
        with app.app_context():
            kalem = KiralamaKalemi(
                kiralama_brm_fiyat=Decimal("999.99")
            )
            db.session.add(kalem)
            db.session.commit()
            assert kalem.kiralama_brm_fiyat == Decimal("999.99")


class TestStokKartiMevcodValidation:
    """Test mevcut_stok validation"""
    
    def test_mevcut_stok_negative_rejected(self, app):
        """Negative stock should be rejected"""
        with app.app_context():
            stok = StokKarti(
                parca_kodu="TEST",
                parca_adi="Test",
                mevcut_stok=-5
            )
            with pytest.raises(ValueError, match="negatif"):
                db.session.add(stok)
                db.session.commit()
            db.session.rollback()
    
    def test_mevcut_stok_zero_allowed(self, app):
        """Zero stock should be allowed"""
        with app.app_context():
            stok = StokKarti(
                parca_kodu="TEST",
                parca_adi="Test",
                mevcut_stok=0
            )
            db.session.add(stok)
            db.session.commit()
            assert stok.mevcut_stok == 0
    
    def test_mevcut_stok_positive_allowed(self, app):
        """Positive stock should be allowed"""
        with app.app_context():
            stok = StokKarti(
                parca_kodu="TEST",
                parca_adi="Test",
                mevcut_stok=1000
            )
            db.session.add(stok)
            db.session.commit()
            assert stok.mevcut_stok == 1000
```

---

## ✅ VERIFICATION CHECKLIST

### After Implementation

- [ ] All 3 models have @validates decorators
- [ ] @validates properly rejects invalid values
- [ ] @validates properly accepts valid values
- [ ] Migration file created with 3 CHECK constraints
- [ ] Migration applied successfully
- [ ] Database constraints verified with `.schema`
- [ ] All new tests passing (9+ tests)
- [ ] All edge case tests still passing (27 tests)
- [ ] Full test suite passing
- [ ] No existing functionality broken
- [ ] Documentation updated

### Commands to Verify

```bash
# Verify validators work
pytest tests/test_validation_fixes.py -v

# Verify edge cases still pass
pytest tests/test_edge_cases.py -v

# Verify database constraints
sqlite3 kiralama.db ".schema firma" | grep -i check
sqlite3 kiralama.db ".schema kiralama_kalemi" | grep -i check
sqlite3 kiralama.db ".schema stok_karti" | grep -i check

# Verify no regressions
pytest tests/ -v --cov=app
```

---

## 📊 SUCCESS CRITERIA

| Metric | Target | Status |
|--------|--------|--------|
| firma_adi validation | Applied | ⏳ |
| Price validation | Applied | ⏳ |
| Quantity validation | Applied | ⏳ |
| Database constraints | 3/3 | ⏳ |
| Test pass rate | 100% | ⏳ |
| No regressions | 0 failed | ⏳ |

---

## 🚀 NEXT STEPS

1. **Implement Phase 1** (30 min) - Add @validates to 3 models
2. **Implement Phase 2** (30 min) - Create migration with CHECK constraints
3. **Implement Phase 3** (30 min) - Add comprehensive test cases
4. **Verify & Deploy** (15 min) - Run full test suite, verify constraints
5. **Document** - Update model docstrings and validation guide

**Total Estimated Time:** 2-3 hours

---

## 📝 RISK ASSESSMENT

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| Migration fails | Low | High | Test in dev first, backup DB |
| Data exists with invalid values | Medium | Medium | Run validation check before migrate |
| Breaking changes | Low | High | Comprehensive test suite |
| Performance impact | Low | Low | Simple CHECK constraints |

**Overall Risk:** LOW

---

**Document Generated:** 2026-04-15  
**Status:** Ready for Implementation  
**Approval:** Pending
