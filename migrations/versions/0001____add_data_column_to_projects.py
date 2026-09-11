"""add_data_column_to_projects

Revision ID: a1b2c3d4e5f6
Revises: <ضع revision السابق هنا>
Create Date: 2026-09-11 14:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = "0001"
down_revision = None   # ← ضع revision السابق الفعلي
branch_labels = None
depends_on = None


# ─────────────────────────────────────────────────────────────────────────────
# Helpers — idempotent column checks
# ─────────────────────────────────────────────────────────────────────────────

def _column_exists(table_name: str, column_name: str) -> bool:
    """Return True if column_name exists in table_name."""
    bind = op.get_bind()
    inspector = inspect(bind)

    if table_name not in inspector.get_table_names():
        return False

    columns = [c["name"] for c in inspector.get_columns(table_name)]
    return column_name in columns


def _index_exists(table_name: str, index_name: str) -> bool:
    """Return True if index_name exists on table_name."""
    bind = op.get_bind()
    inspector = inspect(bind)
    if table_name not in inspector.get_table_names():
        return False
    indexes = [i["name"] for i in inspector.get_indexes(table_name)]
    return index_name in indexes


def _table_exists(table_name: str) -> bool:
    """Return True if table_name exists."""
    bind = op.get_bind()
    inspector = inspect(bind)
    return table_name in inspector.get_table_names()


# ─────────────────────────────────────────────────────────────────────────────
# Upgrade
# ─────────────────────────────────────────────────────────────────────────────

def upgrade():
    """
    Add the `data` JSON column to the `projects` table.

    The column stores the render output blob:
      {
        "video_url": "...",
        "video_path": "...",
        "thumbnail": "...",
        "thumbnail_path": "...",
        "clips": [...],
        "layers": [...],
        "total_duration": 12.5,
        "media_files": [...],
        "rendered_at": "2026-09-11T14:06:13.178Z",
        "output_local_path": "/app/temp/.../render_xxx.mp4"
      }
    """

    # تأكد من وجود الجدول
    if not _table_exists("projects"):
        print("⚠️  Table 'projects' does not exist — skipping migration.")
        return

    # ── إضافة العمود إن لم يكن موجوداً ───────────────────────────────────────
    if not _column_exists("projects", "data"):
        print("✅ Adding column 'projects.data' ...")
        op.add_column(
            "projects",
            sa.Column(
                "data",
                sa.JSON(),
                nullable=True,
                server_default=sa.text("'{}'"),
            ),
        )
    else:
        print("ℹ️  Column 'projects.data' already exists — skipping ADD COLUMN.")

    # ── تعيين قيم افتراضية للصفوف الفارغة ────────────────────────────────────
    # استخدم bind للتعامل مع أنواع DB مختلفة
    bind = op.get_bind()
    dialect = bind.dialect.name

    try:
        if dialect == "postgresql":
            bind.execute(sa.text(
                "UPDATE projects SET data = '{}'::jsonb WHERE data IS NULL"
            ))
        elif dialect in ("mysql", "mariadb"):
            bind.execute(sa.text(
                "UPDATE projects SET data = JSON_OBJECT() WHERE data IS NULL"
            ))
        else:
            # sqlite + others: JSON as text
            bind.execute(sa.text(
                "UPDATE projects SET data = '{}' WHERE data IS NULL"
            ))
        print("✅ Populated NULL data with '{}'.")
    except Exception as e:
        print(f"⚠️  Could not normalize data values: {e}")

    # ── فهرس (اختياري) على status ────────────────────────────────────────────
    if not _index_exists("projects", "ix_projects_status"):
        try:
            op.create_index("ix_projects_status", "projects", ["status"])
            print("✅ Created index ix_projects_status.")
        except Exception as e:
            print(f"⚠️  Could not create index ix_projects_status: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Downgrade
# ─────────────────────────────────────────────────────────────────────────────

def downgrade():
    """Remove the `data` column and its index (if present)."""

    if not _table_exists("projects"):
        print("⚠️  Table 'projects' does not exist — nothing to downgrade.")
        return

    # احذف الفهرس أولاً
    if _index_exists("projects", "ix_projects_status"):
        try:
            op.drop_index("ix_projects_status", table_name="projects")
            print("✅ Dropped index ix_projects_status.")
        except Exception as e:
            print(f"⚠️  Could not drop index: {e}")

    # احذف العمود
    if _column_exists("projects", "data"):
        try:
            op.drop_column("projects", "data")
            print("✅ Dropped column 'projects.data'.")
        except Exception as e:
            print(f"⚠️  Could not drop column 'projects.data': {e}")
    else:
        print("ℹ️  Column 'projects.data' does not exist — skipping.")
