create schema if not exists extensions;
create extension if not exists btree_gist with schema extensions;
set search_path = public, extensions;

create table if not exists public.instruments (
    name text primary key,
    color text not null,
    color_code text not null,
    active boolean not null default true,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

insert into public.instruments (name, color, color_code)
values
    ('CytoFLEX LX', 'purple', '#8B5CF6'),
    ('Discover S8 Spectral Flow Cytometer', 'teal', '#0891B2'),
    ('Symphony A1', 'blue', '#2878D0'),
    ('FACSAria™ Fusion', 'gray', '#7B8490')
on conflict (name) do update
set color = excluded.color,
    color_code = excluded.color_code,
    updated_at = now();

create table if not exists public.bookings (
    id text primary key,
    created_at text not null,
    user_name text not null check (length(user_name) between 1 and 120),
    pi_name text not null check (length(pi_name) between 1 and 120),
    phone text not null check (length(phone) between 1 and 24),
    email text not null check (length(email) between 1 and 254),
    department text not null check (length(department) <= 160),
    specimen text not null check (length(specimen) between 1 and 80),
    notes text not null check (length(notes) <= 1500),
    slots jsonb not null check (
        case
            when jsonb_typeof(slots) = 'array'
            then jsonb_array_length(slots) between 1 and 12
            else false
        end
    ),
    status text not null check (status in ('confirmed', 'cancelled')),
    form_name text not null check (length(form_name) between 1 and 255),
    form_path text not null unique
);

create index if not exists bookings_created_at_idx
    on public.bookings (created_at desc);
create index if not exists bookings_status_created_at_idx
    on public.bookings (status, created_at desc);

create table if not exists public.booking_sessions (
    id bigint generated always as identity primary key,
    booking_id text not null references public.bookings (id) on delete cascade,
    instrument_name text not null references public.instruments (name),
    session_date date not null,
    session_time text not null,
    starts_at timestamptz not null,
    ends_at timestamptz not null,
    status text not null check (status in ('confirmed', 'cancelled')),
    created_at timestamptz not null default now(),
    check (ends_at > starts_at),
    constraint booking_sessions_session_date_weekday_check
        check (extract(isodow from session_date) between 1 and 6)
);

create index if not exists booking_sessions_date_idx
    on public.booking_sessions (session_date, instrument_name);
create index if not exists booking_sessions_booking_id_idx
    on public.booking_sessions (booking_id);

alter table public.booking_sessions
    drop constraint if exists booking_sessions_no_overlap;
alter table public.booking_sessions
    add constraint booking_sessions_no_overlap
    exclude using gist (
        instrument_name with =,
        tstzrange(starts_at, ends_at, '[)') with &&
    )
    where (status = 'confirmed');

create or replace function public.sync_booking_sessions()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    delete from public.booking_sessions where booking_id = new.id;

    insert into public.booking_sessions (
        booking_id,
        instrument_name,
        session_date,
        session_time,
        starts_at,
        ends_at,
        status
    )
    select
        new.id,
        slot->>'instrument',
        (slot->>'date')::date,
        slot->>'time',
        ((slot->>'date')::date + split_part(slot->>'time', '-', 1)::time)
            at time zone 'Asia/Kolkata',
        ((slot->>'date')::date + split_part(slot->>'time', '-', 2)::time)
            at time zone 'Asia/Kolkata',
        new.status
    from jsonb_array_elements(new.slots) as entries(slot);

    return new;
end;
$$;
revoke all on function public.sync_booking_sessions() from public, anon, authenticated;

drop trigger if exists bookings_sync_sessions on public.bookings;
create trigger bookings_sync_sessions
after insert or update of slots, status on public.bookings
for each row execute function public.sync_booking_sessions();

create table if not exists public.booking_audit_log (
    id bigint generated always as identity primary key,
    booking_id text not null,
    action text not null check (action in ('created', 'updated', 'deleted')),
    previous_status text,
    new_status text,
    previous_slot_count integer,
    new_slot_count integer,
    actor text not null default 'system',
    happened_at timestamptz not null default now()
);

create index if not exists booking_audit_log_booking_happened_idx
    on public.booking_audit_log (booking_id, happened_at desc);
create index if not exists booking_audit_log_happened_idx
    on public.booking_audit_log (happened_at desc);

create or replace function public.audit_booking_changes()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    if tg_op = 'INSERT' then
        insert into public.booking_audit_log (
            booking_id, action, new_status, new_slot_count, actor
        )
        values (
            new.id, 'created', new.status, jsonb_array_length(new.slots),
            coalesce(nullif(current_setting('app.actor', true), ''), 'system')
        );
        return new;
    elsif tg_op = 'UPDATE' then
        insert into public.booking_audit_log (
            booking_id, action, previous_status, new_status,
            previous_slot_count, new_slot_count, actor
        )
        values (
            new.id, 'updated', old.status, new.status,
            jsonb_array_length(old.slots), jsonb_array_length(new.slots),
            coalesce(nullif(current_setting('app.actor', true), ''), 'system')
        );
        return new;
    else
        insert into public.booking_audit_log (
            booking_id, action, previous_status, previous_slot_count, actor
        )
        values (
            old.id, 'deleted', old.status, jsonb_array_length(old.slots),
            coalesce(nullif(current_setting('app.actor', true), ''), 'system')
        );
        return old;
    end if;
end;
$$;
revoke all on function public.audit_booking_changes() from public, anon, authenticated;

drop trigger if exists bookings_audit_changes on public.bookings;
create trigger bookings_audit_changes
after insert or update or delete on public.bookings
for each row execute function public.audit_booking_changes();

alter table public.instruments enable row level security;
alter table public.bookings enable row level security;
alter table public.booking_sessions enable row level security;
alter table public.booking_audit_log enable row level security;

revoke all on public.instruments, public.bookings,
    public.booking_sessions, public.booking_audit_log
    from anon, authenticated;
grant all on public.instruments, public.bookings,
    public.booking_sessions, public.booking_audit_log
    to service_role;
grant usage, select on sequence
    public.booking_sessions_id_seq,
    public.booking_audit_log_id_seq
    to service_role;

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('booking-forms', 'booking-forms', false, 10485760, array['application/pdf'])
on conflict (id) do update
set public = false,
    file_size_limit = 10485760,
    allowed_mime_types = array['application/pdf'];

drop policy if exists "Server can manage facility booking forms"
    on storage.objects;
create policy "Server can manage facility booking forms"
    on storage.objects
    for all
    to service_role
    using (bucket_id = 'booking-forms')
    with check (bucket_id = 'booking-forms');
