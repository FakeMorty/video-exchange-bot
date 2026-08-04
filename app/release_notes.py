from __future__ import annotations

import html
import re
from pathlib import Path

# Единственный ручной источник версии для отображения в боте.
# Все тексты изменений автоматически подтягиваются из CHANGELOG.md,
# поэтому будущим агентам достаточно:
# 1) обновить CURRENT_VERSION при релизе,
# 2) добавить записи в CHANGELOG.md.
CURRENT_VERSION = "v3.8.0-growth-funnel"
CURRENT_STATUS = "Актуальная боевая сборка"

_CHANGELOG_PATH = Path(__file__).resolve().parent.parent / "CHANGELOG.md"

# Лимит сообщения Telegram — 4096 символов. Оставляем запас под шапку
# и (для админов) подсказку, чтобы кнопка «Версия бота» не падала никогда.
_MAX_BODY_LEN = 3500
_MAX_ITEM_LEN = 600

_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_CODE_RE = re.compile(r"`([^`]+)`")


def _md_to_html(text: str) -> str:
    """Мини-конвертер changelog-разметки в безопасный Telegram HTML.

    Сначала экранируем любой HTML (в CHANGELOG.md встречались строки вида
    `User <tg id>`, которые роняли панель с ошибкой парсинга сущностей),
    затем превращаем **bold** в <b> и `code` в <code>.
    """
    escaped = html.escape(text, quote=False)
    escaped = _BOLD_RE.sub(r"<b>\1</b>", escaped)
    escaped = _CODE_RE.sub(r"<code>\1</code>", escaped)
    return escaped


def _read_changelog() -> str:
    try:
        return _CHANGELOG_PATH.read_text(encoding="utf-8")
    except Exception:
        return ""


def get_recent_changelog_items(limit: int = 8) -> list[str]:
    """Возвращает последние пункты changelog без markdown-маркеров."""
    content = _read_changelog()
    items: list[str] = []
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line.startswith("*"):
            continue
        item = line.lstrip("*").strip()
        if item:
            items.append(item)
        if len(items) >= limit:
            break
    return items


def build_version_text(*, admin: bool = False, limit: int = 8) -> str:
    items = get_recent_changelog_items(limit=limit)

    text = (
        "🤖 <b>ИНФОРМАЦИЯ О ВЕРСИИ И ИЗМЕНЕНИЯХ</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"• <b>Текущая версия:</b> <code>{CURRENT_VERSION}</code>\n"
        f"• <b>Статус:</b> {CURRENT_STATUS}\n\n"
        "📢 <b>Последние изменения:</b>\n"
    )

    if not items:
        text += "• История изменений пока недоступна. Проверь файл CHANGELOG.md.\n"

    shown = 0
    for item in items:
        clipped = item if len(item) <= _MAX_ITEM_LEN else item[: _MAX_ITEM_LEN - 1].rstrip() + "…"
        line = f"• {_md_to_html(clipped)}\n"
        # Гарантия: сообщение целиком (с админской подсказкой) укладывается в 4096.
        if len(text) + len(line) > _MAX_BODY_LEN:
            break
        text += line
        shown += 1

    omitted = len(items) - shown
    if omitted > 0:
        text += f"• …и ещё {omitted} — полная история в CHANGELOG.md\n"

    if admin:
        text += (
            "\n👑 <b>Подсказка для сопровождения:</b>\n"
            "Панель версии читает список изменений прямо из <code>CHANGELOG.md</code>. "
            "Перед релизом обновляйте версию в <code>app/release_notes.py</code> и добавляйте новые пункты в changelog."
        )

    return text
