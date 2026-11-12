"""Two builds from the same seed write identical rows. Uses a small world in two scratch databases."""
from __future__ import annotations

import uuid

import psycopg
from psycopg.rows import dict_row

from market import db
from market.sim import world

from .conftest import BASE, _admin

TABLES = ["users", "sources", "companies", "field_values", "reachability", "public_counts", "deals", "deal_roles",
          "customers", "call_notes"]


def _build(name: str) -> dict[str, str]:
    url = BASE.rsplit("/", 1)[0] + "/" + name
    with psycopg.connect(_admin(BASE), autocommit=True) as c:
        c.execute(f'create database "{name}"')
    try:
        db.migrate(url)
        with psycopg.connect(url, row_factory=dict_row) as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    world.build(cur, seed=7, n_companies=1500)
            out = {}
            for t in TABLES:
                cols = [r["column_name"] for r in conn.execute(
                    "select column_name from information_schema.columns where table_name = %s and column_name not in ('created_at') order by ordinal_position", (t,))]
                q = f"select md5(string_agg(row({', '.join(cols)})::text, '|' order by {cols[0]})) as h from {t}"
                out[t] = conn.execute(q).fetchone()["h"]
            return out
    finally:
        with psycopg.connect(_admin(BASE), autocommit=True) as c:
            c.execute(f'drop database if exists "{name}" with (force)')


def test_two_builds_are_identical(database):
    a = _build(f"market_det_{uuid.uuid4().hex[:6]}")
    b = _build(f"market_det_{uuid.uuid4().hex[:6]}")
    assert a == b
