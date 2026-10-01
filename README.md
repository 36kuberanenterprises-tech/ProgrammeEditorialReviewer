# Programme Editorial Reviewer

Web application for NGO, CSR and development sector editorial review using the OpenAI Responses API.

## Features

* Upload DOCX, PDF, TXT or MD files.
* Review language, repetition, factual caution and editorial consistency.
* Preserve supplied facts and figures.
* Flag unclear or unsupported statements for confirmation.
* Treat pre existing beneficiary skills correctly.
* Show deletions in red strikethrough and additions in blue.
* Download a marked editorial review DOCX and a clean revised DOCX.

## Environment variable

Set `OPENAI_API_KEY` on the server. Never hard code the API key in source code.

## Run locally

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

Default model is `gpt-6-luna`. For more demanding documents, choose `gpt-6-sol` in the interface.
