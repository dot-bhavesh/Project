from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("viewer")

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_BOOKS_DIR = PROJECT_ROOT / "ncert_books"


class ViewerError(Exception):
    """Raised when a PDF cannot be opened or a viewer command fails."""


SUBJECT_DIRS: dict[str, Path] = {
    "physics_I": DEFAULT_BOOKS_DIR / "physics_I",
    "physics_II": DEFAULT_BOOKS_DIR / "physics_II",
    "chemistry_I": DEFAULT_BOOKS_DIR / "chemistry_I",
    "chemistry_II": DEFAULT_BOOKS_DIR / "chemistry_II",
    "mathematics": DEFAULT_BOOKS_DIR / "mathematics",
}

PREFIX_TO_DIR_KEY: dict[str, str] = {
    "keph1": "physics_I",
    "keph2": "physics_II",
    "kech1": "chemistry_I",
    "kech2": "chemistry_II",
    "kemh1": "mathematics",
}


def resolve_pdf_path(
    pdf_filename: str | Path,
    books_dir: Path = DEFAULT_BOOKS_DIR,
) -> Path:
    """Resolve a PDF filename or path across cwd, project root, pre-mapped subject folders, and books_dir."""
    candidate = Path(pdf_filename).expanduser()

    search_paths = [
        candidate,
        Path.cwd() / candidate,
        PROJECT_ROOT / candidate,
        books_dir / candidate,
    ]

    # Check pre-mapped subject folder based on NCERT filename prefix (e.g., keph101.pdf -> physics_I)
    stem_lower = candidate.stem.lower()
    for prefix, dir_key in PREFIX_TO_DIR_KEY.items():
        if stem_lower.startswith(prefix):
            mapped_dir = books_dir / dir_key if books_dir != DEFAULT_BOOKS_DIR else SUBJECT_DIRS[dir_key]
            search_paths.append(mapped_dir / candidate.name)
            break

    # Check all pre-mapped subject folders as a fallback
    for dir_key in SUBJECT_DIRS:
        mapped_dir = books_dir / dir_key if books_dir != DEFAULT_BOOKS_DIR else SUBJECT_DIRS[dir_key]
        search_paths.append(mapped_dir / candidate.name)

    search_paths.append(books_dir / candidate.name)

    for path in search_paths:
        if path.is_file():
            return path.resolve()

    if books_dir.is_dir():
        matches = sorted(books_dir.rglob(candidate.name))
        if matches:
            return matches[0].resolve()

    raise ViewerError(
        f"PDF file not found: '{pdf_filename}' (checked cwd, project root, mapped subject folders, and '{books_dir}')."
    )


def _split_i3_horizontal() -> None:
    """Split the active i3wm container horizontally if i3-msg is available."""
    if shutil.which("i3-msg") is None:
        logger.warning("i3-msg not found in PATH; skipping horizontal workspace split.")
        return

    try:
        result = subprocess.run(
            ["i3-msg", "split", "h"],
            capture_output=True,
            text=True,
            check=False,
            timeout=3,
        )
        if result.returncode != 0:
            logger.warning(
                "i3-msg split h exited with code %d: %s",
                result.returncode,
                result.stderr.strip() or result.stdout.strip(),
            )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("Failed to run i3-msg split h: %s", exc)


def open_pdf_page(
    pdf_filename: str | Path,
    page_num: int,
    books_dir: Path = DEFAULT_BOOKS_DIR,
    split_horizontal: bool = True,
) -> subprocess.Popen[bytes]:
    """
    Split the i3wm workspace horizontally (optional) and launch zathura at `page_num`
    without blocking the calling Python process.
    """
    if isinstance(page_num, bool) or not isinstance(page_num, int) or page_num < 1:
        raise ViewerError(f"Invalid page number: {page_num!r}. Expected a positive integer >= 1.")

    if shutil.which("zathura") is None:
        raise ViewerError(
            "zathura is not installed or not in PATH. Install with: sudo apt install zathura zathura-pdf-poppler"
        )

    pdf_path = resolve_pdf_path(pdf_filename=pdf_filename, books_dir=books_dir)

    if split_horizontal:
        _split_i3_horizontal()

    cmd = ["zathura", "-P", str(page_num), str(pdf_path)]

    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        raise ViewerError(f"Failed to launch zathura for '{pdf_path}': {exc}") from exc

    # Brief check in case zathura immediately fails on startup (e.g., bad file or display)
    try:
        early_code = process.wait(timeout=0.15)
        raise ViewerError(
            f"zathura exited immediately with code {early_code} for '{pdf_path}' at page {page_num}."
        )
    except subprocess.TimeoutExpired:
        logger.info("Launched zathura (PID %d) on '%s' at page %d.", process.pid, pdf_path.name, page_num)
        return process


if __name__ == "__main__":
    import sys

    if len(sys.argv) >= 3:
        target_pdf = sys.argv[1]
        try:
            target_page = int(sys.argv[2])
        except ValueError:
            print(f"[ERROR] Page number must be an integer, got '{sys.argv[2]}'.")
            sys.exit(1)
    else:
        # Quick test fallback: create a tiny sample PDF via python if needed or pass args:
        # python3 viewer.py ncert_books/keph101.pdf 12
        sample_pdf = DEFAULT_BOOKS_DIR / "test_sample.pdf"
        if not sample_pdf.exists():
            sample_pdf.parent.mkdir(parents=True, exist_ok=True)
            # Minimal valid single-page PDF bytes for quick local testing
            minimal_pdf = (
                b"%PDF-1.4\n"
                b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
                b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n"
                b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 300 144] "
                b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >> endobj\n"
                b"4 0 obj << /Length 44 >> stream\nBT /F1 18 Tf 30 70 Td (NCERT Viewer Test) Tj ET\nendstream endobj\n"
                b"5 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n"
                b"xref\n0 6\n0000000000 65535 f \n0000000009 00000 n \n0000000058 00000 n \n"
                b"0000000115 00000 n \n0000000241 00000 n \n0000000334 00000 n \n"
                b"trailer << /Size 6 /Root 1 0 R >>\nstartxref\n403\n%%EOF\n"
            )
            sample_pdf.write_bytes(minimal_pdf)
        target_pdf = str(sample_pdf)
        target_page = 1

    try:
        proc = open_pdf_page(target_pdf, target_page)
        print(f"Success: zathura running non-blockingly with PID {proc.pid}")
    except ViewerError as exc:
        print(f"[ERROR] {exc}")
        sys.exit(1)
