"""Static SEO regression checks. Run: python -m unittest discover -s tests -v."""
import json
from html.parser import HTMLParser
from pathlib import Path
import unittest
from urllib.parse import unquote, urlsplit
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
BASE = 'https://habjjan.com/'
NS = {'s': 'http://www.sitemaps.org/schemas/sitemap/0.9',
      'x': 'http://www.w3.org/1999/xhtml',
      'i': 'http://www.google.com/schemas/sitemap-image/1.1'}


class Page(HTMLParser):
    def __init__(self, path):
        super().__init__(convert_charrefs=True)
        self.path, self.tags, self.graphs = path, [], []
        self.ld = None
        self.feed(path.read_text())
        self.canonical = next(a['href'] for t, a in self.tags
                              if t == 'link' and a.get('rel') == 'canonical')

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.tags.append((tag, attrs))
        if tag == 'script' and attrs.get('type') == 'application/ld+json':
            self.ld = ''

    def handle_data(self, data):
        if self.ld is not None:
            self.ld += data

    def handle_endtag(self, tag):
        if tag == 'script' and self.ld is not None:
            self.graphs.append(json.loads(self.ld))
            self.ld = None

    def alternatives(self):
        return {a['hreflang']: a['href'] for t, a in self.tags
                if t == 'link' and a.get('rel') == 'alternate'}


class SEOTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pages = [Page(p) for p in sorted(ROOT.rglob('index.html'))
                     if '.git' not in p.parts]
        cls.by_url = {p.canonical: p for p in cls.pages}
        cls.sitemap = ET.parse(ROOT / 'sitemap.xml').getroot()

    def test_canonicals_and_language_alternatives(self):
        self.assertEqual(len(self.pages), 24)
        self.assertEqual(len(self.by_url), len(self.pages))
        for page in self.pages:
            with self.subTest(page=page.path):
                self.assertEqual(page.path, ROOT / unquote(urlsplit(page.canonical).path).lstrip('/') / 'index.html')
                self.assertEqual(set(page.alternatives()), {'fr', 'en', 'it', 'x-default'})
                for target in page.alternatives().values():
                    self.assertEqual(page.alternatives(), self.by_url[target].alternatives())

    def test_metadata_complete_and_unique(self):
        for page in self.pages:
            with self.subTest(page=page.path):
                metas = [a for t, a in page.tags if t == 'meta']
                for key in ['description', 'robots', 'twitter:card', 'twitter:title', 'twitter:description', 'twitter:image']:
                    found = [a['content'] for a in metas if a.get('name') == key]
                    self.assertEqual(len(found), 1, key)
                    self.assertTrue(found[0])
                for key in ['og:type', 'og:site_name', 'og:title', 'og:description', 'og:url', 'og:image', 'og:locale']:
                    found = [a['content'] for a in metas if a.get('property') == key]
                    self.assertEqual(len(found), 1, key)
                    self.assertTrue(found[0])
                self.assertFalse(any('noindex' in a.get('content', '') for a in metas if a.get('name') == 'robots'))

    def test_linked_artist_and_website_identity(self):
        expected_socials = None
        for page in self.pages:
            with self.subTest(page=page.path):
                self.assertEqual(len(page.graphs), 1)
                nodes = page.graphs[0]['@graph']
                ids = [n['@id'] for n in nodes if '@id' in n]
                self.assertEqual(len(ids), len(set(ids)))
                artist = next(n for n in nodes if n.get('@id') == BASE+'#artist')
                self.assertEqual(artist['@type'], 'Person')
                self.assertEqual(artist['url'], BASE)
                expected_socials = expected_socials or artist['sameAs']
                self.assertEqual(artist['sameAs'], expected_socials)
                site = next(n for n in nodes if n.get('@id') == BASE+'#website')
                self.assertEqual(site['url'], BASE)
                node = next(n for n in nodes if n.get('@id') == page.canonical+'#webpage')
                self.assertEqual(node['url'], page.canonical)
                if node['@type'] == 'ProfilePage':
                    self.assertEqual(node['mainEntity'], {'@id': BASE+'#artist'})

    def test_internal_links_and_assets_exist(self):
        for page in self.pages:
            for tag, attrs in page.tags:
                keys = ['src', 'poster'] if tag in ['img', 'source', 'video', 'audio'] else ['href'] if tag in ['a', 'link'] else []
                for key in keys:
                    value = attrs.get(key, '')
                    parts = urlsplit(value)
                    if not parts.path or parts.scheme and parts.netloc != 'habjjan.com':
                        continue
                    local = ROOT / unquote(parts.path).lstrip('/') if parts.path.startswith('/') else page.path.parent / unquote(parts.path)
                    if parts.path.endswith('/'):
                        local /= 'index.html'
                    with self.subTest(page=page.path, url=value):
                        self.assertTrue(local.is_file(), value)

    def test_sitemap_pages_alternates_and_images(self):
        entries = self.sitemap.findall('s:url', NS)
        self.assertEqual({e.find('s:loc', NS).text for e in entries}, set(self.by_url))
        self.assertEqual(len(entries), len(self.pages))
        for entry in entries:
            page = self.by_url[entry.find('s:loc', NS).text]
            alts = {e.get('hreflang'):e.get('href') for e in entry.findall('x:link', NS)}
            self.assertEqual(alts, page.alternatives())
            expected = {BASE.rstrip('/')+a['src'] for t, a in page.tags if t == 'img'}
            self.assertEqual({e.text for e in entry.findall('i:image/i:loc', NS)}, expected)


if __name__ == '__main__':
    unittest.main()
