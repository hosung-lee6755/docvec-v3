"""Test that critical migrations work on fresh database installations."""

import subprocess
import tempfile
import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text


@pytest.mark.integration
def test_migration_c2d4e6f8a0b1_fresh_install():
    """Test that migration c2d4e6f8a0b1 (add PREPROCESS workflow) works on empty DB.

    This migration creates the system user AND the workflow that references it.
    On an empty DB, the workflow FK constraint will fail if the user isn't created first.
    This test verifies the fix: the migration creates the system user with ON CONFLICT DO NOTHING
    before inserting the workflow.
    """
    # Create temporary Postgres database
    with tempfile.TemporaryDirectory() as tmpdir:
        db_url = "postgresql://postgres:postgres@localhost:5432/test_migration_fresh"

        # We assume Postgres is running on localhost:5432 (Docker Compose setup)
        # Skip if Postgres is not available
        try:
            engine = create_engine(db_url)
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
        except Exception:
            pytest.skip("Postgres not available on localhost:5432")

        # Run migrations (this exercises the fix)
        backend_dir = Path(__file__).parent.parent.parent
        os.chdir(backend_dir)

        # Set the database URL for Alembic
        env = os.environ.copy()
        env["DATABASE_URL"] = db_url

        try:
            # Create the database
            engine = create_engine("postgresql://postgres:postgres@localhost:5432/")
            with engine.connect() as conn:
                conn.execute(text("DROP DATABASE IF EXISTS test_migration_fresh"))
                conn.execute(text("CREATE DATABASE test_migration_fresh"))

            # Run Alembic upgrade
            result = subprocess.run(
                ["poetry", "run", "alembic", "upgrade", "head"],
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
            )

            assert result.returncode == 0, f"Migration failed: {result.stderr}"

            # Verify the system user was created
            engine = create_engine(db_url)
            with engine.connect() as conn:
                system_user = conn.execute(
                    text("SELECT id, email, username FROM users WHERE id = '00000000-0000-0000-0000-000000000001'")
                ).first()
                assert system_user is not None, "System user was not created"
                assert system_user[1] == "system@docvec.internal"
                assert system_user[2] == "system"

            # Verify the workflow was created
            with engine.connect() as conn:
                workflow = conn.execute(
                    text("SELECT id, project_id, kind, name FROM workflow_definitions WHERE id = '00000000-0000-0000-0000-0000000000f1'")
                ).first()
                assert workflow is not None, "System workflow was not created"
                assert workflow[1] is None, "System workflow should have project_id = NULL"
                assert workflow[2] == "PREPROCESS", "System workflow should be PREPROCESS kind"
                assert "표준" in workflow[3], "System workflow should have Korean name"

            # Verify the workflow version was created
            with engine.connect() as conn:
                version = conn.execute(
                    text("SELECT id, workflow_id FROM workflow_versions WHERE id = '00000000-0000-0000-0000-0000000000f2'")
                ).first()
                assert version is not None, "System workflow version was not created"
                assert version[1] == "00000000-0000-0000-0000-0000000000f1"

        finally:
            # Cleanup
            try:
                engine = create_engine("postgresql://postgres:postgres@localhost:5432/")
                with engine.connect() as conn:
                    conn.execute(text("DROP DATABASE IF EXISTS test_migration_fresh"))
            except Exception:
                pass
