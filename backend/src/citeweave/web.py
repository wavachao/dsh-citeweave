"""Public web retrieval. URLs are validated before every fetch and redirect."""

import hashlib
import http.client
import ipaddress
import os
import socket
import ssl
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup

from . import config

USER_AGENT = "CiteWeave/0.1 (+https://github.com/wavachao/citeweave; source-linked search)"


class NoEvidenceError(ValueError):
    """A completed retrieval produced no readable evidence."""

    def __init__(self, errors):
        super().__init__("No readable sources retrieved; try explicit public webpage URLs")
        self.errors = errors or [{"url": "", "error": "No matching web results were found."}]


def _doh_address(hostname):
    with httpx.Client(timeout=12) as client:
        response = client.get("https://dns.google/resolve", params={"name": hostname, "type": "A"})
        response.raise_for_status()
        addresses = [a["data"] for a in response.json().get("Answer", []) if a.get("type") == 1]
    if not addresses or any(not ipaddress.ip_address(a).is_global for a in addresses):
        raise ValueError("No public origin address found")
    return addresses[0]


def _public_address(url):
    parsed = urlsplit(url)
    if (
        parsed.scheme not in ("http", "https")
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise ValueError("Only public HTTP(S) URLs without credentials are allowed")
    if parsed.port not in (None, 80, 443):
        raise ValueError("Custom network ports are not allowed")
    try:
        literal = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        literal = None
    if literal is not None and not literal.is_global:
        raise ValueError("Nonpublic IP literals are blocked")
    if literal is None and os.getenv("CITEWEAVE_DOH", "0") == "1":
        return _doh_address(parsed.hostname)
    ips = socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)
    addresses = [entry[4][0] for entry in ips]
    fake_net = ipaddress.ip_network("198.18.0.0/15")
    if addresses and all(ipaddress.ip_address(a) in fake_net for a in addresses):
        # Clash fake-IP DNS is not an origin address. Resolve via a fixed trusted
        # DoH endpoint, then apply the same public-address check and IP pinning.
        return _doh_address(parsed.hostname)
    if not ips or any(not ipaddress.ip_address(entry[4][0]).is_global for entry in ips):
        raise ValueError("Private, loopback, link-local and reserved destinations are blocked")
    return next((entry[4][0] for entry in ips if entry[0] == socket.AF_INET), ips[0][4][0])


def public_url(url):
    _public_address(url)
    return url


def fetch(url, image=False):
    for _ in range(5):
        address = _public_address(url)
        normalized = httpx.URL(url)
        parsed = urlsplit(str(normalized))
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        proxy = os.getenv("https_proxy") or os.getenv("HTTPS_PROXY") or os.getenv("http_proxy")
        proxy_url = urlsplit(proxy) if proxy else None
        if proxy_url and proxy_url.scheme != "http":
            raise ValueError("Use an HTTP CONNECT proxy for web retrieval")
        conn = http.client.HTTPConnection(
            proxy_url.hostname if proxy_url else address,
            (proxy_url.port or 80) if proxy_url else port,
            timeout=20,
        )
        try:
            if proxy_url and parsed.scheme == "https":
                tunnel_headers = {}
                if proxy_url.username:
                    import base64
                    from urllib.parse import unquote

                    auth = f"{unquote(proxy_url.username)}:{unquote(proxy_url.password or '')}"
                    tunnel_headers["Proxy-Authorization"] = (
                        "Basic " + base64.b64encode(auth.encode()).decode()
                    )
                conn.set_tunnel(address, port, tunnel_headers)
            conn.connect()
            if parsed.scheme == "https":
                # Pin the validated IP, while checking TLS against the real site.
                # No hostname checks or certificate validation are disabled.
                conn.sock = ssl.create_default_context().wrap_socket(
                    conn.sock, server_hostname=parsed.hostname
                )
            target = normalized.raw_path.decode("ascii")
            if proxy_url and parsed.scheme == "http":
                target = str(normalized.copy_with(host=address))
            conn.request(
                "GET",
                target,
                headers={
                    "User-Agent": USER_AGENT,
                    "Host": parsed.netloc,
                    "Accept-Encoding": "identity",
                },
            )
            response = conn.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                url = urljoin(url, response.getheader("Location", ""))
                continue
            if response.status >= 400:
                raise ValueError(f"HTTP {response.status} while retrieving {url}")
            ctype = response.getheader("Content-Type", "").split(";")[0].lower()
            if image and ctype not in ("image/jpeg", "image/png", "image/webp", "image/gif"):
                raise ValueError("Unsupported image type")
            if not image and ctype not in ("text/html", "application/xhtml+xml"):
                raise ValueError("Expected an HTML page")
            limit = 12_000_000 if image else 4_000_000
            payload = response.read(limit + 1)
            if len(payload) > limit:
                raise ValueError("Resource exceeds download limit")
            return payload, url, ctype
        except http.client.HTTPException as e:
            raise ValueError(f"HTTP retrieval failed: {type(e).__name__}") from e
        finally:
            conn.close()
    raise ValueError("Too many redirects")


def search(query, limit=5):
    endpoint = os.getenv("SEARXNG_URL")
    if endpoint:
        # SearXNG is an administrator-configured backend, never user-supplied.
        with httpx.Client(timeout=30) as client:
            r = client.get(endpoint.rstrip("/") + "/search", params={"q": query, "format": "json"})
            r.raise_for_status()
            return [
                {"url": d["url"], "title": d.get("title", "")} for d in r.json()["results"][:limit]
            ]
    from ddgs import DDGS
    from ddgs.exceptions import DDGSException

    try:
        return [
            {"url": r["href"], "title": r["title"]}
            for r in DDGS(timeout=20).text(query, max_results=limit)
        ]
    except DDGSException as exc:
        if str(exc).strip() == "No results found.":
            return []
        raise


def extract_page(html, url, sid):
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else urlsplit(url).hostname
    for node in soup(["script", "style", "nav", "footer", "header", "noscript", "form"]):
        node.decompose()
    main = soup.find("article") or soup.find("main") or soup.body or soup
    images, urls = [], set()
    for img in main.find_all("img"):
        raw = img.get("data-src") or img.get("src") or ""
        target = urljoin(url, raw)
        if not raw or target in urls or urlsplit(target).scheme not in ("http", "https"):
            continue
        alt = str(img.get("alt", "")).strip()
        if any(
            w in (target + " " + alt).lower()
            for w in ("logo", "avatar", "tracking", "pixel.gif", "icon")
        ):
            continue
        if any(
            str(img.get(key, "")).isdigit() and int(img[key]) < 100 for key in ("width", "height")
        ):
            continue
        figure = img.find_parent("figure")
        caption_node = figure.find("figcaption") if figure else None
        caption = caption_node.get_text(" ", strip=True) if caption_node else alt
        images.append(
            {
                "id": "",
                "url": target,
                "caption": caption,
                "source_id": sid,
                "source_url": url,
                "caption_kind": "publisher_caption" if caption else "unverified",
            }
        )
        urls.add(target)
        if len(images) == 8:
            break
    paragraphs = [n.get_text(" ", strip=True) for n in main.find_all(["h1", "h2", "h3", "p", "li"])]
    text = "\n\n".join(p for p in paragraphs if len(p) > 20)[:50000]
    return {"id": sid, "title": title, "url": url, "text": text}, images


def retrieve(query, urls=None):
    results = [{"url": url} for url in urls] if urls else search(query)
    sources, images, errors = [], [], []
    for result in results[:5]:
        try:
            html, final, _ = fetch(result["url"])
            source, found = extract_page(html, final, f"s{len(sources)}")
            if not source["text"]:
                continue
            sources.append(source)
            images.extend(found)
        except (httpx.HTTPError, ValueError, OSError) as e:
            errors.append({"url": result["url"], "error": str(e)[:250]})
    if not sources:
        raise NoEvidenceError(errors)
    for i, image in enumerate(images):
        image["id"] = f"i{i}"
    return sources, images, errors


def cache_image(url):
    from io import BytesIO

    from PIL import Image, ImageOps

    digest = hashlib.sha256(url.encode()).hexdigest()
    path = config.DATA / "cache/images" / (digest + ".jpg")
    if not path.exists():
        payload, _, _ = fetch(url, image=True)
        with Image.open(BytesIO(payload)) as image:
            if image.width * image.height > 40_000_000:
                raise ValueError("Image resolution exceeds the limit")
            image = ImageOps.exif_transpose(image).convert("RGB")
            image.thumbnail((1024, 1024))
            path.parent.mkdir(parents=True, exist_ok=True)
            image.save(path, "JPEG", quality=90)
    return path
