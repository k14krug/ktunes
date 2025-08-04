"""Merge migration heads

Revision ID: cef21eeab88a
Revises: 83cb9f2e8977, duplicate_detection_indexes, f584c9b90032
Create Date: 2025-08-01 16:21:03.584606

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'cef21eeab88a'
down_revision = ('83cb9f2e8977', 'duplicate_detection_indexes', 'f584c9b90032')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
