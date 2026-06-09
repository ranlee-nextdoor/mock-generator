"""
Brand asset fetching: pull a brand's logo and on-site creatives by domain.

- Logos: Brandfetch (if BRANDFETCH_API_KEY set, higher quality + brand images),
  otherwise a zero-config Clearbit logo fallback.
- Creatives: scrape the brand's own homepage for og:image / twitter:image and
  prominent inline images. We deliberately use the brand's OWN site, not open-web
  image search — cleaner sources, fewer rights headaches.
- proxy_image: server-side fetch of an external image so the browser can pull it
  in without CORS, with an SSRF guard against internal addresses.
"""
import ipaddress
import os
import re
import socket
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

UA = "Mozilla/5.0 (compatible; NextdoorMockGenerator/1.0)"
TIMEOUT = 10
MAX_IMAGE_BYTES = 25 * 1024 * 1024  # 25MB cap on proxied images
MAX_CREATIVES = 12

# Skip obvious non-creative imagery
_SKIP_PATTERNS = re.compile(
    r"(sprite|icon|favicon|logo|pixel|spacer|tracking|analytics|\.svg($|\?)|1x1|badge)",
    re.IGNORECASE,
)


def normalize_domain(raw: str) -> str:
    """'https://www.Nike.com/shoes' -> 'nike.com'."""
    raw = (raw or "").strip().lower()
    if not raw:
        return ""
    if "://" not in raw:
        raw = "https://" + raw
    host = urlparse(raw).netloc or urlparse(raw).path
    host = host.split("/")[0]
    if host.startswith("www."):
        host = host[4:]
    return host


def _is_public_host(host: str) -> bool:
    """SSRF guard: resolve host and reject private / loopback / reserved IPs."""
    try:
        infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError, OSError):
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return False
    return True


def _dedupe(urls: list, skip_noise: bool = True) -> list:
    """Keep http(s) only, drop duplicates, preserve order.

    skip_noise drops icon/sprite/tracking junk — wanted for creatives, but
    NOT for logos (where icons/favicons are exactly what we want).
    """
    seen, out = set(), []
    for u in urls:
        if not u or not u.startswith(("http://", "https://")):
            continue
        if skip_noise and _SKIP_PATTERNS.search(u):
            continue
        if u in seen:
            continue
        seen.add(u)
        out.append(u)
    return out


def _brandfetch_logos(domain: str) -> list:
    """High-quality logos via Brandfetch, only if a key is configured."""
    key = os.environ.get("BRANDFETCH_API_KEY")
    if not key:
        return []
    try:
        r = requests.get(
            f"https://api.brandfetch.io/v2/brands/{domain}",
            headers={"Authorization": f"Bearer {key}", "User-Agent": UA},
            timeout=TIMEOUT,
        )
        if not r.ok:
            return []
        urls = []
        for logo in r.json().get("logos", []):
            for fmt in logo.get("formats", []):
                if fmt.get("src"):
                    urls.append(fmt["src"])
        return urls
    except requests.RequestException:
        return []


def fetch_brand_assets(domain_input: str) -> dict:
    domain = normalize_domain(domain_input)
    if not domain or "." not in domain:
        return {"error": "Enter a valid brand domain, e.g. nike.com"}

    logos = _brandfetch_logos(domain)
    creatives: list = []

    # One homepage fetch feeds both logo and creative discovery.
    try:
        r = requests.get(f"https://{domain}", headers={"User-Agent": UA}, timeout=TIMEOUT)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        base = str(r.url)

        # Square brand marks — apple-touch-icon is almost always a clean logo.
        for sel, attr in [
            ('link[rel="apple-touch-icon"]', "href"),
            ('link[rel="apple-touch-icon-precomposed"]', "href"),
            ('link[rel="icon"]', "href"),
            ('link[rel="shortcut icon"]', "href"),
            ('link[rel="mask-icon"]', "href"),
        ]:
            for tag in soup.select(sel):
                if tag.get(attr):
                    logos.append(urljoin(base, tag[attr]))

        # Creatives: the brand's chosen social-preview "hero" shots first.
        for sel, attr in [
            ('meta[property="og:image"]', "content"),
            ('meta[property="og:image:secure_url"]', "content"),
            ('meta[name="twitter:image"]', "content"),
            ('link[rel="image_src"]', "href"),
        ]:
            for tag in soup.select(sel):
                if tag.get(attr):
                    creatives.append(urljoin(base, tag[attr]))

        # Then prominent inline images.
        for img in soup.find_all("img"):
            src = img.get("src") or img.get("data-src")
            if not src:
                srcset = img.get("data-srcset") or img.get("srcset") or ""
                src = srcset.split()[0] if srcset.split() else None
            if src:
                creatives.append(urljoin(base, src))
    except requests.RequestException:
        pass

    # Guaranteed keyless logo backstop.
    logos.append(f"https://www.google.com/s2/favicons?domain={domain}&sz=256")

    return {
        "domain": domain,
        "logos": _dedupe(logos, skip_noise=False),
        "creatives": _dedupe(creatives)[:MAX_CREATIVES],
    }


def proxy_image(url: str):
    """
    Fetch an external image server-side. Returns (bytes, content_type) or
    (None, error_message). Guards scheme, host, content-type, and size.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None, "Invalid URL"
    if not _is_public_host(parsed.hostname):
        return None, "Blocked host"
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=TIMEOUT, stream=True)
        r.raise_for_status()
    except requests.RequestException as e:
        return None, f"Fetch failed: {e}"

    ctype = r.headers.get("Content-Type", "")
    if not ctype.startswith("image/"):
        return None, "Not an image"

    chunks, total = [], 0
    for chunk in r.iter_content(8192):
        total += len(chunk)
        if total > MAX_IMAGE_BYTES:
            return None, "Image too large"
        chunks.append(chunk)
    return b"".join(chunks), ctype
