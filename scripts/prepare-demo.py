"""Create a disposable bug reproduction without overwriting existing files."""
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))
from backend.config import settings

workspace = Path(settings.ALLOWED_ROOT).resolve()
template = root / 'demo-template'
workspace.mkdir(parents=True, exist_ok=True)
for source in template.rglob('*.py'):
    target = workspace / source.relative_to(template)
    if target.exists():
        continue
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(source.read_bytes())
result = subprocess.run([sys.executable, 'app/main.py'], cwd=workspace, capture_output=True, text=True, timeout=5)
(workspace / 'terminal_stderr.log').write_text(result.stderr, encoding='utf-8')
print('Demo workspace:', workspace)
print('Reproduction exit code:', result.returncode)
print('Describe the terminal error in Prism. Relevant context is selected automatically.')
print('Suggested task: Diagnose the captured KeyError and propose a minimal fix to app/main.py, treating missing prices as zero. Use the current workspace_files. If isolated commands are unavailable, propose only the patch.')
