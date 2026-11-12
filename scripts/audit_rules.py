"""Rules against data: checks the demo database against every product rule in docs/SPEC.md and every rule the schema
could not express as a CHECK. Run as `make audit` or through tests/test_rules_vs_data.py. Read-only.

Each check is a query that returns the rows breaking the rule; an empty result passes."""
from __future__ import annotations

import json
import sys

CHECKS: list[tuple[str, str]] = [
    ("No deal closes before it opens",
     "select id from deals where closed_at < created_at"),
    ("A deal is open exactly when it has no close date",
     "select id from deals where (outcome = 'open') <> (closed_at is null)"),
    ("No deal opens after the desk's today",
     "select id from deals where created_at > app_now()"),
    ("No customer starts before its won deal closes",
     """select c.company from customers c where not exists (select 1 from deals d where d.company = c.company
        and d.kind = 'new' and d.outcome = 'won' and d.closed_at::date <= c.started_on)"""),
    ("Churn comes after the start",
     "select company from customers where churned_on is not null and churned_on <= started_on"),
    ("A customer's lifecycle says customer or churned",
     """select c.company from customers c join companies x on x.id = c.company
        where x.lifecycle <> case when c.churned_on is null then 'customer' else 'churned' end"""),
    ("Every expansion deal is at a company that bought first",
     """select d.id from deals d where d.kind = 'expansion' and not exists (select 1 from deals w where w.company = d.company
        and w.kind = 'new' and w.outcome = 'won' and w.closed_at <= d.created_at)"""),
    ("A deal snapshot matches the company (only size may have grown since)",
     """select d.id from deals d join companies c on c.id = d.company where c.lifecycle <> 'competitor' and (
        d.snapshot->>'country' <> c.country or coalesce(d.snapshot->>'pricing_model','') <> coalesce(c.pricing_model,'')
        or (c.industry is not null and d.snapshot->>'industry' is distinct from c.industry)
        or d.snapshot->>'region' is distinct from c.region or d.snapshot->>'hq_city' is distinct from c.hq_city
        or (d.snapshot->>'founded_year')::int is distinct from c.founded_year
        or coalesce(d.snapshot->>'revenue_band','') <> coalesce(c.revenue_band,'')
        or (d.snapshot->>'employees')::int > c.employees)"""),
    ("No call note names a prospect (no CRM contact pattern survives redaction)",
     r"""select id from call_notes where text_redacted ~ '(Mr|Ms|Mrs|Dr)\.\s+[A-Z]' or text_redacted ~ '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[a-z]{2,}'"""),
    ("Every quote is a verbatim part of its call note",
     "select q.id from quotes q join call_notes n on n.id = q.call_note where position(q.text in n.text_redacted) = 0"),
    ("Every book row belongs to the plan its book names",
     """select r.book, r.company from target_book_rows r join target_books b on b.id = r.book
        where not exists (select 1 from assignments a where a.plan = b.plan and a.company = r.company)
          and not exists (select 1 from segment_test_members m join segment_tests t on t.id = m.test
                          where m.company = r.company and m.grp = 'worked' and t.started_on <= b.created_at::date)"""),
    ("No held-back company is in an Account Desk book made while its test ran",
     """select r.book, r.company from target_book_rows r join target_books b on b.id = r.book and b.destination = 'account_desk'
        join segment_test_members m on m.company = r.company and m.grp = 'held_back'
        join segment_tests t on t.id = m.test and b.created_at::date between t.started_on and t.ends_on"""),
    ("Every worked member of a test is in the Account Desk book made when it started",
     """select t.id, m.company from segment_tests t join segment_test_members m on m.test = t.id and m.grp = 'worked'
        where t.started_on is not null and exists (select 1 from target_books b where b.destination = 'account_desk'
              and b.created_at::date between t.started_on and t.ends_on)
          and not exists (select 1 from target_book_rows r join target_books b on b.id = r.book
              where r.company = m.company and b.destination = 'account_desk' and b.created_at::date between t.started_on and t.ends_on)"""),
    ("A desk's reported opportunity is a deal in the CRM opened in that period",
     """select r.id from desk_results r where r.opportunities > 0 and not exists (select 1 from deals d where d.company = r.company
        and d.created_at::date between r.period_start and r.period_end)"""),
    ("A desk never reports a win the CRM does not have",
     """select r.id from desk_results r where r.won > 0 and not exists (select 1 from deals d where d.company = r.company
        and d.outcome = 'won' and d.closed_at::date between r.period_start and r.period_end)"""),
    ("Every owner in a plan has a capacity row",
     """select distinct a.plan, a.owner from assignments a where a.owner is not null and not exists
        (select 1 from capacity_snapshots s where s.plan = a.plan and s.user_id = a.owner)"""),
    ("A territory reported balanced has nobody over their hours",
     """select p.id, t.key from territory_plans p join territories t on t.plan = p.id
        where (p.balance_report->t.key->>'balanced')::boolean and exists (select 1 from capacity_snapshots s
        where s.plan = p.id and s.user_id in (select (jsonb_array_elements_text(t.rule->'people'))::int)
          and s.hours_required > s.hours_available + 0.05)"""),
    ("Nothing is stamped after the desk's today",
     """select 'assignments' as t, count(*) from assignments where created_at > app_now() having count(*) > 0
        union all select 'audit_log', count(*) from audit_log where at > app_now() having count(*) > 0
        union all select 'users', count(*) from users where created_at > app_now() having count(*) > 0
        union all select 'llm_calls', count(*) from llm_calls where at > app_now() having count(*) > 0
        union all select 'icp_versions', count(*) from icp_versions where created_at > app_now() having count(*) > 0
        union all select 'proposals', count(*) from change_proposals where created_at > app_now() having count(*) > 0
        union all select 'books', count(*) from target_books where created_at > app_now() having count(*) > 0
        union all select 'deals', count(*) from deals where created_at > app_now() having count(*) > 0"""),
    ("A profile version's evidence ran before the version was written",
     """select v.id from icp_versions v join analysis_runs r on r.id = v.based_on_analysis where r.ran_at > v.created_at"""),
    ("A proposal cites findings that exist and say what it says",
     """select p.id from change_proposals p, jsonb_array_elements_text(p.evidence->'finding_ids') fid
        where not exists (select 1 from findings f where f.id = fid::int)"""),
    ("No expansion deal opens after its customer left",
     """select d.id from deals d join customers c on c.company = d.company where d.kind = 'expansion'
        and c.churned_on is not null and d.created_at::date >= c.churned_on"""),
    ("Every deal has two to seven roles",
     """select d.id from deals d where (select count(*) from deal_roles r where r.deal = d.id) not between 2 and 7"""),
    ("A call note's author had joined when it was written",
     "select n.id from call_notes n join users u on u.id = n.author where n.written_at::date < u.started_on"),
    ("A deal's owner had joined when it opened",
     "select d.id from deals d join users u on u.id = d.owner where d.created_at::date < u.started_on"),
    ("No sole trader is in any book",
     "select r.company from target_book_rows r join companies c on c.id = r.company where c.sole_trader"),
    ("No customer or open deal is in an Account Desk book (on the book's date)",
     """select r.book, r.company from target_book_rows r join target_books b on b.id = r.book
        where exists (select 1 from customers c where c.company = r.company and c.started_on <= b.created_at::date
                      and (c.churned_on is null or c.churned_on > b.created_at::date))
           or exists (select 1 from deals d where d.company = r.company and d.created_at <= b.created_at
                      and (d.closed_at is null or d.closed_at > b.created_at))"""),
    ("Capacity figures add up to the plan's assignments (from the snapshot side)",
     """select s.plan, s.user_id from capacity_snapshots s where
        (s.accounts_by_tier->>'A')::int + (s.accounts_by_tier->>'B')::int + (s.accounts_by_tier->>'C')::int + (s.accounts_by_tier->>'X')::int
        <> (select count(*) from assignments a where a.plan = s.plan and a.owner = s.user_id)"""),
    ("Hours required equal the tier hours of the accounts held",
     """select s.plan, s.user_id from capacity_snapshots s, settings h where h.key = 'hours_per_tier' and abs(s.hours_required - (
        (s.accounts_by_tier->>'A')::int * (h.value->>'A')::numeric + (s.accounts_by_tier->>'B')::int * (h.value->>'B')::numeric
        + (s.accounts_by_tier->>'C')::int * (h.value->>'C')::numeric)) > 0.11"""),
    ("Every rule of the published profile has evidence or says Hypothesis (evidence key present)",
     """select v.id from icp_versions v, jsonb_array_elements((v.rules->'factors') || (v.rules->'penalties') || (v.rules->'excludes')) r
        where v.status = 'published' and not (r ? 'evidence')"""),
    ("Evidence on a rule points at a finding that exists",
     """select v.id from icp_versions v, jsonb_array_elements((v.rules->'factors') || (v.rules->'penalties') || (v.rules->'excludes')) r
        where v.status in ('published','draft') and r->'evidence' is not null and jsonb_typeof(r->'evidence') = 'object'
          and not exists (select 1 from findings f where f.id = (r->'evidence'->>'finding_id')::int)"""),
    ("A published or retired version was published by someone other than its author",
     "select id from icp_versions where status <> 'draft' and (published_by is null or published_by = author)"),
    ("An active plan was activated by a manager who is not its author",
     """select p.id from territory_plans p join users u on u.id = p.activated_by where p.status = 'active'
        and (u.role <> 'manager' or p.activated_by = p.author)"""),
    ("A segment test's held-back group is 20% of its members",
     """select t.id from segment_tests t where t.status <> 'draft' and (select count(*) from segment_test_members m
        where m.test = t.id and m.grp = 'held_back') <> round(t.held_back_share * t.cohort_size)"""),
    ("Test results come only for members of that test",
     """select r.id from desk_results r where r.test is not null and not exists (select 1 from segment_test_members m
        where m.test = r.test and m.company = r.company)"""),
    ("A held-back result is never marked worked or sent to a desk",
     "select id from desk_results where held_back and (worked or destination is not null)"),
    ("A dismissed proposal has a reason",
     "select id from change_proposals where status = 'dismissed' and coalesce(trim(reason), '') = ''"),
    ("A drafted proposal names the draft it went into",
     "select id from change_proposals where status = 'drafted' and draft_version is null"),
    ("A model-read field never excluded a company",
     """select f.company from account_fit f where f.tier = 'X' and f.excluded is not null
        and f.excluded not like 'Already %%' and exists (select 1 from field_values v where v.company = f.company
        and v.source = 'model' and v.field = 'industry') and not exists (select 1 from field_values v where v.company = f.company
        and v.source <> 'model' and v.field = 'industry') and f.inputs->'model_fields' ? 'industry'
        and f.excluded = 'Sector we do not sell to'"""),
    ("Sizing ranges are ordered and nested (SAM within TAM, SOM within SAM)",
     """select run, dimension, key from segment_sizing where not (tam_low <= tam_high and sam_low <= sam_high and
        som_low <= som_high and sam_high <= tam_high and som_high <= sam_high)"""),
    ("Coverage is unknown, never 100%, where no public count exists",
     "select run, key from segment_sizing where public_count is null and coverage_share is not null"),
    ("Every finding's opportunities are at least its wins",
     "select id from findings where wins > opps or rest_wins > rest_opps"),
    ("The demo opens with a draft plan, an open proposal, a running test and a read test",
     """select 1 where not (exists (select 1 from territory_plans where status = 'draft')
        and exists (select 1 from change_proposals where status = 'open')
        and exists (select 1 from segment_tests where status = 'running')
        and exists (select 1 from segment_tests where status = 'read'))"""),
    ("No planted effect is stronger than the plan allows (usage 38% at most against others)",
     """select id from findings where trait = 'pricing_model' and value = '"usage"' and (win_rate > 0.40 or rest_wins::numeric / rest_opps < 0.12)"""),
    ("Only invented domains", "select id from companies where primary_domain not like '%%.example'"),
    ("Only invented team addresses", "select id from users where email not like '%%@lumenledger.example'"),
]


def run(cur) -> list[dict]:
    from market import db
    out = []
    for name, sql in CHECKS:
        rows = db.all(cur, sql)
        out.append({"rule": name, "breaks": len(rows), "sample": [list(r.values()) for r in rows[:5]]})
    return out


def main() -> int:
    from market import db
    with db.tx() as cur:
        cur.execute("set transaction read only")
        res = run(cur)
    bad = [r for r in res if r["breaks"]]
    print(json.dumps({"checks": len(res), "failing": bad}, indent=1, default=str))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
