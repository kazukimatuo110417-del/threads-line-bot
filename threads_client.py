from typing import Any

import httpx

from config import get_settings


def _auth_params() -> dict[str, str]:
    token = get_settings().threads_access_token
    if not token:
        raise RuntimeError("THREADS_ACCESS_TOKENが未設定です。")
    return {"access_token": token}


async def publish_text(text: str) -> str:
    base = get_settings().threads_api_base.rstrip("/")
    async with httpx.AsyncClient(timeout=30) as client:
        create_response = await client.post(
            f"{base}/me/threads",
            data={**_auth_params(), "media_type": "TEXT", "text": text},
        )
        create_response.raise_for_status()
        creation_id = create_response.json()["id"]

        publish_response = await client.post(
            f"{base}/me/threads_publish",
            data={**_auth_params(), "creation_id": creation_id},
        )
        publish_response.raise_for_status()
        return str(publish_response.json()["id"])


async def get_post_insights(threads_post_id: str) -> dict[str, int]:
    base = get_settings().threads_api_base.rstrip("/")
    metrics = "views,likes,replies,reposts,quotes,shares"
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            f"{base}/{threads_post_id}/insights",
            params={**_auth_params(), "metric": metrics},
        )
        if response.status_code >= 400:
            response = await client.get(
                f"{base}/{threads_post_id}/insights",
                params={**_auth_params(), "metric": "likes,replies,reposts,quotes"},
            )
        response.raise_for_status()
    return _normalize_insights(response.json())


def _normalize_insights(payload: dict[str, Any]) -> dict[str, int]:
    result: dict[str, int] = {}
    for item in payload.get("data", []):
        name = item.get("name")
        value = 0
        if "total_value" in item:
            value = item["total_value"].get("value", 0)
        elif item.get("values"):
            value = item["values"][-1].get("value", 0)
        if name:
            result[str(name)] = int(value or 0)
    return result
