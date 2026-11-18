-- Integrated week 2 fixes (decisions 73 to 78). Safe to run twice. To take it back: drop table scheduled_moves, crm_owner_reads;
-- alter table crm_outbox drop column trace_parent, drop column ref.
set local lock_timeout = '5s';  -- a busy table fails the start; the next start retries

-- A CRM request row keeps the W3C traceparent of the request that queued it (NULL with tracing off), so the span that sends the
-- row can link to it; and `ref` names what the row is for ("plan:4", "move:7") so a screen can say when it reached CRM Desk.
alter table crm_outbox add column if not exists trace_parent text;
alter table crm_outbox add column if not exists ref text;
create index if not exists crm_outbox_ref on crm_outbox (ref) where ref is not null;

-- An approved move proposal while a plan is scheduled: the moves wait here for their date and are applied to the plan in effect.
create table if not exists scheduled_moves (
  id serial primary key,
  proposal int not null references move_proposals(id),
  company int not null references companies(id),
  to_owner int not null references users(id),
  to_territory text,
  effective_on date not null,
  status text not null default 'pending' check (status in ('pending', 'applied', 'dropped')),
  applied_at timestamptz,
  dropped_why text,
  unique (proposal, company));
create index if not exists scheduled_moves_due on scheduled_moves (effective_on) where status = 'pending';
create index if not exists scheduled_moves_company on scheduled_moves (company) where status = 'pending';

-- Who CRM Desk holds as AE and SDR for an account, and which desk or person set each, as the account feed last said.
create table if not exists crm_owner_reads (
  company int primary key references companies(id) on delete cascade,
  ae_email text, ae_set_by text, sdr_email text, sdr_set_by text,
  read_at timestamptz not null default app_now());

-- "Ask for approval": a note from the author of a draft to the managers, with the reason.
alter table notices drop constraint if exists notices_kind_check;
alter table notices add constraint notices_kind_check check (kind in ('profile_rolled_back', 'plan_rolled_back', 'approval_asked'));
alter table notices alter column restored drop not null;
