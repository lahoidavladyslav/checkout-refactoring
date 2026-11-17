"""PostgreSQL fixtures.

The tests run against a real PostgreSQL, found in this order:

1. ``TEST_DATABASE_URL`` (an admin URL such as ``postgresql+psycopg://postgres@localhost/postgres``),
   which is what CI uses;
2. a throwaway cluster started from the local PostgreSQL binaries (``initdb`` / ``pg_ctl``);
3. otherwise the tests are skipped.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url

from shop.infrastructure.sql.engine import create_db_engine

ROOT = Path(__file__).resolve().parents[2]
DB_NAME = "shop_test"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture(scope="session")
def admin_url() -> Iterator[str]:
    configured = os.environ.get("TEST_DATABASE_URL")
    if configured:
        yield configured
        return

    initdb, pg_ctl = shutil.which("initdb"), shutil.which("pg_ctl")
    if not (initdb and pg_ctl):
        pytest.skip("no PostgreSQL: set TEST_DATABASE_URL or install the server binaries")

    data = Path(tempfile.mkdtemp(prefix="shop-pg-"))
    port = _free_port()
    subprocess.run(
        [initdb, "-D", str(data / "data"), "-U", "postgres", "--auth=trust", "-E", "UTF8"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            pg_ctl,
            "-D",
            str(data / "data"),
            "-l",
            str(data / "log"),
            "-o",
            f"-p {port} -c listen_addresses=127.0.0.1 -c unix_socket_directories= "
            "-c fsync=off -c synchronous_commit=off",
            "-w",
            "start",
        ],
        check=True,
        capture_output=True,
    )
    try:
        yield f"postgresql+psycopg://postgres@127.0.0.1:{port}/postgres"
    finally:
        subprocess.run([pg_ctl, "-D", str(data / "data"), "-m", "immediate", "stop"], check=False)
        shutil.rmtree(data, ignore_errors=True)


@pytest.fixture(scope="session")
def database_url(admin_url: str) -> Iterator[str]:
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f"DROP DATABASE IF EXISTS {DB_NAME} WITH (FORCE)"))
        connection.execute(text(f"CREATE DATABASE {DB_NAME}"))
    url = make_url(admin_url).set(database=DB_NAME).render_as_string(hide_password=False)
    try:
        yield url
    finally:
        with admin.connect() as connection:
            connection.execute(text(f"DROP DATABASE IF EXISTS {DB_NAME} WITH (FORCE)"))
        admin.dispose()


def alembic_config(url: str) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    config.cmd_opts = None  # type: ignore[assignment]  # alembic reads -x args from here
    os.environ["SHOP_DATABASE_URL"] = url
    return config


@pytest.fixture(scope="session")
def migrated_url(database_url: str) -> str:
    """The test database with the schema created by the real Alembic migrations."""
    command.upgrade(alembic_config(database_url), "head")
    return database_url


@pytest.fixture
def engine(migrated_url: str) -> Iterator[Engine]:
    """A clean schema for every test."""
    engine = create_db_engine(migrated_url)
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE outbox, order_lines, orders RESTART IDENTITY CASCADE"))
        connection.execute(text("ALTER SEQUENCE orders_id_seq RESTART WITH 1"))
    yield engine
    engine.dispose()
