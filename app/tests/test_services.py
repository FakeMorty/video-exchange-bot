import pytest
from decimal import Decimal
from app.services import to_decimal, round_coin

def test_to_decimal():
    assert to_decimal("10.5") == Decimal("10.5")
    assert to_decimal(5) == Decimal("5")

def test_round_coin():
    val = Decimal("10.556")
    assert round_coin(val) == Decimal("10.55")
    
    val2 = Decimal("10.5")
    assert round_coin(val2) == Decimal("10.50")
