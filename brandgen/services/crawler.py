"""Website crawler — pulls text, images, CSS colors/fonts, and logo candidates."""

from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (compatible; BrandGenBot/1.0; +https://example.com/bot)"
)
HEX_RE = re.compile(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})\b")
RGB_RE = re.compile(
    r"rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})(?:\s*,\s*[\d.]+)?\s*\)"
)
FONT_RE = re.compile(r"font-family\s*:\s*([^;}{]+)", re.IGNORECASE)

SKIP_EXTENSIONS = (".svg", ".gif", ".ico", ".webp")  # we still allow webp for products


@dataclass
class CrawlResult:
    url: str
    name: str = ""
    pages: list[dict] = field(default_factory=list)
    colors: list[str] = field(default_factory=list)
    fonts: list[str] = field(default_factory=list)
    logo_candidates: list[str] = field(default_factory=list)
    images: list[dict] = field(default_factory=list)
    summary_text: str = ""


def _normalize_hex(value: str) -> str | None:
    value = value.lower().strip()
    if not value.startswith("#"):
        return None
    if len(value) == 4:
        value = "#" + "".join(c * 2 for c in value[1:])
    if len(value) != 7:
        return None
    # Drop near-white / near-black noise later; keep everything for ranking
    return value


def _rgb_to_hex(r: int, g: int, b: int) -> str:
    return f"#{r:02x}{g:02x}{b:02x}"


def _is_boring_color(hex_color: str) -> bool:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    # pure white / black / near-gray
    if max(r, g, b) - min(r, g, b) < 18 and (max(r, g, b) > 230 or min(r, g, b) < 30):
        return True
    if hex_color in {"#ffffff", "#000000", "#fff", "#000"}:
        return True
    return False


def _extract_colors(html: str, css_blobs: Iterable[str]) -> list[str]:
    counter: Counter[str] = Counter()
    blobs = [html, *css_blobs]
    for blob in blobs:
        for match in HEX_RE.findall(blob):
            normalized = _normalize_hex(match)
            if normalized and not _is_boring_color(normalized):
                counter[normalized] += 1
        for r, g, b in RGB_RE.findall(blob):
            hex_color = _rgb_to_hex(int(r), int(g), int(b))
            if not _is_boring_color(hex_color):
                counter[hex_color] += 1
    return [c for c, _ in counter.most_common(8)]


def _extract_fonts(css_blobs: Iterable[str]) -> list[str]:
    counter: Counter[str] = Counter()
    for blob in css_blobs:
        for match in FONT_RE.findall(blob):
            # take first family name, strip quotes
            family = match.split(",")[0].strip().strip("'\"")
            if family.lower() in {"inherit", "initial", "sans-serif", "serif", "monospace", "system-ui"}:
                continue
            if family:
                counter[family] += 1
    return [f for f, _ in counter.most_common(5)]


def _guess_logo_urls(soup: BeautifulSoup, base_url: str) -> list[str]:
    """Prefer visible logo <img> / apple-touch icons over tiny favicons."""
    logo_imgs: list[str] = []
    apple_icons: list[str] = []
    favicons: list[str] = []

    for img in soup.find_all("img"):
        attrs = " ".join(
            str(img.get(a, "")).lower()
            for a in ("src", "alt", "class", "id", "title")
        )
        if "logo" in attrs:
            src = img.get("src") or img.get("data-src") or img.get("data-lazy-src")
            if src and not src.startswith("data:"):
                logo_imgs.append(urljoin(base_url, src))

    header = soup.find("header") or soup.find(class_=re.compile(r"header|nav", re.I))
    if header:
        img = header.find("img")
        if img:
            src = img.get("src") or img.get("data-src")
            if src and not src.startswith("data:"):
                logo_imgs.insert(0, urljoin(base_url, src))

    for link in soup.find_all("link", href=True):
        rel = link.get("rel")
        rel_s = " ".join(rel).lower() if isinstance(rel, list) else str(rel or "").lower()
        href = urljoin(base_url, link["href"])
        if "apple-touch-icon" in rel_s:
            apple_icons.append(href)
        elif "icon" in rel_s:
            favicons.append(href)

    # og:image sometimes is a brand mark
    og = soup.find("meta", property="og:image")
    if og and og.get("content"):
        apple_icons.append(urljoin(base_url, og["content"]))

    ordered = logo_imgs + apple_icons + favicons
    seen: set[str] = set()
    unique: list[str] = []
    for url in ordered:
        if url not in seen:
            seen.add(url)
            unique.append(url)
    return unique[:8]


def _collect_images(soup: BeautifulSoup, base_url: str, limit: int = 12) -> list[dict]:
    results: list[dict] = []
    seen: set[str] = set()

    # Also pick up og:image and link images
    og = soup.find("meta", property="og:image")
    if og and og.get("content"):
        results.append(
            {
                "url": urljoin(base_url, og["content"]),
                "alt": "og:image",
                "label": "photo",
            }
        )
        seen.add(results[0]["url"])

    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or img.get("data-lazy-src")
        if not src or src.startswith("data:"):
            continue
        full = urljoin(base_url, src)
        if full in seen:
            continue
        seen.add(full)
        alt = (img.get("alt") or "").strip()
        attrs = " ".join(
            str(img.get(a, "")).lower() for a in ("src", "alt", "class", "id")
        )
        label = "other"
        if "logo" in attrs:
            label = "logo"
        elif any(k in attrs for k in ("product", "mockup", "screenshot", "app")):
            label = "product"
        elif any(k in attrs for k in ("hero", "photo", "team", "people")):
            label = "photo"
        results.append({"url": full, "alt": alt, "label": label})
        if len(results) >= limit:
            break
    return results


def _same_domain(base: str, link: str) -> bool:
    return urlparse(base).netloc == urlparse(link).netloc


def _fetch(session: requests.Session, url: str, timeout: int = 20) -> str | None:
    try:
        resp = session.get(url, timeout=timeout)
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "")
        if "text" not in content_type and "html" not in content_type and "css" not in content_type:
            return None
        return resp.text
    except requests.RequestException as exc:
        logger.warning("Fetch failed for %s: %s", url, exc)
        return None


def _fetch_css(session: requests.Session, soup: BeautifulSoup, base_url: str, limit: int = 4) -> list[str]:
    blobs: list[str] = []
    # inline styles
    for style in soup.find_all("style"):
        if style.string:
            blobs.append(style.string)
    # linked stylesheets (same domain preferred)
    links = []
    for link in soup.find_all("link", rel=lambda v: v and "stylesheet" in str(v).lower()):
        href = link.get("href")
        if href:
            links.append(urljoin(base_url, href))
    for href in links[:limit]:
        css = _fetch(session, href)
        if css:
            blobs.append(css)
    return blobs


def _page_text(soup: BeautifulSoup) -> str:
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = " ".join(soup.get_text(" ", strip=True).split())
    return text[:4000]


def _discover_links(soup: BeautifulSoup, base_url: str) -> list[str]:
    keywords = ("product", "case", "about", "feature", "solution", "service", "work")
    links: list[str] = []
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a["href"])
        if not _same_domain(base_url, href):
            continue
        path = urlparse(href).path.lower()
        label = (a.get_text() or "").lower()
        if any(k in path or k in label for k in keywords):
            links.append(href.split("#")[0].rstrip("/"))
    # dedupe
    seen: set[str] = set()
    out: list[str] = []
    for link in links:
        if link not in seen:
            seen.add(link)
            out.append(link)
    return out[:3]


def crawl_website(url: str, max_pages: int = 3) -> CrawlResult:
    """Crawl homepage + a few key internal pages and extract brand signals."""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    result = CrawlResult(url=url)
    to_visit = [url.rstrip("/")]
    visited: set[str] = set()
    all_css: list[str] = []
    all_text_parts: list[str] = []

    while to_visit and len(visited) < max_pages:
        page_url = to_visit.pop(0)
        if page_url in visited:
            continue
        html = _fetch(session, page_url)
        if not html:
            continue
        visited.add(page_url)
        soup = BeautifulSoup(html, "lxml")

        if not result.name:
            title = soup.title.string.strip() if soup.title and soup.title.string else ""
            og = soup.find("meta", property="og:site_name")
            result.name = (og.get("content") if og else None) or title.split("|")[0].split("–")[0].strip() or urlparse(url).netloc

        css_blobs = _fetch_css(session, soup, page_url)
        all_css.extend(css_blobs)

        text = _page_text(soup)
        all_text_parts.append(text)
        result.pages.append({"url": page_url, "title": result.name, "text": text[:1500]})

        result.logo_candidates.extend(_guess_logo_urls(soup, page_url))
        result.images.extend(_collect_images(soup, page_url))

        if len(visited) == 1:
            for link in _discover_links(soup, page_url):
                if link not in visited and link not in to_visit:
                    to_visit.append(link)

    # dedupe images / logos
    seen_img: set[str] = set()
    unique_images = []
    for img in result.images:
        if img["url"] not in seen_img:
            seen_img.add(img["url"])
            unique_images.append(img)
    result.images = unique_images[:15]

    seen_logo: set[str] = set()
    unique_logos = []
    for logo in result.logo_candidates:
        if logo not in seen_logo:
            seen_logo.add(logo)
            unique_logos.append(logo)
    result.logo_candidates = unique_logos[:5]

    result.colors = _extract_colors(" ".join(all_text_parts[:1]), all_css)
    # also scan homepage HTML colors if CSS sparse
    if len(result.colors) < 3 and result.pages:
        homepage_html = _fetch(session, url) or ""
        result.colors = _extract_colors(homepage_html, all_css)

    result.fonts = _extract_fonts(all_css)
    result.summary_text = "\n\n".join(all_text_parts)[:6000]

    if not result.colors:
        result.colors = ["#0f172a", "#2563eb", "#f8fafc"]
    if not result.fonts:
        result.fonts = ["Inter", "system-ui"]

    return result
