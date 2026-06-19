from magi.memory.hybrid_retrieval.service_policy import parse_turn_number


def test_parse_turn_number_supports_locomo_dialog_turn_ids() -> None:
    assert parse_turn_number("D1:10") == 10


def test_parse_turn_number_supports_underscore_turn_ids() -> None:
    assert parse_turn_number("turn_10") == 10


def test_parse_turn_number_ignores_random_product_turn_ids() -> None:
    assert parse_turn_number("turn_01KVF31NGF5DBAHTA5TG33ZA6A") is None
