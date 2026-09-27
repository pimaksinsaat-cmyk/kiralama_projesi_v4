"""Nakliye güzergâhı üretimi ve uzunluk doğrulaması."""

from app.services.base import ValidationError


NAKLIYE_GUZERGAH_MAX_LENGTH = 500


def _normalize(value, fallback):
    normalized = " ".join(str(value or "").split())
    return normalized or fallback


def _shorten(value, limit):
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def build_nakliye_guzergah(makine, cikis, varis):
    """Otomatik güzergâhı kısa ve veritabanı sınırı içinde üretir."""
    makine = _shorten(_normalize(makine, "Makine"), 120)
    cikis = _shorten(_normalize(cikis, "Bilinmeyen çıkış"), 250)
    varis = _shorten(_normalize(varis, "Bilinmeyen varış"), 120)
    guzergah = f"{makine}: {cikis} → {varis}"
    return _shorten(guzergah, NAKLIYE_GUZERGAH_MAX_LENGTH)


def validate_nakliye_guzergah(value):
    """Kullanıcı/API güzergâhını DB işleminden önce doğrular."""
    guzergah = str(value or "").strip()
    if not guzergah:
        raise ValidationError("Sefer güzergâhı boş bırakılamaz.")
    if len(guzergah) > NAKLIYE_GUZERGAH_MAX_LENGTH:
        raise ValidationError(
            f"Sefer güzergâhı en fazla {NAKLIYE_GUZERGAH_MAX_LENGTH} karakter olabilir."
        )
    return guzergah
