import pytest
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
