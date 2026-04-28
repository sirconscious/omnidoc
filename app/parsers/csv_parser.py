import csv
import logging
import re
from pathlib import Path
from typing import Tuple, List, Dict, Any
from datetime import datetime

logger = logging.getLogger(__name__)
MIN_WORDS_PER_CHUNK = 20


def _detect_delimiter(sample: str) -> str:
    """Auto-detect CSV delimiter using csv.Sniffer."""
    try:
        sniffer = csv.Sniffer()
        delimiter = sniffer.sniff(sample, delimiters_to_guess=[",", ";", "\t", "|"]).delimiter
        return delimiter
    except Exception:
        return ","


def _detect_column_type(values: List[str]) -> str:
    """Detect if a column is numeric, date, boolean, or text."""
    non_empty = [v for v in values if v and v.strip()]
    if not non_empty:
        return "text"
    
    numeric_count = 0
    date_count = 0
    bool_count = 0
    
    for val in non_empty[:100]:
        val_stripped = val.strip()
        
        if re.match(r"^-?\d+\.?\d*$", val_stripped):
            numeric_count += 1
            continue
        
        if re.match(r"^\d{4}-\d{2}-\d{2}", val_stripped):
            date_count += 1
            continue
        
        if val_stripped.lower() in ("true", "false", "yes", "no", "1", "0"):
            bool_count += 1
    
    threshold = len(non_empty[:100]) * 0.8
    
    if numeric_count >= threshold:
        return "numeric"
    if date_count >= threshold:
        return "date"
    if bool_count >= threshold:
        return "boolean"
    return "text"


def _parse_dates(values: List[str]) -> Tuple[str, str]:
    """Find earliest and latest dates in a column."""
    dates = []
    for val in values:
        val_stripped = val.strip() if val else ""
        try:
            for fmt in ["%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d"]:
                try:
                    dt = datetime.strptime(val_stripped, fmt)
                    dates.append(dt)
                    break
                except ValueError:
                    continue
        except Exception:
            continue
    
    if dates:
        return min(dates).strftime("%Y-%m-%d"), max(dates).strftime("%Y-%m-%d")
    return None, None


def _format_row(row: Dict[str, str], column_types: Dict[str, str], formatter: str = "key_value") -> str:
    """Format a CSV row as searchable text."""
    if formatter == "key_value":
        pairs = []
        for key, val in row.items():
            if val and val.strip():
                pairs.append(f"{key}:{val.strip()}")
        return " | ".join(pairs)
    return str(row)


def _compute_numeric_summary(rows: List[Dict[str, str]], numeric_cols: List[str]) -> Dict[str, Dict[str, float]]:
    """Compute summary stats for numeric columns."""
    summary = {}
    
    for col in numeric_cols:
        values = []
        for row in rows:
            val = row.get(col, "").strip()
            if val:
                try:
                    values.append(float(val))
                except ValueError:
                    continue
        
        if values:
            summary[col] = {
                "min": min(values),
                "max": max(values),
                "mean": sum(values) / len(values),
                "count": len(values),
            }
    
    return summary


def _compute_date_range(rows: List[Dict[str, str]], date_cols: List[str]) -> Dict[str, Dict[str, str]]:
    """Compute date ranges for date columns."""
    ranges = {}
    
    for col in date_cols:
        values = [row.get(col, "").strip() for row in rows if row.get(col, "").strip()]
        earliest, latest = _parse_dates(values)
        if earliest:
            ranges[col] = {"earliest": earliest, "latest": latest}
    
    return ranges


def _filter_small_chunks(chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Filter out chunks with less than MIN_WORDS_PER_CHUNK words."""
    filtered = [c for c in chunks if c.get("word_count", 0) >= MIN_WORDS_PER_CHUNK]
    
    if not filtered and chunks:
        max_chunk = max(chunks, key=lambda c: c.get("word_count", 0))
        filtered = [max_chunk]
    
    for i, chunk in enumerate(filtered):
        chunk["index"] = i
    
    return filtered


def parse_csv(file_path: Path) -> Tuple[str, Dict[str, Any], List[Dict[str, Any]]]:
    """Parse a CSV file with enhanced type detection."""
    try:
        with open(file_path, newline="", encoding="utf-8", errors="replace") as f_raw:
            sample = f_raw.read(8192)
    except Exception:
        sample = ""
    
    delimiter = _detect_delimiter(sample)
    
    rows = []
    header = []
    
    with open(file_path, newline="", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f, delimiter=delimiter)
        header = reader.fieldnames or []
        for row in reader:
            rows.append(dict(row))
    
    column_types = {}
    numeric_cols = []
    date_cols = []
    
    for col in header:
        values = [row.get(col, "") for row in rows]
        col_type = _detect_column_type(values)
        column_types[col] = col_type
        
        if col_type == "numeric":
            numeric_cols.append(col)
        elif col_type == "date":
            date_cols.append(col)
    
    numeric_summary = _compute_numeric_summary(rows, numeric_cols) if numeric_cols else {}
    date_range = _compute_date_range(rows, date_cols) if date_cols else {}
    
    text_parts = []
    for row in rows:
        text_parts.append(_format_row(row, column_types))
    full_text = "\n".join(text_parts)
    
    chunks = []
    if rows:
        header_keys = list(rows[0].keys())
        header_row = _format_row(dict(zip(header_keys, header_keys)), column_types)
        
        rows_per_chunk = 50
        chunk_idx = 0
        for i in range(0, len(rows), rows_per_chunk):
            chunk_rows = rows[i:i + rows_per_chunk]
            
            chunk_text_parts = [header_row]
            for row in chunk_rows:
                chunk_text_parts.append(_format_row(row, column_types))
            
            chunk_text = "\n".join(chunk_text_parts)
            word_count = len(chunk_text.split())
            
            chunks.append({
                "index": chunk_idx,
                "text": chunk_text,
                "source_page": None,
                "source_section": None,
                "has_table": False,
                "word_count": word_count,
            })
            chunk_idx += 1
    
    # Note: filtering now handled in main.py after overlap
    # chunks = _filter_small_chunks(chunks)
    
    metadata = {
        "rows": len(rows),
        "columns": header,
        "delimiter": delimiter,
        "column_types": column_types,
        "numeric_summary": numeric_summary,
        "date_range": date_range,
    }
    
    return full_text, metadata, chunks


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        file_path = Path(sys.argv[1])
    else:
        file_path = Path("test_data/sample_products.csv")
    
    text, meta, chunks = parse_csv(file_path)
    
    print(f"=== CSV Parser Test: {file_path.name} ===")
    print(f"Total rows: {meta['rows']}")
    print(f"Columns: {meta['columns']}")
    print(f"Column types: {meta['column_types']}")
    print(f"Chunks after filtering: {len(chunks)}")
    print()
    for i, chunk in enumerate(chunks):
        lines = chunk["text"].split("\n")
        print(f"Chunk {i}: {chunk['word_count']} words")
        print(f"  First line: {lines[0] if lines else '(empty)'}")
        print(f"  Last line: {lines[-1] if lines else '(empty)'}")
        print()
