from abc import ABC, abstractmethod
from contextlib import asynccontextmanager, AbstractAsyncContextManager
from typing import TypeVar, TypedDict, AsyncGenerator, Any, Union, Type, Optional, List
from dataclasses import dataclass
from ..core.schema import Schema
from ..core.model import Model
from ..core.expressions import BaseExpression


class Index(TypedDict):
    col: str
    type: str


@dataclass
class ColumnMeta:
    """Normalised description of one column of a result set, identical across
    adapters."""

    name: str
    type: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "type": self.type}


@dataclass
class ColumnInfo:
    """Schema level information about a column of a table."""

    name: str
    type: Optional[str] = None
    nullable: bool = True
    default: Any = None
    primary_key: bool = False
    indexed: bool = False
    position: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type,
            "nullable": self.nullable,
            "default": self.default,
            "primary_key": self.primary_key,
            "indexed": self.indexed,
            "position": self.position,
        }


@dataclass
class IndexInfo:
    """Information about an index defined on a table."""

    name: str
    columns: list[str]
    unique: bool = False
    primary: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "columns": list(self.columns),
            "unique": self.unique,
            "primary": self.primary,
        }


@dataclass
class ExecutionResult:
    rows: list[dict[str, Any]] | None
    lastrowid: int | None
    rowcount: int
    description: list[dict[str, Any]] | None
    #: Number of rows written by a DML statement (INSERT/UPDATE/DELETE).
    #: ``0`` for statements that do not write.
    rows_affected: int = 0
    #: True when the statement produced a result set (even an empty one).
    returns_rows: bool = False

    @property
    def columns(self) -> list[str]:
        """Convenience accessor for just the column names."""
        return [column["name"] for column in (self.description or [])]


# Generic TypeVar that works for both Schema and Model
# This allows automatic type inference: if you pass Type[User], you get User back
T = TypeVar("T", bound=Union[Schema, Model])


class StorageSession(ABC):
    def __init__(self, conn):
        self._conn = conn

    @abstractmethod
    async def create(self, model: T) -> T: ...
    @abstractmethod
    async def update(
        self,
        model: Union[T, Type[T]],
        filters: Union[dict, BaseExpression],
        updates: dict,
    ) -> T: ...
    @abstractmethod
    async def delete(
        self, model: Union[T, Type[T]], filters: Union[dict, BaseExpression]
    ) -> bool: ...

    @abstractmethod
    async def bulk_delete(
        self,
        model: Union[T, Type[T]],
        filters: Optional[dict] = None,
        contains: Optional[dict] = None,
    ) -> int: ...
    @abstractmethod
    async def get(
        self,
        model: Union[T, Type[T]],
        for_update: bool = False,
        filters: Optional[Union[dict, BaseExpression]] = None,
        contains: Optional[dict] = None,
    ) -> T: ...
    @abstractmethod
    async def list(
        self,
        model: Union[T, Type[T]],
        limit: int = 25,
        after_id: Optional[int] = None,
        filters: Optional[Union[dict, BaseExpression]] = None,
        contains: Optional[dict] = None,
    ) -> list[T]: ...
    @abstractmethod
    async def begin(self): ...
    @abstractmethod
    async def commit(self): ...
    @abstractmethod
    async def rollback(self): ...
    @abstractmethod
    async def connect(self) -> "StorageSession": ...
    @abstractmethod
    async def close(self): ...
    @abstractmethod
    async def execute(self, sql: str, *args, force_commit=False) -> ExecutionResult: ...
    @abstractmethod
    async def init_schema(self, schema: T): ...
    @abstractmethod
    async def init_index(self, table: str, indexes: List[Index]): ...

    # Introspection: concrete rather than abstract so an adapter that does not
    # implement them still instantiates, and fails only when they are used.
    async def get_schemas(self) -> List[str]:
        """List the namespaces/schemas available on the connection.

        Backends without a notion of schemas return an empty list.
        """
        return []

    async def get_tables(self, schema: Optional[str] = None) -> List[str]:
        """List user tables (and views) visible on the connection."""
        raise NotImplementedError(
            f"{type(self).__name__} does not implement get_tables()"
        )

    async def get_columns(
        self, table: str, schema: Optional[str] = None
    ) -> List[ColumnInfo]:
        """Describe the columns of ``table``."""
        raise NotImplementedError(
            f"{type(self).__name__} does not implement get_columns()"
        )

    async def get_indexes(
        self, table: str, schema: Optional[str] = None
    ) -> List[IndexInfo]:
        """Describe the indexes defined on ``table``."""
        raise NotImplementedError(
            f"{type(self).__name__} does not implement get_indexes()"
        )

    async def count(self, table: str, schema: Optional[str] = None) -> int:
        """Exact row count for ``table``."""
        raise NotImplementedError(
            f"{type(self).__name__} does not implement count()"
        )

    @classmethod
    @abstractmethod
    def compile_expression(cls, expression: BaseExpression):
        str: ...


# to create independent sessions and connection objects and since its returning StorageSession which implements aenter and aexit , we can use `async with storage.session()`
class Storage(ABC):
    def __init__(self, conn_uri: str, debug=False):
        self.conn_uri = conn_uri
        self._debug = debug

    # not using here asyncontextmanager and async to type hint properly
    # AbstractAsyncContextManager -> async and asynccontextmanager
    @abstractmethod
    def session(self) -> AbstractAsyncContextManager[StorageSession]:
        pass

    @asynccontextmanager
    async def begin(self) -> AsyncGenerator[StorageSession, Any]:
        # session = await self.session()
        # session is async context manager
        async with self.session() as session:
            try:
                await session.begin()
                yield session
                await session.commit()
            except Exception as e:
                await session.rollback()
                raise e
            finally:
                await session.close()

    @staticmethod
    def get_model_class(model: Union[T, Type[T]]) -> Type[T]:
        # Model instance (Schema()) is provided
        if isinstance(model, Schema) or isinstance(model, Model):
            return model.__class__
        # Model class is given
        elif (isinstance(model, type) and issubclass(model, Schema)) or (
            isinstance(model, type) and issubclass(model, Model)
        ):
            return model

        raise TypeError("Invalid model type")
