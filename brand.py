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
# More browser-like headers for homepage fetches — reduces (doesn't eliminate)
# datacenter bot-walls that serve stripped pages to plain server requests.
BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
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


_DOMAIN_RE = re.compile(r"^(?:https?://)?(?:www\.)?[a-z0-9-]+(?:\.[a-z0-9-]+)+/?$", re.IGNORECASE)


def _looks_like_domain(query: str) -> bool:
    """True if the input is already a domain/URL (e.g. 'nike.com'), not a name."""
    return bool(_DOMAIN_RE.match(query.strip()))


def _clearbit_suggest(name: str) -> tuple:
    """Brand name -> (domain, canonical name) via Clearbit's keyless autocomplete."""
    try:
        r = requests.get(
            "https://autocomplete.clearbit.com/v1/companies/suggest",
            params={"query": name}, headers={"User-Agent": UA}, timeout=TIMEOUT,
        )
        if r.ok and r.json():
            top = r.json()[0]
            return top.get("domain", ""), top.get("name", "")
    except (requests.RequestException, ValueError):
        pass
    return "", ""


def _brandfetch_search(name: str) -> tuple:
    """Fallback brand name -> (domain, name) via Brandfetch's keyless search."""
    try:
        r = requests.get(
            f"https://api.brandfetch.io/v2/search/{name}",
            headers={"User-Agent": UA}, timeout=TIMEOUT,
        )
        if r.ok and r.json():
            top = r.json()[0]
            return top.get("domain", ""), top.get("name", "")
    except (requests.RequestException, ValueError):
        pass
    return "", ""


def resolve_domain(query: str) -> tuple:
    """Accept a brand name OR a domain; return (domain, display_name)."""
    query = (query or "").strip()
    if not query:
        return "", ""
    if _looks_like_domain(query):
        return normalize_domain(query), ""
    domain, name = _clearbit_suggest(query)
    if not domain:
        domain, name = _brandfetch_search(query)
    return domain, name


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


def _brandfetch_parse(data: dict) -> tuple:
    """Pull (logo_urls, image_urls) from a Brandfetch v2 brand payload."""
    def first_src(entry):
        for fmt in entry.get("formats", []):
            if fmt.get("src"):
                return fmt["src"]
        return None

    # One src per asset (primary format) to avoid near-duplicate thumbnails.
    logos = [s for s in (first_src(l) for l in data.get("logos", [])) if s]
    # `images` holds real brand imagery (banners etc.) — our best creatives,
    # and they serve from a CDN so they survive datacenter bot-walls.
    images = [s for s in (first_src(i) for i in data.get("images", [])) if s]
    return logos, images


def _brandfetch_assets(domain: str) -> tuple:
    """High-quality (logos, brand images) via Brandfetch, only if a key is set."""
    key = os.environ.get("BRANDFETCH_API_KEY")
    if not key:
        return [], []
    try:
        r = requests.get(
            f"https://api.brandfetch.io/v2/brands/{domain}",
            headers={"Authorization": f"Bearer {key}", "User-Agent": UA},
            timeout=TIMEOUT,
        )
        if not r.ok:
            return [], []
        return _brandfetch_parse(r.json())
    except (requests.RequestException, ValueError):
        return [], []


def fetch_brand_assets(query: str) -> dict:
    domain, name = resolve_domain(query)
    if not domain or "." not in domain:
        return {"error": f"Couldn't find a brand for '{query.strip()}'. Try the website (e.g. nike.com)."}

    bf_logos, bf_images = _brandfetch_assets(domain)
    logos = list(bf_logos)
    social_imgs: list = []   # og:image / twitter:image — often just the brand card (= logo)
    content_imgs: list = []  # real inline <img> hero shots

    # One homepage fetch feeds both logo and creative discovery.
    try:
        r = requests.get(f"https://{domain}", headers=BROWSER_HEADERS, timeout=TIMEOUT)
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

        # Social-preview images — kept as fallback only (frequently the logo on a card).
        for sel, attr in [
            ('meta[property="og:image"]', "content"),
            ('meta[property="og:image:secure_url"]', "content"),
            ('meta[name="twitter:image"]', "content"),
            ('link[rel="image_src"]', "href"),
        ]:
            for tag in soup.select(sel):
                if tag.get(attr):
                    social_imgs.append(urljoin(base, tag[attr]))

        # Prominent inline images — the real creatives.
        for img in soup.find_all("img"):
            src = img.get("src") or img.get("data-src")
            if not src:
                srcset = img.get("data-srcset") or img.get("srcset") or ""
                src = srcset.split()[0] if srcset.split() else None
            if src:
                content_imgs.append(urljoin(base, src))
    except requests.RequestException:
        pass

    # Guaranteed keyless logo backstop.
    logos.append(f"https://www.google.com/s2/favicons?domain={domain}&sz=256")

    logo_urls = _dedupe(logos, skip_noise=False)
    logo_set = set(logo_urls)
    # Brandfetch brand images are the most reliable real creatives — rank first.
    bf_content = [u for u in _dedupe(bf_images) if u not in logo_set]
    scraped_content = [u for u in _dedupe(content_imgs) if u not in logo_set and u not in bf_content]
    content = bf_content + scraped_content
    social = [u for u in _dedupe(social_imgs) if u not in logo_set and u not in content]

    # Real content images first; the social card only as a last-resort option.
    creatives = (content + social)[:MAX_CREATIVES]

    return {
        "domain": domain,
        "name": name or domain,
        "logos": logo_urls,
        "creatives": creatives,
        # True only when we found a genuine content image (Brandfetch brand image
        # or inline hero) — safe to auto-fill media. When false, the only
        # "creative" is the brand card, so we don't auto-fill the logo's twin.
        "has_content_creative": bool(content),
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
