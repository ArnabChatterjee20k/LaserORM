from .sql import SQLSession
from contextlib import asynccontextmanager
from .storage import T, Storage, ExecutionResult, ColumnInfo, IndexInfo
import asyncpg
from asyncpg.transaction import Transaction
import json
import re
from datetime import datetime
from typing import TypeVar, Type, Union, AsyncGenerator, Any, Optional, List
from .storage import Index
from ..core.expressions import BaseExpression


#: Trailing row count in a Postgres command tag, e.g. "INSERT 0 3" -> 3.
_STATUS_ROWCOUNT = re.compile(r"(\d+)\s*$")


def _rows_affected(status: Optional[str]) -> int:
    """Extract the affected-row count from a Postgres command tag."""
    if not status:
        return 0
    match = _STATUS_ROWCOUNT.search(status.strip())
    return int(match.group(1)) if match else 0


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
            "dict": "JSONB",
            "list": "JSONB",
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
            if self.pool is None:
                raise ConnectionError(
                    "PostgreSQL session is not connected - call connect() first"
                )
            async with self.pool.acquire() as conn:
                if with_transaction:
                    async with conn.transaction():
                        yield conn
                else:
                    yield conn

    async def execute(self, sql: str, *args, force_commit=False) -> ExecutionResult:
        # Flatten args if needed
        if len(args) == 1 and isinstance(args[0], (list, tuple)):
            args = args[0]
        async with self.get_connection(with_transaction=force_commit) as connection:
            # prepared so the result set columns are known even with zero rows
            try:
                stmt = await connection.prepare(sql)
            except asyncpg.PostgresSyntaxError as error:
                # multi-statement scripts cannot be prepared; the simple query
                # protocol runs them, but takes no bind parameters
                if "multiple commands" not in str(error) or args:
                    raise
                status = await connection.execute(sql)
                return ExecutionResult(
                    rows=[],
                    lastrowid=None,
                    rowcount=0,
                    description=None,
                    rows_affected=_rows_affected(status),
                    returns_rows=False,
                )

            attributes = stmt.get_attributes()
            returns_rows = bool(attributes)
            description = (
                [
                    {
                        "name": attribute.name,
                        "type": (
                            attribute.type.name
                            if hasattr(attribute.type, "name")
                            else None
                        ),
                    }
                    for attribute in attributes
                ]
                if returns_rows
                else None
            )

            records = await stmt.fetch(*args)
            rows = [dict(record) for record in records]

            get_status = getattr(stmt, "get_statusmsg", None)
            status = get_status() if callable(get_status) else None
            rows_affected = 0 if returns_rows else _rows_affected(status)

            return ExecutionResult(
                rows=rows,
                lastrowid=(rows[0] if rows else {}).get("id"),
                rowcount=len(rows) if returns_rows else rows_affected,
                description=description,
                rows_affected=rows_affected,
                returns_rows=returns_rows,
            )

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
        filters: dict | BaseExpression = None,
        contains: dict = None,
    ) -> T:
        if not filters:
            raise ValueError("Filters must be provided for PostgreSQL adapter")

        try:
            table = Storage.get_model_class(model)
            table_name = table.__name__.lower()

            where_clauses = []
            values = []

            if issubclass(type(filters), BaseExpression):
                where_sql, where_vals = self.compile_expression(filters)
                where_clauses.append(where_sql)
                values.extend(where_vals)
            else:
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
        filters: dict | BaseExpression | None = None,
        contains: dict | None = None,
    ) -> list[T]:
        try:
            table = Storage.get_model_class(model)
            table_name = table.__name__.lower()

            where_clauses = []
            values = []

            if filters:
                if issubclass(type(filters), BaseExpression):
                    where_sql, where_vals = self.compile_expression(filters)
                    where_clauses.append(where_sql)
                    values.extend(where_vals)
                else:
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

            limit_sql = "" if limit is None or limit < 0 else f"LIMIT {int(limit)}"
            query = (
                f"SELECT * FROM {table_name} {where_sql} ORDER BY id ASC {limit_sql}"
            )
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

    async def update(self, model: T, filters: dict | BaseExpression, updates: dict):
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
                if "json" in schema.get(attr).get("type") and value is not None:
                    set_clauses.append(f"{attr} = ${idx}::jsonb")
                else:
                    set_clauses.append(f"{attr} = ${idx}")
                values.append(value)

            where_clauses = []
            if issubclass(type(filters), BaseExpression):
                where_sql, where_vals = self.compile_expression(filters)
                offset = len(values)
                # replacing the $i in compiled expression via replacing as asyncpg works via $index
                # though placeholder is used but $i will be always $1
                # making index will be hard accross functions as index is mutated here + will be mutated in the compiled expression as well
                for i in range(1, len(where_vals) + 1):
                    where_sql = where_sql.replace(f"${i}", f"${i + offset}")
                where_clauses.append(where_sql)
                values.extend(where_vals)
            else:
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

    async def delete(self, model: Union[T, Type[T]], filters: dict | BaseExpression):
        try:
            table = Storage.get_model_class(model)
            table_name = table.__name__.lower()

            where_clauses = []
            values = []

            if issubclass(type(filters), BaseExpression):
                where_sql, where_vals = self.compile_expression(filters)
                where_clauses.append(where_sql)
                values.extend(where_vals)
            else:
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
        filters: dict | BaseExpression = None,
        contains: dict = None,
    ) -> int:
        try:
            table = Storage.get_model_class(model)
            table_name = table.__name__.lower()

            where_clauses = []
            values = []

            if filters:
                if issubclass(type(filters), BaseExpression):
                    where_sql, where_vals = self.compile_expression(filters)
                    where_clauses.append(where_sql)
                    values.extend(where_vals)
                else:
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

            result = await self.execute(sql, *values)
            return result.rows_affected
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
        # connect() may have failed; closing a pool that was never created
        # masks the real error with an AttributeError
        if self.pool is None:
            self.connection = None
            self.ongoing_transaction = None
            return
        if self.ongoing_transaction:
            self.ongoing_transaction = None
            if self.connection is not None:
                await self.pool.release(self.connection)
            self.connection = None
        try:
            await self.pool.close()
        finally:
            self.pool = None

    @classmethod
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

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------
    async def get_schemas(self) -> List[str]:
        result = await self.execute(
            "SELECT nspname AS name FROM pg_catalog.pg_namespace "
            "WHERE nspname NOT LIKE 'pg\\_%' AND nspname <> 'information_schema' "
            "ORDER BY nspname"
        )
        return [row["name"] for row in (result.rows or [])]

    async def get_tables(self, schema: Optional[str] = None) -> List[str]:
        result = await self.execute(
            "SELECT table_name AS name FROM information_schema.tables "
            "WHERE table_schema = $1 ORDER BY table_name",
            [schema or "public"],
        )
        return [row["name"] for row in (result.rows or [])]

    async def get_columns(
        self, table: str, schema: Optional[str] = None
    ) -> List[ColumnInfo]:
        schema, table = self.split_qualified_name(table, schema)
        result = await self.execute(
            "SELECT column_name AS name, "
            "       data_type AS type, "
            "       is_nullable = 'YES' AS nullable, "
            "       column_default AS default_value, "
            "       ordinal_position AS position "
            "FROM information_schema.columns "
            "WHERE table_schema = $1 AND table_name = $2 "
            "ORDER BY ordinal_position",
            [schema, table],
        )
        if not result.rows:
            return []

        primary_keys = set()
        indexed = set()
        for index in await self.get_indexes(table, schema):
            indexed.update(index.columns)
            if index.primary:
                primary_keys.update(index.columns)

        return [
            ColumnInfo(
                name=row["name"],
                type=row["type"],
                nullable=bool(row["nullable"]),
                default=row["default_value"],
                primary_key=row["name"] in primary_keys,
                indexed=row["name"] in indexed,
                position=int(row["position"] or 0),
            )
            for row in result.rows
        ]

    async def get_indexes(
        self, table: str, schema: Optional[str] = None
    ) -> List[IndexInfo]:
        schema, table = self.split_qualified_name(table, schema)
        result = await self.execute(
            "SELECT i.relname AS name, "
            "       ix.indisunique AS is_unique, "
            "       ix.indisprimary AS is_primary, "
            "       array_agg(a.attname ORDER BY a.attnum) AS columns "
            "FROM pg_class t "
            "JOIN pg_namespace n ON n.oid = t.relnamespace "
            "JOIN pg_index ix ON t.oid = ix.indrelid "
            "JOIN pg_class i ON i.oid = ix.indexrelid "
            "JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(ix.indkey) "
            "WHERE n.nspname = $1 AND t.relname = $2 "
            "GROUP BY i.relname, ix.indisunique, ix.indisprimary "
            "ORDER BY i.relname",
            [schema, table],
        )
        return [
            IndexInfo(
                name=row["name"],
                columns=list(row["columns"] or []),
                unique=bool(row["is_unique"]),
                primary=bool(row["is_primary"]),
            )
            for row in (result.rows or [])
        ]

    async def count(self, table: str, schema: Optional[str] = None) -> int:
        schema, table = self.split_qualified_name(table, schema)
        qualified = self.quote_identifier(table, schema)
        result = await self.execute(f"SELECT COUNT(*) AS total FROM {qualified}")
        rows = result.rows or [{}]
        return int(rows[0].get("total") or 0)

    @staticmethod
    def split_qualified_name(table: str, schema: Optional[str] = None):
        """Split a possibly ``schema.table`` name into its two parts."""
        if "." in table:
            table_schema, _, table_name = table.partition(".")
            return table_schema.strip('"'), table_name.strip('"')
        return (schema or "public"), table.strip('"')

    @staticmethod
    def quote_identifier(name: str, schema: Optional[str] = None) -> str:
        """Quote a table/column identifier for safe interpolation."""
        quoted = '"' + str(name).replace('"', '""') + '"'
        if schema:
            return PostgreSQLSession.quote_identifier(schema) + "." + quoted
        return quoted

    def process_exception(self, e: Exception):
        """
        Process and categorize exceptions from asyncpg operations.
        Handles connection errors, authentication errors, integrity violations,
        syntax errors, and other PostgreSQL-specific errors.
        """
        msg = str(e)
        error_module = getattr(type(e), "__module__", "")
        msg_lower = msg.lower()

        # Connection errors - handle first as they're most critical
        if isinstance(e, asyncpg.PostgresConnectionError):
            if "connection refused" in msg_lower or "could not connect" in msg_lower:
                return Exception(
                    f"Connection refused: Unable to connect to PostgreSQL server. {msg}"
                )
            elif "timeout" in msg_lower:
                return Exception(
                    f"Connection timeout: Database connection timed out. {msg}"
                )
            elif "network" in msg_lower or "socket" in msg_lower:
                return Exception(f"Network error: Connection network issue. {msg}")
            elif "connection" in msg_lower and "failure" in msg_lower:
                return Exception(f"Connection failure: {msg}")
            return Exception(f"Connection error: {msg}")

        # Authentication errors - check specific types first
        if isinstance(e, asyncpg.InvalidPasswordError):
            return Exception(
                f"Authentication failed: Invalid username or password. {msg}"
            )

        if isinstance(e, asyncpg.InvalidAuthorizationSpecificationError):
            return Exception(
                f"Authorization error: Invalid authorization specification. {msg}"
            )

        # Integrity constraint violations
        if isinstance(e, asyncpg.IntegrityConstraintViolationError):
            if "duplicate key value violates unique constraint" in msg:
                return Exception(f"Duplicate entry error: {msg}")
            elif "violates not-null constraint" in msg:
                return Exception(f"Missing required field: {msg}")
            elif "violates foreign key constraint" in msg:
                return Exception(f"Foreign key constraint violation: {msg}")
            elif "violates check constraint" in msg:
                return Exception(f"Check constraint violation: {msg}")
            return Exception(f"Integrity error: {msg}")

        # Syntax errors
        if isinstance(e, asyncpg.PostgresSyntaxError):
            return Exception(f"SQL syntax error: {msg}")

        # Other PostgreSQL errors (catch-all for PostgresError and its subclasses)
        if isinstance(e, asyncpg.PostgresError):
            # Check for authentication errors in message
            if "password authentication failed" in msg_lower:
                return Exception(
                    f"Authentication failed: Invalid username or password. {msg}"
                )
            elif "authentication failed" in msg_lower:
                return Exception(f"Authentication failed: {msg}")
            # Check for common operational errors
            elif "relation" in msg_lower and "does not exist" in msg_lower:
                return Exception(f"Table not found: {msg}")
            elif "column" in msg_lower and "does not exist" in msg_lower:
                return Exception(f"Invalid column: {msg}")
            elif "permission denied" in msg_lower:
                return Exception(f"Permission denied: Insufficient privileges. {msg}")
            elif "database" in msg_lower and "does not exist" in msg_lower:
                return Exception(f"Database not found: {msg}")
            elif "syntax error" in msg_lower:
                return Exception(f"SQL syntax error: {msg}")
            elif "too many connections" in msg_lower:
                return Exception(
                    f"Connection limit exceeded: Too many database connections. {msg}"
                )
            elif "server closed the connection" in msg_lower:
                return Exception(
                    f"Connection closed: Server closed the connection unexpectedly. {msg}"
                )
            return Exception(f"PostgreSQL error: {msg}")

        # Check if it's any other asyncpg exception by module name
        if error_module.startswith("asyncpg"):
            return Exception(f"AsyncPG error: {msg}")

        # Return original exception if not an asyncpg error
        return e


class PostgreSQL(Storage):
    def __init__(self, connection_uri: str, debug: bool = False):
        if not connection_uri:
            raise ValueError("PostgreSQL requires a connection URI")
        super().__init__(str(connection_uri), debug=debug)

    @asynccontextmanager
    async def session(self):
        session = PostgreSQLSession(self.conn_uri)
        try:
            try:
                await session.connect()
            except Exception as error:
                raise session.process_exception(error) from error
            yield session
        finally:
            await session.close()
