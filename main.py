import base64
import hashlib
import hmac
import json
import logging
import os
import random
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Header, HTTPException, Request
from openai import OpenAI

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

LINE_API_BASE = "https://api.line.me/v2/bot"
NUMBER_LABELS = ["①", "②", "③", "④", "⑤"]
CATEGORIES = [
    ("経営者", "経営者との接点"),
    ("人事", "人事との接点"),
    ("総務", "総務との接点"),
    ("メリット訴求", "松尾と繋がるメリット"),
    ("交流・質問", "交流・質問型"),
]

app = FastAPI(title="Threads法人集客LINE Bot")
scheduler = AsyncIOScheduler(timezone=ZoneInfo(os.getenv("APP_TIMEZONE", "Asia/Tokyo")))


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def db_path() -> Path:
    path = Path(os.getenv("DATABASE_PATH", "data/bot.sqlite3"))
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


@contextmanager
def connect():
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS app_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS candidate_batches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                candidates_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                body TEXT NOT NULL,
                target_category TEXT NOT NULL,
                post_category TEXT NOT NULL,
                posted_at TEXT NOT NULL,
                threads_post_id TEXT NOT NULL,
                metrics_json TEXT NOT NULL DEFAULT '{}',
                analysis_score REAL NOT NULL DEFAULT 0,
                last_metrics_at TEXT
            );
            """
        )


def get_state(key: str, default: Any = None) -> Any:
    with connect() as conn:
        row = conn.execute("SELECT value FROM app_state WHERE key = ?", (key,)).fetchone()
    return default if row is None else json.loads(row["value"])


def set_state(key: str, value: Any) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO app_state (key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (key, json.dumps(value, ensure_ascii=False), utc_now_iso()),
        )


def save_candidate_batch(candidates: list[dict[str, str]]) -> int:
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO candidate_batches (candidates_json, created_at) VALUES (?, ?)",
            (json.dumps(candidates, ensure_ascii=False), utc_now_iso()),
        )
        return int(cur.lastrowid)


def get_candidate_batch(batch_id: int) -> list[dict[str, str]]:
    with connect() as conn:
        row = conn.execute("SELECT candidates_json FROM candidate_batches WHERE id = ?", (batch_id,)).fetchone()
    return [] if row is None else json.loads(row["candidates_json"])


def save_post(body: str, target_category: str, post_category: str, threads_post_id: str) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO posts (body, target_category, post_category, posted_at, threads_post_id, metrics_json)
            VALUES (?, ?, ?, ?, ?, '{}')
            """,
            (body, target_category, post_category, utc_now_iso(), threads_post_id),
        )


def engagement_score(metrics: dict[str, int]) -> float:
    return (
        metrics.get("likes", 0)
        + metrics.get("replies", 0) * 3
        + metrics.get("reposts", 0) * 2
        + metrics.get("quotes", 0) * 2
        + metrics.get("shares", 0) * 2
        + min(metrics.get("views", 0), 1000) * 0.01
    )


def summarize_learning() -> str:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM posts ORDER BY posted_at DESC LIMIT 50").fetchall()
    if not rows:
        return "まだ投稿データがありません。5カテゴリを大きく偏らせず、反応が出る切り口を試してください。"
    groups: dict[str, list[float]] = {}
    for row in rows:
        key = f"{row['target_category']}×{row['post_category']}"
        groups.setdefault(key, []).append(float(row["analysis_score"]))
    ranked = sorted(((k, sum(v) / len(v), len(v)) for k, v in groups.items()), key=lambda x: x[1], reverse=True)
    top = "、".join(f"{k}(平均{s:.1f}/投稿{n}件)" for k, s, n in ranked[:3])
    return f"過去投稿では {top} が比較的良いです。同じ文章の繰り返しは避け、良い方向性を少し増やしてください。"


def pick_daily_categories() -> list[tuple[str, str]]:
    picked = random.sample(CATEGORIES, 5)
    if random.random() < 0.5:
        picked[random.randrange(5)] = random.choice(CATEGORIES)
        counts = {name: sum(1 for item in picked if item[0] == name) for name, _ in CATEGORIES}
        if max(counts.values()) > 2:
            return random.sample(CATEGORIES, 5)
    return picked


def openai_client() -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEYが未設定です。")
    return OpenAI(api_key=api_key)


def generate_candidates(reason: str) -> list[dict[str, str]]:
    chosen = pick_daily_categories()
    response = openai_client().chat.completions.create(
        model=os.getenv("OPENAI_MODEL", "gpt-4.1"),
        messages=[
            {
                "role": "system",
                "content": "あなたは法人向けThreads運用に強い編集者です。営業ではなく自然な接点作りを目的にします。JSONだけで返します。",
            },
            {
                "role": "user",
                "content": (
                    "Threads投稿候補を5案作ってください。目的は経営者・人事・総務との自然な接点作りです。"
                    "DM、競合調査、他人投稿収集、営業リスト化は禁止。商品を直接販売しない。"
                    f"今回のカテゴリ順: {chosen}\n"
                    f"過去分析: {summarize_learning()}\n"
                    f"生成理由: {reason}\n"
                    '形式は {"candidates":[{"target_category":"...","post_category":"...","body":"..."}]} のJSONだけ。必ず5件。'
                ),
            },
        ],
        response_format={"type": "json_object"},
        temperature=0.9,
    )
    parsed = json.loads(response.choices[0].message.content or "{}")
    items = parsed.get("candidates", [])
    candidates = []
    for index, item in enumerate(items[:5]):
        fallback_target, fallback_category = chosen[index]
        candidates.append(
            {
                "target_category": str(item.get("target_category") or fallback_target),
                "post_category": str(item.get("post_category") or fallback_category),
                "body": str(item.get("body") or "").strip(),
            }
        )
    if len(candidates) != 5 or any(not c["body"] for c in candidates):
        raise RuntimeError("AI候補の生成に失敗しました。もう一度お試しください。")
    return candidates


def polish_text(original: str) -> str:
    response = openai_client().chat.completions.create(
        model=os.getenv("OPENAI_MODEL", "gpt-4.1"),
        messages=[
            {"role": "system", "content": "意味や方向性を変えず、Threads投稿として自然に整えてください。新しい実績や商品説明は追加しないでください。"},
            {"role": "user", "content": original},
        ],
        temperature=0.4,
    )
    return (response.choices[0].message.content or original).strip()


def quick_reply(labels: list[str]) -> dict[str, Any]:
    return {"items": [{"type": "action", "action": {"type": "message", "label": label, "text": label}} for label in labels]}


def text_message(text: str, replies: list[str] | None = None) -> dict[str, Any]:
    msg: dict[str, Any] = {"type": "text", "text": text}
    if replies:
        msg["quickReply"] = quick_reply(replies)
    return msg


async def line_post(path: str, payload: dict[str, Any]) -> None:
    token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
    if not token:
        raise RuntimeError("LINE_CHANNEL_ACCESS_TOKENが未設定です。")
    async with httpx.AsyncClient(timeout=20) as client:
        res = await client.post(f"{LINE_API_BASE}{path}", headers={"Authorization": f"Bearer {token}"}, json=payload)
    res.raise_for_status()


async def reply_message(reply_token: str, messages: list[dict[str, Any]]) -> None:
    await line_post("/message/reply", {"replyToken": reply_token, "messages": messages})


async def push_message(user_id: str, messages: list[dict[str, Any]]) -> None:
    await line_post("/message/push", {"to": user_id, "messages": messages})


def verify_signature(body: bytes, signature: str | None) -> bool:
    secret = os.getenv("LINE_CHANNEL_SECRET", "").encode("utf-8")
    if not secret:
        return True
    expected = base64.b64encode(hmac.new(secret, body, hashlib.sha256).digest()).decode("utf-8")
    return hmac.compare_digest(expected, signature or "")


def format_candidates(candidates: list[dict[str, str]]) -> str:
    parts = ["今日のThreads候補です👇"]
    for index, item in enumerate(candidates, start=1):
        parts.append(f"\n{NUMBER_LABELS[index - 1]} {item['target_category']}向け\n{item['body']}")
    return "\n".join(parts)


async def send_candidates(user_id: str, reply_token: str | None = None, reason: str = "daily") -> None:
    candidates = generate_candidates(reason)
    batch_id = save_candidate_batch(candidates)
    set_state("current_selection", {"batch_id": batch_id, "body": "", "target_category": "", "post_category": ""})
    msg = text_message(format_candidates(candidates), NUMBER_LABELS + ["作り直す"])
    if reply_token:
        await reply_message(reply_token, [msg])
    else:
        await push_message(user_id, [msg])


def selected_candidate(batch_id: int, number_text: str) -> dict[str, str] | None:
    if number_text not in NUMBER_LABELS:
        return None
    candidates = get_candidate_batch(batch_id)
    index = NUMBER_LABELS.index(number_text)
    return None if index >= len(candidates) else candidates[index]


async def publish_text(text: str) -> str:
    token = os.getenv("THREADS_ACCESS_TOKEN", "")
    if not token:
        raise RuntimeError("THREADS_ACCESS_TOKENが未設定です。")
    base = os.getenv("THREADS_API_BASE", "https://graph.threads.net/v1.0").rstrip("/")
    async with httpx.AsyncClient(timeout=30) as client:
        create = await client.post(f"{base}/me/threads", data={"access_token": token, "media_type": "TEXT", "text": text})
        create.raise_for_status()
        publish = await client.post(f"{base}/me/threads_publish", data={"access_token": token, "creation_id": create.json()["id"]})
        publish.raise_for_status()
        return str(publish.json()["id"])


async def get_post_insights(threads_post_id: str) -> dict[str, int]:
    token = os.getenv("THREADS_ACCESS_TOKEN", "")
    if not token:
        return {}
    base = os.getenv("THREADS_API_BASE", "https://graph.threads.net/v1.0").rstrip("/")
    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.get(f"{base}/{threads_post_id}/insights", params={"access_token": token, "metric": "views,likes,replies,reposts,quotes,shares"})
        if res.status_code >= 400:
            res = await client.get(f"{base}/{threads_post_id}/insights", params={"access_token": token, "metric": "likes,replies,reposts,quotes"})
        res.raise_for_status()
    metrics: dict[str, int] = {}
    for item in res.json().get("data", []):
        value = item.get("total_value", {}).get("value", 0)
        if item.get("name"):
            metrics[str(item["name"])] = int(value or 0)
    return metrics


async def refresh_metrics() -> None:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM posts ORDER BY posted_at DESC").fetchall()
    for row in rows:
        metrics = await get_post_insights(row["threads_post_id"])
        if metrics:
            with connect() as conn:
                conn.execute(
                    "UPDATE posts SET metrics_json = ?, analysis_score = ?, last_metrics_at = ? WHERE id = ?",
                    (json.dumps(metrics, ensure_ascii=False), engagement_score(metrics), utc_now_iso(), row["id"]),
                )


async def handle_text(user_id: str, reply_token: str, text: str) -> None:
    set_state("line_user_id", user_id)
    text = text.strip()
    flow = get_state("flow", "idle")
    selection = get_state("current_selection", {})

    if text == "候補":
        set_state("flow", "idle")
        await send_candidates(user_id, reply_token, "manual")
        return
    if text == "作り直す":
        await send_candidates(user_id, reply_token, "retry")
        return
    if text in NUMBER_LABELS:
        candidate = selected_candidate(int(selection.get("batch_id") or 0), text)
        if not candidate:
            await reply_message(reply_token, [text_message("候補が見つかりません。「候補」と送って作り直してください。")])
            return
        set_state("current_selection", candidate)
        set_state("flow", "selected")
        await reply_message(reply_token, [text_message(f"選んだ投稿本文です👇\n\n{candidate['body']}", ["このまま投稿", "修正する", "別案を見る", "やめる"])])
        return
    if text == "別案を見る":
        await send_candidates(user_id, reply_token, "alternative")
        return
    if text == "修正する":
        set_state("flow", "awaiting_revision")
        await reply_message(reply_token, [text_message("修正版の文章をそのまま送ってください")])
        return
    if flow == "awaiting_revision":
        updated = {"body": text, "target_category": selection.get("target_category") or "修正投稿", "post_category": selection.get("post_category") or "ユーザー修正"}
        set_state("current_selection", updated)
        set_state("flow", "revised")
        await reply_message(reply_token, [text_message(f"修正版はこちらです👇\n\n{text}", ["このまま投稿", "AIで整える", "やめる"])])
        return
    if text == "AIで整える":
        body = selection.get("body")
        if not body:
            await reply_message(reply_token, [text_message("整える文章が見つかりません。「候補」と送ってください。")])
            return
        polished = polish_text(body)
        selection["body"] = polished
        set_state("current_selection", selection)
        set_state("flow", "final_confirm")
        await reply_message(reply_token, [text_message(f"AIで整えた最終本文です👇\n\n{polished}", ["投稿する", "やめる"])])
        return
    if text == "このまま投稿":
        body = selection.get("body")
        if not body:
            await reply_message(reply_token, [text_message("投稿本文が見つかりません。「候補」と送ってください。")])
            return
        set_state("flow", "final_confirm")
        await reply_message(reply_token, [text_message(f"最終確認です👇\n\n{body}", ["投稿する", "やめる"])])
        return
    if text == "投稿する":
        body = selection.get("body")
        if not body:
            await reply_message(reply_token, [text_message("投稿本文が見つかりません。「候補」と送ってください。")])
            return
        threads_post_id = await publish_text(body)
        save_post(body, selection.get("target_category") or "未分類", selection.get("post_category") or "未分類", threads_post_id)
        set_state("flow", "idle")
        set_state("current_selection", {})
        await reply_message(reply_token, [text_message("Threadsへ投稿しました。投稿データも保存しました。")])
        return
    if text == "やめる":
        set_state("flow", "idle")
        set_state("current_selection", {})
        await reply_message(reply_token, [text_message("中止しました。必要になったら「候補」と送ってください。")])
        return
    await reply_message(reply_token, [text_message("操作する場合は「候補」と送ってください。")])


@app.on_event("startup")
async def startup() -> None:
    init_db()
    scheduler.add_job(morning_push, "cron", hour=7, minute=0, id="morning_push", replace_existing=True)
    scheduler.add_job(refresh_metrics, "cron", hour=6, minute=40, id="refresh_metrics", replace_existing=True)
    scheduler.start()


@app.on_event("shutdown")
async def shutdown() -> None:
    scheduler.shutdown(wait=False)


@app.get("/")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/line/webhook")
async def line_webhook(request: Request, x_line_signature: str | None = Header(default=None)) -> dict[str, str]:
    body = await request.body()
    if not verify_signature(body, x_line_signature):
        raise HTTPException(status_code=400, detail="Invalid LINE signature")
    payload = await request.json()
    for event in payload.get("events", []):
        user_id = event.get("source", {}).get("userId")
        if user_id:
            set_state("line_user_id", user_id)
        if event.get("type") == "follow" and user_id:
            await push_message(user_id, [text_message("友だち追加ありがとうございます。「候補」と送るとThreads投稿候補を5案作ります。")])
        if event.get("type") == "message" and event.get("message", {}).get("type") == "text" and user_id:
            await handle_text(user_id, event["replyToken"], event["message"].get("text", ""))
    return {"status": "ok"}


async def morning_push() -> None:
    user_id = os.getenv("LINE_USER_ID", "") or get_state("line_user_id", "")
    if not user_id:
        logger.warning("LINE_USER_ID is not set yet.")
        return
    try:
        await refresh_metrics()
    except Exception:
        logger.exception("Failed to refresh metrics before morning push.")
    await send_candidates(user_id, reason="daily")
