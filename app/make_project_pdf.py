import os
from pathlib import Path
from typing import Iterable

from reportlab.lib.pagesizes import A4
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas


PROJECT_ROOT = Path(".")
OUTPUT_FILE = "project_dump.pdf"

# Ограничения
MAX_PAGES = 90
MAX_SIZE_MB = 15

# Что включать
INCLUDE_EXTENSIONS = {
    ".py",
    ".txt",
    ".md",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".env",
    ".sql",
}

# Что исключать
EXCLUDED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    ".idea",
    ".vscode",
    "dist",
    "build",
    ".mypy_cache",
    ".pytest_cache",
}

EXCLUDED_FILES = {
    OUTPUT_FILE,
}

# Крупные/мусорные каталоги при желании можно исключить
OPTIONAL_EXCLUDED_PARTS = {
    "site-packages",
}


def is_probably_text_file(path: Path) -> bool:
    if path.suffix.lower() in INCLUDE_EXTENSIONS:
        return True

    # .env без suffix
    if path.name.startswith(".env"):
        return True

    return False


def should_skip(path: Path) -> bool:
    parts = set(path.parts)

    if parts & EXCLUDED_DIRS:
        return True

    if parts & OPTIONAL_EXCLUDED_PARTS:
        return True

    if path.name in EXCLUDED_FILES:
        return True

    if path.is_dir():
        return True

    if not is_probably_text_file(path):
        return True

    return False


def iter_project_files(root: Path) -> Iterable[Path]:
    all_files = []
    for path in root.rglob("*"):
        if should_skip(path):
            continue
        all_files.append(path)

    # Стабильная сортировка
    all_files.sort(key=lambda p: str(p).lower())
    return all_files


def safe_read_text(path: Path) -> str:
    for enc in ("utf-8", "utf-8-sig", "cp1251", "latin-1"):
        try:
            return path.read_text(encoding=enc)
        except Exception:
            continue
    return "[[FAILED TO READ FILE]]"


def wrap_line_to_width(text: str, font_name: str, font_size: int, max_width: float) -> list[str]:
    if not text:
        return [""]

    # Быстрая проверка
    if stringWidth(text, font_name, font_size) <= max_width:
        return [text]

    result = []
    current = ""

    for ch in text:
        test = current + ch
        if stringWidth(test, font_name, font_size) <= max_width:
            current = test
        else:
            if current:
                result.append(current)
            current = ch

    if current:
        result.append(current)

    return result


def build_text_blocks(root: Path) -> list[str]:
    blocks = []
    for path in iter_project_files(root):
        rel = path.relative_to(root)
        content = safe_read_text(path)

        block = [
            "=" * 80,
            f"FILE: {rel}",
            "=" * 80,
            content.rstrip(),
            "",
        ]
        blocks.append("\n".join(block))
    return blocks


def render_pdf(blocks: list[str], output_file: str) -> tuple[int, int]:
    page_width, page_height = A4

    # Попытки ужать документ
    attempts = [
        {"font_size": 9, "line_gap": 11, "margin": 36},
        {"font_size": 8, "line_gap": 9, "margin": 28},
        {"font_size": 7, "line_gap": 8, "margin": 20},
        {"font_size": 6, "line_gap": 7, "margin": 16},
    ]

    last_pages = None

    for cfg in attempts:
        c = canvas.Canvas(output_file, pagesize=A4)
        font_name = "Courier"
        font_size = cfg["font_size"]
        line_gap = cfg["line_gap"]
        margin = cfg["margin"]

        usable_width = page_width - margin * 2
        y = page_height - margin
        pages = 1

        c.setFont(font_name, font_size)

        def new_page():
            nonlocal y, pages
            c.showPage()
            c.setFont(font_name, font_size)
            y = page_height - margin
            pages += 1

        for block in blocks:
            for raw_line in block.splitlines():
                wrapped_lines = wrap_line_to_width(
                    raw_line,
                    font_name,
                    font_size,
                    usable_width,
                )
                for line in wrapped_lines:
                    if y < margin:
                        new_page()
                    c.drawString(margin, y, line)
                    y -= line_gap

            # пустая строка между файлами
            if y < margin:
                new_page()
            y -= line_gap

        c.save()

        file_size = os.path.getsize(output_file)
        last_pages = pages

        if pages <= MAX_PAGES and file_size <= MAX_SIZE_MB * 1024 * 1024:
            return pages, file_size

    return last_pages or 0, os.path.getsize(output_file)


def main():
    blocks = build_text_blocks(PROJECT_ROOT)
    pages, size_bytes = render_pdf(blocks, OUTPUT_FILE)

    size_mb = size_bytes / (1024 * 1024)

    print(f"PDF created: {OUTPUT_FILE}")
    print(f"Pages: {pages}")
    print(f"Size: {size_mb:.2f} MB")

    if pages > MAX_PAGES:
        print(f"WARNING: pages exceed limit ({pages} > {MAX_PAGES})")

    if size_mb > MAX_SIZE_MB:
        print(f"WARNING: size exceeds limit ({size_mb:.2f} MB > {MAX_SIZE_MB} MB)")


if __name__ == "__main__":
    main()