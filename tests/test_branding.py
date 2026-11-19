"""Icono aprobado, derivados reales, rutas Ingress y cierre estable."""
from hashlib import sha256
from html.parser import HTMLParser
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image
import yaml

from app.main import create_app

ROOT = Path(__file__).resolve().parents[1]


class BrandingLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.icons = []
        self.images = []

    def handle_starttag(self, tag, attrs):
        data = dict(attrs)
        if tag == 'link' and data.get('rel') in ('icon', 'apple-touch-icon'):
            self.icons.append(data)
        if tag == 'img':
            self.images.append(data)


def test_master_is_exactly_the_user_approved_image():
    assert sha256((ROOT/'artwork/icono-maestro.png').read_bytes()).hexdigest() == 'acee83f857cfd458fc0445270d2a2bffd9abbe9d919369853a4c0f86e23e96ea'


@pytest.mark.parametrize('size', [32,180,192,512])
def test_png_derivatives_keep_approved_pixels(size):
    with Image.open(ROOT/'artwork/icono-maestro.png') as master:
        expected = master.convert('RGBA').resize((size,size), Image.Resampling.LANCZOS)
    with Image.open(ROOT/f'menu_compra/app/static/icons/icon-{size}.png') as icon:
        assert icon.format == 'PNG' and icon.size == (size,size)
        assert icon.convert('RGBA').tobytes() == expected.tobytes()


def test_store_icon_logo_and_multisize_favicon():
    with Image.open(ROOT/'menu_compra/icon.png') as icon:
        assert icon.format == 'PNG' and icon.size == (128,128)
    with Image.open(ROOT/'menu_compra/logo.png') as logo:
        assert logo.format == 'PNG' and logo.size == (512,160)
    with Image.open(ROOT/'menu_compra/app/static/favicon.ico') as icon:
        assert icon.format == 'ICO' and {(16,16),(32,32),(48,48),(64,64)} <= icon.ico.sizes()


def test_brand_and_favicon_load_through_relative_urls(tmp_path):
    with TestClient(create_app(tmp_path, development=True)) as client:
        parser = BrandingLinks()
        parser.feed(client.get('/').text)
        assert len(parser.icons) == 5
        assert any(link.get('rel') == 'apple-touch-icon' for link in parser.icons)
        assert len(parser.images) == 1
        for resource in parser.icons + parser.images:
            url = resource.get('href', resource.get('src'))
            assert url.startswith('static/') and '?v=1.0.0' in url
            response = client.get('/' + url)
            assert response.status_code == 200 and response.headers['content-type'].startswith('image/')
        assert client.get('/api/health').json()['version'] == '1.0.0'


def test_stable_metadata_preserves_access_slug_and_storage():
    config = yaml.safe_load((ROOT/'menu_compra/config.yaml').read_text(encoding='utf-8'))
    assert config['stage'] == 'stable' and config['version'] == '1.0.0'
    assert config['slug'] == 'menu_compra' and config['ingress_port'] == 8099 and config['ingress'] is True
    assert config['backup'] == 'cold' and config['environment']['MENU_COMPRA_DATA_DIR'] == '/data'
    assert not any(key in config for key in ('ports','host_network','homeassistant_api','hassio_api'))
