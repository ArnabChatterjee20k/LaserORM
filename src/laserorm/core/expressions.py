from dataclasses import dataclass
from typing import Any
from abc import ABC, abstractmethod


# Intarnal expressions layer for comparators and binary expressions
class BaseComparisonExpression(ABC):

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

    def __and__(self, other: "BaseComparisonExpression"):
        return AndExpression(self, other)

    def __or__(self, other: "BaseComparisonExpression"):
        return OrExpression(self, other)

    def __repr__(self):
        return f"<Expr key={self.key} value={self.value}>"


class Expression(BaseComparisonExpression):
    """
    Represents a symbolic expression used when accessing a Column at the class level.
    Example: Account.id -> <Expression attribute='id'>
    """

    __slots__ = ("_key", "_value", "_metadata")

    def __init__(self, key: str, value: Any, metadata: dict = {}):
        self._key = key
        self._value = value
        self._metadata = metadata

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


@dataclass
class AndExpression(BaseComparisonExpression):
    left: BaseComparisonExpression
    right: BaseComparisonExpression

    def __repr__(self):
        return f"({self.left} AND {self.right})"

    @staticmethod
    def name():
        return "and"


@dataclass
class OrExpression(BaseComparisonExpression):
    left: BaseComparisonExpression
    right: BaseComparisonExpression

    def __repr__(self):
        return f"({self.left} OR {self.right})"

    @staticmethod
    def name():
        return "or"


@dataclass
class EqualExpression(BaseComparisonExpression):
    """Represents an equality comparison: field == value"""

    key: str
    value: Any

    def __repr__(self):
        return f"Equal({self.key} == {self.value})"

    @staticmethod
    def name():
        return "=="


@dataclass
class NotEqualExpression(BaseComparisonExpression):
    """Represents an inequality comparison: field != value"""

    key: str
    value: Any

    def __repr__(self):
        return f"NotEqual({self.key} != {self.value})"

    @staticmethod
    def name():
        return "!="


@dataclass
class LessThanExpression(BaseComparisonExpression):
    """Represents a less than comparison: field < value"""

    key: str
    value: Any

    def __repr__(self):
        return f"LessThan({self.key} < {self.value})"

    @staticmethod
    def name():
        return "<"


@dataclass
class LessThanOrEqualExpression(BaseComparisonExpression):
    """Represents a less than or equal comparison: field <= value"""

    key: str
    value: Any

    def __repr__(self):
        return f"LessThanOrEqual({self.key} <= {self.value})"

    @staticmethod
    def name():
        return "<="


@dataclass
class GreaterThanExpression(BaseComparisonExpression):
    """Represents a greater than comparison: field > value"""

    key: str
    value: Any

    def __repr__(self):
        return f"GreaterThan({self.key} > {self.value})"

    @staticmethod
    def name():
        return ">"


@dataclass
class GreaterThanOrEqualExpression(BaseComparisonExpression):
    """Represents a greater than or equal comparison: field >= value"""

    key: str
    value: Any

    def __repr__(self):
        return f"GreaterThanOrEqual({self.key} >= {self.value})"

    @staticmethod
    def name():
        return ">="
