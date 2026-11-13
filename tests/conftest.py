"""Every test runs on real Postgres. The session builds the full demo world (18,000 companies, fixed seed) once in its
own database, dropped at the end; tests that change data run in a transaction that is rolled back."""
from __future__ import annotations

import os
import uuid

import psycopg
import pytest

from market import db

BASE = os.environ.get("TEST_DATABASE_URL", "postgres://postgres@127.0.0.1:54339/postgres")


def _admin(url: str) -> str:
    return url.rsplit("/", 1)[0] + "/postgres"


@pytest.fixture(scope="session")
def database():
    name = f"{os.environ.get('TEST_DB_PREFIX', 'mkb_test_')}{uuid.uuid4().hex[:8]}"
    with psycopg.connect(_admin(BASE), autocommit=True) as c:
        c.execute(f'create database "{name}"')
    url = BASE.rsplit("/", 1)[0] + "/" + name
    db.configure(url, max_size=6)
    db.migrate(url)
    yield url
    db.close()
    with psycopg.connect(_admin(BASE), autocommit=True) as c:
        c.execute(f'drop database if exists "{name}" with (force)')


@pytest.fixture(scope="session")
def demo(database):
    """The demo world, exactly as `python -m market demo` builds it."""
    from market.sim import story
    return story.build_demo()


@pytest.fixture
def cur(demo):
    """A transaction that is rolled back after the test."""
    with db.pool().connection() as conn:
        tx = conn.transaction()
        tx.__enter__()
        with conn.cursor() as c:
            yield c
        tx.__exit__(psycopg.Rollback, psycopg.Rollback(), None)


@pytest.fixture
def users(cur):
    return {u["name"].split()[0]: u for u in db.all(cur, "select * from users")}
