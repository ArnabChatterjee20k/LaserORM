# LaserORM

> **The simplest async ORM you'll ever use** - One model, infinite possibilities.

LaserORM is a minimalistic, async-first ORM that embraces the philosophy of **"one model, many databases"**. Instead of complex migrations, multiple model files, and database-specific code, LaserORM lets you define a single model and use it across different database backends seamlessly.

## 🎯 Core Philosophy

**One Model, Many Databases** - Define your data structure once, use it everywhere.

LaserORM believes that your data model shouldn't be tied to a specific database. Whether you're prototyping with SQLite, scaling with PostgreSQL, or switching between databases, your model remains the same.

## ✨ What Makes LaserORM Special

### 1. **Single Model Definition**
```python
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict
from laserorm.model import Model

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
```

That's it. No migrations, no separate schema files, no database-specific code.

### 2. **Universal Database Support**
```python
# SQLite for development
from laserorm.storage.sqlite import SQLite
storage = SQLite("dev.db")

# PostgreSQL for production  
from laserorm.storage.postgresql import PostgreSQL
storage = PostgreSQL("postgresql://user:pass@localhost/db")

# Same model, same code, different databases
```

### 3. **Zero Configuration**
- **Auto-schema generation** from your model
- **Automatic type mapping** (Python types → SQL types)
- **Built-in indexing** from field metadata
- **JSON support** for complex data types
- **Auto-incrementing primary keys**

### 4. **Async-First Design**
```python
async with storage.session() as session:
    # Create
    account = await session.create(Account(uid="user123", permissions=["read", "write"]))
    
    # Read
    user = await session.get(Account, filters={"uid": "user123"})
    
    # Update
    updated = await session.update(Account, {"uid": "user123"}, {"is_active": False})
    
    # Delete
    await session.delete(Account, {"uid": "user123"})
```

## 🚀 Quick Start

### Installation

#### Option 1: Install from GitHub (pip)
```bash
# Basic installation (install from master/main branch)
pip install git+https://github.com/ArnabChatterjee20k/LaserORM.git

# For SQLite support
pip install "git+https://github.com/ArnabChatterjee20k/LaserORM.git#egg=laserorm[sqlite]"

# For PostgreSQL support
pip install "git+https://github.com/ArnabChatterjee20k/LaserORM.git#egg=laserorm[postgres]"

# For both SQLite and PostgreSQL
pip install "git+https://github.com/ArnabChatterjee20k/LaserORM.git#egg=laserorm[sqlite,postgres]"

# Install from a specific branch
pip install git+https://github.com/ArnabChatterjee20k/LaserORM.git@branch-name

# Install from a specific tag/version
pip install git+https://github.com/ArnabChatterjee20k/LaserORM.git@v0.1.0
```

#### Option 2: Install using uv (recommended)
```bash
# For SQLite support
uv add laserorm[sqlite]

# For PostgreSQL support  
uv add laserorm[postgres]

# For development
uv add --group dev laserorm[sqlite,postgres]
```

> **Note:** Replace `ArnabChatterjee20k` with your actual GitHub username/organization in the pip install commands above.

### Basic Usage

1. **Define your model:**
```python
from dataclasses import dataclass, field
from datetime import datetime
from laserorm.model import Model

@dataclass
class User(Model):
    email: str = field(metadata={"unique": True})
    name: str
    age: int
    is_active: bool = True
    created_at: datetime = field(default_factory=datetime.now)
```

2. **Choose your database:**
```python
from laserorm.storage.sqlite import SQLite

storage = SQLite("myapp.db")
```

3. **Use it:**
```python
async with storage.session() as session:
    # Initialize schema (creates tables automatically)
    await session.init_schema(User)
    
    # Create a user
    user = await session.create(User(
        email="john@example.com",
        name="John Doe", 
        age=30
    ))
    
    # Find users
    users = await session.list(User, limit=10)
    john = await session.get(User, filters={"email": "john@example.com"})
    
    # Update
    await session.update(User, {"email": "john@example.com"}, {"age": 31})
    
    # Delete
    await session.delete(User, {"email": "john@example.com"})
```

## 🔧 Advanced Features

### Expressions (powerful, pythonic filters)

LaserORM provides a lightweight expression system that lets you build safe, composable WHERE clauses using normal Python operators.

- Equality/relational: `==`, `!=`, `<`, `<=`, `>`, `>=`
- Logical: `&` (AND), `|` (OR)
- Membership:
  - IN: `Model.field[[v1, v2, ...]]`
  - NOT IN: `Model.field[{"not": [v1, v2, ...]}]`
  - NOT IN : `~(Model.field[[v1, v2, ...]])`

Examples:
```python
from src.laserorm.storage.sqlite import SQLite
from src.laserorm.core.model import Model

class Account(Model):
    uid: str
    is_active: bool
    score: int

storage = SQLite("expr_demo.db")

async with storage.session() as session:
    await session.init_schema(Account)
    await session.create(Account(uid="u1", is_active=True, score=10))
    await session.create(Account(uid="u2", is_active=False, score=5))

    # Equality
    one = await session.get(Account, filters=(Account.uid == "u1"))

    # AND / OR with nesting
    expr = (Account.is_active == True) & ((Account.score > 7) | (Account.score == 5))
    many = await session.list(Account, filters=expr)

    # IN
    in_expr = Account.uid[["u1", "u3"]]
    in_rows = await session.list(Account, filters=in_expr)

    # NOT IN
    not_in_expr = Account.uid[{"not": ["u2"]}]
    rest = await session.list(Account, filters=not_in_expr)
```

Type safety via `type_hint` is propagated from field definitions to expressions, and validated when compiling to SQL. Callables used as values (e.g., `lambda: 5`) are evaluated automatically.

### Complex Queries
```python
# Filter by multiple fields
users = await session.list(User, filters={"is_active": True, "age": 25})

# Search within JSON fields
users = await session.list(User, contains={"metadata": {"role": "admin"}})

# Pagination
page1 = await session.list(User, limit=10)
page2 = await session.list(User, limit=10, after_id=page1[-1].id)
```

### Transactions
```python
async with storage.begin() as session:
    user1 = await session.create(User(email="user1@example.com", name="User 1"))
    user2 = await session.create(User(email="user2@example.com", name="User 2"))
    # Both users are created atomically
```

### Schema: declarative data classes

`Schema` is a dataclass-first API with built-in metadata, great for portability and explicit defaults. Convert any `Schema` to a runtime `Model` with `to_model()` to leverage expressions.

```python
from src.laserorm.core.schema import Schema, create_field, FieldMetadataOptions
from src.laserorm.storage.sqlite import SQLite

class User(Schema):
    uid: str = create_field(FieldMetadataOptions(index=True))
    name: str = create_field(FieldMetadataOptions())
    age: int = create_field(FieldMetadataOptions())

UserModel = User.to_model()  # converts Schema → Model with columns/expressions

storage = SQLite("schema_demo.db")
async with storage.session() as session:
    await session.init_schema(User)
    await session.create(User(uid="u1", name="Alice", age=20))

    # Use expression filters via the generated Model
    got = await session.get(UserModel, filters=(UserModel.uid == "u1"))
    older = await session.list(UserModel, filters=(UserModel.age >= 18))
```

Key points:
- `Schema` controls on-disk shape (defaults, JSON typing, indexes)
- `to_model()` generates a dynamic `Model` with expression-ready fields

### Model: minimal runtime model with expressions

`Model` is the runtime-friendly variant that’s expression-enabled out of the box. Just annotate fields to generate columns.

```python
from src.laserorm.core.model import Model
from src.laserorm.storage.sqlite import SQLite

class Account(Model):
    uid: str
    permissions: list[str]
    is_active: bool = True

storage = SQLite("model_demo.db")
async with storage.session() as session:
    await session.init_schema(Account)
    await session.create(Account(uid="a1", permissions=["read"]))
    await session.create(Account(uid="a2", permissions=["read", "write"]))

    # Expressions
    one = await session.get(Account, filters=(Account.uid == "a2"))
    some = await session.list(Account, filters=(Account.uid[["a1", "a3"]]))
    not_a2 = await session.list(Account, filters=(Account.uid[{"not": ["a2"]}]))
```

### JSON Support
```python
@dataclass
class Product(Model):
    name: str
    price: float
    tags: list[str] = field(default_factory=list)  # Stored as JSON
    metadata: dict = field(default_factory=dict)   # Stored as JSON

# Query JSON fields
products = await session.list(Product, contains={"tags": "electronics"})
```

## 🎨 The LaserORM Way

### Traditional ORM Approach:
```
models/
├── user.py          # User model
├── product.py       # Product model  
├── order.py         # Order model
migrations/
├── 001_create_users.py
├── 002_create_products.py
├── 003_create_orders.py
└── 004_add_indexes.py
```

### LaserORM Approach:
```
models/
└── models.py        # All models in one file
```

**That's it.** No migrations, no complex setup, no database-specific code.

## 🏗️ Architecture

LaserORM is built on three core principles:

1. **Model-First**: Your Python dataclass is the single source of truth
2. **Database-Agnostic**: Same model works with any supported database
3. **Async-Native**: Built for modern Python async applications

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   Your Model    │───▶│   LaserORM       │───▶│   Any Database  │
│   (Dataclass)   │    │   (Adapter)      │    │   (SQLite/PG)   │
└─────────────────┘    └──────────────────┘    └─────────────────┘
```

## 🎯 Perfect For

- **Rapid Prototyping**: Get up and running in minutes
- **Microservices**: Lightweight and fast
- **Multi-Database Apps**: Switch databases without changing code
- **Async Applications**: Built for modern Python
- **Learning**: Simple enough to understand the entire codebase

## 🔮 Why "Laser"?

Just like a laser focuses light into a powerful, precise beam, LaserORM focuses on the essentials - **one model, many possibilities**. No bloat, no complexity, just pure focus on what matters: your data.

## 📚 Examples

Check out the `src/tests/` directory for comprehensive examples of:
- CRUD operations
- Complex queries with filters and contains
- Expression filters (AND/OR, IN/NOT IN, comparisons)
- JSON field handling
- Transaction management
- Multi-database usage

## 🤝 Contributing

LaserORM is designed to be simple and understandable. The entire codebase is small enough to read in an afternoon. Contributions are welcome!

## 📄 License

MIT License - Use it, modify it, build amazing things with it.

---

**LaserORM** - *One model, infinite possibilities.*
