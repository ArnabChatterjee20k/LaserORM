"""
Unit tests for laserorm.core.model module
"""

import pytest
from typing import Optional, Union
from laserorm.core.model import (
    Model,
    Column,
    Expression,
    Meta,
    EqualExpression,
    NotEqualExpression,
    LessThanExpression,
    LessThanOrEqualExpression,
    GreaterThanExpression,
    GreaterThanOrEqualExpression,
)


class TestExpression:
    """Test Expression class functionality"""

    def test_expression_creation(self):
        """Test creating an Expression with a key"""
        expr = Expression("user_id", None)
        assert expr.key == "user_id"
        assert repr(expr) == "<Expr user_id>"

    def test_expression_comparison_operators(self):
        """Test all comparison operators on Expression"""
        expr = Expression("age", None)

        # Test equality
        eq_expr = expr == 25
        assert isinstance(eq_expr, EqualExpression)
        assert eq_expr.key == "age"
        assert eq_expr.value == 25

        # Test inequality
        ne_expr = expr != 30
        assert isinstance(ne_expr, NotEqualExpression)
        assert ne_expr.key == "age"
        assert ne_expr.value == 30

        # Test less than
        lt_expr = expr < 30
        assert isinstance(lt_expr, LessThanExpression)
        assert lt_expr.key == "age"
        assert lt_expr.value == 30

        # Test less than or equal
        le_expr = expr <= 30
        assert isinstance(le_expr, LessThanOrEqualExpression)
        assert le_expr.key == "age"
        assert le_expr.value == 30

        # Test greater than
        gt_expr = expr > 20
        assert isinstance(gt_expr, GreaterThanExpression)
        assert gt_expr.key == "age"
        assert gt_expr.value == 20

        # Test greater than or equal
        ge_expr = expr >= 20
        assert isinstance(ge_expr, GreaterThanOrEqualExpression)
        assert ge_expr.key == "age"
        assert ge_expr.value == 20


class TestColumn:
    """Test Column descriptor functionality"""

    def test_column_creation(self):
        """Test creating a Column with key, value, and type_hint"""
        col = Column("name", "John", str)
        assert col.key == "name"
        assert col.value == "John"
        assert col.type_hint == str
        assert col.name is None  # Will be set by __set_name__

    def test_column_set_name(self):
        """Test __set_name__ method sets the name and key"""
        col = Column()
        col.__set_name__(TestModel, "email")
        assert col.name == "email"
        assert col.key == "email"

    def test_column_set_name_with_existing_key(self):
        """Test __set_name__ preserves existing key"""
        col = Column("custom_key")
        col.__set_name__(TestModel, "email")
        assert col.name == "email"
        assert col.key == "custom_key"

    def test_column_get_class_level(self):
        """Test __get__ returns Expression at class level"""
        col = Column("age")
        col.__set_name__(TestModel, "age")
        result = col.__get__(None, TestModel)
        assert isinstance(result, Expression)
        assert result.key == "age"

    def test_column_get_instance_level(self):
        """Test __get__ returns stored value at instance level"""
        col = Column("name", "John")
        col.__set_name__(TestModel, "name")
        instance = TestModel()
        instance.__dict__["name"] = "Jane"
        result = col.__get__(instance, TestModel)
        assert result == "Jane"

    def test_column_get_instance_level_none(self):
        """Test __get__ returns None when no value stored"""
        col = Column("name")
        col.__set_name__(TestModel, "name")
        instance = TestModel()
        result = col.__get__(instance, TestModel)
        assert result is None

    def test_column_set(self):
        """Test __set__ stores value in instance dictionary"""
        col = Column("name")
        col.__set_name__(TestModel, "name")
        instance = TestModel()
        col.__set__(instance, "Alice")
        assert instance.__dict__["name"] == "Alice"


class TestMeta:
    """Test Meta metaclass functionality"""

    def test_meta_allows_initial_attribute_setting(self):
        """Test Meta allows setting attributes initially"""

        class TestClass(metaclass=Meta):
            pass

        # Should not raise error
        TestClass.new_attr = "value"
        assert TestClass.new_attr == "value"

    def test_meta_prevents_reassigning_expression(self):
        """Test Meta prevents reassigning Expression attributes"""

        class TestClass(metaclass=Meta):
            name = Expression("name", None)

        with pytest.raises(TypeError, match="Cannot reassign frozen attribute 'name'"):
            TestClass.name = "new_value"

    def test_meta_prevents_reassigning_column(self):
        """Test Meta prevents reassigning Column attributes"""

        class TestClass(metaclass=Meta):
            age = Column("age")

        with pytest.raises(TypeError, match="Cannot reassign frozen attribute 'age'"):
            TestClass.age = "new_value"


class TestModel:
    """Test Model class functionality"""

    def test_model_inheritance_aware_columns(self):
        """Test Model collects columns from inheritance hierarchy"""

        class BaseModel(Model):
            name: str
            age: int

        class ChildModel(BaseModel):
            email: str

        # Check that all fields are present
        child = ChildModel(name="John", age=25, email="john@example.com")
        assert child.name == "John"
        assert child.age == 25
        assert child.email == "john@example.com"

    def test_model_init_with_kwargs(self):
        """Test Model __init__ with keyword arguments"""

        class UserModel(Model):
            name: str
            age: Optional[int] = None
            is_active: bool = True

        user = UserModel(name="Alice", age=30, is_active=False)
        assert user.name == "Alice"
        assert user.age == 30
        assert user.is_active is False

    def test_model_init_with_defaults(self):
        """Test Model __init__ uses default values"""

        class UserModel(Model):
            name: str
            age: Optional[int] = None
            is_active: bool = True

        user = UserModel(name="Bob")
        assert user.name == "Bob"
        assert user.age is None
        assert user.is_active is True

    def test_model_get_fields(self):
        """Test get_fields method returns all field names"""

        class UserModel(Model):
            name: str
            age: int
            email: str

        user = UserModel(name="Charlie", age=35, email="charlie@example.com")
        fields = user.get_fields()
        assert "name" in fields
        assert "age" in fields
        assert "email" in fields

    def test_model_to_dict(self):
        """Test to_dict method converts model to dictionary"""

        class UserModel(Model):
            name: str
            age: int
            email: str

        user = UserModel(name="David", age=40, email="david@example.com")
        data = user.to_dict()
        assert data["name"] == "David"
        assert data["age"] == 40
        assert data["email"] == "david@example.com"

    def test_model_to_dict_exclude_fields(self):
        """Test to_dict excludes specified fields"""

        class UserModel(Model):
            name: str
            age: int
            email: str

        user = UserModel(name="Eve", age=45, email="eve@example.com")
        data = user.to_dict(exclude=["age"])
        assert "name" in data
        assert "age" not in data
        assert "email" in data

    def test_model_to_dict_include_none(self):
        """Test to_dict include_none parameter"""

        class UserModel(Model):
            name: str
            age: Optional[int] = None
            email: str

        user = UserModel(name="Frank", email="frank@example.com")

        # Test with include_none=True (default)
        data_with_none = user.to_dict()
        assert "age" in data_with_none
        assert data_with_none["age"] is None

        # Test with include_none=False
        data_without_none = user.to_dict(include_none=False)
        assert "age" not in data_without_none

    def test_model_get_values(self):
        """Test get_values method for database insertion"""

        class UserModel(Model):
            name: str
            age: Optional[int] = None
            email: str

        user = UserModel(name="Grace", age=50, email="grace@example.com")
        values = user.get_values()
        assert values["name"] == "Grace"
        assert values["age"] == 50
        assert values["email"] == "grace@example.com"

    def test_model_get_values_with_none(self):
        """Test get_values handles None values based on type annotations"""

        class UserModel(Model):
            name: str
            age: Optional[int] = None
            email: str

        user = UserModel(name="Henry", email="henry@example.com")
        values = user.get_values()
        assert values["name"] == "Henry"
        assert values["age"] is None  # Optional[int] allows None
        assert values["email"] == "henry@example.com"

    def test_model_get_schema(self):
        """Test get_schema class method generates schema"""

        class UserModel(Model):
            name: str
            age: Optional[int] = None
            email: str

        schema = UserModel.get_schema()
        assert "name" in schema
        assert "age" in schema
        assert "email" in schema

        # Check schema structure
        name_schema = schema["name"]
        assert "type" in name_schema
        assert "sub_type" in name_schema
        assert "default" in name_schema
        assert "primary_key" in name_schema
        assert "index" in name_schema
        assert "unique" in name_schema
        assert "auto_increment" in name_schema

    def test_model_expression_functionality(self):
        """Test that Model fields can be used as expressions"""

        class UserModel(Model):
            name: str
            age: int
            email: str

        # Test class-level access returns Expression
        name_expr = UserModel.name
        assert isinstance(name_expr, Expression)
        assert name_expr.key == "name"

        # Test comparison expressions
        age_gt_25 = UserModel.age > 25
        assert isinstance(age_gt_25, GreaterThanExpression)
        assert age_gt_25.key == "age"
        assert age_gt_25.value == 25

        email_eq = UserModel.email == "test@example.com"
        assert isinstance(email_eq, EqualExpression)
        assert email_eq.key == "email"
        assert email_eq.value == "test@example.com"

    def test_model_exclude_class_variable(self):
        """Test Model exclude class variable functionality"""

        class UserModel(Model):
            exclude = ["password"]  # Override default exclude
            name: str
            password: str
            email: str

        user = UserModel(name="Ivy", password="secret", email="ivy@example.com")

        # Test to_dict excludes password
        data = user.to_dict()
        assert "name" in data
        assert "password" not in data
        assert "email" in data

        # Test get_values excludes password
        values = user.get_values()
        assert "name" in values
        assert "password" not in values
        assert "email" in values

    def test_model_schema_exclude_class_variable(self):
        """Test Model schema_exclude class variable functionality"""

        class UserModel(Model):
            schema_exclude = ["internal_id"]
            name: str
            internal_id: str
            email: str

        # Test get_schema excludes internal_id
        schema = UserModel.get_schema()
        assert "name" in schema
        assert "internal_id" not in schema
        assert "email" in schema


# Helper class for testing
class TestModel:
    """Helper class for testing Column descriptor"""

    pass
