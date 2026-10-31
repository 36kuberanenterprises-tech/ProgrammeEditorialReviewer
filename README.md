# Programme Editorial Reviewer

Web application for NGO, CSR and development sector proofreading and Hindi to Gujarati translation.

## Existing proofreading

* Upload DOCX, PDF, TXT or MD files, or paste text.
* Review language, repetition, factual caution and editorial consistency.
* Preserve supplied facts and figures, and flag statements needing confirmation.
* Treat existing beneficiary skills accurately.
* Show deletions in red strikethrough and additions in blue.
* Download marked editorial review DOCX and clean revised DOCX.

## Hindi to Gujarati translation service

Choose the **Hindi to Gujarati translation** tab.

1. Upload a Hindi DOCX, PDF, TXT or MD document or paste Hindi text.
2. Count source words and prepare an indicative quotation. The rate is editable and defaults to INR 1.80 per Hindi source word. Numbers are counted; punctuation is not. Agree the counting method with the client before billing.
3. Generate an AI assisted Gujarati working draft using the configured Gemini API.
4. Compare original Hindi and editable Gujarati passages side by side.
5. Your Gujarati translator can edit and approve passages, and apply up to four feedback revisions per passage in the active browser session.
6. Download a working Word file. A final Word file is enabled after every passage has been marked as verified by the human translator.

### Document handling

* DOCX exports retain their original paragraphs, tables and styles where possible. Embedded images are kept in place, but complex inline formatting must be reviewed.
* PDF text is extracted into a new Word file. The original PDF layout and graphics are not reconstructed.
* Scanned image PDFs require text recognition before use.
* The service does not certify the accuracy of AI translations. A competent Hindi to Gujarati translator and proofreader must check all content before delivery.
* Revision history is not stored in a database. Refreshing the page loses the current review session.

### Privacy

The translated source text is transmitted to the configured Gemini API for processing. Check the client's confidentiality and data processing requirements before uploading restricted material. Do not store API keys in GitHub or the browser.

## Configuration

Set the environment variable `GEMINI_API_KEY` on the server. Do not hardcode secrets in source files.

## Local startup

```bash
pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8000
```

## Render deployment

Build command:

```text
pip install -r requirements.txt
```

Start command:

```text
uvicorn app:app --host 0.0.0.0 --port $PORT
```

The translation service uses the same Gemini credentials already configured for proofreading. Automated tests run in GitHub Actions.
