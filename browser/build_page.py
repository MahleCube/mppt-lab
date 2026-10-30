"""Generate the GitHub Pages entry point from the shared application UI."""
from pathlib import Path
import json
import re

ROOT = Path(__file__).resolve().parent.parent
html = (ROOT / 'static/index.html').read_text(encoding='utf-8')
html = re.sub(r'(href|src)="/([^"?]+\.(?:css|js))"', r'\1="static/\2"', html)
html = re.sub(r'href="/([^"/]+\.md)"', r'href="\1"', html)
html = html.replace('</head>', '  <link rel="stylesheet" href="browser/runtime.css">\n</head>')
html = html.replace('<script src="static/layout.js">', '<script src="browser/api.js"></script>\n<script src="static/layout.js">')
version = json.loads((ROOT / 'browser/config.json').read_text(encoding='utf-8'))['browser_build']
html = re.sub(r'((?:href|src)="(?:static|browser)/[^"?]+\.(?:css|js))"',
              lambda match: match.group(1) + '?v=' + version + '"', html)
(ROOT / 'index.html').write_text(html, encoding='utf-8')
(ROOT / '.nojekyll').touch()
