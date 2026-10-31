"""Multilingual routing and human approval tests. Gemini is stubbed, not called."""
import io
import json

import pytest
from docx import Document
from fastapi.testclient import TestClient

import app as review_app
from translation_service import LANGUAGES, translation_needs_review


def test_scheduled_language_catalog_and_page():
    assert len(LANGUAGES) == 23
    assert LANGUAGES["en"] == "English"
    assert LANGUAGES["kn"] == "Kannada"
    assert LANGUAGES["pa"] == "Punjabi"
    client = TestClient(review_app.app)
    catalog = client.get("/translation/languages")
    assert catalog.status_code == 200
    assert len(catalog.json()["languages"]) == 23
    page = client.get("/")
    assert page.status_code == 200
    assert 'id="translationSourceLanguage"' in page.text
    assert 'id="translationTargetLanguage"' in page.text
    assert 'id="swapTranslationLanguages"' in page.text
    assert "Proofreading" in page.text


@pytest.mark.parametrize("source,target", [("kn", "hi"), ("hi", "kn"), ("te", "kn"),
                                            ("pa", "en"), ("en", "hi"), ("ta", "ml"),
                                            ("as", "or"), ("sat", "mni")])
def test_translation_routes_selected_languages_and_exports(monkeypatch, source, target):
    calls = []

    def fake_gemini(model, payload, system_prompt):
        data = json.loads(payload)
        calls.append(data)
        if "passages" in data:
            assert data["source_language"] == LANGUAGES[source]
            assert data["target_language"] == LANGUAGES[target]
            return json.dumps({"items": [
                {"id": passage["id"], "translated": "Translated sample for review", "flags": []}
                for passage in data["passages"]
            ]})
        assert data["source_language"] == LANGUAGES[source]
        assert data["target_language"] == LANGUAGES[target]
        return json.dumps({"translated": "Revised by reviewer", "flags": []})

    monkeypatch.setattr(review_app, "gemini_generate", fake_gemini)
    client = TestClient(review_app.app)
    data = {"text": "Sample text 2026", "source_language": source, "target_language": target}
    generated = client.post("/translation/translate", data=data)
    assert generated.status_code == 200, generated.text
    body = generated.json()
    assert body["source_language"] == source
    assert body["target_language"] == target
    assert body["items"][0]["reviewed"] is False
    revised = client.post("/translation/revise", data={
        "original": "Sample text 2026",
        "translated": "Translated sample for review",
        "feedback": "Check terminology",
        "revision_round": 1,
        "source_language": source,
        "target_language": target,
    })
    assert revised.status_code == 200, revised.text
    assert revised.json()["reviewed"] is False
    items = body["items"]
    items[0]["translated"] = revised.json()["translated"]
    items[0]["reviewed"] = True
    export = client.post("/translation/download", data={
        "payload": json.dumps(items),
        "stage": "final",
        "filename": "source.txt",
        "target_language": target,
    })
    assert export.status_code == 200
    assert f"_{LANGUAGES[target]}_final.docx" in export.headers["content-disposition"]
    doc = Document(io.BytesIO(export.content))
    assert doc.paragraphs[0].text == "Revised by reviewer"
    assert len(calls) == 2


def test_translation_rejects_unknown_or_identical_language_pairs():
    client = TestClient(review_app.app)
    for source, target in [("kn", "kn"), ("invalid", "hi"), ("en", "invalid")]:
        result = client.post("/translation/translate", data={
            "text": "Hello", "source_language": source, "target_language": target
        })
        assert result.status_code == 400


def test_script_review_for_different_language_pairs():
    assert translation_needs_review("Hello", "नमस्ते", "hi") == []
    assert translation_needs_review("ನಮಸ್ಕಾರ", "नमस्ते", "hi") == []
    assert translation_needs_review("नमस्ते", "ನಮಸ್ಕಾರ", "kn") == []
    assert translation_needs_review("Hello", "Hello", "hi")
    assert translation_needs_review("नमस्ते", "", "en")
    assert translation_needs_review("नमस्ते", "हिन्दी भाषा", "te")
