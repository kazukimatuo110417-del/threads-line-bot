import json
import random

from analytics import summarize_learning
from config import get_settings

CATEGORIES = [
    ("経営者", "経営者との接点"),
    ("人事", "人事との接点"),
    ("総務", "総務との接点"),
    ("メリット訴求", "松尾と繋がるメリット"),
    ("交流・質問", "交流・質問型"),
]


def pick_daily_categories() -> list[tuple[str, str]]:
    pool = CATEGORIES[:]
    picked = random.sample(pool, 5)
    if random.random() < 0.5:
        duplicate = random.choice(pool)
        replace_index = random.randrange(5)
        picked[replace_index] = duplicate
        counts = {name: sum(1 for item in picked if item[0] == name) for name, _ in pool}
        if max(counts.values()) > 2:
            return random.sample(pool, 5)
    return picked


def _client():
    settings = get_settings()
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEYが未設定です。")
    from openai import OpenAI

    return OpenAI(api_key=settings.openai_api_key)


def generate_candidates(reason: str = "daily") -> list[dict[str, str]]:
    chosen = pick_daily_categories()
    learning = summarize_learning()
    prompt = {
        "role": "user",
        "content": (
            "Threads法人集客LINE Botの投稿候補を5案作ってください。\n"
            "目的は営業ではなく、経営者・人事・総務との自然な接点作りです。\n"
            "DM、競合調査、他人投稿収集、営業リスト化の要素は入れないでください。\n"
            "各投稿は日本語で、自然なThreads投稿にしてください。\n"
            "同じ文章の言い換えではなく、切り口を変えてください。\n"
            "松尾本人の商品を直接販売しないでください。\n"
            f"今回の5案のカテゴリはこの順番です: {chosen}\n"
            f"過去投稿の分析メモ: {learning}\n"
            f"生成理由: {reason}\n"
            "JSONオブジェクトだけで返してください。形式は "
            '{"candidates":[{"target_category":"...","post_category":"...","body":"..."}]} '
            "です。candidatesは必ず5件にしてください。"
        ),
    }
    response = _client().chat.completions.create(
        model=get_settings().openai_model,
        messages=[
            {
                "role": "system",
                "content": (
                    "あなたは法人向けThreads運用に強い編集者です。"
                    "ユーザー未承認の投稿は絶対に投稿されない前提で、候補文だけを作ります。"
                ),
            },
            prompt,
        ],
        response_format={"type": "json_object"},
        temperature=0.9,
    )
    content = response.choices[0].message.content or "{}"
    parsed = json.loads(content)
    items = parsed.get("candidates", parsed if isinstance(parsed, list) else [])
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
    if len(candidates) != 5 or any(not item["body"] for item in candidates):
        raise RuntimeError("AI候補の生成に失敗しました。もう一度お試しください。")
    return candidates


def polish_text(original: str) -> str:
    response = _client().chat.completions.create(
        model=get_settings().openai_model,
        messages=[
            {
                "role": "system",
                "content": (
                    "ユーザーの文章の意味や方向性を変えず、Threads投稿として読みやすく整えてください。"
                    "新しい主張、実績、商品説明は追加しないでください。"
                ),
            },
            {"role": "user", "content": original},
        ],
        temperature=0.4,
    )
    return (response.choices[0].message.content or original).strip()
