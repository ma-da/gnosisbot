import re
import unittest
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / 'app' / 'static'


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.stylesheets = []
        self.options = []
        self._in_option = False
        self.in_header = False
        self.mode_in_header = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if 'id' in a:
            self.ids.append(a['id'])
        if tag == 'header':
            self.in_header = True
        if tag == 'select' and a.get('id') == 'mode-select':
            self.mode_in_header = self.in_header
        if tag == 'link' and a.get('rel') == 'stylesheet':
            self.stylesheets.append(a['href'].split('?')[0])
        if tag == 'option':
            self._in_option = True

    def handle_endtag(self, tag):
        if tag == 'option':
            self._in_option = False
        if tag == 'header':
            self.in_header = False

    def handle_data(self, data):
        if self._in_option and data.strip():
            self.options.append(data.strip())


class LayoutTests(unittest.TestCase):
    def test_single_global_stylesheet_and_compact_structure(self):
        html = (STATIC / 'quantum-oracle.html').read_text(encoding='utf8')
        parsed = PageParser()
        parsed.feed(html)
        self.assertEqual(
            [x for x in parsed.stylesheets if x.startswith('/assets/css/')],
            ['/assets/css/global.css', '/assets/css/system-health.css', '/assets/css/site-shell-v2.css']
        )
        self.assertFalse(parsed.mode_in_header)
        self.assertEqual(parsed.options, [])
        self.assertNotIn('id="mode-select"', html)
        self.assertIn('consultation', html.lower())
        self.assertEqual(len(parsed.ids),len(set(parsed.ids)))
        self.assertFalse((STATIC / 'css' / 'app.css').exists())
        self.assertFalse((STATIC / 'css' / 'tokens.css').exists())
        self.assertIn('id="reading-status"',html)
        self.assertLess(html.index('id="visual"'),html.index('id="interference"'))
        self.assertLess(html.index('id="interference"'),html.index('class="switcher"'))
        self.assertLess(html.index('class="switcher"'),html.index('id="interpret-title"'))

    def test_explicit_quantum_reveal_and_phase_controls(self):
        html = (STATIC / 'quantum-oracle.html').read_text(encoding='utf8')
        appjs = (STATIC / 'js' / 'app.js').read_text(encoding='utf8')
        vizjs = (STATIC / 'js' / 'viz.js').read_text(encoding='utf8')
        self.assertIn('disabled>Quantum Reading</button>',html)
        self.assertIn('disabled>Becoming</button>',html)
        self.assertIn('!consultationStarted', appjs)
        self.assertIn('hardware && !revealedNow', appjs)
        self.assertIn('consultation?.open()', appjs)
        self.assertIn("render('becoming')", appjs)
        self.assertIn('if (!revealedNow) { void revealNow(); return; }', appjs)
        self.assertIn("render('becoming');viz?.showPhase('becoming',true)",appjs)
        self.assertIn('async revealNow()',vizjs)
        self.assertIn('startAmbient()',vizjs)
        self.assertNotIn('autoplayBecoming',vizjs)
        self.assertNotIn("onPhase('becoming')",vizjs)

    def test_viewport_constrained_ring_and_responsive_order(self):
        css=(STATIC / 'css' / 'global.css').read_text(encoding='utf8')
        self.assertIn('--viewport-height: 100dvh',css)
        self.assertIn('--ring-size: min(',css)
        self.assertIn('var(--viewport-height) - var(--header-h)',css)
        self.assertIn('var(--interference-height) - var(--controls-reserve)',css)
        self.assertIn('width: var(--ring-size)',css)
        self.assertIn('height: var(--ring-size)',css)
        self.assertLess(css.index(':root {'),css.index('.topbar {'))
        self.assertLess(css.index('.content {'),css.index('@media (max-width: 680px)'))
        self.assertLess(css.index('@media (max-width: 680px)'),css.index('@media (prefers-reduced-motion: reduce)'))

    def test_preserves_radial_hex_and_long_morph(self):
        viz = (STATIC / 'js' / 'viz.js').read_text(encoding='utf8')
        config=(STATIC / 'js' / 'config.js').read_text(encoding='utf8')
        self.assertIn('rotationDeg=(angle+Math.PI/2)*180/Math.PI',viz)
        self.assertIn('const glyphWidth=25.5',viz)
        self.assertIn('morphMs: 2640',config)
        self.assertIn('this.hanzi.transition().duration(720)',viz)
        self.assertIn('.duration(1200)',viz)

if __name__=='__main__':
    unittest.main()
