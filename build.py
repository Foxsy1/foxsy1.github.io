#!/usr/bin/env python3
"""Publish enriched OceanVeil anime catalogs with playback-friendly TMDB/IMDb IDs.

Optional direct streams can be supplied as explicit verified links in streams.json.
Live discovery remains best-effort; no extraction of protected streams.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import hashlib
import unicodedata
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse, urldefrag
from urllib.robotparser import RobotFileParser
from xml.etree import ElementTree

import requests
from bs4 import BeautifulSoup
from enrichment import Enricher, preview_metadata

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
    # GitHub Pages user/organization repositories deploy at the domain root.
    # Project repositories deploy under /<repository>/.
    # owner may contain mixed case, but the public domain is case-insensitive.
    host = f"{owner.lower()}.github.io"
    if name.lower() == host:
        return f"https://{host}"
    return f"https://{host}/{name}"


class GentleFetcher:
    def __init__(self):
        self.events = []
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
            self.events.append({"url": url, "result": "robots_denied"})
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
            self.events.append({"url": url, "result": "ok"})
            if len(r.content) > 5_000_000:
                print("Skipping overly large page", url)
                return None
            return r.text
        except requests.RequestException as e:
            print("Source unavailable:", url, str(e)[:140])
            self.events.append({"url": url, "result": f"error: {str(e)[:100]}"})
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


def rendered_official_cards(fetcher: GentleFetcher) -> dict[str, dict]:
    """Optional JS-rendered public listings (no accounts, cookies or stream requests).

    This is best-effort: a browser may still be blocked on CI. Only use it if
    the official site robots policy allows the relevant URLs.
    """
    if os.getenv("ENABLE_BROWSER_DISCOVERY") != "1":
        return {}
    if not fetcher.allowed(OFFICIAL + "/") or not fetcher.allowed(OFFICIAL + "/anime_titles"):
        print("Skipping rendered discovery: robots policy does not permit official page")
        return {}
    try:
        from playwright.sync_api import sync_playwright
        records = {}
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
            context = browser.new_context(viewport={"width": 1365, "height": 950})
            page = context.new_page()
            for url in [OFFICIAL + "/", OFFICIAL + "/anime_titles"]:
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=35000)
                    page.wait_for_timeout(2200)
                    # Catch cards that load after scrolling; bounded and polite.
                    for _ in range(4):
                        page.mouse.wheel(0, 900)
                        page.wait_for_timeout(400)
                    found = official_cards(page.content(), url)
                    print("Browser-rendered cards", url, len(found))
                    records.update(found)
                    fetcher.events.append({"url": url, "result": f"browser: {len(found)} titles"})
                except Exception as exc:
                    print("Browser page unavailable", url, repr(exc)[:180])
                    fetcher.events.append({"url": url, "result": f"browser_error: {str(exc)[:100]}"})
            browser.close()
        return records
    except Exception as exc:
        print("Browser fallback not available:", repr(exc)[:180])
        fetcher.events.append({"url": OFFICIAL, "result": f"browser_start_error: {str(exc)[:100]}"})
        return {}


def slug_key(title: str) -> str:
    """Stable ID for a seed title whose real OceanVeil page ID is not known."""
    text = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", text).strip("-")[:60]
    suffix = hashlib.sha256(title.casefold().encode("utf8")).hexdigest()[:8]
    return f"seed-{slug}-{suffix}"


def title_key(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii").lower())


def read_seed() -> dict[str, dict]:
    path = ROOT / "seed.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf8"))
    result = {}
    for item in data["titles"]:
        title = clean_title(item["title"])
        if not title:
            continue
        source_url = SECONDARY if item.get("source") == "index" else OFFICIAL + "/"
        result[slug_key(title)] = {
            "title": title, "poster": "", "url": source_url,
            "source": "starter-snapshot", "first_seen": "2026-10-12",
            "last_seen": "2026-10-12",
        }
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
    saved = read_old_state()
    seed = read_seed()
    titles = dict(seed)
    titles.update(saved)
    fresh = secondary_index(fetcher)

    seen = {}
    for page in [OFFICIAL + "/", OFFICIAL + "/anime_titles"]:
        html = fetcher.get(page)
        if html:
            seen.update(official_cards(html, page))
    fresh.update({k: v for k, v in seen.items() if k not in fresh})
    if not seen:
        seen.update(rendered_official_cards(fetcher))
        fresh.update({k: v for k, v in seen.items() if k not in fresh})
    print("Official pages provided", len(seen), "linked titles (including rendered fallback)")

    for url in scan_sitemaps(fetcher):
        oid = ocean_id(url)
        if not oid or oid in fresh or oid in titles:
            continue
        html = fetcher.get(url)
        if not html:
            continue
        title, poster = details_from_official(html, url)
        if title:
            fresh[oid] = {"title": title, "poster": poster, "url": f"{OFFICIAL}/anime_titles/{oid}"}

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    by_name = {title_key(v["title"]): k for k, v in titles.items()}
    fresh_usable = {}
    for oid, record in fresh.items():
        if not title_ok(record.get("title")):
            continue
        fresh_usable[oid] = record
        duplicate_key = by_name.get(title_key(record["title"]))
        previous = titles.get(oid) or (titles.get(duplicate_key, {}) if duplicate_key else {})
        if duplicate_key and duplicate_key != oid and duplicate_key.startswith("seed-"):
            del titles[duplicate_key]
        titles[oid] = {
            "title": record["title"],
            "poster": record.get("poster") or previous.get("poster", ""),
            "url": record["url"],
            "source": "live-discovery",
            "first_seen": previous.get("first_seen", today),
            "last_seen": today,
        }
        by_name[title_key(record["title"])] = oid

    if not titles:
        raise RuntimeError("No seed or saved records, and no live titles. Refusing to publish empty data.")
    # Enrich without requiring API keys. Never replace canonical matches with
    # an unverified fuzzy result, and preserve old enrichment on outages.
    enrichment = Enricher()
    prior_count = 0
    max_new = int(os.getenv("ENRICH_MAX_NEW", "45"))
    attempts = 0
    for key, record in titles.items():
        previous = dict(record.get("enrichment") or {})
        if previous.get("id") and previous.get("refresh_after", "") >= today:
            prior_count += 1
            continue
        if attempts >= max_new:
            continue
        attempts += 1
        updated = enrichment.enrich(record['title'], previous)
        if updated:
            record['enrichment'] = updated
    dump_json(STATE_FILE, {"titles": titles})

    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    shutil.copy(ROOT / "static" / "placeholder.png", OUT / "placeholder.png")
    (OUT / ".nojekyll").touch()
    base_url = pages_base_url()
    # Optional user-supplied direct streams. Keys are canonical video IDs, e.g.
    # tmdb:123:1:1; values are lists of {url, title} or {externalUrl, title}.
    # These are not discovered automatically and may require authorized access.
    stream_source = ROOT / "streams.json"
    try:
        streams_config = json.loads(stream_source.read_text(encoding='utf8')) if stream_source.exists() else {}
    except (OSError, ValueError) as e:
        print("Invalid streams.json:", e)
        streams_config = {}
    safe_streams = {}
    for video_id, entries in streams_config.items() if isinstance(streams_config, dict) else []:
        if not isinstance(video_id, str) or not isinstance(entries, list):
            continue
        valid = []
        for e in entries:
            if not isinstance(e, dict):
                continue
            u = e.get('url') or e.get('externalUrl')
            if not isinstance(u, str) or not u.startswith('https://'):
                continue
            item = {'title': str(e.get('title') or 'Watch')[:120]}
            if e.get('url'):
                item['url'] = u
            else:
                item['externalUrl'] = u
            valid.append(item)
        if valid:
            safe_streams[video_id] = valid
    resources = ['catalog', {"name": "meta", "types": ['series', 'movie'], "idPrefixes": ['oceanveil:', 'kitsu:']}]
    if safe_streams:
        # Only advertised if direct/official sources have been configured.
        # Ordinary matched TMDB/IMDb entries are still playable via other addons.
        prefixes = sorted({vid.removeprefix('movie:').split(':', 2)[0] + ':' + vid.removeprefix('movie:').split(':', 2)[1]
                           if vid.removeprefix('movie:').startswith('tmdb:') and len(vid.removeprefix('movie:').split(':')) > 1
                           else vid.removeprefix('movie:').split(':')[0]
                           for vid in safe_streams})
        resources.append({"name": "stream", "types": ["series", "movie"], "idPrefixes": prefixes})

    manifest = {
        "id": "community.oceanveil.auto.catalog",
        "version": "1.4.0",
        "name": "OceanVeil Anime",
        "description": "OceanVeil anime discovery catalog, compatible TMDB/IMDb/Kitsu IDs, TVDB/TMDB and MDBList enrichment. Playback uses your installed stream addons; optional direct links supported.",
        "resources": resources,
        "types": ['series', 'movie'],
        "catalogs": [
            {"type": "series", "id": "oceanveil-anime", "name": "OceanVeil Anime", "extra": []},
            {"type": "movie", "id": "oceanveil-movies", "name": "OceanVeil Movies", "extra": []},
        ],
        "behaviorHints": {"configurable": False},
    }
    dump_json(OUT / "manifest.json", manifest)

    grouped = {'series': [], 'movie': []}
    identifiers = set()
    match_counts = {'tmdb': 0, 'imdb': 0, 'kitsu': 0, 'oceanveil': 0}
    enrich_counts = {'tmdb_metadata': 0, 'tvdb_metadata': 0, 'mdb_ratings': 0}
    for oid, data in sorted(titles.items(), key=lambda kv: (kv[1].get('last_seen', ''), kv[1].get('first_seen', ''), kv[1]['title']), reverse=True):
        e = data.get('enrichment') or {}
        item_id = e.get('id') or f'oceanveil:{oid}'
        # Only TMDB movie IDs are allowed to appear in movie catalogs.
        typ = 'movie' if item_id.startswith('tmdb:') and e.get('tmdb_type') == 'movie' else 'series'
        if item_id in identifiers:
            continue
        identifiers.add(item_id)
        match_counts['tmdb' if item_id.startswith('tmdb:') else 'imdb' if item_id.startswith('tt') else 'kitsu' if item_id.startswith('kitsu:') else 'oceanveil'] += 1
        enrich_counts['tmdb_metadata'] += int(bool(e.get('description') and e.get('tmdb_id')))
        enrich_counts['tvdb_metadata'] += int(bool(e.get('tvdb_id')))
        enrich_counts['mdb_ratings'] += int(bool(e.get('ratings')))
        fallback = data.get('poster') or f'{base_url}/placeholder.png'
        meta_preview = preview_metadata(data['title'], e, fallback)
        preview = {'id': item_id, 'type': typ, **meta_preview}
        grouped[typ].append(preview)
        if item_id.startswith(('oceanveil:', 'kitsu:')):
            source_link = data.get('url') or OFFICIAL
            full = {**preview, 'website': source_link, 'videos': []}
            if ocean_id(source_link):
                full['links'] = [{'name': 'OceanVeil', 'category': 'watch', 'url': source_link}]
            dump_json(OUT / 'meta' / typ / f'{item_id}.json', {'meta': full})

    # Also produce the exact /skip=0.json route expected by some clients.
    for typ, catid in [('series', 'oceanveil-anime'), ('movie', 'oceanveil-movies')]:
        rows = grouped[typ]
        for skip in range(0, len(rows) + 100, 100):
            output = {'metas': rows[skip:skip + 100]}
            if skip == 0:
                dump_json(OUT / 'catalog' / typ / f'{catid}.json', output)
            dump_json(OUT / 'catalog' / typ / catid / f'skip={skip}.json', output)
    # Static playback endpoints for explicitly configured public or authorized URLs.
    for video_id, streams in safe_streams.items():
        kind = 'movie' if video_id.startswith('movie:') else 'series'
        # user may prefix movie: for route classification; strip prefix if present.
        normalized_id = video_id.removeprefix('movie:')
        dump_json(OUT / 'stream' / kind / f'{normalized_id}.json', {'streams': streams})
    listing = grouped['series'] + grouped['movie']
    live_count = sum(r.get("source") == "live-discovery" for r in titles.values())
    newly_found = sum(oid not in saved for oid in fresh_usable)
    status = {
        "known_title_count": len(listing),
        "starter_snapshot_count": len(seed),
        "stored_live_title_count": live_count,
        "live_titles_extracted_this_run": len(fresh_usable),
        "new_live_title_ids_this_run": newly_found,
        "updated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_checks": getattr(fetcher, "events", []),
        "addon_manifest_url": f"{base_url}/manifest.json",
        "catalog_url": f"{base_url}/catalog/series/oceanveil-anime.json",
        "build_version": manifest["version"],
        "identifier_counts": match_counts,
        "enrichment_counts": enrich_counts,
        "stream_endpoints": len(safe_streams),
        "metadata_apis_configured": {"tmdb": bool(enrichment.tmdb_key), "tvdb": bool(enrichment.tvdb_key), "mdblist": bool(enrichment.mdb_key)},
        "id_match_sources": enrichment.events,
        "unmatched_titles": [x['name'] for x in listing if x['id'].startswith('oceanveil:')][:50],
        "notes": ("Live sources provided titles this run." if fresh_usable else
                  "No live titles extracted this run. The seeded/saved list was published, "
                  "but discovery of future additions is not verified while source access is blocked."),
    }
    dump_json(OUT / "status.json", status)
    # The homepage includes direct test links, so a user can isolate publishing
    # faults before troubleshooting the Nuvio application or profile settings.
    page = ("<!doctype html><html lang='en'><meta charset='utf-8'><meta name='viewport' "
            "content='width=device-width,initial-scale=1'><title>OceanVeil Auto Catalog</title>"
            "<style>body{font:16px/1.6 system-ui;max-width:740px;margin:8vh auto;padding:20px;"
            "background:#101823;color:white}a{color:#9dc9ff}code{overflow-wrap:anywhere}"
            "li{padding:4px 0}</style>"
            f"<h1>OceanVeil Auto Catalog</h1><p>{len(listing)} catalog titles.</p>"
            "<ul><li><a href='manifest.json'>Addon manifest</a></li>"
            "<li><a href='catalog/series/oceanveil-anime.json'>Raw catalog JSON</a></li>"
            "<li><a href='catalog-preview.html'>Visual catalog preview</a></li>"
            "<li><a href='status.json'>Update status</a></li></ul>"
            f"<p>Install URL: <code>{base_url}/manifest.json</code></p>"
            "<p>If this site's preview works but the row is missing in Nuvio, reinstall "
            "the addon into the right Nuvio profile and enable its home catalog.</p>"
            "<p>Uses standard TMDB/IMDb/Kitsu IDs for compatibility with your installed "
            "metadata and stream addons. Optional stream endpoints need supplied sources. "
            "Live discovery may remain unavailable.</p></html>")
    (OUT / "index.html").write_text(page, encoding="utf8")
    preview = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>OceanVeil – catalog debug preview</title><style>
*{box-sizing:border-box}body{font-family:system-ui,sans-serif;background:#0b1523;color:#eef6ff;margin:0;padding:28px}
h1{margin:0 0 8px}a{color:#88cdff}p{color:#aec0d1}.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(142px,1fr));gap:20px}
article{background:#16263b;border-radius:12px;padding:10px;min-height:265px}img{width:100%;aspect-ratio:2/3;object-fit:cover;background:#24354b;border-radius:7px}b{display:block;margin-top:8px;font-size:14px;line-height:1.35}
#status{padding:12px;background:#172c46;border-radius:10px;margin:22px 0}
</style></head><body><h1>OceanVeil – catalog preview</h1>
<p>This page reads the same movie/series catalog JSON Nuvio should request. It does not test Nuvio installation or playback.</p>
<p><a href="manifest.json">Manifest</a> · <a href="catalog/series/oceanveil-anime.json">Raw catalog</a> · <a href="status.json">Discovery status</a></p>
<div id="status" role="status">Loading catalog…</div><div id="cards" class="grid"></div>
<script>
(async()=>{
 const status=document.getElementById('status');
 try {
  const response=await fetch('./catalog/series/oceanveil-anime.json',{cache:'no-store'});
  if(!response.ok) throw Error('Catalog request returned HTTP '+response.status);
  const value=await response.json();
  const moviesResponse = await fetch('./catalog/movie/oceanveil-movies.json',{cache:'no-store'});
  if(moviesResponse.ok) { const movieData=await moviesResponse.json(); if(Array.isArray(movieData.metas)) value.metas.push(...movieData.metas); }
  if(!Array.isArray(value.metas))throw Error('Response has no metas array');
  status.textContent='Catalog endpoint OK: '+value.metas.length+' titles. If Nuvio remains empty, check the addon installation, selected profile, and Home Catalog settings.';
  for(const entry of value.metas){
   const card=document.createElement('article');
   const img=document.createElement('img');img.src=entry.poster||'';img.alt='Poster for '+entry.name;img.loading='lazy';
   const name=document.createElement('b');name.textContent=entry.name||'(untitled)';
   card.append(img,name);document.getElementById('cards').append(card);
  }
 } catch (e){status.textContent='Catalog endpoint failed: '+e.message;}
})();
</script></body></html>"""
    (OUT / "catalog-preview.html").write_text(preview, encoding="utf8")
    if not fresh_usable:
        print("::warning::No live titles extracted. Publishing starter/saved snapshot; discovery of new releases is NOT currently verified.")
    print(f"Generated {len(listing)} titles; seeded {len(seed)}, saved live {live_count}, fetched this run {len(fresh_usable)}. Base: {base_url}")


if __name__ == "__main__":
    build()
