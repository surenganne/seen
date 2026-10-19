from seen_core import pricing


def test_synthetic_zero_token_messages_do_not_void_the_turn_cost() -> None:
    """Claude Code writes `<synthetic>` assistant messages with no usage; they must not make a real turn unpriced."""
    real = {"tok_in": 100, "tok_out": 1000, "tok_cache_read": 0, "tok_cache_write": 0}
    alone, _ = pricing.cost({"claude-opus-5-5": real})
    both, _ = pricing.cost({"claude-opus-5-5": real, "<synthetic>": {"tok_in": 0, "tok_out": 0}})
    assert alone and both == alone


def test_unpriced_model_with_tokens_is_still_unknown() -> None:
    assert pricing.cost({"some-unpriced-model": {"tok_in": 5, "tok_out": 5}})[0] is None
