"""Initial Klen ERP migration and runtime schema baseline."""

from alembic import op

from klen_clone.db import Base
from klen_clone import models  # noqa: F401 - registers metadata

revision = "20260908_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    raise RuntimeError("Baseline downgrade is intentionally disabled because it would destroy ERP evidence")
