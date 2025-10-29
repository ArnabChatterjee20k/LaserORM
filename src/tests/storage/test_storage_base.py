"""
Base test class for storage adapters
All storage implementations should inherit from this class to ensure consistent testing
"""

import pytest
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict
from laserorm.core.schema import Schema
from laserorm.core.model import Model
from ..resources import Account


# Model version of Account for testing
class AccountModel(Model):
    uid: str
    permissions: list[str]
    password: str | None = None
    is_active: bool = True
    is_blocked: bool = False
    created_at: datetime = datetime.now
    updated_at: datetime = datetime.now
    last_active_at: datetime | None = None
    metadata: Dict = dict


class BaseStorageTest(ABC):
    """Base test class for all storage adapters"""

    @abstractmethod
    async def get_storage(self):
        """Get a storage instance for testing. Should be implemented by subclasses."""
        pass

    @abstractmethod
    async def cleanup_storage(self, storage):
        """Clean up storage after tests. Should be implemented by subclasses."""
        pass

    @pytest.mark.asyncio
    async def test_schema_crud_operations(self):
        """Test basic CRUD operations with Schema"""
        storage = await self.get_storage()

        try:
            async with storage.session() as session:
                await session.init_schema(Account)

                # create
                created = await session.create(Account(uid="x", permissions=["read"]))
                assert created.uid == "x"
                assert created.id is not None

                # get
                got = await session.get(Account, filters={"uid": "x"})
                assert got and got.uid == "x"
                assert got.permissions == ["read"]

                # list
                lst = await session.list(Account, limit=10)
                assert len(lst) >= 1

                # update
                updated = await session.update(
                    Account, {"uid": "x"}, {"permissions": ["read", "update"]}
                )
                assert "update" in updated.permissions
                assert "read" in updated.permissions

                # delete
                ok = await session.delete(Account, {"uid": "x"})
                assert ok is True
                assert await session.get(Account, filters={"uid": "x"}) is None
        finally:
            await self.cleanup_storage(storage)

    @pytest.mark.asyncio
    async def test_list_with_filters_and_contains(self):
        """Test list operations with filters and contains"""
        storage = await self.get_storage()

        try:
            async with storage.session() as session:
                await session.init_schema(Account)

                await session.create(Account(uid="u1", permissions=["read"]))
                await session.create(Account(uid="u2", permissions=["read", "write"]))
                await session.create(Account(uid="u3", permissions=["delete"]))

                # filter by uid
                res = await session.list(Account, filters={"uid": "u2"})
                assert len(res) == 1 and res[0].uid == "u2"

                # contains on list field
                res = await session.list(Account, contains={"permissions": "write"})
                assert any(a.uid == "u2" for a in res)
                assert not any(a.uid == "u1" for a in res)
        finally:
            await self.cleanup_storage(storage)

    @pytest.mark.asyncio
    async def test_pagination_after_id(self):
        """Test pagination using after_id"""
        storage = await self.get_storage()

        try:
            async with storage.session() as session:
                await session.init_schema(Account)

                created = []
                for i in range(5):
                    created.append(
                        await session.create(Account(uid=f"p{i}", permissions=[]))
                    )

                # first page
                page1 = await session.list(Account, limit=2)
                assert len(page1) == 2
                # second page using after_id
                last_id = page1[-1].id
                page2 = await session.list(Account, limit=2, after_id=last_id)
                assert len(page2) == 2
                # third page
                last_id2 = page2[-1].id
                page3 = await session.list(Account, limit=2, after_id=last_id2)
                assert len(page3) >= 1
        finally:
            await self.cleanup_storage(storage)

    @pytest.mark.asyncio
    async def test_update_with_no_valid_fields_returns_none(self):
        """Test update with invalid fields returns None"""
        storage = await self.get_storage()

        try:
            async with storage.session() as session:
                await session.init_schema(Account)
                await session.create(Account(uid="z", permissions=["read"]))

                result = await session.update(
                    Account, {"uid": "z"}, {"not_a_field": True}
                )
                assert result is None
        finally:
            await self.cleanup_storage(storage)

    @pytest.mark.asyncio
    async def test_get_without_filters_raises(self):
        """Test get without filters raises ValueError"""
        storage = await self.get_storage()

        try:
            async with storage.session() as session:
                await session.init_schema(Account)
                with pytest.raises(ValueError):
                    await session.get(Account)
        finally:
            await self.cleanup_storage(storage)

    @pytest.mark.asyncio
    async def test_metadata_operations(self):
        """Test metadata field operations"""
        storage = await self.get_storage()

        try:
            async with storage.session() as session:
                await session.init_schema(Account)

                # Create account with metadata
                metadata = {
                    "name": "Test User",
                    "email": "test@example.com",
                    "role": "admin",
                }
                account = Account(
                    uid="meta_test", permissions=["read"], metadata=metadata
                )
                created = await session.create(account)
                assert created.metadata == metadata

                # Get account and verify metadata
                got = await session.get(Account, filters={"uid": "meta_test"})
                assert got.metadata == metadata
                assert got.metadata["name"] == "Test User"
                assert got.metadata["email"] == "test@example.com"

                # Update metadata
                new_metadata = {
                    "name": "Updated User",
                    "email": "updated@example.com",
                    "role": "user",
                }
                updated = await session.update(
                    Account, {"uid": "meta_test"}, {"metadata": new_metadata}
                )
                assert updated.metadata == new_metadata
        finally:
            await self.cleanup_storage(storage)

    @pytest.mark.asyncio
    async def test_permissions_operations(self):
        """Test permissions field operations"""
        storage = await self.get_storage()

        try:
            async with storage.session() as session:
                await session.init_schema(Account)

                # Create account with permissions
                permissions = ["read", "write", "delete"]
                account = Account(uid="perm_test", permissions=permissions)
                created = await session.create(account)
                assert created.permissions == permissions

                # Get account and verify permissions
                got = await session.get(Account, filters={"uid": "perm_test"})
                assert got.permissions == permissions
                assert "read" in got.permissions
                assert "write" in got.permissions

                # Update permissions
                new_permissions = ["read", "admin"]
                updated = await session.update(
                    Account, {"uid": "perm_test"}, {"permissions": new_permissions}
                )
                assert updated.permissions == new_permissions
                assert "admin" in updated.permissions
                assert "write" not in updated.permissions
        finally:
            await self.cleanup_storage(storage)

    @pytest.mark.asyncio
    async def test_account_status_fields(self):
        """Test is_active and is_blocked fields"""
        storage = await self.get_storage()

        try:
            async with storage.session() as session:
                await session.init_schema(Account)

                # Create active account
                account = Account(
                    uid="status_test",
                    permissions=["read"],
                    is_active=True,
                    is_blocked=False,
                )
                created = await session.create(account)
                assert created.is_active is True
                assert created.is_blocked is False

                # Block account
                updated = await session.update(
                    Account, {"uid": "status_test"}, {"is_blocked": True}
                )
                assert updated.is_blocked is True
                assert updated.is_active is True  # Should remain active

                # Deactivate account
                updated = await session.update(
                    Account, {"uid": "status_test"}, {"is_active": False}
                )
                assert updated.is_active is False
                assert updated.is_blocked is True  # Should remain blocked
        finally:
            await self.cleanup_storage(storage)

    @pytest.mark.asyncio
    async def test_timestamp_fields(self):
        """Test created_at, updated_at, and last_active_at fields"""
        storage = await self.get_storage()

        try:
            async with storage.session() as session:
                await session.init_schema(Account)

                # Create account
                account = Account(uid="timestamp_test", permissions=["read"])
                created = await session.create(account)

                assert created.created_at is not None
                assert created.updated_at is not None
                assert created.last_active_at is None  # Should be None initially

                # Update last_active_at
                from datetime import datetime

                now = datetime.now()
                updated = await session.update(
                    Account, {"uid": "timestamp_test"}, {"last_active_at": now}
                )
                assert updated.last_active_at is not None
                assert updated.last_active_at == now
        finally:
            await self.cleanup_storage(storage)

    @pytest.mark.asyncio
    async def test_password_field(self):
        """Test password field handling"""
        storage = await self.get_storage()

        try:
            async with storage.session() as session:
                await session.init_schema(Account)

                # Create account with password
                password = "hashed_password_123"
                account = Account(
                    uid="password_test", permissions=["read"], password=password
                )
                created = await session.create(account)
                assert created.password == password

                # Get account and verify password
                got = await session.get(Account, filters={"uid": "password_test"})
                assert got.password == password

                # Update password
                new_password = "new_hashed_password_456"
                updated = await session.update(
                    Account, {"uid": "password_test"}, {"password": new_password}
                )
                assert updated.password == new_password
        finally:
            await self.cleanup_storage(storage)

    @pytest.mark.asyncio
    async def test_multiple_accounts_operations(self):
        """Test operations with multiple accounts"""
        storage = await self.get_storage()

        try:
            async with storage.session() as session:
                await session.init_schema(Account)

                # Create multiple accounts
                accounts_data = [
                    ("user1", ["read"], {"name": "User One"}),
                    ("user2", ["read", "write"], {"name": "User Two"}),
                    ("user3", ["admin"], {"name": "User Three"}),
                    ("user4", ["read"], {"name": "User Four"}),
                ]

                created_accounts = []
                for uid, permissions, metadata in accounts_data:
                    account = Account(
                        uid=uid, permissions=permissions, metadata=metadata
                    )
                    created = await session.create(account)
                    created_accounts.append(created)

                # List all accounts
                all_accounts = await session.list(Account)
                assert len(all_accounts) == 4

                # Filter by permissions
                admin_accounts = await session.list(
                    Account, contains={"permissions": "admin"}
                )
                assert len(admin_accounts) == 1
                assert admin_accounts[0].uid == "user3"

                # Filter by metadata
                accounts_with_write = await session.list(
                    Account, contains={"permissions": "write"}
                )
                assert len(accounts_with_write) == 1
                assert accounts_with_write[0].uid == "user2"

                # Delete multiple accounts
                for account in created_accounts[:2]:  # Delete first two
                    await session.delete(Account, {"uid": account.uid})

                remaining_accounts = await session.list(Account)
                assert len(remaining_accounts) == 2
        finally:
            await self.cleanup_storage(storage)

    @pytest.mark.asyncio
    async def test_model_crud_operations(self):
        """Test basic CRUD operations with Model"""
        storage = await self.get_storage()

        try:
            async with storage.session() as session:
                await session.init_schema(AccountModel)

                # create
                created = await session.create(
                    AccountModel(uid="y", permissions=["write"])
                )
                assert created.uid == "y"
                assert created.id is not None

                # get
                got = await session.get(AccountModel, filters={"uid": "y"})
                assert got and got.uid == "y"
                assert got.permissions == ["write"]

                # list
                lst = await session.list(AccountModel, limit=10)
                assert len(lst) >= 1

                # update
                updated = await session.update(
                    AccountModel, {"uid": "y"}, {"permissions": ["write", "delete"]}
                )
                assert (
                    updated
                    and "write" in updated.permissions
                    and "delete" in updated.permissions
                )

                # delete
                deleted = await session.delete(AccountModel, {"uid": "y"})
                assert deleted

                # verify deletion
                got_after_delete = await session.get(AccountModel, filters={"uid": "y"})
                assert got_after_delete is None

        finally:
            await self.cleanup_storage(storage)

    @pytest.mark.asyncio
    async def test_schema_to_model_conversion(self):
        """Test Schema to Model conversion and CRUD operations"""
        storage = await self.get_storage()

        try:
            async with storage.session() as session:
                # Convert Schema to Model
                AccountModelFromSchema = Account.to_model()
                await session.init_schema(AccountModelFromSchema)
                # create
                created = await session.create(
                    AccountModelFromSchema(uid="z", permissions=["admin"])
                )
                assert created.uid == "z"
                assert created.id is not None

                # get
                got = await session.get(AccountModelFromSchema, filters={"uid": "z"})
                assert got and got.uid == "z"
                assert got.permissions == ["admin"]

                # list
                lst = await session.list(AccountModelFromSchema, limit=10)
                assert len(lst) >= 1

                # update
                updated = await session.update(
                    AccountModelFromSchema,
                    {"uid": "z"},
                    {"permissions": ["admin", "super"]},
                )
                assert (
                    updated
                    and "admin" in updated.permissions
                    and "super" in updated.permissions
                )

                # delete
                deleted = await session.delete(AccountModelFromSchema, {"uid": "z"})
                assert deleted

                # verify deletion
                got_after_delete = await session.get(
                    AccountModelFromSchema, filters={"uid": "z"}
                )
                assert got_after_delete is None

        finally:
            await self.cleanup_storage(storage)
