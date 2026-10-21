"""Регрессионные тесты многоязычности (русский -> английский -> испанский -> португальский).

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
import shutil
import tempfile

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
from app.i18n_pt import PT_SOURCE
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


@pytest.mark.parametrize("lang", ["en", "es", "pt"])
def test_semantic_keys_are_fully_translated(lang):
    """Все семантические ключи русского словаря переведены на язык."""
    missing = [k for k in TRANSLATIONS["ru"] if k not in TRANSLATIONS[lang]]
    assert not missing, f"не переведены: {missing}"


@pytest.mark.parametrize("lang", ["en", "es", "pt"])
def test_placeholders_match_russian_source(lang):
    """Плейсхолдеры в переводе должны повторять русский исходник.

    Потерянный `{name}` или `{balance}` = упавшее сообщение у пользователя.
    """
    for key, ru_text in TRANSLATIONS["ru"].items():
        translated = TRANSLATIONS[lang][key]
        assert set(_PLACEHOLDER.findall(translated)) == set(_PLACEHOLDER.findall(ru_text)), key


@pytest.mark.parametrize("lang", ["en", "es", "pt"])
def test_source_dictionary_placeholders_match_keys(lang):
    """То же для массовых словарей: ключ — русская строка, значение — перевод."""
    source = {"en": EN_SOURCE, "es": ES_SOURCE, "pt": PT_SOURCE}[lang]
    for ru_text, translated in source.items():
        assert set(_PLACEHOLDER.findall(translated)) == set(_PLACEHOLDER.findall(ru_text)), (
            f"{lang}: плейсхолдеры не совпадают в строке {ru_text[:60]!r}"
        )


@pytest.mark.parametrize("lang,source", [("es", ES_SOURCE), ("pt", PT_SOURCE)])
def test_translation_keys_are_a_subset_of_english(lang, source):
    """Словарь языка не должен содержать ключей, которых нет в английском.

    Иначе перевод «висел» бы на строке, которой в боте уже нет.
    """
    extra = set(source) - set(EN_SOURCE)
    assert not extra, f"{lang}: лишние ключи: {list(extra)[:5]}"


def test_spanish_covers_every_string_of_the_bot():
    """Испанский закрыт полностью: непереведённых строк не осталось.

    Тест страхует от обратного: если в боте появится новая русская строка,
    она сначала должна попасть и в испанский словарь (язык вводится целиком).
    """
    missing = [k for k in EN_SOURCE if k not in ES_SOURCE]
    assert not missing, f"не переведено на испанский: {len(missing)} шт., например {missing[:3]!r}"


def test_untranslated_string_falls_back_to_english_not_russian(monkeypatch):
    """Пока строки нет в словаре языка — показываем английский, а не русский.

    Испанский сейчас полный, поэтому строку временно убираем из словаря сами:
    фолбэк должен работать и для следующих языков, которые переводятся по частям.
    """
    from app import i18n

    probe = next(k for k in EN_SOURCE if EN_SOURCE[k] != k)
    monkeypatch.delitem(i18n.TRANSLATIONS["es"], probe, raising=False)
    assert t("es", probe) == EN_SOURCE[probe]
    assert t("es", probe) != probe


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


def _mini_app_i18n_blocks() -> list[dict[str, list[tuple[str, str]]]]:
    """JS-словари Mini App из app/main.py: [{язык: [(ключ, значение)]}].

    Внутри страниц Mini App свои словари (`const I18N = {ru: {...}, en: {...}}`),
    они не видны из Python — поэтому разбираем исходник: считаем скобки, следя
    за кавычками (в значениях попадаются `\\n` и экранированные кавычки).
    """
    import pathlib

    src = pathlib.Path(__file__).resolve().parents[1] / "main.py"
    text = src.read_text(encoding="utf-8")
    blocks = []
    for m in re.finditer(r"\bI18N\s*=\s*\{", text):
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
        body = text[text.index("{", m.start()): i + 1]
        langs = {}
        for lang, inner in re.findall(r'(\w+):\s*\{\n((?:.*?\n)*?)\s*\}', body):
            langs[lang] = re.findall(r'"((?:[^"\\]|\\.)*)"\s*:\s*"((?:[^"\\]|\\.)*)"', inner)
        blocks.append(langs)
    return blocks


@pytest.mark.parametrize("lang", ["es", "pt"])
def test_mini_app_is_translated_with_placeholders_intact(lang: str):
    """Страницы Mini App переведены полностью и без потери плейсхолдеров.

    Это второй, отдельный от бота массив строк: словари лежат прямо в JS-коде
    страниц, поэтому Python-тесты их не видят — проверяем по исходнику.
    """
    blocks = _mini_app_i18n_blocks()
    assert len(blocks) >= 4, f"ожидали 4 словаря Mini App, нашли {len(blocks)}"
    for n, langs in enumerate(blocks, 1):
        assert lang in langs, f"Mini App, словарь {n}: нет языка {lang}"
        ru_keys = [k for k, _ in langs["ru"]]
        assert [k for k, _ in langs[lang]] == ru_keys, (
            f"Mini App, словарь {n}: ключи {lang} != ru"
        )
        for rk, (_, lv) in zip(ru_keys, langs[lang]):
            assert re.findall(r"\{(\w+)\}", rk) == re.findall(r"\{(\w+)\}", lv), (
                f"Mini App, словарь {n}: потерян плейсхолдер в {rk!r}"
            )
        # перевод действительно отличается от русского там, где он есть и в en
        same_as_ru = [k for (k, v), (_, rv) in zip(langs[lang], langs["ru"]) if v == rv]
        en_differs = [k for (k, v), (_, rv) in zip(langs["en"], langs["ru"]) if v != rv]
        assert not [k for k in en_differs if k in same_as_ru], (
            f"Mini App, словарь {n}: не переведено "
            f"{[k for k in en_differs if k in same_as_ru][:3]}"
        )


def test_mini_app_scripts_are_valid_javascript():
    """JS страниц Mini App разбирается парсером.

    Словари лежат внутри Python-строк, поэтому escape-последовательности
    проходят через Питон: опечатка в `\\n` превращается в настоящий перевод
    строки внутри JS-строки — и страница целиком падает с SyntaxError,
    ещё до того как что-то покажет пользователю. Ловим это на тестах.
    """
    import ast
    import pathlib
    import subprocess

    src = pathlib.Path(__file__).resolve().parents[1] / "main.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))
    pages = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and re.search(r"\bI18N\s*=\s*\{", node.value)
    ]
    assert len(pages) >= 4, f"ожидали 4 страницы Mini App, нашли {len(pages)}"
    node_bin = shutil.which("node")
    if not node_bin:  # без Node.js проверяем хотя бы отсутствие «сырых» переносов
        for page in pages:
            for script in re.findall(r"<script[^>]*>(.*?)</script>", page, re.S):
                for lit in re.findall(r'"((?:[^"\\]|\\.)*)"', script):
                    assert "\n" not in lit, f"сырой перенос строки в JS-строке: {lit!r}"
        return
    for i, page in enumerate(pages):
        for j, script in enumerate(re.findall(r"<script[^>]*>(.*?)</script>", page, re.S)):
            if "I18N" not in script:
                continue
            tmp = pathlib.Path(tempfile.gettempdir()) / f"mini_app_{i}_{j}.js"
            tmp.write_text(script, encoding="utf-8")
            res = subprocess.run(
                [node_bin, "--check", str(tmp)], capture_output=True, text=True
            )
            assert res.returncode == 0, f"Mini App страница {i}, script {j}: {res.stderr}"


def test_portuguese_is_supported_and_shown_in_picker():
    assert "pt" in SUPPORTED_LANGUAGES
    assert normalize_language("pt") == "pt"
    assert normalize_language("pt-BR") == "pt"
    assert language_label("pt") == "🇧🇷 Português"
    labels = [btn.text for row in language_keyboard().inline_keyboard for btn in row]
    assert any("Português" in lbl for lbl in labels)


def test_portuguese_menu_labels_are_translated():
    assert t("pt", "menu.watch") == "🎬 Assistir"
    assert t("pt", "menu.buy") == "🛍 Loja"
    # Кнопку на португальском обработчик должен узнавать так же, как русскую.
    assert t("pt", "menu.watch") in menu_button_variants("watch")


@pytest.mark.parametrize("lang,source", [("en", EN_SOURCE), ("es", ES_SOURCE), ("pt", PT_SOURCE)])
def test_translation_keeps_leading_emoji_of_the_source(lang, source):
    """Перевод начинается с того же значка, что и русский исходник.

    Ловит тихую беду: перевод уехал на соседнюю строку («◀️ Назад» однажды
    уехало на «Ср» и стало «Mi»). По-настоящему проверить смысл перевода
    тест не может, а рассогласование значка видно сразу — и у пользователя
    кнопка «Назад» без стрелки выглядит обманом.
    """

    def mark(s: str) -> str:
        m = re.match(r"^((?:[^\w\sЀ-ӿ{<]️?)+)", s)
        return m.group(1) if m else ""

    broken = [
        (k, v) for k, v in source.items() if mark(k) and not mark(v).startswith(mark(k))
    ]
    assert not broken, f"{lang}: потерян значок в начале {broken[:3]}"
