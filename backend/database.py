"""Small SQL connection boundary for local SQLite and server-side PostgreSQL.

Only application-authored SQL crosses this boundary. Values remain driver-bound.
The PostgreSQL schema is private; browsers never receive database credentials.
"""

import os
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env", override=False)


class DatabaseUnavailable(RuntimeError):
    """Sanitized database failure safe for an API response or CLI output."""


def connection_failure_hint(error):
    """Return fixed diagnostic text only; never return driver text or credentials."""
    message = str(error).lower()
    if "password authentication failed" in message or "tenant or user not found" in message:
        return "DB_AUTH: Check the database password and pooler username in the deployment environment."
    if "certificate" in message or "ssl error" in message:
        return "DB_TLS: Check the trusted CA file. Use backend/certs/supabase-ca.crt, not a local computer path; retain sslmode=verify-full."
    if any(x in message for x in ("translate host", "resolve host", "name or service not known", "getaddrinfo")):
        return "DB_DNS: Database hostname could not be resolved. Check the project's session pooler hostname."
    if any(x in message for x in ("network is unreachable", "connection refused", "timeout", "timed out")):
        return "DB_NETWORK: Database endpoint could not be reached. Check the session pooler address and network restrictions."
    return "DB_CONNECTION: Check the deployment's server-only PostgreSQL connection and schema permissions."


def postgres_parameters(statement):
    # Preserve quoted question marks and escape literal '%' for psycopg binding.
    pieces = re.split(r"('(?:''|[^'])*'|\"(?:\"\"|[^\"])*\")", statement)
    return "".join(
        p.replace("%", "%%").replace("?", "%s") if i % 2 == 0 else p.replace("%", "%%")
        for i, p in enumerate(pieces)
    )


class Record(dict):
    """Mapping with SQLite-compatible positional access, including SELECT counts."""

    def __getitem__(self, key):
        return (
            tuple(self.values())[key]
            if isinstance(key, int)
            else super().__getitem__(key)
        )


class PostgresCursor:
    def __init__(self, cursor):
        self.cursor = cursor

    @property
    def rowcount(self):
        return self.cursor.rowcount

    def fetchone(self):
        row = self.cursor.fetchone()
        return Record(row) if row is not None else None

    def fetchall(self):
        return [Record(row) for row in self.cursor.fetchall()]

    def __iter__(self):
        return (Record(row) for row in self.cursor)


class PostgresConnection:
    def __init__(self, raw, schema):
        self.raw, self.schema = raw, schema

    def execute(self, statement, parameters=None):
        command = statement.strip().upper()
        if command == "BEGIN IMMEDIATE":
            # Serialize revision-sensitive writes before reading revision/state.
            return PostgresCursor(
                self.raw.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (self.schema,),
                )
            )
        if command == "BEGIN":
            return PostgresCursor(
                self.raw.execute(
                    "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
                )
            )
        return PostgresCursor(
            self.raw.execute(
                postgres_parameters(statement) if parameters is not None else statement,
                parameters,
            )
        )

    def executemany(self, statement, rows):
        cursor = self.raw.cursor()
        cursor.executemany(postgres_parameters(statement), rows)
        return PostgresCursor(cursor)


class Database:
    def __init__(self, path=None, schema=None):
        # Explicit test/local paths always take precedence over cloud settings.
        configured = (
            str(path)
            if path is not None
            else (
                os.environ.get("PROMISEFLOW_DATABASE_URL")
                or os.environ.get("PROMISEFLOW_DB", "data/promiseflow.db")
            )
        )
        self.postgres = configured.startswith(("postgresql://", "postgres://"))
        if "://" in configured and not self.postgres:
            raise ValueError(
                "Use a PostgreSQL connection string, not a Supabase API URL"
            )
        self._connection_string = configured
        self.path = None if self.postgres else configured
        self.schema = schema or os.environ.get("PROMISEFLOW_DB_SCHEMA", "promiseflow")
        if (
            not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", self.schema)
            or self.schema in ("public", "auth", "storage", "extensions", "realtime")
            or self.schema.startswith("pg_")
        ):
            raise ValueError(
                "Use a dedicated private database schema, such as promiseflow"
            )
        if not self.postgres:
            Path(configured).parent.mkdir(parents=True, exist_ok=True)

    def postgres_options(self):
        try:
            url = urlsplit(self._connection_string)
            if not url.hostname or not url.username or not url.path.strip("/"):
                raise ValueError()
            local = url.hostname in ("localhost", "127.0.0.1", "::1")
            options = parse_qs(url.query)
            if set(options) - {"sslmode", "sslrootcert", "application_name"}:
                raise ValueError()
            mode = options.get("sslmode", ["disable" if local else "verify-full"])[-1]
            if not local and mode != "verify-full":
                raise ValueError()
        except ValueError:
            raise ValueError(
                "Invalid PostgreSQL connection configuration; remote databases require sslmode=verify-full"
            ) from None
        result = dict(connect_timeout=10, prepare_threshold=None, sslmode=mode)
        if not local:
            cert = (
                os.environ.get("PROMISEFLOW_DB_SSLROOTCERT")
                or options.get("sslrootcert", [None])[-1]
            )
            if not cert:
                cert = (
                    "backend/certs/supabase-ca.crt"
                    if url.hostname.endswith(".supabase.co") or url.hostname.endswith(".pooler.supabase.com")
                    else "system"
                )
            if cert != "system":
                cert_path = Path(cert)
                if not cert_path.is_absolute():
                    cert_path = ROOT / cert_path
                if not cert_path.is_file():
                    raise DatabaseUnavailable(
                        "DB_TLS: Configured CA file is missing. Set PROMISEFLOW_DB_SSLROOTCERT=backend/certs/supabase-ca.crt for Supabase; local computer paths cannot be used on Vercel."
                    )
                cert = str(cert_path)
            result["sslrootcert"] = cert
        return result

    @contextmanager
    def connect(self):
        if not self.postgres:
            db = sqlite3.connect(self.path, timeout=30)
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA journal_mode=WAL")
            try:
                yield db
                db.commit()
            except Exception:
                db.rollback()
                raise
            finally:
                db.close()
            return
        import psycopg
        from psycopg.rows import dict_row
        from psycopg import sql

        try:
            with psycopg.connect(
                self._connection_string, row_factory=dict_row, **self.postgres_options()
            ) as raw:
                raw.execute(
                    sql.SQL("SET LOCAL search_path TO {}, pg_catalog").format(
                        sql.Identifier(self.schema)
                    )
                )
                raw.execute("SET LOCAL statement_timeout = '30s'")
                raw.execute("SET LOCAL lock_timeout = '10s'")
                yield PostgresConnection(raw, self.schema)
        except psycopg.IntegrityError:
            raise ValueError(
                "Database constraint rejected the operation; refresh and check the supplied records"
            ) from None
        except psycopg.Error as exc:
            raise DatabaseUnavailable(
                f"Database operation failed (SQLSTATE {exc.sqlstate or 'connection'}). {connection_failure_hint(exc)}"
            ) from None

    def initialize(self):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if self.postgres:
                db.execute(f'CREATE SCHEMA IF NOT EXISTS "{self.schema}"')
            identity = (
                "BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY"
                if self.postgres
                else "INTEGER PRIMARY KEY AUTOINCREMENT"
            )
            definitions = {
                "meta": "key TEXT PRIMARY KEY, value TEXT NOT NULL",
                "entities": "kind TEXT NOT NULL, id TEXT NOT NULL, body TEXT NOT NULL, PRIMARY KEY(kind,id)",
                "versions": f"id {identity}, created_at TEXT NOT NULL, created_by TEXT NOT NULL, reason TEXT NOT NULL, base_id BIGINT, revision INTEGER NOT NULL, result TEXT NOT NULL, inputs TEXT NOT NULL, approved_by TEXT, activated_at TEXT",
                "audit": f"id {identity}, at TEXT NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL, detail TEXT NOT NULL",
                "users": "username TEXT PRIMARY KEY, role TEXT NOT NULL, password TEXT NOT NULL",
                "sessions": "hash TEXT PRIMARY KEY, username TEXT NOT NULL, expires DOUBLE PRECISION NOT NULL",
                "imports": "id TEXT PRIMARY KEY, actor TEXT NOT NULL, revision INTEGER NOT NULL, data TEXT NOT NULL, created_at TEXT NOT NULL, consumed INTEGER NOT NULL DEFAULT 0",
                "events": "id TEXT PRIMARY KEY, created_at TEXT NOT NULL, actor TEXT NOT NULL, version_id BIGINT NOT NULL, body TEXT NOT NULL",
                "solve_cache": "fingerprint TEXT PRIMARY KEY, created_at TEXT NOT NULL, result TEXT NOT NULL",
                "decisions": f"id {identity}, version_id BIGINT NOT NULL, actor TEXT NOT NULL, at TEXT NOT NULL, action TEXT NOT NULL, reason TEXT NOT NULL",
                "import_backups": "import_id TEXT PRIMARY KEY, before_data TEXT NOT NULL, applied_revision INTEGER NOT NULL, restored INTEGER NOT NULL DEFAULT 0",
                "solve_jobs": "id TEXT PRIMARY KEY, actor TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, revision INTEGER NOT NULL, result TEXT, error TEXT",
                "actual_events": f"id {identity}, request_id TEXT NOT NULL UNIQUE, actor TEXT NOT NULL, recorded_at TEXT NOT NULL, order_id TEXT NOT NULL, body TEXT NOT NULL",
                "execution_closures": "order_id TEXT PRIMARY KEY, actor TEXT NOT NULL, at TEXT NOT NULL, reason TEXT NOT NULL",
                "actual_corrections": "event_id BIGINT PRIMARY KEY REFERENCES actual_events(id), actor TEXT NOT NULL, at TEXT NOT NULL, reason TEXT NOT NULL",
            }
            for table, definition in definitions.items():
                db.execute(f"CREATE TABLE IF NOT EXISTS {table} ({definition})")
                if self.postgres:
                    db.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
            if self.postgres:
                # Keep even accidentally exposed tables inaccessible to Data API roles.
                roles = ["PUBLIC"] + [
                    r[0]
                    for r in db.execute(
                        "SELECT rolname FROM pg_roles WHERE rolname IN ('anon','authenticated','service_role')"
                    )
                ]
                for role in roles:
                    db.execute(f'REVOKE ALL ON SCHEMA "{self.schema}" FROM {role}')
                    db.execute(
                        f'REVOKE ALL ON ALL TABLES IN SCHEMA "{self.schema}" FROM {role}'
                    )
                    db.execute(
                        f'REVOKE ALL ON ALL SEQUENCES IN SCHEMA "{self.schema}" FROM {role}'
                    )
            db.execute(
                "INSERT INTO meta VALUES ('revision','0') ON CONFLICT (key) DO NOTHING"
            )
            db.execute(
                "INSERT INTO meta VALUES ('active','0') ON CONFLICT (key) DO NOTHING"
            )
            version = db.execute(
                "SELECT value FROM meta WHERE key='schema_version'"
            ).fetchone()
            if version and int(version[0]) > 4:
                raise ValueError(
                    "Database schema is newer than this application; upgrade the server"
                )
            db.execute(
                "INSERT INTO meta VALUES ('schema_version','4') ON CONFLICT (key) DO UPDATE SET value=excluded.value"
            )
