# Programme Editorial Reviewer

A web application for NGO, CSR and development sector proofreading and multilingual translation, keeping user supplied names, figures and programme details intact.

## Proofreading tab

* Review pasted text, a full page or an uploaded DOCX, PDF, TXT, MD, image or scanned document.
* Correct language and readability while highlighting spelling, grammar and factual issues requiring confirmation.
* Display editorial changes with marked additions and deletions, and export marked or clean Word copies.
* For long passages, use a simplified comparison to keep mobile and desktop browsers responsive.
* The software is an editing assistant, not a substitute for verification of donor reports, evidence or beneficiary information.

## Translation tab

Choose from English and the 22 scheduled Indian languages using separate source and target selectors. Use Swap languages to reverse a pair. The selected pair must be different. The language list describes available choices, not a guarantee of linguistic quality.

1. Select the source and target languages.
2. Select a writing style: Natural and simple, School and learning materials, NGO and CSR reports, or Formal and official.
3. Optionally supply preferred terms, one per line: `source term = preferred target term`. There is a limit of 30 terms.
4. Paste source text or upload DOCX, PDF, TXT, MD, or a supported image. Choosing a file clears pasted source text, and typing text clears the selected file. Press Translate for a working draft. Images and scanned PDF pages are automatically transcribed before translation.
5. Use Read text from image or PDF to inspect and correct the transcription first when the source is a photograph, handwritten note, screenshot or scanned document. Then press Translate. Read and correct each target passage against the source. Four rounds of AI revision feedback are available per passage.
6. Tick approval only after a competent bilingual reviewer has checked the text. Download a working Word copy at any time or a final Word copy once all passages are marked reviewed.
7. Use Copy passage, Copy all or Download TXT for short text. Click Save review progress to download a local JSON file so editing can resume later. Keep it securely.
8. Open the JSON using Resume saved translation. If your source was DOCX, select the same original Word file again to preserve structure and pass the source file checksum check when exporting.

### Image and scanned document reading

* Accepts JPG, JPEG, JFIF, PNG, WEBP, GIF, BMP, TIFF, HEIC, HEIF and AVIF when the installed image decoder supports the file. No software can guarantee support for every proprietary or damaged format.
* Converts uploaded image frames into manageable images for Gemini vision to transcribe in the original source language. GIF and multipage TIFF frames are treated as separate pages, up to 12.
* Supports scanned PDFs, including pages without a text layer, by rendering those pages into images with PDFium. Existing selectable text from other pages is reused.
* Restricts source files to 15 MB and documents containing images to 12 pages or frames. Use a clear scan for accurate reading.
* Use Read image or scanned PDF text in Proofreading to read source text into an editable full page before review. The Translation tab also has Read text from image or PDF, which places the extracted text into the source editor.
* Users can also submit an image directly for translation or proofreading. When the extraction step is automatic, a bilingual reviewer must check the source against the original image before approving an output.
* Text is extracted and translated, but photos, drawings and the original scanned layout are not reproduced in exported Word files.

### Limitations and privacy

* Uploaded image pixels and document text may be sent to the configured Gemini API. Do not upload confidential documents without permission under the relevant data protection terms.
* Work is not saved to a server database. Save a local project before closing or refreshing the page. Saved JSON files contain the source and translated text, so protect these files.
* PDF extraction and image transcription create new Word text documents. Original image placement and complex PDF layout are not reconstructed. Some unclear handwriting or low resolution images may not be readable.
* Word paragraph and table structure is preserved where possible, but complex inline formatting and target fonts may need manual corrections. Urdu and other languages written right to left receive right to left paragraph direction in Word export.
* Translation quality is not automatically certified. Model performance may be weak for less common languages, alternate scripts and specialised terminology.
* Missing translations, suspicious script and differing numbers or amounts are flagged for human checking. These are warnings, not a full automated quality assessment.
* Changing source material or language pair starts a new translation. The app offers protection against accidentally discarding reviewed work. Writing style and terminology changes do not rewrite already generated passages.
* The online deployment and Gemini account must be configured separately; GitHub automated tests cannot guarantee live API translation quality.

## Configuration and local startup

Use a server environment variable named `GEMINI_API_KEY`, without putting API keys in GitHub or the browser.

For a privately used deployment, set `EDITOR_ACCESS_CODE` as an additional Render environment variable. If set, AI proofreading and translation requests require users to enter that code on the webpage. Do not commit it to the repository. Without the variable, the existing public access behaviour remains unchanged. This is a simple access gate rather than a full user management system.

```bash
pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8000
```

## Render deployment

Build command: `pip install -r requirements.txt`

Start command: `uvicorn app:app --host 0.0.0.0 --port $PORT`

Automated tests for document handling, image preparation, scanned PDFs, language routing, input validation and user experience run through GitHub Actions.
