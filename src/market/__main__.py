"""Command line: python -m market <command>

  migrate              apply migrations
  demo                 rebuild the demo database from its fixed seed (about 18,000 companies)
  serve                run the web app and API (and the worker in-process)
  world-export DIR     write the shared world export (companies, people, tiers) to DIR
  import-results FILE  read results by account from a CSV (domain, period_start, period_end, worked, held_back,
                       test, meetings, opportunities, won, lost, pipeline_cents; at most 5 MB and 50,000 rows)
  mcp                  read-only MCP server on stdio
  crm-sync             send the active plan's books to the CRM now (CRM=crmdesk), and print what it refused
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time

from . import db
from .config import CONFIG


def reset() -> None:
    import psycopg
    with psycopg.connect(CONFIG.database_url, autocommit=True) as conn:
        conn.execute("drop schema public cascade")
        conn.execute("create schema public")
    db.close()
    db.migrate()


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    cmd = argv[1] if len(argv) > 1 else "serve"
    CONFIG.validate()
    if cmd == "migrate":
        print(db.migrate())
    elif cmd == "demo":
        from .sim import story
        t0 = time.time()
        reset()
        info = story.build_demo(n_companies=int(os.environ.get("DEMO_COMPANIES", "18000")))
        print(json.dumps({"world": info, "seconds": round(time.time() - t0, 1)}, default=str))
        db.close()
    elif cmd == "crm-sync":
        from . import crm
        if not crm.enabled():
            raise SystemExit("No CRM is set: CRM=crmdesk with CRM_DESK_URL and CRM_DESK_KEY.")
        with db.tx() as cur:
            plan = db.val(cur, "select id from territory_plans where status = 'active'")
            crm.queue_plan(cur, plan)
        sent = 0
        while True:
            try:
                with db.tx() as cur:
                    row = db.one(cur, "select * from crm_outbox where status = 'queued' order by id limit 1 for update skip locked")
                    if row is None:
                        break
                    crm.deliver(cur, row)
                    sent += 1
            except crm.CrmDown as exc:
                if exc.retry_after is None:
                    raise
                time.sleep(exc.retry_after)  # CRM Desk asked to wait; the row is still queued
        with db.tx() as cur:
            print(json.dumps({"requests": sent, **crm.summary(cur)}, default=str, indent=1))
        db.close()
    elif cmd == "world-export":
        from . import world_export
        print(json.dumps(world_export.export(argv[2] if len(argv) > 2 else "world"), indent=1))
    elif cmd == "import-results":
        import csv
        from datetime import date as _d

        from .api.app import ResultRow, read_results
        path = argv[2]
        if os.path.getsize(path) > 5 * 1024 * 1024:
            raise SystemExit("Over 5 MB. Split the file.")
        with open(path, encoding="utf-8-sig") as f:
            raw = list(csv.DictReader(f))
        if len(raw) > 50_000:
            raise SystemExit("Over 50,000 rows. Split the file.")
        dest = argv[3] if len(argv) > 3 else "account_desk"
        rows = []
        for r in raw:
            r = {k: v for k, v in r.items() if v not in ("", None)}
            for k in ("worked", "held_back"):
                if k in r:
                    r[k] = r[k].strip().lower() in ("1", "true", "yes")
            rows.append(ResultRow.model_validate(r).model_dump())
        with db.tx() as cur:
            print(json.dumps({"read": read_results(cur, dest, rows)}))
        _ = _d
    elif cmd == "mcp":
        logging.getLogger().setLevel(logging.WARNING)
        from . import mcp_server
        mcp_server.main()
    elif cmd == "serve":
        import uvicorn
        # Behind Render's proxy the client address is in X-Forwarded-For; trust it so the rate limit is per visitor.
        uvicorn.run("market.api.app:app", host=os.environ.get("HOST", "127.0.0.1"),
                    port=int(os.environ.get("PORT", "8800")), log_level="info", proxy_headers=True,
                    forwarded_allow_ips=os.environ.get("FORWARDED_ALLOW_IPS", "*" if CONFIG.public_demo else "127.0.0.1"))
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
