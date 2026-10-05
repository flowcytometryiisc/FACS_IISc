set search_path = public, extensions;

create table if not exists public.facility_events (
    id text primary key,
    category text not null check (category in ('workshop', 'event')),
    title text not null check (length(trim(title)) between 1 and 120),
    start_date text not null,
    end_date text not null,
    summary text not null check (length(trim(summary)) between 1 and 240),
    description text not null check (length(trim(description)) between 1 and 2000),
    link_label text not null check (length(trim(link_label)) between 1 and 80),
    link_url text not null check (length(trim(link_url)) between 1 and 2048),
    created_at text not null,
    updated_at text not null,
    check (start_date <= end_date)
);

create index if not exists facility_events_date_idx
    on public.facility_events (start_date, end_date);

alter table public.facility_events enable row level security;
revoke all on public.facility_events from anon, authenticated;
grant all on public.facility_events to service_role;
