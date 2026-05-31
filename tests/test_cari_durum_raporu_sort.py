"""Cari durum raporu bakiye sıralaması."""
from unittest.mock import patch

from app.cari.routes import _get_cari_durum_raporu_verisi

_SAMPLE = [
    {'firma_adi': 'Zeta', 'bakiye_kdvli': 200},
    {'firma_adi': 'Beta', 'bakiye_kdvli': 100},
    {'firma_adi': 'Alfa', 'bakiye_kdvli': 100},
    {'firma_adi': 'Gamma', 'bakiye_kdvli': 50},
]


@patch('app.cari.routes.CariRaporService.get_durum_raporu')
def test_bakiye_kdvli_sort_desc_then_alpha(mock_get):
    mock_get.return_value = (list(_SAMPLE), {})
    rapor, _, sort_by, sort_dir = _get_cari_durum_raporu_verisi('bakiye_kdvli', 'desc', '')
    assert sort_by == 'bakiye_kdvli'
    assert sort_dir == 'desc'
    assert [r['firma_adi'] for r in rapor] == ['Zeta', 'Alfa', 'Beta', 'Gamma']


@patch('app.cari.routes.CariRaporService.get_durum_raporu')
def test_bakiye_kdvli_sort_asc_then_alpha(mock_get):
    mock_get.return_value = (list(_SAMPLE), {})
    rapor, _, _, _ = _get_cari_durum_raporu_verisi('bakiye_kdvli', 'asc', '')
    assert [r['firma_adi'] for r in rapor] == ['Gamma', 'Alfa', 'Beta', 'Zeta']
