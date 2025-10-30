import pytest

from src.laserorm.core.model import Model
from src.laserorm.storage.sqlite import SQLiteSession
from src.laserorm.core.expressions import NotInExpression


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


def test_in_collection_via_getitem():
    # AccountModel.uid[[1,2,3]] -> IN [1,2,3]
    expr = AccountModel.uid[[1, 2, 3]]
    d = expr.to_dict()
    assert d["type"] == "in"
    assert d["key"] == "uid"
    assert d["value"] == [1, 2, 3]


def test_in_empty_collection_via_getitem():
    expr = AccountModel.uid[[]]
    assert expr.to_dict() == {"type": "in", "key": "uid", "value": []}


def test_in_nested_with_and_or_via_getitem():
    expr = (AccountModel.uid[[1, 2]] & AccountModel.score[[10, 20, 30]]) | (
        AccountModel.uid[[3]] & AccountModel.score[[40]]
    )
    assert expr.to_dict() == {
        "type": "or",
        "left": {
            "type": "and",
            "left": {"type": "in", "key": "uid", "value": [1, 2]},
            "right": {"type": "in", "key": "score", "value": [10, 20, 30]},
        },
        "right": {
            "type": "and",
            "left": {"type": "in", "key": "uid", "value": [3]},
            "right": {"type": "in", "key": "score", "value": [40]},
        },
    }


def test_compile_expression_validates_type_hint_scalar_ok():
    sql, vals = SQLiteSession.compile_expression(AccountModel.uid == 10)
    assert sql == "uid = ?"
    assert vals == [10]


def test_compile_expression_validates_type_hint_scalar_wrong_type():
    with pytest.raises(TypeError):
        SQLiteSession.compile_expression(AccountModel.uid == "not-int")


def test_compile_expression_calls_callable_for_scalar_value():
    sql, vals = SQLiteSession.compile_expression(AccountModel.uid == (lambda: 7))
    assert sql == "uid = ?"
    assert vals == [7]


def test_compile_expression_in_with_callables_and_validation():
    expr = AccountModel.uid[[1, (lambda: 2), 3]]
    sql, vals = SQLiteSession.compile_expression(expr)
    assert sql == "uid IN (?,?,?)"
    assert vals == [1, 2, 3]

    with pytest.raises(TypeError):
        SQLiteSession.compile_expression(AccountModel.uid[[1, (lambda: "x")]])


def test_compile_expression_and_or_recurses_and_builds_placeholders():
    expr = (AccountModel.uid[[1, 2]]) & (
        (AccountModel.score > 5) | (AccountModel.score <= (lambda: 9))
    )
    sql, vals = SQLiteSession.compile_expression(expr)
    assert sql == "(uid IN (?,?)) AND ((score > ?) OR (score <= ?))"
    assert vals == [1, 2, 5, 9]


def test_not_in_via_getitem_dict_and_compilation():
    expr = AccountModel.uid[{"not": [4, 5]}]
    sql, vals = SQLiteSession.compile_expression(expr)
    assert sql == "uid NOT IN (?,?)"
    assert vals == [4, 5]

    with pytest.raises(TypeError):
        SQLiteSession.compile_expression(AccountModel.uid[{"not": [4, "bad"]}])


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
    from src.laserorm.core.expressions import BaseExpression

    class BrokenExpr(BaseExpression):
        @staticmethod
        def name():
            return "broken"

    with pytest.raises(NotImplementedError):
        BrokenExpr().to_dict()
