from .sql import SQLSession, StorageSession
from contextlib import asynccontextmanager
from .storage import Storage
from ..model import Model
import asyncpg
from asyncpg.transaction import Transaction
import json
from datetime import datetime
from typing import TypeVar, Type, Union, AsyncGenerator, Any
from .storage import Index

T = TypeVar("T", bound=Model)

# connect = creates a pool
# in every opertion -> a new connection will be used from the pool
# during transaction , begin creates a new connection and transaction
# it will be used throughout for operations
# in close -> the connection is relased from the pool


class PostgreSQLSession(SQLSession):
    def __init__(self, conn_uri: str):
        self.conn_uri = conn_uri
        self.pool: asyncpg.Pool = None
        self.connection: asyncpg.Connection = None
        self.ongoing_transaction: Transaction = None

    def python_to_sqltype(self, py_type):
        # If union, pick the first non-NoneType
        if isinstance(py_type, list):
            main_type = next((t for t in py_type if t != "NoneType"), "TEXT")
            return self.python_to_sqltype(main_type)

        mapping = {
            "str": "TEXT",
            "bool": "BOOLEAN",
            "int": "INTEGER",
            "float": "REAL",
            "datetime": "TIMESTAMP",
            "json": "JSONB",
            "NoneType": "TEXT",
            "auto_increment": "SERIAL",
        }
        return mapping.get(py_type, "TEXT")

    @asynccontextmanager
    async def get_connection(
        self, with_transaction=False
    ) -> AsyncGenerator[asyncpg.Connection, Any]:
        """
        Async force commit if we reconnect while having an active connection.
        Else we need to do operation per connnection.
        So to reuse connection from pool or for getting ongoing connection
        """
        if self.ongoing_transaction:
            yield self.connection
        else:
            async with self.pool.acquire() as conn:
                if with_transaction:
                    async with conn.transaction():
                        yield conn
                else:
                    yield conn

    async def execute(self, sql: str, *args, force_commit=False):
        try:
            row: asyncpg.Record = None
            # Flatten args if needed
            if len(args) == 1 and isinstance(args[0], (list, tuple)):
                args = args[0]

            async with self.get_connection(with_transaction=force_commit) as connection:
                row = await connection.fetchrow(sql, *args)

            if row:
                return row.get("id")
            return row
        except Exception as e:
            print(f"Error executing SQL: {sql}, args: {args}, error: {e}")
            raise

    async def init_index(self, table: str, indexes: list[Index]):
        if not indexes:
            return

        for index in indexes:
            col = index.get("col")
            index_type = index.get("type")

            index_name = f"{table}_{col}_idx"
            index_type = "USING GIN" if index_type == "json" else ""
            stmt = f"CREATE INDEX IF NOT EXISTS {index_name} ON {table} {index_type} ({col});"
            await self.execute(stmt)

    async def get(
        self,
        model: Union[T, Type[T]],
        for_update: bool = False,
        filters: dict = None,
        contains: dict = None,
    ) -> T:
        if not filters:
            raise ValueError("Filters must be provided for PostgreSQL adapter")

        try:
            table = Storage.get_model_class(model)
            table_name = table.__name__.lower()

            where_clauses = []
            values = []

            # Filters
            for idx, (key, value) in enumerate(filters.items(), start=1):
                where_clauses.append(f"{key} = ${idx}")
                values.append(value)

            # Contains filters
            if contains:
                schema = model.get_schema()
                for key, contain_value in contains.items():
                    idx = len(values) + 1
                    field_type = schema.get(key, {}).get("type")
                    if field_type == "json":
                        where_clauses.append(f"{key} @> ${idx}::jsonb")
                        values.append(json.dumps(contain_value))
                    else:
                        where_clauses.append(f"{key} LIKE ${idx}")
                        values.append(f"%{contain_value}%")

            where_sql = " AND ".join(where_clauses)
            query = f"SELECT * FROM {table_name} WHERE {where_sql} LIMIT 1"
            if for_update:
                query += " FOR UPDATE"
            async with self.get_connection() as connection:
                row = await connection.fetchrow(query, *values)

            if not row:
                return None
            schema = model.get_schema(exclude=["id"])
            result_data = dict(row)
            result_data.pop("id", None)
            result = table(**self.decode(schema, result_data))
            result.id = row["id"]

            return result

        except Exception as e:
            raise self.process_exception(e)

    async def list(
        self,
        model: Union[T, Type[T]],
        limit: int = 25,
        after_id: int | None = None,
        filters: dict | None = None,
        contains: dict | None = None,
    ):
        try:
            table = Storage.get_model_class(model)
            table_name = table.__name__.lower()

            where_clauses = []
            values = []

            if filters:
                for key, value in filters.items():
                    idx = len(values) + 1
                    where_clauses.append(f"{key} = ${idx}")
                    values.append(value)

            if after_id is not None:
                idx = len(values) + 1
                where_clauses.append(f"id > ${idx}")
                values.append(after_id)

            if contains:
                schema = model.get_schema()
                for key, contain_value in contains.items():
                    idx = len(values) + 1
                    field_type = schema.get(key, {}).get("type")
                    if field_type == "json":
                        where_clauses.append(f"{key} @> ${idx}::jsonb")
                        values.append(json.dumps(contain_value))
                    else:
                        where_clauses.append(f"{key} LIKE ${idx}")
                        values.append(f"%{contain_value}%")

            where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

            query = f"""
                SELECT * FROM {table_name}
                {where_sql}
                ORDER BY id ASC
                LIMIT {limit}
            """
            async with self.get_connection() as connection:
                rows = await connection.fetch(query, *values)

            results = []
            schema = model.get_schema(exclude=["id"])
            for row in rows:
                result_data = dict(row)
                result_data.pop("id", None)
                obj = table(**self.decode(schema, result_data))
                obj.id = row["id"]
                results.append(obj)

            return results

        except Exception as e:
            raise self.process_exception(e)

    async def update(self, model: Model, filters: dict, updates: dict):
        if not filters:
            raise ValueError("filters are empty")
        try:
            table = Storage.get_model_class(model)
            table_name = table.__name__.lower()

            schema = model.get_schema(exclude=["id"])
            updates = self.encode(schema, updates)
            if not updates:
                return None

            set_clauses = []
            values = []

            for attr, value in updates.items():
                idx = len(values) + 1
                set_clauses.append(f"{attr} = ${idx}")
                values.append(value)

            where_clauses = []
            for attr, value in filters.items():
                idx = len(values) + 1
                where_clauses.append(f"{attr} = ${idx}")
                values.append(value)

            set_clause = ", ".join(set_clauses)
            where_clause = " AND ".join(where_clauses)

            sql = (
                f"UPDATE {table_name} SET {set_clause} WHERE {where_clause} RETURNING *"
            )
            async with self.get_connection() as connection:
                row = await connection.fetchrow(sql, *values)

            if not row:
                return None

            schema = model.get_schema(exclude=["id"])
            result_data = dict(row)
            result_data.pop("id", None)
            result = table(**self.decode(schema, result_data))
            result.id = row["id"]
            return result

        except Exception as e:
            raise self.process_exception(e)

    async def delete(self, model: Union[T, Type[T]], filters: dict):
        try:
            table = Storage.get_model_class(model)
            table_name = table.__name__.lower()

            where_clauses = []
            values = []

            for attr, value in filters.items():
                idx = len(values) + 1
                where_clauses.append(f"{attr} = ${idx}")
                values.append(value)

            where_clause = " AND ".join(where_clauses)
            sql = f"DELETE FROM {table_name} WHERE {where_clause}"

            await self.execute(sql, *values)
            return True
        except Exception as e:
            raise self.process_exception(e)

    async def bulk_delete(
        self,
        model: Union[T, Type[T]],
        filters: dict = None,
        contains: dict = None,
    ) -> int:
        try:
            table = Storage.get_model_class(model)
            table_name = table.__name__.lower()

            where_clauses = []
            values = []

            if filters:
                for attr, value in filters.items():
                    idx = len(values) + 1
                    where_clauses.append(f"{attr} = ${idx}")
                    values.append(value)

            if contains:
                schema = model.get_schema()
                for key, contain_value in contains.items():
                    idx = len(values) + 1
                    if schema.get(key, {}).get("type") == "json":
                        where_clauses.append(f"{key} @> ${idx}::jsonb")
                        values.append(json.dumps(contain_value))
                    else:
                        where_clauses.append(f"{key} LIKE ${idx}")
                        values.append(f"%{contain_value}%")

            where_clause = " AND ".join(where_clauses) if where_clauses else ""
            sql = f"DELETE FROM {table_name}"
            if where_clause:
                sql += f" WHERE {where_clause}"

            result = await self.ongoing_transaction.execute(sql, *values)
            return int(result.split()[-1]) if result else 0
        except Exception as e:
            raise self.process_exception(e)

    async def rollback(self):
        if self.ongoing_transaction:
            await self.ongoing_transaction.rollback()
            return
        async with self.pool.acquire() as connection:
            await connection.execute("ROLLBACK")

    async def begin(self):
        # not using the async with self.pool.acquire() as during the exit the connection is released
        # doing it manually
        self.connection = await self.pool.acquire()
        self.ongoing_transaction = self.connection.transaction()
        await self.ongoing_transaction.start()

    async def commit(self):
        if self.ongoing_transaction:
            await self.ongoing_transaction.commit()
            return
        async with self.pool.acquire() as connection:
            await connection.execute("COMMIT")

    async def connect(self):
        self.pool = await asyncpg.create_pool(self.conn_uri)
        return self

    async def close(self):
        if self.ongoing_transaction:
            self.ongoing_transaction = None
            await self.pool.release(self.connection)
            self.connection = None
        await self.pool.close()

    def get_placeholder(self, count: int):
        return ",".join([f"${i}" for i in range(1, count + 1)])

    def get_datetime_format(self):
        """PostgreSQL uses ISO format for datetime storage"""
        return "%Y-%m-%d %H:%M:%S.%f"

    def get_primary_key(self, column: str, datatype: str, auto_increment: bool):
        sql_def = [column]
        if auto_increment:
            sql_def.append(self.python_to_sqltype("auto_increment"))
        else:
            sql_def.append(self.python_to_sqltype(datatype))
        sql_def.append("PRIMARY KEY")
        return " ".join(sql_def)

    def format_datetime_for_db(self, dt: datetime) -> str:
        """Format datetime for database storage"""
        if dt is None:
            return None
        return dt

    def process_exception(self, e: Exception):
        if isinstance(e, asyncpg.IntegrityConstraintViolationError):
            msg = str(e)
            if "duplicate key value violates unique constraint" in msg:
                return Exception(f"Duplicate entry error: {msg}")
            elif "violates not-null constraint" in msg:
                return Exception(f"Missing required field: {msg}")
            return Exception(f"Integrity error: {msg}")

        elif isinstance(e, asyncpg.PostgresError):
            msg = str(e)
            if "relation" in msg and "does not exist" in msg:
                return Exception(f"Table not found: {msg}")
            elif "column" in msg and "does not exist" in msg:
                return Exception(f"Invalid column: {msg}")
            return Exception(f"PostgreSQL error: {msg}")

        return e


class PostgreSQL(Storage):
    def __init__(self, connection_uri: str):
        self.conn_uri = connection_uri

    @asynccontextmanager
    async def session(self):
        session = PostgreSQLSession(self.conn_uri)
        try:
            await session.connect()
            yield session
        except Exception as e:
            raise e
        finally:
            await session.close()
