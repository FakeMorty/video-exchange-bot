from __future__ import annotations

from pathlib import Path

# Единственный ручной источник версии для отображения в боте.
# Все тексты изменений автоматически подтягиваются из CHANGELOG.md,
# поэтому будущим агентам достаточно:
# 1) обновить CURRENT_VERSION при релизе,
# 2) добавить записи в CHANGELOG.md.
CURRENT_VERSION = "v3.4.0-stable"
CURRENT_STATUS = "Актуальная боевая сборка"

_CHANGELOG_PATH = Path(__file__).resolve().parent.parent / "CHANGELOG.md"


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
    if not items:
        items = ["История изменений пока недоступна. Проверьте файл CHANGELOG.md."]

    text = (
        "🤖 <b>ИНФОРМАЦИЯ О ВЕРСИИ И ИЗМЕНЕНИЯХ</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"• <b>Текущая версия:</b> <code>{CURRENT_VERSION}</code>\n"
        f"• <b>Статус:</b> {CURRENT_STATUS}\n\n"
        "📢 <b>Последние изменения:</b>\n"
    )

    for item in items:
        text += f"• {item}\n"

    if admin:
        text += (
            "\n👑 <b>Подсказка для сопровождения:</b>\n"
            "Панель версии читает список изменений прямо из <code>CHANGELOG.md</code>. "
            "Перед релизом обновляйте версию в <code>app/release_notes.py</code> и добавляйте новые пункты в changelog."
        )

    return text
