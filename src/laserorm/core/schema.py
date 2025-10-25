from abc import ABC
from dataclasses import dataclass, asdict, fields, MISSING, field
from typing import get_origin, get_args, Union, Optional, Any, ClassVar, TypedDict
from types import UnionType
import datetime


class MissingDefault:
    pass


class CurrentTimeStamp:
    pass


class FieldMetadataOptions(TypedDict):
    index: Optional[bool] = False
    primary_key: Optional[bool] = False
    unique: Optional[bool] = False
    auto_increment: Optional[bool] = False


def create_field(metadata: FieldMetadataOptions, **fieldOptions):
    return field(metadata=metadata, **fieldOptions)


@dataclass
class Model(ABC):
    # making both exclude class var to ignore during data representation(fields() ignore classvar)
    # including id in exclude to provide it in the schema and not get transfered in the get_value
    # init=False => cant init a value as it is auto
    exclude: ClassVar[list[str]] = ["id"]
    schema_exclude: ClassVar[list[str]] = []

    id: Optional[int] = field(
        default=None,
        metadata={"primary_key": True, "index": True, "auto_increment": True},
        init=False,
    )

    # convert the model to dict form
    def to_dict(self, exclude: list[str] = [], include_none: bool = True) -> dict:
        data = asdict(self)
        return {
            k: v
            for k, v in data.items()
            if k not in self.exclude
            and k not in exclude
            and (include_none or v is not None)
        }

    def get_fields(self):
        return {f.name for f in fields(self)}

    # todo: Have a mechanism to ignore some fields externally by passing ignorable values in the function
    def get_values(self):
        """
        Return a dictionary representing the values to be inserted in the DB.
        If user provided the value then use it else for the default dont use it
        Or if the schema allows using None
        """
        insert_data = {}
        for f in fields(self):
            origin = get_origin(f.type)
            if f.name in self.exclude:
                continue

            value = getattr(self, f.name, None)
            if value is None:
                # check if schema allows None or not
                if origin is Union or origin is UnionType:
                    types = [
                        t.__name__ if hasattr(t, "__name__") else str(t)
                        for t in get_args(f.type)
                    ]
                    if "NoneType" in types:
                        insert_data[f.name] = value
            else:
                insert_data[f.name] = value

        return insert_data

    @classmethod
    def get_schema(cls, exclude=[]):
        """Generate json schema; default values are ignored and only default_factory are considered"""
        schema = {}
        for field in fields(cls):
            if field.name in exclude or field.name in cls.schema_exclude:
                continue
            field_type = field.type
            field_name = field.name
            origin = get_origin(field_type)
            metadata = field.metadata
            default = MissingDefault()
            if field.default_factory is not MISSING:
                if isinstance(field_type, type) and issubclass(
                    field_type, datetime.datetime
                ):
                    default = CurrentTimeStamp()

                else:
                    default = field.default_factory()

            schema[field_name] = {
                "type": None,
                "sub_type": None,
                "default": default,
                "primary_key": metadata.get("primary_key", False),
                "index": metadata.get("index", False),
                "unique": metadata.get("unique", False),
                "auto_increment": metadata.get("auto_increment", False),
            }
            if origin is Union or origin is UnionType:
                schema[field_name]["type"] = [
                    t.__name__ if hasattr(t, "__name__") else str(t)
                    for t in get_args(field_type)
                ]
            # only if we have something like list[type] or List[type] otherwise if we have list[type] | None it will get ignored as it will be union
            elif (
                origin in (list, dict)
                or str(field_type).startswith("typing.List")
                or str(field_type).startswith("typing.Dict")
            ):
                schema[field_name]["type"] = "json"
                if origin == list or str(field_type).startswith("typing.List"):
                    schema[field_name]["sub_type"] = "list"
                elif origin == dict or str(field_type).startswith("typing.Dict"):
                    schema[field_name]["sub_type"] = "dict"

            else:
                schema[field_name]["type"] = [
                    (
                        field_type.__name__
                        if hasattr(field_type, "__name__")
                        else str(field_type)
                    )
                ]

        return schema
