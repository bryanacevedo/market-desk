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
    # Opportunities per worked account over 12 months, from the desks' results (worked groups only).
    opp = db.one(cur, """select count(*) as n, count(*) filter (where opportunities > 0) as k from desk_results
                         where worked and period_end > %s::date - 365""", now)
    opp_rate = (opp["k"] / opp["n"]) if opp and opp["n"] else 0.1
    opp_lo, opp_hi = stats.wilson(opp["k"], opp["n"], conf=0.95) if opp and opp["n"] else (0.05, 0.15)
    cap_accounts = territories.capacity_accounts(cur, plan) if plan else 0.0
    rid = db.val(cur, "insert into sizing_runs (ran_at, icp_version, plan, settings) values (%s,%s,%s,%s) returning id",
                 now, vid, plan, J({"shrink_k": k, "opp_rate": opp_rate, "capacity_accounts": cap_accounts}))

    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for c in comps:
        groups[("segment", c["segment"])].append(c)
        groups[("region_group", c["region_group"])].append(c)
        groups[("total", "all")].append(c)
    sam_total = sum(1 for c in comps if _in_sam(c, reach, signer_seg.get(c["segment"], signer_all)))
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
        sam = [c for c in cs if _in_sam(c, reach, signer_seg.get(c["segment"], signer_all))]
        sam_judged = [c for c in sam if c["judged"]]
        sam_ab = sum(1 for c in sam_judged if c["tier"] in ("A", "B"))
        sam_nj = sum(1 for c in sam if not c["judged"])
        sam_fit = sam_ab / len(sam_judged) if sam_judged else 0
        reachable = sum(1 for c in cs if reach[c["id"]].get(signer_seg.get(c["segment"], signer_all), False))
        tam_low, tam_high = ab_known * p25, int((ab_known + nj * fit_share) * p75)
        sam_low, sam_high = sam_ab * p25, int((sam_ab + sam_nj * sam_fit) * p75)
        sam_count = sam_ab
        share = (sam_count / sam_total) if sam_total else 0
        cap = cap_accounts * share if dim != "total" else cap_accounts
        workable = min(sam_count, cap)
        som_low = int(workable * opp_lo * wlo * p25)
        som_high = int(min(workable * opp_hi * whi * p75, sam_high))
        som_low = min(som_low, som_high)
        rows.append((rid, dim, key, len(cs), tiers.get("A", 0), tiers.get("B", 0), tiers.get("C", 0), tiers.get("X", 0), nj,
                     pub, coverage, reachable, sam_count, round(cap, 1), tam_low, tam_high, min(sam_low, tam_low),
                     min(sam_high, tam_high), som_low, min(som_high, sam_high),
                     J({"p25": p25, "median": p50, "p75": p75, "from": acv_note, "won_deals": len(acvs)}),
                     J({"wins": wins, "opps": opps, "overall": overall, "shrunk": shrunk, "low": wlo, "high": whi,
                        "raw_low": raw_lo, "raw_high": raw_hi, "k": k}),
                     J({"capacity_accounts": round(cap, 1), "opp_rate": opp_rate, "opp_low": opp_lo, "opp_high": opp_hi,
                        "signer": signer_seg.get(key, signer_all) if dim == "segment" else signer_all})))
    with cur.copy("""copy segment_sizing (run, dimension, key, universe_count, fit_a, fit_b, fit_c, fit_x, not_judged,
                     public_count, coverage_share, reachable_count, sam_count, capacity_accounts, tam_low, tam_high,
                     sam_low, sam_high, som_low, som_high, acv_basis, win_rate_basis, capacity_basis) from stdin""") as cp:
        for r in rows:
            cp.write_row(r)
    return rid


def _in_sam(c: dict, reach: dict, signer: str) -> bool:
    return (c["region"] in C.SERVED_REGIONS and c["tier"] != "X" and not c["sole_trader"]
            and bool(reach[c["id"]].get(signer, False)))
