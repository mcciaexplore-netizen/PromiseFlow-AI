import os
import threading
from datetime import datetime
import pytest
from backend.database import Database, DatabaseUnavailable, Record, postgres_parameters, connection_failure_hint, ROOT
from backend.store import Store, Conflict
from backend.db_admin import migrate_sqlite
from backend.engine import CpSatProvider


def test_supabase_certificate_default_and_relative_path(monkeypatch, tmp_path):
    monkeypatch.delenv("PROMISEFLOW_DB_SSLROOTCERT", raising=False)
    monkeypatch.chdir(tmp_path)
    url = "postgresql://postgres.ref:secret@aws-0-ap-south-1.pooler.supabase.com:5432/postgres"
    options = Database(url).postgres_options()
    assert options["sslmode"] == "verify-full"
    assert options["sslrootcert"] == str(ROOT / "backend/certs/supabase-ca.crt")
    monkeypatch.setenv("PROMISEFLOW_DB_SSLROOTCERT", "backend/certs/supabase-ca.crt")
    assert Database(url).postgres_options() == options
    monkeypatch.setenv("PROMISEFLOW_DB_SSLROOTCERT", "missing-private-path.crt")
    with pytest.raises(DatabaseUnavailable, match="DB_TLS") as exc:
        Database(url).postgres_options()
    assert "missing-private-path" not in str(exc.value)


@pytest.mark.parametrize("message,category", [
    ("password authentication failed", "DB_AUTH"),
    ("SSL error: certificate verify failed", "DB_TLS"),
    ("could not translate host name", "DB_DNS"),
    ("connection timeout expired", "DB_NETWORK"),
    ("unexpected driver failure", "DB_CONNECTION"),
])
def test_connection_diagnostics_never_include_driver_secrets(message, category):
    hint = connection_failure_hint(RuntimeError(message + " postgresql://u:VERY_PRIVATE@host/db"))
    assert hint.startswith(category)
    assert "VERY_PRIVATE" not in hint and "postgresql://" not in hint


def test_explicit_sqlite_target_overrides_cloud_environment(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "PROMISEFLOW_DATABASE_URL", "postgresql://user:secret@db.example.com/postgres"
    )
    db = Database(tmp_path / "local.db")
    assert not db.postgres
    cloud = Database()
    assert cloud.postgres
    assert cloud.postgres_options()["sslmode"] == "verify-full"
    assert cloud.path is None


@pytest.mark.parametrize(
    "url",
    [
        "https://project.supabase.co",
        "postgresql://u:p@db.example.com/postgres?sslmode=disable",
        "postgresql://u:p@localhost/postgres?host=db.example.com",
    ],
)
def test_invalid_or_unverified_remote_configuration_rejected(url):
    with pytest.raises(ValueError):
        Database(url).postgres_options()


@pytest.mark.parametrize(
    "schema",
    ["public", "auth", "storage", "pg_catalog", "unsafe;DROP TABLE users", "UPPER"],
)
def test_schema_must_be_private_and_safe(tmp_path, schema):
    with pytest.raises(ValueError):
        Database(tmp_path / "test.db", schema=schema)


def test_parameter_conversion_keeps_literals_and_values_separate():
    assert (
        postgres_parameters("SELECT '?' AS literal, ? AS value, '100%' AS pct")
        == "SELECT '?' AS literal, %s AS value, '100%%' AS pct"
    )
    row = Record(id=3, name="O'Brien ? 100%")
    assert row[0] == row["id"] == 3
    assert dict(row)["name"] == "O'Brien ? 100%"


@pytest.fixture
def cloud(storage_target):
    if not os.environ.get("PROMISEFLOW_TEST_POSTGRES_URL"):
        pytest.skip(
            "Set PROMISEFLOW_TEST_POSTGRES_URL for disposable PostgreSQL integration tests"
        )
    path, schema = storage_target
    return Store(path, schema=schema)


def test_postgres_generated_ids_rollback_and_values(cloud, factory, base):
    factory.settings.plant_name = "O'Brien ? 100%"
    cloud.save_factory(factory, 0, "tester", "Seed")
    assert cloud.load().settings.plant_name == factory.settings.plant_name
    with pytest.raises(RuntimeError):
        with cloud.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "INSERT INTO users VALUES (?,?,?)", ("rollback", "sales", "hash")
            )
            raise RuntimeError("Abort transaction")
    with cloud.connect() as db:
        assert (
            db.execute("SELECT 1 FROM users WHERE username=?", ("rollback",)).fetchone()
            is None
        )
    result = CpSatProvider().solve(factory, base)
    vid = cloud.save_version(factory, result, 1, None, "tester", "Plan")
    assert vid > 0
    assert cloud.activate(vid, "tester")["id"] == vid


def test_postgres_two_writers_cannot_share_a_revision(cloud, factory):
    cloud.save_factory(factory, 0, "tester", "Seed")
    barrier = threading.Barrier(2)
    outcomes = []

    def write():
        barrier.wait(timeout=10)
        try:
            cloud.save_factory(factory, 1, "tester", "Concurrent update")
            outcomes.append("saved")
        except Conflict:
            outcomes.append("conflict")

    threads = [threading.Thread(target=write) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
    assert sorted(outcomes) == ["conflict", "saved"]


def test_postgres_schema_has_rls_and_no_public_grants(cloud):
    with cloud.connect() as db:
        rows = db.execute(
            "SELECT c.relrowsecurity FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=? AND c.relkind='r'",
            (cloud.database.schema,),
        ).fetchall()
        assert len(rows) == 15 and all(r[0] for r in rows)
        public_access = db.execute(
            "SELECT count(*) FROM pg_namespace n, aclexplode(n.nspacl) a WHERE n.nspname=? AND a.grantee=0",
            (cloud.database.schema,),
        ).fetchone()[0]
        assert public_access == 0


def test_postgres_copy_preserves_plan_and_rejects_overwrite(
    cloud, tmp_path, factory, base
):
    source_path = tmp_path / "source.db"
    source = Store(source_path)
    source.save_factory(factory, 0, "tester", "Seed")
    with source.connect() as db:
        db.execute("INSERT INTO meta VALUES ('mode','demo')")
        db.execute("INSERT INTO sessions VALUES ('old-session','tester',9999999999)")
    result = CpSatProvider().solve(factory, base)
    vid = source.save_version(factory, result, 1, None, "tester", "Baseline")
    source.activate(vid, "tester")
    outcome = migrate_sqlite(source_path, cloud)
    assert outcome["active_version"] == vid
    assert cloud.snapshot() == source.snapshot()
    with cloud.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0
    next_id = cloud.save_version(factory, result, 2, vid, "tester", "Next plan")
    assert next_id > vid
    with pytest.raises(ValueError, match="initialized"):
        migrate_sqlite(source_path, cloud)
