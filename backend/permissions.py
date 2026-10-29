"""One authoritative access policy, shared by collection and execution."""
import json
import os
from pathlib import Path
from shared.schemas import AccessSettings


class PermissionStore:
    def __init__(self, path: Path | None = None):
        self.path = path
        self.settings = AccessSettings()
        if path and path.exists():
            try:
                self.settings = AccessSettings.model_validate_json(path.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                # Corrupt policy must never re-enable revoked collection.
                self.settings = AccessSettings(screen=False, terminal=False, processes=False)

    def update(self, capability: str, allowed: bool):
        updated = self.settings.model_copy(update={capability: allowed})
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix('.tmp')
            temporary.write_text(updated.model_dump_json(indent=2), encoding='utf-8')
            os.replace(temporary, self.path)
        self.settings = updated


from backend.config import settings
permission_store = PermissionStore(Path(settings.STATE_DIR) / 'access.json')


def command_permissions(argv: list[str]) -> set[str]:
    """Conservative package-manager classification; runtime mounts/network enforce scope."""
    if not argv:
        return set()
    binary = Path(argv[0]).stem.lower()
    args = [item.lower() for item in argv[1:]]
    package_manager = binary in {'pip', 'pip3', 'npm', 'npx', 'yarn', 'pnpm', 'poetry', 'cargo', 'go'}
    python_pip = binary in {'python', 'python3', 'py'} and len(args) >= 2 and args[:2] == ['-m', 'pip']
    if (package_manager or python_pip) and any(arg in {'install', 'i', 'ci', 'add', 'update', 'upgrade', 'download', 'get'} for arg in args):
        return {'install_dependencies', 'modify_files', 'network'}
    if binary == 'npx':
        return {'install_dependencies', 'modify_files', 'network'}
    if binary == 'git' and any(arg in {'fetch', 'pull', 'push', 'clone', 'ls-remote'} for arg in args):
        return {'network', 'modify_files'}
    return set()


def proposal_permissions(proposal) -> set[str]:
    required = set(proposal.required_permissions)
    if proposal.files:
        required.add('modify_files')
    if proposal.requires_network:
        required.add('network')
    for argv in proposal.commands:
        required.update(command_permissions(argv))
    if 'install_dependencies' in required:
        required.update({'modify_files', 'network'})
    return required & {'modify_files', 'install_dependencies', 'network'}
