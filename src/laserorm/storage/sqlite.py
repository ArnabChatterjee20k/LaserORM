from .sql import SQLSession, StorageSession
from contextlib import asynccontextmanager
from .storage import Storage
from ..core.schema import Model
import aiosqlite
from datetime import datetime
from typing import TypeVar, Type, Union
from .storage import Index
from psycopg2 import sql

T = TypeVar("T", bound=Model)


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
            "NoneType": "TEXT",
            "auto_increment": "AUTOINCREMENT",
        }
        return mapping.get(py_type, "TEXT")

    async def execute(self, sql: str, *args, force_commit=False):
        async with self.connection.execute(sql, *args) as cursor:
            # commit is getting controlled externall via transactions
            if force_commit:
                await self.connection.commit()
            return cursor.lastrowid

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

    async def get(
        self,
        model: Union[T, Type[T]],
        for_update=False,
        filters: dict = None,
        contains: dict = None,
    ) -> T:
        if not filters:
            raise ValueError("Filters must be provided for sqlite adapter")
        try:
            table = Storage.get_model_class(model)

            table_name = table.__name__.lower()
            where = " AND ".join([f"{attribute}=?" for attribute in filters])
            values = [value for value in filters.values()]
            select = f"SELECT * FROM {table_name} where {where} LIMIT 1"
            async with self.connection.execute(select, values) as cursor:
                row = await cursor.fetchone()
            if not row:
                return None

            # removing id from the from the schema and the row as we can't init id
            schema = model.get_schema(exclude=["id"])
            result = dict(zip(schema, row[1:]))
            result = table(**self.decode(schema, result))
            result.id = row[0]

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
        self, model, limit=25, after_id: int = None, filters=None, contains=None
    ):
        try:
            table = Storage.get_model_class(model)
            table_name = table.__name__.lower()

            where = ""
            values = []

            if filters:
                where_clauses = [f"{attribute}=?" for attribute in filters]
                values.extend(filters.values())

                if after_id is not None:
                    where_clauses.append("id > ?")
                    values.append(after_id)

                where = " AND ".join(where_clauses)
                where = f"WHERE {where}"
            elif after_id is not None:
                where = "WHERE id > ?"
                values.append(after_id)

            select = f"SELECT * FROM {table_name} {where} ORDER BY id ASC LIMIT {limit}"

            async with self.connection.execute(select, values) as cursor:
                rows = await cursor.fetchall()

            results = []

            schema = model.get_schema(exclude=["id"])
            for row in rows:
                result_data = dict(zip(schema, row[1:]))
                obj = table(**self.decode(schema, result_data))
                obj.id = row[0]

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

    async def update(self, model: Model, filters: dict, updates: dict):
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

            where_clause = " AND ".join([f"{attr}=?" for attr in filters])
            where_values = list(filters.values())

            sql = (
                f"UPDATE {table_name} SET {set_clause} WHERE {where_clause} RETURNING *"
            )
            async with self.connection.execute(
                sql, (*set_values, *where_values)
            ) as cursor:
                row = await cursor.fetchone()
                if not row:
                    return None
            # excluding id in the row
            result = dict(zip(schema, row[1:]))
            result = table(**self.decode(schema, result))
            result.id = row[0]
            return result
        except Exception as e:
            raise self.process_exception(e)

    async def delete(self, model: Union[T, Type[T]], filters: dict):
        """Delete a row based on model id"""
        try:
            table = Storage.get_model_class(model)
            table_name = table.__name__.lower()

            where_clause = " AND ".join([f"{attr}=?" for attr in filters])
            where_values = list(filters.values())

            sql = f"DELETE FROM {table_name} WHERE {where_clause}"

            await self.connection.execute(sql, (*where_values,))

            return True
        except Exception as e:
            raise self.process_exception(e)

    async def bulk_delete(
        self,
        model: Union[T, Type[T]],
        filters: dict = None,
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
        self.connection = await aiosqlite.connect(self.conn_uri)
        return self

    async def close(self):
        await self.connection.close()

    def get_placeholder(self, count: int):
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
    def __init__(self, connection_uri: str):
        self.conn_uri = connection_uri

    @asynccontextmanager
    async def session(self):
        session = SQLiteSession(self.conn_uri)
        try:
            await session.connect()
            yield session
        except Exception as e:
            raise e
        finally:
            await session.close()
