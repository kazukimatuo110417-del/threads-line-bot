import base64
import hashlib
import hmac
from typing import Any

import httpx

from config import get_settings


LINE_API_BASE = "https://api.line.me/v2/bot"


def verify_signature(body: bytes, signature: str | None) -> bool:
    secret = get_settings().line_channel_secret.encode("utf-8")
    digest = hmac.new(secret, body, hashlib.sha256).digest()
    expected = base64.b64encode(digest).decode("utf-8")
    return hmac.compare_digest(expected, signature or "")


def quick_reply(labels: list[str]) -> dict[str, Any]:
    return {
        "items": [
            {
                "type": "action",
                "action": {"type": "message", "label": label, "text": label},
            }
            for label in labels
        ]
    }


def text_message(text: str, replies: list[str] | None = None) -> dict[str, Any]:
    message: dict[str, Any] = {"type": "text", "text": text}
    if replies:
        message["quickReply"] = quick_reply(replies)
    return message


async def reply_message(reply_token: str, messages: list[dict[str, Any]]) -> None:
    await _post("/message/reply", {"replyToken": reply_token, "messages": messages})


async def push_message(user_id: str, messages: list[dict[str, Any]]) -> None:
    await _post("/message/push", {"to": user_id, "messages": messages})


async def _post(path: str, payload: dict[str, Any]) -> None:
    token = get_settings().line_channel_access_token
    if not token:
        raise RuntimeError("LINE_CHANNEL_ACCESS_TOKENが未設定です。")
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            f"{LINE_API_BASE}{path}",
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
        )
    response.raise_for_status()
