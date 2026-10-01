import io
import os
import re
import json
import difflib
from pathlib import Path
from typing import List, Dict, Any

import httpx
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request
from docx import Document
from docx.shared import RGBColor
from pypdf import PdfReader

BASE_DIR = Path(__file__).resolve().parent
app = FastAPI(title="Programme Editorial Reviewer")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

SYSTEM_PROMPT = r"""
You are a senior Indian NGO, CSR and development sector editor.
Your task is not basic grammar correction. Review the supplied programme text as an institutional editor.

Rules:
1. Preserve every verified fact, figure, name, location, date, income figure, funding amount and programme term exactly as supplied.
2. Never invent achievements, referrals, customer growth, confidence, demand, family support, impact, partnerships or outcomes.
3. If a claim needs verification or the source is unclear, do not guess. Flag it for confirmation.
4. Remove repetition and duplicate meaning.
5. Rebuild awkward sentences naturally instead of replacing words one by one.
6. Use professional, natural Indian English suitable for CSR reports, coffee table books, annual reports and donor publications.
7. Avoid exaggerated, promotional, dramatic or template style conclusions.
8. For beneficiary stories, preserve the actual sequence: previous situation, reason for joining, training or support, what happened afterwards, present livelihood or enterprise situation and practical change, only when supported by the source.
9. If a beneficiary already had a skill, say the programme strengthened, improved or commercialised it. Do not claim the programme created the skill.
10. Maintain consistent terminology, headings, abbreviations, trade names, programme names and location presentation.
11. Identify unsupported causal claims and mark them for confirmation.
12. Do not use hyphens, en dashes or em dashes in newly written prose. Rewrite sentences to avoid them.
13. Keep the revised paragraph close to the source in meaning and length unless repetition requires shortening.
14. Do not silently correct factual conflicts. Flag them.
15. Do not add new facts from general knowledge. Work only from the supplied text.

Return ONLY valid JSON in this exact shape:
{
  "items": [
    {
      "id": 1,
      "revised": "revised paragraph",
      "reason": "short explanation of the main editorial change",
      "flags": ["Please confirm ..."]
    }
  ]
}
The id must match the paragraph id supplied by the user.
"""

ALLOWED_MODELS = {
    "gemini-3.1-flash-lite": "Gemini 3.1 Flash Lite",
    "gemini-3.8-flash": "Gemini 3.8 Flash",
}


def get_gemini_key() -> str:
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        raise HTTPException(
            status_code=500,
            detail="GEMINI_API_KEY is not configured on the server. Create a free Gemini API key in Google AI Studio and add it to Render Environment.",
        )
    return key


def extract_text(filename: str, data: bytes) -> List[str]:
    ext = Path(filename).suffix.lower()
    if ext == ".docx":
        doc = Document(io.BytesIO(data))
        return [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    if ext == ".pdf":
        reader = PdfReader(io.BytesIO(data))
        paras: List[str] = []
        for page in reader.pages:
            text = page.extract_text() or ""
            for block in re.split(r"\n\s*\n|\n(?=[A-Z0-9])", text):
                block = re.sub(r"\s+", " ", block).strip()
                if block:
                    paras.append(block)
        return paras
    if ext in {".txt", ".md"}:
        text = data.decode("utf-8", errors="ignore")
        return [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    raise HTTPException(status_code=400, detail="Supported files: DOCX, PDF, TXT and MD.")


def chunks(items: List[Dict[str, Any]], max_chars: int = 10000):
    batch, size = [], 0
    for item in items:
        s = len(item["text"])
        if batch and size + s > max_chars:
            yield batch
            batch, size = [], 0
        batch.append(item)
        size += s
    if batch:
        yield batch


def extract_json(text: str) -> Dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, flags=re.S)
        if not m:
            raise ValueError("Model did not return valid JSON")
        return json.loads(m.group(0))


def gemini_generate(model: str, payload: str) -> str:
    key = get_gemini_key()
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    body = {
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": payload}]}],
        "generationConfig": {
            "temperature": 0.2,
            "responseMimeType": "application/json",
            "maxOutputTokens": 32768,
        },
    }
    try:
        with httpx.Client(timeout=120.0) as client:
            response = client.post(
                url,
                headers={"x-goog-api-key": key, "Content-Type": "application/json"},
                json=body,
            )
    except httpx.HTTPError as exc:
        raise RuntimeError(f"Could not reach Gemini API: {exc}") from exc

    if response.status_code >= 400:
        try:
            err = response.json().get("error", {})
            message = err.get("message") or response.text
        except Exception:
            message = response.text
        if response.status_code == 429:
            raise RuntimeError("Gemini free tier rate limit reached. Please wait and try again later.")
        if response.status_code in {401, 403}:
            raise RuntimeError("Gemini API key is invalid or does not have access to this model.")
        raise RuntimeError(f"Gemini API error {response.status_code}: {message}")

    data = response.json()
    candidates = data.get("candidates") or []
    if not candidates:
        feedback = data.get("promptFeedback") or {}
        raise RuntimeError(f"Gemini returned no editorial response. {feedback}")
    parts = candidates[0].get("content", {}).get("parts", [])
    text = "".join(str(part.get("text", "")) for part in parts if part.get("text"))
    if not text.strip():
        raise RuntimeError("Gemini returned an empty editorial response.")
    return text


def review_paragraphs(paragraphs: List[str], model: str) -> List[Dict[str, Any]]:
    source_items = [{"id": i + 1, "text": p} for i, p in enumerate(paragraphs)]
    reviewed: Dict[int, Dict[str, Any]] = {}

    for batch in chunks(source_items):
        payload = json.dumps({"paragraphs": batch}, ensure_ascii=False)
        text = gemini_generate(model, payload)
        data = extract_json(text)
        for item in data.get("items", []):
            try:
                idx = int(item["id"])
            except Exception:
                continue
            if idx < 1 or idx > len(paragraphs):
                continue
            flags = item.get("flags", []) or []
            if not isinstance(flags, list):
                flags = [str(flags)]
            reviewed[idx] = {
                "id": idx,
                "original": paragraphs[idx - 1],
                "revised": str(item.get("revised", paragraphs[idx - 1])).strip(),
                "reason": str(item.get("reason", "")).strip(),
                "flags": [str(flag) for flag in flags],
            }

    result = []
    for i, original in enumerate(paragraphs, start=1):
        result.append(reviewed.get(i, {
            "id": i,
            "original": original,
            "revised": original,
            "reason": "No change returned by the model.",
            "flags": ["Please review manually because no model revision was returned."],
        }))
    return result


def add_diff_paragraph(doc: Document, original: str, revised: str):
    p = doc.add_paragraph()
    sm = difflib.SequenceMatcher(None, original.split(), revised.split())
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            r = p.add_run(" ".join(original.split()[i1:i2]) + " ")
            r.font.color.rgb = RGBColor(0, 0, 0)
        elif tag in {"delete", "replace"}:
            deleted = " ".join(original.split()[i1:i2])
            if deleted:
                r = p.add_run(deleted + " ")
                r.font.color.rgb = RGBColor(192, 0, 0)
                r.font.strike = True
            if tag == "replace":
                added = " ".join(revised.split()[j1:j2])
                if added:
                    r = p.add_run(added + " ")
                    r.font.color.rgb = RGBColor(0, 102, 204)
        elif tag == "insert":
            added = " ".join(revised.split()[j1:j2])
            if added:
                r = p.add_run(added + " ")
                r.font.color.rgb = RGBColor(0, 102, 204)
    return p


def build_review_doc(results: List[Dict[str, Any]], title: str) -> bytes:
    doc = Document()
    doc.add_heading("Editorial Review", level=1)
    doc.add_paragraph(title)
    legend = doc.add_paragraph()
    r = legend.add_run("Red strikethrough")
    r.font.color.rgb = RGBColor(192, 0, 0)
    r.font.strike = True
    legend.add_run(" means deletion. ")
    r = legend.add_run("Blue text")
    r.font.color.rgb = RGBColor(0, 102, 204)
    legend.add_run(" means addition or replacement.")

    for item in results:
        doc.add_heading(f"Paragraph {item['id']}", level=2)
        add_diff_paragraph(doc, item["original"], item["revised"])
        if item["reason"]:
            p = doc.add_paragraph()
            p.add_run("Editorial note: ").bold = True
            p.add_run(item["reason"])
        for flag in item["flags"]:
            p = doc.add_paragraph()
            rr = p.add_run("Please confirm: ")
            rr.bold = True
            rr.font.color.rgb = RGBColor(192, 0, 0)
            p.add_run(str(flag))

    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


def build_clean_doc(results: List[Dict[str, Any]], title: str) -> bytes:
    doc = Document()
    doc.add_heading(title, level=1)
    for item in results:
        doc.add_paragraph(item["revised"])
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/health")
def health():
    return {
        "status": "ok",
        "provider": "gemini",
        "gemini_key_configured": bool(os.getenv("GEMINI_API_KEY")),
    }


@app.post("/review")
async def review(file: UploadFile = File(...), model: str = Form("gemini-3.1-flash-lite")):
    if model not in ALLOWED_MODELS:
        raise HTTPException(status_code=400, detail="Unsupported model selection.")
    data = await file.read()
    if len(data) > 15 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File is too large. Maximum size is 15 MB.")
    paragraphs = extract_text(file.filename or "document", data)
    if not paragraphs:
        raise HTTPException(status_code=400, detail="No readable text was found in the file.")
    try:
        results = review_paragraphs(paragraphs, model)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Editorial review could not be completed: {exc}") from exc
    return {"filename": file.filename, "count": len(results), "items": results, "provider": "Gemini free tier"}


@app.post("/download/reviewed")
async def download_reviewed(payload: str = Form(...), filename: str = Form("document.docx")):
    results = json.loads(payload)
    data = build_review_doc(results, filename)
    stem = Path(filename).stem
    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{stem}_editorial_review.docx"'},
    )


@app.post("/download/clean")
async def download_clean(payload: str = Form(...), filename: str = Form("document.docx")):
    results = json.loads(payload)
    data = build_clean_doc(results, f"{Path(filename).stem} Revised Copy")
    stem = Path(filename).stem
    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{stem}_clean_revised.docx"'},
    )
