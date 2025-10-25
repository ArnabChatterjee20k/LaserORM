from abc import abstractmethod
import json
from .storage import StorageSession
from ..core.schema import Model, MissingDefault, CurrentTimeStamp
from datetime import datetime
from .storage import Index
from typing import Any


class SQLSession(StorageSession):
    async def init_schema(self, model: Model) -> str:
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

    async def create(self, model: Model) -> Model:
        try:
            table_name = type(model).__name__.lower()
            model_values = self.encode(model.get_schema(), model.get_values())
            columns = list(model_values.keys())
            values = list(model_values.values())
            placeholders = self.get_placeholder(len(values))
            column_names = ",".join(columns)
            sql = f"INSERT INTO {table_name} ({column_names}) VALUES ({placeholders}) RETURNING id"
            row_id = await self.execute(sql, values)
            model.id = row_id
            return model
        except Exception as e:
            print(e)
            # raise self.process_exception(e)

    @abstractmethod
    def python_to_sqltype(self, py_type: str) -> str:
        pass

    @abstractmethod
    async def execute(self, query):
        pass

    @abstractmethod
    async def get_placeholder(self, count: int):
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
