"""Target books for the other desks (docs/SPEC.md 9.2 and 15.7 to 15.8).

Account Desk gets accounts.csv in its exact columns and icp.json in its shape, compiled down to the fields it has.
Events Desk gets icp.md in the headings and phrasing of its sample ICP document. Nothing is pushed anywhere: files
are versioned per destination and downloaded."""
from __future__ import annotations

import csv
import hashlib
import io
import json

from . import audit, db
from . import catalog as C
from .db import J
from .evidence import rule_label

AD_OPS = {"in", "between", "has_any", "has_none"}


def compile_for_account_desk(rules: dict) -> tuple[dict, list[dict]]:
    """Account Desk's ICP shape, using only the fields it has. `eq` becomes `in` with one value. Rules on any other
    field are returned as dropped, with the reason."""
    out = {"factors": [], "penalties": [], "excludes": [], "tiers": dict(rules["tiers"])}
    dropped = []
    for kind in ("factors", "penalties", "excludes"):
        for r in rules.get(kind, []):
            if r["field"] not in C.AD_FIELDS:
                dropped.append({"kind": kind, "key": r["key"], "rule": rule_label(r),
                                "why": f"Account Desk has no {C.FIELD_LABEL.get(r['field'], r['field']).lower()} field"})
                continue
            op, value = r["op"], r["value"]
            if op == "eq":
                op, value = "in", [value]
            if op not in AD_OPS:
                dropped.append({"kind": kind, "key": r["key"], "rule": rule_label(r), "why": f"Account Desk has no {op} operator"})
                continue
            item = {"key": r["key"], "field": r["field"], "op": op, "value": value}
            if kind == "excludes":
                item = {"field": r["field"], "op": op, "value": value, "reason": r["reason"]}
            else:
                item["weight"] = r["weight"]
            out[kind].append(item)
    return out, dropped


def book_rows(cur, plan_id: int, version_id: int) -> list[dict]:
    """Tier A and B companies assigned in the plan plus the worked group of a running test; never a held-back member,
    a sole trader or a customer."""
    return db.all(cur, """
        with running as (
            select m.company from segment_test_members m join segment_tests t on t.id = m.test
            where m.grp = 'worked' and t.status = 'running'),
        held as (
            select m.company from segment_test_members m join segment_tests t on t.id = m.test
            where m.grp = 'held_back' and t.status = 'running'),
        chosen as (
            select a.company, a.owner from assignments a where a.plan = %s
            union select r.company, null from running r
            where not exists (select 1 from assignments a where a.plan = %s and a.company = r.company))
        select c.id, c.name, c.primary_domain, c.country, c.lifecycle, c.crm_id, p.primary_domain as parent_domain,
               f.tier, f.segment, u.email as owner_email, ch.owner,
               c.id in (select company from running) as test_member
        from chosen ch join companies c on c.id = ch.company
        join account_fit f on f.company = c.id and f.icp_version = %s
        left join companies p on p.id = c.parent_id left join users u on u.id = ch.owner
        where f.tier in ('A','B') and c.lifecycle = 'prospect' and not c.sole_trader
          and c.id not in (select company from held)
          -- on the book's own date: no deal open then, and not a customer then
          and not exists (select 1 from deals d where d.company = c.id and d.created_at <= app_now()
                          and (d.closed_at is null or d.closed_at > app_now()))
          and not exists (select 1 from customers k where k.company = c.id and k.started_on <= app_now()::date
                          and (k.churned_on is null or k.churned_on > app_now()::date))
        order by c.name""", plan_id, plan_id, version_id)


def exportable_values(cur, ids: list[int]) -> dict[int, dict]:
    """Vendor, CRM or person values only, never a model-read one, and never from a source whose licence forbids
    redistribution: such a cell is left blank."""
    out: dict[int, dict] = {i: {} for i in ids}
    for r in db.all(cur, """
        select f.company, f.field, f.value from field_values f join sources s on s.key = f.source
        where f.company = any(%s) and f.source <> 'model' and not s.no_redistribution
          and f.field in ('industry','employees','revenue_band','tech','pricing_model')""", ids):
        out[r["company"]][r["field"]] = r["value"]
    return out


def _cell(v) -> str:
    """A spreadsheet runs a cell that starts with = + - or @ as a formula; such a value is written with a leading quote."""
    t = "" if v is None else str(v)
    return "'" + t if t[:1] in ("=", "+", "-", "@") else t


def accounts_csv(cur, rows: list[dict]) -> tuple[bytes, int]:
    vals = exportable_values(cur, [r["id"] for r in rows])
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(C.AD_COLUMNS)
    blanks = 0
    for r in rows:
        v = vals[r["id"]]
        blanks += sum(1 for k in ("industry", "employees", "revenue_band") if k not in v)
        w.writerow([_cell(x) for x in (r["name"], r["primary_domain"], v.get("industry", ""), v.get("employees", ""), r["country"],
                    v.get("revenue_band", ""), ";".join(v.get("tech") or []), r["lifecycle"], r["owner_email"] or "",
                    r["crm_id"] or "", r["parent_domain"] or "")])
    return buf.getvalue().encode(), blanks


def _tier_word(tier: str) -> str:
    return {"A": "tier 1", "B": "tier 2"}.get(tier, "tier 3")


def events_desk_md(cur, version: dict) -> bytes:
    """Lumen Ledger's ICP in Events Desk's format (samples/orrery-icp.md). A is tier 1, B is tier 2, C and X are tier 3."""
    rules = version["rules"]
    owner = db.one(cur, "select name from users where id = %s", version["author"])
    size = next((f for f in rules["factors"] if f["field"] == "employees"), None)
    ind = next((f for f in rules["factors"] if f["field"] == "industry"), None)
    run = db.val(cur, "select max(id) from analysis_runs")
    lines = [f"# {C.SELLER}: who we sell to", "", f"Seller: {C.SELLER}", f"Owner: {owner['name']}, Revenue Operations",
             f"Last reviewed: {str(version['published_at'] or version['created_at'])[:10]}", "",
             f"(Fictional document written by Market Desk from profile version {version['number']}. {C.SELLER} and every "
             "company named below are made up.)", "", "## The short version", "",
             f"{C.SELLER} sells usage-based billing and revenue recognition software to B2B software companies.",
             "", "## Size", ""]
    if size:
        lo, hi = size["value"]
        lines.append(f"A company with {lo:,} to {hi:,} employees is the right size.")
    pen = [p for p in rules.get("penalties", []) if p["field"] == "employees"]
    for p in pen:
        lines.append(f"A company with {p['value'][0]:,} to {p['value'][1]:,} employees scores lower.")
    lines += ["", "## Where we win", ""]
    def verdict(rule: dict) -> str | None:
        ev = (rule.get("evidence") or {}).get("finding_id")
        return db.val(cur, "select verdict from findings where id = %s", ev) if ev else None

    if ind:
        word = "win more often than the rest" if verdict(ind) == "clear_higher" else "are the industries the profile scores"
        lines.append(f"{', '.join(ind['value'][:-1])} and {ind['value'][-1]} {word}.")
    for f in rules["factors"]:
        if f["field"] == "pricing_model":
            v = rule_label(f).split(": ", 1)[1].lower()
            lines.append(f"Companies with {v} pricing " + ("win more often." if verdict(f) == "clear_higher" else "score higher."))
    heavy = sorted(rules["factors"], key=lambda f: -f["weight"])
    t1 = ", ".join(rule_label(f).lower() for f in heavy[:3])
    lines += ["", "## How we tier a company", "",
              f"- Tier 1: scores {rules['tiers']['A']} or more out of 100; the biggest weights are {t1}.",
              f"- Tier 2: scores {rules['tiers']['B']} to {rules['tiers']['A'] - 1}, usually {rule_label(heavy[0]).lower()} "
              f"and {rule_label(heavy[1]).lower()} without the rest.",
              "- Tier 3: everyone else, and every company we exclude or already sell to.", "",
              "## Who we talk to", ""]
    roles = db.all(cur, """select persona, sum(share_as_signer * n_won_deals) / sum(n_won_deals) as s
                           from segment_roles group by persona order by s desc""")
    signers = [C.PERSONAS[r["persona"]] for r in roles[:2]]
    others = [C.PERSONAS[r["persona"]] for r in roles[2:5]]
    lines.append(f"The buyer is the {signers[0].lower()}" + (f" or the {signers[1].lower()}." if len(signers) > 1 else "."))
    if others:
        lines.append(f"{', '.join(others)} take part in the decision.")
    lines += ["", "## Kinds of company we see", "", ", ".join(C.INDUSTRIES) + ".", "", "## Who we skip", ""]
    for ex in rules.get("excludes", []):
        lines.append(f"{rule_label(ex).split(': ', 1)[1]}: {ex['reason'].lower()}.")
    lines.append(f"{', '.join(C.COMPETITORS)} are competitors and never get contacted. Current customers belong to the "
                 "account team.")
    lines += ["", "## Companies we know", ""]
    # Named examples: never a sole trader, and only facts a vendor, the CRM or a person gave, from a source that may
    # be passed on (the same rule as the Account Desk file).
    known = db.all(cur, """
        select c.id, c.name, f.tier from companies c
        join account_fit f on f.company = c.id and f.icp_version = %s
        where f.judged and f.tier in ('A','B') and c.lifecycle = 'prospect' and not c.sole_trader
        order by f.tier, md5(c.primary_domain) limit 40""", version["id"])
    vals = exportable_values(cur, [k["id"] for k in known])
    known = [k | {"industry": vals[k["id"]].get("industry"), "employees": vals[k["id"]].get("employees")} for k in known]
    known = [k for k in known if k["industry"] and k["employees"]][:5]
    for k in known:
        lines.append(f"- {k['name']}: {_tier_word(k['tier'])}. {k['industry']}, about {k['employees']:,} people.")
    lines += ["", "## Looks right, is not", ""]  # Events Desk's parser reads this heading by name
    look = db.all(cur, """
        select c.id, c.name, f.tier, f.excluded from companies c
        join account_fit f on f.company = c.id and f.icp_version = %s
        where f.judged and f.tier in ('C','X') and c.industry = any(%s) and c.lifecycle = 'prospect' and not c.sole_trader
        order by f.tier desc, md5(c.primary_domain) limit 40""", version["id"], C.PROFILE_INDUSTRIES)
    vals = exportable_values(cur, [k["id"] for k in look])
    look = [k | {"industry": vals[k["id"]].get("industry"), "employees": vals[k["id"]].get("employees")} for k in look]
    look = [k for k in look if k["industry"] and k["employees"]][:4]
    for k in look:
        why = k["excluded"] or ("outside the size range" if size and not (size["value"][0] <= k["employees"] <= size["value"][1])
                                else "it misses too many rules")
        lines.append(f"- {k['name']}: {_tier_word(k['tier'])}. {k['industry']}, but {why[0].lower() + why[1:]}.")
    _ = run
    return ("\n".join(lines) + "\n").encode()


def _diff(cur, destination: str, rows: list[dict]) -> dict:
    prev = db.one(cur, "select id from target_books where destination = %s order by version desc limit 1", destination)
    if not prev:
        return {"added": len(rows), "removed": 0, "tier_moved": 0, "owner_moved": 0, "previous": None}
    old = {r["company"]: r for r in db.all(cur, "select * from target_book_rows where book = %s", prev["id"])}
    new = {r["id"]: r for r in rows}
    return {"previous": prev["id"], "added": len(set(new) - set(old)), "removed": len(set(old) - set(new)),
            "tier_moved": sum(1 for k in set(new) & set(old) if new[k]["tier"] != old[k]["tier"]),
            "owner_moved": sum(1 for k in set(new) & set(old) if new[k]["owner"] != old[k]["owner"])}


def build_book(cur, destination: str, by: dict, *, at=None) -> int:
    if by["role"] != "revops":
        raise PermissionError("RevOps creates target books.")
    version = db.one(cur, "select * from icp_versions where status = 'published'")
    plan = db.val(cur, "select id from territory_plans where status = 'active'")
    if not plan:
        raise ValueError("A book needs an active plan.")
    n = (db.val(cur, "select max(version) from target_books where destination = %s", destination) or 0) + 1
    rows = book_rows(cur, plan, version["id"]) if destination == "account_desk" else []
    files: dict[str, bytes] = {}
    dropped: list[dict] = []
    if destination == "account_desk":
        icp, dropped = compile_for_account_desk(version["rules"])
        files["accounts.csv"], _blanks = accounts_csv(cur, rows)
        files["icp.json"] = (json.dumps(icp, indent=2) + "\n").encode()
    else:
        files["icp.md"] = events_desk_md(cur, version)
    diff = _diff(cur, destination, rows)
    digest = hashlib.sha256(b"".join(files[k] for k in sorted(files))).hexdigest()
    bid = db.val(cur, """insert into target_books (version, icp_version, plan, destination, created_at, created_by,
                         file_sha256, rows, dropped_rules, diff) values (%s,%s,%s,%s,coalesce(%s, app_now()),%s,%s,%s,%s,%s)
                         returning id""", n, version["id"], plan, destination, at, by["id"], digest, len(rows),
                  J(dropped), J(diff))
    for path, data in files.items():
        db.run(cur, "insert into target_book_files (book, path, bytes) values (%s,%s,%s)", bid, path, data)
    if rows:
        with cur.copy("copy target_book_rows (book, company, tier, owner, segment, test_member) from stdin") as cp:
            for r in rows:
                cp.write_row((bid, r["id"], r["tier"], r["owner"], r["segment"], r["test_member"]))
    audit.log(cur, by["name"], "book_created", "book", bid, {"destination": destination, "rows": len(rows)}, actor_id=by["id"])
    return bid


def preview(cur, version_id: int) -> dict:
    """What a book from any version (a draft included) would carry to Account Desk: the compiled ICP and the rules
    it cannot carry. Not versioned."""
    v = db.one(cur, "select * from icp_versions where id = %s", version_id)
    icp, dropped = compile_for_account_desk(v["rules"])
    return {"version": v["number"], "status": v["status"], "icp": icp, "dropped_rules": dropped}
