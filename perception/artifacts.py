"""Session-owned screenshot storage with expiry and bounded cleanup."""
from pathlib import Path
import tempfile
import threading
import time
import uuid


class ScreenshotStore:
    def __init__(self):
        self.directory = None
        self.files = {}
        self.lock = threading.RLock()
        self.closed = False

    def allocate(self) -> Path:
        with self.lock:
            if self.closed:
                raise RuntimeError('Screenshot session closed')
            if self.directory is None:
                self.directory = Path(tempfile.mkdtemp(prefix='prism-session-')).resolve()
            path = self.directory / ('screen_' + uuid.uuid4().hex + '.png')
            self.files[path] = time.monotonic()
            return path

    def cleanup(self, ttl: float = 3600, close: bool = False):
        with self.lock:
            if close:
                self.closed = True
            for path, created in list(self.files.items()):
                if close or time.monotonic() - created >= ttl:
                    if self.directory and path.parent == self.directory and not path.is_symlink():
                        try:
                            path.unlink(missing_ok=True)
                            del self.files[path]
                        except OSError:
                            pass  # A capture/OCR reader may still hold the file.
            if close and self.directory:
                try:
                    self.directory.rmdir()  # Never recursively remove unknown content.
                except OSError:
                    pass


    def discard(self, path: Path):
        with self.lock:
            if path in self.files and self.directory and path.parent == self.directory and not path.is_symlink():
                try:
                    path.unlink(missing_ok=True)
                    self.files.pop(path, None)
                except OSError:
                    pass

    def reopen(self):
        with self.lock:
            if self.closed:
                self.directory = None
                self.files = {}
                self.closed = False


screenshots = ScreenshotStore()
