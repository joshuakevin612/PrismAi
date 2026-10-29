"""Collect installed dependency license notices without changing the UI bundle."""
import importlib.metadata
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent.parent
LICENSE_NAME = re.compile(r'^(licen[cs]e|copying|notice)([._-].*)?$', re.I)


def main():
    lock = json.loads((ROOT/'frontend/package-lock.json').read_text())
    notices = ['Third-party JavaScript dependency notices\nGenerated from the installed locked dependency tree.\n']
    for relative, metadata in sorted(lock['packages'].items()):
        if not relative:
            continue
        package = ROOT/'frontend'/relative
        if not (package/'package.json').is_file():
            continue  # Optional packages for other operating systems.
        data = json.loads((package/'package.json').read_text(encoding='utf-8'))
        notices.append(f"\n{'='*72}\n{data.get('name',relative)} {metadata.get('version','')}\nLicense: {data.get('license','See package notices')}\n")
        for path in sorted(package.iterdir()):
            if path.is_file() and LICENSE_NAME.match(path.name):
                notices.append(path.read_text(encoding='utf-8',errors='replace'))
    (ROOT/'frontend/THIRD_PARTY_NOTICES.txt').write_text('\n'.join(notices),encoding='utf-8')
    notices = ['Third-party Python dependency notices\nGenerated from the installed application environment.\n']
    for distribution in sorted(importlib.metadata.distributions(),key=lambda d:d.metadata['Name'].lower()):
        notices.append(f"\n{'='*72}\n{distribution.metadata['Name']} {distribution.version}\nLicense: {distribution.metadata.get('License-Expression',distribution.metadata.get('License','See package notices'))}\n")
        for relative in distribution.files or []:
            if LICENSE_NAME.match(relative.name) and ('.dist-info' in str(relative) or '.egg-info' in str(relative)):
                path = distribution.locate_file(relative)
                if path.is_file():
                    notices.append(path.read_text(encoding='utf-8',errors='replace'))
    (ROOT/'docs/THIRD_PARTY_PYTHON_NOTICES.txt').write_text('\n'.join(notices),encoding='utf-8')
    print('Collected JavaScript and Python dependency notices.')


if __name__ == '__main__':
    main()
