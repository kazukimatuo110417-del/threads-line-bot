from analytics import engagement_score


def test_engagement_score_values_replies_more_than_views() -> None:
    low_engagement = engagement_score({"views": 500})
    replies = engagement_score({"views": 10, "replies": 2})
    assert replies > low_engagement
