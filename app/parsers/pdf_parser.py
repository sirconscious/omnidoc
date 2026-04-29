import logging
import re
from pathlib import Path
from typing import Tuple, List, Dict, Any

logger = logging.getLogger(__name__)
MIN_WORDS_PER_CHUNK = 20
MAX_WORDS_PER_CHUNK = 200

try:
    import pdfplumber
    HAS_PDFPLUMBER = True
except ImportError:
    HAS_PDFPLUMBER = False
    logger.warning("pdfplumber not installed - PDF parsing limited")

try:
    import pytesseract
    from pdf2image import convert_from_path
    HAS_OCR = True
except ImportError:
    HAS_OCR = False
    logger.warning("OCR dependencies (pytesseract/pdf2image) not installed - scanned PDFs will not be processed")


def _ocr_page(image_path: str) -> str:
    """Extract text from a PDF page image using OCR."""
    if not HAS_OCR:
        return ""
    try:
        from PIL import Image
        img = Image.open(image_path)
        text = pytesseract.image_to_string(img)
        return text.strip()
    except Exception as e:
        logger.warning(f"OCR failed: {e}")
        return ""


def _extract_tables(pdf) -> Tuple[str, bool]:
    """Extract tables from PDF and format as markdown."""
    has_tables = False
    table_texts = []
    
    for page_num, page in enumerate(pdf.pages, 1):
        tables = page.extract_tables()
        if tables:
            has_tables = True
            for table in tables:
                if table and table[0]:
                    header = table[0]
                    rows = table[1:] if len(table) > 1 else []
                    
                    all_rows_for_width = [header] + rows
                    if not all_rows_for_width or not all_rows_for_width[0] or not header:
                        continue
                    
                    max_cols = len(header)
                    col_widths = []
                    for col_idx in range(max_cols):
                        max_width = len(str(header[col_idx]))
                        for row in rows:
                            if col_idx < len(row):
                                max_width = max(max_width, len(str(row[col_idx])))
                        col_widths.append(max_width)
                    
                    sep = "|" + "|".join(["" * (w + 2) for w in col_widths]) + "|"
                    
                    lines = [sep]
                    header_line = "|" + "|".join([str(h).center(w + 2) for h, w in zip(header, col_widths)]) + "|"
                    lines.append(header_line)
                    lines.append(sep)
                    
                    for row in rows:
                        row_line = "|" + "|".join([str(row[i]).ljust(col_widths[i]) if i < len(row) else " " * col_widths[i] for i in range(len(col_widths))]) + "|"
                        lines.append(row_line)
                    
                    table_texts.append(f"--- Table on Page {page_num} ---\n" + "\n".join(lines))
    
    return "\n\n".join(table_texts), has_tables


def _extract_metadata(pdf) -> Dict[str, Any]:
    """Extract PDF metadata (title, author, creation date, etc.)."""
    meta = {}
    
    try:
        meta_dict = pdf.metadata
        if meta_dict:
            meta["title"] = meta_dict.get("/Title") or meta_dict.get("Title") or None
            meta["author"] = meta_dict.get("/Author") or meta_dict.get("Author") or None
            meta["creator"] = meta_dict.get("/Creator") or meta_dict.get("Creator") or None
            meta["creation_date"] = meta_dict.get("/CreationDate") or meta_dict.get("CreationDate") or None
            meta["mod_date"] = meta_dict.get("/ModDate") or meta_dict.get("ModDate") or None
    except Exception as e:
        logger.warning(f"Failed to extract PDF metadata: {e}")
    
    return meta


def _extract_page_with_fallback(pdf, page_num: int, page) -> Tuple[str, bool]:
    """Extract text from a single page, falling back to OCR if needed."""
    text = page.extract_text() or ""
    
    if len(text.strip()) < 20:
        logger.info(f"Page {page_num} has insufficient text ({len(text)} chars), attempting OCR...")
        
        if HAS_OCR:
            try:
                import tempfile
                import os
                
                with tempfile.TemporaryDirectory() as tmpdir:
                    images = convert_from_path(str(page.parent.stream.stream.name), first_page=page_num, last_page=page_num, output_folder=tmpdir)
                    if images:
                        img_path = os.path.join(tmpdir, f"page_{page_num}.png")
                        images[0].save(img_path, "PNG")
                        text = _ocr_page(img_path)
                        
                        if text:
                            logger.info(f"OCR recovered {len(text)} chars from page {page_num}")
                            return text, True
            except Exception as e:
                logger.warning(f"OCR fallback failed for page {page_num}: {e}")
        
        return text, False
    
    return text, False


def _has_table_in_text(text: str) -> bool:
    """Check if chunk text contains table markup."""
    return "--- Table" in text or "| " in text


def _strip_table_from_overlap(text: str) -> str:
    """Remove table lines from overlap text."""
    lines = text.split("\n")
    filtered = []
    for line in lines:
        if line.startswith("|") or line.startswith("---"):
            continue
        filtered.append(line)
    return "\n".join(filtered)


def _filter_small_chunks(chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Filter out chunks with less than MIN_WORDS_PER_CHUNK words."""
    filtered = [c for c in chunks if c.get("word_count", 0) >= MIN_WORDS_PER_CHUNK]
    
    if not filtered and chunks:
        max_chunk = max(chunks, key=lambda c: c.get("word_count", 0))
        filtered = [max_chunk]
    
    for i, chunk in enumerate(filtered):
        chunk["index"] = i
    
    return filtered


def _chunk_single_page(text: str, max_words: int = 100) -> List[Dict[str, Any]]:
    """Split single-page text into line-aware chunks."""
    lines = text.split("\n")
    
    chunks = []
    current_chunk_lines = []
    current_words = 0
    
    for line in lines:
        line_words = len(line.split())
        if line_words == 0:
            continue
        
        if current_words + line_words > max_words and current_chunk_lines:
            chunk_text = "\n".join(current_chunk_lines)
            lines_stripped = [l.strip() for l in chunk_text.split("\n") if l.strip()]
            section = lines_stripped[0][:100] if lines_stripped else None
            
            chunks.append({
                "index": len(chunks),
                "text": chunk_text,
                "source_page": 1,
                "source_section": section,
                "has_table": _has_table_in_text(chunk_text),
                "word_count": len(chunk_text.split()),
            })
            current_chunk_lines = []
            current_words = 0
        
        current_chunk_lines.append(line)
        current_words += line_words
    
    if current_chunk_lines:
        chunk_text = "\n".join(current_chunk_lines)
        lines_stripped = [l.strip() for l in chunk_text.split("\n") if l.strip()]
        section = lines_stripped[0][:100] if lines_stripped else None
        
        chunks.append({
            "index": len(chunks),
            "text": chunk_text,
            "source_page": 1,
            "source_section": section,
            "has_table": _has_table_in_text(chunk_text),
            "word_count": len(chunk_text.split()),
        })
    
    return chunks


def parse_pdf(file_path: Path) -> Tuple[str, Dict[str, Any], List[Dict[str, Any]]]:
    """Parse a PDF file with enhanced extraction."""
    if not HAS_PDFPLUMBER:
        logger.error("pdfplumber not available")
        return "", {"error": "pdfplumber not installed"}, []
    
    metadata = {
        "page_count": 0,
        "has_tables": False,
        "has_ocr_pages": False,
        "title": None,
        "author": None,
        "creator": None,
        "creation_date": None,
        "mod_date": None,
    }
    
    all_text_parts = []
    chunks = []
    ocr_pages = []
    
    with pdfplumber.open(file_path) as pdf:
        metadata["page_count"] = len(pdf.pages)
        
        pdf_meta = _extract_metadata(pdf)
        metadata.update(pdf_meta)
        
        table_text, has_tables = _extract_tables(pdf)
        metadata["has_tables"] = has_tables
        
        for page_num, page in enumerate(pdf.pages, 1):
            page_text, was_ocr = _extract_page_with_fallback(pdf, page_num, page)
            
            if was_ocr:
                ocr_pages.append(page_num)
                metadata["has_ocr_pages"] = True
            
            if page_text:
                all_text_parts.append(page_text)
                
                word_count = len(page_text.split())
                chunk_has_table = _has_table_in_text(page_text)
                
                chunks.append({
                    "index": page_num - 1,
                    "text": page_text,
                    "source_page": page_num,
                    "source_section": None,
                    "has_table": chunk_has_table,
                    "word_count": word_count,
                })
        
        if has_tables and table_text:
            for chunk in chunks:
                if chunk["source_page"] == 1:
                    if not chunk["has_table"]:
                        chunk["text"] = chunk["text"] + "\n\n" + table_text
                        chunk["has_table"] = True
                    break
    
    full_text = "\n\n".join(all_text_parts)
    
    if metadata["has_ocr_pages"]:
        metadata["ocr_pages"] = ocr_pages
    
    # Special handling for single-page PDFs with substantial content
    if len(pdf.pages) == 1 and len(chunks) == 1 and chunks[0]["word_count"] > 200:
        logger.info(f"Single-page PDF with {chunks[0]['word_count']} words - splitting into {len(_chunk_single_page(chunks[0]['text']))} chunks")
        chunks = _chunk_single_page(chunks[0]["text"])
    
    # Note: filtering now handled in main.py after overlap
    # chunks = _filter_small_chunks(chunks)
    
    return full_text, metadata, chunks
