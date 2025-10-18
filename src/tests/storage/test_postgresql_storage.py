import pytest
import os
import asyncio
from laserorm.storage.postgresql import PostgreSQL
from .test_storage_base import BaseStorageTest


class TestPostgreSQLStorage(BaseStorageTest):
    """PostgreSQL storage implementation tests"""

    async def get_storage(self):
        """Get PostgreSQL storage instance for testing"""
        postgres_uri = os.getenv(
            "POSTGRES_URI",
            "postgresql://pyauth:pyauth@localhost:5432/pyauth",
        )
        storage = PostgreSQL(postgres_uri)

        # Clean up any existing test data
        async with storage.begin() as session:
            try:
                await session.connection.execute(
                    "DROP TABLE IF EXISTS account CASCADE;"
                )
            except Exception:
                pass  # Table might not exist

        return storage

    async def cleanup_storage(self, storage):
        """Clean up PostgreSQL storage after tests"""
        async with storage.session() as session:
            try:
                await session.connection.execute(
                    "DROP TABLE IF EXISTS account CASCADE;"
                )
            except Exception:
                pass


@pytest.fixture
def postgres_uri():
    """Get PostgreSQL connection URI from environment or use default"""
    return os.getenv(
        "POSTGRES_URI",
        "postgresql://pyauth:pyauth@localhost:5432/pyauth",
    )


@pytest.fixture
async def postgres_storage(postgres_uri):
    """Create PostgreSQL storage instance and ensure clean state"""
    storage = PostgreSQL(postgres_uri)

    # Clean up any existing test data
    async with storage.session() as session:
        try:
            await session.execute("DROP TABLE IF EXISTS account CASCADE;")
        except Exception:
            pass  # Table might not exist

    yield storage

    # Cleanup after test
    async with storage.session() as session:
        try:
            await session.execute("DROP TABLE IF EXISTS account CASCADE;")
        except Exception:
            pass
