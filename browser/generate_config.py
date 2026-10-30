"""Export the local application's selection metadata for static hosting."""
import json
import hashlib
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import server

payload = dict(
    version=3, defaults=server.APP_DEFAULTS, presets=server.APP_PRESETS,
    limits=server.LIMITS, algorithms=server.ALGORITHMS,
    plant_fields=server.PLANT_FIELDS, experiments=server.EXPERIMENTS,
    circuit_references=server.CIRCUIT_REFERENCES,
    default_preset_id=server.C07_PRESET['id'], reference_preset=server.C07_PRESET,
    verification=None, verification_url=None,
)
files = (sorted(ROOT.glob('*.py')) + [ROOT / 'c07_preset.json']
         + sorted(path for path in (ROOT / 'static').glob('*') if path.is_file())
         + sorted(path for path in (ROOT / 'browser').glob('*')
                  if path.suffix in ('.py', '.js', '.wasm', '.css')))
digest = hashlib.sha256()
for path in files:
    digest.update(path.relative_to(ROOT).as_posix().encode())
    digest.update(path.read_bytes())
payload['browser_build'] = digest.hexdigest()[:20]
(ROOT / 'browser' / 'config.json').write_text(
    json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(',', ':')) + '\n',
    encoding='utf-8')
