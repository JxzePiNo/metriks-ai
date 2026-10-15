# Metriks AI — Backend

Python + FastAPI API for the Metriks AI document management system.

## Requirements

- Python 3.12 or newer (`.python-version` pins 3.12)
- [uv](https://docs.astral.sh/uv/) for dependency management (`pip install uv` or see the uv docs)

Dependencies are declared in `pyproject.toml` and locked in `uv.lock`.

## Setup

```bash
cd backend
uv sync
```

Alternatively, use a virtual environment and pip (Python 3.12+):

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8000
```

`requirements.txt` includes runtime and development dependencies pinned from
`uv.lock`. Regenerate it after changing dependencies:

```bash
uv export --frozen --format requirements-txt --no-emit-project --output-file requirements.txt
```

## Run locally

```bash
uv run uvicorn app.main:app --reload --port 8000
```

| URL                                | Purpose                                      |
| ---------------------------------- | -------------------------------------------- |
| <http://localhost:8000/health>     | Liveness: the process is up                  |
| <http://localhost:8000/ready>      | Readiness: the app has started               |
| <http://localhost:8000/docs>       | Interactive OpenAPI documentation            |

With RAG disabled, `/ready` reports application readiness with empty dependency checks.
The optional RAG endpoints load their dependencies lazily; an unavailable dependency
returns a sanitized HTTP 503. `/health` remains a process liveness check.

## Configuration

Settings are read from environment variables, or from a local `.env` file in `backend/` (never commit it). See `app/core/config.py`.

| Variable    | Allowed values                                   | Default |
| ----------- | ------------------------------------------------ | ------- |
| `APP_ENV`   | `local`, `test`, `production`                    | `local` |
| `LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`  | `INFO`  |
| `CORS_ORIGINS` | Comma-separated browser origins (no `*`)      | empty (CORS disabled) |

Invalid values stop the application at startup. Logs are written to stdout as single-line JSON.

All errors are returned as `{"error": {"code": "...", "message": "..."}}`.

## Tests and linting

Tests need no AWS credentials, database or API keys.

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .   # use `uv run ruff format .` to apply
python -m compileall -q app tests
```

## Structure

```
app/
  main.py          application factory (create_app) and ASGI entry point
  api/health.py    /health and /ready routes
  core/config.py   settings
  core/logging.py  JSON logging
  core/errors.py   exception handlers
tests/
```

## Intelligent RAG pipeline

The optional RAG implementation lives in `app/rag/` and integrates with the existing
FastAPI application, CORS configuration, and error envelope. Set `RAG_ENABLED=true`
to enable authenticated access. Existing health endpoints work without installing
the ML libraries or configuring secrets.

1. Upload a PDF. PyMuPDF extracts page text and native tables as Markdown. Embedded
   images and scanned pages pass through local Tesseract OCR using PyMuPDF.
2. Presidio detects names, emails, employee IDs, phone numbers, payment identifiers,
   IP addresses, and selected national identifiers. Authorized curated aliases are
   matched before recognition. Replace detected values with opaque `PII_…` tokens.
3. Persist **only pseudonymized Markdown**, plus encrypted identity records in a
   separate private SQLite database. Original PDFs, filenames, extracted raw text,
   and user questions are not retained by the application. Multipart uploads may
   use temporary OS spool files during the request; secure the host/temp storage.
4. Classify the sanitized document locally as `financial`, `technical`, `mixed`, or
   `other` using an explainable keyword classifier. An uploader can override this
   label. A separate `confidentiality` label is `internal`, `confidential` (default),
   or `restricted`. Labels are metadata, **not substitutes for document ACLs**.
5. Chunk by page and model token budget, embed locally with
   `sentence-transformers/paraphrase-multilingual-mpnet-base-v2` (768 dimensions), and store sanitized
   chunks, vectors, labels, tenant, and explicit reader ACLs in Elasticsearch.
6. Pseudonymize each question **before** scope checking, embedding, or model calls.
   Run the NeMo company topic-control input rail. Rejected questions increment an
   atomic application-owned SQLite session counter. The third rejection locks the
   session; later requests return 423. Valid questions do not reset the counter.
   Provider failures do not count as rejected questions. New sessions start at zero;
   this is a conversation policy, not an account-wide abuse control.
7. Apply tenant, user, ready-document IDs, and optional classification filters to
   both Elasticsearch BM25 and approximate kNN retrieval. Fuse results using RRF
   (`k=60`), then rerank with `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1`.
8. Detect the query language locally (English/Italian), then generate structured
   claims in that language with the OpenAI Responses API (`store=False`), using
   only sanitized questions and retrieved passages. Validate cited source IDs and
   verbatim quotes. Discard unsupported citations/quotes. Return HTML-escaped answer
   text and `<mark>`-highlighted evidence, with page-level source references.
9. Restore tokens only when requested by a viewer with `pii:read`, and only for
   tokens present in the cited accessible passages. Markdown downloads always stay
   pseudonymized. Original source PDFs are not available for download.

BM25 is lexical retrieval. MPNet is a dense bi-encoder; it is not a cross-encoder.
The separate cross-encoder scores question/passage pairs after fusion. RRF runs in
the application, so this pipeline does not depend on Elasticsearch's licensed RRF
retriever feature. All neural embeddings and reranking run locally on CPU.

### Install and run RAG locally

From `metriks-ai/backend`, using Python 3.12:

```bash
uv sync --extra rag
uv run --extra rag python -m spacy download en_core_web_lg
uv run --extra rag python -m spacy download it_core_news_lg
# macOS: brew install tesseract tesseract-lang
# Debian/Ubuntu: apt-get install tesseract-ocr tesseract-ocr-eng tesseract-ocr-ita libgomp1
cp ../.env.example .env
```

Fill in `.env` with a **new** OpenAI key, randomly generated bearer credentials,
and stable encryption/lookup keys. Never commit these values. A key shared in chat
should be revoked and replaced. Generate separate keys with:

```bash
uv run python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
uv run python -c 'import secrets; print(secrets.token_hex(32))'
uv run python -c 'import secrets; print(secrets.token_urlsafe(48))'
```

Use those outputs for `IDENTITY_ENCRYPTION_KEY`, `IDENTITY_LOOKUP_KEY`, and the
credential key in `RAG_API_TOKENS`, respectively. Configure a server-owned mapping:

```dotenv
RAG_ENABLED=true
OPENAI_API_KEY=YOUR_NEW_KEY
IDENTITY_ENCRYPTION_KEY=YOUR_FERNET_KEY
IDENTITY_LOOKUP_KEY=YOUR_SEPARATE_RANDOM_KEY
RAG_API_TOKENS='{"YOUR_RANDOM_BEARER_TOKEN":{"tenant_id":"customer-1","user_id":"alice","scopes":["documents:read","documents:write","chat:write","identity:write","pii:read"]}}'
```

Start Elasticsearch and then the API:

```bash
# From the metriks-ai root (requires Docker)
docker compose -f docker-compose.yml -f docker-compose.rag.yml up -d elasticsearch
# From backend/
uv run --extra rag uvicorn app.main:app --reload --port 8000
```

First authenticated RAG access initializes Presidio, downloads public embedding/
reranker weights if not cached, connects to Elasticsearch, and creates its index.
Provision both spaCy models before startup. This can take time on first access.
Subsequent requests reuse initialized clients. Private data is not sent to model
download services. An OpenAI model must support Responses structured outputs;
`OPENAI_MODEL` defaults to `gpt-4.1-mini` and can be changed.

For a fully containerized stack, configure the root `.env`, then run from the root:

```bash
docker compose -f docker-compose.yml -f docker-compose.rag.yml up --build
```

The RAG override builds the optional libraries and both spaCy models, adds Elasticsearch,
and persists the private database, sanitized Markdown, and model cache in named
volumes. The base Compose stack continues to run with RAG disabled. The RAG image
is significantly larger due to local NLP models. Elasticsearch security is disabled
only for this loopback-bound local development service. Use authenticated TLS for
an external/production cluster. PostgreSQL remains available to the existing stack;
this POC uses SQLite for RAG metadata, identity lookup, and sessions.

For pip, `requirements.txt` is the locked base runtime/development export;
`requirements-rag.txt` includes the RAG libraries as well:

```bash
python -m pip install -r requirements-rag.txt
python -m spacy download en_core_web_lg
python -m spacy download it_core_news_lg
python -m uvicorn app.main:app --reload --port 8000
```

### English and Italian support

The supported application languages are **English (`en`) and Italian (`it`)**.
Documents, questions, and source passages can use either language, including mixed
documents. Query language is detected locally with Lingua before pseudonymization;
the original question is never sent to a language-detection service.

| Layer | Bilingual behavior |
| --- | --- |
| PDF/OCR | Native Unicode text and tables; scanned/embedded image text uses `OCR_LANGUAGE=eng+ita`. Install both Tesseract language packs. |
| PII | Both English and Italian Presidio/spaCy pipelines inspect every text, including mixed-language pages. Names, shared identifiers, Italian fiscal/VAT codes, identity cards, and passports are screened. |
| Classification | English and Italian financial/technical keywords; API label values remain `financial`, `technical`, `mixed`, `other`. |
| Search | Multilingual MPNet dense embeddings and multilingual mMARCO cross-encoder reranking. BM25 searches standard, English-stemmed, and Italian-stemmed fields; dense retrieval supplies cross-language matching without translating raw text. |
| Guardrails | The same topic policy applies to both languages. Refusals and lock messages follow the query language. |
| Answers | Generated claim text follows the query language even when evidence is in another language. Supporting quotations remain verbatim in their original language. |

The generator checks the language of each generated claim locally. If it detects
the wrong language, it retries once with an explicit correction. A second failure
returns a localized 503 rather than a knowingly wrong-language answer. Names,
financial abbreviations, numbers, and PII tokens can remain unchanged. Language
detection and NER remain probabilistic; evaluate real company terminology and
representative bilingual documents before production use.

No request change is needed for normal queries:

```json
{"session_id":"…","question":"Quali sono i ricavi dell'azienda?"}
```

This returns `"language":"it"` and Italian answer prose, including the Italian
insufficient-evidence response when no accessible source supports an answer.
`"What was company revenue?"` returns `"language":"en"` and English prose.
Each request is detected independently, so users can switch language in one session.
The three-attempt counter stays attached to the session across language changes.

For genuinely ambiguous queries such as `"API?"` or `"EBITDA?"`, use the optional
`"language":"it"`/`"language":"en"` hint. Otherwise the configured
`DEFAULT_QUERY_LANGUAGE` (default `en`) is the fallback. The hint selects the response
language; it does not disable either PII pipeline. Source fields and quotations are
not translated. Document metadata exposes `language` as `en`, `it`, `mixed`, or `und`
(undetermined); citation metadata reports the source page's detected language.

#### Upgrade from the original English-only index

1. Install the updated dependencies and **both** spaCy models using the commands
   above. Install the Italian Tesseract pack too, or rebuild the RAG Docker image.
2. Update existing `.env` files: copied environment files retain their old values.
   Set `OCR_LANGUAGE=eng+ita`,
   `EMBEDDING_MODEL=sentence-transformers/paraphrase-multilingual-mpnet-base-v2`,
   `RERANKER_MODEL=cross-encoder/mmarco-mMiniLMv2-L12-H384-v1`, and
   `ELASTICSEARCH_INDEX=metriks-chunks-multilingual-v2`.
3. Re-upload the source PDFs into the new index, preserving the desired reader ACLs
   and confidentiality labels. The app does not retain original PDFs, so obtain
   them from your source document repository. Re-upload also applies Italian PII
   screening to content that may have passed through the old English-only detector.
4. Verify retrieval and permissions, then retire superseded documents and the old
   Elasticsearch index according to your retention policy. Old indexes are never
   deleted automatically. Do not copy the old vectors into the new index.

The private database receives an additive language-column migration; old metadata,
encrypted identities, ACLs, and sessions are retained. Existing documents are marked
`und` until reingested. The new index records the multilingual retrieval schema and
model name. Reusing an incompatible index fails closed even when vector dimensions
match. Merely restarting the app does not regenerate old embeddings. Chunks respect
the configured encoder's actual context length (128 tokens for the default
multilingual MPNet model, with room reserved for special tokens).

### API contract

Every `/api/v1` request requires `Authorization: Bearer <credential>`. Tenant and
user identity come from the server-side credential mapping, never client-supplied
tenant headers. Scopes are explicit; there is no implicit administrative ACL bypass.
The upload owner is always a reader. Additional readers are user IDs in that tenant.
Use your authentication backend/BFF to supply credentials to a frontend; do not put
a privileged shared bearer token in a browser bundle or `NEXT_PUBLIC_*` variable.

| Method | Endpoint | Purpose / required scope |
| --- | --- | --- |
| POST | `/api/v1/identities` | Register verified aliases; `identity:write` |
| POST | `/api/v1/documents` | Upload multipart PDF; `documents:write` |
| GET | `/api/v1/documents` | List accessible documents; `documents:read` |
| GET | `/api/v1/documents/{id}` | Accessible metadata; `documents:read` |
| GET | `/api/v1/documents/{id}/markdown` | Sanitized source; `documents:read` |
| DELETE | `/api/v1/documents/{id}` | Owner-only removal; `documents:write` |
| POST | `/api/v1/sessions` | Create session; `chat:write` |
| GET | `/api/v1/sessions/{id}` | Inspect unlocked session; `chat:write` |
| POST | `/api/v1/chat` | Ask; `chat:write` and `documents:read` |

Interactive request schemas are at `/docs`; OpenAPI is at `/openapi.json`.
Examples below assume `TOKEN` holds your credential:

```bash
# Register an identity BEFORE indexing documents if its aliases are known.
curl http://localhost:8000/api/v1/identities \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"identifier":"EMP-1042","identifier_type":"employee_id","canonical_name":"Chandana Sree Mala","aliases":["Chandana","C. S. Mala"],"allowed_users":["analyst-1"]}'

curl http://localhost:8000/api/v1/documents \
  -H "Authorization: Bearer $TOKEN" \
  -F 'file=@./report.pdf;type=application/pdf' \
  -F 'allowed_users=["analyst-1"]' -F 'confidentiality=restricted'

curl -X POST http://localhost:8000/api/v1/sessions \
  -H "Authorization: Bearer $TOKEN"

curl http://localhost:8000/api/v1/chat \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"session_id":"SESSION_ID_FROM_RESPONSE","question":"What was revenue?","classifications":["financial","mixed"],"top_k":5,"restore_pii":false}'
```

Upload also accepts optional `classification` and an `identity_choices` JSON form
field. JSON string form fields are intentional: the request contains a binary PDF.
The original filename is ignored; generated document IDs are the source titles.
PDFs default to a 25 MiB application size limit and 300 pages; configure your HTTP
proxy body limit too, since multipart parsing precedes application size validation.

Successful chat responses contain:

```json
{
  "session_id": "…",
  "language": "en",
  "attempts": 0,
  "attempts_remaining": 3,
  "locked": false,
  "status": "answered",
  "answer": "Revenue was EUR 100. [S1]",
  "answer_html": "<p>Revenue was EUR 100. [S1]<br><mark>Revenue EUR 100</mark> [S1]</p>",
  "claims": [{"text":"Revenue was EUR 100.","source_ids":["S1"],"quotes":{"S1":"Revenue EUR 100"}}],
  "citations": [{"source_id":"S1","document_id":"…","title":"Document …","page":1,"classification":"financial","url":"/api/v1/documents/…/markdown","excerpt":"Revenue EUR 100"}]
}
```

Render `claims[].quotes` with a highlight component, or render the server-escaped
`answer_html`. Render `answer` and all source fields as text. List `citations` below
the answer, including page numbers, and fetch their URLs with the viewer's bearer
credential. Citation URLs return sanitized Markdown. Highlights denote verified
excerpts; paraphrased claims are not themselves verbatim source quotations.

Statuses are `answered`, `insufficient_evidence`, or `out_of_scope`. The third
out-of-scope response returns `locked:true`; subsequent requests to that session
return 423. Sessions expire after `SESSION_TTL_SECONDS` (default 24 hours).
403 means insufficient scope; inaccessible document/session IDs return 404; invalid
PDFs/OCR problems return 422; configuration/provider problems return 503.

### Identity ambiguity and private lookup

The two connected indexes are:

- An encrypted private identity vault (`private.sqlite3`): Fernet-encrypted canonical
  names and aliases, tenant-bound HMAC lookup keys, explicit readers, and document
  mention links. It is separate from Elasticsearch. Database indexes contain no
  plaintext names. Keys stay outside the database.
- A document index in Elasticsearch: only pseudonyms, sanitized passages/vectors,
  page/source metadata, labels, tenant, and reader IDs.

An identity curator explicitly asserts that aliases belong to an email/employee ID.
The system never uses name similarity to merge people. Without a curated mapping,
names receive document-scoped tokens. Email and employee ID recognizers can use
strong identifiers across documents. A name and nearby email are not automatically
assumed to identify the same person. Curate aliases before ingestion; changing the
identity inventory does not rewrite existing embeddings, so reingest affected docs.
Registering an existing strong identifier is idempotent, rather than silently changing
its name or permissions. There is no identity editing/merging API in this POC.

When multiple authorized people share an alias, the API responds with:

```json
{"error":{"code":"identity_ambiguous","message":"Multiple people match. Select a token and resend with identity_choices.","alias":"Chandana","candidates":[{"token":"PII_…"},{"token":"PII_…"}]}}
```

Show a selection prompt and resend the original question with
`"identity_choices":{"Chandana":"PII_SELECTED_TOKEN"}`. Canonical names appear in
candidates only for viewers with `pii:read`. Otherwise show the opaque candidate
tokens or involve an authorized identity curator. Unauthorized candidates are never
included. Ambiguous uploads use the same mechanism and must be resubmitted; no
partially indexed upload becomes searchable. A query about an unknown person gets
an ephemeral token rather than writing private question text into the identity vault.

### Guardrails, confidentiality, and POC limits

`app/rag/generation.py` defines a custom **NeMo Guardrails input rail** and a
company-topic classification action. The action uses OpenAI structured output for
the decision, with a fixed company financial/technical policy. It runs through
NeMo's Python `LLMRails.generate_async(..., options={"rails":["input"]})` API before
retrieval or answering. This is not the NVIDIA Topic Control NIM integration and
requires no separate NVIDIA API key or NIM deployment. An unavailable rail fails
closed with 503. Do not replace it with a frontend-only check.
The configured exact-message index handles NeMo's static internal messages without
downloading an unused dialogue embedding model; document retrieval still uses MPNet.
Changing the embedding model requires a new `ELASTICSEARCH_INDEX` and reingestion;
the index records its model name and dimension and rejects incompatible reuse.

PII detection and OCR are probabilistic. Review detector coverage with representative
documents before using real confidential data; company-specific secrets and employee
ID formats need custom recognizers/policies. The built-in employee ID recognizer
accepts `EMP`/`EID` followed by 3–12 digits. OCR extracts text from charts/images;
it does not understand chart geometry or provide visual reasoning. Images are not
persisted or embedded. Unsupported/encrypted PDFs and disabled/failed required OCR
are rejected. Classification is a POC heuristic, not an audited sensitivity detector.

The LLM receives sanitized company content, which can still be commercially
confidential even after personal identifiers are removed. `store=False` disables
Responses storage; it does not itself establish a zero-data-retention agreement.
Use organization-approved provider settings. Citation validation proves that excerpts
occur in sources; it does not prove semantic entailment of every generated claim.

SQLite transactions support a single-host POC with concurrent requests/processes
sharing one local volume. For multiple application hosts, migrate metadata/sessions
to PostgreSQL/Redis and add an ingestion job queue, quotas, and cleanup/retry jobs.
Uploads run synchronously. Failed uploads stay non-searchable, but sanitized orphan
chunks and encrypted mention records may require administrative cleanup. Deletion
tombstones a document before external-index cleanup, so an Elasticsearch outage
cannot make it retrievable. Local disk volumes/backups require access controls and
encryption; sanitized Markdown and document metadata are not encrypted by this app.
Key rotation requires a vault migration; losing keys makes old identity data unusable.
No source PDF rendering/highlighting or frontend screens are added by this backend PR.

### Verification and dependency exports

```bash
uv run --extra rag pytest
uv run ruff check .
uv run ruff format --check .
uv export --frozen --format requirements-txt --no-emit-project --output-file requirements.txt
uv export --frozen --extra rag --format requirements-txt --no-emit-project --output-file requirements-rag.txt
```

Tests use a temporary private database and fake provider/search clients. They verify
sanitization before provider access, tenant/document/session isolation, identity
ambiguity, authorized restoration, quote validation/escaping, atomic attempt limits,
failed-ingestion isolation, both Elasticsearch retrieval filters, and the API contract.
With RAG extras installed they also run real PyMuPDF extraction and the NeMo input
rail with a deterministic local action; no OpenAI requests are made. Full live
retrieval/answer quality testing additionally requires Elasticsearch, downloaded
MPNet/reranker weights, representative PDFs, and a configured OpenAI account.
The suite also exercises Presidio with a local spaCy NER fixture and the real OpenAI
SDK against a mock HTTP transport, including strict JSON-schema validation.

Implementation references: [PyMuPDF OCR](https://pymupdf.readthedocs.io/en/latest/recipes-ocr.html),
[Presidio](https://presidio.dataprivacystack.org/),
[Elasticsearch kNN filtering](https://www.elastic.co/docs/solutions/search/vector/knn),
[Sentence Transformers retrieve/rerank](https://sbert.net/examples/sentence_transformer/applications/retrieve_rerank/README.html),
[NeMo input-only rails](https://docs.nvidia.com/nemo/guardrails/run-guardrailed-inference/using-python-apis/generation-options),
and [OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs).
