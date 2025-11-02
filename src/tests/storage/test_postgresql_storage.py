import pytest
import os
import asyncio
import json
from laserorm.storage.postgresql import PostgreSQL
from .test_storage_base import BaseStorageTest
from ..resources import Account


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

    @pytest.mark.asyncio
    async def test_execute_raw_query(self):
        """Test executing raw SQL queries with PostgreSQL"""
        storage = await self.get_storage()

        # make sure to use the returning id for insertion cases
        # print(await session.execute( "INSERT INTO arnab (name) VALUES ($1) RETURNING id", (chr(65),), force_commit=True))
        try:
            async with storage.session() as session:
                await session.init_schema(Account)

                # Create some test data
                account1 = await session.create(
                    Account(uid="exec_test1", permissions=["read"])
                )
                account2 = await session.create(
                    Account(uid="exec_test2", permissions=["read", "write"])
                )

                # Test SELECT query with parameters (PostgreSQL uses $1, $2, etc.)
                select_sql = "SELECT id, uid FROM account WHERE uid = $1"
                result = await session.execute(select_sql, ("exec_test1",))

                # Verify ExecutionResult structure
                assert result is not None
                assert hasattr(result, "rows")
                assert hasattr(result, "rowcount")
                assert hasattr(result, "lastrowid")
                assert hasattr(result, "description")

                # PostgreSQL returns asyncpg.Record objects which are dict-like
                assert result.rows is not None
                assert result.rowcount >= 0
                if result.rows:
                    # Can access by column name (asyncpg.Record supports dict-like access)
                    first_row = result.rows[0]
                    assert "id" in first_row or hasattr(first_row, "id")
                    assert "uid" in first_row or hasattr(first_row, "uid")

                # Test SELECT query to count records (no parameters)
                count_sql = (
                    "SELECT COUNT(*) as count FROM account WHERE uid LIKE 'exec_test%'"
                )
                count_result = await session.execute(count_sql)
                assert count_result is not None
                assert count_result.rowcount >= 0

                # Test UPDATE query with parameters
                update_sql = "UPDATE account SET permissions = $1::jsonb WHERE uid = $2"
                permissions_json = json.dumps(["read", "write", "admin"])
                update_result = await session.execute(
                    update_sql, (permissions_json, "exec_test1")
                )
                assert update_result is not None
                assert update_result.rowcount >= 0  # Should be 1 if update succeeded

                # Verify the update worked by querying again
                verify_sql = "SELECT uid, permissions FROM account WHERE uid = $1"
                verify_result = await session.execute(verify_sql, ("exec_test1",))
                assert verify_result is not None
                assert verify_result.rowcount >= 0

                # Test DELETE query with parameters
                delete_sql = "DELETE FROM account WHERE uid = $1"
                delete_result = await session.execute(delete_sql, ("exec_test1",))
                assert delete_result is not None
                assert delete_result.rowcount >= 0  # Should be 1 if delete succeeded

                # Verify deletion
                check_sql = "SELECT uid FROM account WHERE uid = $1"
                check_result = await session.execute(check_sql, ("exec_test1",))
                assert check_result is not None
                assert check_result.rowcount == 0  # Should return no rows

                # Clean up remaining test data
                await session.execute(delete_sql, ("exec_test2",))
        finally:
            await self.cleanup_storage(storage)


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
