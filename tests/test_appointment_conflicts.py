from pathlib import Path


def test_scheduling_migration_declares_postgresql_exclusion_constraint():
    migration = Path("migrations/versions/202607050001_create_scheduling_domain.py").read_text()

    assert "CREATE EXTENSION IF NOT EXISTS btree_gist" in migration
    assert "EXCLUDE USING gist" in migration
    assert "tstzrange(start_at, end_at, '[)')" in migration
    assert "WHERE (status = 'scheduled')" in migration
    assert "excl_appointments_scheduled_time_overlap" in migration
