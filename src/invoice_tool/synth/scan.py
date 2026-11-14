"""Make a rendered PDF look like a phone photo / office scan (seeded, deterministic)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np
import pypdfium2 as pdfium
from PIL import Image, ImageEnhance, ImageFilter

FIXED_DATE = datetime(2026, 1, 1).timetuple()  # Pillow expects a struct_time


def rasterize(pdf_path: Path, dpi: int) -> Image.Image:
    pdf = pdfium.PdfDocument(str(pdf_path))
    try:
        page = pdf[0]
        img = page.render(scale=dpi / 72).to_pil()
        page.close()
    finally:
        pdf.close()
    return img.convert("L")


def scanify(img: Image.Image, seed: int, strength: float = 1.0) -> Image.Image:
    rng = np.random.default_rng(seed)
    angle = float(rng.uniform(0.5, 1.7)) * (1 if rng.random() < 0.5 else -1) * strength
    img = img.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True, fillcolor=255)
    # slightly grey paper and uneven lighting
    arr = np.asarray(img, dtype=np.float32)
    w = arr.shape[1]
    gradient = np.linspace(0, 18 * strength, w, dtype=np.float32)[None, :]
    arr = arr * 0.9 + 14 - gradient
    arr += rng.normal(0, 9 * strength, size=arr.shape).astype(np.float32)
    img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), mode="L")
    img = img.filter(ImageFilter.GaussianBlur(radius=0.7 * strength))
    img = ImageEnhance.Contrast(img).enhance(0.88)
    return img


def save(img: Image.Image, path: Path, dpi: int) -> None:
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        img.save(path, "JPEG", quality=62, dpi=(dpi, dpi))
    elif suffix == ".png":
        img.save(path, "PNG", dpi=(dpi, dpi), optimize=True)
    elif suffix == ".pdf":
        # image-only PDF: no text layer, like a scanner's output
        img.save(
            path,
            "PDF",
            resolution=dpi,
            title="Synthetic scanned document",
            author="invoice-synth",
            creationDate=FIXED_DATE,
            modDate=FIXED_DATE,
        )
    else:
        raise ValueError(f"unsupported output type {suffix}")
