from .sql import SQLSession, is_json_type
from contextlib import asynccontextmanager
from .storage import Storage, ExecutionResult, ColumnInfo, IndexInfo
from ..core.schema import Schema
import aiomysql
import json
from datetime import datetime
from typing import TypeVar, Type, Union, Optional, List, Any
from urllib.parse import urlparse, unquote
from .storage import Index
from ..core.expressions import BaseExpression

T = TypeVar("T", bound=Schema)

#: Length used for indexable string columns; TEXT cannot be indexed or made
#: UNIQUE in MySQL without a prefix length.
VARCHAR_LENGTH = 255


def parse_dsn(uri: str) -> dict:
    """Turn a mysql:// URI into aiomysql connect() keyword arguments."""
    parsed = urlparse(uri)
    if parsed.scheme not in ("mysql", "mariadb", "mysql+aiomysql"):
        raise ValueError(f"Not a MySQL connection URI: {uri}")

    return {
        "host": parsed.hostname or "localhost",
        "port": parsed.port or 3306,
        "user": unquote(parsed.username) if parsed.username else None,
        "password": unquote(parsed.password) if parsed.password else None,
        "db": parsed.path.lstrip("/") or None,
    }


class MySQLSession(SQLSession):
    supports_returning = False

    def __init__(self, conn_uri: str):
        self.conn_uri = conn_uri
        self.pool: aiomysql.Pool = None
        self.connection: aiomysql.Connection = None
        self.in_transaction = False

    def python_to_sqltype(self, py_type):
        if isinstance(py_type, list):
            main_type = next((t for t in py_type if t != "NoneType"), "str")
            return self.python_to_sqltype(main_type)

        mapping = {
            "str": f"VARCHAR({VARCHAR_LENGTH})",
            "bool": "TINYINT(1)",
            "int": "INT",
            "float": "DOUBLE",
            "datetime": "DATETIME(6)",
            "json": "JSON",
            "dict": "JSON",
            "list": "JSON",
            "NoneType": f"VARCHAR({VARCHAR_LENGTH})",
            "auto_increment": "AUTO_INCREMENT",
        }
        return mapping.get(py_type, f"VARCHAR({VARCHAR_LENGTH})")

    def format_bool_literal(self, value: bool) -> str:
        return "1" if value else "0"

    def get_default_datetime_sql(self):
        # the precision must match the DATETIME(6) the column is declared with
        return "CURRENT_TIMESTAMP(6)"

    def get_default_sql(self, default, col_type) -> str:
        # MySQL rejects a literal DEFAULT on JSON, TEXT and BLOB columns
        if is_json_type(col_type):
            return ""
        return super().get_default_sql(default, col_type)

    @asynccontextmanager
    async def get_connection(self):
        if self.connection is not None:
            yield self.connection
            return
        if self.pool is None:
            raise ConnectionError(
                "MySQL session is not connected - call connect() first"
            )
        async with self.pool.acquire() as connection:
            yield connection

    async def execute(self, sql: str, *args, force_commit=False) -> ExecutionResult:
        try:
            return await self._execute(sql, *args, force_commit=force_commit)
        except Exception as e:
            raise self.process_exception(e)

    async def _execute(self, sql: str, *args, force_commit=False) -> ExecutionResult:
        if len(args) == 1 and isinstance(args[0], (list, tuple)):
            args = args[0]

        async with self.get_connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(sql, tuple(args) if args else None)

                returns_rows = cursor.description is not None
                description = (
                    [{"name": column[0], "type": None} for column in cursor.description]
                    if returns_rows
                    else None
                )

                rows = []
                if returns_rows:
                    fetched = await cursor.fetchall()
                    names = [column["name"] for column in description]
                    rows = [dict(zip(names, row)) for row in fetched]

                rows_affected = 0 if returns_rows else max(cursor.rowcount, 0)
                lastrowid = cursor.lastrowid or None

            if force_commit and not self.in_transaction:
                await connection.commit()

            return ExecutionResult(
                rows=rows,
                lastrowid=lastrowid,
                rowcount=len(rows) if returns_rows else rows_affected,
                description=description,
                rows_affected=rows_affected,
                returns_rows=returns_rows,
            )

    async def init_index(self, table: str, indexes: list[Index]):
        if not indexes:
            return

        existing = {index.name for index in await self.get_indexes(table)}
        for index in indexes:
            column = index.get("col")
            index_name = f"{table}_{column}_idx"
            if index_name in existing:
                continue
            await self.execute(
                f"CREATE INDEX {index_name} ON {self.quote_identifier(table)} "
                f"({self.quote_identifier(column)})"
            )

    def _decode_row(self, model, table, schema: dict, row: dict):
        row = dict(row)
        row_id = row.pop("id", None)
        row = {key: value for key, value in row.items() if key in schema}
        instance = table(**self.decode(schema, row))
        instance.id = row_id
        return instance

    def _build_where(self, filters):
        """Compile filters into a WHERE fragment plus its parameters."""
        if issubclass(type(filters), BaseExpression):
            where, values = self.compile_expression(filters)
            return where, list(values)
        clauses = [f"{self.quote_identifier(key)} = %s" for key in filters]
        return " AND ".join(clauses), list(filters.values())

    async def get(
        self,
        model: Union[T, Type[T]],
        for_update: bool = False,
        filters: dict | BaseExpression = None,
        contains: dict = None,
    ) -> T:
        if not filters:
            raise ValueError("Filters must be provided for MySQL adapter")

        try:
            table = Storage.get_model_class(model)
            table_name = table.__name__.lower()
            where, values = self._build_where(filters)
            clauses = [where]

            if contains:
                model_schema = model.get_schema()
                for key, contain_value in contains.items():
                    identifier = self.quote_identifier(key)
                    if is_json_type(model_schema.get(key, {}).get("type")):
                        clauses.append(f"JSON_CONTAINS({identifier}, %s)")
                        values.append(json.dumps(contain_value))
                    else:
                        clauses.append(f"{identifier} LIKE %s")
                        values.append(f"%{contain_value}%")

            query = (
                f"SELECT * FROM {self.quote_identifier(table_name)} "
                f"WHERE {' AND '.join(clauses)} LIMIT 1"
            )
            if for_update:
                query += " FOR UPDATE"

            result = await self.execute(query, values)
            if not result.rows:
                return None

            schema = model.get_schema(exclude=["id"])
            return self._decode_row(model, table, schema, result.rows[0])
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

            clauses = []
            values: list[Any] = []

            if filters:
                where, filter_values = self._build_where(filters)
                clauses.append(where)
                values.extend(filter_values)

            if after_id is not None:
                clauses.append("id > %s")
                values.append(after_id)

            if contains:
                model_schema = model.get_schema()
                for key, contain_value in contains.items():
                    identifier = self.quote_identifier(key)
                    if is_json_type(model_schema.get(key, {}).get("type")):
                        clauses.append(f"JSON_CONTAINS({identifier}, %s)")
                        values.append(json.dumps(contain_value))
                    else:
                        clauses.append(f"{identifier} LIKE %s")
                        values.append(f"%{contain_value}%")

            where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            limit_sql = "" if limit is None or limit < 0 else f"LIMIT {int(limit)}"
            query = (
                f"SELECT * FROM {self.quote_identifier(table_name)} "
                f"{where_sql} ORDER BY id ASC {limit_sql}"
            )

            result = await self.execute(query, values)
            schema = model.get_schema(exclude=["id"])
            return [
                self._decode_row(model, table, schema, row)
                for row in (result.rows or [])
            ]
        except Exception as e:
            raise self.process_exception(e)

    async def update(self, model: T, filters: dict | BaseExpression, updates: dict):
        if not filters:
            raise ValueError("filters are empty")
        try:
            table = Storage.get_model_class(model)
            table_name = self.quote_identifier(table.__name__.lower())

            schema = model.get_schema(exclude=["id"])
            updates = self.encode(schema, updates)
            if not updates:
                return None

            set_clause = ", ".join(
                f"{self.quote_identifier(attr)} = %s" for attr in updates
            )
            where, where_values = self._build_where(filters)

            # MySQL has no RETURNING, so the row is read back afterwards; the
            # filters still match it because the update does not touch the id
            await self.execute(
                f"UPDATE {table_name} SET {set_clause} WHERE {where}",
                [*updates.values(), *where_values],
            )

            result = await self.execute(
                f"SELECT * FROM {table_name} WHERE {where} LIMIT 1", where_values
            )
            if not result.rows:
                return None
            return self._decode_row(model, table, schema, result.rows[0])
        except Exception as e:
            raise self.process_exception(e)

    async def delete(self, model: Union[T, Type[T]], filters: dict | BaseExpression):
        try:
            table = Storage.get_model_class(model)
            table_name = self.quote_identifier(table.__name__.lower())
            where, values = self._build_where(filters)

            result = await self.execute(
                f"DELETE FROM {table_name} WHERE {where}", values
            )
            return result.rows_affected > 0
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
            table_name = self.quote_identifier(table.__name__.lower())

            clauses = []
            values: list[Any] = []

            if filters:
                where, filter_values = self._build_where(filters)
                clauses.append(where)
                values.extend(filter_values)

            if contains:
                model_schema = model.get_schema()
                for key, contain_value in contains.items():
                    identifier = self.quote_identifier(key)
                    if is_json_type(model_schema.get(key, {}).get("type")):
                        clauses.append(f"JSON_CONTAINS({identifier}, %s)")
                        values.append(json.dumps(contain_value))
                    else:
                        clauses.append(f"{identifier} LIKE %s")
                        values.append(f"%{contain_value}%")

            sql = f"DELETE FROM {table_name}"
            if clauses:
                sql += f" WHERE {' AND '.join(clauses)}"

            result = await self.execute(sql, values)
            return result.rows_affected
        except Exception as e:
            raise self.process_exception(e)

    async def begin(self):
        self.connection = await self.pool.acquire()
        await self.connection.begin()
        self.in_transaction = True

    async def commit(self):
        if self.connection is not None:
            await self.connection.commit()
            return
        async with self.pool.acquire() as connection:
            await connection.commit()

    async def rollback(self):
        if self.connection is not None:
            await self.connection.rollback()
            return
        async with self.pool.acquire() as connection:
            await connection.rollback()

    async def connect(self):
        self.pool = await aiomysql.create_pool(
            **parse_dsn(self.conn_uri), autocommit=True
        )
        return self

    async def close(self):
        # connect() may have failed; closing a pool that was never created
        # masks the real error with an AttributeError
        if self.pool is None:
            self.connection = None
            self.in_transaction = False
            return
        if self.connection is not None:
            self.pool.release(self.connection)
            self.connection = None
        self.in_transaction = False
        self.pool.close()
        await self.pool.wait_closed()
        self.pool = None

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------
    async def get_schemas(self) -> List[str]:
        """MySQL databases are the closest thing it has to schemas."""
        result = await self.execute(
            "SELECT schema_name AS name FROM information_schema.schemata "
            "WHERE schema_name NOT IN "
            "('information_schema', 'mysql', 'performance_schema', 'sys') "
            "ORDER BY schema_name"
        )
        return [row["name"] for row in (result.rows or [])]

    async def get_tables(self, schema: Optional[str] = None) -> List[str]:
        result = await self.execute(
            "SELECT table_name AS name FROM information_schema.tables "
            "WHERE table_schema = COALESCE(%s, DATABASE()) ORDER BY table_name",
            [schema],
        )
        return [row["name"] for row in (result.rows or [])]

    async def get_columns(
        self, table: str, schema: Optional[str] = None
    ) -> List[ColumnInfo]:
        schema, table = self.split_qualified_name(table, schema)
        result = await self.execute(
            "SELECT column_name AS name, "
            "       column_type AS type, "
            "       is_nullable = 'YES' AS nullable, "
            "       column_default AS default_value, "
            "       ordinal_position AS position, "
            "       column_key AS column_key "
            "FROM information_schema.columns "
            "WHERE table_schema = COALESCE(%s, DATABASE()) AND table_name = %s "
            "ORDER BY ordinal_position",
            [schema, table],
        )
        if not result.rows:
            return []

        indexed = set()
        for index in await self.get_indexes(table, schema):
            indexed.update(index.columns)

        return [
            ColumnInfo(
                name=row["name"],
                type=row["type"],
                nullable=bool(row["nullable"]),
                default=row["default_value"],
                primary_key=row["column_key"] == "PRI",
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
            "SELECT index_name AS name, "
            "       MAX(non_unique) = 0 AS is_unique, "
            "       GROUP_CONCAT(column_name ORDER BY seq_in_index) AS columns "
            "FROM information_schema.statistics "
            "WHERE table_schema = COALESCE(%s, DATABASE()) AND table_name = %s "
            "GROUP BY index_name ORDER BY index_name",
            [schema, table],
        )
        return [
            IndexInfo(
                name=row["name"],
                columns=(row["columns"] or "").split(","),
                unique=bool(row["is_unique"]),
                primary=row["name"] == "PRIMARY",
            )
            for row in (result.rows or [])
        ]

    async def count(self, table: str, schema: Optional[str] = None) -> int:
        schema, table = self.split_qualified_name(table, schema)
        result = await self.execute(
            f"SELECT COUNT(*) AS total FROM {self.quote_identifier(table, schema)}"
        )
        rows = result.rows or [{}]
        return int(rows[0].get("total") or 0)

    @staticmethod
    def split_qualified_name(table: str, schema: Optional[str] = None):
        if "." in table:
            table_schema, _, table_name = table.partition(".")
            return table_schema.strip("`"), table_name.strip("`")
        return schema, table.strip("`")

    @staticmethod
    def quote_identifier(name: str, schema: Optional[str] = None) -> str:
        """MySQL quotes identifiers with backticks."""
        quoted = "`" + str(name).replace("`", "``") + "`"
        if schema:
            return MySQLSession.quote_identifier(schema) + "." + quoted
        return quoted

    @classmethod
    def get_placeholder(cls, count: int):
        return ",".join("%s" for _ in range(count))

    def get_datetime_format(self):
        return "%Y-%m-%d %H:%M:%S.%f"

    def get_primary_key(self, column: str, datatype: str, auto_increment: bool):
        sql_def = [column, "INT" if auto_increment else self.python_to_sqltype(datatype)]
        if auto_increment:
            sql_def.append(self.python_to_sqltype("auto_increment"))
        sql_def.append("PRIMARY KEY")
        return " ".join(sql_def)

    def format_datetime_for_db(self, dt: datetime):
        return dt

    def process_exception(self, e: Exception):
        message = str(e)
        code = getattr(e, "args", [None])[0]

        if isinstance(e, aiomysql.IntegrityError):
            if code == 1062 or "Duplicate entry" in message:
                return Exception(f"Duplicate entry error: {message}")
            if code == 1048 or "cannot be null" in message:
                return Exception(f"Missing required field: {message}")
            if code in (1451, 1452):
                return Exception(f"Foreign key constraint violation: {message}")
            return Exception(f"Integrity error: {message}")

        if isinstance(e, aiomysql.OperationalError):
            if code == 1045:
                return Exception(
                    f"Authentication failed: Invalid username or password. {message}"
                )
            if code == 1049:
                return Exception(f"Database not found: {message}")
            if code in (2003, 2002):
                return Exception(
                    f"Connection refused: Unable to connect to MySQL server. {message}"
                )
            if code == 1146 or "doesn't exist" in message:
                return Exception(f"Table not found: {message}")
            if code == 1054:
                return Exception(f"Invalid column: {message}")
            if code == 1142 or "denied" in message:
                return Exception(f"Permission denied: {message}")
            return Exception(f"Operational error: {message}")

        if isinstance(e, aiomysql.ProgrammingError):
            if code == 1146:
                return Exception(f"Table not found: {message}")
            if code == 1054:
                return Exception(f"Invalid column: {message}")
            if code == 1064:
                return Exception(f"SQL syntax error: {message}")
            return Exception(f"Programming error: {message}")

        if isinstance(e, aiomysql.Error):
            return Exception(f"MySQL error: {message}")

        return e


class MySQL(Storage):
    def __init__(self, connection_uri: str, debug: bool = False):
        if not connection_uri:
            raise ValueError("MySQL requires a connection URI")
        super().__init__(str(connection_uri), debug=debug)

    @asynccontextmanager
    async def session(self):
        session = MySQLSession(self.conn_uri)
        try:
            try:
                await session.connect()
            except Exception as error:
                raise session.process_exception(error) from error
            yield session
        finally:
            await session.close()
