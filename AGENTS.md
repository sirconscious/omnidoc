# AGENTS.md — Omnidoc

## What Exists Now
- Python ingestion pipeline (`main.py` script with interactive prompt)
- File parsers: PDF (pdfplumber), CSV, DOCX (python-docx), TXT/MD/JSON
- Storage: MinIO (raw files + parsed JSON)
- Metadata: PostgreSQL
- Keyword search: Elasticsearch (indexes text chunks)
- Vector search: Qdrant (all-MiniLM-L6-v2 embeddings, 384 dims)

## What Does NOT Exist Yet
- No FastAPI server, no query layer, no frontend
- No DuckDB, no NL→SQL
- No tests, no linting, no typechecking
- No docker-compose.yml

## Run Ingestion
```bash
# Install dependencies
pip install -r requirements.txt

# Start services (MinIO, PostgreSQL, Elasticsearch, Qdrant)
# Then run ingestion (interactive: choose file or directory)
python main.py
```

## Environment
- Config loaded via `python-dotenv` in `app/core/config.py`
- All env vars in `.env` (gitignored, see `.env.example`)
- MinIO client uses `secure=False` (HTTP)
- Qdrant uses `QDRANT_HOST` and `QDRANT_PORT` env vars

## Code Structure
```
app/
├── core/         # config.py, database.py
├── parsers/      # pdf_parser, csv_parser, docx_parser
├── storage/      # minio_client.py
├── models/       # document.py, collection.py
└── indexing/     # es_client.py, es_indexer.py, embeddings.py, qdrant_client.py, qdrant_indexer.py
```

## Key Conventions
- Parsers return `(text: str, metadata: dict, chunks: list[dict])`
- DB queries via `execute_query()` in `app/core/database.py`
- Chunk filtering: min 20 words AFTER overlap applied
- Signature table chunks (contain "signature" + "date:") are dropped
- ES index per collection: `omnidoc_{collection_id}`
- Qdrant collection: `documents` (384-dim cosine distance)
- Embedding model loaded once (singleton in `embeddings.py`)

## Ingestion Pipeline (6 steps)
```
[1] Upload raw file → MinIO
[2] Insert metadata → PostgreSQL (status: pending)
[3] Extract text → parser returns (text, metadata, chunks)
[4] Add overlap + filter → Upload parsed JSON → MinIO
[5] Index chunks → Elasticsearch
[6] Index chunks → Qdrant (vector embeddings)
```

## Common Errors
- `ModuleNotFoundError`: Run from project root, not subdirectory
- `S3Error: Access Denied`: Check MINIO_ACCESS_KEY/SECRET in `.env`
- `psycopg2` build fails: Use `psycopg2-binary` (already in requirements.txt)
- `sentence-transformers` first run: Downloads model (~80MB), may take time
