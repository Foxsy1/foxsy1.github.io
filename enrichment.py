"""Offline-at-publish-time enrichments and conservative anime ID crosswalk.

The generated Stremio catalog uses canonical TMDB / IMDb identifiers when
confident; Kitsu as fallback; and OceanVeil IDs only for unmatched entries.
Optional credentials come from GitHub Actions secrets, never published JSON.
"""
from __future__ import annotations

import os
import re
import time
import unicodedata
from datetime import date, timedelta
from difflib import SequenceMatcher
from typing import Any

import requests

FRIBB = "https://raw.githubusercontent.com/Fribb/anime-lists/master/anime-list-full.json"
TMDB = "https://api.themoviedb.org/3"
TVDB = "https://api4.thetvdb.com/v4"
MDB = "https://api.mdblist.com"
KITSU = "https://kitsu.io/api/edge/anime"


def lookup_title(value):
    return re.sub(r"^\s*(?:\[(?:dub|sub)\]|\((?:dub|sub)\))\s*", "", str(value or ""), flags=re.I).strip()


def norm(value):
    text = unicodedata.normalize('NFKD', str(value or '')).encode('ascii', 'ignore').decode().casefold()
    return re.sub(r'[^a-z0-9]+', ' ', text).strip()


def match_score(a, b):
    x, y = norm(a), norm(b)
    if not x or not y:
        return 0.0
    if x == y:
        return 1.0
    # A short/ambiguous name (e.g. Mononoke) must never match a longer title
    # such as Princess Mononoke just because one contains the other.
    return SequenceMatcher(None, x, y).ratio()


def image_url(path, size='w500'):
    if isinstance(path, str) and path.startswith('/'):
        return f'https://image.tmdb.org/t/p/{size}{path}'
    return ''


def names_for(entry):
    if not isinstance(entry, dict):
        return []
    titles = entry.get('titles') or {}
    result = [entry.get('canonicalTitle'), entry.get('slug'), *[titles.get(x) for x in ('en', 'en_jp', 'ja_jp')]]
    return [x for x in result if isinstance(x, str) and x.strip()]


class Enricher:
    def __init__(self, request_session=None):
        self.session = request_session or requests.Session()
        self.tmdb_key = os.environ.get('TMDB_API_KEY', '').strip()
        self.tvdb_key = os.environ.get('TVDB_API_KEY', '').strip()
        self.tvdb_pin = os.environ.get('TVDB_PIN', '').strip()
        self.mdb_key = os.environ.get('MDBLIST_API_KEY', '').strip()
        self._tvdb_token = None
        self._tvdb_disabled = False
        self._mdb_disabled = False
        self._mapping_loaded = False
        self.fribb = {}
        self.events = []
        self._kitsu_cache = {}
        self._tmdb_cache = {}
        self._tvdb_cache = {}
        self._calls = 0
        self.max_calls = int(os.getenv('ENRICH_MAX_CALLS', '180'))

    def get(self, url, params=None, headers=None):
        if self._calls >= self.max_calls:
            return None
        self._calls += 1
        try:
            r = self.session.get(url, params=params, headers=headers or {}, timeout=14)
            if r.status_code in (401, 403, 429):
                # Don't retry auth/quota failures repeatedly in a single run
                if 'mdblist.com' in url:
                    self._mdb_disabled = True
                if 'thetvdb.com' in url:
                    self._tvdb_disabled = True
                return None
            r.raise_for_status()
            if len(r.content) > 16_000_000:
                return None
            return r.json()
        except (requests.RequestException, ValueError):
            return None

    def _post(self, url, body):
        if self._calls >= self.max_calls:
            return None
        self._calls += 1
        try:
            r = self.session.post(url, json=body, timeout=14)
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError):
            return None

    def load_fribb(self):
        if self._mapping_loaded:
            return
        self._mapping_loaded = True
        items = self.get(FRIBB)
        if isinstance(items, list):
            self.fribb = {str(e['kitsu_id']): e for e in items if isinstance(e, dict) and e.get('kitsu_id')}
        self.events.append({'source': 'fribb', 'records': len(self.fribb), 'ok': bool(self.fribb)})

    def find_kitsu(self, name):
        if name in self._kitsu_cache:
            return self._kitsu_cache[name]
        # Kitsu is a secondary search, not enough evidence for an ID alone unless
        # the requested title strongly matches the returned English/romanized name.
        data = self.get(KITSU, {'filter[text]': name, 'page[limit]': '8'},
                        {'Accept': 'application/vnd.api+json'})
        candidates = []
        for item in (data or {}).get('data', []) if isinstance(data, dict) else []:
            attrs = item.get('attributes') or {}
            score = max((match_score(name, x) for x in names_for(attrs)), default=0)
            if score >= 0.87:
                candidates.append((score, item))
        candidates.sort(key=lambda it: it[0], reverse=True)
        selected = None
        if candidates and (len(candidates) == 1 or candidates[0][0] - candidates[1][0] >= .06):
            selected = candidates[0][1]
        self._kitsu_cache[name] = selected
        return selected

    def _tmdb_params(self, extras=None):
        extras = dict(extras or {})
        if self.tmdb_key and not self.tmdb_key.startswith('eyJ'):
            extras['api_key'] = self.tmdb_key
        return extras

    def _tmdb_headers(self):
        return {'Authorization': 'Bearer ' + self.tmdb_key} if self.tmdb_key.startswith('eyJ') else {}

    def tmdb_request(self, path, params=None):
        if not self.tmdb_key:
            return None
        return self.get(TMDB + path, self._tmdb_params(params), self._tmdb_headers())

    def tmdb_search(self, name):
        if not self.tmdb_key:
            return None
        candidates = []
        for kind in ('tv', 'movie'):
            result = self.tmdb_request(f'/search/{kind}', {'query': name, 'include_adult': 'true'})
            for item in (result or {}).get('results', [])[:10]:
                label = item.get('name') or item.get('title') or ''
                score = match_score(name, label)
                if score >= .89:
                    candidates.append((score, kind, item))
        candidates.sort(reverse=True, key=lambda x: x[0])
        if not candidates or (len(candidates) > 1 and candidates[0][0] - candidates[1][0] < .065):
            return None
        score, kind, item = candidates[0]
        return {'tmdb_type': kind, 'tmdb_id': str(item['id']), 'confidence': round(score, 3), 'method': 'tmdb-title-search'}

    def tmdb_details(self, tmdb_id, kind):
        cachekey = (str(tmdb_id), kind)
        if cachekey in self._tmdb_cache:
            return self._tmdb_cache[cachekey]
        details = self.tmdb_request(f'/{kind}/{tmdb_id}', {'append_to_response': 'external_ids'})
        self._tmdb_cache[cachekey] = details
        return details

    def tvdb_token(self):
        if not self.tvdb_key or self._tvdb_disabled:
            return None
        if self._tvdb_token:
            return self._tvdb_token
        req = {'apikey': self.tvdb_key}
        if self.tvdb_pin:
            req['pin'] = self.tvdb_pin
        data = self._post(TVDB + '/login', req)
        self._tvdb_token = ((data or {}).get('data') or {}).get('token')
        if not self._tvdb_token:
            self._tvdb_disabled = True
        return self._tvdb_token

    def tvdb_get(self, path, params=None):
        token = self.tvdb_token()
        if not token:
            return None
        result = self.get(TVDB + path, params, {'Authorization': f'Bearer {token}'})
        return (result or {}).get('data') if isinstance(result, dict) else None

    def tvdb_search(self, name):
        candidates = self.tvdb_get('/search', {'query': name, 'type': 'series'})
        if not isinstance(candidates, list):
            return None
        choices = []
        for c in candidates:
            aliases = c.get('aliases') or []
            candnames = [c.get('name'), c.get('nameTranslations'), *(v for v in aliases if isinstance(v, str))]
            score = max((match_score(name, n) for n in candnames if isinstance(n, str)), default=0)
            if score >= .90 and c.get('tvdb_id') or (score >= .90 and c.get('id')):
                choices.append((score, str(c.get('tvdb_id') or c.get('id'))))
        choices.sort(reverse=True)
        if choices and (len(choices) == 1 or choices[0][0] - choices[1][0] >= .06):
            return {'tvdb_id': choices[0][1], 'confidence': round(choices[0][0], 3), 'method': 'tvdb-title-search'}
        return None

    def tvdb_details(self, tvdb_id):
        if not tvdb_id or not self.tvdb_key:
            return None
        if str(tvdb_id) in self._tvdb_cache:
            return self._tvdb_cache[str(tvdb_id)]
        record = self.tvdb_get(f'/series/{tvdb_id}/extended')
        if not record:
            record = self.tvdb_get(f'/series/{tvdb_id}')
        self._tvdb_cache[str(tvdb_id)] = record
        return record

    def mdblist(self, tmdb_id=None, imdb_id=None, kind='tv', tvdb_id=None):
        if not self.mdb_key or self._mdb_disabled:
            return None
        media = 'movie' if kind == 'movie' else 'show'
        if imdb_id and str(imdb_id).startswith('tt'):
            path = f'/imdb/{media}/{imdb_id}/'
        elif tmdb_id:
            path = f'/tmdb/{media}/{tmdb_id}/'
        elif tvdb_id:
            path = f'/tvdb/{media}/{tvdb_id}/'
        else:
            return None
        obj = self.get(MDB + path, {'apikey': self.mdb_key})
        return obj if isinstance(obj, dict) and obj.get('response') is not False else None

    @staticmethod
    def fribb_ids(record):
        record = record or {}
        tm = record.get('themoviedb_id') or {}
        if not isinstance(tm, dict):
            tm = {}
        kind = 'tv' if tm.get('tv') else 'movie' if tm.get('movie') else None
        tid = tm.get('tv') or tm.get('movie')
        tvdb = record.get('thetvdb_id')
        imdb = record.get('imdb_id')
        return {'tmdb_type': kind, 'tmdb_id': str(tid) if tid else None,
                'tvdb_id': str(tvdb) if tvdb else None,
                'imdb_id': str(imdb) if isinstance(imdb, str) and re.fullmatch(r'tt\d+', imdb) else None}

    @staticmethod
    def remote_ids(tvdb_record):
        ids = {}
        for item in (tvdb_record or {}).get('remoteIds', []):
            rid = str(item.get('id') or '').strip()
            name = str(item.get('sourceName') or '').lower()
            if 'themoviedb' in name or 'tmdb' in name:
                if rid.isdigit():
                    ids['tmdb_id'] = rid
            if 'imdb' in name and re.fullmatch(r'tt\d+', rid):
                ids['imdb_id'] = rid
        return ids

    def enrich(self, title, previous=None):
        """Return cached or new metadata; external APIs aren't contacted without reason.

        Persistent caching prevents using daily quotas for the same 34 titles.
        """
        prior = dict(previous or {})
        until = prior.get('refresh_after', '')
        if prior.get('id') and until >= date.today().isoformat():
            return prior
        title = lookup_title(title)
        self.load_fribb()
        info = {k: v for k, v in prior.items() if k not in ('refresh_after',)}
        resolved = {}
        kitsu = self.find_kitsu(title)
        if kitsu:
            kitid = str(kitsu['id'])
            attrs = kitsu.get('attributes') or {}
            poster = attrs.get('posterImage') or {}
            info['kitsu_id'] = kitid
            info['kitsu_poster'] = next((poster[k] for k in ('large','medium','original') if poster.get(k)), '')
            if self.fribb.get(kitid):
                resolved = self.fribb_ids(self.fribb[kitid])
                resolved['method'] = 'kitsu-fribb'
                resolved['confidence'] = 1.0
            else:
                resolved = {'id': f'kitsu:{kitid}', 'method': 'kitsu-only', 'confidence': 0.9}
        # Retry independent ID matching when Fribb has no TMDB/IMDb identifiers.
        if not resolved.get('tmdb_id') and not resolved.get('imdb_id') and self.tmdb_key:
            found = self.tmdb_search(title)
            if found:
                resolved.update(found)
        if not (resolved.get('tvdb_id') or prior.get('tvdb_id')) and self.tvdb_key:
            tvdb_result = self.tvdb_search(title)
            if tvdb_result:
                resolved['tvdb_id'] = tvdb_result['tvdb_id']
        for key, val in resolved.items():
            if val is not None:
                info[key] = val
        if prior.get('id') and not info.get('tmdb_id') and not info.get('imdb_id'):
            info['id'] = prior['id']
        if info.get('tmdb_id'):
            info['id'] = 'tmdb:' + str(info['tmdb_id'])
        elif info.get('imdb_id'):
            info['id'] = info['imdb_id']
        elif resolved.get('id'):
            info['id'] = resolved['id']
        tmdb_kind = info.get('tmdb_type') or 'tv'
        tmdb_data = self.tmdb_details(info['tmdb_id'], tmdb_kind) if info.get('tmdb_id') else None
        if tmdb_data:
            external = tmdb_data.get('external_ids') or {}
            info['imdb_id'] = external.get('imdb_id') or info.get('imdb_id')
            info['tvdb_id'] = str(external.get('tvdb_id') or info.get('tvdb_id') or '')
            info['description'] = tmdb_data.get('overview') or info.get('description')
            info['poster'] = image_url(tmdb_data.get('poster_path')) or info.get('poster')
            info['background'] = image_url(tmdb_data.get('backdrop_path'), 'original') or info.get('background')
            info['releaseInfo'] = str(tmdb_data.get('first_air_date') or tmdb_data.get('release_date') or '')[:4] or info.get('releaseInfo')
            info['genres'] = [g['name'] for g in tmdb_data.get('genres', []) if g.get('name')]
            info['tmdb_rating'] = tmdb_data.get('vote_average')
        tvdb_data = self.tvdb_details(info.get('tvdb_id')) if info.get('tvdb_id') else None
        if tvdb_data:
            remotes = self.remote_ids(tvdb_data)
            info['imdb_id'] = info.get('imdb_id') or remotes.get('imdb_id')
            info['description'] = info.get('description') or tvdb_data.get('overview')
            info['poster'] = info.get('poster') or tvdb_data.get('image')
            info['background'] = info.get('background') or ''
            info['releaseInfo'] = info.get('releaseInfo') or str(tvdb_data.get('firstAired') or '')[:4]
            # Never replace a confident ID with a disagreeing remote ID.
            if not info.get('tmdb_id') and remotes.get('tmdb_id'):
                info['tmdb_id'] = remotes['tmdb_id']
                info['tmdb_type'] = 'tv'
                info['id'] = 'tmdb:' + remotes['tmdb_id']
        mdb = self.mdblist(info.get('tmdb_id'), info.get('imdb_id'), tmdb_kind, info.get('tvdb_id'))
        if mdb:
            ratings = {r.get('source'): r.get('value') for r in mdb.get('ratings', []) if isinstance(r, dict)}
            info['ratings'] = {name: ratings[name] for name in ('imdb', 'myanimelist', 'letterboxd', 'tomatoes', 'metacritic', 'trakt') if ratings.get(name) is not None}
            info['certification'] = mdb.get('certification') or info.get('certification')
        # Avoid requerying confident IDs daily; unmatched entries get retried sooner.
        days = 7 if info.get('id') else 1
        info['refresh_after'] = (date.today() + timedelta(days=days)).isoformat()
        return {k: v for k, v in info.items() if v is not None}


def preview_metadata(name, meta, fallback_poster):
    imdb = ((meta or {}).get('ratings') or {}).get('imdb')
    tmdb_rating = (meta or {}).get('tmdb_rating')
    imdb_rating = str(imdb) if imdb else (f'{float(tmdb_rating):.1f}' if tmdb_rating else None)
    ratings = (meta or {}).get('ratings') or {}
    pairs = [('IMDb', 'imdb'), ('MAL', 'myanimelist'), ('LB', 'letterboxd'), ('RT', 'tomatoes')]
    note = '⭐ ' + ' · '.join(f'{label} {ratings[key]}' for label, key in pairs if ratings.get(key) is not None) if ratings else ''
    desc = '\n\n'.join(filter(None, (note, meta.get('description') or 'Listed in OceanVeil-related sources. Availability can change.')))
    result = {'name': name, 'poster': meta.get('poster') or meta.get('kitsu_poster') or fallback_poster,
              'posterShape': 'poster', 'description': desc}
    for k in ('background', 'releaseInfo', 'genres'):
        if meta.get(k):
            result[k] = meta[k]
    if imdb_rating:
        result['imdbRating'] = imdb_rating
    return result
