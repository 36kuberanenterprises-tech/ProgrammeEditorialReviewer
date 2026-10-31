"""Safe image and scanned PDF preparation for AI assisted text transcription.

This module only decodes and prepares pixels. The actual reading is performed
by the already configured Gemini service, then presented for human checking.
"""
from __future__ import annotations

import io
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps, ImageSequence, UnidentifiedImageError
from pypdf import PdfReader

try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
    try:
        from pillow_heif import register_avif_opener
        register_avif_opener()
    except (ImportError, AttributeError):
        pass
except ImportError:
    pass

Image.MAX_IMAGE_PIXELS = 35_000_000

IMAGE_SUFFIXES = frozenset({
    ".jpg", ".jpeg", ".jfif", ".png", ".webp", ".gif",
    ".bmp", ".tif", ".tiff", ".heic", ".heif", ".avif",
})
MAX_FILE_BYTES = 15 * 1024 * 1024
MAX_PAGES = 12


class SourceImageError(ValueError):
    pass


def is_image(filename: str) -> bool:
    return Path(filename).suffix.lower() in IMAGE_SUFFIXES


def is_scanned_pdf(filename: str, data: bytes) -> bool:
    if Path(filename).suffix.lower() != ".pdf":
        return False
    try:
        pages = PdfReader(io.BytesIO(data)).pages
        return any(not (page.extract_text() or "").strip() for page in pages)
    except Exception as exc:
        raise SourceImageError("The PDF cannot be read. Check that it is not damaged or password protected.") from exc


def _jpeg_for_vision(frame: Image.Image) -> bytes:
    try:
        if frame.width * frame.height > 35_000_000:
            raise SourceImageError("Image resolution is too large. Reduce it below 35 megapixels.")
        upright = ImageOps.exif_transpose(frame)
        upright.thumbnail((3000, 3000), Image.Resampling.LANCZOS)
        if upright.mode in {"RGBA", "LA"} or "transparency" in upright.info:
            rgba = upright.convert("RGBA")
            background = Image.new("RGB", rgba.size, (255, 255, 255))
            background.paste(rgba, mask=rgba.getchannel("A"))
            upright = background
        else:
            upright = upright.convert("RGB")
        out = io.BytesIO()
        upright.save(out, format="JPEG", quality=90, optimize=True)
        if out.tell() > 8 * 1024 * 1024:
            raise SourceImageError("Prepared image is too large for text extraction.")
        return out.getvalue()
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise SourceImageError("Image resolution is too large to process safely.") from exc


def prepare_image_pages(filename: str, data: bytes) -> list[dict[str, Any]]:
    if not is_image(filename):
        raise SourceImageError("Unsupported image format. Use JPG, PNG, WEBP, HEIC, AVIF, TIFF, BMP or GIF.")
    if not data or len(data) > MAX_FILE_BYTES:
        raise SourceImageError("Choose an image smaller than 15 MB.")
    try:
        with Image.open(io.BytesIO(data)) as picture:
            frames = getattr(picture, "n_frames", 1)
            if frames > MAX_PAGES:
                raise SourceImageError("Image contains more than 12 pages or frames. Split the file first.")
            pages = []
            for number in range(frames):
                picture.seek(number)
                prepared = _jpeg_for_vision(picture.copy())
                pages.append({
                    "number": number + 1,
                    "text": "",
                    "image": prepared,
                    "mime_type": "image/jpeg",
                })
            return pages
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
        if isinstance(exc, SourceImageError):
            raise
        raise SourceImageError("The image format could not be decoded or the file is damaged.") from exc


def prepare_scanned_pdf_pages(data: bytes) -> list[dict[str, Any]]:
    """Keep selectable text and rasterise only pages without a text layer."""
    if not data or len(data) > MAX_FILE_BYTES:
        raise SourceImageError("Choose a PDF smaller than 15 MB.")
    try:
        parsed_pages = PdfReader(io.BytesIO(data)).pages
        if len(parsed_pages) > MAX_PAGES:
            raise SourceImageError("Scanned PDF exceeds 12 pages. Split it into smaller files.")
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(data)
        results = []
        try:
            for number, page in enumerate(parsed_pages):
                text = (page.extract_text() or "").strip()
                if text:
                    results.append({"number": number + 1, "text": text, "image": None, "mime_type": None})
                    continue
                raster_page = pdf[number]
                try:
                    bitmap = raster_page.render(scale=2.0)
                    try:
                        bitmap_image = bitmap.to_pil()
                        prepared = _jpeg_for_vision(bitmap_image)
                    finally:
                        bitmap.close()
                finally:
                    raster_page.close()
                results.append({"number": number + 1, "text": "", "image": prepared, "mime_type": "image/jpeg"})
        finally:
            pdf.close()
        return results
    except SourceImageError:
        raise
    except Exception as exc:
        raise SourceImageError("Unable to read or render this scanned PDF. Check that it is not password protected.") from exc
