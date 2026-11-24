"""Retire the superseded message-only Glass credential, preserving its audit history."""

from alembic import op

revision = "0067_retire_glass_message_keys"
down_revision = "0066_glass_live_ticket"
branch_labels = depends_on = None


def upgrade():
    op.execute("""UPDATE bot_credentials SET revoked_at = CURRENT_TIMESTAMP
                  WHERE revoked_at IS NULL AND scopes = '["glassface:message"]'::jsonb""")


def downgrade():
    # Revoked secrets must stay revoked after a software rollback.
    pass
