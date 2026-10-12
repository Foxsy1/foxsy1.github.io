# OceanVeil Auto Catalog — metadata-only Stremio/Nuvio addon

**What it does:** checks publicly accessible OceanVeil listings, sitemaps, and a third-party index every day; adds newly detected anime to a Stremio-compatible catalog; and publishes static catalog JSON using GitHub Pages. Once installed, the same addon URL works in Stremio and Nuvio. Updates do **not** require editing MDBList.

**What it does not do:** this is **not** an official OceanVeil integration and it does **not** produce playable video streams, bypass a subscription, or extract protected content. **Completeness is not guaranteed.** The third-party `manhwaindex.com/platform/oceanveil` landing page exposes only a subset of its indexed titles; the OceanVeil site may block scrapers or lack a sitemap. Titles discovered in prior runs are retained if the source fails later. Titles removed from OceanVeil aren't automatically deleted. Adult-rated content may be included because this is an unfiltered directory.

## Install on GitHub (no always-on server)

1. Sign in at https://github.com and create a **public** repository named `oceanveil-auto-catalog`. GitHub Pages is available for public repositories on a free account, subject to current GitHub limits.
2. Upload the **contents** of this folder to the root of your repository, including the hidden `.github/workflows/update.yml` file. Uploading a ZIP as one file doesn't work; extract it and upload the files/folders. Use **Add file → Upload files** or GitHub Desktop; create nested directories as needed. Commit on `main`.
3. Open your repository's **Settings → Pages → Build and deployment → Source → GitHub Actions**. Save the setting. Do **not** choose the branch deploy option; workflow-created commits using `GITHUB_TOKEN` won't trigger that kind of Pages build.
4. Open **Actions → Update and publish OceanVeil catalog → Run workflow**, choosing `main`. Wait until both **build** and **deploy** show green. This build needs access to public title sources; if both block requests on the GitHub runner, the first build will fail rather than publish an empty catalog.
5. Open `https://YOUR-USERNAME.github.io/oceanveil-auto-catalog/manifest.json` in a browser (replace `YOUR-USERNAME` with your GitHub username). It should show JSON beginning with the addon `id`. Check `https://YOUR-USERNAME.github.io/oceanveil-auto-catalog/status.json` to see the number of detected titles.
6. In **Stremio**, open **Addons → Add addon by URL** (wording differs by version), paste your `manifest.json` URL, and install. In **Nuvio**, open **Settings → Content & Discovery → Addons → Add Addon**, paste **the same URL**, and install.
7. Look for **OceanVeil Anime** in the relevant home/discover catalog. The GitHub workflow runs automatically each day at **03:15 UTC** and republishes the list. You don't need to re-install it for normal title additions. Clients may show cached results briefly.

## Structure

- `build.py` — public-page scraper + static addon generator, uses only publicly accessible metadata.
- `.github/workflows/update.yml` — daily schedule plus a one-click manual run; builds and deploys directly through GitHub Pages Actions.
- `state.json` — generated/committed by the workflow, storing past discoveries.
- `public/` — generated Stremio addon files (not committed; deployed as Pages artifact).
- `static/placeholder.png` — generic poster for listings without artwork.
- `tests/test_build.py` — offline example tests.

## Verify / troubleshoot

If the generated catalog appears empty or no new shows are being added, check **Actions → latest run → Update catalog** and the `status.json` URL. The scraper respects any readable `robots.txt` blocks; remove any disallowed source rather than trying to bypass protections. OceanVeil may change its HTML or block GitHub Actions IPs, in which case the parsing rules or permitted source need to be updated.

If you have a GitHub repository with a different name, the deployed URL ends with **that** repository name. If Pages is blocked by organization policy or a private-repo plan, choose a Pages-capable public repository or a different HTTPS host. For an account/organization with a custom GitHub Pages domain, add the repository Actions variable `PAGES_BASE_URL` and pass it in `update.yml` to override poster fallback paths.

To run locally (requires Python 3.10+ and internet):

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python build.py
python -m http.server --directory public 8000
```

Then open `http://localhost:8000/manifest.json` to inspect the generated manifest (the URL installed in actual clients should be the **public HTTPS GitHub Pages URL**, not localhost).

## Why a static Stremio addon?

The Stremio protocol serves `manifest.json`, `catalog/series/oceanveil-anime.json`, and per-title `meta/series/oceanveil:ID.json`. The build script also prepares `catalog/series/oceanveil-anime/skip=100.json`, `skip=200.json`, etc. to support Stremio's default 100-result paging. Nuvio supports the same basic catalog/meta endpoints. The addon deliberately does not implement `stream`.

Official specification: https://stremio.github.io/stremio-addon-sdk/protocol.html

GitHub Pages Actions: https://github.com/actions/deploy-pages

## Data/privacy/rights

The scraper uses only public page titles, outbound links, and poster URLs. It doesn't use your OceanVeil login or cookies, doesn't store passwords or subscriptions, and doesn't download videos. Respect OceanVeil's terms, website robots policy, and applicable copyright requirements. Third-party artwork URLs can change, and some titles may disappear or be renamed. Do not use this directory to claim guaranteed title or playback availability in your region.
