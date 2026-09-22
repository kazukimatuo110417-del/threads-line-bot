from ai import pick_daily_categories


def test_pick_daily_categories_returns_five_without_extreme_bias() -> None:
    picked = pick_daily_categories()
    assert len(picked) == 5
    counts = {}
    for target, _category in picked:
        counts[target] = counts.get(target, 0) + 1
    assert max(counts.values()) <= 2
