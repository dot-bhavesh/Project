
"""
search_engine.py — Phase 2 Offline NCERT Search Engine (SQLite FTS5).

Queries the `pages` FTS5 virtual table in `ncert.db` using BM25 ranking,
safe query sanitization, and snippet extraction.
"""

from __future__ import annotations

import os
import re
import sqlite3
import tempfile
from typing import Any

DEFAULT_DB_PATH = "ncert.db"
_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_]+")


# Compatibility functions required by solver.py

def _extract_meaningful_tokens(text):
    return [
        t.lower()
        for t in _TOKEN_PATTERN.findall(text or "")
        if len(t) > 1
    ]


def normalize_typos(text):
    return (text or "").lower()


def _sanitize_fts_query(query: str) -> str:
    """
    Convert raw user input (including formulas or punctuation like ?, +, =, -)
    into a safe FTS5 MATCH expression of quoted literal tokens.

    Returns an empty string if no searchable tokens remain.
    """
    if not query or not query.strip():
        return ""

    tokens = _TOKEN_PATTERN.findall(query)

    if not tokens:
        return ""

    # Quote each token so FTS5 operators and symbols
    # are treated as literal search terms.
    return " ".join(f'"{token}"' for token in tokens)


def search_ncert(
    query: str,
    subject: str | None = None,
    limit: int = 5,
    db_path: str = DEFAULT_DB_PATH,
) -> list[dict[str, Any]]:
    """
    Search NCERT pages offline using SQLite FTS5 and BM25 ranking.

    Args:
        query: Search string, topic, or formula mention.
        subject: Optional subject filter.
        limit: Maximum number of results.
        db_path: Path to the SQLite FTS5 database.

    Returns:
        A list of dictionaries containing:
        subject, book_name, pdf_filename, page_num,
        snippet, full_content.
    """

    if limit <= 0:
        return []

    fts_query = _sanitize_fts_query(query)

    if not fts_query:
        return []

    if not os.path.exists(db_path):
        raise FileNotFoundError(
            f"SQLite database not found at: {db_path}"
        )

    # Column order in `pages`:
    # 0: subject
    # 1: book_name
    # 2: pdf_filename
    # 3: page_num
    # 4: content

    sql = """
        SELECT
            subject,
            book_name,
            pdf_filename,
            page_num,
            snippet(pages, 4, '[', ']', '...', 14) AS snippet,
            content AS full_content
        FROM pages
        WHERE pages MATCH ?
    """

    params: list[Any] = [fts_query]

    if subject is not None and subject.strip():
        sql += " AND subject = ? COLLATE NOCASE"
        params.append(subject.strip())

    sql += " ORDER BY bm25(pages) ASC LIMIT ?"
    params.append(limit)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    try:
        cursor = conn.execute(sql, params)
        rows = cursor.fetchall()
    finally:
        conn.close()

    return [
        {
            "subject": row["subject"],
            "book_name": row["book_name"],
            "pdf_filename": row["pdf_filename"],
            "page_num": row["page_num"],
            "snippet": row["snippet"],
            "full_content": row["full_content"],
        }
        for row in rows
    ]


def _create_dummy_ncert_db(db_path: str) -> None:
    """Create a temporary NCERT database with sample entries."""

    sample_pages = [
        (
            "Physics",
            "Physics Part I",
            "keph104.pdf",
            78,
            "Motion in a Plane: For projectile motion launched with speed v0 at angle theta0, "
            "horizontal range R = (v0^2 * sin(2*theta0)) / g and maximum height H = (v0^2 * sin^2(theta0)) / (2*g).",
        ),
        (
            "Physics",
            "Physics Part I",
            "keph103.pdf",
            52,
            "Kinematic equations for uniformly accelerated motion along a straight line: "
            "v = u + at, s = ut + 1/2*a*t^2, and v^2 - u^2 = 2as.",
        ),
        (
            "Chemistry",
            "Chemistry Part I",
            "kech101.pdf",
            18,
            "Mole concept and molar mass: Number of moles n = given mass / molar mass. "
            "At STP, 1 mole of an ideal gas occupies approximately 22.4 L.",
        ),
        (
            "Maths",
            "Mathematics NCERT Class 11",
            "kemh103.pdf",
            64,
            "Trigonometric Functions: Fundamental identity sin^2(x) + cos^2(x) = 1, "
            "and compound angle expansion cos(x + y) = cos(x)cos(y) - sin(x)sin(y).",
        ),
        (
            "Physics",
            "Physics Part II",
            "keph201.pdf",
            115,
            "Mechanical properties of solids: Young's modulus Y = tensile stress / tensile strain. "
            "What happens if stress exceeds the elastic limit? Permanent deformation occurs.",
        ),
    ]

    conn = sqlite3.connect(db_path)

    try:
        conn.execute("DROP TABLE IF EXISTS pages")

        conn.execute(
            """
            CREATE VIRTUAL TABLE pages USING fts5(
                subject,
                book_name,
                pdf_filename,
                page_num UNINDEXED,
                content
            )
            """
        )

        conn.executemany(
            """
            INSERT INTO pages (
                subject,
                book_name,
                pdf_filename,
                page_num,
                content
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            sample_pages,
        )

        conn.commit()

    finally:
        conn.close()


# Smoke tests

if __name__ == "__main__":

    fd, temp_db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    try:
        _create_dummy_ncert_db(temp_db_path)

        print("--- Test 1: Formula & special characters ---")

        results = search_ncert(
            "v = u + at? - sin^2(x) + cos^2(x) = 1",
            db_path=temp_db_path,
        )

        for item in results:
            print(
                f"[{item['subject']} | p.{item['page_num']}] "
                f"{item['book_name']} "
                f"({item['pdf_filename']}) -> {item['snippet']}"
            )

        print("\n--- Test 2: Subject filter (Physics) ---")

        physics_results = search_ncert(
            "range projectile",
            subject="Physics",
            limit=3,
            db_path=temp_db_path,
        )

        assert len(physics_results) >= 1

        assert all(
            r["subject"] == "Physics"
            for r in physics_results
        )

        assert set(physics_results[0].keys()) == {
            "subject",
            "book_name",
            "pdf_filename",
            "page_num",
            "snippet",
            "full_content",
        }

        print(
            f"Found {len(physics_results)} Physics match(es); "
            f"top page: {physics_results[0]['page_num']}"
        )

        print("\n--- Test 3: Punctuation-only query ---")

        empty_results = search_ncert(
            "??? +++ --- ===",
            db_path=temp_db_path,
        )

        assert empty_results == []

        print("Punctuation-only query safely returned [].")

        print("\nAll smoke tests passed.")

    finally:
        if os.path.exists(temp_db_path):
            os.remove(temp_db_path)
