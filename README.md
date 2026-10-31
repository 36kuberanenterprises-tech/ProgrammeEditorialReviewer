# Programme Editorial Reviewer

A web application for NGO, CSR and development sector proofreading and multilingual translation, keeping user supplied names, figures and programme details intact.

## Proofreading tab

* Review pasted text, a full page or an uploaded DOCX, PDF, TXT or MD document.
* Correct language and readability while highlighting spelling, grammar and factual issues requiring confirmation.
* Display editorial changes with marked additions and deletions, and export marked or clean Word copies.
* For long passages, use a simplified comparison to keep mobile and desktop browsers responsive.
* The software is an editing assistant, not a substitute for verification of donor reports, evidence or beneficiary information.

## Translation tab

Choose from English and the 22 scheduled Indian languages using separate source and target selectors. Use Swap languages to reverse a pair. The selected pair must be different. The language list describes available choices, not a guarantee of linguistic quality.

1. Select the source and target languages.
2. Select a writing style: Natural and simple, School and learning materials, NGO and CSR reports, or Formal and official.
3. Optionally supply preferred terms, one per line: `source term = preferred target term`. There is a limit of 30 terms.
4. Paste text or upload a DOCX, PDF, TXT or MD file. Choosing a file clears pasted source text, and typing text clears the selected file so users do not unknowingly translate the wrong material.
5. Generate a working translation with the configured Gemini API. Check every passage against the source in the side by side reviewer and correct it directly. Four rounds of AI revision feedback are available per passage.
6. Tick approval only after a competent bilingual reviewer has checked the text. Download a working Word copy at any time or a final Word copy once all passages are marked reviewed.
7. Use Copy passage, Copy all or Download TXT for short text. Click Save review progress to download a local JSON file so editing can resume later. Keep it securely.
8. Open the JSON using Resume saved translation. If your source was DOCX, select the same original Word file again to preserve structure and pass the source file checksum check when exporting.

### Quotations

The word count includes Unicode letter and numeric sequences. The suggested starting rate of INR 1.80 per source word applies only to the original Hindi to Gujarati example. Enter an agreed rate for other language pairs; the calculation is indicative and GST is excluded. Verify the client counting method before submitting a financial quote.

### Limitations and privacy

* Translation text is sent to the configured Gemini API. Do not upload confidential documents without permission under the relevant data protection terms.
* Work is not saved to a server database. Save a local project before closing or refreshing the page. Saved JSON files contain the source and translated text, so protect these files.
* PDF extraction creates a new Word document. Complex PDF layout is not reconstructed. Scanned image PDFs require OCR before upload.
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

Automated tests for document handling, language routing, input validation and user experience run through GitHub Actions.
