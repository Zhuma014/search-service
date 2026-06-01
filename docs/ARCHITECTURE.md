# Search Service — Architecture Reference

## What This Service Does

FastAPI microservice: lexical + semantic document search, RAG Q&A, and document sync.
External dependencies: **Elasticsearch** (search index), **PostgreSQL** (metadata/auth), **MinIO** (file storage), **Google Gemini** (LLM).

---

## Directory Map

```
search-service/
├── main.py                        # App entry, lifespan startup/shutdown, health check, router registration
├── config.py                      # All env vars via Pydantic Settings (single `settings` instance)
├── app/
│   ├── middleware/
│   │   └── tenant.py              # TenantMiddleware: validates X-Company-ID header + decodes JWT
│   ├── db/
│   │   └── postgres_client.py     # Async SQLAlchemy engine singleton (postgres_client instance)
│   ├── storage/
│   │   └── minio_client.py        # MinIO singleton (minio_client instance)
│   ├── elasticsearch/
│   │   ├── client.py              # AsyncES client singleton (ESClient) + get_index_name()
│   │   └── indexes.py             # ensure_index(): creates index with russian_custom analyzer + dense_vector mapping
│   ├── extractor/
│   │   └── parser.py              # extract_text(filename, bytes) → dispatches to PDF/DOCX/XLSX/HTML/TXT parsers
│   ├── indexer/
│   │   └── core.py                # index_document_content(): parse → chunk → embed → index to ES
│   ├── services/
│   │   ├── embeddings.py          # get_embeddings(texts), get_query_embedding(text) — local SentenceTransformer
│   │   └── sync_service.py        # sync_documents(company_id, document_id): PG → MinIO → ES pipeline
│   └── routers/
│       ├── search.py              # GET  /ai/api/search
│       ├── ask.py                 # POST /ai/api/ask
│       ├── documents.py           # GET/DELETE /ai/api/documents
│       ├── upload.py              # POST /ai/api/upload
│       ├── generate.py            # POST /ai/api/generate
│       └── knowledge.py           # POST /ai/api/knowledge
```

---

## Key Singletons and Where They Live

| Object | File | How to get it |
|---|---|---|
| `settings` | `config.py` | `from config import settings` |
| `ESClient` | `elasticsearch/client.py` | `ESClient.get_client()` → `AsyncElasticsearch` |
| `postgres_client` | `db/postgres_client.py` | `postgres_client.get_session_factory()` → `async_sessionmaker` |
| `minio_client` | `storage/minio_client.py` | `minio_client.get_client()` → `Minio` (sync) |
| `chat_memory` | `routers/ask.py` | module-level dict — **in-memory only, lost on restart** |
| `is_syncing` | `routers/upload.py` | module-level bool — global sync lock |

---

## Multi-Tenancy

- Each company gets its own ES index: `{company_id}_documents` (via `get_index_name()` in `client.py`)
- `TenantMiddleware` extracts `company_id` from `X-Company-ID` header → `request.state.company_id`
- JWT decoded WITHOUT signature verification → `request.state.user_info`
- Skipped paths: `/health`, `/docs`, `/openapi.json`

---

## Database Schema (expected in PG)

```sql
users              (id, kclock_id, ...)
document           (id, uuid, identifier, number, status, company_id, created_by, created_at)
document_translation (document_id, title, filename, file_path)
task               (document_id, assigned_to, status, action_required, completed_at)
```

---

## ES Index Mapping (per-company)

```
Index name: {company_id}_documents
Analyzer:   russian_custom (snowball stemmer + stopwords)

Fields:
  document_id  keyword        ← primary filter key
  chunk_id     keyword        ← unique chunk ID ({doc_id}_{i})
  uuid         keyword
  number       text + keyword
  status       keyword
  author       keyword
  filename     text
  title        text (russian_custom)
  content      text (russian_custom)
  created_at   date
  embedding    dense_vector(384, cosine)
```

---

## Data Flows

### Sync: PG → MinIO → ES
```
POST /upload
  └── sync_service.sync_documents(company_id, document_id)
        ├── PG: SELECT from document JOIN document_translation
        ├── MinIO: get_best_file(file_path) — priority: PDF > DOCX > XLSX > other
        └── indexer.index_document_content()
              ├── ensure_index(company_id)        ← creates ES index if missing
              ├── parser.extract_text()            ← PDF/DOCX/XLSX/HTML/TXT
              ├── chunk_text(size=1000, overlap=200)
              ├── embeddings.get_embeddings(chunks) ← local, intfloat/multilingual-e5-small
              └── ES: client.index() per chunk     ← individual calls, no bulk
```

### Search: Lexical
```
GET /search?q=...
  ├── PG Query 1: users WHERE kclock_id → user_db_id
  ├── PG Query 1b: UNION ALL (document.created_by + task.assigned_to) → allowed_doc_ids
  ├── ES Query 2: multi_match + filter(document_id IN allowed) + collapse(document_id) + cardinality agg
  └── PG Query 3: document JOIN document_translation JOIN task WHERE id = ANY(result_doc_ids)
```

### RAG: Ask
```
POST /ask
  ├── embeddings.get_query_embedding(question)   ← local
  ├── ES: kNN(field=embedding, filter=document_id) k=5, num_candidates=50
  ├── Build prompt: history + context chunks + question
  └── Gemini: generate_content_async(prompt)
```

---

## Config Variables (config.py)

| Var | Default | Used in |
|---|---|---|
| `ES_URL` | `http://localhost:9200` | `elasticsearch/client.py` |
| `GEMINI_API_KEY` | required | `ask.py`, `generate.py` |
| `GEMINI_MODEL` | `gemini-2.5-flash` | `ask.py`, `generate.py` |
| `DATABASE_URL` | required | `db/postgres_client.py` |
| `SYNC_LIMIT` | `20` | `sync_service.py` |
| `MINIO_ENDPOINT` | required | `storage/minio_client.py` |
| `MINIO_ACCESS_KEY` | required | `storage/minio_client.py` |
| `MINIO_SECRET_KEY` | required | `storage/minio_client.py` |
| `MINIO_BUCKET` | `abs-sed-dev` | `sync_service.py` |
| `MINIO_SECURE` | `True` | `storage/minio_client.py` |
| `SERVICE_PORT` | `8000` | `docker-compose.yml` |
| `LOG_LEVEL` | `info` | `main.py` |

---

## Where to Make Common Changes

| Task | File(s) to edit |
|---|---|
| Add new search field | `elasticsearch/indexes.py` (mapping) + `indexer/core.py` (doc dict) + `routers/search.py` (response) |
| Change chunk size/overlap | `indexer/core.py:15` `chunk_text(chunk_size, overlap)` |
| Change embedding model | `services/embeddings.py` — change model name string |
| Add new file format support | `extractor/parser.py` — add `extract_xxx()` + update `extract_text()` dispatch |
| Change RAG prompt | `routers/ask.py:86-100` |
| Add new API endpoint | create `routers/xxx.py` + register in `main.py` |
| Change PG connection pool | `db/postgres_client.py:25-37` |
| Add new env var | `config.py` Settings class |
| Change n8n webhook URL | `routers/knowledge.py:11` EXTERNAL_URL (hardcoded — move to config) |
| Change document access control | `routers/search.py:56-78` (the UNION ALL query) |
| Change Gemini generation rules | `routers/generate.py` system prompt |
| Change sync file priority order | `services/sync_service.py:25-38` `get_best_file()` |
