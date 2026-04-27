import os
import uuid
import json
import mimetypes
from pathlib import Path
from datetime import datetime

# ── optional PDF parsing ───────────────────────────────────────────────────────
try:
    import pdfplumber
    HAS_PDF = True
except ImportError:
    HAS_PDF = False

# ── your existing modules ──────────────────────────────────────────────────────
from app.storage.minio_client import upload_file as minio_upload
from app.models.document    import insert_document, update_status
from app.storage.minio_client import upload_file as minio_upload_raw


# ──────────────────────────────────────────────────────────────────────────────
# 1.  TEXT EXTRACTION
# ──────────────────────────────────────────────────────────────────────────────

def extract_text(file_path: Path, file_type: str) -> tuple[str, dict]:
    """
    Returns (raw_text, extra_metadata).
    Supports PDF (via pdfplumber) and plain-text files.
    Extend the elif chain for docx, xlsx, etc.
    """
    raw_text      = ""
    extra_meta    = {}

    if file_type == "pdf":
        if not HAS_PDF:
            raise RuntimeError("pdfplumber is not installed. Run: pip install pdfplumber")
        with pdfplumber.open(file_path) as pdf:
            pages     = [p.extract_text() or "" for p in pdf.pages]
            raw_text  = "\n".join(pages)
            extra_meta["page_count"] = len(pdf.pages)

    elif file_type in ("txt", "md", "csv", "json"):
        raw_text = file_path.read_text(encoding="utf-8", errors="replace")

    else:
        # Fallback: try reading as utf-8, silently ignore binary noise
        try:
            raw_text = file_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            raw_text = ""

    word_count             = len(raw_text.split())
    extra_meta["word_count"] = word_count

    return raw_text, extra_meta


# ──────────────────────────────────────────────────────────────────────────────
# 2.  CHUNKING
# ──────────────────────────────────────────────────────────────────────────────

def chunk_text(text: str, chunk_size: int = 200) -> list[str]:
    """
    Section-aware chunker:
      1. Inserts a blank line before ALL-CAPS section headers so pdfplumber's
         single-block output is split at logical boundaries.
      2. Tracks the current section header and repeats it at the start of every
         new chunk — no word-level overlap that bleeds mid-sentence.
      3. Flushes a chunk whenever adding the next paragraph would exceed
         chunk_size words, then opens a fresh chunk with the section header.
    """
    import re

    # Normalise: insert blank line before all-caps section headers
    text = re.sub(r"(?m)^([A-Z][A-Z\s&]{2,})$", r"\n\1", text)

    HEADER_RE = re.compile(r"^[A-Z][A-Z\s&]{2,}$")

    paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]

    chunks: list[str] = []
    current_words: list[str] = []
    current_header: str = ""

    for para in paragraphs:
        # Track the active section header
        if HEADER_RE.match(para):
            current_header = para

        para_words = para.split()

        # Flush when adding this paragraph would overflow
        if current_words and len(current_words) + len(para_words) > chunk_size:
            chunks.append(" ".join(current_words))
            # Start next chunk with the section header so it's self-contained
            current_words = current_header.split() if current_header else []

        current_words.extend(para_words)

    if current_words:
        chunks.append(" ".join(current_words))

    return chunks


# ──────────────────────────────────────────────────────────────────────────────
# 3.  BUILD NORMALIZED JSON
# ──────────────────────────────────────────────────────────────────────────────

def build_document_json(
    doc_id:     str,
    filename:   str,
    file_type:  str,
    raw_text:   str,
    extra_meta: dict,
    file_path:  Path,
) -> dict:
    stat = file_path.stat()
    created_at = datetime.fromtimestamp(stat.st_ctime).strftime("%Y-%m-%d")

    return {
        "id":        doc_id,
        "filename":  filename,
        "file_type": file_type,
        "raw_text":  raw_text,
        "metadata": {
            "page_count": extra_meta.get("page_count", None),
            "word_count": extra_meta.get("word_count", 0),
            "created_at": created_at,
        },
        "chunks": chunk_text(raw_text),
    }


# ──────────────────────────────────────────────────────────────────────────────
# 4.  PIPELINE
# ──────────────────────────────────────────────────────────────────────────────

def ingest(file_path_str: str) -> None:
    file_path = Path(file_path_str).expanduser().resolve()

    # ── validate ───────────────────────────────────────────────────────────────
    if not file_path.exists():
        print(f"  File not found: {file_path}")
        return
    if not file_path.is_file():
        print(f"  Path is not a file: {file_path}")
        return

    filename  = file_path.name
    file_type = file_path.suffix.lstrip(".").lower() or "bin"
    file_size = file_path.stat().st_size
    mime_type, _ = mimetypes.guess_type(str(file_path))
    mime_type = mime_type or "application/octet-stream"
    doc_id    = str(uuid.uuid4())

    print(f"\n Ingesting: {filename}  ({file_size:,} bytes)")

    collection_id = "acf3a192-c113-4ae3-acba-994d300419dd" #this shit needs to be changes 


    # ── Step 1 · upload raw file to MinIO ─────────────────────────────────────
    print("  [1/4] Uploading raw file → MinIO …")
    file_bytes  = file_path.read_bytes()
    minio_key = f"raw/{collection_id}/{doc_id}/{filename}"
    minio_path  = minio_upload(file_bytes, minio_key, mime_type)

    # ── Step 2 · insert metadata row (status = pending) ───────────────────────
    print("  [2/4] Inserting metadata → PostgreSQL …")
    db_id = insert_document(
        filename,
        file_type,
        file_size,
        minio_path,
        collection_id
    )
    try:
        # ── Step 3 · extract text + build JSON ────────────────────────────────
        print("  [3/4] Extracting text & building JSON …")
        raw_text, extra_meta = extract_text(file_path, file_type)

        doc_json = build_document_json(
            doc_id     = str(db_id),
            filename   = filename,
            file_type  = file_type,
            raw_text   = raw_text,
            extra_meta = extra_meta,
            file_path  = file_path,
        )

        # ── Step 4 · store parsed JSON back in MinIO ──────────────────────────
        print("  [4/4] Uploading parsed JSON → MinIO …")
        json_bytes   = json.dumps(doc_json, ensure_ascii=False, indent=2).encode("utf-8")
        json_key = f"parsed/{collection_id}/{db_id}/{file_path.stem}.json"
        minio_upload(json_bytes, json_key, "application/json")

        # ── mark done ─────────────────────────────────────────────────────────
        update_status(db_id, "processed")
        print(f"\n  Done!  DB id={db_id}")
        print(f"         Raw  → {minio_path}")
        print(f"         JSON → parsed/{db_id}/{filename}.json")
        print(f"         Chunks: {len(doc_json['chunks'])}")

    except Exception as exc:
        update_status(db_id, "error", str(exc))
        print(f"\n  Pipeline failed: {exc}")
        raise


# ──────────────────────────────────────────────────────────────────────────────
# 5.  ENTRY POINT
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=== Document Ingestion Pipeline ===")
    path = input("Enter the path to the file you want to upload: ").strip()
    ingest(path)