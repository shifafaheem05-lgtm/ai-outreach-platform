"""token_version on users, performance indexes

Revision ID: 0002
Revises: 0001
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("token_version", sa.Integer(), nullable=False, server_default="0"))
    op.create_index("ix_leads_org_status", "leads", ["org_id", "status"])
    op.create_index("ix_leads_org_score", "leads", ["org_id", "score"])
    op.create_index("ix_campaign_leads_due", "campaign_leads", ["state", "next_send_at"])
    op.create_index("ix_messages_org_dir_sent", "messages", ["org_id", "direction", "sent_at"])


def downgrade() -> None:
    op.drop_index("ix_messages_org_dir_sent", table_name="messages")
    op.drop_index("ix_campaign_leads_due", table_name="campaign_leads")
    op.drop_index("ix_leads_org_score", table_name="leads")
    op.drop_index("ix_leads_org_status", table_name="leads")
    op.drop_column("users", "token_version")
