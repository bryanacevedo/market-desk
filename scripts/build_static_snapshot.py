"""Builds the public demo as a static snapshot: the web app plus every response it needs, saved as files.

It runs the API in this process against a demo database (`python -m market demo` builds one), reads it the way the screens
do, as each of the two people the desk lets you act as (RevOps and the manager), and writes:

  <out>/                         the built web app, with the snapshot's config and fetch shim, noindex and the demo note
  <out>/_snapshot/abc.json.gz    saved responses, sharded by the first 3 hex digits of a key's SHA-1
  <out>/api/books/...            the handoff files and ICP previews the pages offer as downloads, as plain files
  <out>/_headers, robots.txt     noindex everywhere
  <out>/snapshot-manifest.json   every saved request, for the tests and the runbook

A key is the request as the shim sees it: method, path, sorted query pairs, the body with sorted keys, and who the visitor
is acting as. The crawl sends only GETs. The database's fingerprint is compared before and after the crawl (after the
API's own start-up, which applies migrations as any start does), so the build stops if the crawl changed anything.
A response that is the same for both people is saved once and the other key points to it.

    python scripts/build_static_snapshot.py --out .snapshot       # DATABASE_URL names the demo database
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
SHIM = Path(__file__).resolve().parent / "static_snapshot" / "shim.js"
REFUSED = "The public demo does not do this. Run it yourself to try it."
MAX_FILES = 19_000              # Cloudflare Pages takes 20,000 files a deployment on the free plan
FILTER_PAGES = 3                # pages saved for each single filter of the account list
READ_POSTS: list = []           # this app reads with GET only


# ---------------------------------------------------------------- the key, the same as shim.js keyOf

def _canon(v):
    if isinstance(v, list):
        return [_canon(x) for x in v]
    if isinstance(v, dict):
        return {k: _canon(v[k]) for k in sorted(v)}
    return v


def request_key(method: str, path: str, body=None, actor: str = "") -> str:
    parts = urlsplit(path)
    pairs = sorted([list(p) for p in parse_qsl(parts.query, keep_blank_values=True)])
    return json.dumps([method.upper(), parts.path, pairs, None if body is None else _canon(body), str(actor)],
                      separators=(",", ":"), ensure_ascii=False)


def request_hash(method: str, path: str, body=None, actor: str = "") -> str:
    return hashlib.sha1(request_key(method, path, body, actor).encode()).hexdigest()


def is_read(method: str, path: str) -> bool:
    return method == "GET"


# ---------------------------------------------------------------- what the screens ask for, read from web/src

LITERAL = re.compile(r"`([^`]*)`|\"([^\"]*)\"")


def web_read_templates(src: Path = WEB / "src") -> list[str]:
    """Every path the screens read, as written in the code: the first path in each useData call and each Wrap `path=`,
    and each api call with no options (a GET). The tests check each one has a saved response; writes are not listed:
    the shim refuses them."""
    found: set[str] = set()
    for f in sorted(src.rglob("*.tsx")) + sorted(src.rglob("*.ts")):
        text = f.read_text()
        for m in re.finditer(r"\buseData(?:<[^>]*>)?\(|\bpath=\{", text):
            lit = LITERAL.search(text, m.end(), m.end() + 300)
            if lit and lit.start() < m.end() + 4:
                found.add(lit.group(1) if lit.group(1) is not None else lit.group(2))
        for m in re.finditer(r"\bapi(?:<[^>]*>)?\(\s*(?:`([^`]*)`|\"([^\"]*)\")\s*\)", text):
            found.add(m.group(1) if m.group(1) is not None else m.group(2))
        # A path built with a ternary (the rollback sheet): every literal in it.
        for m in re.finditer(r"\bpath=\{\s*\w+\s*\?\s*\"([^\"]+)\"\s*:\s*\"([^\"]+)\"", text):
            found.update(m.groups())
    # A template that nests another (`/api/territories${plan ? `?plan=${plan}` : ""}`) is cut where the nesting starts.
    found = {t[:t.rindex("${")] if t.count("${") > t.count("}") else t for t in found}
    return sorted(t for t in found if t.startswith("/api/"))


def template_pattern(t: str) -> re.Pattern:
    """A template's path part as a pattern: each ${...} matches part of one path segment."""
    parts = re.split(r"\$\{(?:[^{}]|\{[^{}]*\})*\}", t)
    marked = "\0".join(parts).split("?", 1)[0]
    return re.compile("^" + "[^/?]*".join(re.escape(p) for p in marked.split("\0")) + "$")


# ---------------------------------------------------------------- the database's fingerprint

def fingerprint(url: str) -> dict:
    import psycopg
    with psycopg.connect(url, autocommit=True) as c:
        tables = [r[0] for r in c.execute("select tablename from pg_tables where schemaname = 'public' order by 1")]
        out = {}
        for t in tables:
            n, x = c.execute(f'select count(*), coalesce(max(xmin::text::bigint), 0) from "{t}"').fetchone()
            out[t] = [n, x]
        return out


# ---------------------------------------------------------------- the crawl

class Crawl:
    def __init__(self, client, log=print):
        self.c = client
        self.saved: dict[str, list] = {}
        self.manifest: list[dict] = []
        self.sent: list[tuple[str, str]] = []
        self.raw: dict[str, bytes] = {}    # files kept as they are, by the path the page links to
        self.log = log

    def get(self, path: str, actor: str, save: bool = True):
        self.sent.append(("GET", path))
        r = self.c.get(path, headers={"X-Acting-As": str(actor)})
        if r.status_code >= 500 or r.status_code == 429:
            raise SystemExit(f"{path} answered {r.status_code}: {r.text[:200]}")
        data = r.json() if r.content and r.headers.get("content-type", "").startswith("application/json") else None
        if save:
            h = request_hash("GET", path, None, actor)
            if h not in self.saved:
                self.saved[h] = [r.status_code, data]
                self.manifest.append({"method": "GET", "path": path, "actor": str(actor), "status": r.status_code, "hash": h})
        return data if r.status_code == 200 else None


def _domain_rows(data) -> set[int]:
    """The id of every row, at any depth, that carries a primary_domain: a company row."""
    out: set[int] = set()
    if isinstance(data, dict):
        if "primary_domain" in data and isinstance(data.get("id"), int):
            out.add(data["id"])
        for v in data.values():
            out |= _domain_rows(v)
    elif isinstance(data, list):
        for v in data:
            out |= _domain_rows(v)
    return out


def prime(client) -> None:
    """The one read in this app that writes: the first read of the marketing qualified rule publishes its version 1 (mqa.current).
    It is done here, before the first fingerprint and outside the crawl, so the crawl itself changes nothing. A demo
    database that has served a request already has it, and this changes nothing."""
    client.get("/api/definitions")


def _company_ids(data) -> set[int]:
    """Every company id named anywhere in a response: a company sheet opens from many lists."""
    out: set[int] = set()
    if isinstance(data, dict):
        for k, v in data.items():
            if k in ("company", "company_id") and isinstance(v, int) and not isinstance(v, bool):
                out.add(v)
            elif k in ("book", "sample", "accounts") and isinstance(v, list):
                # the person sheet's book, a test's sample and a move proposal's accounts open company sheets by `id`
                out |= {r["id"] for r in v if isinstance(r, dict) and isinstance(r.get("id"), int)}
                out |= _company_ids(v)
            else:
                out |= _company_ids(v)
    elif isinstance(data, list):
        for v in data:
            out |= _company_ids(v)
    return out


def crawl(client, db_url: str, *, account_pages: int | None = None, log=print) -> Crawl:
    """Reads everything a visitor can reach, as each person the desk lets you act as."""
    import psycopg
    k = Crawl(client, log)
    with psycopg.connect(db_url, autocommit=True) as conn:
        def col(sql: str) -> list:
            return [r[0] for r in conn.execute(sql)]
        users = conn.execute("select id, role from users where active and role in ('revops', 'manager') "
                             "order by case role when 'revops' then 0 else 1 end, name").fetchall()
        user_ids = col("select id from users order by id")
        finding_ids = col("select id from findings order by id")
        version_ids = col("select id from icp_versions order by id")
        plan_ids = col("select id from territory_plans order by id")
        test_ids = col("select id from segment_tests order by id")
        proposal_ids = col("select id from change_proposals order by id")
        book_ids = col("select id from target_books order by id")
        source_keys = col("select key from sources order by key")
        move_proposal_ids = col("select id from move_proposals order by id")
        manual = conn.execute("select plan, company from assignments where reason_code = 'manual' order by plan, company").fetchall()
        files = conn.execute("select book, path, bytes from target_book_files order by book, path").fetchall()
    from market import catalog as C
    segments = [s["key"] for s in C.SEGMENTS] + [C.OUTSIDE["key"]]
    regions = list(C.REGION_GROUPS)
    default_actor = next(str(i) for i, role in users if role == "manager")
    k.actors = [str(i) for i, _ in users]
    k.default_actor = default_actor

    fixed = ["/api/me", "/api/market?by=segment", "/api/market?by=region_group", "/api/evidence", "/api/profile", "/api/changes",
             "/api/tests", "/api/territories", "/api/move-proposals", "/api/move-proposals/options", "/api/handoffs",
             "/api/sources", "/api/settings", "/api/profile/rollback-preview", "/api/plans/rollback-preview"]
    fixed += [f"/api/territories?plan={p}" for p in plan_ids]
    fixed += [f"/api/segments/{s}" for s in segments]
    fixed += [f"/api/findings/{i}" for i in finding_ids]
    for v in version_ids:
        fixed += [f"/api/profile/versions/{v}", f"/api/profile/versions/{v}/moves", f"/api/profile/versions/{v}/publish-preview"]
    fixed += [f"/api/plans/{p}/activate-preview" for p in plan_ids]
    fixed += [f"/api/tests/{t}" for t in test_ids]
    fixed += [f"/api/proposals/{p}" for p in proposal_ids]
    fixed += [f"/api/books/{b}" for b in book_ids]
    fixed += [f"/api/sources/{s}" for s in source_keys]
    fixed += [f"/api/people/{u}" for u in user_ids]
    fixed += [f"/api/move-proposals/{m}" for m in move_proposal_ids]
    fixed += [f"/api/moves/{p}/{c}" for p, c in manual]

    n_pages = account_pages
    for uid, _ in users:
        actor = str(uid)
        for p in fixed:
            k.get(p, actor)
        # The account list: every page, then the first pages of each single filter.
        first = k.get("/api/accounts", actor) or {}
        pages = first.get("pages", 1) if n_pages is None else min(first.get("pages", 1), n_pages)
        for page in range(2, pages + 1):
            k.get(f"/api/accounts?page={page}", actor)
        singles = [("tier", t) for t in ("A", "B", "C", "X", "NJ")] + [("segment", s) for s in segments] \
            + [("owner", "unassigned")] + [("owner", o["id"]) for o in first.get("owners", [])] + [("region", r) for r in regions]
        for key, val in singles:
            total_pages = FILTER_PAGES
            for page in range(1, total_pages + 1):
                q = urlencode({key: val, **({"page": page} if page > 1 else {})})
                d = k.get(f"/api/accounts?{q}", actor)
                if not d or page >= d.get("pages", 1):
                    break
        log(f"  actor {actor}: {len(k.saved)} saved so far")

    # Every company a sheet can open: those in the account list, and any other company named in a saved answer.
    wanted: set[int] = set()
    for status, data in list(k.saved.values()):
        if status == 200:
            wanted |= _company_ids(data)
            wanted |= _domain_rows(data)
    log(f"  companies to read: {len(wanted)}")
    for n, cid in enumerate(sorted(wanted)):
        for uid, _ in users:
            k.get(f"/api/companies/{cid}", str(uid))
        if n and n % 2000 == 0:
            log(f"  companies read: {n}")

    # The files the pages offer as downloads, kept as plain files.
    for b, path, data in files:
        k.raw[f"/api/books/{b}/files/{path}"] = bytes(data)
    for v in version_ids:
        r = client.get(f"/api/handoffs/preview/{v}/icp.json", headers={"X-Acting-As": default_actor})
        k.sent.append(("GET", f"/api/handoffs/preview/{v}/icp.json"))
        if r.status_code == 200:
            k.raw[f"/api/handoffs/preview/{v}/icp.json"] = r.content
    return k


# ---------------------------------------------------------------- the bundle

def write_bundle(out: Path, k: Crawl, taken_on: str) -> dict:
    snap = out / "_snapshot"
    snap.mkdir(parents=True, exist_ok=True)
    # The snapshot says what it is: the shell shows the note when /api/me carries `snapshot`.
    for actor in k.actors:
        status, me = k.saved[request_hash("GET", "/api/me", None, actor)]
        me["snapshot"] = {"taken_on": taken_on}
        me["links"] = {}
    # A response that is the same for both people is kept once.
    seen: dict[str, str] = {}
    saved: dict[str, list] = {}
    for h, (status, data) in k.saved.items():
        digest = hashlib.sha1(json.dumps([status, data], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        if digest in seen and seen[digest] != h:
            saved[h] = [status, None, seen[digest]]
        else:
            seen.setdefault(digest, h)
            saved[h] = [status, data]
    shards: dict[str, dict] = {}
    for h, v in saved.items():
        shards.setdefault(h[:3], {})[h] = v
    raw = 0
    for name, items in shards.items():
        data = json.dumps(items, separators=(",", ":"), ensure_ascii=False).encode()
        raw += len(data)
        (snap / f"{name}.json.gz").write_bytes(gzip.compress(data, 9, mtime=0))
    for path, body in k.raw.items():
        target = out / path.lstrip("/")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
    (out / "snapshot-config.js").write_text(
        "window.__SNAPSHOT = " + json.dumps({"takenOn": taken_on, "actors": k.actors, "defaultActor": k.default_actor}) + ";\n")
    (out / "snapshot-manifest.json").write_text(json.dumps({"taken_on": taken_on, "requests": k.manifest}, separators=(",", ":")))
    return {"responses": len(k.saved), "kept_once": sum(1 for v in saved.values() if len(v) == 2), "shards": len(shards), "raw_bytes": raw,
            "plain_files": len(k.raw)}


def finish_web(out: Path) -> None:
    """The built app gets the config and the shim before its own script, noindex, and the headers file."""
    html = (out / "index.html").read_text()
    html = html.replace("<head>", '<head>\n    <meta name="robots" content="noindex,nofollow" />\n'
                                  '    <script src="/snapshot-config.js"></script>\n    <script src="/snapshot-shim.js"></script>', 1)
    (out / "index.html").write_text(html)
    shutil.copyfile(SHIM, out / "snapshot-shim.js")
    (out / "_headers").write_text("/*\n  X-Robots-Tag: noindex, nofollow\n  X-Content-Type-Options: nosniff\n  Referrer-Policy: no-referrer\n"
                                  "\n/_snapshot/*\n  Cache-Control: public, max-age=300\n")
    (out / "robots.txt").write_text("User-agent: *\nDisallow: /\n")


def dir_size(p: Path) -> tuple[int, int]:
    files = [f for f in p.rglob("*") if f.is_file()]
    return len(files), sum(f.stat().st_size for f in files)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", default=str(ROOT / ".snapshot"))
    ap.add_argument("--skip-web-build", action="store_true", help="use web/dist as it is")
    ap.add_argument("--account-pages", type=int, default=None, help="save only this many pages of the account list (default all)")
    ap.add_argument("--max-mb", type=float, default=60.0, help="fail when the bundle is larger")
    a = ap.parse_args(argv)
    url = os.environ.get("DATABASE_URL", "postgres://postgres@127.0.0.1:54339/market")
    if re.search(r"/sim_[^/]*$", url):
        raise SystemExit("Refusing a sim_ database: the snapshot reads a demo database of its own.")
    # Read as the public demo does; the in-process rate limit is for visitors, not for this one reader.
    os.environ.update(PUBLIC_DEMO="1", NO_WORKER="1", MODE="demo", AUTH_MODE="demo")
    os.environ.pop("DESK_LINKS", None)
    sys.path.insert(0, str(ROOT / "src"))
    out = Path(a.out).resolve()
    t0 = time.time()
    if not a.skip_web_build:
        subprocess.run(["npm", "run", "build"], cwd=WEB, check=True)
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(WEB / "dist", out)

    import logging
    logging.disable(logging.INFO)
    from fastapi.testclient import TestClient

    from market import db
    from market.api import app as appmod
    appmod.rate_limit = lambda *args, **kw: None
    with TestClient(appmod.app) as client:
        prime(client)
        before = fingerprint(url)
        k = crawl(client, url, account_pages=a.account_pages)
        after = fingerprint(url)
    db.close()
    if before != after:
        changed = [t for t in before if before[t] != after.get(t)]
        raise SystemExit(f"The crawl changed the database ({', '.join(changed)}). Nothing is published.")
    writes = [s for s in k.sent if not is_read(*s)]
    if writes:
        raise SystemExit(f"The crawl sent a change: {writes[:3]}")
    taken_on = dt.date.today().strftime("%-d %B %Y")
    stats = write_bundle(out, k, taken_on)
    finish_web(out)
    files, size = dir_size(out)
    missing = uncovered(k)
    report = {**stats, "files": files, "bytes": size, "seconds": round(time.time() - t0), "uncovered": missing}
    print(json.dumps(report, indent=1))
    if missing:
        raise SystemExit(f"Screens read paths the snapshot did not save: {missing}")
    if size > a.max_mb * 1_000_000:
        raise SystemExit(f"The bundle is {size / 1e6:.1f} MB, over {a.max_mb} MB.")
    if files > MAX_FILES:
        raise SystemExit(f"The bundle has {files} files, over {MAX_FILES}.")
    return 0


# Read paths the screens use only inside a form that a change fills in, or that need a typed value: answered by the shim
# with a plain "not in the snapshot" message (see the runbook).
NOT_SAVED = {"/api/move-proposals/territory-preview", "/api/move-proposals/candidates"}


def uncovered(k: Crawl, templates: list[str] | None = None) -> list[str]:
    paths = [urlsplit(e["path"]).path for e in k.manifest if e["status"] in (200, 403)]
    out = []
    for t in templates if templates is not None else web_read_templates():
        if t.split("?", 1)[0] in NOT_SAVED:
            continue
        pat = template_pattern(t)
        if not any(pat.match(p) for p in paths):
            out.append(t)
    return out


if __name__ == "__main__":
    raise SystemExit(main())
