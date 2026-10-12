"""Public catalog discovery from DOM, embedded JSON and browser-loaded JSON responses.

No sign-in, media requests, authentication bypass, or session extraction.
This module must not consider an HTTP-200 response proof of a title listing.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

HOSTS = {'oceanveil.net', 'www.oceanveil.net'}
PATH = re.compile(r'^/anime_titles/(\d+)/?$')
TITLE_KEYS = ('anime_title', 'animeTitle', 'english_title', 'englishTitle', 'series_title', 'seriesTitle', 'title', 'name', 'display_name', 'displayName')
ID_KEYS = ('anime_title_id', 'animeTitleId', 'anime_id', 'animeId', 'title_id', 'titleId', 'id')
IMAGE_KEYS = ('poster', 'poster_url', 'posterUrl', 'image', 'image_url', 'thumbnail', 'thumbnail_url', 'cover', 'cover_image', 'jacket')
EXCLUDE = {'newly streaming', 'special pick up', 'why choose oceanveil?', 'watch now', 'all titles', 'welcome', 'anime', 'image', 'oceanveil', 'title', 'titles', 'login', 'more', 'new', 'menu', 'live', 'home', 'play', 'next', 'watch', 'list', 'episode', 'sign up', 'skip', 'faq', 'young adult'}
AGE = re.compile(r'(?<!\d)(18\+|R18\+?|17\+|16\+|15\+|13\+|12\+|PG)(?!\w)', re.I)
DUB = re.compile(r'(?:^|\s)\[Dub\]|\benglish\s+dub(?:bed)?\b', re.I)
SIM = re.compile(r'\bSimCast\b|\bSimulcast\b', re.I)
ADULT = re.compile(r'\b(?:hentai|explicit|uncensored|R18\+?)\b', re.I)


def clean_title(raw):
    if not isinstance(raw, str):
        return ''
    name = ' '.join(raw.split())
    name = re.sub(r'^(?:Cover of |Poster (?:for|of) )', '', name, flags=re.I)
    name = re.sub(r'\s*[|–-]\s*OceanVeil.*$', '', name, flags=re.I)
    if len(name) < 3 or len(name) > 230 or name.casefold() in EXCLUDE or 'oceanveil watch anime' in name.casefold():
        return ''
    if name.lower().startswith(('http:', 'https:')) or '<' in name:
        return ''
    return name


def oid_from_url(url):
    p = urlparse(url)
    match = PATH.fullmatch(p.path)
    return match.group(1) if p.hostname in HOSTS and match else ''


def record_key(title, oid=''):
    if oid and str(oid).isdigit():
        return str(oid)
    return 'discovered-' + hashlib.sha256(re.sub(r'^\s*\[dub\]\s*', '', title, flags=re.I).casefold().encode()).hexdigest()[:14]


def tags_for(*pieces, props=None):
    props = props if isinstance(props, dict) else {}
    text = ' '.join(str(p or '') for p in pieces if p is not None)[:1300]
    dubs = bool(DUB.search(text)) or props.get('dub') is True or props.get('is_dub') is True or props.get('isDub') is True
    simulcast = bool(SIM.search(text)) or props.get('simulcast') is True or props.get('is_simulcast') is True
    ages = [a.upper() for a in AGE.findall(text)]
    # Site-wide 'adult subscription' marketing must never classify every title as explicit.
    nsfw = bool(ADULT.search(text)) or props.get('is_adult') is True or props.get('isAdult') is True or props.get('adult') is True or '18+' in ages or 'R18' in ages or 'R18+' in ages
    safe = not nsfw and bool(set(ages) & {'PG', '12+', '13+'})
    return {'dubbed': dubs, 'simulcast': simulcast, 'nsfw': nsfw, 'sfw': safe, 'age_rating': next(iter(ages), '')}


def merge_record(dest, incoming):
    key = incoming['key']
    if key in dest:
        prior = dest[key]
        for flag in ('dubbed','simulcast','nsfw','sfw'):
            prior[flag] = bool(prior.get(flag) or incoming.get(flag))
        if prior.get('nsfw'):
            prior['sfw'] = False
        for name in ('poster','url','age_rating'):
            if not prior.get(name) and incoming.get(name):
                prior[name] = incoming[name]
        if not prior.get('title') and incoming.get('title'):
            prior['title'] = incoming['title']
        return
    dest[key] = incoming


def make_record(title, url='', oid='', poster='', context='', props=None, origin=''):
    title = clean_title(title)
    if not title:
        return None
    oid = oid or oid_from_url(url)
    if not oid and url and not ((urlparse(url).hostname or '') in HOSTS or (urlparse(url).hostname or '').endswith('.oceanveil.net')):
        return None
    if oid:
        url = f'https://oceanveil.net/anime_titles/{oid}'
    elif not url or (urlparse(url).hostname or '') not in HOSTS:
        url = 'https://oceanveil.net/anime_titles'
    props = props if isinstance(props, dict) else {}
    flags = tags_for(title, context, props.get('rating'), props.get('age_rating'), props.get('classification'), props.get('tags'), props=props)
    img = urljoin(url, poster) if isinstance(poster, str) and poster else ''
    if img and urlparse(img).scheme not in ('http','https'):
        img = ''
    return {'key': record_key(title, oid), 'title': title, 'url': url,
            'poster': img, 'origin': origin or 'source', **flags}


def from_json(data, source_url, max_nodes=12000):
    """Traverse source catalog structures, rejecting generic API payloads without a name and media context."""
    result = {}
    stack = [(data, 0, False)]
    steps = 0
    while stack and steps < max_nodes:
        obj, depth, inherited_context = stack.pop()
        steps += 1
        if depth > 14:
            continue
        if isinstance(obj, list):
            stack.extend((x, depth+1, inherited_context) for x in obj[:2000])
        elif isinstance(obj, dict):
            keys = set(obj)
            # Tight media context test: listing nouns, metadata fields, or a numeric source ID.
            media_context = inherited_context or bool(keys & set(IMAGE_KEYS)) or bool(keys & {'episodes','genre','genres','category','age_rating','rating','isDub','is_dub','video_type','type'})
            name = next((obj[k] for k in TITLE_KEYS if isinstance(obj.get(k), str) and clean_title(obj[k])), '')
            oid = str(next((obj[k] for k in ID_KEYS if isinstance(obj.get(k), (int,str)) and str(obj[k]).isdigit()), ''))
            u = next((str(obj[k]) for k in ('url','href','link','path') if isinstance(obj.get(k), str) and '/anime_titles/' in obj[k]), '')
            if u:
                u = urljoin(source_url, u)
                if urlparse(u).hostname not in HOSTS:
                    u = ''
            if (oid or media_context or u) and name:
                img = next((obj[k] for k in IMAGE_KEYS if isinstance(obj.get(k), str)), '')
                props = dict(obj)
                record = make_record(name, u or source_url, oid, img, json.dumps({k:obj.get(k) for k in ('category','tags','age_rating','rating','label','status','classification', 'ageRestriction','age_restriction') if k in obj}, ensure_ascii=False)[:400], props, 'public-json')
                if record:
                    merge_record(result, record)
            for k,v in obj.items():
                if isinstance(v, (dict,list)):
                    stack.append((v,depth+1, inherited_context or k.lower() in {'anime','animes','animetitles','anime_titles','titles','catalog','catalogue','contents','works','list','items','results','data'}))
    return result


def from_html(html, page_url):
    soup = BeautifulSoup(html, 'html.parser')
    records = {}
    # 1. Real links / data-title attributes. No separate title page fetch required.
    for tag in soup.select('a[href], [data-anime-id], [data-anime-title], [data-title], [data-id]')[:3000]:
        href = urljoin(page_url, tag.get('href') or '')
        oid = oid_from_url(href)
        data_oid = tag.get('data-anime-id') or tag.get('data-id')
        if not oid and isinstance(data_oid, str) and data_oid.isdigit():
            oid = data_oid
        image = tag.select_one('img')
        title = tag.get('data-anime-title') or tag.get('data-title') or (image.get('alt') if image else '')
        if not clean_title(title):
            title = next((h.get_text(' ', strip=True) for h in tag.select('h2,h3,h4,[class*=title]') if clean_title(h.get_text(' ',strip=True))), '')
        if not clean_title(title) and oid:
            title = tag.get_text(' ', strip=True)[:230]
        if not oid and not image and not tag.get('data-anime-title'):
            continue
        context = tag.parent.get_text(' ', strip=True)[:350] if tag.parent else tag.get_text(' ', strip=True)[:200]
        url = f'https://oceanveil.net/anime_titles/{oid}' if oid else page_url
        poster = (image.get('data-src') or image.get('src') or '') if image else ''
        rec = make_record(title, url, oid, poster, context, origin='public-dom')
        if rec:
            merge_record(records, rec)
    # 2. Linkless CSS/JS cards (the old scraper missed these).
    for img in soup.select('img[alt]')[:2000]:
        title = clean_title(img.get('alt'))
        if not title:
            continue
        parent = img
        context = ''
        oid = ''
        for _ in range(4):
            parent = parent.parent
            if not parent:
                break
            text = ' '.join(parent.get_text(' ', strip=True).split())
            if not context and len(text) <= 300 and ('SimCast' in text or 'Dub' in text or AGE.search(text)):
                context = text
            oid = oid or oid_from_url(urljoin(page_url, parent.get('href',''))) or str(parent.get('data-id','') if str(parent.get('data-id','')).isdigit() else '')
            if context and oid:
                break
        # Image without ID only qualifies with strong anime listing context.
        if not (oid or context):
            continue
        rec = make_record(title, f'https://oceanveil.net/anime_titles/{oid}' if oid else page_url, oid, img.get('data-src') or img.get('src') or '', context, origin='public-dom-img')
        if rec:
            merge_record(records, rec)
    # 3. Hydration/JSON-LD arrays and embedded JSON. Ignore arbitrary JS source code.
    for script in soup.select('script[type="application/json"],script[type="application/ld+json"],script#__NEXT_DATA__,script#__NUXT_DATA__')[:30]:
        value = script.string or script.get_text()
        if not value or len(value) > 2_000_000:
            continue
        try:
            for rec in from_json(json.loads(value), page_url).values():
                merge_record(records, rec)
        except (ValueError, TypeError):
            pass
    return records


def render_official(fetcher):
    """Playwright observes only publicly loaded pages and JSON responses."""
    if hasattr(fetcher, 'allowed') and not fetcher.allowed('https://oceanveil.net/anime_titles'):
        fetcher.events.append({'url':'https://oceanveil.net/anime_titles', 'result':'browser_skipped_robots'})
        return {}
    from playwright.sync_api import sync_playwright
    records = {}
    endpoint_hits = {}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=['--no-sandbox'])
        context = browser.new_context(viewport={'width':1280,'height':900})
        page = context.new_page()
        def on_response(response):
            url = response.url
            if urlparse(url).hostname not in HOSTS and not urlparse(url).hostname.endswith('.oceanveil.net'):
                return
            content_type = (response.headers.get('content-type') or '').lower()
            if 'json' not in content_type or not response.ok:
                return
            try:
                raw = response.body()
                if len(raw) > 4_000_000:
                    return
                candidate = from_json(json.loads(raw), url)
                if candidate:
                    for r in candidate.values():
                        merge_record(records, r)
                endpoint_hits[urlparse(url).path[:140]] = {'found':len(candidate),'size':len(raw)}
            except Exception:
                pass
        page.on('response', on_response)
        for path in ('/', '/anime_titles'):
            target = 'https://oceanveil.net' + path
            try:
                page.goto(target, wait_until='domcontentloaded', timeout=35000)
                page.wait_for_timeout(1800)
                for _ in range(5):
                    page.mouse.wheel(0,1200)
                    page.wait_for_timeout(550)
                for r in from_html(page.content(), target).values():
                    merge_record(records,r)
                if hasattr(fetcher, 'capture_probe'):
                    fetcher.capture_probe(page.content(),target,'browser-v6')
                fetcher.events.append({'url':target,'result':f'browser_discovery: {len(records)} records so far'})
            except Exception as exc:
                fetcher.events.append({'url':target,'result':f'browser_error: {str(exc)[:130]}'})
        browser.close()
    fetcher.browser_endpoint_hits = endpoint_hits
    return records
