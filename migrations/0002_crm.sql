-- Market Desk's write to a CRM (shared-world DESIGN.md section 7, step 1): every plan activation queues its books,
-- written in the same transaction as the activation, and a job sends them. A row keeps the CRM's answer, so refusals
-- (an owner a manager pinned) show here as well as in the CRM. Empty when no CRM is set: the desk works alone.
create table crm_outbox (
  id serial primary key,
  plan int references territory_plans(id),
  kind text not null check (kind in ('books')),
  payload jsonb not null,
  status text not null default 'queued' check (status in ('queued', 'sent', 'failed')),
  attempts int not null default 0,
  last_error text,
  answer jsonb,
  sent_at timestamptz,
  created_at timestamptz not null default app_now());
create index crm_outbox_queued on crm_outbox (id) where status = 'queued';
