-- Shared-world Phase 3, step 4 (decisions 46 to 48).
-- 1. Publishing an ICP version sends it to the CRM: a new outbox kind, 'scores', one row per 100 accounts.
alter table crm_outbox drop constraint crm_outbox_kind_check;
alter table crm_outbox add constraint crm_outbox_kind_check check (kind in ('books', 'scores'));
alter table crm_outbox add column icp_version int references icp_versions(id);

-- 2. Deals from a CSV or a CRM: where a deal came from, and how its snapshot of the company was made.
alter table deals add column external_id text;
alter table deals add column source_system text;
alter table deals add column snapshot_source text check (snapshot_source in ('universe', 'csv_row', 'crm_snapshot', 'crm_first_seen', 'crm_backfill'));
alter table deals add constraint deals_external_pair check ((external_id is null) = (source_system is null));
create unique index deals_external on deals (source_system, external_id) where external_id is not null;
alter table deals alter column source drop not null;  -- a lead source the file did not give or we could not map is unknown, never guessed

alter table companies add column origin text not null default 'universe' check (origin in ('universe', 'deals_import', 'crm'));
alter table customers add column origin text not null default 'universe' check (origin in ('universe', 'deals_import', 'crm'));

create table deal_imports (
  id serial primary key, at timestamptz not null default app_now(), by_user int references users(id), actor text not null,
  system text not null, file_sha256 text, total int not null, inserted int not null, updated int not null, rejected int not null,
  report jsonb not null default '{}'::jsonb);

-- Where each CRM feed was last read, so a pull continues instead of starting over.
create table crm_cursors (feed text primary key, since text, updated_at timestamptz not null default app_now());
