"""Regression tests for media-send errors vs recipient/API errors."""

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SendVideo

from app.user_handlers import _is_invalid_stored_media_error


@pytest.mark.parametrize(
    "message",
    [
        "Telegram server says - Bad Request: wrong file identifier/HTTP URL specified",
        "Telegram server says - Bad Request: MEDIA_FILE_INVALID",
    ],
)
def test_known_invalid_file_id_errors_invalidate_content(message):
    error = TelegramBadRequest(method=SendVideo(chat_id=1, video="file-id"), message=message)
    assert _is_invalid_stored_media_error(error) is True


@pytest.mark.parametrize(
    "message",
    [
        "Telegram server says - Bad Request: chat not found",
        "Telegram server says - Bad Request: message text is too long",
    ],
)
def test_other_bad_requests_do_not_invalidate_content(message):
    error = TelegramBadRequest(method=SendVideo(chat_id=1, video="file-id"), message=message)
    assert _is_invalid_stored_media_error(error) is False


def test_non_bad_request_delivery_errors_do_not_invalidate_content():
    assert _is_invalid_stored_media_error(
        RuntimeError("Telegram server says - Forbidden: bot was blocked by the user")
    ) is False
    assert _is_invalid_stored_media_error(TimeoutError("Telegram API timed out")) is False
