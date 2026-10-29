"""Shared credential-path boundary for collection, patching, and command roots."""
from pathlib import Path
import os

EXAMPLES = {'.env.example', '.env.sample', '.env.template'}
PRIVATE_DIRS = {'.ssh', '.aws', '.azure', '.gnupg', '.kube'}
PRIVATE_FILES = {'.npmrc', '.pypirc', '.netrc', '_netrc', 'credentials',
                 'credentials.json', 'service-account.json', 'id_rsa', 'id_dsa',
                 'id_ecdsa', 'id_ed25519'}


def sensitive_path(path: Path, *, git: bool = True) -> bool:
    for part in path.parts:
        name = part.lower()
        if name in EXAMPLES:
            continue
        if (git and name == '.git') or name in PRIVATE_DIRS or name in PRIVATE_FILES:
            return True
        if name == '.env' or name.startswith('.env.') or name.endswith(('.pem', '.key', '.p12', '.pfx')):
            return True
    return False


def safe_workspace(root: Path, *, check_files: bool = False) -> Path:
    """Fail closed for known credentials; full-tree mounts grant full-tree reads.

    Git metadata is intentionally mounted for approved Git commands. Unknown
    credentials cannot be identified by filename: users must keep them outside
    this workspace as well. Symlinks/junctions are rejected for command mounts.
    """
    from backend.config import APP_ROOT, settings
    root = root.resolve(strict=True)
    state = Path(settings.STATE_DIR).resolve()
    if not root.is_dir() or root == Path(root.anchor) or APP_ROOT.is_relative_to(root) or state.is_relative_to(root):
        raise ValueError('UNSAFE_WORKSPACE_ROOT')
    if check_files:
        count = 0
        def scan_error(error):
            raise ValueError('WORKSPACE_SCAN_FAILED') from error
        for directory, dirs, files in os.walk(root, followlinks=False, onerror=scan_error):
            for name in dirs + files:
                count += 1
                if count > 100_000:
                    raise ValueError('WORKSPACE_SCAN_LIMIT')
                path = Path(directory) / name
                if path.is_symlink() or getattr(path.lstat(), 'st_file_attributes', 0) & 0x400:
                    raise ValueError('WORKSPACE_LINK_NOT_ALLOWED')
                if sensitive_path(path.relative_to(root), git=False):
                    raise ValueError('WORKSPACE_CONTAINS_CREDENTIAL_FILES')
    return root
