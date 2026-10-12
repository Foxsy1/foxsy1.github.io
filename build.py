#!/usr/bin/env python3
"""Generate a static Stremio/Nuvio metadata catalog from PUBLIC listings only.

No authentication, stream scraping, paywall access, or DRM handling.
Only newly found titles are appended to state.json; removals require checking manually.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse, urldefrag
from urllib.robotparser import RobotFileParser
from xml.etree import ElementTree

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
STATE_FILE = ROOT / "state.json"
OUT = ROOT / "public"
OFFICIAL = "https://oceanveil.net"
SECONDARY = "https://manhwaindex.com/platform/oceanveil"
UA = "OceanVeilCatalogBot/1.0 (personal metadata catalog; public pages only)"
PAGE_TIMEOUT = 20
RATE_DELAY = 1.0  # Limit requests to each source
MAX_SITEMAP_LINKS = 180  # Keep first run modest
URL_PATTERN = re.compile(r"^/anime_titles/(\d+)(?:/)?$")


def pages_base_url() -> str:
    if os.environ.get("PAGES_BASE_URL"):
        return os.environ["PAGES_BASE_URL"].rstrip("/")
    repo = os.environ.get("GITHUB_REPOSITORY", "example/oceanveil-auto-catalog")
    owner, name = repo.split("/", 1)
    return f"https://{owner}.github.io/{name}".rstrip("/")


class GentleFetcher:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": UA, "Accept": "text/html,application/xml;q=0.9,*/*;q=0.7"})
        self.robots: dict[str, RobotFileParser | None] = {}
        self.last_request: dict[str, float] = {}

    def allowed(self, url: str) -> bool:
        p = urlparse(url)
        host = f"{p.scheme}://{p.netloc}"
        if host not in self.robots:
            try:
                r = self.session.get(host + "/robots.txt", timeout=PAGE_TIMEOUT)
                if r.status_code == 200:
                    robots = RobotFileParser()
                    robots.parse(r.text.splitlines())
                    self.robots[host] = robots
                else:
                    self.robots[host] = None  # no readable policy
            except requests.RequestException:
                self.robots[host] = None
        rp = self.robots[host]
        return rp is None or rp.can_fetch(UA, url)

    def get(self, url: str) -> str | None:
        if not self.allowed(url):
            print("Blocked by robots.txt:", url)
            return None
        p = urlparse(url)
        host = p.netloc
        wait = RATE_DELAY - (time.monotonic() - self.last_request.get(host, 0))
        if wait > 0:
            time.sleep(wait)
        self.last_request[host] = time.monotonic()
        try:
            r = self.session.get(url, timeout=PAGE_TIMEOUT)
            r.raise_for_status()
            if len(r.content) > 5_000_000:
                print("Skipping overly large page", url)
                return None
            return r.text
        except requests.RequestException as e:
            print("Source unavailable:", url, str(e)[:140])
            return None


def absolute_media(raw: str | None, origin: str) -> str:
    if not raw:
        return ""
    u = urljoin(origin, raw.strip())
    return u if urlparse(u).scheme in {"https", "http"} else ""


def title_ok(value: str | None) -> bool:
    if not value:
        return False
    value = " ".join(value.split())
    if not (2 < len(value) < 250):
        return False
    generic = {"welcome", "image", "all titles", "watch now", "watch", "anime", "more", "details", "read more", "newly streaming", "oceanveil"}
    return value.lower() not in generic and "oceanveil watch anime" not in value.lower() and "dive for anime" not in value.lower()


def clean_title(value: str | None) -> str:
    t = " ".join((value or "").split())
    t = re.sub(r"^Cover of\s+", "", t, flags=re.I)
    t = re.sub(r"\s*\|\s*OceanVeil.*$", "", t, flags=re.I)
    return t if title_ok(t) else ""


def ocean_id(url: str) -> str:
    p = urlparse(url)
    if p.netloc not in {"oceanveil.net", "www.oceanveil.net"}:
        return ""
    m = URL_PATTERN.fullmatch(p.path)
    return m.group(1) if m else ""


def details_from_official(html: str, url: str) -> tuple[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    name = ""
    for css in ['meta[property="og:title"]', 'meta[name="twitter:title"]']:
        node = soup.select_one(css)
        name = clean_title(node.get("content") if node else "")
        if name:
            break
    if not name:
        for css in ["main h1", "main h2", "h1"]:
            node = soup.select_one(css)
            name = clean_title(node.get_text(" ", strip=True) if node else "")
            if name and not re.search(r"^(niche anime|unedited titles)", name, flags=re.I):
                break
            name = ""
    poster = ""
    for css in ['meta[property="og:image"]', 'meta[name="twitter:image"]']:
        node = soup.select_one(css)
        poster = absolute_media(node.get("content") if node else "", url)
        if poster:
            break
    return name, poster


def official_cards(html: str, page_url: str) -> dict[str, dict]:
    soup = BeautifulSoup(html, "html.parser")
    result = {}
    for a in soup.select('a[href]'):
        href = urljoin(page_url, a.get("href", ""))
        oid = ocean_id(href)
        if not oid:
            continue
        img = a.find("img")
        title = clean_title(img.get("alt") if img else None) or clean_title(a.get_text(" ", strip=True))
        # Some sites wrap the title next to the linked poster.
        if not title:
            parent = a.parent
            if parent:
                for h in parent.select("h2,h3,h4"):
                    title = clean_title(h.get_text(" ", strip=True))
                    if title:
                        break
        if title:
            poster = ""
            if img:
                poster = absolute_media(img.get("data-src") or img.get("src"), page_url)
            result[oid] = {"title": title, "poster": poster, "url": f"{OFFICIAL}/anime_titles/{oid}"}
    return result


def scan_sitemaps(fetcher: GentleFetcher) -> list[str]:
    candidates = [OFFICIAL + "/sitemap.xml", OFFICIAL + "/sitemap_index.xml"]
    seen = set()
    urls = []
    while candidates and len(seen) < 16:
        url = candidates.pop(0)
        if url in seen:
            continue
        seen.add(url)
        xml = fetcher.get(url)
        if not xml:
            continue
        try:
            root = ElementTree.fromstring(xml)
        except ElementTree.ParseError:
            continue
        for loc in root.findall(".//{*}loc"):
            if not loc.text:
                continue
            value = loc.text.strip()
            if ocean_id(value):
                urls.append(value)
            elif value.endswith(".xml") and value.startswith(OFFICIAL) and len(seen) + len(candidates) < 16:
                candidates.append(value)
    return list(dict.fromkeys(urls))[:MAX_SITEMAP_LINKS]


def secondary_index(fetcher: GentleFetcher) -> dict[str, dict]:
    """The third-party index publicly shows only a subset (e.g. 24 of 104)."""
    html = fetcher.get(SECONDARY)
    if not html:
        return {}
    soup = BeautifulSoup(html, "html.parser")
    paths = []
    for a in soup.select("a[href]"):
        p = urlparse(urljoin(SECONDARY, a.get("href", "")))
        if p.netloc == "manhwaindex.com" and re.fullmatch(r"/anime/[^/]+", p.path):
            paths.append(f"https://manhwaindex.com{p.path}")
    paths = list(dict.fromkeys(paths))[:30]
    result = {}
    for path in paths:
        body = fetcher.get(path)
        if not body:
            continue
        page = BeautifulSoup(body, "html.parser")
        h1 = page.find("h1")
        title = clean_title(h1.get_text(" ", strip=True)) if h1 else ""
        if not title:
            continue
        poster = ""
        for img in page.find_all("img"):
            if "cover" in (img.get("alt") or "").lower():
                poster = absolute_media(img.get("src") or img.get("data-src"), path)
                if poster:
                    break
        if not poster:
            og = page.select_one('meta[property="og:image"]')
            poster = absolute_media(og.get("content") if og else "", path)
        for a in page.select('a[href]'):
            link = urljoin(path, a.get("href", ""))
            oid = ocean_id(link)
            if oid:
                result[oid] = {"title": title, "poster": poster, "url": f"{OFFICIAL}/anime_titles/{oid}"}
                break
    print("Secondary index provided", len(result), "linked titles")
    return result


def read_old_state() -> dict[str, dict]:
    if not STATE_FILE.exists():
        return {}
    data = json.loads(STATE_FILE.read_text(encoding="utf8"))
    return {str(k): v for k, v in data.get("titles", {}).items()}


def dump_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf8")


def build() -> None:
    fetcher = GentleFetcher()
    old = read_old_state()
    fresh = secondary_index(fetcher)

    seen = {}
    for page in [OFFICIAL + "/", OFFICIAL + "/anime_titles"]:
        html = fetcher.get(page)
        if html:
            seen.update(official_cards(html, page))
    fresh.update({k: v for k, v in seen.items() if k not in fresh})
    print("Official pages provided", len(seen), "linked titles")

    # Sitemaps can discover entries that are absent from the landing page.
    for url in scan_sitemaps(fetcher):
        oid = ocean_id(url)
        if not oid or oid in fresh or oid in old:
            continue
        html = fetcher.get(url)
        if not html:
            continue
        title, poster = details_from_official(html, url)
        if title:
            fresh[oid] = {"title": title, "poster": poster, "url": f"{OFFICIAL}/anime_titles/{oid}"}

    if not old and not fresh:
        raise RuntimeError("No public titles could be discovered; no empty addon will be published. Check access/logs.")

    titles = dict(old)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for oid, record in fresh.items():
        if not title_ok(record.get("title")):
            continue
        previous = titles.get(oid, {})
        titles[oid] = {
            "title": record["title"],
            "poster": record.get("poster") or previous.get("poster", ""),
            "url": record["url"],
            "first_seen": previous.get("first_seen", today),
            "last_seen": today,
        }
    dump_json(STATE_FILE, {"titles": titles})

    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    shutil.copy(ROOT / "static" / "placeholder.png", OUT / "placeholder.png")
    (OUT / ".nojekyll").touch()

    base_url = pages_base_url()
    manifest = {
        "id": "community.oceanveil.auto.catalog",
        "version": "1.0.0",
        "name": "OceanVeil Auto Catalog",
        "description": "Automatically refreshed public OceanVeil title directory. Catalog only: no video streams.",
        "resources": ["catalog", {"name": "meta", "types": ["series"], "idPrefixes": ["oceanveil:"]}],
        "types": ["series"],
        "catalogs": [{"type": "series", "id": "oceanveil-anime", "name": "OceanVeil Anime", "extra": [{"name": "skip", "isRequired": False}]}],
        "idPrefixes": ["oceanveil:"],
        "behaviorHints": {"configurable": False},
    }
    dump_json(OUT / "manifest.json", manifest)

    listing = []
    for oid, data in sorted(titles.items(), key=lambda kv: (kv[1]["first_seen"], int(kv[0]) if kv[0].isdigit() else 0), reverse=True):
        item_id = f"oceanveil:{oid}"
        poster = data.get("poster") or f"{base_url}/placeholder.png"
        item = {"id": item_id, "type": "series", "name": data["title"], "poster": poster}
        listing.append(item)
        meta = {**item,
                "description": "Listed on OceanVeil. This directory does not supply video streams. Open the official site to check subscription and regional availability.",
                "website": data["url"],
                "links": [{"name": "Official OceanVeil page", "category": "watch", "url": data["url"]}],
                "videos": [],
                }
        dump_json(OUT / "meta" / "series" / f"{item_id}.json", {"meta": meta})
    # Stremio generally requests 100 results at a time and stops at a shorter page.
    # We generate a terminal empty page for exactly-multiple-of-100 catalogs.
    page_len = 100
    for skip in range(0, len(listing) + page_len, page_len):
        result = {"metas": listing[skip:skip + page_len]}
        catalog_dir = OUT / "catalog" / "series"
        if skip == 0:
            dump_json(catalog_dir / "oceanveil-anime.json", result)
        dump_json(catalog_dir / "oceanveil-anime" / f"skip={skip}.json", result)
    dump_json(OUT / "status.json", {"known_title_count": len(listing), "new_discoveries_this_run": len(set(fresh) - set(old)), "updated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "notes": "Metadata-only; title coverage can be partial. Removed titles are not automatically deleted."})
    print(f"Generated {len(listing)} catalog titles. New this run: {len(set(fresh) - set(old))}. Base URL: {base_url}")


if __name__ == "__main__":
    build()
