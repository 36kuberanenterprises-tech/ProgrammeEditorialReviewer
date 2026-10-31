"""Image OCR ingestion regression tests. No external Gemini calls are made."""
import io
import json

import pytest
from PIL import Image
from docx import Document
from fastapi.testclient import TestClient

import app as editor
from image_reader import SourceImageError, is_scanned_pdf, prepare_image_pages, prepare_scanned_pdf_pages


def picture_bytes(fmt="PNG", frames=1):
    image = Image.new("RGB", (450, 250), "white")
    out = io.BytesIO()
    if frames > 1:
        image.save(out, format="TIFF", save_all=True, append_images=[
            Image.new("RGB", (450, 250), "white") for _ in range(frames - 1)
        ])
    else:
        image.save(out, format=fmt)
    return out.getvalue()


def fake_gemini(model, payload, system_prompt, image_parts=None):
    if image_parts:
        assert image_parts[0]["inline_data"]["mime_type"] == "image/jpeg"
        assert image_parts[0]["inline_data"]["data"]
        return json.dumps({"text": "रिपोर्ट 2026", "warnings": []}, ensure_ascii=False)
    request = json.loads(payload)
    if "passages" in request:
        return json.dumps({"items": [
            {"id": p["id"], "translated": "ವರದಿ 2026", "flags": []}
            for p in request["passages"]
        ]}, ensure_ascii=False)
    if "target_paragraphs" in request:
        return json.dumps({"items": [
            {"id": p["id"], "revised": "रिपोर्ट 2026", "reason": "Checked", "flags": []}
            for p in request["target_paragraphs"]
        ]}, ensure_ascii=False)
    raise AssertionError("Unexpected Gemini request")


@pytest.mark.parametrize("fmt,ext", [("PNG", ".png"), ("JPEG", ".jpg"), ("WEBP", ".webp"), ("BMP", ".bmp"), ("GIF", ".gif"), ("TIFF", ".tiff")])
def test_supported_image_formats(fmt, ext):
    pages = prepare_image_pages("scanned" + ext, picture_bytes(fmt))
    assert len(pages) == 1
    assert pages[0]["mime_type"] == "image/jpeg"
    assert len(pages[0]["image"]) > 100


def test_multiframe_tiff():
    pages = prepare_image_pages("scans.tiff", picture_bytes(frames=2))
    assert len(pages) == 2
    assert pages[0]["number"] == 1
    assert pages[1]["number"] == 2


def test_scanned_pdf_rendering():
    data = picture_bytes("PDF")
    assert is_scanned_pdf("scan.pdf", data)
    pages = prepare_scanned_pdf_pages(data)
    assert len(pages) == 1
    assert pages[0]["image"]


def test_rejects_corrupt_image():
    with pytest.raises(SourceImageError):
        prepare_image_pages("damaged.png", b"not an image")


def test_user_can_extract_readable_text_then_correct(monkeypatch):
    monkeypatch.setattr(editor, "gemini_generate", fake_gemini)
    client = TestClient(editor.app)
    image = picture_bytes()
    response = client.post("/extract/image", files={"file": ("photo.png", image, "image/png")})
    assert response.status_code == 200, response.text
    assert response.json()["text"] == "रिपोर्ट 2026"
    assert response.json()["warnings"]


def test_image_can_be_translated_and_exported(monkeypatch):
    monkeypatch.setattr(editor, "gemini_generate", fake_gemini)
    client = TestClient(editor.app)
    image = picture_bytes()
    response = client.post("/translation/translate",
        files={"file": ("photo.png", image, "image/png")},
        data={"source_language": "hi", "target_language": "kn"})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["items"][0]["original"] == "रिपोर्ट 2026"
    assert data["items"][0]["translated"] == "ವರದಿ 2026"
    assert data["items"][0]["reviewed"] is False
    assert data["items"][0]["flags"]
    data["items"][0]["reviewed"] = True
    exported = client.post("/translation/download", data={
        "payload": json.dumps(data["items"], ensure_ascii=False),
        "filename": "photo.png", "stage": "final", "target_language": "kn",
    })
    assert exported.status_code == 200, exported.text
    final = Document(io.BytesIO(exported.content))
    assert final.paragraphs[0].text == "ವರದಿ 2026"


def test_scanned_pdf_direct_translation(monkeypatch):
    monkeypatch.setattr(editor, "gemini_generate", fake_gemini)
    client = TestClient(editor.app)
    response = client.post("/translation/translate",
        files={"file": ("scan.pdf", picture_bytes("PDF"), "application/pdf")},
        data={"source_language": "hi", "target_language": "kn"})
    assert response.status_code == 200, response.text
    assert response.json()["items"][0]["original"] == "रिपोर्ट 2026"


def test_editor_accepts_image_and_reviews_text(monkeypatch):
    monkeypatch.setattr(editor, "gemini_generate", fake_gemini)
    result = TestClient(editor.app).post("/review",
        files={"file": ("photo.png", picture_bytes(), "image/png")})
    assert result.status_code == 200, result.text
    assert result.json()["review_type"] == "pages"
    assert result.json()["items"][0]["original"] == "रिपोर्ट 2026"


def test_quotation_api_removed_and_interface_task_focused():
    client = TestClient(editor.app)
    assert client.post("/translation/estimate", data={"text": "Hello"}).status_code == 404
    result = client.get("/")
    assert result.status_code == 200
    assert 'id="translationRate"' not in result.text
    assert 'id="translationQuotation"' not in result.text
    assert 'id="translationReadImage"' in result.text
    assert 'id="readEditorImage"' in result.text


def test_photo_ocr_respects_access_gate(monkeypatch):
    monkeypatch.setenv("EDITOR_ACCESS_CODE", "test-secret")
    result = TestClient(editor.app).post("/extract/image",
        files={"file": ("photo.png", picture_bytes(), "image/png")})
    assert result.status_code == 401
