# Database Migrations with Alembic

## Quick Start

```bash
# Create a new migration (auto-generated from model changes)
python migrate.py create "add users table"

# Apply all pending migrations
python migrate.py up

# Rollback last migration
python migrate.py down

# Check current migration version
python migrate.py current

# View migration history
python migrate.py history
```

## Workflow

1. **Modify your SQLAlchemy models** in `database/` or create new model files
2. **Import new models** in `database/connection.py` or `database/__init__.py` so Alembic can see them
3. **Generate migration**: `python migrate.py create "description of change"`
4. **Review the generated file** in `alembic~/versions/` (optional but recommended)
5. **Apply migration**: `python migrate.py up`
6. **Commit both your model changes and the migration file to git**

## Example: Adding a New Table

```python
# In database/models.py (create this file)
from database.connection import Base
from sqlalchemy import Column, Integer, String, DateTime
from datetime import datetime

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
```

```python
# In database/__init__.py (make sure models are imported)
from database.connection import Base
from database.models import User  # Import so Alembic detects it
```

```bash
# Generate migration
python migrate.py create "add users table"

# Apply
python migrate.py up
```

## Production Deployment

Migrations run automatically during deployment. The deploy script will:
1. Build and push new image with updated code
2. Apply pending migrations before starting the app
3. Start/restart services

## Manual Migration on Server

```bash
ssh root@your-server
cd /opt/nx-backend
docker exec nx-backend-backend-1 python migrate.py up
```

## Advanced Alembic Commands

If you need more control, use `alembic` directly:

```bash
# Create empty migration (manual SQL)
alembic revision -m "description"

# Upgrade to specific version
alembic upgrade <revision>

# Downgrade to specific version
alembic downgrade <revision>

# Show SQL without applying
alembic upgrade head --sql

# Stamp database at specific version (dangerous!)
alembic stamp head
```

## Troubleshooting

**"Target database is not up to date"**
- Run `python migrate.py up` to apply pending migrations

**"Can't locate revision"**
- Make sure all migration files are committed to git
- Check that `alembic~/versions/` contains all migration files

**"No module named 'database'"**
- Make sure you're running from the project root
- Check that `database/__init__.py` exists
