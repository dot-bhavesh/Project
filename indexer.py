from __future__ import annotations

import argparse
import logging
import os
import sqlite3
import sys
import time
from pathlib import Path
from typing import Iterable

logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("indexer")

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_BOOKS_DIR = PROJECT_ROOT / "ncert_books"
DEFAULT_DB_PATH = PROJECT_ROOT / "ncert.db"

DIR_META: dict[str, tuple[str, str]] = {
    "physics_I": ("Physics", "Physics Part I"),
    "physics_II": ("Physics", "Physics Part II"),
    "chemistry_I": ("Chemistry", "Chemistry Part I"),
    "chemistry_II": ("Chemistry", "Chemistry Part II"),
    "mathematics": ("Maths", "Mathematics NCERT Class 11"),
}

PREFIX_META: dict[str, tuple[str, str]] = {
    "keph1": ("Physics", "Physics Part I"),
    "keph2": ("Physics", "Physics Part II"),
    "kech1": ("Chemistry", "Chemistry Part I"),
    "kech2": ("Chemistry", "Chemistry Part II"),
    "kemh1": ("Maths", "Mathematics NCERT Class 11"),
}


def _import_pdf_reader():
    """Import PdfReader from pypdf with a helpful installation message."""
    try:
        from pypdf import PdfReader  # type: ignore[import-not-found]
        return PdfReader
    except ImportError as exc:
        raise RuntimeError(
            "Missing dependency 'pypdf'. Install it in your terminal with: pip install pypdf"
        ) from exc


def infer_subject_and_book(pdf_path: Path, books_dir: Path = DEFAULT_BOOKS_DIR) -> tuple[str, str]:
    """Infer (subject, book_name) from parent folder name or NCERT filename prefix."""
    try:
        rel_parts = pdf_path.resolve().relative_to(books_dir.resolve()).parts
        for part in rel_parts[:-1]:
            if part in DIR_META:
                return DIR_META[part]
    except ValueError:
        pass

    stem_lower = pdf_path.stem.lower()
    for prefix, meta in PREFIX_META.items():
        if stem_lower.startswith(prefix):
            return meta

    return ("General", pdf_path.stem)


def iter_pdf_files(books_dir: Path = DEFAULT_BOOKS_DIR) -> list[Path]:
    """Find all .pdf files under books_dir sorted deterministically."""
    if not books_dir.is_dir():
        return []
    return sorted(
        p.resolve()
        for p in books_dir.rglob("*")
        if p.is_file() and p.suffix.lower() == ".pdf"
    )


def extract_pdf_pages(pdf_path: Path, books_dir: Path = DEFAULT_BOOKS_DIR) -> list[tuple[str, str, str, int, str]]:
    """
    Extract non-empty text from each page of a PDF.

    Returns rows matching `pages(subject, book_name, pdf_filename, page_num, content)`.
    """
    PdfReader = _import_pdf_reader()
    subject, book_name = infer_subject_and_book(pdf_path, books_dir=books_dir)
    rows: list[tuple[str, str, str, int, str]] = []

    try:
        reader = PdfReader(str(pdf_path))
    except Exception as exc:
        logger.warning("Skipping unreadable PDF '%s': %s", pdf_path.name, exc)
        return rows

    total_pages = len(reader.pages)
    for idx in range(total_pages):
        page_num = idx + 1
        try:
            raw_text = reader.pages[idx].extract_text() or ""
        except Exception as exc:
            logger.warning("Failed to extract page %d of '%s': %s", page_num, pdf_path.name, exc)
            continue

        cleaned = " ".join(raw_text.split())
        if cleaned:
            rows.append((subject, book_name, pdf_path.name, page_num, cleaned))

    return rows


def init_fts_db(db_path: Path = DEFAULT_DB_PATH, rebuild: bool = False) -> sqlite3.Connection:
    """Create SQLite connection and ensure the FTS5 `pages` virtual table exists."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    if rebuild:
        conn.execute("DROP TABLE IF EXISTS pages")

    conn.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS pages USING fts5(
            subject,
            book_name,
            pdf_filename,
            page_num UNINDEXED,
            content
        )
        """
    )
    conn.commit()
    return conn


def build_index(
    books_dir: Path = DEFAULT_BOOKS_DIR,
    db_path: Path = DEFAULT_DB_PATH,
    rebuild: bool = True,
) -> dict[str, int]:
    """
    Index all PDFs under `books_dir` into SQLite FTS5 at `db_path`.

    Returns summary counts: pdfs_processed, pages_indexed, elapsed_ms.
    """
    start = time.perf_counter()
    pdf_files = iter_pdf_files(books_dir=books_dir)

    if not pdf_files:
        logger.warning("No PDF files found in '%s'.", books_dir)
        conn = init_fts_db(db_path=db_path, rebuild=rebuild)
        conn.close()
        return {
            "pdfs_processed": 0,
            "pages_indexed": 0,
            "elapsed_ms": int((time.perf_counter() - start) * 1000),
        }

    conn = init_fts_db(db_path=db_path, rebuild=rebuild)
    total_pages_indexed = 0
    pdfs_processed = 0

    try:
        conn.execute("BEGIN")
        for pdf_path in pdf_files:
            page_rows = extract_pdf_pages(pdf_path, books_dir=books_dir)
            if not page_rows:
                logger.info("No extractable text found in '%s'.", pdf_path.name)
                pdfs_processed += 1
                continue

            if not rebuild:
                conn.execute("DELETE FROM pages WHERE pdf_filename = ?", (pdf_path.name,))

            conn.executemany(
                """
                INSERT INTO pages (subject, book_name, pdf_filename, page_num, content)
                VALUES (?, ?, ?, ?, ?)
                """,
                page_rows,
            )
            total_pages_indexed += len(page_rows)
            pdfs_processed += 1
            logger.info("Indexed '%s' (%d pages).", pdf_path.name, len(page_rows))

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    elapsed_ms = int((time.perf_counter() - start) * 1000)
    return {
        "pdfs_processed": pdfs_processed,
        "pages_indexed": total_pages_indexed,
        "elapsed_ms": elapsed_ms,
    }


def _parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Index Class 11 NCERT PDFs into an offline SQLite FTS5 database."
    )
    parser.add_argument(
        "--books-dir",
        type=Path,
        default=DEFAULT_BOOKS_DIR,
        help=f"Directory containing NCERT PDFs (default: {DEFAULT_BOOKS_DIR})",
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=DEFAULT_DB_PATH,
        help=f"Output SQLite database path (default: {DEFAULT_DB_PATH})",
    )
    parser.add_argument(
        "--append",
        action="store_true",
        help="Update/append per PDF instead of dropping and rebuilding the `pages` table.",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


if __name__ == "__main__":
    args = _parse_args()
    try:
        stats = build_index(
            books_dir=args.books_dir,
            db_path=args.db_path,
            rebuild=not args.append,
        )
        print(
            f"Done: {stats['pdfs_processed']} PDF(s), {stats['pages_indexed']} page(s) "
            f"indexed in {stats['elapsed_ms']} ms -> {args.db_path}"
        )
    except (RuntimeError, sqlite3.Error, OSError) as exc:
        logger.error("Indexing failed: %s", exc)
        sys.exit(1)
