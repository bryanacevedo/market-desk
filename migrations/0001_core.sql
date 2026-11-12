-- Market Desk core schema. Money is integer cents. Later fixes are new numbered files.

create table sim_clock (id int primary key default 1 check (id = 1), enabled boolean not null default false,
                        at timestamptz not null default now());
insert into sim_clock (id) values (1);
create function app_now() returns timestamptz language sql stable as
  $$ select case when enabled then at else now() end from sim_clock $$;

-- ---------------------------------------------------------------- team and settings
create table users (
  id serial primary key, name text not null, email text not null unique,
  role text not null check (role in ('revops', 'manager', 'sdr', 'ae')),
  timezone text not null default 'America/New_York', started_on date not null,
  ramp_months int not null default 3 check (ramp_months >= 0),
  selling_hours_month numeric not null default 100 check (selling_hours_month >= 0),
  active boolean not null default true, erased boolean not null default false,
  created_at timestamptz not null default app_now());

create table settings (key text primary key, value jsonb not null, note text not null,
                       updated_at timestamptz not null default app_now(), updated_by int references users(id));

-- ---------------------------------------------------------------- sources and the universe
create table sources (
  key text primary key, label text not null,
  kind text not null check (kind in ('firmographic', 'technographic', 'registry', 'public_counts', 'crm', 'desk_results', 'coverage', 'model')),
  adapter text not null check (adapter in ('sim', 'live')), paid boolean not null, unit text,
  price_cents_per_unit numeric, licence_note text not null, no_redistribution boolean not null default false,
  cadence_hours int not null);

create table source_runs (
  id serial primary key, source text not null references sources(key), started_at timestamptz not null,
  finished_at timestamptz, rows_read int not null default 0, rows_changed int not null default 0, error text,
  check (finished_at is null or finished_at >= started_at));

create table companies (
  id serial primary key, name text not null, primary_domain text not null unique check (primary_domain = lower(primary_domain)),
  parent_id int references companies(id), country text not null, region text not null, region_group text not null,
  hq_city text, founded_year int, industry text, employees int check (employees is null or employees >= 0),
  revenue_band text, pricing_model text check (pricing_model in ('usage', 'seat', 'transaction', 'mixed', 'unknown')),
  tech text[] not null default '{}', description text,
  lifecycle text not null default 'prospect' check (lifecycle in ('prospect', 'customer', 'churned', 'open_opp', 'competitor', 'partner')),
  sole_trader boolean not null default false, crm_id text, owner_id int references users(id),
  created_at timestamptz not null default app_now());
create index companies_segment_fields on companies (industry, employees);
create index companies_region_group on companies (region_group);

create table field_values (
  id bigserial primary key, company int not null references companies(id) on delete cascade, field text not null,
  value jsonb not null, source text not null, observed_at timestamptz not null,
  confidence numeric not null check (confidence between 0 and 1), set_by_person boolean not null default false,
  quote text);
create index field_values_company on field_values (company, field);

create table reachability (
  company int not null references companies(id) on delete cascade, persona text not null,
  has_named_contact_source boolean not null, email_fill_rate numeric check (email_fill_rate between 0 and 1),
  observed_at timestamptz not null, primary key (company, persona));

create table public_counts (
  id serial primary key, source text not null references sources(key), country text not null, industry text not null,
  size_band text not null, year int not null, companies int not null check (companies >= 0),
  unique (source, country, industry, size_band, year));

-- ---------------------------------------------------------------- CRM history
create table deals (
  id serial primary key, company int not null references companies(id), kind text not null check (kind in ('new', 'expansion')),
  created_at timestamptz not null, closed_at timestamptz, stage text not null,
  outcome text not null check (outcome in ('won', 'lost', 'open')), amount_cents bigint not null check (amount_cents >= 0),
  loss_reason_text text, loss_code text check (loss_code in ('price', 'timing', 'no_decision', 'competitor', 'missing_feature',
    'compliance', 'champion_left', 'bad_fit', 'other')), loss_code_source text, competitor text,
  source text not null check (source in ('outbound', 'inbound', 'event', 'partner')), owner int references users(id),
  snapshot jsonb not null,
  check (closed_at is null or closed_at >= created_at),
  check ((outcome = 'open') = (closed_at is null)));
create index deals_company on deals (company);
create index deals_closed on deals (closed_at) where kind = 'new';

create table deal_roles (
  id serial primary key, deal int not null references deals(id) on delete cascade, persona text not null,
  seniority text not null, was_signer boolean not null default false, was_champion boolean not null default false);

create table customers (
  company int primary key references companies(id), started_on date not null, churned_on date,
  churn_reason_text text, churn_reason_code text, arr_cents bigint not null check (arr_cents >= 0),
  check (churned_on is null or churned_on >= started_on));

create table call_notes (
  id serial primary key, deal int not null references deals(id) on delete cascade, written_at timestamptz not null,
  author int references users(id), text_redacted text not null);

-- ---------------------------------------------------------------- profile
create table icp_versions (
  id serial primary key, number int not null unique,
  status text not null check (status in ('draft', 'published', 'retired')), rules jsonb not null,
  check (status = 'draft' or published_by is not null),
  based_on_analysis int, note text, author int not null references users(id), published_by int references users(id),
  published_at timestamptz, created_at timestamptz not null default app_now());
create unique index one_published_profile on icp_versions ((true)) where status = 'published';

create function icp_two_people() returns trigger language plpgsql as $$
begin
  if new.status = 'published' and new.published_by is not null and new.published_by = new.author then
    raise exception 'A profile version is published by someone other than its author';
  end if;
  if new.status = 'published' and (tg_op = 'INSERT' or old.status = 'draft')
     and (select role from users where id = new.published_by) <> 'manager' then
    raise exception 'Only a manager publishes a profile version';
  end if;
  return new;
end $$;
create trigger icp_two_people before insert or update on icp_versions for each row execute function icp_two_people();

create table account_fit (
  company int not null references companies(id) on delete cascade, icp_version int not null references icp_versions(id),
  score int check (score between 0 and 100), tier text not null check (tier in ('A', 'B', 'C', 'X')),
  judged boolean not null, segment text not null, scored_out_of numeric not null,
  components_missing text[] not null default '{}', excluded text, inputs jsonb not null, breakdown jsonb not null,
  primary key (company, icp_version));
create index account_fit_version_tier on account_fit (icp_version, tier);

-- ---------------------------------------------------------------- evidence
create table analysis_runs (
  id serial primary key, ran_at timestamptz not null, window_start timestamptz not null, window_end timestamptz not null,
  deals_considered int not null, tests_run int not null, settings jsonb not null);

create table findings (
  id serial primary key, run int not null references analysis_runs(id) on delete cascade, trait text not null,
  value_label text not null, value jsonb not null, opps int not null, wins int not null, win_rate numeric not null,
  wr_low numeric not null, wr_high numeric not null, rest_opps int not null, rest_wins int not null, diff numeric not null,
  diff_low numeric not null, diff_high numeric not null, p_value numeric not null,
  verdict text not null check (verdict in ('clear_higher', 'clear_lower', 'not_clear', 'too_few', 'explained_by_size')),
  mh_or numeric, mh_low numeric, mh_high numeric,
  cycle_median_days numeric, cycle_low numeric, cycle_high numeric, cycle_n int not null default 0,
  acv_median bigint, acv_p25 bigint, acv_p75 bigint, churn_rate_12m numeric, churn_n int not null default 0,
  top_loss_codes jsonb not null default '[]');
create index findings_run on findings (run, trait);

create table finding_strata (
  finding int not null references findings(id) on delete cascade, size_band text not null, opps int not null,
  wins int not null, rest_opps int not null, rest_wins int not null, primary key (finding, size_band));

-- ---------------------------------------------------------------- segments and sizing
create table segments (key text primary key, label text not null, definition jsonb not null, icp_version int references icp_versions(id),
                       position int not null);
create table segment_roles (segment text not null, persona text not null, share_of_won_deals numeric not null,
                            share_as_signer numeric not null, n_won_deals int not null, primary key (segment, persona));
create table quotes (id serial primary key, call_note int not null references call_notes(id) on delete cascade,
                     segment text, text text not null,
                     kind text not null check (kind in ('reason_to_buy', 'objection', 'competitor')));
create table segment_stories (
  id serial primary key, segment text not null, drafted_at timestamptz not null, sentences jsonb,
  status text not null check (status in ('ok', 'withheld')), failures jsonb not null default '[]', source text not null);

create table sizing_runs (id serial primary key, ran_at timestamptz not null, icp_version int not null references icp_versions(id),
                          plan int, settings jsonb not null);
create table segment_sizing (
  run int not null references sizing_runs(id) on delete cascade,
  dimension text not null check (dimension in ('segment', 'region_group', 'total')), key text not null,
  universe_count int not null, fit_a int not null, fit_b int not null, fit_c int not null, fit_x int not null,
  not_judged int not null, public_count int, coverage_share numeric, reachable_count int not null, sam_count int not null,
  capacity_accounts numeric, tam_low bigint not null, tam_high bigint not null, sam_low bigint not null,
  sam_high bigint not null, som_low bigint not null, som_high bigint not null,
  acv_basis jsonb not null, win_rate_basis jsonb not null, capacity_basis jsonb not null,
  check (tam_low <= tam_high and sam_low <= sam_high and som_low <= som_high and sam_high <= tam_high and som_high <= sam_high),
  primary key (run, dimension, key));

-- ---------------------------------------------------------------- territories and capacity
create table territory_plans (
  id serial primary key, name text not null, status text not null check (status in ('draft', 'active', 'retired')),
  based_on int not null references icp_versions(id), author int not null references users(id),
  activated_by int references users(id), activated_at timestamptz, balance_report jsonb not null default '{}',
  check (status <> 'active' or activated_by is not null),
  effective_on date not null default current_date,
  created_at timestamptz not null default app_now());
create unique index one_active_plan on territory_plans ((true)) where status = 'active';

create function plan_two_people() returns trigger language plpgsql as $$
begin
  if new.status = 'active' and new.activated_by is not null and new.activated_by = new.author then
    raise exception 'A plan is activated by someone other than its author';
  end if;
  if new.status = 'active' and new.activated_by is not null
     and (select role from users where id = new.activated_by) <> 'manager' then
    raise exception 'Only a manager activates a plan';
  end if;
  return new;
end $$;
create trigger plan_two_people before insert or update on territory_plans for each row execute function plan_two_people();

create table territories (
  id serial primary key, plan int not null references territory_plans(id) on delete cascade, key text not null,
  label text not null, rule jsonb not null, owner int references users(id), paired_ae int references users(id),
  unique (plan, key));

create table assignments (
  plan int not null references territory_plans(id) on delete cascade, company int not null references companies(id),
  territory int references territories(id), owner int references users(id),
  reason_code text not null check (reason_code in ('rule', 'test', 'existing_owner', 'open_deal', 'customer_team', 'balance_move', 'manual')),
  note text, moved_from int references users(id), created_at timestamptz not null default app_now(), created_by int references users(id),
  check (reason_code <> 'manual' or (note is not null and length(trim(note)) >= 3)),
  primary key (plan, company));
create index assignments_owner on assignments (plan, owner);

create table capacity_snapshots (
  plan int not null references territory_plans(id) on delete cascade, user_id int not null references users(id),
  effective_fte numeric not null, hours_available numeric not null, hours_required numeric not null,
  accounts_by_tier jsonb not null, expected_value_cents bigint not null default 0, primary key (plan, user_id));

-- ---------------------------------------------------------------- handoffs, results, tests, changes
create table target_books (
  id serial primary key, version int not null, icp_version int not null references icp_versions(id),
  plan int not null references territory_plans(id), destination text not null check (destination in ('account_desk', 'events_desk')),
  created_at timestamptz not null, created_by int references users(id), file_sha256 text, rows int not null default 0,
  dropped_rules jsonb not null default '[]', diff jsonb not null default '{}', unique (destination, version));
create table target_book_files (book int not null references target_books(id) on delete cascade, path text not null,
                                bytes bytea not null, primary key (book, path));

create table segment_tests (
  id serial primary key, segment text not null, hypothesis text not null, cohort_size int not null check (cohort_size > 0),
  held_back_share numeric not null default 0.2 check (held_back_share > 0 and held_back_share < 1),
  started_on date, ends_on date, status text not null check (status in ('draft', 'running', 'read', 'stopped')),
  decision text check (decision in ('expand', 'drop', 'extend')), decided_by int references users(id), decision_note text,
  created_by int references users(id), created_at timestamptz not null default app_now(),
  check (ends_on is null or started_on is null or ends_on > started_on));
create table segment_test_members (
  test int not null references segment_tests(id) on delete cascade, company int not null references companies(id),
  grp text not null check (grp in ('worked', 'held_back')), primary key (test, company));

create table target_book_rows (
  book int not null references target_books(id) on delete cascade, company int not null references companies(id),
  tier text not null check (tier in ('A', 'B', 'C', 'X')), owner int references users(id), segment text not null,
  test_member boolean not null default false,
  primary key (book, company));

-- A held-back member of a running test never reaches Account Desk: it is the comparison group.
create function refuse_held_back() returns trigger language plpgsql as $$
begin
  if (select destination from target_books where id = new.book) = 'account_desk' and exists (
      select 1 from segment_test_members m join segment_tests t on t.id = m.test
      where m.company = new.company and m.grp = 'held_back' and t.status = 'running') then
    raise exception 'Company % is held back in a running segment test', new.company;
  end if;
  return new;
end $$;
create trigger refuse_held_back before insert or update on target_book_rows for each row execute function refuse_held_back();

create table desk_results (
  id serial primary key, company int not null references companies(id), destination text,
  period_start date not null, period_end date not null, worked boolean not null, held_back boolean not null,
  test int references segment_tests(id), meetings int not null default 0 check (meetings >= 0),
  opportunities int not null default 0 check (opportunities >= 0), won int not null default 0 check (won >= 0),
  lost int not null default 0 check (lost >= 0), pipeline_cents bigint not null default 0 check (pipeline_cents >= 0),
  read_at timestamptz not null, source_run int references source_runs(id),
  check (not (worked and held_back)), check (period_end >= period_start),
  check (destination is null or destination in ('account_desk', 'events_desk')));
create index desk_results_company on desk_results (company);
-- One row per company, desk, period and test: a second delivery of the same results is refused, never counted twice.
create unique index desk_results_once on desk_results (company, coalesce(destination, ''), period_start, period_end, coalesce(test, 0));

create table change_proposals (
  id serial primary key, kind text not null check (kind in ('add_rule', 'drop_rule', 'reweight', 'add_exclude', 'penalty', 'segment_expand', 'segment_drop')),
  evidence jsonb not null, proposed_rules_diff jsonb not null, text_sentences jsonb, text_status text,
  status text not null check (status in ('open', 'drafted', 'dismissed', 'published')),
  decided_by int references users(id), reason text, draft_version int references icp_versions(id),
  created_at timestamptz not null, key text not null unique,
  check (status <> 'dismissed' or (reason is not null and length(trim(reason)) >= 3)));

-- ---------------------------------------------------------------- platform
create table jobs (
  id bigserial primary key, kind text not null, payload jsonb not null default '{}',
  status text not null default 'queued' check (status in ('queued', 'running', 'done', 'dead')),
  run_at timestamptz not null default app_now(), attempts int not null default 0, max_attempts int not null default 5,
  dedupe_key text, last_error text, locked_at timestamptz, locked_by text, finished_at timestamptz,
  progress jsonb not null default '{}', created_at timestamptz not null default app_now());
create unique index jobs_dedupe on jobs (dedupe_key) where dedupe_key is not null and status in ('queued', 'running');
create index jobs_ready on jobs (run_at) where status = 'queued';

create table alerts (
  id serial primary key, kind text not null, severity text not null, title text not null, body text not null,
  object_kind text, object_id text, dedup_key text unique, at timestamptz not null default app_now(), resolved_at timestamptz);

create table audit_log (
  id bigserial primary key, at timestamptz not null default app_now(), actor_id int references users(id), actor text not null,
  action text not null, object_kind text not null, object_id text, detail jsonb not null default '{}');

create table spend_ledger (id serial primary key, at timestamptz not null default app_now(), source text not null,
                           units numeric not null, cents numeric not null, assumption boolean not null default true, job bigint);

create table llm_calls (
  id serial primary key, at timestamptz not null default app_now(), task text not null, prompt_version text not null,
  model text not null, input_hash text not null, input_tokens int not null default 0, output_tokens int not null default 0,
  cost_cents numeric not null default 0, source text not null check (source in ('live', 'recorded', 'sim')), output jsonb);

create table webhook_deliveries (signature text primary key, at timestamptz not null default app_now());

create table erasures (id serial primary key, kind text not null, subject text not null, at timestamptz not null default app_now(),
                       by_user int references users(id));
