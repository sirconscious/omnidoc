import os
import uuid
import json
import mimetypes
import re
import logging
from pathlib import Path
from datetime import datetime
from app.parsers.pdf_parser import parse_pdf
from app.parsers.csv_parser import parse_csv
from app.parsers.docx_parser import parse_docx

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

try:
    import pdfplumber
    HAS_PDF = True
except ImportError:
    HAS_PDF = False

from app.storage.minio_client import upload_file as minio_upload
from app.models.document    import insert_document, update_status, get_document_by_filename
from app.indexing.es_indexer import index_document_chunks
from app.indexing.qdrant_indexer import index_chunks as qdrant_index_chunks


CHUNK_OVERLAP_SENTENCES = 2
MAX_WORDS_PER_CHUNK = 200
CSV_ROWS_PER_CHUNK = 50


def _get_sentences(text: str) -> list[str]:
    """Split text into sentences."""
    sentences = re.split(r'(?<=[.!?])\s+', text)
    return [s.strip() for s in sentences if s.strip()]


def _strip_table_from_overlap(text: str) -> str:
    """Remove table lines from overlap text."""
    lines = text.split("\n")
    filtered = []
    for line in lines:
        if line.startswith("|") or line.startswith("---"):
            continue
        filtered.append(line)
    return "\n".join(filtered)


def _add_overlap(chunks: list[dict], overlap_sentences: int = 2) -> list[dict]:
    """Add overlap between chunks for semantic search continuity."""
    if len(chunks) <= 1:
        return chunks
    
    result = [chunks[0].copy()]
    
    for i in range(1, len(chunks)):
        current = chunks[i].copy()
        previous_text = chunks[i - 1]["text"]
        
        sentences = _get_sentences(previous_text)
        overlap_text = " ".join(sentences[-overlap_sentences:])
        
        overlap_text = _strip_table_from_overlap(overlap_text)
        
        if overlap_text and current["text"]:
            current["text"] = f"{overlap_text} {current['text']}"
            current["word_count"] = len(current["text"].split())
            
            if "| " in overlap_text or "--- Table" in overlap_text:
                current["has_table"] = True
        
        result.append(current)
    
    return result


def _has_table_in_text(text: str) -> bool:
    """Check if chunk text contains table markup."""
    return "--- Table" in text or "| " in text[:200]


MIN_WORDS_PER_CHUNK = 20


def _filter_and_clean_chunks(chunks: list[dict]) -> list[dict]:
    """Filter small chunks and drop signature tables, then re-index."""
    MIN_WORDS = 20
    
    filtered = []
    for chunk in chunks:
        text = chunk.get("text", "")
        text_lower = text.lower()
        
        # Issue 3: Drop signature table chunks (case-insensitive check)
        if chunk.get("has_table", False):
            if "signature" in text_lower and ("date:" in text_lower or "_______" in text_lower):
                continue
        
        # Issue 2: Filter by word count AFTER overlap
        word_count = len(text.split())
        if word_count >= MIN_WORDS:
            filtered.append(chunk)
    
    # If everything filtered out, keep the largest chunk
    if not filtered and chunks:
        max_chunk = max(chunks, key=lambda c: len(c.get("text", "").split()))
        filtered = [max_chunk]
    
    # Re-index sequential
    for i, chunk in enumerate(filtered):
        chunk["index"] = i
        chunk["word_count"] = len(chunk.get("text", "").split())
    
    return filtered


def _chunk_with_overlap(text: str, max_words: int = 200, file_type: str = None) -> list[dict]:
    """Split text into overlapping chunks."""
    if file_type == "csv":
        return []
    
    paragraphs = re.split(r"\n\s*\n", text)
    
    chunks = []
    current_chunk = []
    current_words = 0
    
    for para in paragraphs:
        words = para.split()
        
        if len(words) > max_words:
            if current_chunk:
                chunks.append({
                    "index": len(chunks),
                    "text": " ".join(current_chunk),
                    "source_page": None,
                    "source_section": None,
                    "has_table": False,
                    "word_count": current_words,
                })
                current_chunk = []
                current_words = 0
            
            for i in range(0, len(words), max_words):
                chunk_text = " ".join(words[i:i + max_words])
                chunks.append({
                    "index": len(chunks),
                    "text": chunk_text,
                    "source_page": None,
                    "source_section": None,
                    "has_table": False,
                    "word_count": len(chunk_text.split()),
                })
            continue
        
        if current_words + len(words) > max_words:
            chunks.append({
                "index": len(chunks),
                "text": " ".join(current_chunk),
                "source_page": None,
                "source_section": None,
                "has_table": False,
                "word_count": current_words,
            })
            current_chunk = []
            current_words = 0
        
        current_chunk.extend(words)
        current_words += len(words)
    
    if current_chunk:
        chunks.append({
            "index": len(chunks),
            "text": " ".join(current_chunk),
            "source_page": None,
            "source_section": None,
            "has_table": False,
            "word_count": current_words,
        })
    
    return chunks


def _parse_txt_md_json(file_path: Path) -> tuple:
    """Parse plain text, markdown, or JSON files."""
    text = file_path.read_text(encoding="utf-8", errors="replace")
    
    chunks = _chunk_with_overlap(text)
    chunks = _add_overlap(chunks)
    
    metadata = {
        "word_count": len(text.split()),
    }
    
    return text, metadata, chunks


def extract_text(file_path: Path, file_type: str):
    """Extract text based on file type."""
    if file_type == "pdf":
        return parse_pdf(file_path)
    elif file_type == "csv":
        return parse_csv(file_path)
    elif file_type == "docx":
        return parse_docx(file_path)
    elif file_type in ("txt", "md", "json"):
        return _parse_txt_md_json(file_path)
    else:
        return "", {}


def build_document_json(
    doc_id:     str,
    filename:   str,
    file_type:  str,
    raw_text:   str,
    extra_meta: dict,
    file_path:  Path,
    parser_chunks: list[dict] = None,
) -> dict:
    """Build the normalized document JSON."""
    stat = file_path.stat()
    created_at = datetime.fromtimestamp(stat.st_ctime).strftime("%Y-%m-%d")
    
    if parser_chunks:
        chunks = _add_overlap(parser_chunks, CHUNK_OVERLAP_SENTENCES)
        chunks = _filter_and_clean_chunks(chunks)  # Issue 2+3: filter AFTER overlap
    else:
        chunks = _chunk_with_overlap(raw_text, MAX_WORDS_PER_CHUNK, file_type)
        chunks = _add_overlap(chunks, CHUNK_OVERLAP_SENTENCES)
        chunks = _filter_and_clean_chunks(chunks)  # Issue 2+3: filter AFTER overlap
    
    metadata = {
        "page_count": extra_meta.get("page_count"),
        "word_count": extra_meta.get("word_count", len(raw_text.split())),
        "created_at": created_at,
        "has_tables": extra_meta.get("has_tables", False),
        "author": extra_meta.get("author"),
        "title": extra_meta.get("title"),
    }
    
    for key in extra_meta:
        if key not in metadata or metadata[key] is None:
            metadata[key] = extra_meta[key]
    
    # Final filter: ensure no chunks below 20 words (absolute last step)
    chunks = [c for c in chunks if c.get("word_count", 0) >= 20]
    for i, c in enumerate(chunks):
        c["index"] = i
    
    return {
        "id":        doc_id,
        "filename":  filename,
        "file_type": file_type,
        "raw_text":  raw_text,
        "metadata": metadata,
        "chunks": chunks,
    }


def ingest(file_path_str: str) -> str:
    """Main ingestion pipeline. Returns 'success', 'skipped', or 'error'."""
    file_path = Path(file_path_str).expanduser().resolve()
    
    if not file_path.exists():
        logger.error(f"File not found: {file_path}")
        return "error"
    if not file_path.is_file():
        logger.error(f"Path is not a file: {file_path}")
        return "error"
    
    filename  = file_path.name
    file_type = file_path.suffix.lstrip(".").lower() or "bin"
    file_size = file_path.stat().st_size
    mime_type, _ = mimetypes.guess_type(str(file_path))
    mime_type = mime_type or "application/octet-stream"
    doc_id    = str(uuid.uuid4())
    
    collection_id = "acf3a192-c113-4ae3-acba-994d300419dd"

    existing = get_document_by_filename(filename, collection_id)
    if existing:
        logger.info(f"  ⏭ Already exists (id={existing['id']}, status={existing['status']}), skipping...")
        return "skipped"
    
    logger.info(f"\nIngesting: {filename}  ({file_size:,} bytes)")
    
    logger.info("[1/5] Uploading raw file → MinIO ...")
    file_bytes  = file_path.read_bytes()
    minio_key = f"raw/{collection_id}/{doc_id}/{filename}"
    minio_path  = minio_upload(file_bytes, minio_key, mime_type)
    
    logger.info("[2/5] Inserting metadata → PostgreSQL ...")
    db_id = insert_document(
        filename,
        file_type,
        file_size,
        minio_path,
        collection_id
    )
    
    try:
        logger.info("[3/5] Extracting text & building JSON ...")
        raw_text, extra_meta, parser_chunks = extract_text(file_path, file_type)
        
        doc_json = build_document_json(
            doc_id     = str(db_id),
            filename   = filename,
            file_type  = file_type,
            raw_text   = raw_text,
            extra_meta = extra_meta,
            file_path  = file_path,
            parser_chunks = parser_chunks,
        )
        
        logger.info("[4/5] Uploading parsed JSON → MinIO ...")
        json_bytes   = json.dumps(doc_json, ensure_ascii=False, indent=2).encode("utf-8")
        json_key = f"parsed/{collection_id}/{db_id}/{file_path.stem}.json"
        minio_upload(json_bytes, json_key, "application/json")

        logger.info("[5/5] Indexing chunks → Elasticsearch ...")
        es_result = index_document_chunks(
            doc_id=str(db_id),
            collection_id=collection_id,
            filename=filename,
            file_type=file_type,
            chunks=doc_json["chunks"],
        )
        if es_result["failed"] > 0:
            logger.warning(f"ES indexing had {es_result['failed']} chunk failures")

        logger.info("[6/6] Indexing chunks → Qdrant (vector search) ...")
        qdrant_index_chunks(
            doc_id=str(db_id),
            filename=filename,
            collection_id=collection_id,
            chunks=doc_json["chunks"],
        )
        logger.info(f"       Qdrant chunks indexed: {len(doc_json['chunks'])}")

        update_status(db_id, "indexed")
        logger.info(f"\nDone! DB id={db_id}")
        logger.info(f"       Raw  → {minio_path}")
        logger.info(f"       JSON → parsed/{db_id}/{filename}.json")
        logger.info(f"       Chunks: {len(doc_json['chunks'])}")
        logger.info(f"       ES chunks indexed: {es_result['indexed']}")
        return "success"
    
    except Exception as exc:
        update_status(db_id, "error", str(exc))
        logger.error(f"\nPipeline failed: {exc}")
        raise


SUPPORTED_EXTENSIONS = {".pdf", ".csv", ".docx", ".txt", ".md", ".json"}


def ingest_directory(dir_path_str: str) -> None:
    """Ingest all supported files in a directory (non-recursive)."""
    dir_path = Path(dir_path_str).expanduser().resolve()

    if not dir_path.exists():
        logger.error(f"Directory not found: {dir_path}")
        return
    if not dir_path.is_dir():
        logger.error(f"Path is not a directory: {dir_path}")
        return

    files = [f for f in dir_path.iterdir() if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS]

    if not files:
        logger.info(f"No supported files found in {dir_path}")
        logger.info(f"Supported types: {', '.join(sorted(SUPPORTED_EXTENSIONS))}")
        return

    files.sort(key=lambda f: f.name)

    logger.info(f"\nFound {len(files)} supported file(s) in {dir_path}")

    succeeded = 0
    failed = 0
    skipped = 0

    for i, file_path in enumerate(files, 1):
        logger.info(f"\n{'='*60}")
        logger.info(f"[{i}/{len(files)}] Processing: {file_path.name}")
        logger.info(f"{'='*60}")
        try:
            result = ingest(str(file_path))
            if result == "skipped":
                skipped += 1
            elif result == "success":
                succeeded += 1
            else:
                failed += 1
        except Exception as exc:
            logger.error(f"Failed to ingest {file_path.name}: {exc}")
            failed += 1

    logger.info(f"\n{'='*60}")
    logger.info(f"Summary: {succeeded} succeeded, {skipped} skipped, {failed} failed")
    logger.info(f"{'='*60}")


if __name__ == "__main__":
    print("=== Document Ingestion Pipeline ===")
    choice = input("Process a single (f)ile or (d)irectory? [f/d]: ").strip().lower()

    if choice == "d":
        dir_path = input("Enter the directory path: ").strip()
        ingest_directory(dir_path)
    else:
        file_path = input("Enter the file path: ").strip()
        ingest(file_path)
