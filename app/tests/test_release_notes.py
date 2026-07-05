from app.release_notes import build_version_text, get_recent_changelog_items, CURRENT_VERSION


def test_release_notes_reads_recent_items_from_changelog():
    items = get_recent_changelog_items(limit=3)
    assert items
    assert all(item.strip() for item in items)
    assert all(not item.startswith("* ") for item in items)


def test_release_notes_text_contains_current_version_and_changelog_hint():
    text = build_version_text(admin=True, limit=2)
    assert CURRENT_VERSION in text
    assert "CHANGELOG.md" in text
    assert "Последние изменения" in text
