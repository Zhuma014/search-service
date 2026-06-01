# API Endpoints Reference

Base prefix: `/ai/api`
Auth required on all endpoints (except `/health`): `Authorization: Bearer <jwt>` + `X-Company-ID: <id>`

---

## GET /health
No auth required.
```json
{
  "service": "search-service",
  "elasticsearch": {"status": "connected", "version": "8.13.0"},
  "postgresql": {"status": "connected"},
  "minio": {"status": "connected", "bucket": "abs-sed-dev", "endpoint": "..."}
}
```

---

## GET /ai/api/search
**File:** `routers/search.py`

Query params: `q` (required, min 1 char), `page` (default 1), `size` (default 10, max 100)

3-query pipeline:
1. PG: resolve `kclock_id` → `user_db_id`
2. PG: UNION ALL `document.created_by` + `task.assigned_to` → `allowed_doc_ids`
3. ES: `multi_match` on `title^3` + `content`, `fuzziness=AUTO`, `analyzer=russian_custom`, filter by `allowed_doc_ids`, `collapse` by `document_id`, `cardinality` agg for total
4. PG: fetch metadata for result doc IDs

```json
{
  "total": 42,
  "page": 1,
  "results": [{
    "document_id": "123",
    "title": "...",
    "filename": "doc.pdf",
    "author": "...",
    "identifier": "REF-001",
    "number": "2024/001",
    "doc_status": "APPROVED",
    "doc_created_at": "2024-01-15",
    "doc_completed_at": "2024-01-20",
    "highlight": {"content": ["...text with <mark>match</mark>..."]}
  }]
}
```

---

## POST /ai/api/ask
**File:** `routers/ask.py`

```json
// Request
{"document_id": "123", "question": "What is the total amount?", "session_id": "abc"}

// Response
{"document_id": "123", "session_id": "abc", "question": "...", "answer": "..."}
```

Flow: local embedding → ES kNN (k=5, num_candidates=50, filter by document_id) → Gemini prompt with chunks + chat history.
Chat history: in-memory `deque(maxlen=8)` keyed by `session_id`. Lost on restart.

**NOTE:** No authorization check — any user can query any document_id.

---

## GET /ai/api/documents
**File:** `routers/documents.py`
Requires `X-Company-ID` header.

Params: `page` (default 1), `size` (default 20, max 100)

ES `match_all` + `collapse(document_id)` + `sort(created_at desc)`.

```json
{"total": 50, "page": 1, "size": 20, "documents": [{"document_id": "123", "title": "...", "created_at": "..."}]}
```

**NOTE:** `total` is pre-collapse chunk count, not unique document count.

---

## DELETE /ai/api/documents/{document_id}
**File:** `routers/documents.py`
Requires `X-Company-ID` header.

ES `delete_by_query` where `document_id = {document_id}`.
Returns 404 if no chunks deleted.

```json
{"document_id": "123", "deleted_chunks": 42, "status": "deleted"}
```

---

## POST /ai/api/upload
**File:** `routers/upload.py`

Query param: `document_id` (optional)

- **With `document_id`:** synchronous sync, returns result immediately
- **Without `document_id`:** background sync (FastAPI `BackgroundTasks`), returns `{"status": "started"}`
- Global `is_syncing` flag prevents concurrent syncs (not per-company)
- SYNC_LIMIT (default 20) caps documents per sync run

```json
// Single doc
{"status": "success", "message": "Document 123 successfully synchronized.", "synced_count": 1, "errors": []}

// Background
{"status": "started", "message": "Full synchronization started in background..."}
```

---

## POST /ai/api/generate
**File:** `routers/generate.py`

```json
// Request
{"prompt": "Draft a formal letter requesting..."}

// Response
{"text": "Dear Sir/Madam..."}
```

Rejects non-document-related prompts with a Russian message.
Uses `settings.GEMINI_MODEL`.

---

## POST /ai/api/knowledge
**File:** `routers/knowledge.py`

Forwards to n8n webhook at hardcoded `http://10.121.252.247:5678/webhook/knowledge`.
Transforms: `question` → `chatInput`, `session_id` → `sessionId`.

```json
// Request
{"session_id": "abc", "question": "What is the policy?"}

// Response
{"answer": "..."}
```

Uses sync `requests` library via `run_in_threadpool`. Timeout: 60s.
