-- A person's own owner change on an account drops it from a scheduled plan (Bryan, 2026-11-15; decision 57). The plan keeps
-- what it meant to do (`planned_owner`); on the start date it neither moves the account nor sends its owner to the CRM.
create table plan_hand_changes (
  plan int not null references territory_plans(id) on delete cascade,
  company int not null references companies(id),
  role text not null check (role in ('owner', 'sdr')),
  source text not null check (source in ('market_desk', 'crm_desk')),
  to_user int references users(id),
  planned_owner int references users(id),
  by_name text,
  note text,
  at timestamptz not null default app_now(),
  primary key (plan, company, role)
);
