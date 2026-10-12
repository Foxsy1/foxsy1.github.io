# OceanVeil Anime — Stremio / Nuvio Catalog V4

A static GitHub Pages addon that publishes an **OceanVeil anime discovery catalog** with TMDB/IMDb/Kitsu identities and optional TMDB, TheTVDB, and MDBList metadata. It is based on the same **canonical-ID model** as the working [NuvEng catalog](https://github.com/NuvEng/NuvEng.github.io).

**Playback is not disabled.** Matched titles use standard IDs so your **already-installed stream addons** can find streams and handle episodes/movies. The addon can also publish optional `/stream/...` JSON endpoints for directly supplied HTTP(S) playback URLs or `externalUrl` links. It cannot invent or obtain media URLs that a provider does not expose; a static GitHub Pages build cannot fetch per-user, expiring signed video links on demand.

**Source coverage caveat:** On the previous October 12 GitHub run, OceanVeil's public pages returned HTTP 200 but the parser extracted **zero** titles, and the secondary index returned HTTP 403. V4 **does not claim** to repair that discovery failure. Daily automated *checks* are enabled; automatic *discovery* of every future addition remains unverified.

## What V4 fixes

- **Nuvio-friendly catalog definitions** (`extra: []`, like NuvEng); includes both a **series** and **movie** catalog, plus `/skip=0.json` variants.
- **Canonical IDs** — `tmdb:12345` for TMDB titles; `tt...` for IMDb-only matches, `kitsu:...` when found but no TMDB/IMDb mapping; `oceanveil:...` only when unmatched. Other stream addons are more likely to recognize these IDs.
- **Title resolution:** conservative Kitsu lookup → Fribb's public anime-ID crosswalk → TMDB search as an optional fallback. Ambiguous titles are deliberately not mapped to a random show.
- **Metadata:** TMDB synopsis/artwork/genres/year, TVDB descriptions/images and remote IDs, MDBList multi-source ratings. Field quality depends on provider availability and keys.
- **Enrichment cache:** persisted in `state.json` (7 days for identified titles), avoiding re-querying unchanged entries on every daily run.
- **Optional streams:** reads `streams.json` for direct HTTPS media links or browser `externalUrl` targets. Declares the `stream` resource only when entries actually exist.
- **Root-domain Pages fix** for `oceanveil-auto-catalog.github.io` preserved.
- **Offline tests** cover GitHub Pages paths, canonical IDs, matching safety, optional streams, and mocked TVDB/TMDB/MDBList responses.

## Install over your existing OceanVeil repo

1. Unzip this download. Upload **the contents of the `oceanveil-auto-catalog/` directory** to the **root** of https://github.com/oceanveil-auto-catalog/oceanveil-auto-catalog.github.io, replacing files. The hidden `.github/workflows/update.yml` directory must be included.
2. **Keep your existing `state.json`** if it exists; this file preserves discovered titles across builds. If you upload a ZIP via GitHub web UI, *extract it first* — do not upload the ZIP itself.
3. Set repo **Settings → Pages → Source: GitHub Actions**.
4. Configure optional GitHub Actions secrets as below.
5. Use **Actions → Update and publish OceanVeil catalog → Run workflow**. Both `build` and `deploy` must pass.
6. Install / reinstall the corrected URL into Nuvio or Stremio:

   **https://oceanveil-auto-catalog.github.io/manifest.json**

7. If installed but not visible in Nuvio, select the right profile and check **Home Catalogs / Display Order**. Enable the new **OceanVeil Anime (series)** catalog and, if wanted, the **OceanVeil Movies** catalog. Remove the previous OceanVeil addon and restart/refresh the app. Nuvio settings labels can vary by version.

## Set up TVDB, TMDB and MDBList

In GitHub repo: **Settings → Secrets and variables → Actions → New repository secret**.

| Secret | Purpose | Required? |
|---|---|---|
| `TMDB_API_KEY` | The Movie Database v3 API key (or v4 read token); enables fallback searches, posters/backgrounds, episode-title metadata | Optional; recommended |
| `TVDB_API_KEY` | TheTVDB v4 key; lookups, remote IDs, artwork/overview | Optional; may require paid/project access |
| `TVDB_PIN` | Subscriber PIN, only for TVDB keys that require one | Optional |
| `MDBLIST_API_KEY` | MDBList multi-source ratings and certifications | Optional; recommended |

API keys are **not written into the public JSON**. If no secrets are configured, the project still attempts the public Kitsu→Fribb ID mapping but cannot obtain TMDB/TVDB/MDBList enrichment. **No subscriptions or third-party data access are included with the ZIP.**

TheTVDB v4 login uses your API key and optional subscriber PIN. API access/licensing is controlled by TheTVDB; see [its v4 API](https://thetvdb.github.io/v4-api/) and [licensing explanation](https://github.com/thetvdb/v4-api). MDBList API information: https://docs.mdblist.com/docs/api.

### Important matching behavior

Anime titles often have multiple adaptations and separate seasons. This project **does not guess** a canonical ID when candidate titles are too similar. The `status.json` `identifier_counts` field shows the number of entries resolved to `tmdb`, `imdb`, `kitsu` and unmatched `oceanveil` IDs. In `status.json`, check `unmatched_titles` and the `enrichment_counts` object as well.

**Only matched identifiers are reliably interoperable with third-party metadata and playback providers.** If a title remains `oceanveil:...`, a client can show it as a catalog entry via this addon's own `/meta` route, but most other stream addons will not know that ID.

## Playback: what is and is not possible

- **Works with existing addons:** when a show maps to an actual `tmdb:` or `tt` ID, the Nuvio/Stremio client can ask its installed metadata and stream addons to load the title and episodes. This is the same basic strategy used by NuvEng.
- **Kitsu fallback:** when a title gets `kitsu:...`, install/enable a Kitsu-compatible metadata addon if the client needs it.
- **Direct OceanVeil playback:** this project has no verified OceanVeil episode-playback API or stable direct media URLs. A stream JSON endpoint can only be generated when suitable URLs are supplied. Source pages, posters, and enriched metadata are *not streams*.
- **Official playback link:** `externalUrl` entries open a website; they aren't an in-player HLS/MP4 stream. Content availability depends on the service and your region/account.

To supply an authorized, direct stream, create `streams.json` in the repo root (this file is optional; the included version is empty). Example configuration with **illustrative fake domains**:

```json
{
  "tmdb:12345:1:1": [
    {"title": "Episode 1 (HLS)", "url": "https://media.example.org/episode1.m3u8"}
  ],
  "movie:tt1234567": [
    {"title": "Open on provider", "externalUrl": "https://watch.example.org/movie/123"}
  ]
}
```

For series, video IDs usually contain an identifier plus season and episode, such as `tt0898266:9:17`; different metadata addons may use other conventions. Confirm the **exact video ID requested** by your client before filling `streams.json`. The `movie:` prefix above selects a movie route and is stripped before writing `/stream/movie/tt1234567.json`. Do **not** publish private signed streams, API tokens, cookies or account credentials in this public file. This is not an OceanVeil stream scraper.

## Test your deployment

- Homepage: https://oceanveil-auto-catalog.github.io/
- Addon manifest: https://oceanveil-auto-catalog.github.io/manifest.json
- Series catalog: https://oceanveil-auto-catalog.github.io/catalog/series/oceanveil-anime.json
- Movie catalog: https://oceanveil-auto-catalog.github.io/catalog/movie/oceanveil-movies.json
- Browser preview: https://oceanveil-auto-catalog.github.io/catalog-preview.html
- Diagnostics: https://oceanveil-auto-catalog.github.io/status.json

**After deploying V4**, expect the manifest version `1.4.0`. If `identifier_counts.tmdb` is zero, look at whether Kitsu/Fribb was available in Actions and whether you configured TMDB API credentials. A successful GitHub Pages deployment only proves static assets were published; it does not prove live title discovery, Nuvio UI appearance, or stream playback.

## Project layout

```text
oceanveil-auto-catalog/
├── .github/workflows/update.yml   # daily GitHub Actions + Pages deploy
├── build.py                        # source discovery and static catalog builder
├── enrichment.py                   # Kitsu/Fribb, TMDB, TVDB, MDBList
├── requirements.txt                # Python runtime
├── seed.json                       # 34 title starter snapshot
├── streams.json                    # optional direct URLs, empty by default
├── static/placeholder.png          # unmatched artwork fallback
├── tests/test_build.py             # offline end-to-end and provider-mock tests
└── README.md
```

At build time the script writes `public/` (deployed to GitHub Pages) and `state.json` (committed by GitHub Actions to retain enrichment/discovery). Neither `public/` nor `.github/` should be removed from the upload workflow; `.github/` is a **source** folder while `public/` is generated.

## Develop locally

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
# Linux/macOS:
ENABLE_BROWSER_DISCOVERY=0 python build.py
python -m http.server --directory public 8000
```

For a local build without network, tests use mocked providers, and the actual builder will attempt public lookups/time out unless sources are reachable. Browser discovery in GitHub Actions installs Chromium via Playwright. Rate limits and provider errors are handled best-effort.
