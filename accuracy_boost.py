from __future__ import annotations

import math
import re
import sqlite3
from pathlib import Path

STOPWORDS = {
    "what", "is", "are", "the", "a", "an", "of", "in", "on", "for", "to",
    "from", "by", "with", "find", "show", "explain", "define", "derive",
    "formula", "equation", "law", "principle", "ncert", "class", "11",
    "doubt", "question", "calculate", "value", "unit", "si"
}

ALIASES = {
    "shm": ["simple harmonic motion", "time period", "angular frequency", "restoring force"],
    "ke": ["kinetic energy", "work energy theorem"],
    "pe": ["potential energy", "conservative force"],
    "newtons second law": ["force", "mass", "acceleration", "dp/dt", "momentum"],
    "newtons first law": ["inertia", "equilibrium"],
    "newtons third law": ["action", "reaction"],
    "boyles law": ["pressure", "volume", "isothermal", "ideal gas"],
    "charles law": ["volume", "temperature", "isobaric", "ideal gas"],
    "ideal gas": ["pv = nrt", "boltzmann", "pressure", "volume", "temperature"],
    "projectile": ["range", "time of flight", "maximum height", "trajectory"],
    "thermodynamics": ["first law", "heat", "internal energy", "work done", "entropy"],
    "mole": ["avogadro", "molar mass", "stoichiometry", "limiting reagent"],
    "hybridisation": ["orbital", "geometry", "vsepr", "sp3", "sp2", "sp"],
    "quantum": ["de broglie", "heisenberg", "bohr", "schrodinger", "wavelength"],
}


def normalize_query(raw: str) -> str:
    text = raw.lower().strip()
    text = re.sub(r"[^a-z0-9\s=+/*^().-]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def expand_terms(raw: str) -> list[str]:
    norm = normalize_query(raw)
    tokens = [t for t in re.split(r"\s+", norm) if t and t not in STOPWORDS and len(t) > 1]
    expanded = list(dict.fromkeys(tokens))
    for alias, extras in ALIASES.items():
        if alias in norm or any(alias == tok for tok in tokens):
            for phrase in extras:
                for w in phrase.lower().split():
                    if w not in STOPWORDS and len(w) > 1 and w not in expanded:
                        expanded.append(w)
    return expanded[:16]


def score_chunk(query: str, text: str, chapter: str = "", subject: str = "") -> float:
    q_norm = normalize_query(query)
    if not q_norm or not text:
        return 0.0
    t_low = text.lower()
    c_low = (chapter or "").lower()
    s_low = (subject or "").lower()

    terms = expand_terms(query)
    score = 0.0

    # Exact phrase match bonus
    if len(q_norm) >= 4 and q_norm in t_low:
        score += 6.0
    if len(q_norm) >= 4 and q_norm in c_low:
        score += 4.5

    # Term coverage & density
    matched_terms = 0
    for term in terms:
        cnt = t_low.count(term)
        if cnt > 0:
            matched_terms += 1
            score += min(3.0, 1.0 + math.log1p(cnt))
        if term in c_low:
            score += 1.5
        if term in s_low:
            score += 0.5

    if terms:
        coverage = matched_terms / len(terms)
        score += coverage * 3.0

    # Boost chunks containing formulas, definitions, or key laws
    if any(sym in text for sym in ("=", "∝", "∆", "Δ", "mol", "m/s", "J", "N", "Pa")):
        score += 0.6
    if any(cue in t_low for cue in ("defined as", "law states", "expression for", "formula", "si unit")):
        score += 0.7

    return round(score, 4)


def best_excerpts(query: str, text: str, max_snippets: int = 2) -> list[str]:
    if not text:
        return []
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if len(s.strip()) > 15]
    if not sentences:
        return [text[:360].strip()]
    ranked = sorted(
        sentences,
        key=lambda s: score_chunk(query, s),
        reverse=True,
    )
    return ranked[:max_snippets]


def search_sqlite_fallback(db_path: Path, query: str, subject: str | None = None, limit: int = 8) -> list[dict]:
    db_path = Path(db_path)
    if not db_path.exists():
        return []
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(chunks)").fetchall()]
        if not cols:
            return []
        text_col = next((c for c in ("content", "text", "body", "chunk") if c in cols), None)
        if not text_col:
            return []
        subj_col = "subject" if "subject" in cols else None
        chap_col = "chapter" if "chapter" in cols else None
        page_col = "page" if "page" in cols else None

        sql = f"SELECT rowid AS _id, * FROM chunks"
        params: list = []
        if subj_col and subject and subject.lower() != "all":
            sql += f" WHERE LOWER({subj_col}) = LOWER(?)"
            params.append(subject)

        rows = conn.execute(sql, params).fetchall()
        scored = []
        for r in rows:
            body = str(r[text_col] or "")
            chap = str(r[chap_col] or "") if chap_col else ""
            subj = str(r[subj_col] or "") if subj_col else (subject or "General")
            page = int(r[page_col] or 1) if page_col and r[page_col] is not None else 1
            sc = score_chunk(query, body, chap, subj)
            if sc > 0:
                scored.append({
                    "score": sc,
                    "subject": subj,
                    "chapter": chap,
                    "page": page,
                    "text": body,
                    "excerpts": best_excerpts(query, body),
                })
        scored.sort(key=lambda item: item["score"], reverse=True)
        return scored[:limit]
    finally:
        conn.close()
