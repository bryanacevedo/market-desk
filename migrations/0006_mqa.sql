-- Shared-world Phase 3, step 5 (decisions 49 to 51): Market Desk decides marketing qualified accounts (MQA) when it is
-- connected to CRM Desk, and sends the result.
-- 1. A new outbox kind, 'mqa', to the same POST /accounts/batch.
alter table crm_outbox drop constraint crm_outbox_kind_check;
alter table crm_outbox add constraint crm_outbox_kind_check check (kind in ('books', 'scores', 'mqa'));

-- 2. The definitions this desk owns, as numbered versions with a hash (the same shape CRM Desk publishes its own in).
create table definition_versions (
  name text not null, version int not null, hash text not null, body jsonb not null,
  published_at timestamptz not null default app_now(), changed_by text not null,
  primary key (name, version));

-- 3. Which of CRM Desk's definitions this desk read, and when (what CRM Desk's CONNECTING.md asks a desk to keep).
create table definitions_read (
  name text primary key, owner_desk text not null, version int not null, hash text not null, read_at timestamptz not null default app_now());
