set search_path = public, extensions;

alter table public.bookings
    drop constraint if exists bookings_status_check;
alter table public.bookings
    add constraint bookings_status_check
    check (status in ('pending', 'confirmed', 'cancelled'));

alter table public.booking_sessions
    drop constraint if exists booking_sessions_status_check;
alter table public.booking_sessions
    add constraint booking_sessions_status_check
    check (status in ('pending', 'confirmed', 'cancelled'));

alter table public.booking_sessions
    drop constraint if exists booking_sessions_no_overlap;
alter table public.booking_sessions
    add constraint booking_sessions_no_overlap
    exclude using gist (
        instrument_name with =,
        tstzrange(starts_at, ends_at, '[)') with &&
    )
    where (status in ('pending', 'confirmed'));
