"""Evidence: every trait value of the deals closed in the window, with its win rate, the rest's, a verdict and the
size check. Traits are read from each deal's snapshot (the company as it was when the deal opened), never from
today's company. Method in docs/SPEC.md sections 6 and 15; numbers on screens never say p, Holm or odds ratio."""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from datetime import timedelta

from . import catalog as C
from . import db, stats
from .db import J
from .fit import segment_of

CONF = 0.95


def _settings(cur) -> dict:
    return {r["key"]: r["value"] for r in db.all(cur, "select key, value from settings")}


def deal_traits(snap: dict, source: str) -> list[tuple[str, str, object]]:
    """(trait, label, value) for one deal. Unknown values are not a trait value."""
    out: list[tuple[str, str, object]] = []
    if snap.get("industry"):
        out.append(("industry", snap["industry"], snap["industry"]))
    band = C.size_band(snap.get("employees"))
    if band:
        out.append(("size_band", band, band))
    for f in ("region", "revenue_band"):
        if snap.get(f):
            out.append((f, snap[f], snap[f]))
    if snap.get("country"):
        out.append(("country", C.COUNTRY_NAME.get(snap["country"], snap["country"]), snap["country"]))
    pm = snap.get("pricing_model")
    if pm and pm != "unknown":
        out.append(("pricing_model", C.PRICING_LABEL[pm], pm))
    for t in snap.get("tech") or []:
        out.append(("tech", t, t))
    out.append(("source", source.capitalize(), source))
    if snap.get("hq_city"):
        out.append(("hq_city", snap["hq_city"], snap["hq_city"]))
    fb = C.founded_band(snap.get("founded_year"))
    if fb:
        out.append(("founded", fb, fb))
    seg = segment_of({"segments": C.SEGMENTS}, snap)
    out.append(("segment", C.SEGMENT_LABEL[seg], seg))
    return out


def _known(trait: str, snap: dict, source: str) -> bool:
    """Whether a deal has a known value for this trait: only known deals form 'the rest'."""
    if trait == "pricing_model":
        return bool(snap.get("pricing_model")) and snap["pricing_model"] != "unknown"
    if trait == "size_band":
        return C.size_band(snap.get("employees")) is not None
    if trait == "founded":
        return snap.get("founded_year") is not None
    if trait in ("tech", "source", "segment"):
        return True
    return bool(snap.get(trait))


RULE_FIELDS = {"employees": "size_band", "industry": "industry", "region": "region", "revenue_band": "revenue_band",
               "tech": "tech", "pricing_model": "pricing_model", "country": "country"}


def rule_label(rule: dict) -> str:
    v = rule["value"]
    field = C.FIELD_LABEL.get(rule["field"], rule["field"])
    if rule["op"] == "between":
        hi = "or more" if v[1] >= 1_000_000 else f"to {v[1]:,}"
        return f"{field}: {v[0]:,} {hi}"
    if rule["field"] == "pricing_model":
        vals = [C.PRICING_LABEL.get(x, x) for x in (v if isinstance(v, list) else [v])]
    elif rule["field"] == "segment":
        vals = [C.SEGMENT_LABEL.get(x, x) for x in (v if isinstance(v, list) else [v])]
    else:
        vals = v if isinstance(v, list) else [v]
    joined = ", ".join(str(x) for x in vals)
    return f"{field}: {'none of ' if rule['op'] == 'has_none' else ''}{joined}"


def published_rules(cur) -> list[dict]:
    rules = db.val(cur, "select rules from icp_versions where status = 'published'")
    if not rules:
        return []
    out = []
    for kind in ("factors", "penalties", "excludes"):
        for r in rules.get(kind, []):
            out.append({**r, "kind": kind})
    return out


def run(cur) -> int:
    from .fit import matches
    s = _settings(cur)
    now = db.val(cur, "select app_now()")
    months = int(s.get("evidence_window_months", 24))
    start = now - timedelta(days=round(months * 30.44))
    deals = db.all(cur, """
        select d.id, d.company, d.outcome, d.created_at, d.closed_at, d.amount_cents, d.loss_code, d.source, d.snapshot
        from deals d where d.kind = 'new' and d.outcome in ('won','lost') and d.closed_at >= %s and d.closed_at <= %s""",
                   start, now)
    churn = {r["company"]: r for r in db.all(cur, "select company, started_on, churned_on from customers")}
    per: dict[tuple[str, object], list[dict]] = defaultdict(list)
    labels: dict[tuple[str, object], str] = {}
    for d in deals:
        d["band"] = C.size_band(d["snapshot"].get("employees"))
        for trait, label, value in deal_traits(d["snapshot"], d["source"]):
            per[(trait, value)].append(d)
            labels[(trait, value)] = label
    # Each rule of the published profile is also a trait: the deals that match the rule against the rest.
    rules = published_rules(cur)
    for d in deals:
        snap = {**d["snapshot"], "segment": segment_of({"segments": C.SEGMENTS}, d["snapshot"])}
        for r in rules:
            if matches(r, snap):
                per[("rule", r["key"])].append(d)
                labels[("rule", r["key"])] = rule_label(r)
    rule_fields = {r["key"]: r["field"] for r in rules}
    # HQ city: only the 12 cities with the most opportunities are tested (docs/SPEC.md 15.4).
    cities = sorted([k for k in per if k[0] == "hq_city"], key=lambda k: -len(per[k]))
    for k in cities[12:]:
        per.pop(k)
    min_opps, min_wins = int(s.get("min_opps", 30)), int(s.get("min_wins", 5))
    rows = []
    for (trait, value), ds in per.items():
        ids = {d["id"] for d in ds}
        if trait == "rule":
            rf = rule_fields[value]
            rest = [d for d in deals if d["id"] not in ids and (rf == "tech" or bool(d["snapshot"].get(rf)) and d["snapshot"].get(rf) != "unknown")]
        else:
            rest = [d for d in deals if d["id"] not in ids and _known(trait, d["snapshot"], d["source"])]
        opps, wins = len(ds), sum(d["outcome"] == "won" for d in ds)
        ropps, rwins = len(rest), sum(d["outcome"] == "won" for d in rest)
        lo, hi = stats.wilson(wins, opps, conf=CONF)
        diff, dlo, dhi = stats.newcombe(wins, opps, rwins, ropps, conf=CONF)
        p = stats.fisher_two_sided(wins, opps - wins, rwins, ropps - rwins)
        won = [d for d in ds if d["outcome"] == "won"]
        cyc = stats.median_ci([(d["closed_at"] - d["created_at"]).days for d in won], conf=CONF)
        acvs = [d["amount_cents"] for d in won]
        started = [churn[d["company"]] for d in won if d["company"] in churn
                   and churn[d["company"]]["started_on"] <= (now - timedelta(days=365)).date()]
        churned = [c for c in started if c["churned_on"] and (c["churned_on"] - c["started_on"]).days <= 365]
        losses = Counter(d["loss_code"] for d in ds if d["outcome"] == "lost" and d["loss_code"])
        nl = sum(losses.values())
        strata = []
        for band, _, _ in C.SIZE_BANDS:
            a = sum(1 for d in ds if d["band"] == band and d["outcome"] == "won")
            b = sum(1 for d in ds if d["band"] == band and d["outcome"] == "lost")
            c = sum(1 for d in rest if d["band"] == band and d["outcome"] == "won")
            dd = sum(1 for d in rest if d["band"] == band and d["outcome"] == "lost")
            strata.append((band, a, b, c, dd))
        rows.append({
            "trait": trait, "value_label": labels[(trait, value)], "value": value, "opps": opps, "wins": wins,
            "win_rate": wins / opps if opps else 0, "wr_low": lo, "wr_high": hi, "rest_opps": ropps, "rest_wins": rwins,
            "diff": diff, "diff_low": dlo, "diff_high": dhi, "p": p,
            "cycle": cyc, "cycle_n": len(won),
            "acv_median": int(stats.quantile(acvs, 0.5)) if acvs else None,
            "acv_p25": int(stats.quantile(acvs, 0.25)) if acvs else None,
            "acv_p75": int(stats.quantile(acvs, 0.75)) if acvs else None,
            "churn_rate": (len(churned) / len(started)) if started else None, "churn_n": len(started),
            "losses": [{"code": k, "share": v / nl, "n": v} for k, v in losses.most_common(3)], "strata": strata,
        })
    # Holm across every value with enough opportunities (a filter on counts, not on outcomes).
    family = [r for r in rows if r["opps"] >= min_opps]
    rejected = stats.holm([r["p"] for r in family], alpha=float(s.get("family_alpha", 0.05)))
    for r, rej in zip(family, rejected):
        r["clear"] = rej
    for r in rows:
        if r["opps"] < min_opps or r["wins"] < min_wins:
            r["verdict"] = "too_few"
        elif r.get("clear"):
            r["verdict"] = "clear_higher" if r["diff"] > 0 else "clear_lower"
        else:
            r["verdict"] = "not_clear"
        r["mh"] = None
        nested = r["trait"] in ("size_band", "segment") or (r["trait"] == "rule" and rule_fields.get(r["value"]) == "employees")
        if r["verdict"] in ("clear_higher", "clear_lower") and not nested:
            mh = stats.mantel_haenszel([x[1:] for x in r["strata"]], conf=CONF)
            r["mh"] = mh
            a, b, c, d = r["wins"], r["opps"] - r["wins"], r["rest_wins"], r["rest_opps"] - r["rest_wins"]
            crude = (a * d) / (b * c) if b and c and a and d else None
            if mh and crude and mh[1] <= 1 <= mh[2] and abs(math.log(mh[0])) <= 0.5 * abs(math.log(crude)):
                r["verdict"] = "explained_by_size"
    run_id = db.val(cur, """insert into analysis_runs (ran_at, window_start, window_end, deals_considered, tests_run, settings)
                            values (%s,%s,%s,%s,%s,%s) returning id""", now, start, now, len(deals), len(family),
                    J({"min_opps": min_opps, "min_wins": min_wins, "conf": CONF, "months": months}))
    for r in rows:
        cyc = r["cycle"]
        fid = db.val(cur, """insert into findings (run, trait, value_label, value, opps, wins, win_rate, wr_low, wr_high,
            rest_opps, rest_wins, diff, diff_low, diff_high, p_value, verdict, mh_or, mh_low, mh_high, cycle_median_days,
            cycle_low, cycle_high, cycle_n, acv_median, acv_p25, acv_p75, churn_rate_12m, churn_n, top_loss_codes)
            values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) returning id""",
            run_id, r["trait"], r["value_label"], J(r["value"]), r["opps"], r["wins"], r["win_rate"], r["wr_low"],
            r["wr_high"], r["rest_opps"], r["rest_wins"], r["diff"], r["diff_low"], r["diff_high"], r["p"], r["verdict"],
            *(r["mh"] or (None, None, None)), *(cyc or (None, None, None)),
            r["cycle_n"], r["acv_median"], r["acv_p25"], r["acv_p75"], r["churn_rate"], r["churn_n"], J(r["losses"]))
        for band, a, b, c, d in r["strata"]:
            db.run(cur, """insert into finding_strata (finding, size_band, opps, wins, rest_opps, rest_wins)
                           values (%s,%s,%s,%s,%s,%s)""", fid, band, a + b, a, c + d, c)
    return run_id


def latest_run(cur) -> int | None:
    return db.val(cur, "select max(id) from analysis_runs")


def changes_since_previous(cur, run_id: int) -> list[dict]:
    """Findings whose verdict differs from the previous run's, or that are new."""
    prev = db.val(cur, "select max(id) from analysis_runs where id < %s", run_id)
    if prev is None:
        return []
    return db.all(cur, """
        select f.id, f.trait, f.value_label, f.verdict, p.verdict as was
        from findings f left join findings p on p.run = %s and p.trait = f.trait and p.value = f.value
        where f.run = %s and (p.id is null or p.verdict <> f.verdict) order by f.trait, f.value_label""", prev, run_id)
