"""The HTTP API and the web app's host.

Identity: in demo mode the browser says who it is acting as (X-Acting-As); in header mode Cloudflare Access's signed
token is verified and a plain header is never trusted. Every write checks the role. Company money (deal sizes, TAM,
SAM, SOM, expected value, costs) leaves the API only for RevOps and managers."""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import threading
import time
import uuid
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .. import (  # noqa: F401 register job handlers
    catalog as C,
)
from .. import (
    db,
    evidence,
    fit,
    handoff,
    jobs,
    profiles,
    proposals,
    territories,
    tests_seg,
)
from ..config import CONFIG
from . import views

log = logging.getLogger("market.api")
WEB = Path(__file__).resolve().parents[3] / "web" / "dist"


@asynccontextmanager
async def lifespan(_app):
    applied = db.migrate()
    if applied:
        log.info("applied migrations at start: %s", ", ".join(applied))
    start_worker()
    yield


_docs = not (CONFIG.public_demo or CONFIG.mode == "live")
app = FastAPI(title="Market Desk", docs_url="/api/docs" if _docs else None, openapi_url="/api/openapi.json" if _docs else None,
              lifespan=lifespan)
MAX_BODY = 1024 * 1024  # 1 MB for every request but the results webhook (5 MB)


@app.middleware("http")
async def headers_and_errors(request: Request, call_next):
    rid = uuid.uuid4().hex[:12]
    started = time.perf_counter()
    limit = 5 * MAX_BODY if request.url.path == "/api/results" else MAX_BODY
    length = request.headers.get("content-length")
    if length and (not length.isdigit() or int(length) > limit):
        return JSONResponse({"error": "Too large."}, status_code=413)
    try:
        response = await call_next(request)
    except Exception:
        log.exception("request %s %s failed (%s)", request.method, request.url.path, rid)
        response = JSONResponse({"error": "Something went wrong on our side.", "request_id": rid}, status_code=500)
    response.headers["X-Request-Id"] = rid
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Strict-Transport-Security"] = "max-age=31536000"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; font-src 'self' data:; "
        "script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")
    if request.url.path.startswith("/api/"):
        log.info('{"rid":"%s","method":"%s","path":"%s","status":%s,"ms":%.0f}', rid, request.method,
                 request.url.path, response.status_code, (time.perf_counter() - started) * 1000)
    return response


_hits: dict[str, deque] = defaultdict(deque)
_hits_lock = threading.Lock()


def rate_limit(request: Request, limit: int = 120, window: float = 60.0) -> None:
    key = request.client.host if request.client else "?"
    now = time.monotonic()
    with _hits_lock:
        if len(_hits) > 10_000:
            for k in [k for k, v in _hits.items() if not v or now - v[-1] > window]:
                del _hits[k]
        q = _hits[key]
        while q and now - q[0] > window:
            q.popleft()
        if len(q) >= limit:
            raise HTTPException(429, "Too many changes in a minute. Try again shortly.")
        q.append(now)


_jwks = None


def _access_email(request: Request) -> str | None:
    """Cloudflare Access signs every request it lets through. Verify the token; never trust a plain header."""
    global _jwks
    import jwt
    token = request.headers.get("Cf-Access-Jwt-Assertion") or request.cookies.get("CF_Authorization")
    if not token:
        return None
    if _jwks is None:
        _jwks = jwt.PyJWKClient(f"https://{CONFIG.access_team_domain}/cdn-cgi/access/certs", cache_keys=True)
    try:
        key = _jwks.get_signing_key_from_jwt(token).key
        claims = jwt.decode(token, key, algorithms=["RS256"], audience=CONFIG.access_aud,
                            issuer=f"https://{CONFIG.access_team_domain}")
    except Exception:
        return None
    return (claims.get("email") or "").strip().lower() or None


def current_user(request: Request) -> dict:
    with db.tx() as cur:
        if CONFIG.auth_mode == "header":
            email = _access_email(request)
            u = db.one(cur, "select * from users where email = %s and active", email) if email else None
        else:
            raw = request.headers.get("X-Acting-As") or request.query_params.get("as")
            u = db.one(cur, "select * from users where id = %s and active", int(raw)) if raw and raw.isdigit() else None
            if u is None:
                # No choice made yet: the least-privileged view, never company money.
                u = db.one(cur, "select * from users where role = 'sdr' and active order by id limit 1")
    if u is None:
        raise HTTPException(401, "Sign in to use the desk.")
    return u


def money(u: dict) -> bool:
    return u["role"] in ("revops", "manager")


def need(u: dict, *roles: str) -> None:
    if u["role"] not in roles:
        raise HTTPException(403, "Your role cannot do this.")


def writer(request: Request, u: dict = Depends(current_user)) -> dict:
    rate_limit(request)
    # A cross-site form cannot send a JSON content type, so every write must; the web app always does.
    if not request.headers.get("content-type", "").startswith("application/json"):
        raise HTTPException(415, "Writes take JSON.")
    if CONFIG.write_key and CONFIG.auth_mode == "demo" and not CONFIG.public_demo \
            and request.headers.get("X-Write-Key") != CONFIG.write_key:
        raise HTTPException(403, "This desk needs its write key for changes.")
    return u


def _fail(exc: Exception) -> HTTPException:
    if isinstance(exc, PermissionError):
        return HTTPException(403, str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(422, str(exc).splitlines()[0])
    log.warning("write refused: %s", type(exc).__name__)
    return HTTPException(422, "That could not be saved.")


# ---------------------------------------------------------------- reads

@app.get("/api/health")
def health() -> dict:
    with db.tx() as cur:
        backlog = db.val(cur, "select count(*) from jobs where status = 'queued' and run_at < app_now() - interval '15 minutes'")
        dead = db.val(cur, "select count(*) from jobs where status = 'dead'")
        now = db.val(cur, "select app_now()")
    return {"ok": backlog < 50 and dead == 0, "now": now, "job_backlog": backlog, "dead_jobs": dead,
            "mode": CONFIG.mode, "public_demo": CONFIG.public_demo}


@app.get("/api/me")
def me(u: dict = Depends(current_user)) -> dict:
    with db.tx() as cur:
        users = db.all(cur, "select id, name, role from users where active order by case role when 'revops' then 0 "
                            "when 'manager' then 1 when 'sdr' then 2 else 3 end, name") if CONFIG.auth_mode == "demo" else []
        counts = {"changes": db.val(cur, "select count(*) from change_proposals where status = 'open'")}
        now = db.val(cur, "select app_now()")
        sim = db.val(cur, "select enabled from sim_clock")
    return {"user": {k: u[k] for k in ("id", "name", "role")}, "users": users, "counts": counts, "money": money(u),
            "now": now, "simulated": sim, "public_demo": CONFIG.public_demo, "seller": CONFIG.seller}


@app.get("/api/market")
def market(by: str = "segment", u: dict = Depends(current_user)) -> dict:
    need(u, "revops", "manager")
    with db.tx() as cur:
        return views.market(cur, by if by in ("segment", "region_group") else "segment", money(u))


@app.get("/api/segments/{key}")
def segment(key: str, u: dict = Depends(current_user)) -> dict:
    # SDRs and AEs read a segment's why-they-buy on My book; money is stripped for them.
    with db.tx() as cur:
        out = views.segment(cur, key, money(u))
    if out is None:
        raise HTTPException(404, "No such segment.")
    return out


@app.get("/api/evidence")
def evidence_page(u: dict = Depends(current_user)) -> dict:
    need(u, "revops", "manager")
    with db.tx() as cur:
        return views.evidence(cur, money(u))


@app.get("/api/findings/{fid}")
def finding(fid: int, u: dict = Depends(current_user)) -> dict:
    need(u, "revops", "manager")
    with db.tx() as cur:
        out = views.finding(cur, fid, money(u))
    if out is None:
        raise HTTPException(404, "No such finding.")
    return out


@app.get("/api/profile")
def profile(u: dict = Depends(current_user)) -> dict:
    need(u, "revops", "manager")
    with db.tx() as cur:
        return views.profile(cur, u)


@app.get("/api/profile/versions/{vid}")
def profile_version(vid: int, u: dict = Depends(current_user)) -> dict:
    need(u, "revops", "manager")
    with db.tx() as cur:
        out = views.version(cur, vid, u)
    if out is None:
        raise HTTPException(404, "No such version.")
    return out


@app.get("/api/profile/versions/{vid}/moves")
def moves(vid: int, u: dict = Depends(current_user)) -> dict:
    need(u, "revops", "manager")
    with db.tx() as cur:
        cur.execute("set transaction read only")
        pub = db.val(cur, "select id from icp_versions where status = 'published'")
        return fit.what_moves(cur, vid, pub) | {"backtest": fit.backtest(cur, vid),
                                                 "backtest_published": fit.backtest(cur, pub)}


@app.get("/api/accounts")
def accounts(q: str = "", tier: str = "", segment: str = "", owner: str = "", page: int = 1, region: str = "",
             u: dict = Depends(current_user)) -> dict:
    with db.tx() as cur:
        return views.accounts(cur, u, q=q[:80], tier=tier, segment=segment, owner=owner, page=max(1, min(page, 1000)),
                              region=region[:40])


@app.get("/api/companies/{cid}")
def company(cid: int, u: dict = Depends(current_user)) -> dict:
    with db.tx() as cur:
        out = views.company(cur, cid, u)
    if out is None:
        raise HTTPException(404, "No such company.")
    return out


@app.get("/api/territories")
def territories_page(plan: int | None = None, u: dict = Depends(current_user)) -> dict:
    need(u, "revops", "manager")
    with db.tx() as cur:
        return views.territories(cur, plan, money(u))


@app.get("/api/people/{uid}")
def person(uid: int, u: dict = Depends(current_user)) -> dict:
    if u["role"] in ("sdr", "ae") and uid != u["id"]:
        raise HTTPException(403, "You can see your own book.")
    with db.tx() as cur:
        out = views.person(cur, uid, money(u))
    if out is None:
        raise HTTPException(404, "No such person.")
    return out


@app.get("/api/moves/{plan}/{cid}")
def plan_move(plan: int, cid: int, u: dict = Depends(current_user)) -> dict:
    need(u, "revops", "manager")
    with db.tx() as cur:
        out = views.plan_move(cur, plan, cid)
    if out is None:
        raise HTTPException(404, "No such assignment.")
    return out


@app.get("/api/tests")
def tests_page(u: dict = Depends(current_user)) -> dict:
    need(u, "revops", "manager")
    with db.tx() as cur:
        return views.tests(cur)


@app.get("/api/tests/{tid}")
def test(tid: int, u: dict = Depends(current_user)) -> dict:
    need(u, "revops", "manager")
    with db.tx() as cur:
        out = views.test(cur, tid)
    if out is None:
        raise HTTPException(404, "No such test.")
    return out


@app.get("/api/changes")
def changes(u: dict = Depends(current_user)) -> dict:
    need(u, "revops", "manager")
    with db.tx() as cur:
        return views.changes(cur)


@app.get("/api/proposals/{pid}")
def proposal(pid: int, u: dict = Depends(current_user)) -> dict:
    need(u, "revops", "manager")
    with db.tx() as cur:
        out = views.proposal(cur, pid)
    if out is None:
        raise HTTPException(404, "No such proposal.")
    return out


@app.get("/api/handoffs")
def handoffs(u: dict = Depends(current_user)) -> dict:
    need(u, "revops", "manager")
    with db.tx() as cur:
        return views.handoffs(cur, money(u))


@app.get("/api/books/{bid}")
def book(bid: int, u: dict = Depends(current_user)) -> dict:
    need(u, "revops", "manager")
    with db.tx() as cur:
        out = views.book(cur, bid, money(u))
    if out is None:
        raise HTTPException(404, "No such book.")
    return out


@app.get("/api/books/{bid}/files/{path}")
def book_file(bid: int, path: str, u: dict = Depends(current_user)) -> Response:
    need(u, "revops", "manager")
    with db.tx() as cur:
        f = db.one(cur, "select bytes from target_book_files where book = %s and path = %s", bid, path)
    if not f:
        raise HTTPException(404, "No such file.")
    kind = {"csv": "text/csv", "json": "application/json", "md": "text/markdown"}.get(path.rsplit(".", 1)[-1], "text/plain")
    return Response(bytes(f["bytes"]), media_type=kind + "; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="book-{bid}-{path}"'})


@app.get("/api/handoffs/preview/{vid}")
def preview(vid: int, u: dict = Depends(current_user)) -> dict:
    need(u, "revops", "manager")
    with db.tx() as cur:
        return handoff.preview(cur, vid)


@app.get("/api/handoffs/preview/{vid}/icp.json")
def preview_file(vid: int, u: dict = Depends(current_user)) -> Response:
    need(u, "revops", "manager")
    with db.tx() as cur:
        p = handoff.preview(cur, vid)
    return Response(json.dumps(p["icp"], indent=2) + "\n", media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="icp-v{p["version"]}-preview.json"'})


@app.get("/api/sources")
def sources(u: dict = Depends(current_user)) -> dict:
    need(u, "revops", "manager")
    with db.tx() as cur:
        return views.sources(cur, money(u))


@app.get("/api/sources/{key}")
def source(key: str, u: dict = Depends(current_user)) -> dict:
    need(u, "revops", "manager")
    with db.tx() as cur:
        out = views.source(cur, key, money(u))
    if out is None:
        raise HTTPException(404, "No such source.")
    return out


@app.get("/api/mybook")
def mybook(u: dict = Depends(current_user)) -> dict:
    with db.tx() as cur:
        return views.mybook(cur, u)


@app.get("/api/settings")
def settings_page(u: dict = Depends(current_user)) -> dict:
    need(u, "revops", "manager")
    with db.tx() as cur:
        return views.settings(cur)


# ---------------------------------------------------------------- writes

class Publish(BaseModel):
    pass


@app.post("/api/profile/versions/{vid}/publish")
def publish(vid: int, u: dict = Depends(writer)) -> dict:
    try:
        with db.tx() as cur:
            profiles.publish(cur, vid, u, rescore_now=True)
            from .. import sizing
            sizing.run(cur)
    except Exception as exc:
        raise _fail(exc) from exc
    return {"ok": True}


class Ids(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=50)
    note: str | None = Field(None, max_length=500)


@app.post("/api/proposals/draft")
def proposals_draft(body: Ids, u: dict = Depends(writer)) -> dict:
    try:
        with db.tx() as cur:
            vid = proposals.make_draft(cur, body.ids, u, body.note)
    except Exception as exc:
        raise _fail(exc) from exc
    return {"version": vid}


class Reason(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


@app.post("/api/proposals/{pid}/dismiss")
def proposal_dismiss(pid: int, body: Reason, u: dict = Depends(writer)) -> dict:
    try:
        with db.tx() as cur:
            proposals.dismiss(cur, pid, u, body.reason)
    except Exception as exc:
        raise _fail(exc) from exc
    return {"ok": True}


@app.post("/api/plans/{pid}/activate")
def activate(pid: int, u: dict = Depends(writer)) -> dict:
    try:
        with db.tx() as cur:
            territories.activate(cur, pid, u)
    except Exception as exc:
        raise _fail(exc) from exc
    return {"ok": True}


class Move(BaseModel):
    company: int
    to: int
    note: str = Field(min_length=3, max_length=500)


@app.post("/api/plans/{pid}/move")
def move(pid: int, body: Move, u: dict = Depends(writer)) -> dict:
    try:
        with db.tx() as cur:
            territories.manual_move(cur, pid, body.company, body.to, body.note, u)
    except Exception as exc:
        raise _fail(exc) from exc
    return {"ok": True}


class NewTest(BaseModel):
    segment: str = Field(max_length=40)
    hypothesis: str = Field(min_length=5, max_length=300)


@app.post("/api/tests")
def new_test(body: NewTest, u: dict = Depends(writer)) -> dict:
    if body.segment not in C.SEGMENT_LABEL:
        raise HTTPException(422, "No such segment.")
    try:
        with db.tx() as cur:
            tid = tests_seg.create_draft(cur, body.segment, body.hypothesis, u)
    except Exception as exc:
        raise _fail(exc) from exc
    return {"id": tid}


@app.post("/api/tests/{tid}/start")
def start_test(tid: int, u: dict = Depends(writer)) -> dict:
    need(u, "revops")
    try:
        with db.tx() as cur:
            return tests_seg.start(cur, tid, u)
    except Exception as exc:
        raise _fail(exc) from exc


class Decision(BaseModel):
    decision: str
    note: str | None = Field(None, max_length=500)


@app.post("/api/tests/{tid}/decide")
def decide_test(tid: int, body: Decision, u: dict = Depends(writer)) -> dict:
    try:
        with db.tx() as cur:
            tests_seg.decide(cur, tid, body.decision, u, body.note)
    except Exception as exc:
        raise _fail(exc) from exc
    return {"ok": True}


class NewBook(BaseModel):
    destination: str


@app.post("/api/books")
def new_book(body: NewBook, u: dict = Depends(writer)) -> dict:
    if body.destination not in ("account_desk", "events_desk"):
        raise HTTPException(422, "Account Desk or Events Desk.")
    try:
        with db.tx() as cur:
            return {"id": handoff.build_book(cur, body.destination, u)}
    except Exception as exc:
        raise _fail(exc) from exc


class SettingValue(BaseModel):
    value: float | dict[str, float] = Field(...)


@app.post("/api/settings/{key}")
def set_setting(key: str, body: SettingValue, u: dict = Depends(writer)) -> dict:
    need(u, "revops")
    with db.tx() as cur:
        current = db.val(cur, "select value from settings where key = %s", key)
        if current is None:
            raise HTTPException(404, "No such setting.")
        if type(current) is not type(body.value) and not (isinstance(current, (int, float)) and isinstance(body.value, (int, float))):
            raise HTTPException(422, "That setting takes a different kind of value.")
        if isinstance(body.value, dict) and set(body.value) != set(current):
            raise HTTPException(422, "That setting takes the same keys it has.")
        if isinstance(body.value, (int, float)) and not (0 <= body.value <= 100_000):
            raise HTTPException(422, "Out of range.")
        db.run(cur, "update settings set value = %s, updated_at = app_now(), updated_by = %s where key = %s",
               db.J(body.value), u["id"], key)
        from .. import audit
        audit.log(cur, u["name"], "setting_changed", "setting", None, {"key": key}, actor_id=u["id"])
    return {"ok": True}


@app.post("/api/users/{uid}/erase")
def erase_user(uid: int, u: dict = Depends(writer)) -> dict:
    if CONFIG.public_demo:
        raise HTTPException(403, "The public demo keeps its invented team.")
    from .. import erasure
    try:
        with db.tx() as cur:
            return erasure.erase_user(cur, uid, u)
    except Exception as exc:
        raise _fail(exc) from exc


@app.post("/api/companies/{cid}/erase-notes")
def erase_notes(cid: int, u: dict = Depends(writer)) -> dict:
    if CONFIG.public_demo:
        raise HTTPException(403, "The public demo keeps its invented notes.")
    from .. import erasure
    try:
        with db.tx() as cur:
            return erasure.erase_company_notes(cur, cid, u)
    except Exception as exc:
        raise _fail(exc) from exc


@app.post("/api/evidence/run")
def run_evidence(u: dict = Depends(writer)) -> dict:
    need(u, "revops")
    from .. import proposals, sizing
    with db.tx() as cur:
        rid = evidence.run(cur)
        sizing.run(cur)
        proposals.generate(cur)
    return {"run": rid}


# ---------------------------------------------------------------- results back from the other desks

MAX_RESULT_ROWS = 50_000


class ResultRow(BaseModel):
    domain: str = Field(max_length=255)
    period_start: date
    period_end: date
    worked: bool = True
    held_back: bool = False
    test: int | None = None
    meetings: int = Field(0, ge=0, le=1000)
    opportunities: int = Field(0, ge=0, le=1000)
    won: int = Field(0, ge=0, le=1000)
    lost: int = Field(0, ge=0, le=1000)
    pipeline_cents: int = Field(0, ge=0)


class Results(BaseModel):
    destination: Literal["account_desk", "events_desk"] | None = None
    rows: list[ResultRow] = Field(max_length=MAX_RESULT_ROWS)


@app.post("/api/results")
async def results_webhook(request: Request) -> dict:
    """Results by account from Account Desk or Events Desk, or from the CRM for a test's held-back group, signed:
    X-Signature = hex HMAC SHA-256 of "<timestamp>.<body>" with WEBHOOK_SECRET, X-Timestamp within five minutes. A
    delivery is read once. The public demo takes no uploads."""
    if CONFIG.public_demo:
        raise HTTPException(403, "The public demo takes no uploads.")
    rate_limit(request, limit=30)
    body = await request.body()
    if len(body) > 5 * MAX_BODY:
        raise HTTPException(413, "Too large.")
    ts = request.headers.get("X-Timestamp", "")
    sig = request.headers.get("X-Signature", "")
    if not ts.isdigit() or abs(time.time() - int(ts)) > 300:
        raise HTTPException(401, "Stale or missing timestamp.")
    good = hmac.new(CONFIG.webhook_secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(good, sig):
        raise HTTPException(401, "Bad signature.")
    try:
        data = Results.model_validate_json(body)
    except Exception as exc:
        raise HTTPException(422, "Rows do not match the contract.") from exc
    with db.tx() as cur:
        if not db.one(cur, "insert into webhook_deliveries (signature) values (%s) on conflict do nothing returning 1", sig):
            raise HTTPException(409, "Already read.")
        return {"read": read_results(cur, data.destination, [r.model_dump() for r in data.rows])}


def read_results(cur, destination: str | None, rows: list[dict]) -> int:
    """Shared by the webhook and the CSV import. Held-back rows carry no destination; a test id must be one the
    company belongs to."""
    n = 0
    for r in rows:
        if r["period_end"] < r["period_start"] or (r["worked"] and r["held_back"]):
            continue
        cid = db.val(cur, "select id from companies where primary_domain = lower(%s)", r["domain"])
        if not cid:
            continue
        test = r.get("test")
        if test and not db.val(cur, "select 1 from segment_test_members where test = %s and company = %s", test, cid):
            test = None
        db.run(cur, """insert into desk_results (company, destination, period_start, period_end, worked, held_back, test,
                       meetings, opportunities, won, lost, pipeline_cents, read_at)
                       values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,app_now())""",
               cid, None if r["held_back"] else destination, r["period_start"], r["period_end"], r["worked"], r["held_back"],
               test, r["meetings"], r["opportunities"], r["won"], r["lost"], r["pipeline_cents"])
        n += 1
    return n


# ---------------------------------------------------------------- the web app

if WEB.exists():
    app.mount("/assets", StaticFiles(directory=WEB / "assets"), name="assets")


@app.get("/{path:path}", include_in_schema=False)
def spa(path: str):
    if path.startswith("api/"):
        raise HTTPException(404, "No such endpoint.")
    index = WEB / "index.html"
    if index.exists():
        return FileResponse(index)
    return HTMLResponse("<p>Build the web app: <code>make web</code></p>")


def start_worker() -> None:
    db.pool()
    if not CONFIG.worker_inline:
        return

    def loop() -> None:
        while True:
            try:
                jobs.run_ready()
            except Exception:
                log.exception("worker tick failed")
            time.sleep(3)

    threading.Thread(target=loop, daemon=True, name="worker").start()


