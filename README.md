# Programme Editorial Reviewer

Web application for NGO, CSR and development sector proofreading and translation between English and 22 scheduled Indian languages.

## Existing proofreading

* Upload DOCX, PDF, TXT or MD files, or paste text.
* Review language, repetition, factual caution and editorial consistency.
* Preserve supplied facts and figures, and flag statements needing confirmation.
* Treat existing beneficiary skills accurately.
* Show deletions in red strikethrough and additions in blue.
* Download marked editorial revie## Indian language translation service

Choose the independent **Translation** tab. Proofreading is retained in its own tab.

1. Select the source language and target language independently, or use Swap languages. Choose from English and all 22 scheduled Indian languages, including Hindi, Kannada, Telugu, Punjabi, Tamil, Gujarati, Bengali, Malayalam, Marathi and Odia. All distinct listed language pairs are selectable.
2. Paste text or upload DOCX, PDF, TXT or MD. The quotation calculator counts Unicode source words, and its starting INR 1.80 rate is editable. This is not a standard rate for all languages. Agree counting rules and price with the client.
3. Generate a Gemini assisted translation draft for the selected language pair. Check that source material matches the selected source language.
4. Compare source and target text side by side, edit individual passages, and apply up to four rounds of AI assisted reviewer feedback per passage.
5. A bilingual translator must verify each passage. The Word export is available as a working copy, and final export is enabled when each passage is marked approved.
6. Download the Word file named for the selected target language. Uploaded DOCX documents retain paragraph and table structure and styles where possible; inline font formatting must be reviewed. PDFs are extracted into new Word files without preserving the original page design.

### Quality, limitations and privacy

* Offering a language pair does not guarantee that the Gemini model will translate it accurately. Low resource languages, script variants, names and specialised terms may require substantial human translation and review. Source and target scripts are checked only for simple warnings, not quality certification.
* Scanned image PDFs need text recognition before upload; Word and PDF layout changes need manual inspection. Target fonts must be installed on the viewing device for correct display.
* Translation source text is transmitted to the configured Gemini API. Check client confidentiality and data processing requirements before uploading restricted content.
* Translation progress and revisions are not stored on a server. Refreshing the browser clears the current session. API keys must be kept only in server environment variables.

keys in GitHub or the browser.

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
