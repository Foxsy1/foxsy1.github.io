# OceanVeil Catalog V5 — accurate cards and playback-compatible IDs

**This is a corrective release, not a claim that OceanVeil discovery is solved.** V1–V3 produced broken or placeholder posters and many nonstandard `oceanveil:` IDs that normal stream addons do not understand. V4 introduced optional TMDB/TVDB/MDBList enrichment but still allowed unusable fallback cards. V5 enforces quality gates and exports source diagnostics.

## What changes

- **Only publish a title** when it resolves to a standard `tmdb:123` or `tt1234567` ID **and** has a TMDB or Kitsu poster. Unmatched, incorrectly mapped, and posterless titles are not pushed to the main home catalog. The status JSON reports everything excluded, so no titles silently disappear.
- **Stop using OceanVeil-hosted poster links and generic placeholders.** They often break in Nuvio; use metadata-provider artwork instead. A valid-looking image CDN URL might still 404, but no source-site poster is deliberately reused.
- **Adult anime can be searched on TMDB** (`include_adult=true`, relevant to OceanVeil). Prefixes like `[Dub]` and `(Sub)` are removed *for matching only*; visible titles retain their original names.
- **Avoid ambiguous matching** when multiple media entries score too similarly, including two identically named adaptations.
- **Use standard Stremio catalog format** (`series` + `movie`, `/catalog/.../xxx.json` and `/skip=0.json`) and the same canonical `tmdb:` ID pattern as NuvEng. Metadata and video streams still come from your **installed Nuvio/Stremio addons**.
- **Source diagnostics:** `source-debug.json` records public page size, headings, sample image alt text, and whether `/anime_titles/123` links appear in the HTML and browser-rendered DOM. It **does not** publish cookie, authentication, or API key information.
- **Daily scheduled rebuild at 03:15 UTC** (08:15 Pakistan), plus manual and push triggers, remains enabled.

## Install / replace your repository

1. Download the V5 ZIP, extract it, and upload the **contents** of the folder to your existing [GitHub repository](https://github.com/oceanveil-auto-catalog/oceanveil-auto-catalog.github.io), replacing files at the root. Include the hidden `.github/workflows/update.yml` path. **Do not delete `state.json`** if already present; it preserves old matches between runs.
2. Configure GitHub repository **Settings → Pages → Source: GitHub Actions**.
3. Add **Settings → Secrets and variables → Actions → New repository secret**:
   - `TMDB_API_KEY` — your TMDB API key **or long read token** (`eyJ...`). **Strongly recommended** for usable catalog cards.
   - `MDBLIST_API_KEY` — your MDBList API key (optional for ratings).
   - `TVDB_API_KEY` / `TVDB_PIN` — optional, **not necessary**.
4. Run **Actions → Update and publish OceanVeil catalog → Run workflow** and ensure both build and deploy succeed.
5. Remove your **old OceanVeil addon** from Nuvio/Stremio, then install `https://oceanveil-auto-catalog.github.io/manifest.json` and enable its **OceanVeil Anime** row in the applicable Nuvio profile. Reopen/refresh Nuvio.

### Check these URLs after deployment

- Manifest: https://oceanveil-auto-catalog.github.io/manifest.json — should contain `"version": "1.5.0"`.
- Catalog: https://oceanveil-auto-catalog.github.io/catalog/series/oceanveil-anime.json — `"metas"` entries, every `id` must be `tmdb:` or `tt...`, with external artwork.
- Browser preview: https://oceanveil-auto-catalog.github.io/catalog-preview.html — preview before Nuvio.
- Status: https://oceanveil-auto-catalog.github.io/status.json — key fields are `known_title_count`, `raw_known_title_count`, `excluded_title_count`, `live_titles_extracted_this_run`, `metadata_apis_configured`, `identifier_counts`, `published_historical_snapshot_count`.
- Source diagnostics: https://oceanveil-auto-catalog.github.io/source-debug.json — shows *why* OceanVeil page parsing is failing/succeeding.

### If the catalog is empty

This is **not automatically a Nuvio bug**. V5 deliberately rejects invalid IDs/artwork. If TMDB/Kitsu cannot resolve the historical starter titles, it can publish an empty catalog rather than making up posters or IDs. Check `status.json` for `excluded_titles` and `metadata_apis_configured`. You need correct secrets, a successful enrichment run, and actual discoverable titles. Existing `state.json` may contain old V2 `oceanveil:` records; V5 will try to enrich them rather than blindly displaying them.

### What about playback?

V5 **does not disable** Stremio/Nuvio playback. Standard TMDB/IMDb IDs let your existing **installed** stream addons handle episodes and movies, assuming they can identify that media and have a source. **A matched ID is not a guarantee of playable video.** OceanVeil's membership videos require their own session/player. A static GitHub Pages catalog cannot fetch protected, authenticated, or expiring video links on-demand. No one can truthfully claim this ZIP already supplies direct OceanVeil streams without a verified, authorized integration. `streams.json` remains available for explicitly supplied, playable HTTPS media URLs or external watch links; do not commit private tokens or signed URLs.

### Does it auto-update OceanVeil?

The updater *runs daily*, but **live discovery is not yet verified**. Earlier logs showed zero titles extracted even when source pages returned HTTP 200, and the secondary index returned HTTP 403. This release adds `source-debug.json`, so you can inspect HTML structure from the GitHub runner and we can implement a real parser rather than inventing another fake fallback. Successful build/deploy **does not** prove live catalog updates.

## Structure

```
.github/workflows/update.yml  # Tests, daily build, state commit, Pages publish
build.py                      # Public source discovery, quality gates, manifests
enrichment.py               # Kitsu → Fribb → TMDB, TVDB/MDBList (optional)
seed.json                     # Historical source candidates, not real-time availability
streams.json                  # Optional manually verified links; empty initially
static/placeholder.png        # Legacy asset; not used for catalog posters
tests/test_build.py           # Offline source/API/format checks
requirements.txt
```

## Offline testing

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
ENABLE_BROWSER_DISCOVERY=0 python build.py
python -m http.server --directory public 8000
```

The offline tests mock source and metadata servers. They verify code paths, **not** actual live OceanVeil or Nuvio availability.
