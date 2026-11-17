"""The static snapshot (scripts/build_static_snapshot.py): every read the screens make has a saved answer, the crawl
changes nothing, the shim and the build agree on each request's key, and every change is refused in plain words."""
from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from market import db

ROOT = Path(__file__).resolve().parents[1]
SHIM = ROOT / "scripts" / "static_snapshot" / "shim.js"
_spec = importlib.util.spec_from_file_location("build_static_snapshot", ROOT / "scripts" / "build_static_snapshot.py")
snap = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(snap)

NODE = shutil.which("node")
FAKE_WINDOW = "globalThis.window = globalThis; globalThis.location = { href: 'https://snap.example/', origin: 'https://snap.example' };"


@pytest.fixture(scope="module")
def crawled(demo, database):
    """The demo world, crawled as the public demo's two visitors (one page of the account list is enough here)."""
    from market.api import app as appmod
    saved_limit = appmod.rate_limit
    appmod.rate_limit = lambda *a, **k: None
    try:
        with TestClient(appmod.app) as client:
            snap.prime(client)
            before = snap.fingerprint(database)
            k = snap.crawl(client, database, account_pages=1, log=lambda *_: None)
            after = snap.fingerprint(database)
    finally:
        appmod.rate_limit = saved_limit
    return k, before, after


def test_every_read_the_screens_make_has_a_saved_response(crawled):
    k, _, _ = crawled
    templates = snap.web_read_templates()
    # The parser finds the reads that matter, so an empty or broken parse cannot pass.
    for must in ("/api/me", "/api/accounts?${qs.toString()}", "/api/companies/${id}", "/api/market?by=${by}",
                 "/api/profile/versions/${id}/moves", "/api/territories", "/api/sources/${id}"):
        assert must in templates, must
    assert snap.uncovered(k, templates) == []
    assert all(e["status"] < 500 and e["status"] != 429 for e in k.manifest)


def test_the_crawl_changes_nothing(crawled):
    k, before, after = crawled
    assert before == after
    assert k.sent and all(snap.is_read(m, p) for m, p in k.sent)
    assert {m for m, _ in k.sent} == {"GET"}


def test_both_people_and_every_company_are_saved(crawled):
    k, _, _ = crawled
    assert len(k.actors) == 2 and k.default_actor in k.actors
    for actor in k.actors:
        assert snap.request_hash("GET", "/api/me", None, actor) in k.saved
        assert snap.request_hash("GET", "/api/accounts", None, actor) in k.saved
    status, page = k.saved[snap.request_hash("GET", "/api/accounts", None, k.default_actor)]
    assert status == 200 and page["rows"]
    for r in page["rows"]:
        assert snap.request_hash("GET", f"/api/companies/{r['id']}", None, k.default_actor) in k.saved


@pytest.mark.skipif(not NODE, reason="node is not installed")
def test_the_shim_and_the_build_agree_on_each_key():
    cases = [
        ["GET", "/api/me", None, "2"],
        ["GET", "/api/accounts?tier=A&page=2", None, "1"],
        ["GET", "/api/accounts?page=2&tier=A", None, "1"],
        ["GET", "/api/market?by=region_group", None, "2"],
        ["GET", "/api/move-proposals/candidates?q=a+b", None, "2"],
    ]
    js = (f"{FAKE_WINDOW}{SHIM.read_text()};const cases = {json.dumps(cases)};"
          "console.log(JSON.stringify(cases.map(([m, p, b, a]) => window.__snapshotKey(m, new URL(p, location.href), b, a))));")
    out = json.loads(subprocess.run([NODE, "-e", js], capture_output=True, text=True, check=True).stdout)
    assert out == [snap.request_key(m, p, b, a) for m, p, b, a in cases]
    assert out[1] == out[2]  # query order does not matter


@pytest.mark.skipif(not NODE, reason="node is not installed")
def test_the_shim_answers_from_the_bundle_and_refuses_every_change(crawled, tmp_path):
    k, _, _ = crawled
    snap.write_bundle(tmp_path, k, "17 November 2026")
    other = next(a for a in k.actors if a != k.default_actor)
    expect = []
    for e in k.manifest:
        if e["path"].startswith(("/api/me", "/api/accounts", "/api/market", "/api/companies/")) and len(expect) < 120:
            expect.append([e["path"], e["actor"], k.saved[e["hash"]][1]])
    (tmp_path / "expect.json").write_text(json.dumps(expect))
    js = f"""{FAKE_WINDOW}
const fs = require('fs');
globalThis.fetch = async (u) => {{ const p = '{tmp_path}' + String(u);
  return fs.existsSync(p) ? new Response(fs.readFileSync(p)) : new Response('', {{ status: 404 }}); }};
eval(fs.readFileSync('{tmp_path}/snapshot-config.js', 'utf8'));
eval(fs.readFileSync('{SHIM}', 'utf8'));
(async () => {{
  const expect = JSON.parse(fs.readFileSync('{tmp_path}/expect.json', 'utf8'));
  const out = {{ same: 0, wrong: [], refused: [], unknownActor: null, missing: null }};
  for (const [p, a, want] of expect) {{
    const r = await window.fetch(p, {{ headers: {{ 'Content-Type': 'application/json', 'X-Acting-As': a }} }});
    if (r.status === 200 || r.status === 403) {{ const got = await r.json(); if (JSON.stringify(got) === JSON.stringify(want)) out.same++; else out.wrong.push(p); }}
    else out.wrong.push(p + ' ' + r.status);
  }}
  for (const m of ['POST', 'PATCH', 'DELETE', 'PUT']) {{
    const r = await window.fetch('/api/tests/1/start', {{ method: m, body: '{{}}' }}); out.refused.push([r.status, (await r.json()).error]);
  }}
  const unknown = await window.fetch('/api/me', {{ headers: {{ 'X-Acting-As': '999' }} }});
  out.unknownActor = (await unknown.json()).user.id;
  const gone = await window.fetch('/api/accounts?q=lumen'); out.missing = [gone.status, (await gone.json()).error];
  console.log(JSON.stringify(out));
}})();"""
    (tmp_path / "check.js").write_text(js)
    out = json.loads(subprocess.run([NODE, str(tmp_path / "check.js")], capture_output=True, text=True, check=True).stdout)
    assert out["wrong"] == [] and out["same"] == len(expect)
    assert out["refused"] == [[403, snap.REFUSED]] * 4
    assert str(out["unknownActor"]) == k.default_actor        # a choice the snapshot did not save reads as the default person
    assert out["missing"][0] == 404 and "full demo" in out["missing"][1]
    assert other in k.actors
    me = k.saved[snap.request_hash("GET", "/api/me", None, k.default_actor)][1]
    assert me["snapshot"]["taken_on"] == "17 November 2026" and me["links"] == {}


def test_every_company_named_in_a_saved_answer_has_a_saved_sheet(crawled):
    k, _, _ = crawled
    named = set()
    for status, data in k.saved.values():
        if status == 200:
            named |= snap._company_ids(data) | snap._domain_rows(data)
    assert named
    for cid in named:
        assert snap.request_hash("GET", f"/api/companies/{cid}", None, k.default_actor) in k.saved, cid


def test_a_response_the_same_for_both_people_is_kept_once(crawled, tmp_path):
    k, _, _ = crawled
    stats = snap.write_bundle(tmp_path, k, "17 November 2026")
    assert 0 < stats["kept_once"] < stats["responses"]
    a, b = k.actors
    ha, hb = (snap.request_hash("GET", "/api/evidence", None, x) for x in (a, b))
    assert k.saved[ha] == k.saved[hb]
    import gzip
    entry = json.loads(gzip.decompress((tmp_path / "_snapshot" / f"{hb[:3]}.json.gz").read_bytes()))[hb]
    assert entry == [200, None, ha]


def test_the_handoff_files_are_plain_files(crawled, tmp_path):
    k, _, _ = crawled
    snap.write_bundle(tmp_path, k, "17 November 2026")
    with db.tx() as cur:
        books = db.all(cur, "select book, path, bytes from target_book_files")
    assert books
    for b in books:
        assert (tmp_path / "api" / "books" / str(b["book"]) / "files" / b["path"]).read_bytes() == bytes(b["bytes"])


def test_the_bundle_is_noindex(tmp_path):
    (tmp_path / "index.html").write_text("<!doctype html><html><head><title>x</title></head><body></body></html>")
    snap.finish_web(tmp_path)
    html = (tmp_path / "index.html").read_text()
    assert '<meta name="robots" content="noindex,nofollow" />' in html
    assert html.index("snapshot-config.js") < html.index("snapshot-shim.js") < html.index("</head>")
    assert "X-Robots-Tag: noindex" in (tmp_path / "_headers").read_text()
    assert "Disallow: /" in (tmp_path / "robots.txt").read_text()
    assert (tmp_path / "snapshot-shim.js").read_text() == SHIM.read_text()


def test_the_refusal_wording_is_the_same_in_the_shim_and_the_build():
    import re
    assert re.search(r'var REFUSED = "([^"]+)"', SHIM.read_text()).group(1) == snap.REFUSED
