"""
Phase 3: Comprehensive Validation Tests
========================================

Tests for the three application-level validators implemented in Phase 1:
1. firma_adi validator (app/firmalar/models.py)
2. kiralama_brm_fiyat validator (app/kiralama/models.py)
3. mevcut_stok validator (app/filo/models.py)

These tests verify:
- Valid inputs are accepted
- Invalid inputs raise ValueError
- Boundary conditions are handled correctly
- Type conversions work as expected
"""

import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.extensions import db
from app.firmalar.models import Firma
from app.kiralama.models import Kiralama, KiralamaKalemi
from app.filo.models import StokKarti, Ekipman
from app.subeler.models import Sube


def _unique_vergi_no():
    return f"T{uuid.uuid4().hex[:10].upper()}"


def _create_sube():
    sube = Sube(isim=f"Sube-{uuid.uuid4().hex[:5]}", adres="Adres", yetkili_kisi="Yetkili", telefon="0212-0000000")
    db.session.add(sube)
    db.session.flush()
    return sube


def _create_firma(name_prefix="Firma", is_musteri=True, is_tedarikci=False):
    firma = Firma(
        firma_adi=f"{name_prefix}-{uuid.uuid4().hex[:5]}",
        yetkili_adi="Yetkili",
        iletisim_bilgileri="Adres",
        vergi_dairesi="Istanbul VD",
        vergi_no=_unique_vergi_no(),
        is_musteri=is_musteri,
        is_tedarikci=is_tedarikci,
        bakiye=Decimal("0"),
    )
    db.session.add(firma)
    db.session.flush()
    return firma


def _create_ekipman(sube_id):
    ekipman = Ekipman(
        kod=f"K-{uuid.uuid4().hex[:8]}",
        yakit="Elektrik",
        tipi="MAKAS",
        marka="Marka",
        model="Model",
        seri_no=f"SN-{uuid.uuid4().hex[:8]}",
        calisma_yuksekligi=10,
        kaldirma_kapasitesi=2000,
        uretim_yili=2024,
        calisma_durumu="bosta",
        sube_id=sube_id,
    )
    db.session.add(ekipman)
    db.session.flush()
    return ekipman


def _create_kiralama(firma_id):
    kiralama = Kiralama(
        kiralama_form_no=f"PF-{uuid.uuid4().hex[:6]}",
        firma_musteri_id=firma_id,
        kdv_orani=20,
    )
    db.session.add(kiralama)
    db.session.flush()
    return kiralama


# ================================================================================
# SECTION A: FIRMA_ADI VALIDATOR TESTS (5 tests)
# ================================================================================

class TestFirmaAdiValidator:
    """Test firma_adi field validation"""

    def test_firma_adi_valid_name_accepted(self, app):
        """Valid firma_adi should be accepted and trimmed"""
        with app.app_context():
            firma = Firma(
                firma_adi="  Test Firma Ltd. Şti.  ",  # With whitespace
                yetkili_adi="Yetkili",
                iletisim_bilgileri="Adres",
                vergi_dairesi="Istanbul VD",
                vergi_no=_unique_vergi_no(),
                is_musteri=True,
                is_tedarikci=False,
                bakiye=Decimal("0"),
            )
            db.session.add(firma)
            db.session.commit()

            reloaded = Firma.query.filter_by(id=firma.id).first()
            assert reloaded is not None
            # Should be trimmed
            assert reloaded.firma_adi == "Test Firma Ltd. Şti."
            print("[OK] Valid firma_adi accepted and trimmed")

    def test_firma_adi_empty_string_rejected(self, app):
        """Empty firma_adi should raise ValueError"""
        with app.app_context():
            with pytest.raises(ValueError):
                firma = Firma(
                    firma_adi="",  # Empty!
                    yetkili_adi="Yetkili",
                    iletisim_bilgileri="Adres",
                    vergi_dairesi="Istanbul VD",
                    vergi_no=_unique_vergi_no(),
                    is_musteri=True,
                    is_tedarikci=False,
                    bakiye=Decimal("0"),
                )
            print("[OK] Empty firma_adi rejected")

    def test_firma_adi_max_length_150_accepted(self, app):
        """firma_adi with exactly 150 chars should be accepted"""
        with app.app_context():
            name_150 = "A" * 150
            firma = Firma(
                firma_adi=name_150,
                yetkili_adi="Yetkili",
                iletisim_bilgileri="Adres",
                vergi_dairesi="Istanbul VD",
                vergi_no=_unique_vergi_no(),
                is_musteri=True,
                is_tedarikci=False,
                bakiye=Decimal("0"),
            )
            db.session.add(firma)
            db.session.commit()

            reloaded = Firma.query.filter_by(id=firma.id).first()
            assert reloaded is not None
            assert len(reloaded.firma_adi) == 150
            print("[OK] firma_adi with exactly 150 chars accepted")

    def test_firma_adi_exceeds_max_length_rejected(self, app):
        """firma_adi exceeding 150 chars should raise ValueError"""
        with app.app_context():
            name_151 = "A" * 151
            with pytest.raises(ValueError) as exc_info:
                firma = Firma(
                    firma_adi=name_151,  # 151 chars - exceeds limit
                    yetkili_adi="Yetkili",
                    iletisim_bilgileri="Adres",
                    vergi_dairesi="Istanbul VD",
                    vergi_no=_unique_vergi_no(),
                    is_musteri=True,
                    is_tedarikci=False,
                    bakiye=Decimal("0"),
                )
            assert "maksimum 150" in str(exc_info.value).lower()
            print("[OK] firma_adi exceeding 150 chars rejected")

    def test_firma_adi_whitespace_only_rejected(self, app):
        """firma_adi with only whitespace should raise ValueError"""
        with app.app_context():
            with pytest.raises(ValueError):
                firma = Firma(
                    firma_adi="   ",  # Only spaces
                    yetkili_adi="Yetkili",
                    iletisim_bilgileri="Adres",
                    vergi_dairesi="Istanbul VD",
                    vergi_no=_unique_vergi_no(),
                    is_musteri=True,
                    is_tedarikci=False,
                    bakiye=Decimal("0"),
                )
            print("[OK] firma_adi with only whitespace rejected")


# ================================================================================
# SECTION B: KIRALAMA_BRM_FIYAT VALIDATOR TESTS (6 tests)
# ================================================================================

class TestKiralamaBrmFiyatValidator:
    """Test kiralama_brm_fiyat field validation"""

    def test_kiralama_brm_fiyat_valid_decimal_accepted(self, app):
        """Valid decimal price should be accepted"""
        with app.app_context():
            sube = _create_sube()
            firma = _create_firma("Musteri", is_musteri=True)
            ekipman = _create_ekipman(sube.id)
            kiralama = _create_kiralama(firma.id)

            kalem = KiralamaKalemi(
                kiralama_id=kiralama.id,
                ekipman_id=ekipman.id,
                kiralama_baslangici=date(2026, 4, 1),
                kiralama_bitis=date(2026, 4, 30),
                kiralama_brm_fiyat=Decimal("1234.56"),
                sonlandirildi=False,
                is_active=True,
            )
            db.session.add(kalem)
            db.session.commit()

            reloaded = KiralamaKalemi.query.filter_by(id=kalem.id).first()
            assert reloaded is not None
            assert reloaded.kiralama_brm_fiyat == Decimal("1234.56")
            print("[OK] Valid decimal price accepted")

    def test_kiralama_brm_fiyat_zero_accepted(self, app):
        """Zero price (free rental) should be accepted"""
        with app.app_context():
            sube = _create_sube()
            firma = _create_firma("Musteri", is_musteri=True)
            ekipman = _create_ekipman(sube.id)
            kiralama = _create_kiralama(firma.id)

            kalem = KiralamaKalemi(
                kiralama_id=kiralama.id,
                ekipman_id=ekipman.id,
                kiralama_baslangici=date(2026, 4, 1),
                kiralama_bitis=date(2026, 4, 30),
                kiralama_brm_fiyat=Decimal("0.00"),
                sonlandirildi=False,
                is_active=True,
            )
            db.session.add(kalem)
            db.session.commit()

            reloaded = KiralamaKalemi.query.filter_by(id=kalem.id).first()
            assert reloaded is not None
            assert reloaded.kiralama_brm_fiyat == Decimal("0.00")
            print("[OK] Zero price accepted")

    def test_kiralama_brm_fiyat_negative_rejected(self, app):
        """Negative price should raise ValueError"""
        with app.app_context():
            sube = _create_sube()
            firma = _create_firma("Musteri", is_musteri=True)
            ekipman = _create_ekipman(sube.id)
            kiralama = _create_kiralama(firma.id)

            with pytest.raises(ValueError) as exc_info:
                kalem = KiralamaKalemi(
                    kiralama_id=kiralama.id,
                    ekipman_id=ekipman.id,
                    kiralama_baslangici=date(2026, 4, 1),
                    kiralama_bitis=date(2026, 4, 30),
                    kiralama_brm_fiyat=Decimal("-100.00"),
                    sonlandirildi=False,
                    is_active=True,
                )
            assert "negatif" in str(exc_info.value).lower()
            print("[OK] Negative price rejected")

    def test_kiralama_brm_fiyat_invalid_string_rejected(self, app):
        """Invalid numeric string should raise ValueError"""
        with app.app_context():
            sube = _create_sube()
            firma = _create_firma("Musteri", is_musteri=True)
            ekipman = _create_ekipman(sube.id)
            kiralama = _create_kiralama(firma.id)

            with pytest.raises(ValueError) as exc_info:
                kalem = KiralamaKalemi(
                    kiralama_id=kiralama.id,
                    ekipman_id=ekipman.id,
                    kiralama_baslangici=date(2026, 4, 1),
                    kiralama_bitis=date(2026, 4, 30),
                    kiralama_brm_fiyat="not_a_number",
                    sonlandirildi=False,
                    is_active=True,
                )
            assert "geçerli bir sayı" in str(exc_info.value).lower()
            print("[OK] Invalid numeric string rejected")

    def test_kiralama_brm_fiyat_none_defaults_to_zero(self, app):
        """None value should default to Decimal('0.00')"""
        with app.app_context():
            sube = _create_sube()
            firma = _create_firma("Musteri", is_musteri=True)
            ekipman = _create_ekipman(sube.id)
            kiralama = _create_kiralama(firma.id)

            kalem = KiralamaKalemi(
                kiralama_id=kiralama.id,
                ekipman_id=ekipman.id,
                kiralama_baslangici=date(2026, 4, 1),
                kiralama_bitis=date(2026, 4, 30),
                kiralama_brm_fiyat=None,
                sonlandirildi=False,
                is_active=True,
            )
            db.session.add(kalem)
            db.session.commit()

            reloaded = KiralamaKalemi.query.filter_by(id=kalem.id).first()
            assert reloaded is not None
            assert reloaded.kiralama_brm_fiyat == Decimal("0.00")
            print("[OK] None value defaults to Decimal('0.00')")

    def test_kiralama_brm_fiyat_large_value_accepted(self, app):
        """Large decimal values should be accepted"""
        with app.app_context():
            sube = _create_sube()
            firma = _create_firma("Musteri", is_musteri=True)
            ekipman = _create_ekipman(sube.id)
            kiralama = _create_kiralama(firma.id)

            # Maximum: 15 total digits, 2 decimal places = 999999999999.99
            large_price = Decimal("999999999999.99")
            kalem = KiralamaKalemi(
                kiralama_id=kiralama.id,
                ekipman_id=ekipman.id,
                kiralama_baslangici=date(2026, 4, 1),
                kiralama_bitis=date(2026, 4, 30),
                kiralama_brm_fiyat=large_price,
                sonlandirildi=False,
                is_active=True,
            )
            db.session.add(kalem)
            db.session.commit()

            reloaded = KiralamaKalemi.query.filter_by(id=kalem.id).first()
            assert reloaded is not None
            assert reloaded.kiralama_brm_fiyat == large_price
            print("[OK] Large decimal value accepted")


# ================================================================================
# SECTION C: MEVCUT_STOK VALIDATOR TESTS (5 tests)
# ================================================================================

class TestMevecutStokValidator:
    """Test mevcut_stok field validation"""

    def test_mevcut_stok_valid_positive_accepted(self, app):
        """Valid positive integer stock should be accepted"""
        with app.app_context():
            stok = StokKarti(
                parca_kodu=f"PC-{uuid.uuid4().hex[:8]}",
                parca_adi="Test Parca",
                mevcut_stok=1000
            )
            db.session.add(stok)
            db.session.commit()

            reloaded = StokKarti.query.filter_by(id=stok.id).first()
            assert reloaded is not None
            assert reloaded.mevcut_stok == 1000
            print("[OK] Valid positive stock accepted")

    def test_mevcut_stok_zero_accepted(self, app):
        """Zero stock should be accepted (empty shelf)"""
        with app.app_context():
            stok = StokKarti(
                parca_kodu=f"PC-{uuid.uuid4().hex[:8]}",
                parca_adi="Test Parca",
                mevcut_stok=0
            )
            db.session.add(stok)
            db.session.commit()

            reloaded = StokKarti.query.filter_by(id=stok.id).first()
            assert reloaded is not None
            assert reloaded.mevcut_stok == 0
            print("[OK] Zero stock accepted")

    def test_mevcut_stok_negative_rejected(self, app):
        """Negative stock should raise ValueError"""
        with app.app_context():
            with pytest.raises(ValueError) as exc_info:
                stok = StokKarti(
                    parca_kodu=f"PC-{uuid.uuid4().hex[:8]}",
                    parca_adi="Test Parca",
                    mevcut_stok=-5
                )
            assert "negatif" in str(exc_info.value).lower()
            print("[OK] Negative stock rejected")

    def test_mevcut_stok_none_defaults_to_zero(self, app):
        """None value should default to 0"""
        with app.app_context():
            stok = StokKarti(
                parca_kodu=f"PC-{uuid.uuid4().hex[:8]}",
                parca_adi="Test Parca",
                mevcut_stok=None
            )
            db.session.add(stok)
            db.session.commit()

            reloaded = StokKarti.query.filter_by(id=stok.id).first()
            assert reloaded is not None
            assert reloaded.mevcut_stok == 0
            print("[OK] None value defaults to 0")

    def test_mevcut_stok_large_value_accepted(self, app):
        """Large integer values should be accepted"""
        with app.app_context():
            stok = StokKarti(
                parca_kodu=f"PC-{uuid.uuid4().hex[:8]}",
                parca_adi="Test Parca",
                mevcut_stok=2147483647  # Max 32-bit signed int
            )
            db.session.add(stok)
            db.session.commit()

            reloaded = StokKarti.query.filter_by(id=stok.id).first()
            assert reloaded is not None
            assert reloaded.mevcut_stok == 2147483647
            print("[OK] Large integer value accepted")


# ================================================================================
# SECTION D: INTEGRATION TESTS (3 tests)
# ================================================================================

class TestValidationIntegration:
    """Test validators working together in real scenarios"""

    def test_valid_rental_with_all_validators(self, app):
        """Create complete rental with all three validators passing"""
        with app.app_context():
            # Create firma with valid name
            firma = Firma(
                firma_adi="Istanbul Kiralama San. Tic. Ltd. Sti.",
                yetkili_adi="Yetkili",
                iletisim_bilgileri="Adres",
                vergi_dairesi="Istanbul VD",
                vergi_no=_unique_vergi_no(),
                is_musteri=True,
                is_tedarikci=False,
                bakiye=Decimal("0"),
            )
            db.session.add(firma)
            db.session.commit()

            # Create rental with valid price
            kiralama = Kiralama(
                kiralama_form_no=f"PF-{uuid.uuid4().hex[:6]}",
                firma_musteri_id=firma.id,
                kdv_orani=20,
            )
            db.session.add(kiralama)
            db.session.flush()

            sube = _create_sube()
            ekipman = _create_ekipman(sube.id)

            kalem = KiralamaKalemi(
                kiralama_id=kiralama.id,
                ekipman_id=ekipman.id,
                kiralama_baslangici=date(2026, 4, 1),
                kiralama_bitis=date(2026, 4, 30),
                kiralama_brm_fiyat=Decimal("5000.00"),
                sonlandirildi=False,
                is_active=True,
            )
            db.session.add(kalem)
            db.session.commit()

            # Create stock with valid quantity
            stok = StokKarti(
                parca_kodu=f"PC-{uuid.uuid4().hex[:8]}",
                parca_adi="Yedek Parca",
                mevcut_stok=500
            )
            db.session.add(stok)
            db.session.commit()

            # Verify all were created successfully
            assert firma.id is not None
            assert kiralama.id is not None
            assert kalem.id is not None
            assert stok.id is not None
            print("[OK] All validators passed in integrated scenario")

    def test_multiple_validation_failures(self, app):
        """Test that any validator failure prevents object creation"""
        with app.app_context():
            failures = []

            # Test 1: firma_adi too long
            try:
                firma = Firma(
                    firma_adi="A" * 200,
                    yetkili_adi="Yetkili",
                    iletisim_bilgileri="Adres",
                    vergi_dairesi="Istanbul VD",
                    vergi_no=_unique_vergi_no(),
                    is_musteri=True,
                    is_tedarikci=False,
                    bakiye=Decimal("0"),
                )
                failures.append("firma_adi not validated")
            except ValueError:
                pass

            # Test 2: negative price
            try:
                sube = _create_sube()
                firma = _create_firma("Musteri", is_musteri=True)
                ekipman = _create_ekipman(sube.id)
                kiralama = _create_kiralama(firma.id)

                kalem = KiralamaKalemi(
                    kiralama_id=kiralama.id,
                    ekipman_id=ekipman.id,
                    kiralama_baslangici=date(2026, 4, 1),
                    kiralama_bitis=date(2026, 4, 30),
                    kiralama_brm_fiyat=Decimal("-50.00"),
                    sonlandirildi=False,
                    is_active=True,
                )
                failures.append("kiralama_brm_fiyat not validated")
            except ValueError:
                pass

            # Test 3: negative stock
            try:
                stok = StokKarti(
                    parca_kodu=f"PC-{uuid.uuid4().hex[:8]}",
                    parca_adi="Test Parca",
                    mevcut_stok=-10
                )
                failures.append("mevcut_stok not validated")
            except ValueError:
                pass

            assert len(failures) == 0, f"Validation failures: {failures}"
            print("[OK] All validators prevented invalid object creation")

    def test_validators_dont_interfere_with_other_fields(self, app):
        """Validators should only check their specific fields"""
        with app.app_context():
            firma = Firma(
                firma_adi="Test Firma",
                yetkili_adi="A" * 500,  # Very long, but not validated
                iletisim_bilgileri="B" * 1000,  # Very long, but not validated
                vergi_dairesi="Istanbul VD",
                vergi_no=_unique_vergi_no(),
                is_musteri=True,
                is_tedarikci=False,
                bakiye=Decimal("999999999.99"),  # Large, but not validated by validator
            )
            db.session.add(firma)
            db.session.commit()

            reloaded = Firma.query.filter_by(id=firma.id).first()
            assert reloaded is not None
            assert len(reloaded.yetkili_adi) == 500
            print("[OK] Validators only check their specific fields")
