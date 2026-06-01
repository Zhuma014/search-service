# Bugs and Issues

Legend: ✅ Fixed | 🔴 Open

---

## CRITICAL — Data Correctness

### ✅ BUG-01: Duplicate chunks on every re-sync
**File:** `app/indexer/core.py:46-54` and `app/services/sync_service.py:102-116`
**Problem:** Both the "delete old chunks before re-index" block (in `core.py`) and the "skip if already indexed" check (in `sync_service.py`) are commented out. Every `/upload` call re-indexes every document, creating duplicate chunks. Running sync 5× = 5× the chunks per document. Search results and RAG context become polluted with duplicates.
**Fix:** Uncomment the `delete_by_query` in `index_document_content()` before the indexing loop. This is the cleaner fix.

```python
# core.py — uncomment this block (lines 46-54):
await client.delete_by_query(
    index=index_name,
    body={"query": {"term": {"document_id": doc_id}}},
    refresh=True
)
```

---

### 🔴 BUG-02: `documents` list endpoint reports wrong `total`
**File:** `app/routers/documents.py:66`
**Problem:** `response["hits"]["total"]["value"]` returns the total chunk count (e.g., 4200), not the unique document count. The collapse query deduplicates the results list, but the total field still reflects all chunks.
**Fix:** Add a cardinality aggregation on `document_id` (same as done in `search.py`):
```python
"aggs": {"unique_docs": {"cardinality": {"field": "document_id"}}}
# then: total = response["aggregations"]["unique_docs"]["value"]
```

---

### 🔴 BUG-03: `seen_doc_ids` dedup in search is dead code masking a real issue
**File:** `app/routers/search.py:186-196`
**Problem:** ES `collapse` already guarantees one hit per `document_id`. The `seen_doc_ids` set check will never trigger. More importantly, if collapse were ever misconfigured, this would silently drop results rather than exposing the issue.
**Fix:** Remove the `seen_doc_ids` block. If you need it as a safeguard, at least log a warning when it triggers.

---

### 🔴 BUG-04: Non-digit document IDs silently dropped in search Query 3
**File:** `app/routers/search.py:167`
**Problem:** `[int(d) for d in result_doc_ids if d.isdigit()]` — if any `document_id` stored in ES is a UUID or non-integer string (e.g., from a document indexed without a DB id), it is silently excluded. Those results return with empty metadata (no title, no status, etc.).
**Fix:** Handle the type conversion more carefully, or store document IDs consistently as integers in ES.

---

## CRITICAL — Security

### 🔴 BUG-05: JWT signature verification disabled
**File:** `app/middleware/tenant.py:39`
**Problem:** `jwt.decode(token, options={"verify_signature": False})` — any base64-encoded JWT payload is accepted, including expired, tampered, or self-signed tokens.
**Fix:** Either verify with the public key from your identity provider, or use an introspection endpoint. Minimum: verify expiration (`"verify_exp": True`).

---

### 🔴 BUG-06: No authorization on `/ask` endpoint
**File:** `app/routers/ask.py`
**Problem:** Any authenticated user can ask questions about any `document_id` by guessing or enumerating IDs. The kNN filter only checks `document_id` match, not whether the requester has access to that document.
**Fix:** Before the kNN search, validate that `body.document_id` is in the user's `allowed_doc_ids` (same UNION query used in `/search`).

---

### 🔴 BUG-07: Hardcoded internal IP in knowledge router
**File:** `app/routers/knowledge.py:11`
**Problem:** `EXTERNAL_URL = "http://10.121.252.247:5678/webhook/knowledge"` — IP address is hardcoded. Breaks on infrastructure changes, leaks topology in code.
**Fix:** Move to config: `N8N_WEBHOOK_URL: str = "http://..."` in `config.py`.

---

## PERFORMANCE

### ✅ BUG-08: ES indexing is unbatched — one HTTP call per chunk
**File:** `app/indexer/core.py:86-90`
**Problem:** Each chunk is indexed with a separate `await client.index()` call. A 100-page PDF generates ~400 chunks → 400 round trips to Elasticsearch per document.
**Fix:** Use `elasticsearch.helpers.async_bulk()`:
```python
from elasticsearch.helpers import async_bulk
actions = [{"_index": index_name, "_id": doc["chunk_id"], "_source": doc} for doc in docs]
await async_bulk(client, actions)
```

---

### ✅ BUG-09: `indices.refresh()` called after every document
**File:** `app/indexer/core.py:92`
**Problem:** `await client.indices.refresh(index=index_name)` forces an expensive Lucene segment merge after each document. During bulk sync of many documents this multiplies the overhead significantly.
**Fix:** Remove the per-document refresh. Let ES auto-refresh (every 1s by default). Only call refresh explicitly in tests or after the full sync completes.

---

### ✅ BUG-10: MinIO `list_objects` blocks the event loop
**File:** `app/services/sync_service.py:16-18`
**Problem:** `minio_client.get_client().list_objects(...)` is synchronous and called directly in an async function. This blocks the event loop for the duration of the MinIO network call.
**Fix:** Wrap in `run_in_threadpool`:
```python
from starlette.concurrency import run_in_threadpool
objects = await run_in_threadpool(lambda: list(client.list_objects(...)))
```
Same applies to `minio_client.download_file()` in `minio_client.py`.

---

### ✅ BUG-11: `is_syncing` flag is global, not per-company
**File:** `app/routers/upload.py:26`
**Problem:** A sync for company A blocks company B from syncing. In a multi-tenant setup this is incorrect.
**Fix:** Use a dict `is_syncing: dict[str, bool] = {}` keyed by company_id.

---

## RELIABILITY / DESIGN

### ✅ BUG-12: PostgreSQL connection not closed on shutdown
**File:** `main.py:84`
**Problem:** The lifespan `yield` block only calls `await ESClient.close()`. `postgres_client.close()` is never called, leaving the connection pool open on shutdown (graceful or not).
**Fix:** Add `await postgres_client.close()` after `await ESClient.close()` in the lifespan.

---

### 🔴 BUG-13: In-memory chat history lost on restart
**File:** `app/routers/ask.py:16`
**Problem:** `chat_memory = {}` lives in process memory. Any restart or redeploy wipes all session context.
**Note:** This may be acceptable for your use case, but document it explicitly.
**Fix (if needed):** Back with Redis: `await redis.setex(session_id, 3600, json.dumps(history))`.

---

### 🔴 BUG-14: `SYNC_LIMIT = 20` silently caps full sync
**File:** `config.py` (SYNC_LIMIT) + `app/services/sync_service.py:87`
**Problem:** Full company sync is capped at 20 documents per run. A company with 200 documents will never be fully synced. The limit was likely meant as a safety valve but is too low.
**Fix:** Either increase the default, or implement pagination in `sync_documents()` to loop until all documents are synced.

---

### 🔴 BUG-15: `knowledge.py` uses synchronous `requests` library
**File:** `app/routers/knowledge.py:4`
**Problem:** Uses the blocking `requests` library via `run_in_threadpool`. This works but wastes a thread per request and adds latency. The project already has an async HTTP client available (or httpx should be added).
**Fix:** Replace with `httpx.AsyncClient`:
```python
import httpx
async with httpx.AsyncClient() as client:
    response = await client.post(EXTERNAL_URL, json=payload, headers=headers, timeout=60)
```

---

## DEAD CODE / CLEANUP

### NOTE-01: Commented-out deduplication in `sync_service.py`
**File:** `app/services/sync_service.py:102-116`
The skip-if-already-indexed check is commented out. Related to BUG-01 — leaving this unaddressed means syncing is always a full re-index.

### NOTE-02: Commented-out scheduler in `main.py`
**File:** `main.py:63-82`
Daily sync scheduler using APScheduler is fully commented out. If periodic sync is needed, it needs to be re-enabled and the hardcoded `company_id="1"` updated.

### NOTE-03: Commented-out old-chunk cleanup in `core.py`
**File:** `app/indexer/core.py:46-54`
See BUG-01. This code should be uncommented (not deleted).
