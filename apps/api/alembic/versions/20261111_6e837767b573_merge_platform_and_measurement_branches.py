"""merge platform and measurement branches

Revision ID: 6e837767b573
Revises: d5085df1f375, b5e7f0a2d4c6
Create Date: 2026-11-11 15:34:39.045802

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6e837767b573'
down_revision: Union[str, Sequence[str], None] = ('d5085df1f375', 'b5e7f0a2d4c6')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
