"""Add bill reminders, bank consent connections and transaction deduplication."""
from alembic import op
import sqlalchemy as sa

revision = "0003_bills_banking"
down_revision = "0002_profile_preferences"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("transactions", sa.Column("external_ref", sa.String(180), nullable=True))
    with op.batch_alter_table("transactions") as batch:
        batch.create_unique_constraint("uq_transactions_external_ref", ["external_ref"])
    op.create_table("bills",
        sa.Column("id",sa.String(36),primary_key=True), sa.Column("user_id",sa.String(36),sa.ForeignKey("users.id",ondelete="CASCADE"),nullable=False),
        sa.Column("name",sa.String(120),nullable=False),sa.Column("amount",sa.Numeric(14,2),nullable=False),sa.Column("category",sa.String(80),nullable=False),
        sa.Column("due_date",sa.Date(),nullable=False),sa.Column("recurrence",sa.String(12),nullable=False),sa.Column("reminder_days",sa.Integer(),nullable=False),
        sa.Column("active",sa.Boolean(),nullable=False),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False))
    op.create_index("ix_bills_user_id","bills",["user_id"])
    op.create_table("notifications",
        sa.Column("id",sa.String(36),primary_key=True),sa.Column("user_id",sa.String(36),sa.ForeignKey("users.id",ondelete="CASCADE"),nullable=False),
        sa.Column("bill_id",sa.String(36),sa.ForeignKey("bills.id",ondelete="CASCADE")),sa.Column("title",sa.String(160),nullable=False),sa.Column("message",sa.String(400),nullable=False),
        sa.Column("due_date",sa.Date()),sa.Column("read_at",sa.DateTime(timezone=True)),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),
        sa.UniqueConstraint("user_id","bill_id","due_date",name="uq_notification_bill_due"))
    op.create_index("ix_notifications_user_id","notifications",["user_id"])
    op.create_table("bank_connections",
        sa.Column("id",sa.String(36),primary_key=True),sa.Column("user_id",sa.String(36),sa.ForeignKey("users.id",ondelete="CASCADE"),nullable=False),
        sa.Column("provider",sa.String(40),nullable=False),sa.Column("consent_id",sa.String(100),nullable=False,unique=True),sa.Column("consent_url",sa.String(500),nullable=False),
        sa.Column("consent_status",sa.String(30),nullable=False),sa.Column("data_session_id",sa.String(100)),sa.Column("masked_accounts_json",sa.Text(),nullable=False),
        sa.Column("last_synced_at",sa.DateTime(timezone=True)),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False))
    op.create_index("ix_bank_connections_user_id","bank_connections",["user_id"])

def downgrade():
    op.drop_table("bank_connections"); op.drop_table("notifications"); op.drop_table("bills")
    with op.batch_alter_table("transactions") as batch:
        batch.drop_constraint("uq_transactions_external_ref",type_="unique")
        batch.drop_column("external_ref")
