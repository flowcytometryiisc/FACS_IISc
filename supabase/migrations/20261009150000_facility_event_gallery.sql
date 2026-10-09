set search_path = public, extensions;

create table if not exists public.facility_gallery_items (
    id text primary key,
    description text not null check (length(trim(description)) between 1 and 240),
    image_path text not null,
    created_at text not null,
    updated_at text not null
);

alter table public.facility_gallery_items enable row level security;
revoke all on public.facility_gallery_items from anon, authenticated;
grant all on public.facility_gallery_items to service_role;
