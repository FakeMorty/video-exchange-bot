from types import SimpleNamespace

from app.user_handlers import _best_event_badge


def test_best_event_badge_filters_by_target_type():
    events = [
        SimpleNamespace(name="CoinsOnly", discount_percent=30, applies_vip=False, applies_coins=True),
        SimpleNamespace(name="VipOnly", discount_percent=20, applies_vip=True, applies_coins=False),
    ]

    vip_badge = _best_event_badge(events, "vip")
    coins_badge = _best_event_badge(events, "coins")

    assert "VipOnly" in vip_badge
    assert "CoinsOnly" not in vip_badge
    assert "CoinsOnly" in coins_badge
    assert "VipOnly" not in coins_badge
