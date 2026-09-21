-- ondemand_queue.sql — paste ONCE into the Supabase SQL editor (operator step).
--
-- On-demand analysis queue: the site's /ondemand "Analyze" button writes here
-- (via the password-gated /api/ondemand route, service key), and the operator's
-- PC (telegram_status_bot.py's web bridge) drains it. The PC has no inbound
-- connectivity, so this table IS the inbound channel.

create table if not exists public.ondemand_queue (
    id           bigint generated always as identity primary key,
    ticker       text        not null,
    status       text        not null default 'pending',
    message      text,
    source       text        not null default 'web',
    requested_at timestamptz not null default now(),
    handled_at   timestamptz,
    constraint ondemand_queue_status_chk
        check (status in ('pending', 'claimed', 'handled', 'failed'))
);

-- The bridge's only read: pending rows, oldest first.
create index if not exists ondemand_queue_pending_idx
    on public.ondemand_queue (requested_at)
    where status = 'pending';

-- One PENDING request per ticker, enforced in the DB so two browser tabs cannot
-- race past the API route's check (route maps error 23505 to the friendly
-- "already queued" message). Pending only: a crash-stuck 'claimed' row must
-- never block re-submission.
create unique index if not exists ondemand_queue_one_pending_per_ticker
    on public.ondemand_queue (ticker)
    where status = 'pending';

-- RLS on with NO policies: anon and authenticated read/write NOTHING. The
-- service key (Next.js API route + the PC bridge) bypasses RLS. Nothing else
-- touches this table, so there is no policy to get wrong — and the bridge's
-- replies (which can reference local machine state) are never anon-readable.
alter table public.ondemand_queue enable row level security;
revoke all on public.ondemand_queue from anon, authenticated;
