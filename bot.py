from app import ai
from analytics import engagement_score
from database import (
    get_state,
    list_posts_for_metrics,
    save_candidate_batch,
    save_post,
    set_state,
    update_post_metrics,
)
from line_client import push_message, reply_message, text_message
from messages import NUMBER_LABELS, format_candidates, format_selected, selected_candidate
from threads_client import get_post_insights, publish_text


async def send_candidates(user_id: str, reply_token: str | None = None, reason: str = "daily") -> None:
    candidates = ai.generate_candidates(reason=reason)
    batch_id = save_candidate_batch(candidates)
    set_state(
        "current_selection",
        {"batch_id": batch_id, "body": "", "target_category": "", "post_category": ""},
    )
    message = text_message(format_candidates(candidates), NUMBER_LABELS + ["作り直す"])
    if reply_token:
        await reply_message(reply_token, [message])
    else:
        await push_message(user_id, [message])


async def handle_text(user_id: str, reply_token: str, text: str) -> None:
    set_state("line_user_id", user_id)
    text = text.strip()
    flow = get_state("flow", "idle")
    selection = get_state("current_selection", {})

    if text == "候補":
        set_state("flow", "idle")
        await send_candidates(user_id, reply_token, reason="manual")
        return

    if text == "作り直す":
        set_state("flow", "idle")
        await send_candidates(user_id, reply_token, reason="retry")
        return

    if text in NUMBER_LABELS:
        candidate = selected_candidate(int(selection.get("batch_id") or 0), text)
        if not candidate:
            await reply_message(reply_token, [text_message("候補が見つかりません。「候補」と送って作り直してください。")])
            return
        set_state("current_selection", candidate)
        set_state("flow", "selected")
        await reply_message(
            reply_token,
            [text_message(format_selected(candidate), ["このまま投稿", "修正する", "別案を見る", "やめる"])],
        )
        return

    if text == "別案を見る":
        await send_candidates(user_id, reply_token, reason="alternative")
        return

    if text == "修正する":
        set_state("flow", "awaiting_revision")
        await reply_message(reply_token, [text_message("修正版の文章をそのまま送ってください")])
        return

    if flow == "awaiting_revision":
        updated = {
            "body": text,
            "target_category": selection.get("target_category") or "修正投稿",
            "post_category": selection.get("post_category") or "ユーザー修正",
        }
        set_state("current_selection", updated)
        set_state("flow", "revised")
        await reply_message(
            reply_token,
            [text_message(f"修正版はこちらです👇\n\n{text}", ["このまま投稿", "AIで整える", "やめる"])],
        )
        return

    if text == "AIで整える":
        body = selection.get("body")
        if not body:
            await reply_message(reply_token, [text_message("整える文章が見つかりません。「候補」と送ってください。")])
            return
        polished = ai.polish_text(body)
        selection["body"] = polished
        set_state("current_selection", selection)
        set_state("flow", "final_confirm")
        await reply_message(
            reply_token,
            [text_message(f"AIで整えた最終本文です👇\n\n{polished}", ["投稿する", "やめる"])],
        )
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
        save_post(
            body=body,
            target_category=selection.get("target_category") or "未分類",
            post_category=selection.get("post_category") or "未分類",
            threads_post_id=threads_post_id,
        )
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


async def refresh_metrics() -> None:
    for post in list_posts_for_metrics():
        metrics = await get_post_insights(post["threads_post_id"])
        update_post_metrics(post["id"], metrics, engagement_score(metrics))
