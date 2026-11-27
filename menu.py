from __future__ import annotations

import re
import select
import sqlite3
import subprocess
import sys
import termios
import tty
from pathlib import Path

from search_engine import DEFAULT_DB_PATH

BANNER = [
    ' ██████╗ ██╗   ██╗ █████╗ ███╗   ██╗    ██╗   ██╗ █████╗ ███╗   ██╗████████╗██████╗  █████╗ ',
    '██╔════╝ ╚██╗ ██╔╝██╔══██╗████╗  ██║    ╚██╗ ██╔╝██╔══██╗████╗  ██║╚══██╔══╝██╔══██╗██╔══██╗',
    '██║  ███╗ ╚████╔╝ ███████║██╔██╗ ██║     ╚████╔╝ ███████║██╔██╗ ██║   ██║   ██████╔╝███████║',
    '██║   ██║  ╚██╔╝  ██╔══██║██║╚██╗██║      ╚██╔╝  ██╔══██║██║╚██╗██║   ██║   ██╔══██╗██╔══██║',
    '╚██████╔╝   ██║   ██║  ██║██║ ╚████║       ██║   ██║  ██║██║ ╚████║   ██║   ██║  ██║██║  ██║',
    ' ╚═════╝    ╚═╝   ╚═╝  ╚═╝╚═╝  ╚═══╝       ╚═╝   ╚═╝  ╚═╝╚═╝  ╚═══╝   ╚═╝   ╚═╝  ╚═╝╚═╝  ╚═╝',
]


def _palette() -> dict[str, str]:
    return {
        "banner": "\x1b[1;36m",
        "title": "\x1b[1;35m",
        "sub": "\x1b[2;37m",
        "rule": "\x1b[90m",
        "active": "\x1b[1;32m",
        "item": "\x1b[37m",
        "search": "\x1b[1;33m",
        "hint": "\x1b[2m",
        "rst": "\x1b[0m",
    }


def _read_key() -> str:
    tty_in = None
    try:
        if sys.stdin.isatty():
            stream = sys.stdin
        else:
            tty_in = open("/dev/tty", "r", encoding="utf-8", errors="ignore")
            stream = tty_in
        fd = stream.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = stream.read(1)
            if not ch:
                return "q"
            if ch == "\x03":
                return "q"
            if ch in ("\r", "\n"):
                return "ENTER"
            if ch in ("\x7f", "\x08"):
                return "BACKSPACE"
            if ch == "\x1b":
                # Drain full escape sequence (e.g. \x1b[A, \x1bOA, \x1b[1;5A)
                seq = ""
                while select.select([stream], [], [], 0.08)[0]:
                    nxt = stream.read(1)
                    if not nxt:
                        break
                    seq += nxt
                    if len(seq) >= 2 and (nxt.isalpha() or nxt == "~"):
                        break
                if seq.endswith("A"):
                    return "UP"
                if seq.endswith("B"):
                    return "DOWN"
                if seq.endswith("C"):
                    return "RIGHT"
                if seq.endswith("D"):
                    return "LEFT"
                # Avoid accidental exit on stray terminal escape sequences
                return "IGNORE"
            return ch
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
    except (OSError, termios.error):
        line = sys.stdin.readline()
        if not line:
            return "q"
        stripped = line.strip()
        if stripped == "":
            return "ENTER"
        return stripped[0]
    finally:
        if tty_in is not None:
            tty_in.close()

def _list_subjects(db_path: Path) -> list[str]:
    db_path = Path(db_path)
    if not db_path.exists():
        return []
    conn = sqlite3.connect(str(db_path))
    try:
        for tbl in ("pages", "chunks"):
            try:
                rows = conn.execute(
                    f"SELECT DISTINCT subject FROM {tbl} WHERE subject IS NOT NULL AND TRIM(subject) != '' ORDER BY subject"
                ).fetchall()
                if rows:
                    return [str(r[0]) for r in rows]
            except sqlite3.Error:
                continue
        return []
    finally:
        conn.close()


def _list_chapters(db_path: Path, subject: str | None) -> list[tuple[str, int]]:
    db_path = Path(db_path)
    if not db_path.exists():
        return []
    conn = sqlite3.connect(str(db_path))
    try:
        # Prefer `pages` table (pdf_filename + page_num)
        try:
            if subject and subject.lower() != "all":
                rows = conn.execute(
                    "SELECT pdf_filename, MIN(page_num) FROM pages WHERE LOWER(subject) = LOWER(?) AND pdf_filename IS NOT NULL AND TRIM(pdf_filename) != '' GROUP BY pdf_filename ORDER BY MIN(page_num), pdf_filename",
                    (subject,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT pdf_filename, MIN(page_num) FROM pages WHERE pdf_filename IS NOT NULL AND TRIM(pdf_filename) != '' GROUP BY pdf_filename ORDER BY MIN(page_num), pdf_filename",
                    (),
                ).fetchall()
            if rows:
                return [(str(r[0]), int(r[1] or 1)) for r in rows]
        except sqlite3.Error:
            pass

        # Fallback to `chunks` table if present
        try:
            if subject and subject.lower() != "all":
                rows = conn.execute(
                    "SELECT chapter, MIN(page) FROM chunks WHERE LOWER(subject) = LOWER(?) AND chapter IS NOT NULL AND TRIM(chapter) != '' GROUP BY chapter ORDER BY MIN(page), chapter",
                    (subject,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT chapter, MIN(page) FROM chunks WHERE chapter IS NOT NULL AND TRIM(chapter) != '' GROUP BY chapter ORDER BY MIN(page), chapter",
                    (),
                ).fetchall()
            return [(str(r[0]), int(r[1] or 1)) for r in rows]
        except sqlite3.Error:
            return []
    finally:
        conn.close()


_PUA_RE = re.compile(r"[\uE000-\uF8FF\U000F0000-\U000FFFFD\U00100000-\U0010FFFD]")
_WORD_MAP = {
    "ONE": "1", "TWO": "2", "THREE": "3", "FOUR": "4", "FIVE": "5",
    "SIX": "6", "SEVEN": "7", "EIGHT": "8", "NINE": "9", "TEN": "10",
}
_KNOWN_TITLES = {
    "keph101": "Ch 1: Units and Measurements",
    "keph102": "Ch 2: Motion in a Straight Line",
    "keph103": "Ch 3: Motion in a Plane",
    "keph104": "Ch 4: Laws of Motion",
    "keph105": "Ch 5: Work, Energy and Power",
    "keph106": "Ch 6: System of Particles and Rotational Motion",
    "keph107": "Ch 7: Gravitation",
    "keph201": "Ch 8: Mechanical Properties of Solids",
    "keph202": "Ch 9: Mechanical Properties of Fluids",
    "keph203": "Ch 10: Thermal Properties of Matter",
    "keph204": "Ch 11: Thermodynamics",
    "keph205": "Ch 12: Kinetic Theory",
    "keph206": "Ch 13: Oscillations",
    "keph207": "Ch 14: Waves",
    "keph1a1": "Appendix / Answers (Part I)",
    "keph1an": "Answers / Notes (Part I)",
    "keph1ps": "Problem Supplement / Summary",
}


def _local_clean_text(t: str) -> str:
    return " ".join(_PUA_RE.sub(" ", t or "").split())

def _clean_chapter_label(pdf_filename: str, page_text: str | None) -> str:
    stem = Path(pdf_filename).stem.lower()
    if stem in _KNOWN_TITLES:
        return _KNOWN_TITLES[stem]
    if isinstance(page_text, str) and page_text.strip():
        cleaned = _local_clean_text(_PUA_RE.sub(" ", page_text))
        m = re.search(r"\bCHAPTER\s+(ONE|TWO|THREE|FOUR|FIVE|SIX|SEVEN|EIGHT|NINE|TEN|\d+)\b(?:\s+([A-Z][A-Za-z0-9 ,\-]{2,48}))?", cleaned, re.IGNORECASE)
        if m:
            num = _WORD_MAP.get(m.group(1).upper(), m.group(1))
            raw_title = (m.group(2) or "").strip()
            raw_title = re.sub(r"\s+\d+$", "", raw_title)
            raw_title = re.split(r"\s+(?:1\.1|2\.1|3\.1|4\.1|5\.1|6\.1|7\.1|LEARNING OBJECTIVES|SUMMARY|EXERCISES)\b", raw_title, maxsplit=1)[0].strip(" ,-")
            words = raw_title.split()
            if len(words) > 6 and words[-1].isupper() and len(words[-1]) <= 3:
                raw_title = " ".join(words[:-1])
            title_cased = raw_title.title() if raw_title.isupper() else raw_title
            return f"Ch {num}: {title_cased}" if title_cased else f"Chapter {num}"
    return Path(pdf_filename).stem


def _find_pdf_file(base_dir: Path, chapter_or_pdf: str | None) -> Path | None:
    if not chapter_or_pdf:
        return None
    raw = str(chapter_or_pdf).strip()
    direct = Path(raw)
    if direct.is_file():
        return direct
    for candidate_root in (base_dir, base_dir / "ncert_books", base_dir / "books", base_dir / "pdfs"):
        if not candidate_root.exists():
            continue
        exact = candidate_root / raw
        if exact.is_file():
            return exact
        for p in candidate_root.rglob("*.pdf"):
            if p.name.lower() == raw.lower() or p.stem.lower() == Path(raw).stem.lower():
                return p
    return None


def _open_in_viewer(db_path: Path, subject: str | None, chapter: str | None, page: int, query: str = "") -> None:
    db_path = Path(db_path).resolve()
    project_dir = Path(__file__).resolve().parent
    pdf_path = _find_pdf_file(project_dir, chapter)

    # First let main.py run if it supports --chapter / --page
    hp = subprocess.run(
        [sys.executable, str(project_dir / "main.py"), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    help_text = (hp.stdout or "") + (hp.stderr or "")
    if "--chapter" in help_text and "--page" in help_text:
        cmd = [
            sys.executable,
            str(project_dir / "main.py"),
            "--db",
            str(db_path),
            "--subject",
            subject or "All",
            "--chapter",
            chapter or "",
            "--page",
            str(max(1, int(page or 1))),
        ]
        if query and "--query" in help_text:
            cmd += ["--query", query]
        subprocess.run(cmd, cwd=str(project_dir), check=False)
        return

    # Direct fallback: launch zathura on the resolved PDF at the requested page
    if pdf_path and pdf_path.is_file():
        pg = max(1, int(page or 1))
        try:
            subprocess.Popen(
                ["zathura", str(pdf_path), "-P", str(pg)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            sys.stdout.write(f"\n  Opened {pdf_path.name} at page {pg} in Zathura.\n")
            sys.stdout.flush()
        except FileNotFoundError:
            sys.stdout.write(f"\n  Zathura not found; PDF located at: {pdf_path} (p.{pg})\n")
            sys.stdout.flush()
    else:
        sys.stdout.write(f"\n  Could not locate PDF file for: {chapter}\n")
        sys.stdout.flush()

def _launch_doubt_solver(db_path: Path, subject: str = "All") -> None:
    db_path = Path(db_path)
    sys.stdout.write("\x1b[2J\x1b[H")
    sys.stdout.flush()

    help_proc = subprocess.run(
        [sys.executable, "main.py", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    help_text = (help_proc.stdout or "") + (help_proc.stderr or "")

    cmd = [sys.executable, "main.py"]
    if "--db" in help_text and db_path.exists():
        cmd += ["--db", str(db_path)]
    if subject and subject != "All" and "--subject" in help_text:
        cmd += ["--subject", subject]

    tty_in = None
    try:
        if sys.stdin.isatty():
            in_stream = sys.stdin
        else:
            tty_in = open("/dev/tty", "r+", encoding="utf-8", errors="ignore")
            in_stream = tty_in

        try:
            termios.tcflush(in_stream.fileno(), termios.TCIFLUSH)
        except (OSError, termios.error):
            pass

        try:
            proc = subprocess.run(cmd, stdin=in_stream, check=False)
        except KeyboardInterrupt:
            return
        if proc.returncode != 0:
            sys.stdout.write(f"\n[Doubt Solver exited with status {proc.returncode}] Press Enter to return...\n")
            sys.stdout.flush()
            in_stream.readline()
    finally:
        if tty_in is not None:
            tty_in.close()

def _draw_menu(
    title: str,
    subtitle: str,
    items: list[str],
    cursor: int,
    query: str,
    searching: bool,
    footer_hint: str,
) -> None:
    pad = "  "
    pal = _palette()
    c_banner = pal["banner"]
    c_title = pal["title"]
    c_sub = pal["sub"]
    c_rule = pal["rule"]
    c_active = pal["active"]
    c_item = pal["item"]
    c_search = pal["search"]
    c_hint = pal["hint"]
    rst = pal["rst"]

    sys.stdout.write("\x1b[2J\x1b[H\n")
    for b_line in BANNER:
        sys.stdout.write(f"{pad}{c_banner}{b_line}{rst}\n")
    sys.stdout.write("\n")

    sys.stdout.write(f"{pad}{c_title}{title}{rst}\n")
    sys.stdout.write(f"{pad}{c_sub}{subtitle}{rst}\n")
    if searching or query:
        tag = "JUMP SEARCH (type to filter, Enter to lock, Esc to clear)" if searching else "FILTER ACTIVE (/ to edit, Esc to clear)"
        sys.stdout.write(f"{pad}{c_search}/ {query}{rst} {c_hint}[{tag}]{rst}\n")
    sys.stdout.write(f"{pad}{c_rule}" + ("-" * 66) + f"{rst}\n")
    if not items:
        sys.stdout.write(f"{pad}  {c_search}No matching items. Press Esc to clear filter.{rst}\n")
    else:
        for idx, label in enumerate(items):
            if idx == cursor:
                sys.stdout.write(f"{pad}  {c_active}> {label}{rst}\n")
            else:
                sys.stdout.write(f"{pad}    {c_item}{label}{rst}\n")
    sys.stdout.write(f"{pad}{c_rule}" + ("-" * 66) + f"{rst}\n")
    sys.stdout.write(f"{pad}{c_hint}{footer_hint}{rst}\n")
    sys.stdout.flush()


def _select_from_list(
    title: str,
    subtitle: str,
    labels: list[str],
    footer_hint: str = "[j/k or Up/Down] Move  [/] Jump Search  [Enter] Select  [q/Esc] Back",
) -> int | None:
    if not labels:
        return None
    cursor = 0
    query = ""
    searching = False

    while True:
        if query:
            q_low = query.lower()
            filtered = [(i, lbl) for i, lbl in enumerate(labels) if q_low in lbl.lower()]
        else:
            filtered = list(enumerate(labels))

        if filtered:
            cursor = max(0, min(cursor, len(filtered) - 1))
        else:
            cursor = 0

        _draw_menu(
            title=title,
            subtitle=subtitle,
            items=[lbl for _, lbl in filtered],
            cursor=cursor,
            query=query,
            searching=searching,
            footer_hint=footer_hint,
        )

        key = _read_key()
        if searching:
            if key == "ESC":
                query = ""
                searching = False
                cursor = 0
            elif key == "ENTER":
                searching = False
            elif key == "BACKSPACE":
                query = query[:-1]
            elif key == "UP":
                if filtered:
                    cursor = (cursor - 1) % len(filtered)
            elif key == "DOWN":
                if filtered:
                    cursor = (cursor + 1) % len(filtered)
            elif isinstance(key, str) and len(key) == 1 and key.isprintable():
                query += key
            continue

        if key in ("q", "Q"):
            return None
        if key == "/":
            searching = True
        elif key in ("j", "DOWN"):
            if filtered:
                cursor = (cursor + 1) % len(filtered)
        elif key in ("k", "UP"):
            if filtered:
                cursor = (cursor - 1) % len(filtered)
        elif key == "ENTER":
            if filtered:
                return filtered[cursor][0]


def _prompt_direct_topic(db_path: Path) -> None:
    db_path = Path(db_path)
    sys.stdout.write("\x1b[2J\x1b[H\n")
    for b_line in BANNER:
        sys.stdout.write(f"  \x1b[1;36m{b_line}\x1b[0m\n")
    sys.stdout.write("\n  \x1b[1;35mDIRECT TOPIC & FORMULA SEARCH\x1b[0m\n")
    sys.stdout.write("  \x1b[2;37mType a topic or formula and press Enter (blank + Enter to return)\x1b[0m\n\n")
    sys.stdout.flush()

    tty_io = None
    try:
        if sys.stdin.isatty():
            in_s = sys.stdin
        else:
            tty_io = open("/dev/tty", "r+", encoding="utf-8", errors="ignore")
            in_s = tty_io

        # Ensure normal canonical echo mode while typing the topic
        try:
            fd = in_s.fileno()
            attrs = termios.tcgetattr(fd)
            attrs[3] = attrs[3] | termios.ICANON | termios.ECHO
            termios.tcsetattr(fd, termios.TCSADRAIN, attrs)
            termios.tcflush(fd, termios.TCIFLUSH)
        except (OSError, termios.error):
            pass

        sys.stdout.write("  Topic > ")
        sys.stdout.flush()
        topic = in_s.readline()
        if not topic:
            return
        topic = topic.strip()
        if not topic:
            return

        cmd = [sys.executable, "main.py"]
        if True and db_path.exists():
            cmd += ["--db", str(db_path)]
        if False:
            cmd += ["--query", topic]
        if False:
            cmd += ["--auto-open"]

        res = subprocess.run(cmd, stdin=in_s, check=False)
        if res.returncode != 0:
            sys.stdout.write(f"\n[Search exited with code {res.returncode}] Press Enter to return...\n")
            sys.stdout.flush()
            in_s.readline()
    except (EOFError, KeyboardInterrupt):
        return
    finally:
        if tty_io is not None:
            tty_io.close()

def _browse_chapters(db_path: Path, subject: str | None) -> None:
    chapters = _list_chapters(db_path, subject)
    if not chapters:
        return
    labels = [_clean_chapter_label(ch, pg) for ch, pg in chapters]
    heading = f"{subject.upper()} CHAPTERS" if subject else "ALL SUBJECTS — CHAPTERS"
    while True:
        pick = _select_from_list(
            title=heading,
            subtitle=f"DB: {db_path.name}  |  Select chapter to open in Zathura",
            labels=labels,
        )
        if pick is None:
            return
        ch_name, pg_num = chapters[pick]
        _open_in_viewer(db_path, subject, ch_name, pg_num)


def run_menu(db_path: Path = DEFAULT_DB_PATH) -> None:
    subjects = _list_subjects(db_path)

    while True:
        hub_items = [
            "NCERT Doubt Solver (Interactive CLI)",
            "Direct Topic & Formula Search",
            "Browse All Chapters",
        ] + [f"Subject: {s}" for s in subjects]

        choice = _select_from_list(
            title="GYAN YANTRA — MAIN HUB",
            subtitle=f"Class 11 Exhibition  |  DB: {db_path.name}  |  Offline NCERT Workbench",
            labels=hub_items,
            footer_hint="[j/k or Up/Down] Move  [/] Jump Search  [Enter] Open  [q/Esc] Exit",
        )

        # Pressing q or Esc on the main Gyan Yantra hub exits cleanly
        if choice is None:
            sys.stdout.write("\x1b[2J\x1b[H")
            sys.stdout.flush()
            return

        if choice == 0:
            _launch_doubt_solver(db_path, subject="All")
        elif choice == 1:
            _prompt_direct_topic(db_path)
        elif choice == 2:
            _browse_chapters(db_path, subject=None)
        else:
            subj = subjects[choice - 3]
            _browse_chapters(db_path, subject=subj)


if __name__ == "__main__":
    try:
        arg_db = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(DEFAULT_DB_PATH)
        run_menu(arg_db)
    except KeyboardInterrupt:
        sys.stdout.write("\n")
        sys.stdout.flush()


def run_yazi_menu(db_path: Path = DEFAULT_DB_PATH, subject: str | None = None, *args, **kwargs):
    """Compatibility entry point imported by main.py."""
    target_db = Path(db_path) if db_path else Path(DEFAULT_DB_PATH)
    if subject and subject != "All":
        _browse_chapters(target_db, subject=subject)
        return None
    return run_menu(target_db)
