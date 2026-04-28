# AGENTS.md — Omnidoc (Omnidoc)

## What Is This Project?

**Omnidoc** (also called Omnidoc during development) is a **Distributed Query Engine over Unstructured Data**.

The core idea: businesses drown in unstructured files — PDFs, CSVs, Word docs, invoices, contracts, emails. Nobody can search across all of it intelligently. Omnidoc fixes that. You point it at a folder, S3 bucket, or Google Drive and within minutes you can ask:

- *"Which contracts mention a penalty clause and are expiring in 2025?"*
- *"What's the average invoice total per client last quarter?"*
- *"Find all support tickets where the customer mentioned a refund"*

It figures out the data itself. You just ask questions.

---

## Target Users / Business Value

- **Law firms** — search across 50,000 contracts instantly
- **Finance teams** — query invoices, POs, audit docs
- **Healthcare** — semantic search across patient notes
- **HR departments** — search CVs, policies, job descriptions
- **Customer support** — find tickets by meaning, not just keywords

This competes with tools like Glean, Notion AI, and Microsoft Copilot — but is self-hostable, works on any file type, and the user owns their data.

---

## Full Tech Stack

| Layer | Technology | Why |
|---|---|---|
| Backend API | FastAPI (Python) | Async, fast, great for AI pipelines |
| File Storage | MinIO (local S3) | S3-compatible, swap for AWS S3 in prod |
| Metadata DB | PostgreSQL | Tracks document state, users, collections |
| Full-text Search | Elasticsearch | Keyword search, filters, aggregations |
| Vector Search | Qdrant | Semantic / meaning-based search |
| Query Engine | DuckDB | SQL directly over CSVs/Parquet in memory |
| LLM | Claude API (claude-sonnet-4-20250514) | Schema inference, NL→SQL, query planning |
| Embeddings | sentence-transformers (all-MiniLM-L6-v2) | Free, runs locally, vectorizes chunks |
| PDF Parsing | pdfplumber | Extract text from PDFs |
| CSV Parsing | Python csv module | Parse tabular data |
| DOCX Parsing | python-docx | Extract text and tables from Word docs |
| Task Queue | Redis + Celery | Async ingestion pipeline (planned) |
| Frontend | Next.js + React + Shadcn/ui + Tailwind | UI (planned Week 4) |
| Auth | NextAuth / JWT | User sessions (planned) |
| Infra | Docker Compose | Local dev, all services in one command |

---

## Project Structure

```
omnidoc/
├── .env                        ← all secrets and config (never commit)
├── requirements.txt
├── AGENTS.md                   ← this file
├── main.py                     ← MAIN ENTRY POINT ingestion
│
├── app/
│   ├── core/
│   │   ├── config.py           ← loads all env vars (single source of truth)
│   │   └── database.py         ← PostgreSQL connection + execute_query
│   │
│   ├── storage/
│   │   └── minio_client.py     ← MinIO file operations
│   │
│   ├── parsers/
│   │   ├── pdf_parser.py       ← returns (text, metadata, chunks)
│   │   ├── csv_parser.py        ← returns (text, metadata, chunks)
│   │   └── docx_parser.py      ← returns (text, metadata, chunks)
│   │
│   ├── models/
│   │   └── document.py         ← insert_document, update_status
│   │
│   └── (indexing/, query/)     ← future weeks
│
├── test_data/                  ← test files for development
└── docker-compose.yml         ← future: all services
```

---

## Environment Variables (.env)

```bash
# MinIO
MINIO_HOST=localhost:9000
MINIO_ACCESS_KEY=admin
MINIO_SECRET_KEY=password123
MINIO_BUCKET=omnidoc

# PostgreSQL
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_USER=admin
POSTGRES_PASSWORD=password123
POSTGRES_DB=omnidoc

# Elasticsearch
ES_HOST=https://localhost:9200
ES_USER=elastic
ES_PASSWORD=yourpassword

# Qdrant
QDRANT_HOST=localhost
QDRANT_PORT=6333

# Claude API
ANTHROPIC_API_KEY=your_key_here
```

---

## PostgreSQL Schema

```sql
-- Collections: groups of documents (e.g. "Q4 Invoices", "Contracts 2025")
CREATE TABLE collections (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        VARCHAR(255) NOT NULL UNIQUE,
    created_at  TIMESTAMP DEFAULT NOW()
);

-- Documents: one row per uploaded file
CREATE TABLE documents (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    filename        VARCHAR(255)    NOT NULL,
    file_type       VARCHAR(50)     NOT NULL,       -- pdf, csv, docx, txt
    file_size       INTEGER,                        -- bytes
    minio_path      VARCHAR(500),                   -- e.g. omnidoc/raw/{collection_id}/{doc_id}/file.pdf
    status          VARCHAR(50)     DEFAULT 'pending',
    -- status flow: pending → parsing → parsed → indexing → indexed → error
    error_message   TEXT,
    word_count      INTEGER,
    page_count      INTEGER,
    collection_id   UUID REFERENCES collections(id),
    created_at      TIMESTAMP       DEFAULT NOW(),
    updated_at      TIMESTAMP       DEFAULT NOW()
);

-- Auto-update updated_at
CREATE OR REPLACE FUNCTION update_timestamp()
RETURNS TRIGGER AS $$
BEGIN NEW.updated_at = NOW(); RETURN NEW; END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER documents_updated_at
    BEFORE UPDATE ON documents
    FOR EACH ROW EXECUTE FUNCTION update_timestamp();
```

---

## Storage Layout in MinIO

Every file is stored twice in MinIO:

```
omnidoc/                                          ← bucket name
├── raw/
│   └── {collection_id}/
│       └── {doc_id}/
│           └── invoice_001.pdf                ← original file, untouched
└── parsed/
    └── {collection_id}/
        └── {doc_id}/
            └── invoice_001.json               ← extracted text + chunks
```

The parsed JSON looks like:
```json
{
  "id": "abc-123",
  "filename": "invoice_001.pdf",
  "file_type": "pdf",
  "raw_text": "Invoice #1042\nClient: Acme Corp\nTotal: $4200...",
  "metadata": {
    "page_count": 2,
    "word_count": 340,
    "created_at": "2024-09-22",
    "has_tables": true
  },
  "chunks": [
    {
      "index": 0,
      "text": "Invoice #1042 Client: Acme Corp",
      "source_page": 1,
      "has_table": false,
      "word_count": 8
    },
    {
      "index": 1,
      "text": "Total: $4200 Due: 2025-03-01",
      "source_page": 2,
      "has_table": false,
      "word_count": 12
    }
  ]
}
```

---

## Ingestion Pipeline

File goes through 4 steps in `main.py`:

```
[1] Upload raw file → MinIO (raw/{collection_id}/{doc_id}/filename)
[2] Insert metadata → PostgreSQL (status = "pending")
[3] Extract text → parser returns (text, metadata, chunks)
[4] Add overlap + filter → Upload parsed JSON → MinIO
    → Update PostgreSQL status = "processed"
    → On any error: status = "error", error_message = exception string
```

Chunking strategy:
- **PDF/DOCX**: chunk per page/section, split oversized by paragraph
- **CSV**: group 50 rows per chunk, header row in EVERY chunk
- **TXT/MD/JSON**: paragraph-aware word chunking
- **Overlap**: last 2 sentences prepended to next chunk
- **Filtering**: min 20 words per chunk, done AFTER overlap
- **Signature tables**: chunks with "signature" + "date:" are dropped

---

## Dual Indexing Strategy (Week 2 — In Progress)

Every chunk from the parsed JSON gets indexed in **two places**:

### Elasticsearch (Keyword + Structured)
- Used for: exact keyword search, filters by date/type/size, aggregations, query history
- Index name: `documents`
- Each document in ES = one chunk (not the whole file)

```json
{
  "doc_id":    "abc-123",
  "chunk_id":  "abc-123_chunk_2",
  "filename":  "invoice_001.pdf",
  "file_type": "pdf",
  "text":      "Late payment penalty applies after 30 days",
  "chunk_index": 2,
  "collection_id": "col-456",
  "created_at": "2024-09-22"
}
```

### Qdrant (Semantic / Vector)
- Used for: meaning-based search, synonym matching, fuzzy concept queries
- Collection name: `documents`
- Each point = one chunk, stored with its embedding vector + payload

```json
{
  "id": "abc-123_chunk_2",
  "vector": [0.23, 0.87, 0.12, ...],
  "payload": {
    "doc_id": "abc-123",
    "filename": "invoice_001.pdf",
    "text": "Late payment penalty applies after 30 days",
    "collection_id": "col-456"
  }
}
```

Embedding model: `sentence-transformers/all-MiniLM-L6-v2` (384 dimensions, runs locally, free)

---

## Query Layer (Week 3 — Planned)

When a user submits a query, a **Query Planner** (LLM) decides the routing:

```
User query
    ↓
LLM classifies intent
    ↓
┌─────────────────────────────────────┐
│ Keyword/filter? → Elasticsearch     │
│ Semantic/fuzzy? → Qdrant            │
│ Aggregation/SQL? → DuckDB           │
│ Hybrid?         → ES + Qdrant merge │
└─────────────────────────────────────┘
    ↓
Results ranked + returned to UI
```

**DuckDB** runs SQL directly on the parsed JSON/CSV files in MinIO without ETL. Example:
```sql
SELECT client_name, SUM(total_amount) as revenue
FROM 'parsed/col-456/*/*.json'
GROUP BY client_name
ORDER BY revenue DESC
```

---

## Key Coding Conventions

- **All env vars** loaded only in `app/core/config.py` — never use `os.getenv()` anywhere else
- **All DB queries** go through `execute_query()` in `app/core/database.py`
- **Parsers** always return a tuple: `(text: str, metadata: dict, chunks: list[dict])`
- **Status field** is the pipeline's control panel — always update it before and after long operations
- **Never hardcode** collection IDs, bucket names, or credentials anywhere
- **Error handling**: wrap pipeline steps in try/except, always call `update_status(id, "error", str(e))` on failure
- Use **keyword arguments** for all Minio() and psycopg2.connect() calls
- All files must have `__init__.py` in their directory to be treated as Python packages
- **Filtering**: min 20 words per chunk, done AFTER overlap is applied
- **Signature tables**: chunks with signature + date fields are dropped

---

## Current Build Status

| Week | Goal | Status |
|---|---|---|
| Week 1 | File ingestion pipeline | ✅ Complete |
| Week 2 | ES + Qdrant dual indexing | 🔄 In Progress |
| Week 3 | Query planner + DuckDB + NL→SQL | ⏳ Planned |
| Week 4 | React UI + auth + deployment | ⏳ Planned |

### What Works Right Now
- Upload any PDF/CSV/DOCX via `main.py`
- Raw file saved to MinIO
- Metadata tracked in PostgreSQL with status flow
- Text extracted and chunked into parsed JSON
- Parsed JSON saved back to MinIO
- Overlap between chunks (last 2 sentences)
- Small chunks (< 20 words) filtered after overlap
- Signature tables dropped from output

### What's Being Built Next
- `app/indexing/` — Elasticsearch + Qdrant indexing pipeline

---

## How to Run Locally

```bash
# 1. Start services
docker compose up -d

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run ingestion on a file
python main.py
```

---

## Common Errors & Fixes

| Error | Cause | Fix |
|---|---|---|
| `ModuleNotFoundError: config` | Wrong import path | Use `from app.core.config import ...` |
| `ModuleNotFoundError: No module named 'app'` | Running from wrong directory | Always run from project root |
| `S3Error: Access Denied` | Wrong MinIO credentials | Check `.env` MINIO_ACCESS_KEY/SECRET |
| `psycopg2 build failed` | Wrong package | Use `psycopg2-binary` not `psycopg2` |
| `uuid_generate_v4() does not exist` | Missing extension | Use `gen_random_uuid()` instead |
| `relation does not exist` | Table not created | Run the SQL schema above in psql |
| `IndentationError` | Broken paste | Re-indent — Python is strict |