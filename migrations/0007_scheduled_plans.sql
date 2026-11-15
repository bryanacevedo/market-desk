-- A plan activated before its start date waits as `scheduled` and applies on that date (Backlog bl_134, decision 55).
-- Its owners are not anyone's yet: everything that reads "the active plan" keeps meaning the plan in effect today.
alter table territory_plans drop constraint territory_plans_status_check;
alter table territory_plans add constraint territory_plans_status_check check (status in ('draft', 'active', 'scheduled', 'retired'));
create unique index one_scheduled_plan on territory_plans ((true)) where status = 'scheduled';

create or replace function plan_two_people() returns trigger language plpgsql as $$
begin
  if new.status in ('active', 'scheduled') and new.activated_by is not null and new.activated_by = new.author then
    raise exception 'A plan is activated by someone other than its author';
  end if;
  if new.status in ('active', 'scheduled') and new.activated_by is not null
     and (select role from users where id = new.activated_by) <> 'manager' then
    raise exception 'Only a manager activates a plan';
  end if;
  return new;
end $$;
