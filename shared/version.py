"""Version the installed artifact; development retains the public API version."""
import json
from pathlib import Path

manifest = Path(__file__).resolve().parent.parent/'release.json'
VERSION = json.loads(manifest.read_text())['version'] if manifest.is_file() else '1.0.0'
