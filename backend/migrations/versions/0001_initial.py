"""Initial FinTwin tables."""
from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(120), nullable=False),
        sa.Column("city", sa.String(100), nullable=False),
        sa.Column("monthly_salary", sa.Numeric(14,2), nullable=False),
        sa.Column("photo_path", sa.String(255)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_table("transactions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("merchant", sa.String(160), nullable=False), sa.Column("category", sa.String(80), nullable=False),
        sa.Column("kind", sa.String(12), nullable=False), sa.Column("amount", sa.Numeric(14,2), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False), sa.Column("note", sa.String(300)),
    )
    op.create_index("ix_transactions_user_id", "transactions", ["user_id"])
    op.create_index("ix_transactions_category", "transactions", ["category"])
    op.create_index("ix_transactions_occurred_at", "transactions", ["occurred_at"])
    op.create_table("goals",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False), sa.Column("target_amount", sa.Numeric(14,2), nullable=False),
        sa.Column("current_amount", sa.Numeric(14,2), nullable=False), sa.Column("target_date", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_goals_user_id", "goals", ["user_id"])
    op.create_table("datasets",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False), sa.Column("stored_path", sa.String(500), nullable=False),
        sa.Column("checksum", sa.String(64), nullable=False), sa.Column("rows", sa.Integer(), nullable=False),
        sa.Column("columns_json", sa.Text(), nullable=False), sa.Column("validation_json", sa.Text(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_datasets_user_id", "datasets", ["user_id"])
    op.create_table("training_runs",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("dataset_id", sa.String(36), sa.ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target", sa.String(120), nullable=False), sa.Column("status", sa.String(24), nullable=False),
        sa.Column("metrics_json", sa.Text(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_training_runs_user_id", "training_runs", ["user_id"])
    op.create_table("model_versions",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("training_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False), sa.Column("task", sa.String(30), nullable=False), sa.Column("artifact_path", sa.String(500), nullable=False),
        sa.Column("schema_json", sa.Text(), nullable=False), sa.Column("metrics_json", sa.Text(), nullable=False),
        sa.Column("approved", sa.Boolean(), nullable=False), sa.Column("active", sa.Boolean(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_model_versions_user_id", "model_versions", ["user_id"])
    op.create_index("ix_model_versions_run_id", "model_versions", ["run_id"])

def downgrade():
    for name in ("model_versions", "training_runs", "datasets", "goals", "transactions", "users"):
        op.drop_table(name)
