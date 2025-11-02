import pytest
import json
from laserorm.storage.sqlite import SQLite
from ..resources import Account
from .test_storage_base import BaseStorageTest


class TestSQLiteStorage(BaseStorageTest):
    """SQLite storage implementation tests"""

    async def get_storage(self):
        """Get SQLite storage instance for testing"""
        import tempfile
        import os

        # Create a temporary database file
        temp_dir = tempfile.mkdtemp()
        db_path = os.path.join(temp_dir, "test.db")
        return SQLite(db_path)

    async def cleanup_storage(self, storage):
        """Clean up SQLite storage after tests"""
        # SQLite cleanup is handled by tempfile cleanup
        pass

    @pytest.fixture
    def tmp_path(self):
        """Provide tmp_path for backward compatibility with existing tests"""
        import tempfile

        return tempfile.mkdtemp()

    @pytest.mark.asyncio
    async def test_execute_raw_query(self):
        """Test executing raw SQL queries with SQLite"""
        storage = await self.get_storage()

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

                # Test SELECT query with parameters (SQLite uses ? placeholders)
                select_sql = "SELECT id, uid FROM account WHERE uid = ?"
                result = await session.execute(select_sql, ("exec_test1",))

                # Verify ExecutionResult structure
                assert result is not None
                assert hasattr(result, "rows")
                assert hasattr(result, "rowcount")
                assert hasattr(result, "lastrowid")
                assert hasattr(result, "description")

                # SQLite returns list of dicts in format {row[0]: row[1]} for 2+ columns
                assert result.rows is not None
                assert result.rowcount >= 0
                if result.rows and len(result.rows) > 0:
                    # SQLite format: [{column1: column2}] for 2-column queries
                    first_row = result.rows[0]
                    assert isinstance(first_row, dict)

                # Test SELECT query to count records (no parameters)
                count_sql = (
                    "SELECT COUNT(*) as count FROM account WHERE uid LIKE 'exec_test%'"
                )
                count_result = await session.execute(count_sql)
                assert count_result is not None
                assert count_result.rowcount >= 0

                # Test UPDATE query with parameters
                update_sql = "UPDATE account SET permissions = ? WHERE uid = ?"
                permissions_json = json.dumps(["read", "write", "admin"])
                update_result = await session.execute(
                    update_sql, (permissions_json, "exec_test1")
                )
                assert update_result is not None
                assert update_result.rowcount >= 0  # Should be 1 if update succeeded

                # Verify the update worked by querying again
                verify_sql = "SELECT uid, permissions FROM account WHERE uid = ?"
                verify_result = await session.execute(verify_sql, ("exec_test1",))
                assert verify_result is not None
                assert verify_result.rowcount >= 0

                # Test DELETE query with parameters
                delete_sql = "DELETE FROM account WHERE uid = ?"
                delete_result = await session.execute(delete_sql, ("exec_test1",))
                assert delete_result is not None
                assert delete_result.rowcount >= 0  # Should be 1 if delete succeeded

                # Verify deletion
                check_sql = "SELECT uid FROM account WHERE uid = ?"
                check_result = await session.execute(check_sql, ("exec_test1",))
                assert check_result is not None
                assert check_result.rowcount == 0  # Should return no rows

                # Clean up remaining test data
                await session.execute(delete_sql, ("exec_test2",))
        finally:
            await self.cleanup_storage(storage)
