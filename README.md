# Search Service

FastAPI microservice for lexical/semantic search and RAG using Elasticsearch and Google Gemini.

## 🚀 Quick Start

### 1. Configure Environment
Create a `.env` file:
```env
GEMINI_API_KEY=your_key
ES_URL=http://localhost:9200
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/db
MINIO_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_BUCKET=documents
```

### 2. Run with Docker
```bash
docker-compose up -d
```

Service available at: `http://localhost:8000`  
API Docs: `http://localhost:8000/docs`

## 🛠 Features
- **Search**: Lexical and semantic (vector) search via Elasticsearch.
- **RAG**: Document-based Q&A using Google Gemini.
- **Files**: Support for PDF, DOCX, XLSX, and Web content.
- **Storage**: PostgreSQL (metadata) + MinIO (objects).
- **Multi-tenancy**: Isolated data per tenant via middleware.

## 📂 Structure
- `app/routers/`: API endpoints (search, ask, upload).
- `app/services/`: Core logic and LLM integration.
- `app/extractor/`: File parsing logic.
- `app/elasticsearch/`: ES indexing and search clients.
