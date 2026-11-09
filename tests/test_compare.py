from evals.compare import results_match


def test_scalar_with_rounding():
    assert results_match([(6.83,)], [(6.8,)])
    assert results_match([(61.8,)], [("61.8%",)])
    assert not results_match([(6.83,)], [(6.9,)])


def test_extra_columns_allowed_in_any_position():
    assert results_match([("Swapped",)], [(8.9, "Swapped")])
    assert results_match([("Action", 219), ("Comedy", 183)], [(219, "x", "action"), (183, "y", "COMEDY")])


def test_missing_column_or_rows_fails():
    assert not results_match([("Action", 219)], [("Action",)])
    assert not results_match([("a",), ("b",)], [("a",)])


def test_order_only_matters_when_requested():
    gold, pred = [("a",), ("b",)], [("b",), ("a",)]
    assert results_match(gold, pred)
    assert not results_match(gold, pred, ordered=True)


def test_duplicates_count():
    assert not results_match([("a",), ("a",)], [("a",), ("b",)])


def test_nulls_and_empty():
    assert results_match([], [])
    assert results_match([(None,)], [(None,)])
    assert not results_match([(None,)], [(0,)])


def test_wrong_column_pairing_rejected():
    # Each gold column must map to a *different* predicted column.
    assert not results_match([("a", "a")], [("a", "b")])
