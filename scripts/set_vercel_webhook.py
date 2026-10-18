#!/usr/bin/env python3
"""Ставит Telegram-вебхук на Vercel-деплой бота (и умеет его снимать).

Использование:
    BOT_TOKEN=123:ABC WEBHOOK_BASE=https://video-exchange-bot-xxx.vercel.app \\
        python scripts/set_vercel_webhook.py

    # с секретом (тот же WEBHOOK_SECRET должен стоять в env vars Vercel):
    BOT_TOKEN=... WEBHOOK_BASE=... WEBHOOK_SECRET=s3cr3t \\
        python scripts/set_vercel_webhook.py

    # снять вебхук и вернуть боту возможность polling:
    BOT_TOKEN=... python scripts/set_vercel_webhook.py --delete

Переменные:
    BOT_TOKEN      — токен от @BotFather (обязательно)
    WEBHOOK_BASE   — публичный URL деплоя без завершающего слэша
    WEBHOOK_PATH   — путь вебхука (по умолчанию /webhook)
    WEBHOOK_SECRET — опционально; Telegram будет присылать его в заголовке
                     X-Telegram-Bot-Api-Secret-Token

Напоминание: webhook и polling взаимоисключающи — не держите одновременно
включёнными Render/Docker-инстанс (polling) и Vercel-вебхук.
"""

from __future__ import annotations

import os
import sys
import urllib.request
import json


def _call(token: str, method: str, payload: dict) -> dict:
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/{method}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 (фиксированный хост Telegram)
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        print("BOT_TOKEN is not set", file=sys.stderr)
        return 1

    if "--delete" in sys.argv:
        print(_call(token, "deleteWebhook", {"drop_pending_updates": False}))
        print("Webhook удалён. Теперь бот снова может работать через polling.")
        return 0

    base = os.getenv("WEBHOOK_BASE", "").strip().rstrip("/")
    if not base.startswith("https://"):
        print("WEBHOOK_BASE must be an https:// URL of the Vercel deployment", file=sys.stderr)
        return 1
    path = os.getenv("WEBHOOK_PATH", "/webhook").strip() or "/webhook"
    url = f"{base}{path}"

    payload: dict = {"url": url, "drop_pending_updates": False}
    secret = os.getenv("WEBHOOK_SECRET", "").strip()
    if secret:
        payload["secret_token"] = secret

    print(f"Setting webhook to {url} ...")
    print(_call(token, "setWebhook", payload))
    print(_call(token, "getWebhookInfo", {}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
