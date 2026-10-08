set search_path = public, extensions;

alter table public.facility_events
    add column if not exists image_path text;

create table if not exists public.facility_workshop_archive (
    id text primary key,
    summary text not null check (length(trim(summary)) between 1 and 240),
    image_path text,
    updated_at text not null
);

insert into public.facility_workshop_archive (id, summary, image_path, updated_at)
values (
    'past-workshop',
    'Two days of sessions exploring fundamental principles and dynamic applications of flow cytometry, including immunophenotyping, with an in-depth look at the Beckman Coulter CytoFLEX LX Flow Cytometer.',
    null,
    now()::text
)
on conflict (id) do nothing;

alter table public.facility_workshop_archive enable row level security;
revoke all on public.facility_workshop_archive from anon, authenticated;
grant all on public.facility_workshop_archive to service_role;

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
    'workshop-images',
    'workshop-images',
    false,
    5242880,
    array['image/jpeg', 'image/png', 'image/webp']
)
on conflict (id) do update
set public = false,
    file_size_limit = 5242880,
    allowed_mime_types = array['image/jpeg', 'image/png', 'image/webp'];
