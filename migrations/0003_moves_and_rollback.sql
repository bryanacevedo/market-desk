-- Territory move proposals (a manager or RevOps proposes, someone else decides, an approval makes a draft plan that goes
-- through the usual activation and the CRM books), and the memory a rollback needs: which plan or profile version
-- each one replaced, and who restored or rolled back what, and when.
create table move_proposals (
  id serial primary key,
  status text not null default 'open' check (status in ('open', 'approved', 'rejected')),
  to_owner int not null references users(id),
  to_territory text,
  reason text not null check (length(trim(reason)) >= 3),
  effective_on date not null,
  proposed_by int not null references users(id),
  proposed_at timestamptz not null default app_now(),
  decided_by int references users(id),
  decided_at timestamptz,
  decision_note text,
  plan int references territory_plans(id),
  check (status = 'open' or (decided_by is not null and decided_at is not null)),
  check (status <> 'rejected' or (decision_note is not null and length(trim(decision_note)) >= 3)),
  check (decided_by is null or decided_by <> proposed_by));
create table move_proposal_accounts (
  proposal int not null references move_proposals(id) on delete cascade,
  company int not null references companies(id),
  from_owner int references users(id),
  primary key (proposal, company));
create index move_proposals_open on move_proposals (id) where status = 'open';

alter table territory_plans
  add column replaced int references territory_plans(id),
  add column drafted_from int references territory_plans(id),
  add column restored_by int references users(id), add column restored_at timestamptz,
  add column rolled_back_by int references users(id), add column rolled_back_at timestamptz;
alter table icp_versions
  add column replaced int references icp_versions(id),
  add column restored_by int references users(id), add column restored_at timestamptz,
  add column rolled_back_by int references users(id), add column rolled_back_at timestamptz;

-- A batch that was still waiting when its plan was rolled back is cancelled, never sent.
alter table crm_outbox drop constraint crm_outbox_status_check;
alter table crm_outbox add constraint crm_outbox_status_check check (status in ('queued', 'sent', 'failed', 'cancelled'));
