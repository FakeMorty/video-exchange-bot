#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Добавление батча переводов в массовый словарь языка (app/i18n_<lang>.py).

Инструмент живёт в репозитории, потому что перевод каждого нового языка —
это десятки батчей на протяжении многих сессий: scratch-файлы вне репозитория
не переживают паузу между сессиями, а порядок ключей и проверки должны быть
одинаковыми от батча к батчу.

Запуск (из корня репозитория):
    PYTHONPATH=. python3 tools/i18n_batch.py <lang> <batch.jsonl> <индекс 1-based>

  <lang>        — код языка: es, pt, de, fr ... (файл app/i18n_<lang>.py,
                 словарь <LANG>_SOURCE);
  <batch.jsonl> — JSON Lines, по строке на пару: {"k": <русская строка>, "v": <перевод>};
  <индекс>      — номер ключа в замороженном списке, с которого начинается батч.

Формат именно JSON, а не «ключ: значение» построчно: около 40 % ключей
содержат переводы строк, и построчный формат их молча разрывал.

Замороженный порядок ключей
---------------------------
Порядок = порядок ключей завершённого испанского словаря (``app.i18n_es``),
который строился по частоте встречаемости строк в коде. Он зафиксирован
раз и навсегда: если его пересортировать, нумерация батчей между сессиями
поедет (словарь лежит внутри glob `app/*.py`, поэтому каждое добавление
меняет частотную картину). Новые языки должны идти в том же порядке, что
даёт бонус: строки, видимые пользователю чаще всего, переводятся первыми.

Что проверяется до записи (при любой ошибке файл не трогаем)
-----------------------------------------------------------
* ключ батча побуквенно равен ключу из замороженного списка — защита от
  съехавшего порядка и от опечаток;
* плейсхолдеры (`{name}`, `{balance:,.0f}`, `{arg0}`) совпадают с русским
  исходником — иначе `str.format` уронит сообщение у пользователя;
* ключа ещё нет в словаре — защита от повторного применения батча;
* предупреждение про ключи без кириллицы (легальные «🎵 {name}», «VIP»).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

lang, batch_path, start = sys.argv[1], sys.argv[2], int(sys.argv[3])
dict_name = f"{lang.upper()}_SOURCE"
module = ROOT / f"app/i18n_{lang}.py"

from app.i18n_es import ES_SOURCE  # noqa: E402  (после настройки sys.path)

# Порядок ключей = порядок завершённого испанского словаря (см. docstring).
keys = list(ES_SOURCE)

pairs = []
for line in Path(batch_path).read_text(encoding="utf-8").splitlines():
    if line.strip():
        row = json.loads(line)
        pairs.append((row["k"], row["v"]))

slice_keys = keys[start - 1: start - 1 + len(pairs)]
mismatch = [(start + i, pairs[i][0], k) for i, k in enumerate(slice_keys) if pairs[i][0] != k]
if mismatch:
    print("НЕСОВПАДЕНИЕ КЛЮЧЕЙ (индекс | в батче | в списке):")
    for idx, got, want in mismatch[:20]:
        print(f"  {idx}\n    батч:  {got!r}\n    список:{want!r}")
    sys.exit(1)

PH = re.compile(r"\{[a-zA-Z_]+(?::[.0-9a-zA-Z]+)?\}")
mod = __import__(f"app.i18n_{lang}", fromlist=[dict_name])
vals = dict(getattr(mod, dict_name))
for k, v in pairs:
    if PH.findall(k) != PH.findall(v):
        print(f"ПЛЕЙСХОЛДЕРЫ НЕ СОВПАДАЮТ: {k!r} -> {v!r}")
        sys.exit(1)
    if k in vals:
        print(f"КЛЮЧ УЖЕ ЕСТЬ: {k!r}")
        sys.exit(1)
    vals[k] = v

suspicious = []
for k in vals:
    letters = re.sub(r"\{[^}]*\}|\d+", " ", k)
    letters = re.sub(r"[^\w\s]", " ", letters).strip()
    if letters and not any("\u0400" <= c <= "\u04FF" for c in letters):
        suspicious.append(k)
if suspicious:
    print("ВНИМАНИЕ, ключи без кириллицы (проверь глазами):", suspicious[:5])

src = module.read_text(encoding="utf-8")
header = src.split(f"{dict_name}: dict[str, str] = {{")[0]
order = [k for k in keys if k in vals]
assert len(order) == len(vals), f"в словаре {len(vals)} ключей, в списке {len(order)}"
out = [header, f"{dict_name}: dict[str, str] = {{"]
for k in order:
    out.append(f"    {json.dumps(k, ensure_ascii=False)}: {json.dumps(vals[k], ensure_ascii=False)},")
out.append("}")
out.append("")
module.write_text("\n".join(out), encoding="utf-8")
print(f"ок: +{len(pairs)}, всего {len(vals)} из {len(keys)}")
