import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Header, HTTPException, Request
from zoneinfo import ZoneInfo

from bot import handle_text, refresh_metrics, send_candidates
from config import get_settings
from database import get_state, init_db, set_state
from line_client import push_message, text_message, verify_signature

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Threads法人集客LINE Bot")
scheduler = AsyncIOScheduler(timezone=ZoneInfo(get_settings().app_timezone))


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
    if get_settings().line_channel_secret and not verify_signature(body, x_line_signature):
        raise HTTPException(status_code=400, detail="Invalid LINE signature")

    payload = await request.json()
    for event in payload.get("events", []):
        event_type = event.get("type")
        source = event.get("source", {})
        user_id = source.get("userId")
        if user_id:
            set_state("line_user_id", user_id)

        if event_type == "follow" and user_id:
            await push_message(
                user_id,
                [text_message("友だち追加ありがとうございます。「候補」と送るとThreads投稿候補を5案作ります。")],
            )
            continue

        if event_type == "message" and event.get("message", {}).get("type") == "text" and user_id:
            await handle_text(user_id, event["replyToken"], event["message"].get("text", ""))

    return {"status": "ok"}


async def morning_push() -> None:
    configured = get_settings().line_user_id
    stored = get_state("line_user_id", "")
    user_id = configured or stored
    if not user_id:
        logger.warning("LINE_USER_ID is not set yet.")
        return
    try:
        await refresh_metrics()
    except Exception:
        logger.exception("Failed to refresh metrics before morning push.")
    await send_candidates(user_id, reason="daily")
