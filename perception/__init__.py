"""Real perception only. Tests inject collectors rather than selecting a demo mode."""
from shared.schemas import ContextBundle, ContextRequest


def collect_context(req: ContextRequest) -> ContextBundle:
    from perception.collector import collect_context as collect
    return collect(req)


def health() -> dict[str, bool]:
    from perception.screen import is_tesseract_available
    from perception.github import is_github_configured
    from perception.container_runtime import availability
    return {'tesseract': is_tesseract_available(), 'github_token': is_github_configured(), 'sandbox': availability()[0]}
