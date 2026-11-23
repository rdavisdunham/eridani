"""One short-lived hands-free voice admission per dedicated Glass credential."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0066_glass_live_ticket"
down_revision = "0065_today_pins"
branch_labels = depends_on = None


def upgrade():
    op.add_column("bot_credentials", sa.Column("glass_live_ticket", JSONB(), nullable=True))


def downgrade():
    op.drop_column("bot_credentials", "glass_live_ticket")
