set search_path = public, extensions;

create table if not exists public.calendar_closures (
    id text primary key,
    kind text not null check (kind in ('exception', 'workshop')),
    start_date text not null,
    end_date text not null,
    slot_times jsonb not null default '[]'::jsonb,
    remark text not null,
    created_at text not null,
    check (start_date <= end_date),
    check (length(trim(remark)) between 1 and 500)
);

create index if not exists calendar_closures_date_range_idx
    on public.calendar_closures (start_date, end_date);

alter table public.calendar_closures enable row level security;
revoke all on public.calendar_closures from anon, authenticated;
grant all on public.calendar_closures to service_role;
