"""Check active source and tracked sensitive paths; never print matched values."""
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from shared.paths import sensitive_path

PATTERNS = [re.compile(r'\bgh[pousr]_[A-Za-z0-9]{36,}\b'),
            re.compile(r'\bgithub_pat_[A-Za-z0-9_]{22,}\b'),
            re.compile(r'\bAKIA[0-9A-Z]{16}\b'),
            re.compile(r'\bnvapi-[A-Za-z0-9_-]{20,}\b'),
            re.compile(r'-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----')]


def scan(root=ROOT):
    findings = []
    for directory in ('backend','perception','shared','scripts','frontend/src'):
        for path in (root/directory).rglob('*'):
            if path.is_file() and path.suffix in {'.py','.ts','.tsx','.js','.mjs'}:
                for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(),1):
                    if any(pattern.search(line) for pattern in PATTERNS):
                        findings.append(f'{path.relative_to(root)}:{number}: credential pattern')
    tracked = subprocess.run(['git','-C',str(root),'ls-files','-z'],capture_output=True,text=True)
    if tracked.returncode == 0:
        for name in tracked.stdout.split('\0'):
            if name and sensitive_path(Path(name)):
                findings.append(f'{name}: tracked sensitive path')
    return findings


if __name__ == '__main__':
    findings = scan()
    print('\n'.join(findings) if findings else 'Active source credential check passed.')
    raise SystemExit(bool(findings))
