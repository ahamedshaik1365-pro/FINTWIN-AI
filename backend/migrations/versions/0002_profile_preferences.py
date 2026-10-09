"""Persist dashboard personalisation fields on user accounts."""
from alembic import op
import sqlalchemy as sa

revision = "0002_profile_preferences"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("users", sa.Column("essential_expenses", sa.Numeric(14, 2), nullable=False, server_default="0"))
    op.add_column("users", sa.Column("employment_status", sa.String(30), nullable=False, server_default="Employed"))
    op.add_column("users", sa.Column("experience", sa.String(30), nullable=False, server_default="1–2 years"))
    op.add_column("users", sa.Column("currency", sa.String(16), nullable=False, server_default="INR"))

def downgrade():
    op.drop_column("users", "currency")
    op.drop_column("users", "experience")
    op.drop_column("users", "employment_status")
    op.drop_column("users", "essential_expenses")
