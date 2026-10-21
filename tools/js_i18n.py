#!/usr/bin/env python3
"""Словари Mini App внутри JS-кода страниц (app/main.py).

Страницы Mini App хранят переводы прямо в JS: `const I18N = {ru: {...}, en: {...}}`.
Из Python они не видны, поэтому этот инструмент разбирает исходник:

    python3 tools/js_i18n.py dump [блок]            — показать ключи (JSON)
    python3 tools/js_i18n.py build <блок> <файл> <язык>
                                                    — вставить/заменить словарь языка

Файл для `build` — JSON-массив пар [ключ, значение] в порядке русских ключей блока.
Список блоков в app/main.py: 1 — Секслото-шоу, 2 — лента видео, 3 — кейсы, 4 — аркада.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "app" / "main.py"
BLOCK_RE = re.compile(r"\bI18N\s*=\s*\{")


def blocks(text: str) -> list[tuple[int, int]]:
    """(позиция '{', позиция '}') для каждого блока I18N = {...}."""
    out = []
    for m in BLOCK_RE.finditer(text):
        i = text.index("{", m.start())
        depth = 0
        in_str = esc = False
        while i < len(text):
            ch = text[i]
            if in_str:
                esc = not esc and ch == "\\"
                if ch == '"' and not esc:
                    in_str = False
            elif ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        out.append((text.index("{", m.start()), i))
    return out


def lang_dicts(body: str) -> list[tuple[str, int, int, str]]:
    """[(язык, начало '{', конец '}', отступ)] для словарей верхнего уровня блока."""
    out = []
    for m in re.finditer(r"(?:^|\n)([ \t]*)(\w+):\s*\{", body):
        indent, lang = m.group(1), m.group(2)
        i = body.index("{", m.start())
        depth = 0
        in_str = esc = False
        while i < len(body):
            ch = body[i]
            if in_str:
                esc = not esc and ch == "\\"
                if ch == '"' and not esc:
                    in_str = False
            elif ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        out.append((lang, body.index("{", m.start()), i, indent))
    return out


def entries(inner: str) -> list[tuple[str, str]]:
    return re.findall(r'"((?:[^"\\]|\\.)*)"\s*:\s*"((?:[^"\\]|\\.)*)"', inner)


def indent_of(inner: str) -> str:
    """Отступ строки с первой парой ключ: значение (не lstrip — он ломает метод)."""
    for line in inner.split("\n"):
        if '"' in line:
            return line[: len(line) - len(line.lstrip())]
    return "  "


def norm(v: str) -> str:
    """Сравнимая форма значения: без разницы в экранировании."""
    return json.loads('"%s"' % v)


def load(text: str, n: int):
    spans = blocks(text)
    if not 1 <= n <= len(spans):
        raise SystemExit(f"блок {n} вне диапазона 1..{len(spans)}")
    start, end = spans[n - 1]
    body = text[start : end + 1]
    dicts = lang_dicts(body)
    langs = {
        lang: entries(body[ds : de + 1]) for lang, ds, de, _ in dicts
    }
    return start, end, body, dicts, langs


def cmd_dump(argv: list[str]) -> int:
    text = SRC.read_text(encoding="utf-8")
    want = [int(a) for a in argv] or list(range(1, len(blocks(text)) + 1))
    out = {}
    for n in want:
        _, _, _, dicts, langs = load(text, n)
        ru = [k for k, _ in langs["ru"]]
        out[n] = {
            "indent": dicts[0][3],
            "indent_entries": indent_of(langs["ru"] and "" or ""),
            "langs": sorted(langs),
            "keys": [
                [k] + [dict(langs.get(lg, [])).get(k, "") for lg in sorted(langs)]
                for k in ru
            ],
        }
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


def cmd_build(argv: list[str]) -> int:
    if len(argv) != 3:
        raise SystemExit("нужно: build <блок> <файл.json> <язык>")
    n, path, lang = int(argv[0]), Path(argv[1]), argv[2]
    pairs = json.loads(path.read_text(encoding="utf-8"))
    text = SRC.read_text(encoding="utf-8")
    start, end, body, dicts, langs = load(text, n)

    ru_keys = [k for k, _ in langs["ru"]]
    if [k for k, _ in pairs] != ru_keys:
        raise SystemExit(
            "ключи не совпадают с русскими. первое расхождение: %r" % next(
                (
                    (a, b)
                    for a, b in zip([k for k, _ in pairs], ru_keys)
                    if a != b
                ),
                "разная длина: %d != %d" % (len(pairs), len(ru_keys)),
            )
        )
    for k, v in pairs:
        ph_ru = re.findall(r"\{(\w+)\}", k)
        ph_v = re.findall(r"\{(\w+)\}", v)
        if ph_ru != ph_v:
            raise SystemExit(f"плейсхолдеры в {k!r}: {ph_ru} != {ph_v}")

    base_indent = dicts[0][3]
    entry_indent = base_indent + "  "
    lines = [f"{base_indent}{lang}: {{"]
    for i, (k, v) in enumerate(pairs):
        tail = "," if i + 1 < len(pairs) else ""
        lines.append(
            f'{entry_indent}"{k}": {json.dumps(v, ensure_ascii=False)}{tail}'
        )
    lines.append(f"{base_indent}}}")
    new_dict = "\n".join(lines)

    if lang in langs:
        # заменяем существующий словарь языка
        ds, de = next((d[1], d[2]) for d in dicts if d[0] == lang)
        repl_start = start + body.rindex("\n", 0, ds) + 1
        repl_end = start + de + 1
        # сохраняем запятую, если она была после закрывающей скобки
        after = text[repl_end : repl_end + 1]
        new = new_dict + ("," if after == "," else "")
        text = text[:repl_start] + new + text[repl_end + (1 if after == "," else 0) :]
    else:
        # вставляем после последнего словаря верхнего уровня
        _, _, last_end, _ = dicts[-1]
        end_pos = start + last_end + 1  # сразу после закрывающей "}" прошлого языка
        tail = text[end_pos:]
        stripped = tail.lstrip()
        if stripped.startswith(","):  # запятая уже стоит — не дублируем
            tail = stripped[1:]
        text = text[:end_pos] + ",\n" + new_dict + tail

    SRC.write_text(text, encoding="utf-8")
    _, _, _, _, langs2 = load(SRC.read_text(encoding="utf-8"), n)
    print(f"ок: блок {n}, язык {lang}, {len(langs2[lang])} пар, языки: {sorted(langs2)}")
    return 0


def main() -> int:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    cmd, argv = sys.argv[1], sys.argv[2:]
    if cmd == "dump":
        return cmd_dump(argv)
    if cmd == "build":
        return cmd_build(argv)
    raise SystemExit(f"неизвестная команда: {cmd}")


if __name__ == "__main__":
    raise SystemExit(main())
