"""
search_engine.py — Offline NCERT Search Engine (SQLite FTS5 + Typo & Concept Ranking).
"""

from __future__ import annotations

import os
import re
import sqlite3
from typing import Any

DEFAULT_DB_PATH = "ncert.db"
_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_]+")
_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
    "how", "in", "into", "is", "it", "of", "on", "or", "that", "the",
    "this", "to", "what", "when", "where", "which", "with", "find",
    "show", "explain", "define", "derive", "give", "tell", "me",
}

_TYPO_MAP: dict[str, str] = {
    "dimention": "dimension",
    "dimentions": "dimensions",
    "dimenson": "dimension",
    "veloctiy": "velocity",
    "velocitiy": "velocity",
    "aceleration": "acceleration",
    "accelaration": "acceleration",
    "formla": "formula",
    "formular": "formula",
    "eqaution": "equation",
    "equaton": "equation",
    "projecitle": "projectile",
    "projectle": "projectile",
    "momenutm": "momentum",
    "momemtum": "momentum",
    "thermdynamics": "thermodynamics",
    "gravitaion": "gravitation",
    "oscilations": "oscillations",
    "chemisty": "chemistry",
    "phyics": "physics",
    "chap": "chapter",
    "ch": "chapter",
}

_CONCEPT_EXPANSIONS: dict[str, list[str]] = {
    "dimension": ["dimensional", "formula", "analysis", "mlt"],
    "velocity": ["speed", "displacement", "instantaneous", "average"],
    "flight": ["projectile", "time", "sin", "g"],
    "projectile": ["flight", "range", "height", "trajectory", "sin"],
    "plane": ["projectile", "components", "2d", "velocity"],
    "shm": ["oscillation", "harmonic", "period", "frequency"],
    "mole": ["molar", "mass", "avogadro", "stoichiometry"],
    "momentum": ["impulse", "force", "mass", "velocity"],
    "work": ["energy", "kinetic", "potential", "displacement"],
}


def normalize_typos(query: str) -> str:
    if not query:
        return ""
    out_tokens: list[str] = []
    for tok in _TOKEN_PATTERN.findall(query.lower()):
        fixed = _TYPO_MAP.get(tok, tok)
        out_tokens.append(fixed)
    return " ".join(out_tokens)


def _extract_meaningful_tokens(query: str) -> list[str]:
    norm = normalize_typos(query)
    if not norm:
        return []
    raw_tokens = _TOKEN_PATTERN.findall(norm)
    filtered = [t for t in raw_tokens if len(t) > 1 and t.lower() not in _STOPWORDS]
    if filtered:
        return list(dict.fromkeys(filtered))
    return list(dict.fromkeys(raw_tokens))


def _fts_term(tok: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9_]", "", tok)
    if not clean:
        return ""
    if len(clean) >= 5 and clean.isalpha():
        return f'"{clean}"*'
    return f'"{clean}"'


def _sanitize_fts_query(query: str) -> str:
    tokens = _extract_meaningful_tokens(query)
    if not tokens:
        return ""

    expanded = list(tokens)
    for tok in tokens:
        for extra in _CONCEPT_EXPANSIONS.get(tok.lower(), []):
            if extra.lower() not in {x.lower() for x in expanded}:
                expanded.append(extra)

    main_terms = [_fts_term(t) for t in tokens[:5]]
    main_terms = [m for m in main_terms if m]
    if not main_terms:
        return ""

    and_clause = " AND ".join(main_terms)
    extra_terms = [_fts_term(t) for t in expanded[len(tokens):] if t.lower() not in {x.lower() for x in tokens}]
    extra_terms = [e for e in extra_terms if e]
    if extra_terms:
        or_extras = " OR ".join(extra_terms[:5])
        return f"({and_clause}) OR ({or_extras})"
    return and_clause


def _is_conversion_dump(text: str) -> bool:
    low = (text or "").lower()
    markers = ("0.6213 mi", "1.609 km", "3.281 ft", "0.2248 lbf", "14.7 lbf", "33.8 ft h2o", "231 in3")
    return sum(1 for m in markers if m in low) >= 2


def _score_row(query: str, content: str) -> float:
    q_norm = normalize_typos(query)
    c_low = (content or "").lower()
    if not c_low:
        return 0.0

    tokens = [t.lower() for t in _extract_meaningful_tokens(query)]
    score = 0.0

    if len(q_norm.strip()) >= 4 and q_norm.strip() in c_low:
        score += 6.0

    matched_unique = 0
    for tok in tokens:
        if re.search(rf"\b{re.escape(tok)}", c_low):
            matched_unique += 1
            hits = len(re.findall(rf"\b{re.escape(tok)}", c_low))
            score += min(4.5, 2.0 + 0.8 * hits)

    if tokens:
        score += (matched_unique / len(tokens)) * 4.0

    if _is_conversion_dump(content) and not any(w in q_norm for w in ("convert", "conversion", "acre", "mile", "gallon", "atm")):
        score -= 8.0

    return score


def search_ncert(
    query: str,
    subject: str | None = None,
    limit: int = 5,
    db_path: str = DEFAULT_DB_PATH,
) -> list[dict[str, Any]]:
    if limit <= 0:
        return []

    if not os.path.exists(db_path):
        raise FileNotFoundError(f"SQLite database not found at: {db_path}")

    tokens = _extract_meaningful_tokens(query)
    if not tokens:
        return []

    strict_query = _sanitize_fts_query(query)
    broad_query = " OR ".join(_fts_term(t) for t in tokens[:6] if _fts_term(t))

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        seen_keys: set[tuple[Any, ...]] = set()
        candidates: list[sqlite3.Row] = []

        for expr in (strict_query, broad_query):
            if not expr:
                continue
            sql = """
                SELECT
                    subject,
                    book_name,
                    pdf_filename,
                    page_num,
                    snippet(pages, 4, '', '', '...', 18) AS snippet,
                    content AS full_content
                FROM pages
                WHERE pages MATCH ?
            """
            params: list[Any] = [expr]
            if subject is not None and subject.strip() and subject.strip().lower() != "all":
                sql += " AND subject = ? COLLATE NOCASE"
                params.append(subject.strip())
            sql += " ORDER BY bm25(pages) ASC LIMIT ?"
            params.append(max(limit * 4, 16))

            rows = conn.execute(sql, params).fetchall()
            for r in rows:
                key = (r["subject"], r["book_name"], r["pdf_filename"], r["page_num"])
                if key not in seen_keys:
                    seen_keys.add(key)
                    candidates.append(r)
            if len(candidates) >= limit * 2:
                break
    finally:
        conn.close()

    ranked = sorted(
        candidates,
        key=lambda r: _score_row(query, r["full_content"] or ""),
        reverse=True,
    )

    return [
        {
            "subject": row["subject"],
            "book_name": row["book_name"],
            "pdf_filename": row["pdf_filename"],
            "page_num": row["page_num"],
            "snippet": row["snippet"],
            "full_content": row["full_content"],
        }
        for row in ranked[:limit]
    ]
