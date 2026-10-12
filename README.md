# OceanVeil Auto Catalog V6 — Live discovery + eight Nuvio catalogs

This is a replacement for your V5 GitHub Pages repository. The previous scraper saw HTTP 200 responses but extracted **zero** live titles; it mostly expected `<a href="/anime_titles/123">` anchors, which JavaScript-driven listings need not use. V6 replaces that assumption. **The new extraction methods pass local/mock tests, but only the next GitHub Actions run can confirm they work against the live OceanVeil deployment.** A scheduled green build is not evidence of successful discovery.

## What V6 changes

- Collects title records from public HTML linked cards, **linkless image cards**, embedded JSON/hydration (`__NEXT_DATA__` and JSON-LD), and **public JSON responses loaded by Chromium**. This is fundamentally different from simply scanning numbered URLs.
- Preserves OceanVeil source tags when available: `SimCast`, `[Dub]`, ratings such as `PG`, `13+`, and `18+`. Doesn't classify an entire page NSFW just because the site's marketing calls it an adult streaming platform.
- Keeps saved title records and enriched IDs between daily runs. Uses TMDB/IMDb IDs with external posters; unmatched records are reported, not silently published as unplayable `oceanveil:` items.
- Includes **eight series lists**, plus an additional Movies list for the Stremio movie type. (Stremio distinguishes `series` from `movie`; publishing movie metadata under `series` just to keep a count of eight would be incorrect.)
- Adds a **catalog selector** at `catalog-preview.html`, category counts in `status.json` and discovery method counts + public endpoint paths in `source-debug.json`.
- Leaves normal playback resolution to your existing stream addons, using recognizable IDs. Does **not** disable playback. `streams.json` still supports direct, explicitly provided authorized HTTPS stream links, but the ZIP does not contain OceanVeil subscription streams.

## The eight catalog rows

| Order | Series catalog | Rule |
|---|---|---|
| 1 | Simulcast | Explicit `SimCast`/simulcast source flag |
| 2 | Dubbed | `[Dub]` or explicit English-dub source flag |
| 3 | NSFW | Explicit 18+ / R18 / adult classification in a **title's own source data** |
| 4 | SFW | Verified PG / 12+ / 13+ source classification, excluding 18+ |
| 5 | Mix | Alternating SFW and NSFW selection, without duplicates |
| 6 | Top | Available titles sorted by metadata rating; unscored titles last |
| 7 | Mix of All | Every matched series, including uncertain age ratings, deduplicated |
| 8 | NSFW Dubbed | Verified NSFW **and** dubbed, not merely one or the other |

**16+ isn't proof of explicit content or safe-for-all-ages.** V6 leaves titles classified *only* 16+ in Mix of All/Top until a more reliable classification is available. Consequently some sections may be empty until source metadata is found. Historical starter titles without source labels also default to Top + Mix of All, not fabricated categories.

An optional **OceanVeil Movies** row appears separately because movie and series have different Stremio types.

## Install — complete replacement

1. Extract ZIP. Upload **all files inside** the folder into the root of [your repository](https://github.com/oceanveil-auto-catalog/oceanveil-auto-catalog.github.io), replacing previous files. Upload the hidden `.github/workflows/update.yml` path as well.
2. **Preserve `state.json`** already in the repository; it caches title matches and improves update reliability. The ZIP does not contain a `state.json`.
3. Retain repository Actions secrets:
   - `TMDB_API_KEY`: your TMDB long `eyJ...` read token works.
   - `MDBLIST_API_KEY`: optional MDBList ratings enrichment.
   - `TVDB_API_KEY` and `TVDB_PIN`: entirely optional.
4. Keep **Settings → Pages → Source: GitHub Actions**.
5. **Actions → Update and publish OceanVeil catalog → Run workflow**. Wait for build and deploy to finish.
6. Remove the previous OceanVeil addon from the selected Nuvio/Stremio profile, then install:

   **`https://oceanveil-auto-catalog.github.io/manifest.json`**

7. Check whether the eight rows are enabled on your Nuvio Home/Discovery screen. Catalogs with zero entries may not display on a particular Nuvio layout.

## Verification — do this before judging success

- **Manifest:** https://oceanveil-auto-catalog.github.io/manifest.json — version `1.6.0`, eight series catalog objects, one optional Movies catalog.
- **Visual preview:** https://oceanveil-auto-catalog.github.io/catalog-preview.html — choose each catalog, see exactly what Nuvio should load.
- **All series:** https://oceanveil-auto-catalog.github.io/catalog/series/oceanveil-mix-all.json
- **Status:** https://oceanveil-auto-catalog.github.io/status.json
- **Source diagnostics:** https://oceanveil-auto-catalog.github.io/source-debug.json

In `status.json`, these values matter:

```json
{
  "build_version": "1.6.0",
  "live_titles_extracted_this_run": 0,
  "discovery_methods": {
    "third_party": 0,
    "official_http": 0,
    "official_browser": 0,
    "official_sitemap": 0
  },
  "catalog_counts": {
    "oceanveil-simulcast": 0,
    "oceanveil-mix-all": 0
  }
}
```

**Those zeros are an explanatory example, not an expected result.** If every discovery count remains zero, the site still isn't exposing usable public data to the GitHub runner. Do **not** call it fixed simply because the action succeeded; send `source-debug.json` **and** the `Update catalog` job log so the underlying page structure can be handled specifically. If `official_browser` or `official_http` is greater than zero and the new titles survive ID matching, live updates are working.

## Auto-update and quota management

The existing GitHub workflow remains scheduled **daily at 03:15 UTC** (08:15 PKT). Pushes and manual triggers also rebuild. `state.json` caches discovery and metadata; metadata enrichment is rate-limited by `ENRICH_MAX_NEW` and `ENRICH_MAX_CALLS` in the workflow. If hundreds of titles are found at once, the first run may discover many but publish only those already matched/enriched; further daily runs should fill in the rest. Increase these limits cautiously, within your TMDB/MDBList API quotas.

No GitHub Pages backend runs continuously and no OceanVeil membership credentials are required or stored.

## Repository layout

```
.github/workflows/update.yml  # Schedule, tests, build, persist state, Pages deploy
build.py                      # State updates, eight catalogs, canonical IDs, manifests
discovery.py                  # DOM + embedded JSON + browser-network discovery
enrichment.py                # Kitsu/Fribb/TMDB/TVDB/MDBList enrichment
seed.json                     # Historical starter titles, not current catalog proof
streams.json                  # Optional supplied authorized streams (empty by default)
static/placeholder.png        # Legacy asset; never used as published poster
requirements.txt
tests/test_build.py
tests/test_discovery.py
```

## Offline tests

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
ENABLE_BROWSER_DISCOVERY=0 python build.py
python -m http.server --directory public 8000
```

The tests simulate official HTML, browser JSON and metadata API responses. They do not make live OceanVeil requests in this offline environment. A successful test **doesn't prove** GitHub runners can access the same resources as your normal browser.
