-- docs/control_tower_schema.sql
-- Control-tower tables. Run once in the Supabase SQL editor (same project the
-- site already uses — the one holding ondemand_queue). RLS on + zero policies
-- = service-role access only, same posture as ondemand_queue.sql.

create table if not exists control_heartbeat (
  id         text primary key,
  payload    jsonb not null,
  updated_at timestamptz not null default now()
);

create table if not exists control_commands (
  id          bigint generated always as identity primary key,
  command     text not null,
  args        jsonb not null default '{}'::jsonb,
  status      text not null default 'pending',  -- pending | running | done | error
  result      text,
  created_at  timestamptz not null default now(),
  executed_at timestamptz
);

alter table control_heartbeat enable row level security;
alter table control_commands  enable row level security;
revoke all on control_heartbeat from anon, authenticated;
revoke all on control_commands  from anon, authenticated;
