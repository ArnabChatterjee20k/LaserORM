import pytest

from src.laserorm.core.model import Model


class AccountModel(Model):
    uid: int
    name: str
    active: bool
    score: int


def test_simple_equal_expression_dict():
    expr = AccountModel.uid == 1
    assert expr.to_dict() == {"type": "==", "key": "uid", "value": 1}


def test_all_comparison_ops_to_dict():
    assert (AccountModel.uid == 1).to_dict() == {"type": "==", "key": "uid", "value": 1}
    assert (AccountModel.uid != 2).to_dict() == {"type": "!=", "key": "uid", "value": 2}
    assert (AccountModel.score < 3).to_dict() == {
        "type": "<",
        "key": "score",
        "value": 3,
    }
    assert (AccountModel.score <= 4).to_dict() == {
        "type": "<=",
        "key": "score",
        "value": 4,
    }
    assert (AccountModel.score > 5).to_dict() == {
        "type": ">",
        "key": "score",
        "value": 5,
    }
    assert (AccountModel.score >= 6).to_dict() == {
        "type": ">=",
        "key": "score",
        "value": 6,
    }


def test_and_expression_to_dict():
    expr = (AccountModel.uid == 1) & (AccountModel.uid == 2)
    assert expr.to_dict() == {
        "type": "and",
        "left": {"type": "==", "key": "uid", "value": 1},
        "right": {"type": "==", "key": "uid", "value": 2},
    }


def test_or_expression_to_dict():
    expr = (AccountModel.name == "alice") | (AccountModel.name == "bob")
    assert expr.to_dict() == {
        "type": "or",
        "left": {"type": "==", "key": "name", "value": "alice"},
        "right": {"type": "==", "key": "name", "value": "bob"},
    }


def test_nested_and_or_expression():
    # (uid == 1) AND ((score > 10) OR (active == True))
    expr = (AccountModel.uid == 1) & (
        (AccountModel.score > 10) | (AccountModel.active == True)
    )
    assert expr.to_dict() == {
        "type": "and",
        "left": {"type": "==", "key": "uid", "value": 1},
        "right": {
            "type": "or",
            "left": {"type": ">", "key": "score", "value": 10},
            "right": {"type": "==", "key": "active", "value": True},
        },
    }


def test_deeply_nested_mixed_expression():
    # ((uid == 1) AND (name != "root")) OR ((score <= 99) AND ((active == True) OR (score >= 50)))
    left = (AccountModel.uid == 1) & (AccountModel.name != "root")
    right = (AccountModel.score <= 99) & (
        (AccountModel.active == True) | (AccountModel.score >= 50)
    )
    expr = left | right
    assert expr.to_dict() == {
        "type": "or",
        "left": {
            "type": "and",
            "left": {"type": "==", "key": "uid", "value": 1},
            "right": {"type": "!=", "key": "name", "value": "root"},
        },
        "right": {
            "type": "and",
            "left": {"type": "<=", "key": "score", "value": 99},
            "right": {
                "type": "or",
                "left": {"type": "==", "key": "active", "value": True},
                "right": {"type": ">=", "key": "score", "value": 50},
            },
        },
    }


def test_left_associativity_multiple_and():
    # ((uid == 1) AND (uid == 2)) AND (uid == 3)
    expr = (AccountModel.uid == 1) & (AccountModel.uid == 2) & (AccountModel.uid == 3)
    d = expr.to_dict()
    assert d["type"] == "and"
    assert d["left"]["type"] == "and"
    assert d["left"]["left"] == {"type": "==", "key": "uid", "value": 1}
    assert d["left"]["right"] == {"type": "==", "key": "uid", "value": 2}
    assert d["right"] == {"type": "==", "key": "uid", "value": 3}


def test_operator_precedence_bitwise_and_over_or():
    # OR has lower precedence than AND in Python bitwise ops
    # uid == 1 | uid == 2 & uid == 3  -> parsed as (uid == 1) | ((uid == 2) & (uid == 3))
    expr = (AccountModel.uid == 1) | ((AccountModel.uid == 2) & (AccountModel.uid == 3))
    assert expr.to_dict() == {
        "type": "or",
        "left": {"type": "==", "key": "uid", "value": 1},
        "right": {
            "type": "and",
            "left": {"type": "==", "key": "uid", "value": 2},
            "right": {"type": "==", "key": "uid", "value": 3},
        },
    }


def test_mixed_types_values():
    expr = (
        (AccountModel.uid == 0)
        & (AccountModel.name == "")
        & (AccountModel.active == False)
    )
    d = expr.to_dict()
    assert d["type"] == "and"
    # Left branch should itself be an AND of first two
    left = d["left"]
    assert left["type"] == "and"
    assert left["left"] == {"type": "==", "key": "uid", "value": 0}
    assert left["right"] == {"type": "==", "key": "name", "value": ""}
    assert d["right"] == {"type": "==", "key": "active", "value": False}


def test_repr_does_not_crash_for_various_expressions():
    # Ensure __repr__ returns a string for all expression kinds
    str(AccountModel.uid == 1)
    str((AccountModel.uid == 1) & (AccountModel.uid == 2))
    str((AccountModel.uid == 1) | (AccountModel.uid == 2))
    str(AccountModel.score < 10)
    str(AccountModel.score <= 10)
    str(AccountModel.score > 10)
    str(AccountModel.score >= 10)


def test_error_path_unimplemented_to_dict_on_custom_base_subclass():
    # Create a broken subclass without key/value or left/right to trigger NotImplementedError
    from src.laserorm.core.expressions import BaseComparisonExpression

    class BrokenExpr(BaseComparisonExpression):
        @staticmethod
        def name():
            return "broken"

    with pytest.raises(NotImplementedError):
        BrokenExpr().to_dict()
