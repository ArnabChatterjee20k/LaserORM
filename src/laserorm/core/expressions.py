from dataclasses import dataclass
from typing import Any
from abc import ABC, abstractmethod


# Intarnal expressions layer for comparators and binary expressions
class BaseExpression(ABC):

    @staticmethod
    def name():
        pass

    def to_dict(self):
        if hasattr(self, "key") and hasattr(self, "value"):
            return {
                "type": self.name(),
                "key": self.key,
                "value": self.value,
            }
        if hasattr(self, "left") and hasattr(self, "right"):
            return {
                "type": self.name(),
                "left": self.left.to_dict(),
                "right": self.right.to_dict(),
            }
        raise NotImplementedError(f"to_dict not implemented for {type(self).__name__}")

    def __eq__(self, other):
        return EqualExpression(self.key, other, getattr(self, "type_hint", None))

    def __ne__(self, other):
        return NotEqualExpression(self.key, other, getattr(self, "type_hint", None))

    def __lt__(self, other):
        return LessThanExpression(self.key, other, getattr(self, "type_hint", None))

    def __le__(self, other):
        return LessThanOrEqualExpression(
            self.key, other, getattr(self, "type_hint", None)
        )

    def __gt__(self, other):
        return GreaterThanExpression(self.key, other, getattr(self, "type_hint", None))

    def __ge__(self, other):
        return GreaterThanOrEqualExpression(
            self.key, other, getattr(self, "type_hint", None)
        )

    # Support AND with &
    def __and__(self, other: "BaseExpression"):
        return AndExpression(self, other)

    # Support AND with |
    def __or__(self, other: "BaseExpression"):
        return OrExpression(self, other)

    def __repr__(self):
        return f"<Expr key={self.key} value={self.value}>"

    # Support bracket-based IN construction: AccountModel.uid[[1,2,3]]
    def __getitem__(self, item):
        if isinstance(item, (list, tuple, set)):
            return InExpression(self.key, list(item), getattr(self, "type_hint", None))

        # a hack to support not via dict: AccountModel.uid[{"not": [1, 2, 3]}]
        if isinstance(item, dict) and "not" in item:
            values = item.get("not", [])
            if not isinstance(values, (list, tuple, set)):
                raise TypeError("'not' must be a list/tuple/set of values for NOT IN")
            return NotInExpression(
                self.key, list(values), getattr(self, "type_hint", None)
            )

        raise TypeError("__getitem__ expects a list/tuple/set for IN expression")

    # Support bracket-based NOT IN construction: ~(AccountModel.uid[[1,2,3]])
    def __invert__(self):
        if isinstance(self, InExpression):
            return NotInExpression(
                self.key, self.value, getattr(self, "type_hint", None)
            )
        raise TypeError(
            f"Cannot invert non-IN expression of type {type(self).__name__}"
        )


class Expression(BaseExpression):
    """
    Represents a symbolic expression used when accessing a Column at the class level.
    Example: Account.id -> <Expression attribute='id'>
    """

    __slots__ = ("_key", "_value", "_metadata", "_type_hint")

    def __init__(
        self, key: str, value: Any, metadata: dict = {}, type_hint: Any = None
    ):
        self._key = key
        self._value = value
        self._metadata = metadata
        self._type_hint = type_hint

    @property
    def key(self):
        """Read-only access to the expression key"""
        return self._key

    @property
    def value(self):
        """Read-only access to the expression value"""
        return self._value

    @property
    def metadata(self):
        """Read-only access to the expression metadata"""
        return self._metadata

    @property
    def type_hint(self):
        return self._type_hint


@dataclass
class AndExpression(BaseExpression):
    left: BaseExpression
    right: BaseExpression

    def __repr__(self):
        return f"({self.left} AND {self.right})"

    @staticmethod
    def name():
        return "and"


@dataclass
class OrExpression(BaseExpression):
    left: BaseExpression
    right: BaseExpression

    def __repr__(self):
        return f"({self.left} OR {self.right})"

    @staticmethod
    def name():
        return "or"


@dataclass
class EqualExpression(BaseExpression):
    """Represents an equality comparison: field == value"""

    key: str
    value: Any
    type_hint: Any | None = None

    def __repr__(self):
        return f"Equal({self.key} == {self.value})"

    @staticmethod
    def name():
        return "=="


@dataclass
class NotEqualExpression(BaseExpression):
    """Represents an inequality comparison: field != value"""

    key: str
    value: Any
    type_hint: Any | None = None

    def __repr__(self):
        return f"NotEqual({self.key} != {self.value})"

    @staticmethod
    def name():
        return "!="


@dataclass
class LessThanExpression(BaseExpression):
    """Represents a less than comparison: field < value"""

    key: str
    value: Any
    type_hint: Any | None = None

    def __repr__(self):
        return f"LessThan({self.key} < {self.value})"

    @staticmethod
    def name():
        return "<"


@dataclass
class LessThanOrEqualExpression(BaseExpression):
    """Represents a less than or equal comparison: field <= value"""

    key: str
    value: Any
    type_hint: Any | None = None

    def __repr__(self):
        return f"LessThanOrEqual({self.key} <= {self.value})"

    @staticmethod
    def name():
        return "<="


@dataclass
class GreaterThanExpression(BaseExpression):
    """Represents a greater than comparison: field > value"""

    key: str
    value: Any
    type_hint: Any | None = None

    def __repr__(self):
        return f"GreaterThan({self.key} > {self.value})"

    @staticmethod
    def name():
        return ">"


@dataclass
class GreaterThanOrEqualExpression(BaseExpression):
    """Represents a greater than or equal comparison: field >= value"""

    key: str
    value: Any
    type_hint: Any | None = None

    def __repr__(self):
        return f"GreaterThanOrEqual({self.key} >= {self.value})"

    @staticmethod
    def name():
        return ">="


@dataclass
class InExpression(BaseExpression):
    """Represents membership: values in field (e.g., {1,2} in id)"""

    key: str
    value: list[Any]
    type_hint: Any | None = None

    def __repr__(self):
        return f"In({self.key} IN {self.value})"

    @staticmethod
    def name():
        return "in"


@dataclass
class NotInExpression(BaseExpression):
    """Represents NOT IN membership: values not in field"""

    key: str
    value: list[Any]
    type_hint: Any | None = None

    def __repr__(self):
        return f"NotIn({self.key} NOT IN {self.value})"

    @staticmethod
    def name():
        return "not in"


@dataclass
class NotInExpression(BaseExpression):
    """Represents non-membership: value NOT IN field"""

    key: str
    value: list[Any]
    type_hint: Any | None = None

    def __repr__(self):
        return f"NotIn({self.key} NOT IN {self.value})"

    @staticmethod
    def name():
        return "not in"
