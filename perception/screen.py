"""
perception/screen.py
Handles screen capture via mss and OCR text extraction via pytesseract.
Applies secret redaction and ensures partial results over exceptions.
"""

import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple

import mss
from PIL import Image

from shared.schemas import ScreenContext
from perception.redactor import redact_secrets

# Configurable Tesseract path or executable search
_TESSERACT_ENV_VAR = "TESSERACT_PATH"
_DEFAULT_SCREENSHOT_DIR = Path(tempfile.gettempdir()) / "prism_screenshots"


def configure_tesseract() -> bool:
    """Configures pytesseract with the local binary if available."""
    try:
        import pytesseract

        # 1. Check explicit environment variable
        custom_path = os.getenv(_TESSERACT_ENV_VAR)
        if custom_path and os.path.isfile(custom_path):
            pytesseract.pytesseract.tesseract_cmd = custom_path
            return True

        # 2. Check standard Windows default paths
        win_candidates = [
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"),
        ]
        for candidate in win_candidates:
            if os.path.isfile(candidate):
                pytesseract.pytesseract.tesseract_cmd = candidate
                return True

        # 3. Check system PATH
        which_tesseract = shutil.which("tesseract")
        if which_tesseract:
            pytesseract.pytesseract.tesseract_cmd = which_tesseract
            return True

        return False
    except Exception:
        return False


def is_tesseract_available() -> bool:
    """Checks if tesseract executable is reachable and operational."""
    if not configure_tesseract():
        return False
    try:
        import pytesseract
        version = pytesseract.get_tesseract_version()
        return bool(version)
    except Exception:
        return False


def capture_screen(
    monitor_idx: int = 1,
    output_dir: Optional[Path] = None,
    run_ocr: bool = True,
) -> Tuple[Optional[ScreenContext], list[str]]:
    """
    Captures primary (or selected) monitor screen and extracts text via OCR.
    Never raises exceptions: returns (ScreenContext, warnings).
    """
    warnings: list[str] = []
    target_dir = output_dir or _DEFAULT_SCREENSHOT_DIR
    target_dir.mkdir(parents=True, exist_ok=True)

    screenshot_path: Optional[str] = None
    width = 0
    height = 0

    try:
        with mss.MSS() as sct:
            monitors = sct.monitors
            # monitors[0] is all monitors combined, monitors[1] is monitor 1
            if monitor_idx < len(monitors):
                mon = monitors[monitor_idx]
            else:
                mon = monitors[0]
                warnings.append(f"MONITOR_{monitor_idx}_NOT_FOUND_USING_PRIMARY")

            width = mon["width"]
            height = mon["height"]

            timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
            file_name = f"screen_{timestamp_str}.png"
            file_path = target_dir / file_name

            sct_img = sct.grab(mon)
            mss.tools.to_png(sct_img.rgb, sct_img.size, output=str(file_path))
            screenshot_path = str(file_path)
    except Exception as e:
        warnings.append(f"SCREEN_CAPTURE_FAILED: {type(e).__name__}")
        return None, warnings

    ocr_text = ""
    ocr_confidence: Optional[float] = None

    if run_ocr and screenshot_path:
        if not is_tesseract_available():
            warnings.append("TESSERACT_NOT_FOUND")
        else:
            try:
                import pytesseract

                with Image.open(screenshot_path) as img:
                    # Extract text and data for confidence calculation
                    raw_text = pytesseract.image_to_string(img, timeout=5)
                    ocr_text = redact_secrets(raw_text.strip())

                    # Calculate average confidence
                    data = pytesseract.image_to_data(
                        img, output_type=pytesseract.Output.DICT, timeout=5
                    )
                    confs = [
                        float(c)
                        for c in data.get("conf", [])
                        if str(c).strip() not in ("-1", "")
                    ]
                    if confs:
                        ocr_confidence = round(sum(confs) / (len(confs) * 100.0), 3)
            except Exception as ocr_err:
                warnings.append(f"OCR_FAILED: {type(ocr_err).__name__}")

    screen_ctx = ScreenContext(
        captured_at=datetime.now(timezone.utc),
        monitor=monitor_idx,
        width=width,
        height=height,
        ocr_text=ocr_text,
        ocr_confidence=ocr_confidence,
        screenshot_path=screenshot_path,
    )

    return screen_ctx, warnings
