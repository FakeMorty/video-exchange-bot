"""Тесты обязательного нормального ника (без User <tg id>)."""

from app.config import NICKNAME_MIN_LENGTH
from app.services import (
    has_valid_nickname,
    is_placeholder_nickname,
    validate_nickname_format,
)


class _FakeUser:
    def __init__(self, display_name, telegram_id=1, nickname_set=True):
        self.display_name = display_name
        self.telegram_id = telegram_id
        self.nickname_set = nickname_set


def test_min_length_is_at_least_4():
    assert NICKNAME_MIN_LENGTH >= 4


def test_placeholder_user_id_patterns():
    tid = 8809168513
    assert is_placeholder_nickname(f"User {tid}", tid)
    assert is_placeholder_nickname(f"User{tid}", tid)
    assert is_placeholder_nickname(f"User#{tid}", tid)
    assert is_placeholder_nickname(f"User_{tid}", tid)
    assert is_placeholder_nickname(f"user-{tid}", tid)
    assert is_placeholder_nickname(str(tid), tid)
    assert is_placeholder_nickname(None)
    assert is_placeholder_nickname("")
    assert not is_placeholder_nickname("Полина", tid)
    assert not is_placeholder_nickname("Fast", tid)
    assert not is_placeholder_nickname("Mixaka86565", tid)


def test_validate_rejects_dots_questions_short_and_placeholder():
    assert validate_nickname_format(".")[0] is False
    assert validate_nickname_format("?")[0] is False
    assert validate_nickname_format("....")[0] is False
    assert validate_nickname_format("ab")[0] is False
    assert validate_nickname_format("abc")[0] is False
    assert validate_nickname_format("User1")[0] is False
    assert validate_nickname_format("1234")[0] is False
    assert validate_nickname_format("aaaa")[0] is False


def test_validate_accepts_normal_nicks():
    assert validate_nickname_format("Полина")[0] is True
    assert validate_nickname_format("Fast")[0] is True
    assert validate_nickname_format("wllmLvt")[0] is True
    assert validate_nickname_format("Cool_Nick")[0] is True
    assert validate_nickname_format("a_b1")[0] is True


def test_has_valid_nickname_forces_placeholder_users():
    bad = _FakeUser("User 8809168513", telegram_id=8809168513, nickname_set=True)
    assert has_valid_nickname(bad) is False

    good = _FakeUser("Полина", telegram_id=1, nickname_set=True)
    assert has_valid_nickname(good) is True

    unset = _FakeUser(None, telegram_id=1, nickname_set=False)
    assert has_valid_nickname(unset) is False

    short = _FakeUser("abc", telegram_id=1, nickname_set=True)
    assert has_valid_nickname(short) is False
