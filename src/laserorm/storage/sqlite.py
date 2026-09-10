from .sql import SQLSession
from contextlib import asynccontextmanager
from .storage import Storage, ExecutionResult, ColumnInfo, IndexInfo
from ..core.schema import Schema
import aiosqlite
import os
from datetime import datetime
from typing import TypeVar, Type, Union, Optional, List, Any
from .storage import Index
from ..core.expressions import BaseExpression

T = TypeVar("T", bound=Schema)


class SQLiteSession(SQLSession):
    def __init__(self, conn_uri: str):
        self.conn_uri = conn_uri
        self.connection: aiosqlite.Connection = None

    def python_to_sqltype(self, py_type):
        # If union, pick the first non-NoneType
        if isinstance(py_type, list):
            main_type = next((t for t in py_type if t != "NoneType"), "TEXT")
            return self.python_to_sqltype(main_type)

        mapping = {
            "str": "TEXT",
            "bool": "INTEGER",
            "int": "INTEGER",
            "float": "REAL",
            "datetime": "TEXT",  # store as ISO string
            "json": "TEXT",
            "dict": "TEXT",
            "list": "TEXT",
            "NoneType": "TEXT",
            "auto_increment": "AUTOINCREMENT",
        }
        return mapping.get(py_type, "TEXT")

    def format_bool_literal(self, value: bool) -> str:
        return "1" if value else "0"

    async def execute(self, sql: str, *args, force_commit=False) -> ExecutionResult:
        async with self.connection.execute(sql, *args) as cursor:
            # commit is getting controlled externally via transactions
            if force_commit:
                await self.connection.commit()

            # set even when the statement returns zero rows
            returns_rows = cursor.description is not None
            description = (
                [
                    {"name": column[0], "type": None}
                    for column in cursor.description
                ]
                if returns_rows
                else None
            )

            rows = []
            if returns_rows:
                fetched = await cursor.fetchall()
                names = [column["name"] for column in description]
                rows = [dict(zip(names, row)) for row in fetched]

            rows_affected = 0 if returns_rows else max(cursor.rowcount, 0)

            return ExecutionResult(
                rows=rows,
                lastrowid=cursor.lastrowid,
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
            index_name = f"{table}_{col}_idx"

            # check if index exists
            stmt = """
            SELECT name 
            FROM sqlite_master 
            WHERE type='index' AND name=?;
            """
            cursor = await self.connection.execute(stmt, (index_name,))
            existing_index = await cursor.fetchone()
            await cursor.close()

            if existing_index:
                continue  # skip, already exists

            # create the index
            create_stmt = f"CREATE INDEX {index_name} ON {table}({col});"
            await self.connection.execute(create_stmt)

        await self.connection.commit()

    def _row_to_instance(self, table, schema: dict, names: list, row) -> Any:
        """Build a model instance from a raw row, mapping by column name so a
        table whose physical column order differs from the model still reads.
        """
        data = dict(zip(names, row))
        row_id = data.pop("id", None)
        data = {key: value for key, value in data.items() if key in schema}
        instance = table(**self.decode(schema, data))
        instance.id = row_id
        return instance

    async def get(
        self,
        model: Union[T, Type[T]],
        for_update=False,
        filters: dict | BaseExpression = None,
        contains: dict = None,
    ) -> T:
        if not filters:
            raise ValueError("Filters must be provided for sqlite adapter")
        try:
            table = Storage.get_model_class(model)

            table_name = table.__name__.lower()
            if issubclass(type(filters), BaseExpression):
                # print(self.compile_expression(filters))
                where, values = self.compile_expression(filters)
            else:
                where = " AND ".join([f"{attribute}=?" for attribute in filters])
                values = [value for value in filters.values()]

            select = f"SELECT * FROM {table_name} WHERE {where} LIMIT 1"
            async with self.connection.execute(select, values) as cursor:
                row = await cursor.fetchone()
                names = [column[0] for column in (cursor.description or [])]
            if not row:
                return None

            # removing id from the schema and the row as we can't init id
            schema = model.get_schema(exclude=["id"])
            result = self._row_to_instance(table, schema, names, row)

            if contains:
                schema = model.get_schema()
                for key, contain_value in contains.items():
                    value = getattr(result, key, None)

                    # If value is missing, only pass if both are None
                    if value is None:
                        if contain_value is None:
                            continue
                        return None

                    if schema.get(key, {}).get("sub_type") == "list":
                        if not set(value).intersection(set(contain_value)):
                            return None
                    else:
                        # in case of dictionaries or other types
                        if contain_value not in value:
                            return None
            return result
        except Exception as e:
            raise self.process_exception(e)

    async def list(
        self, model: T, limit=25, after_id: int = None, filters=None, contains=None
    ) -> list[T]:
        try:
            table = Storage.get_model_class(model)
            table_name = table.__name__.lower()

            where = ""
            values = []

            where_clauses = []
            if filters:
                if issubclass(type(filters), BaseExpression):
                    compiled_sql, compiled_values = self.compile_expression(filters)
                    where_clauses.append(compiled_sql)
                    values.extend(compiled_values)
                else:
                    where_clauses.extend(f"{attribute}=?" for attribute in filters)
                    values.extend(filters.values())

            if after_id is not None:
                where_clauses.append("id > ?")
                values.append(after_id)

            if where_clauses:
                where = "WHERE " + " AND ".join(where_clauses)

            limit_sql = "" if limit is None or limit < 0 else f"LIMIT {int(limit)}"
            select = (
                f"SELECT * FROM {table_name} {where} ORDER BY id ASC {limit_sql}"
            ).strip()

            async with self.connection.execute(select, values) as cursor:
                rows = await cursor.fetchall()
                names = [column[0] for column in (cursor.description or [])]

            results = []

            schema = model.get_schema(exclude=["id"])
            for row in rows:
                obj = self._row_to_instance(table, schema, names, row)

                if contains:
                    valid = True
                    for key, contain_value in contains.items():
                        value = getattr(obj, key, None)
                        if value is None or contain_value not in value:
                            valid = False
                            break
                    if not valid:
                        continue

                results.append(obj)

            return results
        except Exception as e:
            raise self.process_exception(e)

    async def update(self, model: T, filters: dict | BaseExpression, updates: dict):
        """Update a row based on model.id using get_schema() order"""
        if not filters:
            raise ValueError("filters are empty")
        try:
            table = Storage.get_model_class(model)
            table_name = table.__name__.lower()

            schema = model.get_schema(exclude=["id"])
            updates = self.encode(schema, updates)

            if not updates:
                return None

            set_clause = ", ".join([f"{attr}=?" for attr in updates])
            set_values = list(updates.values())

            if issubclass(type(filters), BaseExpression):
                where_clause, where_values = self.compile_expression(filters)
            else:
                where_clause = " AND ".join([f"{attr}=?" for attr in filters])
                where_values = list(filters.values())

            sql = (
                f"UPDATE {table_name} SET {set_clause} WHERE {where_clause} RETURNING *"
            )
            async with self.connection.execute(
                sql, (*set_values, *where_values)
            ) as cursor:
                row = await cursor.fetchone()
                names = [column[0] for column in (cursor.description or [])]
                if not row:
                    return None
            return self._row_to_instance(table, schema, names, row)
        except Exception as e:
            raise self.process_exception(e)

    async def delete(self, model: Union[T, Type[T]], filters: dict | BaseExpression):
        """Delete a row based on model id"""
        try:
            table = Storage.get_model_class(model)
            table_name = table.__name__.lower()

            if issubclass(type(filters), BaseExpression):
                where_clause, where_values = self.compile_expression(filters)
            else:
                where_clause = " AND ".join([f"{attr}=?" for attr in filters])
                where_values = list(filters.values())

            sql = f"DELETE FROM {table_name} WHERE {where_clause}"

            async with self.connection.execute(sql, (*where_values,)) as cursor:
                return cursor.rowcount > 0
        except Exception as e:
            raise self.process_exception(e)

    async def bulk_delete(
        self,
        model: Union[T, Type[T]],
        filters: dict | BaseExpression = None,
        contains: dict = None,
    ) -> int:
        """Delete multiple rows based on filters and contains conditions"""
        try:
            table = Storage.get_model_class(model)
            table_name = table.__name__.lower()

            where_clauses = []
            values = []

            # Add filter conditions
            if filters:
                if issubclass(type(filters), BaseExpression):
                    where_sql, compiled_values = self.compile_expression(filters)
                    where_clauses.append(where_sql)
                    values.extend(compiled_values)
                else:
                    filter_clauses = [f"{attr}=?" for attr in filters]
                    where_clauses.extend(filter_clauses)
                    values.extend(filters.values())

            # Add contains conditions (for JSON fields)
            if contains:
                for key, contain_value in contains.items():
                    where_clauses.append(f"{key} LIKE ?")
                    values.append(f"%{contain_value}%")

            # Build the DELETE query
            if where_clauses:
                where_clause = " AND ".join(where_clauses)
                sql = f"DELETE FROM {table_name} WHERE {where_clause}"
            else:
                # If no filters, delete all rows (be careful!)
                sql = f"DELETE FROM {table_name}"

            # Execute the delete and get the number of affected rows
            async with self.connection.execute(sql, values) as cursor:
                return cursor.rowcount
        except Exception as e:
            raise self.process_exception(e)

    async def rollback(self):
        return await self.connection.rollback()

    async def begin(self):
        # "BEGIN" defaults to DEFERRED mode, which delays acquiring a write lock
        # until the first write operation. This can cause "database is locked" errors
        # when multiple async tasks start transactions concurrently.
        # Using "BEGIN IMMEDIATE" acquires the write lock upfront, preventing such conflicts.
        await self.connection.execute("BEGIN IMMEDIATE")

    async def commit(self):
        await self.connection.commit()

    async def connect(self):
        directory = os.path.dirname(os.path.abspath(str(self.conn_uri)))
        if directory and not os.path.isdir(directory):
            os.makedirs(directory, exist_ok=True)
        self.connection = await aiosqlite.connect(self.conn_uri)
        await self.connection.execute("PRAGMA foreign_keys = ON")
        return self

    async def close(self):
        # connect() may have failed; closing a connection that was never
        # opened masks the real error with an AttributeError
        if self.connection is None:
            return
        try:
            await self.connection.close()
        finally:
            self.connection = None

    @classmethod
    def get_placeholder(cls, count: int):
        return ",".join("?" for _ in range(count))

    def get_datetime_format(self):
        """SQLite uses ISO format for datetime storage"""
        return "%Y-%m-%d %H:%M:%S.%f"

    def get_primary_key(self, column: str, datatype: str, auto_increment: bool):
        sql_def = [column, self.python_to_sqltype(datatype), "PRIMARY KEY"]
        if auto_increment:
            sql_def.append(self.python_to_sqltype("auto_increment"))
        return " ".join(sql_def)

    def format_datetime_for_db(self, dt: datetime) -> str:
        """Format datetime for database storage"""
        if dt is None:
            return None
        return dt.strftime(self.get_datetime_format())

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------
    async def get_schemas(self) -> List[str]:
        """SQLite has no schemas (attached databases aside)."""
        return []

    async def get_tables(self, schema: Optional[str] = None) -> List[str]:
        result = await self.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type IN ('table', 'view') AND name NOT LIKE 'sqlite_%' "
            "ORDER BY name"
        )
        return [row["name"] for row in (result.rows or [])]

    async def get_columns(
        self, table: str, schema: Optional[str] = None
    ) -> List[ColumnInfo]:
        table_name = self.quote_identifier(table)
        result = await self.execute(f"PRAGMA table_info({table_name})")
        if not result.rows:
            return []

        indexed = set()
        for index in await self.get_indexes(table):
            indexed.update(index.columns)

        columns = []
        for row in result.rows:
            columns.append(
                ColumnInfo(
                    name=row.get("name"),
                    type=(row.get("type") or "").upper() or None,
                    nullable=not bool(row.get("notnull")),
                    default=row.get("dflt_value"),
                    primary_key=bool(row.get("pk")),
                    indexed=row.get("name") in indexed or bool(row.get("pk")),
                    position=int(row.get("cid") or 0) + 1,
                )
            )
        return columns

    async def get_indexes(
        self, table: str, schema: Optional[str] = None
    ) -> List[IndexInfo]:
        table_name = self.quote_identifier(table)
        listing = await self.execute(f"PRAGMA index_list({table_name})")
        indexes = []
        for row in listing.rows or []:
            index_name = row.get("name")
            detail = await self.execute(
                f"PRAGMA index_info({self.quote_identifier(index_name)})"
            )
            columns = [
                item.get("name") for item in (detail.rows or []) if item.get("name")
            ]
            indexes.append(
                IndexInfo(
                    name=index_name,
                    columns=columns,
                    unique=bool(row.get("unique")),
                    primary=row.get("origin") == "pk",
                )
            )
        return indexes

    async def count(self, table: str, schema: Optional[str] = None) -> int:
        result = await self.execute(
            f"SELECT COUNT(*) AS total FROM {self.quote_identifier(table)}"
        )
        rows = result.rows or [{}]
        return int(rows[0].get("total") or 0)

    @staticmethod
    def quote_identifier(name: str, schema: Optional[str] = None) -> str:
        """Quote a table/column identifier for safe interpolation."""
        quoted = '"' + str(name).replace('"', '""') + '"'
        if schema:
            return SQLiteSession.quote_identifier(schema) + "." + quoted
        return quoted

    def process_exception(self, e: Exception):
        if isinstance(e, aiosqlite.IntegrityError):
            msg = str(e)
            if "UNIQUE constraint failed" in msg:
                return Exception(f"Duplicate entry error: {msg}")
            elif "NOT NULL constraint failed" in msg:
                return Exception(f"Missing required field: {msg}")
            return Exception(f"Integrity error: {msg}")

        elif isinstance(e, aiosqlite.OperationalError):
            msg = str(e)
            if "no such table" in msg:
                return Exception(f"Table not found: {msg}")
            elif "no such column" in msg:
                return Exception(f"Invalid column: {msg}")
            return Exception(f"Operational error: {msg}")

        return e


class SQLite(Storage):
    def __init__(self, connection_uri: str, debug: bool = False):
        if not connection_uri:
            raise ValueError("SQLite requires a database path")
        super().__init__(str(connection_uri), debug=debug)

    @asynccontextmanager
    async def session(self):
        session = SQLiteSession(self.conn_uri)
        try:
            await session.connect()
            yield session
        finally:
            await session.close()
