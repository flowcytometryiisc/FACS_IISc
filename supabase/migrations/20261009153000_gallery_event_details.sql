set search_path = public, extensions;

alter table public.facility_gallery_items
    add column if not exists event_name text not null default 'Event photo',
    add column if not exists event_date text;
