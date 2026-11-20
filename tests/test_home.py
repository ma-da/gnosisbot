"""HTML and golden spiral contracts for the new home page."""
import re
import unittest
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / 'app' / 'static'


class Reader(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.hrefs = []
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if 'id' in a: self.ids.append(a['id'])
        if 'href' in a: self.hrefs.append(a['href'])


class LandingPageTests(unittest.TestCase):
    def test_structure_and_accessible_navigation(self):
        html = (ROOT / 'index.html').read_text(encoding='utf8')
        parser = Reader()
        parser.feed(html)
        self.assertEqual(len(parser.ids), len(set(parser.ids)), 'duplicate HTML element IDs')
        self.assertIn('about', parser.ids)
        self.assertIn('contact', parser.ids)
        self.assertTrue(any(h in parser.hrefs for h in ('#contact','/#contact')))
        self.assertIn('/quantum-oracle.html', parser.hrefs)
        self.assertIn('id="spiral-segments"', html)
        self.assertIn('/assets/images/Quantum-Oracle-Signal-Flow.png', html)
        self.assertIn('class="quantum-diagram"', html)
        self.assertIn('Quantum oracle signal flow', html)
        self.assertIn('/assets/images/Quantum-Oracle-Signal-Flow.png', html)
        self.assertIn('name="name"', html)
        self.assertIn('name="email"', html)
        self.assertIn('name="message"', html)
        self.assertIn('method="POST"', html)

    def test_gold_ratio_and_placeholder_links(self):
        js = (ROOT / 'js' / 'home.js').read_text(encoding='utf8')
        self.assertIn('FIBONACCI_TILES', js)
        self.assertIn('quarterDiscPath(', js)
        self.assertIn('SPIRAL_DESTINATIONS', js)
        self.assertIn('selectSegment(', js)
        self.assertIn('coming soon', js)
        self.assertIn('FIBONACCI_TILES', js)
        self.assertEqual(len(re.findall(r'^  [1-7]: null,?$', js, re.M)), 7)
        self.assertIn('coming soon', js)
        css = (ROOT / 'css' / 'global.css').read_text(encoding='utf8')
        self.assertIn('.home-tile--spiral', css)
        self.assertIn('.contact-form', css)
        self.assertLess(css.index('.home-tile--spiral'), css.index('@media (max-width: 680px)'))


if __name__ == '__main__':
    unittest.main()
