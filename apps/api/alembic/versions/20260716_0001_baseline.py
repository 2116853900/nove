"""baseline schema from SQLAlchemy metadata

Revision ID: 20260716_0001
Revises:
Create Date: 2026-07-16

Creates the full application schema for fresh deployments.
Existing local DBs can continue using app.migrate.ensure_schema;
production should prefer: alembic upgrade head
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

from app.db import Base
from app import models  # noqa: F401

revision: str = "20260716_0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
