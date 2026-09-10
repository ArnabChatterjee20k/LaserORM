import os

import pytest

from laserorm.storage.mysql import MySQL, parse_dsn
from .test_storage_base import BaseStorageTest


def mysql_uri() -> str:
    return os.getenv("MYSQL_URI", "mysql://laser:laser@localhost:3306/laserorm")


class TestMySQLStorage(BaseStorageTest):
    """MySQL storage implementation tests"""

    async def get_storage(self):
        storage = MySQL(mysql_uri())
        try:
            async with storage.session() as session:
                await session.execute("DROP TABLE IF EXISTS account", force_commit=True)
                await session.execute("DROP TABLE IF EXISTS doc", force_commit=True)
        except Exception as error:  # pragma: no cover - environment dependent
            pytest.skip(f"MySQL not available: {error}")
        return storage

    async def cleanup_storage(self, storage):
        try:
            async with storage.session() as session:
                await session.execute("DROP TABLE IF EXISTS account", force_commit=True)
                await session.execute("DROP TABLE IF EXISTS doc", force_commit=True)
        except Exception:
            pass


def test_parse_dsn_reads_every_part():
    assert parse_dsn("mysql://user:secret@db.example.com:3307/shop") == {
        "host": "db.example.com",
        "port": 3307,
        "user": "user",
        "password": "secret",
        "db": "shop",
    }


def test_parse_dsn_defaults_the_port():
    assert parse_dsn("mysql://user:secret@localhost/shop")["port"] == 3306


def test_parse_dsn_unescapes_credentials():
    parsed = parse_dsn("mysql://user%40corp:p%40ss@localhost/shop")
    assert parsed["user"] == "user@corp"
    assert parsed["password"] == "p@ss"


def test_parse_dsn_rejects_another_scheme():
    with pytest.raises(ValueError):
        parse_dsn("postgresql://user:secret@localhost/shop")


@pytest.mark.asyncio
async def test_failed_connect_raises_real_error():
    """A session that cannot connect surfaces the connection error, not an
    AttributeError from closing a pool that was never created."""
    storage = MySQL("mysql://nobody:nobody@127.0.0.1:1/nothing")

    with pytest.raises(Exception) as excinfo:
        async with storage.session():
            pass

    assert "NoneType" not in str(excinfo.value)
