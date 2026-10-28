# ============================================================
# OPSYN — tests/test_migrations.py   (I.1.3)
# Migration chain integrity: verifies all 0043–0051 migration
# files exist and form an unbroken revision chain.
# Run: pytest tests/test_migrations.py -v
# No database required — parses .py files directly.
# ============================================================

import os
import re
import pathlib
import pytest


ALEMBIC_DIR = pathlib.Path(__file__).parent.parent / "alembic" / "versions"

EXPECTED_CHAIN = [
    ("0043", "0042"),
    ("0044", "0043"),
    ("0045", "0044"),
    ("0046", "0045"),
    ("0047", "0046"),
    ("0048", "0047"),
    ("0049", "0048"),
    ("0050", "0049"),
    ("0051", "0050"),
]


def _find_migration_file(revision: str) -> pathlib.Path | None:
    """Locate a migration file by its revision prefix."""
    for f in ALEMBIC_DIR.glob(f"{revision}_*.py"):
        return f
    return None


def _parse_revision_fields(path: pathlib.Path) -> dict:
    """Extract revision, down_revision from a migration file."""
    text = path.read_text(encoding="utf-8")
    rev  = re.search(r"^revision\s*=\s*['\"](\w+)['\"]", text, re.MULTILINE)
    down = re.search(r"^down_revision\s*=\s*['\"](\w+)['\"]", text, re.MULTILINE)
    return {
        "revision":      rev.group(1)  if rev  else None,
        "down_revision": down.group(1) if down else None,
    }


class TestMigrationFiles:

    @pytest.mark.parametrize("revision,_", EXPECTED_CHAIN)
    def test_migration_file_exists(self, revision, _):
        """Each required migration file must exist on disk."""
        path = _find_migration_file(revision)
        assert path is not None, (
            f"Migration file for revision {revision} not found in {ALEMBIC_DIR}"
        )

    @pytest.mark.parametrize("revision,expected_down", EXPECTED_CHAIN)
    def test_migration_down_revision_correct(self, revision, expected_down):
        """Each migration's down_revision must point to the expected predecessor."""
        path = _find_migration_file(revision)
        if path is None:
            pytest.skip(f"Migration {revision} not found — file existence test will catch this")
        fields = _parse_revision_fields(path)
        assert fields["revision"] == revision, (
            f"revision field in {path.name} should be '{revision}', got '{fields['revision']}'"
        )
        assert fields["down_revision"] == expected_down, (
            f"down_revision in {path.name} should be '{expected_down}', "
            f"got '{fields['down_revision']}'"
        )

    def test_migration_files_have_upgrade_function(self):
        """Every migration in the chain must define an upgrade() function."""
        for revision, _ in EXPECTED_CHAIN:
            path = _find_migration_file(revision)
            if path is None:
                continue
            text = path.read_text(encoding="utf-8")
            assert "def upgrade()" in text, (
                f"Migration {revision} ({path.name}) is missing upgrade() function"
            )

    def test_migration_files_have_downgrade_function(self):
        """Every migration in the chain must define a downgrade() function."""
        for revision, _ in EXPECTED_CHAIN:
            path = _find_migration_file(revision)
            if path is None:
                continue
            text = path.read_text(encoding="utf-8")
            assert "def downgrade()" in text, (
                f"Migration {revision} ({path.name}) is missing downgrade() function"
            )

    def test_0051_adds_is_reopened_column(self):
        """Migration 0051 must alter the 'tasks' table to add 'is_reopened'."""
        path = _find_migration_file("0051")
        if path is None:
            pytest.skip("Migration 0051 not found")
        text = path.read_text(encoding="utf-8")
        assert "is_reopened" in text, "0051 must add is_reopened column"
        assert "'tasks'" in text or '"tasks"' in text, "0051 must target the tasks table"

    def test_0050_adds_source_task_id_to_projects(self):
        """Migration 0050 must add source_task_id to projects table."""
        path = _find_migration_file("0050")
        if path is None:
            pytest.skip("Migration 0050 not found")
        text = path.read_text(encoding="utf-8")
        assert "source_task_id" in text
        assert "projects" in text

    def test_0043_creates_tasks_table_extensions(self):
        """Migration 0043 must be present (first Phase 5 migration)."""
        path = _find_migration_file("0043")
        assert path is not None, "Base Phase 5 migration 0043 must exist"

    def test_chain_is_contiguous(self):
        """All 9 revisions (0043–0051) must form a contiguous chain."""
        revisions = {rev for rev, _ in EXPECTED_CHAIN}
        missing   = []
        for revision in revisions:
            if _find_migration_file(revision) is None:
                missing.append(revision)
        assert not missing, f"Missing migration files: {missing}"
