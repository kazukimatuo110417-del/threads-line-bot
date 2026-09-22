import json
from collections import defaultdict

from database import list_posts


def engagement_score(metrics: dict[str, int]) -> float:
    likes = metrics.get("likes", 0)
    replies = metrics.get("replies", 0)
    reposts = metrics.get("reposts", 0)
    quotes = metrics.get("quotes", 0)
    shares = metrics.get("shares", 0)
    views = metrics.get("views", 0)
    return likes + replies * 3 + reposts * 2 + quotes * 2 + shares * 2 + min(views, 1000) * 0.01


def summarize_learning() -> str:
    posts = list_posts(limit=50)
    if not posts:
        return "まだ投稿データがありません。経営者・人事・総務・メリット訴求・交流質問を大きく偏らせず試してください。"

    grouped: dict[str, list[float]] = defaultdict(list)
    for post in posts:
        key = f"{post['target_category']}×{post['post_category']}"
        grouped[key].append(float(post["analysis_score"]))

    ranked = sorted(
        ((key, sum(scores) / len(scores), len(scores)) for key, scores in grouped.items()),
        key=lambda item: item[1],
        reverse=True,
    )
    if not ranked:
        return "分析できる投稿データがまだ少ないため、幅広い切り口を試してください。"

    top = ranked[:3]
    bottom = ranked[-3:]
    top_text = "、".join(f"{key}(平均{score:.1f}/投稿{count}件)" for key, score, count in top)
    bottom_text = "、".join(f"{key}(平均{score:.1f}/投稿{count}件)" for key, score, count in bottom)
    return (
        "過去投稿では、反応が比較的良い方向性は "
        f"{top_text} です。弱めの方向性は {bottom_text} です。"
        "良い方向性は少し増やしつつ、同じ文章の繰り返しは避けてください。"
    )


def decode_metrics(metrics_json: str) -> dict[str, int]:
    try:
        data = json.loads(metrics_json or "{}")
        return {str(k): int(v or 0) for k, v in data.items()}
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
