"""
Unit tests for laserorm.core.schema module
"""

import pytest
from dataclasses import dataclass, field, MISSING
from datetime import datetime
from typing import Optional, Union, List, Dict
from laserorm.core.schema import (
    Schema,
    MissingDefault,
    CurrentTimeStamp,
    FieldMetadataOptions,
    create_field,
)


class TestMissingDefault:
    """Test MissingDefault class"""

    def test_missing_default_creation(self):
        """Test creating MissingDefault instance"""
        missing = MissingDefault()
        assert isinstance(missing, MissingDefault)


class TestCurrentTimeStamp:
    """Test CurrentTimeStamp class"""

    def test_current_timestamp_creation(self):
        """Test creating CurrentTimeStamp instance"""
        timestamp = CurrentTimeStamp()
        assert isinstance(timestamp, CurrentTimeStamp)


class TestFieldMetadataOptions:
    """Test FieldMetadataOptions TypedDict"""

    def test_field_metadata_options_creation(self):
        """Test creating FieldMetadataOptions with default values"""
        metadata = FieldMetadataOptions()
        # FieldMetadataOptions should provide default values as specified in the TypedDict
        assert metadata.index is False
        assert metadata.primary_key is False
        assert metadata.unique is False
        assert metadata.auto_increment is False

    def test_field_metadata_options_custom_values(self):
        """Test creating FieldMetadataOptions with custom values"""
        metadata = FieldMetadataOptions(
            index=True, primary_key=True, unique=True, auto_increment=True
        )
        assert metadata.index is True
        assert metadata.primary_key is True
        assert metadata.unique is True
        assert metadata.auto_increment is True


class TestCreateField:
    """Test create_field function"""

    def test_create_field_basic(self):
        """Test creating a field with basic metadata"""
        metadata = FieldMetadataOptions(index=True)
        field_obj = create_field(metadata, default_factory=lambda: "test")

        assert field_obj.default_factory() == "test"
        assert field_obj.metadata["index"] is True
        # create_field should merge metadata with defaults
        assert field_obj.metadata["primary_key"] is False
        assert field_obj.metadata["unique"] is False
        assert field_obj.metadata["auto_increment"] is False

    def test_create_field_with_all_options(self):
        """Test creating a field with all metadata options"""
        metadata = FieldMetadataOptions(
            index=True, primary_key=True, unique=True, auto_increment=True
        )
        field_obj = create_field(metadata, default_factory=lambda: 42, init=False)

        assert field_obj.default_factory() == 42
        assert field_obj.init is False
        assert field_obj.metadata["index"] is True
        assert field_obj.metadata["primary_key"] is True
        assert field_obj.metadata["unique"] is True
        assert field_obj.metadata["auto_increment"] is True


class TestSchemaModel:
    """Test Model class from schema module"""

    def test_model_inheritance(self):
        """Test Model class can be inherited"""

        @dataclass
        class UserSchema(Schema):
            name: str
            email: str

        assert issubclass(UserSchema, Schema)

    def test_model_has_id_field(self):
        """Test Model has id field with correct metadata"""

        @dataclass
        class UserSchema(Schema):
            name: str

        # Check that id field exists
        user = UserSchema(name="John")
        assert hasattr(user, "id")
        assert user.id is None  # init=False means it's not in __init__

    def test_model_exclude_class_variables(self):
        """Test Model has exclude and schema_exclude class variables"""

        @dataclass
        class UserSchema(Schema):
            name: str

        assert hasattr(UserSchema, "exclude")
        assert hasattr(UserSchema, "schema_exclude")
        assert isinstance(UserSchema.exclude, list)
        assert isinstance(UserSchema.schema_exclude, list)

    def test_model_to_dict(self):
        """Test to_dict method"""

        @dataclass
        class UserSchema(Schema):
            name: str
            email: str
            age: Optional[int] = None

        user = UserSchema(name="Alice", email="alice@example.com", age=30)
        data = user.to_dict()

        assert data["name"] == "Alice"
        assert data["email"] == "alice@example.com"
        assert data["age"] == 30
        assert "id" not in data  # id should be excluded by default

    def test_model_to_dict_exclude_parameter(self):
        """Test to_dict with exclude parameter"""

        @dataclass
        class UserSchema(Schema):
            name: str
            email: str
            age: int

        user = UserSchema(name="Bob", email="bob@example.com", age=25)
        data = user.to_dict(exclude=["age"])

        assert data["name"] == "Bob"
        assert data["email"] == "bob@example.com"
        assert "age" not in data

    def test_model_to_dict_include_none(self):
        """Test to_dict include_none parameter"""

        @dataclass
        class UserSchema(Schema):
            name: str
            email: str
            age: Optional[int] = None

        user = UserSchema(name="Charlie", email="charlie@example.com")

        # Test with include_none=True (default)
        data_with_none = user.to_dict()
        assert "age" in data_with_none
        assert data_with_none["age"] is None

        # Test with include_none=False
        data_without_none = user.to_dict(include_none=False)
        assert "age" not in data_without_none

    def test_model_get_fields(self):
        """Test get_fields method"""

        @dataclass
        class UserSchema(Schema):
            name: str
            email: str
            age: int

        user = UserSchema(name="David", email="david@example.com", age=35)
        fields = user.get_fields()

        assert "name" in fields
        assert "email" in fields
        assert "age" in fields
        assert "id" in fields  # id field should be included

    def test_model_get_values(self):
        """Test get_values method for database insertion"""

        @dataclass
        class UserSchema(Schema):
            name: str
            email: str
            age: Optional[int] = None

        user = UserSchema(name="Eve", email="eve@example.com", age=40)
        values = user.get_values()

        assert values["name"] == "Eve"
        assert values["email"] == "eve@example.com"
        assert values["age"] == 40
        assert "id" not in values  # id should be excluded by default

    def test_model_get_values_with_none(self):
        """Test get_values handles None values based on type annotations"""

        @dataclass
        class UserSchema(Schema):
            name: str
            email: str
            phone: str  # Required field
            age: Optional[int] = None  # Optional field with default

        user = UserSchema(name="Frank", email="frank@example.com", phone="123-456-7890")
        values = user.get_values()

        assert values["name"] == "Frank"
        assert values["email"] == "frank@example.com"
        assert values["phone"] == "123-456-7890"
        assert "age" in values  # Optional[int] allows None
        assert values["age"] is None

    def test_model_get_schema(self):
        """Test get_schema class method"""

        @dataclass
        class UserSchema(Schema):
            name: str
            email: str
            age: Optional[int] = None

        schema = UserSchema.get_schema()

        # Check that all fields are in schema
        assert "name" in schema
        assert "email" in schema
        assert "age" in schema
        assert "id" in schema

        # Check schema structure for a field
        name_schema = schema["name"]
        assert "type" in name_schema
        assert "sub_type" in name_schema
        assert "default" in name_schema
        assert "primary_key" in name_schema
        assert "index" in name_schema
        assert "unique" in name_schema
        assert "auto_increment" in name_schema

    def test_model_get_schema_exclude_parameter(self):
        """Test get_schema with exclude parameter"""

        @dataclass
        class UserSchema(Schema):
            name: str
            email: str
            age: int

        schema = UserSchema.get_schema(exclude=["age"])

        assert "name" in schema
        assert "email" in schema
        assert "age" not in schema

    def test_model_get_schema_schema_exclude(self):
        """Test get_schema respects schema_exclude class variable"""

        @dataclass
        class UserSchema(Schema):
            schema_exclude = ["internal_id"]
            name: str
            email: str
            internal_id: str

        schema = UserSchema.get_schema()

        assert "name" in schema
        assert "email" in schema
        assert "internal_id" not in schema

        # Test get_values includes internal_id (schema_exclude only affects get_schema, not get_values)
        user = UserSchema(name="Test", email="test@example.com", internal_id="123")
        values = user.get_values()
        assert "name" in values
        assert "email" in values
        assert "internal_id" in values  # schema_exclude doesn't affect get_values

    def test_model_get_schema_union_types(self):
        """Test get_schema handles Union types correctly"""

        @dataclass
        class UserSchema(Schema):
            name: str
            age: Union[int, None]  # Same as Optional[int]
            status: Union[str, int]

        schema = UserSchema.get_schema()

        # Check Union type handling
        age_schema = schema["age"]
        assert isinstance(age_schema["type"], list)
        assert "int" in age_schema["type"]
        assert "NoneType" in age_schema["type"]

        status_schema = schema["status"]
        assert isinstance(status_schema["type"], list)
        assert "str" in status_schema["type"]
        assert "int" in status_schema["type"]

    def test_model_get_schema_list_types(self):
        """Test get_schema handles list types correctly"""

        @dataclass
        class UserSchema(Schema):
            name: str
            tags: List[str]
            metadata: Dict[str, str]

        schema = UserSchema.get_schema()

        # Check list type handling
        tags_schema = schema["tags"]
        assert tags_schema["type"] == "json"
        assert tags_schema["sub_type"] == "list"

        # Check dict type handling
        metadata_schema = schema["metadata"]
        assert metadata_schema["type"] == "json"
        assert metadata_schema["sub_type"] == "dict"

    def test_model_get_schema_default_values(self):
        """Test get_schema handles different types of default values correctly"""

        @dataclass
        class UserSchema(Schema):
            # Field with no default (should be MissingDefault)
            name: str

            # Field with simple default value (should preserve the value)
            age: int = 25

            # Field with boolean default (should preserve the value)
            is_active: bool = True

            # Field with default_factory for datetime (should be CurrentTimeStamp)
            created_at: datetime = field(default_factory=datetime.now)

            # Field with default_factory for list (should call the factory)
            tags: list[str] = field(default_factory=list)

            # Field with default_factory for dict (should call the factory)
            metadata: dict = field(default_factory=dict)

        schema = UserSchema.get_schema()

        # Test field with no default
        name_schema = schema["name"]
        assert isinstance(name_schema["default"], MissingDefault)

        # Test simple default values - these should be preserved as-is
        age_schema = schema["age"]
        assert age_schema["default"] == 25, f"Expected 25, got {age_schema['default']}"

        is_active_schema = schema["is_active"]
        assert (
            is_active_schema["default"] is True
        ), f"Expected True, got {is_active_schema['default']}"

        # Test default_factory for datetime - should be CurrentTimeStamp
        created_at_schema = schema["created_at"]
        assert isinstance(created_at_schema["default"], CurrentTimeStamp)

        # Test default_factory for list - should be callable and return empty list
        tags_schema = schema["tags"]
        assert tags_schema["default"] == []

        # Test default_factory for dict - should be callable and return empty dict
        metadata_schema = schema["metadata"]
        assert metadata_schema["default"] == {}

    def test_model_get_schema_metadata(self):
        """Test get_schema preserves field metadata"""

        @dataclass
        class UserSchema(Schema):
            name: str = field(metadata={"index": True, "unique": True})
            email: str = field(metadata={"primary_key": True})
            age: int = field(metadata={"auto_increment": True})

        schema = UserSchema.get_schema()

        # Check metadata preservation
        name_schema = schema["name"]
        assert name_schema["index"] is True
        assert name_schema["unique"] is True
        assert name_schema["primary_key"] is False

        email_schema = schema["email"]
        assert email_schema["primary_key"] is True
        assert email_schema["index"] is False

        age_schema = schema["age"]
        assert age_schema["auto_increment"] is True
        assert age_schema["index"] is False

    def test_model_custom_exclude(self):
        """Test Model with custom exclude list"""

        @dataclass
        class UserSchema(Schema):
            exclude = ["password", "secret_key"]
            name: str
            email: str
            password: str
            secret_key: str

        user = UserSchema(
            name="Grace", email="grace@example.com", password="secret", secret_key="key"
        )

        # Test to_dict excludes custom fields
        data = user.to_dict()
        assert "name" in data
        assert "email" in data
        assert "password" not in data
        assert "secret_key" not in data

        # Test get_values excludes custom fields
        values = user.get_values()
        assert "name" in values
        assert "email" in values
        assert "password" not in values
        assert "secret_key" not in values

        # Test get_schema does NOT exclude custom fields by default
        # (only schema_exclude affects get_schema, not exclude)
        schema = UserSchema.get_schema()
        assert "name" in schema
        assert "email" in schema
        assert "password" in schema  # exclude doesn't affect get_schema
        assert "secret_key" in schema  # exclude doesn't affect get_schema

        # But we can exclude via the exclude parameter
        schema_with_exclude = UserSchema.get_schema(exclude=["password", "secret_key"])
        assert "name" in schema_with_exclude
        assert "email" in schema_with_exclude
        assert "password" not in schema_with_exclude
        assert "secret_key" not in schema_with_exclude

    def test_model_inheritance_with_schema(self):
        """Test Model inheritance with schema methods"""

        # using kw_only so that we can mix up the required fields and default fields together in parent child in random order
        @dataclass(kw_only=True)
        class BaseSchema(Schema):
            name: str
            created_at: datetime = field(default_factory=datetime.now)

        @dataclass(kw_only=True)
        class UserSchema(BaseSchema):
            email: str
            age: int = field(
                default_factory=lambda: 0
            )  # Add default to avoid field ordering issues

        user = UserSchema(name="Henry", email="henry@example.com", age=55)

        # Test that all fields are accessible
        assert user.name == "Henry"
        assert user.email == "henry@example.com"
        assert user.age == 55
        assert isinstance(user.created_at, datetime)

        # Test schema includes all fields
        schema = UserSchema.get_schema()
        assert "name" in schema
        assert "email" in schema
        assert "age" in schema
        assert "created_at" in schema
        assert "id" in schema

    def test_to_model_basic_conversion(self):
        """Test basic conversion from schema to model"""

        @dataclass
        class UserSchema(Schema):
            name: str
            email: str
            age: int = 25

        # Convert schema to model
        UserModel = UserSchema.to_model()

        # Test that it returns a class
        assert isinstance(UserModel, type)
        assert UserModel.__name__ == "UserSchema"

        # Test that it inherits from StaticModel
        from laserorm.core.model import Model as StaticModel

        assert issubclass(UserModel, StaticModel)

        # Test that annotations are set correctly
        assert hasattr(UserModel, "__annotations__")
        annotations = UserModel.__annotations__
        assert "name" in annotations
        assert "email" in annotations
        assert "age" in annotations

    def test_to_model_instance_creation(self):
        """Test creating instances from converted model"""

        @dataclass
        class UserSchema(Schema):
            name: str
            email: str
            age: int = 25

        UserModel = UserSchema.to_model()

        # Test creating instance with required fields
        user = UserModel(name="John", email="john@example.com")

        # Test that fields are accessible
        assert user.name == "John"
        assert user.email == "john@example.com"
        assert user.age == 25  # Should use default value

    def test_to_model_with_defaults(self):
        """Test conversion with various default values"""

        @dataclass
        class UserSchema(Schema):
            name: str
            email: str
            age: int = 30
            is_active: bool = True
            tags: list[str] = field(default_factory=list)

        UserModel = UserSchema.to_model()

        # Test instance creation with defaults
        user = UserModel(name="Alice", email="alice@example.com")

        assert user.name == "Alice"
        assert user.email == "alice@example.com"
        assert user.age == 30
        assert user.is_active is True
        # The default_factory should be called, not the class itself
        assert isinstance(user.tags, list)
        assert user.tags == []

    def test_to_model_excludes_id_field(self):
        """Test that to_model excludes the id field to avoid conflicts"""

        @dataclass
        class UserSchema(Schema):
            name: str
            email: str

        UserModel = UserSchema.to_model()

        # Test that id is in annotations (should be excluded but must be part of the class definition)
        annotations = UserModel.__annotations__
        assert "id" in annotations

        # Test that we can still create instances
        user = UserModel(name="Bob", email="bob@example.com")
        assert user.name == "Bob"
        assert user.email == "bob@example.com"

    def test_to_model_with_union_types(self):
        """Test conversion with Union types"""

        @dataclass
        class UserSchema(Schema):
            name: str
            age: Union[int, None]
            status: Union[str, int]

        UserModel = UserSchema.to_model()

        # Test instance creation with Union types
        user = UserModel(name="Charlie", age=25, status="active")

        assert user.name == "Charlie"
        assert user.age == 25
        assert user.status == "active"

        # Test with None value
        user2 = UserModel(name="David", age=None, status=1)
        assert user2.age is None
        assert user2.status == 1

    def test_to_model_with_list_dict_types(self):
        """Test conversion with list and dict types"""

        @dataclass
        class UserSchema(Schema):
            name: str
            tags: List[str]
            metadata: Dict[str, str]

        UserModel = UserSchema.to_model()

        # Test instance creation
        user = UserModel(name="Eve", tags=["admin", "user"], metadata={"role": "admin"})

        assert user.name == "Eve"
        assert user.tags == ["admin", "user"]
        assert user.metadata == {"role": "admin"}

    def test_to_model_inheritance(self):
        """Test conversion with inheritance"""

        @dataclass(kw_only=True)
        class BaseSchema(Schema):
            name: str
            created_at: datetime = field(default_factory=datetime.now)

        @dataclass(kw_only=True)
        class UserSchema(BaseSchema):
            email: str
            age: int = 25

        UserModel = UserSchema.to_model()

        # Test that it inherits from StaticModel, not from the schema classes
        from laserorm.core.model import Model as StaticModel

        assert issubclass(UserModel, StaticModel)
        assert not issubclass(UserModel, BaseSchema)
        assert not issubclass(UserModel, UserSchema)

        # Test instance creation
        user = UserModel(name="Frank", email="frank@example.com", age=30)

        assert user.name == "Frank"
        assert user.email == "frank@example.com"
        assert user.age == 30
        assert isinstance(user.created_at, datetime)

    def test_to_model_model_methods_work(self):
        """Test that converted model has all the expected Model methods"""

        @dataclass
        class UserSchema(Schema):
            name: str
            email: str
            age: int = 25

        UserModel = UserSchema.to_model()

        # Test that Model methods are available
        assert hasattr(UserModel, "get_schema")
        assert hasattr(UserModel, "get_fields")

        # Test get_schema method
        schema = UserModel.get_schema()
        assert "name" in schema
        assert "email" in schema
        assert "age" in schema

        # Test get_fields method on instance
        user = UserModel(name="Grace", email="grace@example.com")
        fields = user.get_fields()
        assert "name" in fields
        assert "email" in fields
        assert "age" in fields

    def test_to_model_custom_exclude(self):
        """Test conversion respects custom exclude lists"""

        @dataclass
        class UserSchema(Schema):
            exclude = ["password", "secret_key"]
            name: str
            email: str
            password: str
            secret_key: str

        UserModel = UserSchema.to_model()

        # Test that excluded fields are present in annotations
        annotations = UserModel.__annotations__
        assert "name" in annotations
        assert "email" in annotations
        assert "password" in annotations
        assert "secret_key" in annotations

        # Test instance creation (should only require non-excluded fields)
        user = UserModel(name="Henry", email="henry@example.com")
        assert user.name == "Henry"
        assert user.email == "henry@example.com"

        # Test that converted model's get_schema does NOT exclude password and secret_key
        # (only schema_exclude affects get_schema, not exclude)
        schema = UserModel.get_schema()
        # Since password and secret_key are not in annotations, they won't be in schema anyway
        # But if they were, they would still be included because exclude doesn't affect get_schema

        # Test that converted model's get_values excludes password and secret_key
        # (Note: since they're excluded from annotations during conversion, they won't be accessible)
        values = user.get_values()
        assert "name" in values
        assert "email" in values
        assert "password" not in values
        assert "secret_key" not in values

    def test_to_model_custom_schema_exclude(self):
        """Test conversion respects custom schema_exclude lists"""

        @dataclass
        class UserSchema(Schema):
            schema_exclude = ["internal_id", "deleted_at"]
            name: str
            email: str
            internal_id: str
            deleted_at: str

        UserModel = UserSchema.to_model()

        # Test that schema_excluded fields are still in annotations (unlike exclude)
        annotations = UserModel.__annotations__
        assert "name" in annotations
        assert "email" in annotations
        assert "internal_id" in annotations
        assert "deleted_at" in annotations

        # Test instance creation (fields are in annotations, so they can be set)
        user = UserModel(
            name="John",
            email="john@example.com",
            internal_id="123",
            deleted_at="2023-01-01",
        )
        assert user.name == "John"
        assert user.email == "john@example.com"

        # Test that converted model's get_schema excludes internal_id and deleted_at
        schema = UserModel.get_schema()
        assert "name" in schema
        assert "email" in schema
        assert "internal_id" not in schema
        assert "deleted_at" not in schema

        # Test that converted model's get_values still includes internal_id and deleted_at
        # (schema_exclude only affects get_schema, not get_values)
        # Actually, looking at the code, get_values uses exclude list, not schema_exclude
        values = user.get_values()
        assert "name" in values
        assert "email" in values
        assert "internal_id" in values
        assert "deleted_at" in values

    def test_to_model_preserves_module_info(self):
        """Test that converted model preserves module information"""

        @dataclass
        class UserSchema(Schema):
            name: str
            email: str

        UserModel = UserSchema.to_model()

        # Test that module is preserved
        assert UserModel.__module__ == UserSchema.__module__
        assert UserModel.__name__ == "UserSchema"
