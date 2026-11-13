-- A rollback needs a reason, and the other managers and RevOps are told. A territory move can name the territory whose
-- rule picked its accounts.
alter table territory_plans add column rolled_back_reason text;
alter table icp_versions add column rolled_back_reason text;
create table notices (
  id serial primary key,
  kind text not null check (kind in ('profile_rolled_back', 'plan_rolled_back')),
  subject text not null,            -- "ICP version 4" or the plan's name
  restored text not null,           -- "version 3" or the plan's name
  reason text not null check (length(trim(reason)) >= 3),
  path text not null,
  by_user int not null references users(id),
  at timestamptz not null default app_now());
create table notice_seen (
  notice int not null references notices(id) on delete cascade,
  user_id int not null references users(id),
  at timestamptz not null default app_now(),
  primary key (notice, user_id));
alter table move_proposals add column by_territory text;
