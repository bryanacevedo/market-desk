"""Sizing per segment and per region group (docs/SPEC.md 8 and 15.1 to 15.2). Every figure is a range of scenario
bounds: the low end multiplies the low ends of its parts, the high end the high ends. No single TAM number exists."""
from __future__ import annotations

from collections import Counter, defaultdict

from . import catalog as C
from . import db, stats, territories
from .db import J


def _settings(cur) -> dict:
    return {r["key"]: r["value"] for r in db.all(cur, "select key, value from settings")}


def run(cur) -> int:
    s = _settings(cur)
    k = float(s.get("shrink_k", 20))
    now = db.val(cur, "select app_now()")
    vid = db.val(cur, "select id from icp_versions where status = 'published'")
    plan = db.val(cur, "select id from territory_plans where status = 'active'")
    ev_run = db.val(cur, "select max(id) from analysis_runs")
    # The overall signer: the persona that signs most won deals.
    signer_all = db.val(cur, """select persona from deal_roles r join deals d on d.id = r.deal
                                where r.was_signer and d.outcome = 'won' group by persona order by count(*) desc limit 1""") or "cfo"
    signer_seg = {r["segment"]: r["persona"] for r in db.all(cur, """
        select distinct on (segment) segment, persona from segment_roles order by segment, share_as_signer desc""")}
    comps = db.all(cur, """
        select c.id, c.country, c.region, c.region_group, c.employees, c.industry, f.tier, f.judged, f.segment,
               coalesce(c.sole_trader, false) as sole_trader
        from companies c join account_fit f on f.company = c.id and f.icp_version = %s
        where c.lifecycle <> 'competitor'""", vid)
    reach = defaultdict(dict)
    for r in db.all(cur, "select company, persona, has_named_contact_source from reachability"):
        reach[r["company"]][r["persona"]] = r["has_named_contact_source"]
    public = defaultdict(int)
    public_cells = set()
    for r in db.all(cur, "select country, industry, size_band, companies from public_counts"):
        public[(r["country"], r["industry"], r["size_band"])] = r["companies"]
        public_cells.add((r["country"], r["industry"], r["size_band"]))
    seg_f = {r["value"]: r for r in db.all(cur, "select * from findings where run = %s and trait = 'segment'", ev_run)}
    tot_opps = sum(r["opps"] for r in seg_f.values()) or 1
    tot_wins = sum(r["wins"] for r in seg_f.values())
    overall = tot_wins / tot_opps
    won = db.all(cur, "select d.amount_cents, d.snapshot from deals d where d.kind = 'new' and d.outcome = 'won'")
    from .fit import segment_of
    acv_by_seg = defaultdict(list)
    for d in won:
        acv_by_seg[segment_of({"segments": C.SEGMENTS}, d["snapshot"])].append(d["amount_cents"])
    all_acv = [d["amount_cents"] for d in won]
    # Opportunities per worked account over 12 months, from the desks' results (worked groups only): the segment's own
    # rate from 100 worked accounts up, else the overall rate; with no results at all, the default in settings.
    opp_rows = db.all(cur, """select f.segment, count(*) as n, count(*) filter (where r.opportunities > 0) as k
                              from desk_results r join account_fit f on f.company = r.company and f.icp_version = %s
                              where r.worked and r.period_end > %s::date - 365 group by f.segment""", vid, now)
    opp_n = sum(r["n"] for r in opp_rows)
    opp_k = sum(r["k"] for r in opp_rows)
    default_rate = float(s_get(s, "opp_rate_default", 0.10))

    def opp_basis(seg: str | None) -> tuple[float, float, float, str]:
        row = next((r for r in opp_rows if r["segment"] == seg), None)
        if row and row["n"] >= 100:
            lo, hi = stats.wilson(row["k"], row["n"], conf=0.95)
            return row["k"] / row["n"], lo, hi, "segment"
        if opp_n:
            lo, hi = stats.wilson(opp_k, opp_n, conf=0.95)
            return opp_k / opp_n, lo, hi, "overall"
        return default_rate, default_rate * 0.5, default_rate * 1.5, "assumption"

    opp_rate = opp_basis(None)[0]
    cap_accounts = territories.capacity_accounts(cur, plan) if plan else 0.0
    rid = db.val(cur, "insert into sizing_runs (ran_at, icp_version, plan, settings) values (%s,%s,%s,%s) returning id",
                 now, vid, plan, J({"shrink_k": k, "opp_rate": opp_rate, "capacity_accounts": cap_accounts}))

    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for c in comps:
        groups[("segment", c["segment"])].append(c)
        groups[("region_group", c["region_group"])].append(c)
        groups[("total", "all")].append(c)
    # Capacity is shared by segments in proportion to their tier A and B companies in SAM, so segment rows add up to
    # the total; region rows use the overall signer (SPEC 15.11).
    # Capacity goes to segments and regions in proportion to the tier A and B accounts the active plan owns there: a
    # segment no territory works gets none, and SOM there is zero.
    owned_seg = {r["k"]: r["n"] for r in db.all(cur, """
        select f.segment as k, count(*) as n from assignments a join account_fit f on f.company = a.company and f.icp_version = %s
        where a.plan = %s and f.tier in ('A','B') group by 1""", vid, plan)} if plan else {}
    owned_reg = {r["k"]: r["n"] for r in db.all(cur, """
        select c.region_group as k, count(*) as n from assignments a join companies c on c.id = a.company
        join account_fit f on f.company = a.company and f.icp_version = %s
        where a.plan = %s and f.tier in ('A','B') group by 1""", vid, plan)} if plan else {}
    owned_total = sum(owned_seg.values())
    rows = []
    for (dim, key), cs in groups.items():
        tiers = Counter(c["tier"] if c["judged"] else "NJ" for c in cs)
        judged = [c for c in cs if c["judged"]]
        ab_known = sum(1 for c in judged if c["tier"] in ("A", "B"))
        nj = tiers.get("NJ", 0)
        fit_share = ab_known / len(judged) if judged else 0
        cells = {(c["country"], c["industry"], C.size_band(c["employees"])) for c in cs if c["industry"] and C.size_band(c["employees"])}
        known_cells = [x for x in cells if x in public_cells]
        pub = sum(public[x] for x in known_cells) if known_cells else None
        in_cells = sum(1 for c in cs if (c["country"], c["industry"], C.size_band(c["employees"])) in public_cells)
        coverage = (in_cells / pub) if pub else None
        if dim == "segment" and key in seg_f and seg_f[key]["wins"] >= 15:
            acvs = acv_by_seg[key]
            acv_note = "segment"
        else:
            acvs = all_acv
            acv_note = "overall" if dim == "segment" else "overall"
        p25, p50, p75 = (int(stats.quantile(acvs, q)) for q in (0.25, 0.5, 0.75))
        f = seg_f.get(key) if dim == "segment" else None
        if f:
            wins, opps = f["wins"], f["opps"]
        else:
            wins, opps = tot_wins, tot_opps
        shrunk = (wins + k * overall) / (opps + k)
        wlo, whi = stats.wilson(round(wins + k * overall), round(opps + k), conf=0.95)
        raw_lo, raw_hi = stats.wilson(wins, opps, conf=0.95)
        signer_of = (lambda c: signer_all) if dim == "region_group" or key == "outside" else (lambda c: signer_seg.get(c["segment"], signer_all))
        sam = [c for c in cs if _in_sam(c, reach, signer_of(c))]
        sam_judged = [c for c in sam if c["judged"]]
        sam_ab = sum(1 for c in sam_judged if c["tier"] in ("A", "B"))
        sam_nj = sum(1 for c in sam if not c["judged"])
        sam_fit = sam_ab / len(sam_judged) if sam_judged else 0
        reachable = sum(1 for c in cs if reach[c["id"]].get(signer_of(c), False))
        tam_low, tam_high = ab_known * p25, int((ab_known + nj * fit_share) * p75)
        sam_low, sam_high = sam_ab * p25, int((sam_ab + sam_nj * sam_fit) * p75)
        sam_count = sam_ab
        owned = owned_seg if dim == "segment" else owned_reg
        share = (owned.get(key, 0) / owned_total) if owned_total else 0
        cap = cap_accounts * share if dim != "total" else cap_accounts
        workable = min(sam_count, cap)
        o_rate, o_lo, o_hi, o_from = opp_basis(key if dim == "segment" else None)
        som_low = int(workable * o_lo * wlo * p25)
        som_high = int(min(workable * o_hi * whi * p75, sam_high))
        som_low = min(som_low, som_high)
        rows.append((rid, dim, key, len(cs), tiers.get("A", 0), tiers.get("B", 0), tiers.get("C", 0), tiers.get("X", 0), nj,
                     pub, coverage, reachable, sam_count, round(cap, 1), tam_low, tam_high, min(sam_low, tam_low),
                     min(sam_high, tam_high), som_low, min(som_high, sam_high),
                     J({"p25": p25, "median": p50, "p75": p75, "from": acv_note, "won_deals": len(acvs)}),
                     J({"wins": wins, "opps": opps, "overall": overall, "shrunk": shrunk, "low": wlo, "high": whi,
                        "raw_low": raw_lo, "raw_high": raw_hi, "k": k}),
                     J({"capacity_accounts": round(cap, 1), "opp_rate": o_rate, "opp_low": o_lo, "opp_high": o_hi, "opp_from": o_from,
                        "signer": signer_seg.get(key, signer_all) if dim == "segment" else signer_all})))
    # The whole market's SOM is the sum of its segments', so the two always agree.
    seg_rows = [r for r in rows if r[1] == "segment"]
    rows = [r[:18] + (sum(x[18] for x in seg_rows), min(sum(x[19] for x in seg_rows), r[17])) + r[20:] if r[1] == "total" else r
            for r in rows]
    with cur.copy("""copy segment_sizing (run, dimension, key, universe_count, fit_a, fit_b, fit_c, fit_x, not_judged,
                     public_count, coverage_share, reachable_count, sam_count, capacity_accounts, tam_low, tam_high,
                     sam_low, sam_high, som_low, som_high, acv_basis, win_rate_basis, capacity_basis) from stdin""") as cp:
        for r in rows:
            cp.write_row(r)
    return rid


def s_get(s: dict, key: str, default):
    return s.get(key, default)


def _in_sam(c: dict, reach: dict, signer: str) -> bool:
    return (c["region"] in C.SERVED_REGIONS and c["tier"] != "X" and not c["sole_trader"]
            and bool(reach[c["id"]].get(signer, False)))
