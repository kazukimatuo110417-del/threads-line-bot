from database import get_candidate_batch


NUMBER_LABELS = ["①", "②", "③", "④", "⑤"]


def format_candidates(candidates: list[dict[str, str]]) -> str:
    parts = ["今日のThreads候補です👇"]
    for index, item in enumerate(candidates, start=1):
        parts.append(
            f"\n{NUMBER_LABELS[index - 1]} {item['target_category']}向け\n{item['body']}"
        )
    return "\n".join(parts)


def format_selected(candidate: dict[str, str]) -> str:
    return f"選んだ投稿本文です👇\n\n{candidate['body']}"


def selected_candidate(batch_id: int, number_text: str) -> dict[str, str] | None:
    if number_text not in NUMBER_LABELS:
        return None
    candidates = get_candidate_batch(batch_id)
    index = NUMBER_LABELS.index(number_text)
    if index >= len(candidates):
        return None
    return candidates[index]
