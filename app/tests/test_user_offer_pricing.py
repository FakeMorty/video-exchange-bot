from decimal import Decimal

from app.user_offer_handlers import _calc_offer_stars_price


def test_offer_stars_price_rounds_up_instead_of_undercharging():
    assert _calc_offer_stars_price(Decimal("50")) == 5
    assert _calc_offer_stars_price(Decimal("55")) == 6
    assert _calc_offer_stars_price(Decimal("101")) == 11
