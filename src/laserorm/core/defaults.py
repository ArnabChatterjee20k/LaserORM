"""Sentinel default markers shared by :mod:`laserorm.core.schema` and
:mod:`laserorm.core.model`.

They live in their own module so that ``model`` can use them without importing
``schema`` (which imports ``model``).
"""


class MissingDefault:
    """Marks a field that has no default at all."""

    def __repr__(self):  # pragma: no cover - debugging aid
        return "<MissingDefault>"


class CurrentTimeStamp:
    """Marks a field defaulting to the database's current timestamp."""

    def __repr__(self):  # pragma: no cover - debugging aid
        return "<CurrentTimeStamp>"
