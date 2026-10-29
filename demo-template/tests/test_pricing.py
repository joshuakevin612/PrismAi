from app.main import calculate_total


def test_items_without_a_price_are_zero():
    assert calculate_total([{'price': 10}, {}]) == 10


def test_empty_items():
    assert calculate_total([]) == 0
