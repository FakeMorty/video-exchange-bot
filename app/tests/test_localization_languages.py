"""Регрессионные тесты многоязычности (русский -> английский -> испанский).

Проверяют то, что легко сломать при добавлении языка:
* язык появляется в списке и в кнопке «🌐 Язык»;
* семантические ключи переведены полностью;
* плейсхолдеры `{name}`, `{balance}` и т.п. сохранены — иначе `str.format`
  уронит сообщение прямо у пользователя;
* массовый словарь не содержит ключей, которых нет в коде-источнике;
* непереведённая строка падает на английский, а не на русский;
* постер для языка без собственной папки берётся из `en/`.
"""
import re

import pytest

from app.holidays import resolve_poster
from app.i18n import (
    SUPPORTED_LANGUAGES,
    TRANSLATIONS,
    language_label,
    normalize_language,
    t,
)
from app.i18n_en import EN_SOURCE
from app.i18n_es import ES_SOURCE
from app.keyboards import language_keyboard, menu_button_variants

_PLACEHOLDER = re.compile(r"\{(\w+)\}")


def test_spanish_is_supported_and_shown_in_picker():
    assert "es" in SUPPORTED_LANGUAGES
    assert normalize_language("es") == "es"
    assert normalize_language("es-MX") == "es"
    assert language_label("es") == "🇪🇸 Español"
    labels = [btn.text for row in language_keyboard().inline_keyboard for btn in row]
    assert any("Español" in lbl for lbl in labels)


def test_spanish_menu_labels_are_translated():
    assert t("es", "menu.watch") == "🎬 Ver"
    assert t("es", "menu.buy") == "🛍 Tienda"
    # Кнопку на испанском обработчик должен узнавать так же, как русскую.
    assert t("es", "menu.watch") in menu_button_variants("watch")


@pytest.mark.parametrize("lang", ["en", "es"])
def test_semantic_keys_are_fully_translated(lang):
    """Все семантические ключи русского словаря переведены на язык."""
    missing = [k for k in TRANSLATIONS["ru"] if k not in TRANSLATIONS[lang]]
    assert not missing, f"не переведены: {missing}"


@pytest.mark.parametrize("lang", ["en", "es"])
def test_placeholders_match_russian_source(lang):
    """Плейсхолдеры в переводе должны повторять русский исходник.

    Потерянный `{name}` или `{balance}` = упавшее сообщение у пользователя.
    """
    for key, ru_text in TRANSLATIONS["ru"].items():
        translated = TRANSLATIONS[lang][key]
        assert set(_PLACEHOLDER.findall(translated)) == set(_PLACEHOLDER.findall(ru_text)), key


@pytest.mark.parametrize("lang", ["en", "es"])
def test_source_dictionary_placeholders_match_keys(lang):
    """То же для массовых словарей: ключ — русская строка, значение — перевод."""
    source = {"en": EN_SOURCE, "es": ES_SOURCE}[lang]
    for ru_text, translated in source.items():
        assert set(_PLACEHOLDER.findall(translated)) == set(_PLACEHOLDER.findall(ru_text)), (
            f"{lang}: плейсхолдеры не совпадают в строке {ru_text[:60]!r}"
        )


def test_spanish_source_keys_are_a_subset_of_english():
    """Испанский словарь не должен содержать ключей, которых нет в английском.

    Иначе перевод «висел» бы на строке, которой в боте уже нет.
    """
    extra = set(ES_SOURCE) - set(EN_SOURCE)
    assert not extra, f"лишние ключи: {list(extra)[:5]}"


def test_untranslated_string_falls_back_to_english_not_russian():
    """Пока строка не переведена — показываем английский, а не русский."""
    untranslated = next(k for k in EN_SOURCE if k not in ES_SOURCE)
    assert t("es", untranslated) == EN_SOURCE[untranslated]
    assert t("es", untranslated) != untranslated


def test_russian_never_falls_back_to_english():
    """Русский — исходный язык: чего нет в словаре, то и показываем."""
    assert normalize_language("de") == "ru"  # неизвестный язык пока = русский
    assert t("ru", "menu.watch") == "🎬 Смотреть"
    unknown = "этой-строки-нет-ни-в-одном-словаре"
    assert t("ru", unknown) == unknown
    assert t("en", unknown) == unknown


def test_poster_for_language_without_folder_uses_english():
    """У испанского нет своих постеров — берём английские, а не русские."""
    assert "/en/" in resolve_poster("mar_8.jpg", lang="es").replace("\\", "/")
    ru = resolve_poster("mar_8.jpg", lang="ru").replace("\\", "/")
    assert "/en/" not in ru
