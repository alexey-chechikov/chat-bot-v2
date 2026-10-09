"""Скачать официальные страницы GinArea о механике сетки в docs/ginarea_official/ (для точной копии алгоритма)."""
import urllib.request
from pathlib import Path

BASE = "https://ginareas-organization.gitbook.io/ginarea.org/"
PAGES = [
    "strategii-i-tipy-botov-ginarea/default-grid", "strategii-i-tipy-botov-ginarea/auto-grid",
    "strategii-i-tipy-botov-ginarea/dynamic-grid", "strategii-i-tipy-botov-ginarea/pro-mode",
    "strategii-i-tipy-botov-ginarea/usdt-fyuchersy", "nastroiki-botov", "nastroiki-botov/granicy-torgov",
    "nastroiki-botov/nastroiki-setki", "nastroiki-botov/nastroiki-ordera",
    "nastroiki-botov/nastroiki-vkhoda-vykhoda-iz-pozicii", "nastroiki-botov/nastroiki-tp-i-sl",
    "nastroiki-botov/nastroiki-p-and-l-treilinga", "nastroiki-botov/in-order-details",
    "nastroiki-botov/in-order-stop", "upravlenie-botom/ordera", "upravlenie-botom/statistika-grafik",
]
OUT = Path(__file__).resolve().parents[2] / "docs" / "ginarea_official"
OUT.mkdir(parents=True, exist_ok=True)
for p in PAGES:
    req = urllib.request.Request(BASE + p + ".md", headers={"User-Agent": "curl/8.7.1", "Accept": "*/*"})
    body = urllib.request.urlopen(req, timeout=30).read()
    (OUT / (p.replace("/", "__") + ".md")).write_bytes(body)
    print(p, len(body))
