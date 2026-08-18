"""Безопасный клиент DonationAlerts для автоматической сверки платежей.

Клиент использует только подтверждённые официальной документацией интерфейсы:
OAuth 2.0, REST `/alerts/donations` и private-канал Centrifugo.
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import aiohttp

from app.logger import get_logger

logger = get_logger(__name__)

API_BASE_URL = "https://www.donationalerts.com/api/v1"
OAUTH_TOKEN_URL = "https://www.donationalerts.com/oauth/token"
CENTRIFUGO_URL = "wss://centrifugo.donationalerts.com/connection/websocket"
DONATION_SCOPES = "oauth-user-show oauth-donation-index oauth-donation-subscribe"


@dataclass(frozen=True)
class DonationEvent:
    donation_id: str
    amount: str | int | float
    currency: str
    message: str
    username: str


def _as_dict(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError):
            return None
        return decoded if isinstance(decoded, dict) else None
    return None


def parse_donation_event(payload: Any) -> DonationEvent | None:
    """Извлекает событие donation из REST-ответа или разных обёрток Centrifugo.

    DonationAlerts может передать полезные поля напрямую, в `data`, `pub.data`
    либо `result.data`; обработчик намеренно принимает только объект с ID,
    суммой и текстовым сообщением.
    """
    queue: list[Any] = [payload]
    seen: set[int] = set()
    while queue:
        value = queue.pop(0)
        marker = id(value)
        if marker in seen:
            continue
        seen.add(marker)
        current = _as_dict(value)
        if not current:
            continue

        donation_id = current.get("id") or current.get("donation_id") or current.get("alert_id")
        amount = current.get("amount") or current.get("amount_main")
        if donation_id is not None and amount is not None:
            return DonationEvent(
                donation_id=str(donation_id),
                amount=amount,
                currency=str(current.get("currency") or "RUB").upper(),
                message=str(current.get("message") or current.get("comment") or ""),
                username=str(current.get("username") or current.get("name") or ""),
            )

        for nested_key in ("data", "result", "params", "push", "pub"):
            nested = current.get(nested_key)
            if nested is not None:
                queue.append(nested)
    return None


class DonationAlertsClient:
    """OAuth-клиент DonationAlerts без хранения секретов в исходном коде."""

    def __init__(
        self,
        *,
        client_id: str = "",
        client_secret: str = "",
        refresh_token: str = "",
        access_token: str = "",
        timeout_seconds: int = 20,
    ) -> None:
        self.client_id = client_id.strip()
        self.client_secret = client_secret.strip()
        self.refresh_token = refresh_token.strip()
        self._static_access_token = access_token.strip()
        self.timeout = aiohttp.ClientTimeout(total=timeout_seconds)

    @property
    def configured(self) -> bool:
        return bool(self._static_access_token or (
            self.client_id and self.client_secret and self.refresh_token
        ))

    async def exchange_authorization_code(
        self,
        http: aiohttp.ClientSession,
        *,
        code: str,
        redirect_uri: str,
    ) -> dict[str, Any]:
        """Обменивает авторизационный код на OAuth-токены владельца."""
        if not self.client_id or not self.client_secret:
            raise RuntimeError("DonationAlerts client credentials are not configured")
        payload = {
            "grant_type": "authorization_code",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "redirect_uri": redirect_uri,
            "code": code,
        }
        async with http.post(OAUTH_TOKEN_URL, data=payload, timeout=self.timeout) as response:
            data = await response.json(content_type=None)
            if response.status != 200 or not data.get("refresh_token"):
                raise RuntimeError(f"DonationAlerts OAuth code exchange failed: HTTP {response.status}")
            return data

    async def get_access_token(self, http: aiohttp.ClientSession) -> str:
        """Возвращает bearer token; refresh token всегда имеет приоритет."""
        if self.client_id and self.client_secret and self.refresh_token:
            payload = {
                "grant_type": "refresh_token",
                "refresh_token": self.refresh_token,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "scope": DONATION_SCOPES,
            }
            async with http.post(OAUTH_TOKEN_URL, data=payload, timeout=self.timeout) as response:
                data = await response.json(content_type=None)
                if response.status != 200 or not data.get("access_token"):
                    raise RuntimeError(
                        f"DonationAlerts OAuth refresh failed: HTTP {response.status}"
                    )
                return str(data["access_token"])

        if self._static_access_token:
            return self._static_access_token
        raise RuntimeError("DonationAlerts OAuth credentials are not configured")

    async def get_profile(self, http: aiohttp.ClientSession, access_token: str) -> dict[str, Any]:
        async with http.get(
            f"{API_BASE_URL}/user/oauth",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=self.timeout,
        ) as response:
            data = await response.json(content_type=None)
            if response.status != 200 or not isinstance(data.get("data"), dict):
                raise RuntimeError(f"DonationAlerts profile request failed: HTTP {response.status}")
            return data["data"]

    async def list_donations(
        self, http: aiohttp.ClientSession, access_token: str
    ) -> list[DonationEvent]:
        async with http.get(
            f"{API_BASE_URL}/alerts/donations",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=self.timeout,
        ) as response:
            data = await response.json(content_type=None)
            if response.status != 200:
                raise RuntimeError(f"DonationAlerts donations request failed: HTTP {response.status}")
        items = data.get("data") if isinstance(data, dict) else []
        return [event for item in items or [] if (event := parse_donation_event(item))]

    async def realtime_events(self) -> AsyncIterator[DonationEvent]:
        """Открывает private-канал донатов и отдаёт подтверждённые события.

        Вызывающий код отвечает за повторные подключения. При ошибке сокета
        его резервирует обычная REST-сверка.
        """
        async with aiohttp.ClientSession(timeout=self.timeout) as http:
            access_token = await self.get_access_token(http)
            profile = await self.get_profile(http, access_token)
            user_id = profile.get("id")
            socket_token = profile.get("socket_connection_token")
            if not user_id or not socket_token:
                raise RuntimeError("DonationAlerts profile lacks socket credentials")

            async with http.ws_connect(CENTRIFUGO_URL, heartbeat=25, timeout=self.timeout) as ws:
                await ws.send_json({"params": {"token": socket_token}, "id": 1})
                connected = await ws.receive_json(timeout=self.timeout.total)
                client_id = ((connected.get("result") or {}).get("client")) if isinstance(connected, dict) else None
                if not client_id:
                    raise RuntimeError("DonationAlerts Centrifugo did not return client ID")

                channel = f"$alerts:donation_{user_id}"
                async with http.post(
                    f"{API_BASE_URL}/centrifuge/subscribe",
                    headers={"Authorization": f"Bearer {access_token}"},
                    json={"channels": [channel], "client": client_id},
                    timeout=self.timeout,
                ) as response:
                    subscription = await response.json(content_type=None)
                    if response.status != 200:
                        raise RuntimeError(
                            f"DonationAlerts channel subscription failed: HTTP {response.status}"
                        )
                channels = subscription.get("channels") if isinstance(subscription, dict) else []
                connection_token = (channels or [{}])[0].get("token")
                if not connection_token:
                    raise RuntimeError("DonationAlerts subscription did not return a channel token")

                await ws.send_json({
                    "params": {"channel": channel, "token": connection_token},
                    "method": 1,
                    "id": 2,
                })

                async for message in ws:
                    if message.type == aiohttp.WSMsgType.TEXT:
                        try:
                            payload = json.loads(message.data)
                        except (TypeError, ValueError):
                            continue
                        event = parse_donation_event(payload)
                        if event:
                            yield event
                    elif message.type in {aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSED}:
                        raise RuntimeError("DonationAlerts Centrifugo connection closed")


async def reconnecting_realtime_events(
    client: DonationAlertsClient,
    stop_event: asyncio.Event,
) -> AsyncIterator[DonationEvent]:
    """Переподключается к real-time каналу с ограниченной паузой при сбоях."""
    delay = 2
    while not stop_event.is_set():
        try:
            async for event in client.realtime_events():
                delay = 2
                if stop_event.is_set():
                    return
                yield event
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("DonationAlerts real-time listener reconnect: %s", exc)
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=delay)
            except asyncio.TimeoutError:
                pass
            delay = min(delay * 2, 60)
