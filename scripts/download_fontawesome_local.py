"""Bir kerelik: Font Awesome 6.4.0 css + woff2 dosyalarını app/static/vendor altına indirir."""
import os
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FA_DIR = os.path.join(ROOT, "app", "static", "vendor", "font-awesome")
CSS = os.path.join(FA_DIR, "css", "all.min.css")
WEBFONTS = os.path.join(FA_DIR, "webfonts")
BASE = "https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0"
FILES = [
    ("css/all.min.css", CSS),
    ("webfonts/fa-brands-400.woff2", os.path.join(WEBFONTS, "fa-brands-400.woff2")),
    ("webfonts/fa-regular-400.woff2", os.path.join(WEBFONTS, "fa-regular-400.woff2")),
    ("webfonts/fa-solid-900.woff2", os.path.join(WEBFONTS, "fa-solid-900.woff2")),
    ("webfonts/fa-v4compatibility.woff2", os.path.join(WEBFONTS, "fa-v4compatibility.woff2")),
]


def main():
    for url_suffix, dest in FILES:
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        url = f"{BASE}/{url_suffix}"
        print(url, "->", dest)
        urllib.request.urlretrieve(url, dest)
    print("OK")


if __name__ == "__main__":
    main()
