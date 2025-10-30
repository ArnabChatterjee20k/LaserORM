import pytest

from src.laserorm.core.schema import Schema, create_field, FieldMetadataOptions
from src.laserorm.storage.sqlite import SQLiteSession


class UserSchema(Schema):
    uid: int = create_field(FieldMetadataOptions(index=True))
    name: str = create_field(FieldMetadataOptions())
    age: int = create_field(FieldMetadataOptions())


def TestModel():
    return UserSchema.to_model()


def test_compile_equal_and_in_from_schema_model():
    User = TestModel()
    # Basic ==
    sql, vals = SQLiteSession.compile_expression(User.uid == 1)
    assert sql == "uid = ?"
    assert vals == [1]

    # IN
    sql, vals = SQLiteSession.compile_expression(User.uid[[1, 2, 3]])
    assert sql == "uid IN (?,?,?)"
    assert vals == [1, 2, 3]


def test_compile_not_in_and_or_from_schema_model():
    User = TestModel()
    expr = (User.uid[{"not": [5, 6]}]) | (
        (User.age > 18) & (User.name == (lambda: "a"))
    )
    sql, vals = SQLiteSession.compile_expression(expr)
    assert (
        sql == "uid NOT IN (?,?) OR (age > ?) AND (name = ?)"
        or sql == "(uid NOT IN (?,?)) OR ((age > ?) AND (name = ?))"
    )
    assert vals == [5, 6, 18, "a"]


def test_type_validation_via_schema_model():
    User = TestModel()
    with pytest.raises(TypeError):
        SQLiteSession.compile_expression(User.uid == "x")

    with pytest.raises(TypeError):
        SQLiteSession.compile_expression(User.uid[[1, "x"]])
