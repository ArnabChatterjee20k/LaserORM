from abc import abstractmethod
import json
from .storage import T, StorageSession
from ..core.schema import Schema, MissingDefault, CurrentTimeStamp
from datetime import datetime
from .storage import Index
from typing import Union, Any, get_origin, get_args
from ..core.expressions import (
    BaseExpression,
    AndExpression,
    OrExpression,
    EqualExpression,
    NotEqualExpression,
    LessThanExpression,
    LessThanOrEqualExpression,
    GreaterThanExpression,
    GreaterThanOrEqualExpression,
    InExpression,
    NotInExpression,
)


class SQLSession(StorageSession):
    async def init_schema(self, model: T) -> str:
        table_name = model.__name__.lower()
        schema = model.get_schema()
        columns_sql = []
        indexes: list[Index] = []

        for column, info in schema.items():
            col_type = info["type"]
            default = info["default"]
            primary = info["primary_key"]
            index = info["index"]
            auto_increment = info["auto_increment"]
            unique = info["unique"]

            if index:
                indexes.append({"col": column, "type": col_type})

            if primary:
                columns_sql.append(
                    self.get_primary_key(column, col_type, auto_increment)
                )

            else:
                constraints = ""

                if auto_increment:
                    constraints += " " + self.python_to_sqltype("auto_increment")

                if unique:
                    constraints += " " + "UNIQUE"

                # SQL type
                sql_type = self.python_to_sqltype(col_type)

                # NOT NULL
                not_null = ""
                if isinstance(col_type, list) and "NoneType" not in col_type:
                    not_null = "NOT NULL"
                elif isinstance(col_type, str) and col_type != "json":
                    not_null = "NOT NULL"

                # DEFAULT
                default_sql = ""
                if isinstance(default, CurrentTimeStamp):
                    default_sql = f"DEFAULT {self.get_default_datetime_sql()}"

                elif not isinstance(default, MissingDefault):
                    if col_type == "json":
                        default_sql = f"DEFAULT {self.get_default_json_sql()}"

                    elif isinstance(default, str):
                        default_sql = f"DEFAULT '{default}'"
                    elif default is None:
                        default_sql = "DEFAULT NULL"
                    else:
                        default_sql = f"DEFAULT {default}"

                col_def = " ".join(
                    part
                    for part in [column, sql_type, constraints, not_null, default_sql]
                    if part
                )
                columns_sql.append(col_def)

        create_table_sql = (
            f"CREATE TABLE IF NOT EXISTS {table_name} (\n  "
            + ",\n  ".join(columns_sql)
            + "\n);"
        )
        await self.execute(create_table_sql)
        await self.init_index(table_name, indexes)
        return create_table_sql

    async def create(self, model: T) -> T:
        try:
            table_name = type(model).__name__.lower()
            model_values = self.encode(model.get_schema(), model.get_values())
            columns = list(model_values.keys())
            values = list(model_values.values())
            placeholders = self.get_placeholder(len(values))
            column_names = ",".join(columns)
            sql = f"INSERT INTO {table_name} ({column_names}) VALUES ({placeholders}) RETURNING id"
            result = await self.execute(sql, values)
            model.id = result.lastrowid
            return model
        except Exception as e:
            raise self.process_exception(e)

    @classmethod
    def compile_expression(cls, expression: BaseExpression) -> tuple[str, Any]:
        def resolve_callable(value):
            return value() if callable(value) else value

        def validate_value(value: Any, type_hint: Any) -> bool:
            value = resolve_callable(value)
            if type_hint is None:
                return True
            origin = get_origin(type_hint)
            args = get_args(type_hint)
            if origin is Union:
                return any(validate_value(value, arg) for arg in args)
            if origin is list:
                # Column is list[T] but comparisons generally won't be on list types; allow any
                return isinstance(value, list)
            if origin is dict:
                return isinstance(value, dict)
            if hasattr(type_hint, "__name__"):
                try:
                    return isinstance(value, type_hint)
                except TypeError:
                    return True
            return True

        def validate_collection(values: list[Any], expr: BaseExpression):
            """Validate a list/tuple against a list[...] type hint"""
            type_hint = expr.type_hint
            origin = get_origin(type_hint)
            args = get_args(type_hint)

            # TODO: use type resolution like we have in the schema to_model
            # If column type is list[str], we validate each element as str
            if origin is list and args:
                inner_type = args[0]
                for v in values:
                    if not validate_value(v, inner_type):
                        raise TypeError(
                            f"Invalid IN element type for {expr.key}: {type(v)}. Expected {inner_type}"
                        )
            else:
                if not isinstance(values, (list, tuple, set)):
                    raise TypeError(f"Expected list/tuple/set for {expr.key}")

        def compile(expr: BaseExpression) -> tuple[str, list[Any]]:
            # recursive types(left + right)
            if isinstance(expr, AndExpression):
                left_sql, left_values = compile(expr.left)
                right_sql, right_values = compile(expr.right)

                return f"({left_sql}) AND ({right_sql})", [*left_values, *right_values]

            if isinstance(expr, OrExpression):
                left_sql, left_values = compile(expr.left)
                right_sql, right_values = compile(expr.right)

                return f"({left_sql}) OR ({right_sql})", [*left_values, *right_values]

            # collection operators first (avoid validating the list container as a scalar)
            if isinstance(expr, InExpression):
                values = [resolve_callable(v) for v in list(expr.value)]
                validate_collection(values, expr)
                placeholders = cls.get_placeholder(len(values))
                return f"{expr.key} IN ({placeholders})", values

            if isinstance(expr, NotInExpression):
                values = [resolve_callable(v) for v in list(expr.value)]
                validate_collection(values, expr)
                placeholders = cls.get_placeholder(len(values))
                return f"{expr.key} NOT IN ({placeholders})", values

            # flat scalar operators
            val = resolve_callable(expr.value)
            if not validate_value(val, expr.type_hint):
                raise TypeError(
                    f"Invalid type for {expr.key}: {type(val)}. Expected {expr.type_hint}"
                )
            if isinstance(expr, EqualExpression):
                return f"{expr.key} = {cls.get_placeholder(1)}", [val]
            if isinstance(expr, NotEqualExpression):
                return f"{expr.key} != {cls.get_placeholder(1)}", [val]
            if isinstance(expr, LessThanExpression):

                return f"{expr.key} < {cls.get_placeholder(1)}", [val]
            if isinstance(expr, LessThanOrEqualExpression):

                return f"{expr.key} <= {cls.get_placeholder(1)}", [val]
            if isinstance(expr, GreaterThanExpression):

                return f"{expr.key} > {cls.get_placeholder(1)}", [val]
            if isinstance(expr, GreaterThanOrEqualExpression):

                return f"{expr.key} >= {cls.get_placeholder(1)}", [val]

            d = expr.to_dict()
            raise NotImplementedError(f"Unsupported expression: {d}")

        return compile(expression)

    @abstractmethod
    def python_to_sqltype(self, py_type: str) -> str:
        pass

    @classmethod
    @abstractmethod
    async def get_placeholder(cls, count: int):
        pass

    def get_default_datetime_sql(self):
        return "CURRENT_TIMESTAMP"

    def get_default_json_sql(self):
        return "NULL"

    def get_datetime_format(self):
        """Return the datetime format string for this database"""
        return "%Y-%m-%d %H:%M:%S.%f"

    @abstractmethod
    def format_datetime_for_db(self, dt: datetime) -> Any:
        pass

    def parse_datetime_from_db(self, dt_str: str) -> datetime:
        """Parse datetime from database string"""
        if dt_str is None:
            return None
        try:
            return datetime.strptime(dt_str, self.get_datetime_format())
        except ValueError:
            # Fallback to ISO format if the primary format fails
            try:
                return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
            except ValueError:
                # Last resort - try common formats
                for fmt in [
                    "%Y-%m-%d %H:%M:%S",
                    "%Y-%m-%dT%H:%M:%S",
                    "%Y-%m-%dT%H:%M:%SZ",
                ]:
                    try:
                        return datetime.strptime(dt_str, fmt)
                    except ValueError:
                        continue
                raise ValueError(f"Unable to parse datetime: {dt_str}")

    def encode(self, schema: dict, values: dict):
        new_values = {}
        for key, value in values.items():
            if key in schema:
                key_type = schema.get(key).get("type")
                if "json" in key_type and value is not None:
                    new_values[key] = json.dumps(value)
                elif "datetime" in key_type and isinstance(value, datetime):
                    new_values[key] = self.format_datetime_for_db(value)
                else:
                    new_values[key] = value
        return new_values

    def decode(self, schema: dict, values: dict):
        new_values = {}
        for key, value in values.items():
            if key in schema:
                key_type = schema.get(key).get("type")
                if "json" in key_type and value is not None:
                    new_values[key] = json.loads(value)
                elif "bool" in key_type:
                    new_values[key] = bool(value)
                elif (
                    "datetime" in key_type
                    and value is not None
                    and isinstance(value, str)
                ):
                    new_values[key] = self.parse_datetime_from_db(value)
                else:
                    new_values[key] = value
        return new_values

    @abstractmethod
    def process_exception(self, e: Exception):
        pass

    @abstractmethod
    def get_primary_key(self, column: str, datatype: str, auto_increment: bool):
        pass
