"""Güvenli next / post-login yönlendirme yardımcıları."""
import pytest

from app import create_app
from app.utils import get_safe_next_redirect, login_next_query_value
from config import ProductionConfig, TestingConfig


def test_get_safe_next_relative_path():
    app = create_app(TestingConfig)
    with app.test_request_context('/', base_url='http://example.com:80/'):
        assert get_safe_next_redirect('/raporlama') == '/raporlama'
        assert get_safe_next_redirect('/x?a=1') == '/x?a=1'


def test_get_safe_next_rejects_protocol_relative():
    app = create_app(TestingConfig)
    with app.test_request_context('/', base_url='http://example.com:80/'):
        assert get_safe_next_redirect('//evil.com/x') is None


def test_get_safe_next_rejects_other_host():
    app = create_app(TestingConfig)
    with app.test_request_context('/', base_url='http://example.com:80/'):
        assert get_safe_next_redirect('https://evil.com/') is None


def test_get_safe_next_accepts_same_host_absolute():
    app = create_app(TestingConfig)
    with app.test_request_context('/', base_url='http://example.com:80/'):
        assert get_safe_next_redirect('http://example.com/foo') == '/foo'


def test_get_safe_next_rejects_newlines():
    app = create_app(TestingConfig)
    with app.test_request_context('/', base_url='http://example.com:80/'):
        assert get_safe_next_redirect('/x\nLocation:') is None


def test_login_next_query_value():
    app = create_app(TestingConfig)
    with app.test_request_context('/kiralama/?tab=1', base_url='http://example.com:80/'):
        assert login_next_query_value() == '/kiralama/?tab=1'


def test_production_config_requires_secret_key(monkeypatch):
    monkeypatch.delenv('SECRET_KEY', raising=False)
    with pytest.raises(ValueError, match='SECRET_KEY'):
        create_app(ProductionConfig)
