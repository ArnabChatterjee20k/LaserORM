import asyncio
import os
import pytest
import pytest_asyncio
from tests.resources import Account
from laserorm.storage.sqlite import SQLite


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture()
def sqlite_db_path(tmp_path):
    return str(tmp_path / "test.db")


@pytest.fixture()
def sqlite_storage(sqlite_db_path):
    return SQLite(sqlite_db_path)


@pytest_asyncio.fixture()
async def initialized_storage(sqlite_storage):
    # Initialize schema for core models used by most tests
    async with sqlite_storage.session() as session:
        await session.init_schema(Account)
    return sqlite_storage
