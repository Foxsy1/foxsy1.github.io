import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build as generator


class OfflineFeed:
    pages = {
        generator.SECONDARY: '<html><a href="/anime/angel-beats">Angel Beats!</a></html>',
        'https://manhwaindex.com/anime/angel-beats': '''<h1>Angel Beats!</h1><img alt="Cover of Angel Beats!" src="https://cdn.example.net/angel.jpg" />
            <a href="https://oceanveil.net/anime_titles/434">Watch on OceanVeil</a>''',
        'https://oceanveil.net/': '<a href="/anime_titles/500"><img alt="Added from OceanVeil" src="/poster500.jpg"></a>',
        'https://oceanveil.net/anime_titles': '',
        'https://oceanveil.net/sitemap.xml': '<urlset><url><loc>https://oceanveil.net/anime_titles/501</loc></url></urlset>',
        'https://oceanveil.net/sitemap_index.xml': '',
        'https://oceanveil.net/anime_titles/501': '<meta property="og:title" content="New from sitemap" /><meta property="og:image" content="https://img.example/poster.jpg" />',
    }

    def get(self, url):
        return self.pages.get(url)


class Tests(unittest.TestCase):
    def test_catalog_build_and_remembers_titles(self):
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            (root / 'static').mkdir()
            (root / 'static' / 'placeholder.png').write_bytes(b'posterfixture')
            with patch.object(generator, 'ROOT', root), patch.object(generator, 'STATE_FILE', root / 'state.json'), patch.object(generator, 'OUT', root / 'public'), patch.object(generator, 'GentleFetcher', OfflineFeed):
                generator.build()
                manifest = json.loads((root / 'public' / 'manifest.json').read_text())
                data = json.loads((root / 'public' / 'catalog' / 'series' / 'oceanveil-anime.json').read_text())
                self.assertEqual(manifest['catalogs'][0]['name'], 'OceanVeil Anime')
                self.assertEqual(len(data['metas']), 3)
                self.assertTrue((root / 'public' / 'meta' / 'series' / 'oceanveil:434.json').exists())
                # Next run with nothing available still builds from saved state.
                with patch.object(generator, 'GentleFetcher', type('Empty', (), {'get': lambda self, url: None})):
                    generator.build()
                    data = json.loads((root / 'public' / 'catalog' / 'series' / 'oceanveil-anime.json').read_text())
                    self.assertEqual(len(data['metas']), 3)


if __name__ == '__main__':
    unittest.main()
