"""Single-process state ownership and bounded local diagnostic logs."""
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from perception.redactor import redact_secrets
from shared.instance import instance_lock
from shared.version import VERSION


class RedactedJSONFormatter(logging.Formatter):
    def format(self, record):
        result = {'time': self.formatTime(record), 'level': record.levelname,
                  'logger': record.name, 'version': VERSION, 'message': redact_secrets(record.getMessage())}
        if record.exc_info:
            result['exception'] = redact_secrets(self.formatException(record.exc_info))
        return json.dumps(result, ensure_ascii=False)


def configure_logs(state: Path):
    directory = state / 'logs'
    directory.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(directory / 'prism.log', maxBytes=2_000_000, backupCount=3, encoding='utf-8')
    handler.setFormatter(RedactedJSONFormatter())
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    for existing in root.handlers:
        existing.setFormatter(RedactedJSONFormatter())
