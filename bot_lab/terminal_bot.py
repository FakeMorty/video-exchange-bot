#!/usr/bin/env python3
"""Terminal Telegram Bot emulator for AI agents and developers.

Runs the real aiogram routers against a fake Telegram Bot API session.
No Telegram network is used. By default DB is an isolated SQLite file.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import shlex
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncGenerator

# Must be set before importing app.config/app.db.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
DEFAULT_DB = ROOT / ".bot_lab.sqlite3"


@dataclass
class ButtonAction:
    kind: str  # "message" | "callback"
    title: str
    value: str


class FakeTelegramSession:  # subclassed lazily after aiogram import in build_app()
    pass


def _install_lab_env(db_url: str, *, real_env: bool = False) -> None:
    """Make imports safe for local emulation."""
    if real_env:
        return
    os.environ["BOT_TOKEN"] = os.environ.get("BOT_TOKEN", "123456:BOT_LAB_FAKE_TOKEN")
    os.environ["DATABASE_URL"] = db_url
    os.environ.setdefault("WEBHOOK_BASE", "http://bot-lab.local")
    os.environ.setdefault("WEBHOOK_PATH", "/webhook")
    os.environ.setdefault("ENABLE_AI_ASSISTANT", "true")
    os.environ.setdefault("AI_ASSISTANT_API_KEY", "bot-lab-fake-key")


class BotLab:
    def __init__(self, *, user_id: int, username: str, first_name: str, real_ai: bool = False):
        self.user_id = user_id
        self.username = username
        self.first_name = first_name
        self.real_ai = real_ai
        self.update_id = 1000
        self.message_id = 1
        self.last_bot_message = None
        self.buttons: list[ButtonAction] = []
        self.bot = None
        self.dp = None
        self.session = None

    async def setup(self) -> None:
        from aiogram import Bot, Dispatcher
        from aiogram.client.default import DefaultBotProperties
        from aiogram.client.session.base import BaseSession
        from aiogram.enums import ParseMode
        from aiogram.fsm.storage.memory import MemoryStorage

        lab = self

        class _FakeTelegramSession(BaseSession):
            async def close(self) -> None:
                return None

            async def stream_content(
                self,
                url: str,
                headers: dict[str, Any] | None = None,
                timeout: int = 30,
                chunk_size: int = 65536,
                raise_for_status: bool = True,
            ) -> AsyncGenerator[bytes, None]:
                if False:
                    yield b""
                return

            async def make_request(self, bot: Bot, method: Any, timeout: int | None = None) -> Any:
                return lab.handle_api_call(method)

        self.session = _FakeTelegramSession()
        self.bot = Bot(
            token=os.environ.get("BOT_TOKEN", "123456:BOT_LAB_FAKE_TOKEN"),
            session=self.session,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        self.dp = Dispatcher(storage=MemoryStorage())

        # Import after env is installed.
        from app.db import init_db
        from app.admin_handlers import router as admin_router
        from app.user_handlers import router as user_router
        from app.user_offer_handlers import router as user_offer_router
        from app.donation_shop import router as donation_router
        from app import ai_assistant
        from app.ai_assistant import router as ai_router
        from app.middlewares import BanCheckMiddleware

        if not self.real_ai:
            async def fake_call_katya(messages: list[dict]) -> str:
                last = ""
                for item in reversed(messages):
                    if item.get("role") == "user":
                        last = item.get("content", "")
                        break
                return (
                    "[BOT LAB] Катя отвечает без внешнего API. "
                    f"Я получила сообщение: {last!r}. "
                    "Этого достаточно, чтобы проверить FSM, списание монет, кнопки и историю."
                )
            ai_assistant.call_katya = fake_call_katya

        self.dp.message.middleware(BanCheckMiddleware())
        self.dp.callback_query.middleware(BanCheckMiddleware())
        self.dp.include_router(admin_router)
        self.dp.include_router(user_router)
        self.dp.include_router(user_offer_router)
        self.dp.include_router(donation_router)
        self.dp.include_router(ai_router)

        await init_db()

    def _next_message_id(self) -> int:
        self.message_id += 1
        return self.message_id

    def _chat(self):
        from aiogram.types import Chat
        return Chat(id=self.user_id, type="private", username=self.username, first_name=self.first_name)

    def _user(self):
        from aiogram.types import User
        return User(id=self.user_id, is_bot=False, first_name=self.first_name, username=self.username, language_code="ru")

    def handle_api_call(self, method: Any) -> Any:
        from aiogram.types import Chat, Message, StickerSet

        method_name = method.__class__.__name__
        returning = getattr(method, "__returning__", None)

        if method_name in {"SendMessage", "EditMessageText"}:
            text = getattr(method, "text", None) or ""
            self._print_bot_text(text, edited=(method_name == "EditMessageText"))
            self._capture_markup(getattr(method, "reply_markup", None))
            msg = Message(message_id=self._next_message_id(), date=datetime.now(), chat=self._chat(), text=text)
            self.last_bot_message = msg
            return msg

        if method_name in {"SendPhoto", "EditMessageCaption"}:
            caption = getattr(method, "caption", None) or "[photo]"
            self._print_bot_text(caption, prefix="BOT PHOTO")
            self._capture_markup(getattr(method, "reply_markup", None))
            msg = Message(message_id=self._next_message_id(), date=datetime.now(), chat=self._chat(), caption=caption)
            self.last_bot_message = msg
            return msg

        if method_name == "SendSticker":
            print("\n🤖 BOT STICKER: [sticker]")
            return Message(message_id=self._next_message_id(), date=datetime.now(), chat=self._chat())

        if method_name == "SendChatAction":
            print("\n🤖 BOT ACTION: typing...")
            return True

        if method_name == "AnswerCallbackQuery":
            text = getattr(method, "text", None)
            if text:
                print(f"\n🤖 CALLBACK ANSWER: {text}")
            return True

        if method_name == "DeleteMessage":
            print("\n🤖 BOT: [delete message]")
            return True

        if method_name == "GetStickerSet":
            return StickerSet(name="bot_lab", title="Bot Lab", sticker_type="regular", stickers=[])

        if method_name == "GetChatMember":
            from aiogram.types import ChatMemberMember
            return ChatMemberMember(user=self._user(), status="member")

        # Safe fallback by expected return type.
        if returning is bool:
            print(f"\n🤖 BOT API: {method_name} -> True")
            return True
        if returning is Message:
            print(f"\n🤖 BOT API: {method_name} -> [message]")
            msg = Message(message_id=self._next_message_id(), date=datetime.now(), chat=Chat(id=self.user_id, type="private"))
            self.last_bot_message = msg
            return msg

        print(f"\n🤖 BOT API: {method_name} -> None fallback")
        return None

    def _print_bot_text(self, text: str, *, edited: bool = False, prefix: str = "BOT") -> None:
        marker = "✏️ " if edited else ""
        print(f"\n🤖 {marker}{prefix}:")
        print(text)

    def _capture_markup(self, markup: Any) -> None:
        self.buttons = []
        if not markup:
            return

        # InlineKeyboardMarkup
        inline_keyboard = getattr(markup, "inline_keyboard", None)
        if inline_keyboard:
            for row in inline_keyboard:
                for btn in row:
                    if getattr(btn, "callback_data", None):
                        self.buttons.append(ButtonAction("callback", btn.text, btn.callback_data))
            self.print_buttons()
            return

        # ReplyKeyboardMarkup
        keyboard = getattr(markup, "keyboard", None)
        if keyboard:
            for row in keyboard:
                for btn in row:
                    self.buttons.append(ButtonAction("message", btn.text, btn.text))
            self.print_buttons()

    def print_buttons(self) -> None:
        if not self.buttons:
            print("\n(no buttons)")
            return
        print("\nКнопки:")
        for i, b in enumerate(self.buttons, 1):
            badge = "cb" if b.kind == "callback" else "msg"
            print(f"  {i:>2}. [{badge}] {b.title}")

    async def send_message(self, text: str) -> None:
        from aiogram.types import Message, MessageEntity, Update

        entities = None
        if text.startswith("/"):
            cmd = text.split(maxsplit=1)[0]
            entities = [MessageEntity(type="bot_command", offset=0, length=len(cmd))]

        msg = Message(
            message_id=self._next_message_id(),
            date=datetime.now(),
            chat=self._chat(),
            from_user=self._user(),
            text=text,
            entities=entities,
        )
        self.update_id += 1
        print(f"\n👤 USER: {text}")
        await self.dp.feed_update(self.bot, Update(update_id=self.update_id, message=msg))

    async def send_callback(self, data: str) -> None:
        from aiogram.types import CallbackQuery, Message, Update

        msg = self.last_bot_message or Message(
            message_id=self._next_message_id(),
            date=datetime.now(),
            chat=self._chat(),
            text="[bot message]",
        )
        cb = CallbackQuery(
            id=f"lab-{self.update_id}",
            from_user=self._user(),
            chat_instance="bot-lab-chat-instance",
            message=msg,
            data=data,
        )
        self.update_id += 1
        print(f"\n👤 CALLBACK: {data}")
        await self.dp.feed_update(self.bot, Update(update_id=self.update_id, callback_query=cb))

    async def select_button(self, index: int) -> None:
        if index < 1 or index > len(self.buttons):
            print(f"Нет кнопки #{index}. Напиши !buttons")
            return
        btn = self.buttons[index - 1]
        if btn.kind == "message":
            await self.send_message(btn.value)
        else:
            await self.send_callback(btn.value)

    async def run_repl(self) -> None:
        print("""
╔══════════════════════════════════════════════════════╗
║ Bot Lab: терминальный эмулятор Telegram-бота         ║
╚══════════════════════════════════════════════════════╝
Команды лаборатории:
  !help             показать помощь
  !buttons          показать последние кнопки
  !user ID USERNAME FIRST_NAME  сменить пользователя
  !reset            очистить FSM текущей сессии диспетчера
  !quit             выйти

Пиши обычные сообщения как в Telegram: /start, /cancel, ник, текст кнопки.
Можно нажимать кнопки номером: 1, 2, 3...
""")
        self.print_buttons()
        while True:
            try:
                raw = input("bot-lab> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not raw:
                continue
            if raw.isdigit():
                await self.select_button(int(raw))
                continue
            if raw.startswith("!"):
                await self.handle_lab_command(raw)
                continue
            await self.send_message(raw)

    async def handle_lab_command(self, raw: str) -> None:
        parts = shlex.split(raw)
        cmd = parts[0]
        if cmd in {"!quit", "!exit"}:
            raise SystemExit(0)
        if cmd == "!help":
            print("Пиши /start, /cancel, /katya или номер кнопки. !buttons — список кнопок.")
            return
        if cmd == "!buttons":
            self.print_buttons()
            return
        if cmd == "!user":
            if len(parts) < 4 or not parts[1].isdigit():
                print("Использование: !user 123456 username Имя")
                return
            self.user_id = int(parts[1])
            self.username = parts[2]
            self.first_name = " ".join(parts[3:])
            self.buttons = []
            print(f"Пользователь переключён: id={self.user_id}, @{self.username}, {self.first_name}")
            return
        if cmd == "!reset":
            # User-facing equivalent is /cancel; for dispatcher memory storage, recreate app.
            await self.setup()
            print("FSM/session storage recreated.")
            return
        print(f"Неизвестная lab-команда: {cmd}")


async def amain() -> int:
    parser = argparse.ArgumentParser(description="Run local terminal emulator for the Telegram bot")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite DB path for lab state")
    parser.add_argument("--memory-db", action="store_true", help="Use in-memory SQLite DB")
    parser.add_argument("--use-env", action="store_true", help="Do not override env vars (danger: can use real DB)")
    parser.add_argument("--real-ai", action="store_true", help="Call real AI API instead of fake Katya response")
    parser.add_argument("--user-id", type=int, default=100001)
    parser.add_argument("--username", default="bot_lab_user")
    parser.add_argument("--first-name", default="BotLab")
    args = parser.parse_args()

    if args.memory_db:
        db_url = "sqlite+aiosqlite:///:memory:"
    else:
        db_path = Path(args.db).resolve()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        db_url = f"sqlite+aiosqlite:///{db_path}"

    _install_lab_env(db_url, real_env=args.use_env)

    lab = BotLab(
        user_id=args.user_id,
        username=args.username,
        first_name=args.first_name,
        real_ai=args.real_ai,
    )
    await lab.setup()
    await lab.run_repl()
    return 0


def main() -> None:
    try:
        raise SystemExit(asyncio.run(amain()))
    except SystemExit:
        raise
    except Exception as e:
        print(f"Bot Lab crashed: {e}", file=sys.stderr)
        raise


if __name__ == "__main__":
    main()
