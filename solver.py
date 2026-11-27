from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path
from typing import Any

from search_engine import DEFAULT_DB_PATH, _extract_meaningful_tokens, normalize_typos, search_ncert

_PUA = re.compile(r"[\uE000-\uF8FF\U000F0000-\U000FFFFD\U00100000-\U0010FFFD]")
_SENT = re.compile(r"(?<=[.!?])\s+")
_WORD = re.compile(r"[A-Za-z0-9_]+")
_EQ_PAT = re.compile(
    r"([A-Za-z][A-Za-z0-9_]*(?:\s*\([^)]+\))?\s*=\s*[^.;\n]{2,95})"
)
_FORMULA_HINTS = re.compile(
    r"(=|sin|cos|tan|cot|sec|csc|log|ln|lim|d/dt|d/dx|∫|∑|Δ|∆|\^)",
    re.I,
)
_GARBLED_EQ = re.compile(r"\b[a-z](?:\s+[a-z]){3,}\s*=")

NCERT_PDF_LABELS: dict[str, str] = {
    "keph101.pdf": "Units and Measurements",
    "keph102.pdf": "Motion in a Straight Line",
    "keph103.pdf": "Motion in a Plane",
    "keph104.pdf": "Laws of Motion",
    "keph105.pdf": "Work, Energy and Power",
    "keph106.pdf": "System of Particles and Rotational Motion",
    "keph107.pdf": "Gravitation",
    "keph201.pdf": "Mechanical Properties of Solids",
    "keph202.pdf": "Mechanical Properties of Fluids",
    "keph203.pdf": "Thermal Properties of Matter",
    "keph204.pdf": "Thermodynamics",
    "keph205.pdf": "Kinetic Theory",
    "keph206.pdf": "Oscillations",
    "keph207.pdf": "Waves",
    "keph1a1.pdf": "Appendix / Answers (Part I)",
    "keph1an.pdf": "Answers / Notes (Part I)",
    "keph1ps.pdf": "Problem Supplement / Summary",
}


def format_pdf_display_name(pdf_filename: str | None, fallback_title: str = "") -> str:
    raw = (pdf_filename or "").strip()
    base = Path(raw).name.lower() if raw else ""
    if base in NCERT_PDF_LABELS:
        return NCERT_PDF_LABELS[base]
    if fallback_title and fallback_title.strip():
        return fallback_title.strip()
    if not raw:
        return "NCERT Chapter"
    stem = Path(base).stem
    stem = re.sub(r"[_-]+", " ", stem).strip()
    return stem.title() if stem else raw


def clean_ncert_text(text: str) -> str:
    if not text:
        return ""
    s = _PUA.sub(" ", text)
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"\(\s+", "(", s)
    s = re.sub(r"\s+\)", ")", s)
    s = re.sub(r"\s*/\s*", " / ", s)
    s = re.sub(r"\s+([.,;:!?])", r"\1", s)
    s = re.sub(r"\s+:", ":", s)
    return s.strip()


def _clean_snippet(snip: str) -> str:
    s = clean_ncert_text(snip or "")
    s = s.replace("[", "").replace("]", "")
    s = re.sub(r"\s*\.\.\.\s*", " … ", s)
    return s.strip(" …")


def _search_any_keyword(query: str, subject: str | None, limit: int, db_path: str) -> list[dict[str, Any]]:
    if limit <= 0 or not os.path.exists(db_path):
        return []
    toks = _extract_meaningful_tokens(query)
    if not toks:
        return []
    or_expr = " OR ".join(f'"{t}"' for t in toks)
    sql = (
        "SELECT subject, book_name, pdf_filename, page_num, "
        "snippet(pages, 4, '', '', '...', 16) AS snippet, content AS full_content "
        "FROM pages WHERE pages MATCH ?"
    )
    params: list[Any] = [or_expr]
    if subject and subject.strip() and subject.strip().lower() != "all":
        sql += " AND subject = ? COLLATE NOCASE"
        params.append(subject.strip())
    sql += " ORDER BY bm25(pages) ASC LIMIT ?"
    params.append(limit)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()
    return [
        {
            "subject": r["subject"],
            "book_name": r["book_name"],
            "pdf_filename": r["pdf_filename"],
            "page_num": r["page_num"],
            "snippet": r["snippet"],
            "full_content": r["full_content"],
        }
        for r in rows
    ]


def _score_sentence(sent: str, qtoks: set[str], phrases: list[str], wants_formula: bool) -> int:
    low = normalize_typos(sent) if "normalize_typos" in globals() else sent.lower()
    words = {t.lower() for t in _WORD.findall(low)}
    ov = len(qtoks & words)
    phrase_hits = sum(1 for p in phrases if p in low)
    if ov == 0:
        return 0

    score = ov * 5 + phrase_hits * 5
    if "=" in sent:
        score += 3 if wants_formula else 1
    elif _FORMULA_HINTS.search(sent) and wants_formula:
        score += 2

    if any(cue in low for cue in ("defined as", "is called", "is known as", "given by", "dimensions", "formula", "law")):
        score += 2

    if _GARBLED_EQ.search(low) and "=" in low:
        score -= 6

    if len(sent) > 220:
        score -= 2
    return score


def _extract_key_sentences(text: str, query: str, max_sentences: int = 3) -> list[str]:
    cleaned = clean_ncert_text(text)
    if not cleaned:
        return []
    q_low = (query or "").lower()
    wants_formula = any(w in q_low for w in ("formula", "equation", "expression", "derive", "calculate", "value"))
    qtoks = {t.lower() for t in _extract_meaningful_tokens(query)}

    # Extract 2- and 3-word phrases from the query for general phrase matching
    qwords = [t.lower() for t in _WORD.findall(q_low) if len(t) > 1]
    phrases = [
        " ".join(qwords[i : i + n])
        for n in (3, 2)
        for i in range(max(0, len(qwords) - n + 1))
    ]

    sents = [s.strip() for s in _SENT.split(cleaned) if len(s.strip()) >= 14]
    scored: list[tuple[int, int, str]] = []
    for idx, sc in enumerate(sents):
        pts = _score_sentence(sc, qtoks, phrases, wants_formula)
        if pts > 0:
            scored.append((pts, -idx, sc))

    scored.sort(reverse=True)
    picked: list[str] = []
    for _, _, sc in scored:
        if sc not in picked:
            picked.append(sc)
        if len(picked) >= max_sentences:
            break

    return picked if picked else sents[:2]


_PROSE_WORDS_RE = re.compile(
    r"\b(where|which|when|what|is|are|the|this|that|with|from|into|given|called|known|velocity|mass|body|time|distance|height|range|angle|projectile|motion|chapter|section)\b",
    re.I,
)
_DIM_EXPR_RE = re.compile(r"\[[^\]]*[MLT][^\]]*\]")


def _looks_like_real_formula(eq: str) -> bool:
    s = sanitize_formula_display(eq) if "sanitize_formula_display" in globals() else (eq or "").strip()
    if "=" not in s or len(s) < 4 or len(s) > 75:
        return False
    lhs, rhs = s.split("=", 1)
    lhs = lhs.strip()
    rhs = rhs.strip()
    if not lhs or not rhs:
        return False
    # Reject narrative sentences disguised around '='
    if len(_PROSE_WORDS_RE.findall(lhs)) >= 1 or len(_PROSE_WORDS_RE.findall(rhs)) >= 2:
        return False
    # Must contain math operators, dimensional brackets, trig/log, or compact symbolic terms
    has_math = bool(re.search(r"[+\-*/^()\[\]0-9]|sin|cos|tan|log|lim", rhs, re.I))
    if not has_math:
        return False
    if len(rhs.split()) > 10:
        return False
    return True


def _extract_formula_lines(sentences: list[str], query: str = "", max_items: int = 3) -> list[str]:
    qtoks = {t.lower() for t in _extract_meaningful_tokens(query)}
    candidates: list[tuple[int, str]] = []
    seen: set[str] = set()

    for s in sentences:
        # Check dimensional expressions like [L T^-1] or [M L T^-2]
        for dm in _DIM_EXPR_RE.finditer(s):
            d_tok = dm.group(0).strip()
            key = re.sub(r"\s+", "", d_tok.lower())
            if key not in seen:
                seen.add(key)
                rank = 8 if "dim" in " ".join(qtoks) else 4
                candidates.append((rank, d_tok))

        for m in _EQ_PAT.finditer(s):
            eq = m.group(1).strip(" ,;:")
            if not _looks_like_real_formula(eq):
                continue
            key = re.sub(r"\s+", " ", eq.lower())
            if key in seen:
                continue
            seen.add(key)

            eq_words = {t.lower() for t in _WORD.findall(eq)}
            sent_words = {t.lower() for t in _WORD.findall(s)}
            rank = len(qtoks & eq_words) * 6 + len(qtoks & sent_words) * 2
            if _FORMULA_HINTS.search(eq):
                rank += 2
            candidates.append((rank, eq))

    candidates.sort(key=lambda item: item[0], reverse=True)
    return [eq for _, eq in candidates[:max_items]]

def solve_doubt(
    question: str,
    subject: str | None = None,
    limit: int = 3,
    db_path: str = str(DEFAULT_DB_PATH),
) -> dict[str, Any]:
    q = (question or "").strip()
    if not q:
        return {
            "question": question,
            "found": False,
            "summary": "Please enter a topic, formula, or doubt.",
            "formulas": [],
            "primary_source": None,
            "references": [],
        }

    matches = search_ncert(query=q, subject=subject, limit=limit, db_path=db_path)
    if not matches:
        matches = _search_any_keyword(query=q, subject=subject, limit=limit, db_path=db_path)

    if not matches:
        return {
            "question": q,
            "found": False,
            "summary": f"No matching NCERT pages found for '{q}'.",
            "formulas": [],
            "primary_source": None,
            "references": [],
        }

    refs: list[dict[str, Any]] = []
    all_ks: list[str] = []
    for m in matches:
        cf = clean_ncert_text(m.get("full_content", ""))
        cs = _clean_snippet(m.get("snippet", ""))
        ks_list = _extract_key_sentences(cf, q, max_sentences=2)
        for ks in ks_list:
            if ks not in all_ks:
                all_ks.append(ks)
        refs.append(
            {
                "subject": m["subject"],
                "book_name": m["book_name"],
                "pdf_filename": m["pdf_filename"],
                "display_name": format_pdf_display_name(m["pdf_filename"], m.get("book_name") or ""),
                "page_num": m["page_num"],
                "snippet": cs,
                "key_points": ks_list,
            }
        )

    top_points = refs[0]["key_points"] if refs and refs[0]["key_points"] else all_ks[:2]
    summary = "\n  ".join(top_points[:2]) if top_points else refs[0]["snippet"]
    formulas = _extract_formula_lines(all_ks, query=q, max_items=3)
    top = refs[0]
    return {
        "question": q,
        "found": True,
        "summary": summary,
        "formulas": formulas,
        "primary_source": {
            "subject": top["subject"],
            "book_name": top["book_name"],
            "pdf_filename": top["pdf_filename"],
            "display_name": top["display_name"],
            "page_num": top["page_num"],
        },
        "references": refs,
    }
