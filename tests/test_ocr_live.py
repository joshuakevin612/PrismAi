"""Use the actual Tesseract binary against a reproducible synthetic capture."""
import os
import shutil
from types import SimpleNamespace
import pytest
from PIL import Image, ImageDraw, ImageFont
from perception import screen

pytestmark = pytest.mark.skipif(os.getenv('PRISM_RUN_OCR_TESTS') != '1', reason='Requires Tesseract installed')


def test_actual_tesseract_text_and_redaction(tmp_path, monkeypatch):
    assert screen.is_tesseract_available()
    image = Image.new('RGB', (900, 180), 'white')
    draw = ImageDraw.Draw(image)
    from pathlib import Path
    candidates = [Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'),
                  Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts/arial.ttf',
                  Path('/System/Library/Fonts/Supplemental/Arial.ttf')]
    font = next((ImageFont.truetype(str(p), 32) for p in candidates if p.is_file()), ImageFont.load_default(size=32))
    draw.text((20, 20), 'Prism verification', fill='black', font=font)
    draw.text((20, 80), 'password=supersecret123', fill='black', font=font)
    class Capture:
        monitors = [{'width':900,'height':180}] * 2
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def grab(self, monitor): return SimpleNamespace(rgb=image.tobytes(), size=image.size)
    monkeypatch.setattr(screen.mss, 'MSS', Capture)
    context, warnings = screen.capture_screen(output_dir=tmp_path)
    assert context and 'Prism' in context.ocr_text and not warnings
    assert 'supersecret123' not in context.ocr_text
    assert 0 <= context.ocr_confidence <= 1
