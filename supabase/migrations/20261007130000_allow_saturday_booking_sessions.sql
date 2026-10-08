set search_path = public, extensions;

do $$
declare
    weekday_constraint record;
begin
    for weekday_constraint in
        select conname
        from pg_constraint
        where conrelid = 'public.booking_sessions'::regclass
          and contype = 'c'
          and pg_get_constraintdef(oid) ilike '%isodow%'
          and pg_get_constraintdef(oid) ilike '%session_date%'
    loop
        execute format(
            'alter table public.booking_sessions drop constraint %I',
            weekday_constraint.conname
        );
    end loop;
end;
$$;

alter table public.booking_sessions
    add constraint booking_sessions_session_date_weekday_check
    check (extract(isodow from session_date) between 1 and 6);
