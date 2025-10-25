from typing import get_type_hints, Any, Optional, Union, get_origin, get_args
from types import UnionType
from dataclasses import dataclass
import datetime


@dataclass
class EqualExpression:
    """Represents an equality comparison: field == value"""

    key: str
    value: Any

    def __repr__(self):
        return f"Equal({self.key} == {self.value})"


@dataclass
class NotEqualExpression:
    """Represents an inequality comparison: field != value"""

    key: str
    value: Any

    def __repr__(self):
        return f"NotEqual({self.key} != {self.value})"


@dataclass
class LessThanExpression:
    """Represents a less than comparison: field < value"""

    key: str
    value: Any

    def __repr__(self):
        return f"LessThan({self.key} < {self.value})"


@dataclass
class LessThanOrEqualExpression:
    """Represents a less than or equal comparison: field <= value"""

    key: str
    value: Any

    def __repr__(self):
        return f"LessThanOrEqual({self.key} <= {self.value})"


@dataclass
class GreaterThanExpression:
    """Represents a greater than comparison: field > value"""

    key: str
    value: Any

    def __repr__(self):
        return f"GreaterThan({self.key} > {self.value})"


@dataclass
class GreaterThanOrEqualExpression:
    """Represents a greater than or equal comparison: field >= value"""

    key: str
    value: Any

    def __repr__(self):
        return f"GreaterThanOrEqual({self.key} >= {self.value})"


class Expression:
    """
    Represents a symbolic expression used when accessing a Column at the class level.
    Example: Account.id -> <Expression attribute='id'>
    """

    __slots__ = ("_key", "_value")

    def __init__(self, key: str, value: Any):
        self._key = key
        self._value = value

    @property
    def key(self):
        """Read-only access to the expression key"""
        return self._key

    @property
    def value(self):
        """Read-only access to the expression value"""
        return self._value

    def __eq__(self, other):
        return EqualExpression(self.key, other)

    def __ne__(self, other):
        return NotEqualExpression(self.key, other)

    def __lt__(self, other):
        return LessThanExpression(self.key, other)

    def __le__(self, other):
        return LessThanOrEqualExpression(self.key, other)

    def __gt__(self, other):
        return GreaterThanExpression(self.key, other)

    def __ge__(self, other):
        return GreaterThanOrEqualExpression(self.key, other)

    def __repr__(self):
        return f"<Expr {self.key}>"


# -------------------------------------------------------------------
#  Column: Descriptor protocol for class and instance-level behavior
# -------------------------------------------------------------------
class Column:
    """
    A descriptor that represents a database column-like field.
    Behaves like:
      - On the class level -> returns an Expression
      - On the instance level -> behaves like a normal attribute
    """

    def __init__(self, key=None, value=None, type_hint=None):
        self.key = key
        self.value = value
        self.name = None  # will be set via __set_name__
        self.type_hint = type_hint  # used for runtime validation (future use)

    def __set_name__(self, owner, name):
        """Automatically called when assigned to a class attribute"""
        self.name = name
        if self.key is None:
            self.key = name

    def __get__(self, instance, owner):
        """Class-level access returns an Expression, instance-level gets stored value"""
        if instance is None:
            return Expression(self.key, self.value)
        return instance.__dict__.get(self.name, None)

    def __set__(self, instance, value):
        """Sets the value in the instance dictionary"""
        instance.__dict__[self.name] = value


# -------------------------------------------------------------------
#  Meta: Metaclass that prevents reassigning class-level attributes and freezing the Model
#  Needed for the expressions otherwise they can be reassinged.
#  ex -> User.id = 12 # freezing stops doing this
# -------------------------------------------------------------------
class Meta(type):
    """
    Custom metaclass that:
      - Allows initial attribute setting during subclass creation
      - Freezes Column/Expression attributes afterward (immutable class-level behavior)
    """

    def __setattr__(cls, name, value):
        # Only restrict reassignment for Column/Expression objects that already exist
        existing = cls.__dict__.get(name, None)
        if isinstance(existing, (Expression, Column)):
            raise TypeError(
                f"Cannot reassign frozen attribute '{name}' on {cls.__name__}"
            )
        super().__setattr__(name, value)
        # To set name to the attr for the Column
        # setattr should call the set_name always
        if hasattr(value, "__set_name__"):
            value.__set_name__(cls, name)


class Model(metaclass=Meta):
    """
    Base class providing:
      - Automatic Column wrapping for annotated fields
      - Inheritance-aware column collection (MRO)
      - Optional validation flag via __init_subclass__
    """

    # including exclude, schema_exclude in them so that they are not included in the schema
    exclude: list[str] = ["id", "exclude", "schema_exclude"]
    schema_exclude: list[str] = ["exclude", "schema_exclude"]

    def __init_subclass__(cls, **kwargs):
        # Consume known subclass configuration (e.g. validation=True)
        kwargs.pop("validation", None)
        super().__init_subclass__(**kwargs)
        # Get annotations only from the current class (not parents)
        # not doing cls.__dict__.get('__annotations__', {}) => as it doesn't consider the direct parent
        # get_type_hints is recursive
        annotations = get_type_hints(cls)
        for key, type_hint in annotations.items():
            # using get on dict instead of getattr as getattr will call get of the Column and it will return Expression
            # dict will bypass the descriptor protocol
            if isinstance(cls.__dict__.get(key, None), Column):
                continue
            default = cls.__dict__.get(key, None)
            setattr(cls, key, Column(key, default, type_hint))

    def __init__(self, **kwargs):
        """
        Initializes the model instance:
          - Collects all Columns from the class hierarchy (MRO)
          - Assigns values from kwargs or falls back to defaults
        """
        columns = {}
        # Walk through all classes in MRO (bottom-up)
        # not iterating over only self.__class__.__dict__.items() as it targets only the current class attributes and not the parents
        for base in reversed(self.__class__.__mro__):
            if base is object:
                continue
            for key, value in base.__dict__.items():
                if isinstance(value, Column):
                    columns[key] = value

        # Assign values to the instance
        for key, col in columns.items():
            if key in kwargs:
                setattr(self, key, kwargs[key])
            elif getattr(col, "value", None) is not None:
                setattr(self, key, col.value)
            else:
                setattr(self, key, None)

    def get_fields(self):
        """Return a set of field names from the model"""
        fields = set()
        for base in reversed(self.__class__.__mro__):
            if base is object:
                continue
            for key, value in base.__dict__.items():
                if isinstance(value, Column):
                    fields.add(key)
        return fields

    def to_dict(self, exclude: list[str] = [], include_none: bool = True) -> dict:
        """Convert the model instance to a dictionary representation"""
        data = {}
        exclude_list = getattr(self, "exclude", [])
        if not isinstance(exclude_list, list):
            exclude_list = []

        for field_name in self.get_fields():
            if field_name in exclude_list or field_name in exclude:
                continue

            value = getattr(self, field_name, None)
            if include_none or value is not None:
                data[field_name] = value

        return data

    def get_values(self):
        """
        Return a dictionary representing the values to be inserted in the DB.
        If user provided the value then use it else for the default dont use it
        Or if the schema allows using None
        """
        insert_data = {}
        annotations = get_type_hints(self.__class__)

        exclude_list = getattr(self.__class__, "exclude", [])
        if not isinstance(exclude_list, list):
            exclude_list = []

        for field_name in self.get_fields():
            if field_name in exclude_list:
                continue

            value = getattr(self, field_name, None)
            if value is None:
                # Check if the field type allows None
                field_type = annotations.get(field_name)
                if field_type:
                    origin = get_origin(field_type)
                    if origin is Union or origin is UnionType:
                        types = [
                            t.__name__ if hasattr(t, "__name__") else str(t)
                            for t in get_args(field_type)
                        ]
                        if "NoneType" in types:
                            insert_data[field_name] = value
            else:
                insert_data[field_name] = value

        return insert_data

    @classmethod
    def get_schema(cls, exclude: list[str] = []):
        """Generate json schema for the model class"""
        schema = {}
        annotations = get_type_hints(cls)

        schema_exclude_list = getattr(cls, "schema_exclude").value

        for field_name in annotations:
            if field_name in exclude or field_name in schema_exclude_list:
                continue

            field_type = annotations[field_name]
            origin = get_origin(field_type)

            # Get metadata from Column if it exists
            column = getattr(cls, field_name, None)
            metadata = {}
            if isinstance(column, Column):
                # For now, we'll use basic metadata structure
                # This could be extended to support more metadata options
                metadata = {
                    "primary_key": False,
                    "index": False,
                    "unique": False,
                    "auto_increment": False,
                }

            default = None
            if isinstance(column, Column) and column.value is not None:
                if isinstance(column.value, type) and issubclass(
                    column.value, datetime.datetime
                ):
                    default = "CURRENT_TIMESTAMP"
                else:
                    default = column.value

            schema[field_name] = {
                "type": None,
                "sub_type": None,
                "default": default,
                "primary_key": metadata.get("primary_key", False),
                "index": metadata.get("index", False),
                "unique": metadata.get("unique", False),
                "auto_increment": metadata.get("auto_increment", False),
            }

            if origin is Union or origin is UnionType:
                schema[field_name]["type"] = [
                    t.__name__ if hasattr(t, "__name__") else str(t)
                    for t in get_args(field_type)
                ]
            elif (
                origin in (list, dict)
                or str(field_type).startswith("typing.List")
                or str(field_type).startswith("typing.Dict")
            ):
                schema[field_name]["type"] = "json"
                if origin == list or str(field_type).startswith("typing.List"):
                    schema[field_name]["sub_type"] = "list"
                elif origin == dict or str(field_type).startswith("typing.Dict"):
                    schema[field_name]["sub_type"] = "dict"
            else:
                schema[field_name]["type"] = [
                    (
                        field_type.__name__
                        if hasattr(field_type, "__name__")
                        else str(field_type)
                    )
                ]

        return schema
