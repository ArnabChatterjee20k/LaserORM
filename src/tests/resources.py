from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict
from laserorm.model import Model


# example model
@dataclass
class Account(Model):

    uid: str = field(metadata={"index": True, "unique": True})
    permissions: list[str] = field(default_factory=list)
    password: str | None = None

    is_active: bool = True
    is_blocked: bool = False

    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    last_active_at: datetime | None = None

    metadata: Dict = field(default_factory=dict)
